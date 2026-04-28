from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Session

from shared.models import CallSession, GrievanceTicket

if TYPE_CHECKING:
    from shared.auth.dependencies import CurrentUser

from shared.auth.scope import scope_for_tickets


def _scoped_tickets(db: Session, user: Optional["CurrentUser"]) -> list[GrievanceTicket]:
    q = db.query(GrievanceTicket)
    from shared.auth.scope import scope_for_tickets
    for col, val in scope_for_tickets(user).items():
        q = q.filter(getattr(GrievanceTicket, col) == val)
    return q.order_by(GrievanceTicket.created_at.desc()).all()
from shared.schemas import (
    CallCentreDashboard, CallCentreForecast, CallCentrePerformance,
    CallCentreSummary, CallCentreTicket, LiveMetrics,
)


def classify_issue(transcript: str) -> str:
    text = transcript.lower()
    if any(w in text for w in ["stock", "not available", "unavailable", "distribution", "rice", "wheat", "sugar"]):
        return "Stock Availability"
    if any(w in text for w in ["entitlement", "card", "ration card", "beneficiary", "record"]):
        return "Entitlement Verification"
    if any(w in text for w in ["dispatch", "delay", "late", "transit", "supply"]):
        return "Supply Delay"
    if any(w in text for w in ["complaint", "grievance", "report", "wrong", "fraud"]):
        return "Grievance / Fraud"
    return "General Support"


def sentiment_label(score: float) -> str:
    if score <= -0.55:
        return "Distressed"
    if score <= -0.25:
        return "Negative"
    if score < 0.2:
        return "Neutral"
    return "Positive"


def assigned_team(category: str) -> str:
    return {
        "Stock Availability": "District Supply Team",
        "Entitlement Verification": "Citizen Records Team",
        "Supply Delay": "Logistics Control Room",
        "Grievance / Fraud": "Vigilance & Enforcement",
        "General Support": "Citizen Help Desk",
    }.get(category, "Citizen Help Desk")


def resolution_eta(priority: str, category: str) -> int:
    if priority == "HIGH":
        return 4
    if category in ("Entitlement Verification", "Grievance / Fraud"):
        return 8
    return 12


def summarize_transcript(transcript: str, category: str) -> str:
    clean = transcript.strip()
    if len(clean) > 110:
        clean = clean[:107].rstrip() + "..."
    return f"{category}: {clean}"


def next_action(category: str, priority: str) -> str:
    if priority == "HIGH":
        return "Escalate to duty officer and create immediate follow-up task."
    return {
        "Entitlement Verification": "Verify beneficiary record and entitlement mapping in RCMS.",
        "Stock Availability": "Check district stock position and FPS replenishment status.",
        "Supply Delay": "Review dispatch timeline and contact logistics coordinator.",
        "Grievance / Fraud": "Forward to Vigilance team for investigation within 24 hours.",
    }.get(category, "Assign to help-desk queue and track response.")


def _ticket_to_schema(t: GrievanceTicket) -> CallCentreTicket:
    return CallCentreTicket(
        ticket_id=t.ticket_id, call_id=t.ticket_id,
        caller_name=t.caller_name, language=t.language,
        category=t.category, priority=t.priority,
        sentiment_score=t.sentiment_score, sentiment_label=t.sentiment_label,
        transcript=t.transcript, summary=t.summary,
        assigned_team=t.assigned_team, next_action=t.next_action,
        resolution_eta_hours=t.resolution_eta_hours,
        channel=t.source_channel, status=t.status,
        district_name=t.district_name, fps_reference=t.fps_reference,
        created_at=t.created_at.isoformat() if t.created_at else None,
    )


def get_tickets(db: Session, user: Optional["CurrentUser"] = None) -> list[CallCentreTicket]:
    return [_ticket_to_schema(t) for t in _scoped_tickets(db, user)]


def get_ticket_by_id(db: Session, ticket_id: str) -> GrievanceTicket | None:
    return db.query(GrievanceTicket).filter(GrievanceTicket.ticket_id == ticket_id).first()


def update_ticket_status(db: Session, ticket_id: str, status: str) -> GrievanceTicket | None:
    ticket = get_ticket_by_id(db, ticket_id)
    if not ticket:
        return None
    ticket.status = status
    ticket.updated_at = datetime.utcnow()
    if status == "RESOLVED":
        ticket.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    return ticket


def get_summary(db: Session, user: Optional["CurrentUser"] = None) -> CallCentreSummary:
    tickets = _scoped_tickets(db, user)
    sessions = db.query(CallSession).all()
    languages = sorted({t.language for t in tickets if t.language})
    return CallCentreSummary(
        total_calls=len(sessions),
        open_tickets=sum(1 for t in tickets if t.status == "OPEN"),
        high_priority_tickets=sum(1 for t in tickets if t.priority == "HIGH"),
        languages_covered=languages or ["English"],
    )


def get_dashboard(db: Session, user: Optional["CurrentUser"] = None) -> CallCentreDashboard:
    tickets = _scoped_tickets(db, user)
    sessions = db.query(CallSession).all()
    cat_ctr = Counter(t.category for t in tickets)
    lang_ctr = Counter(t.language for t in tickets)
    total = len(tickets)
    avg_sentiment = sum(t.sentiment_score for t in tickets) / max(total, 1)
    avg_eta = sum(t.resolution_eta_hours for t in tickets) / max(total, 1)
    high_priority = sum(1 for t in tickets if t.priority == "HIGH")
    resolved = sum(1 for t in tickets if t.status == "RESOLVED")
    resolution_rate = (resolved / max(total, 1)) * 100
    summary = CallCentreSummary(
        total_calls=len(sessions),
        open_tickets=sum(1 for t in tickets if t.status == "OPEN"),
        high_priority_tickets=high_priority,
        languages_covered=sorted({t.language for t in tickets if t.language}) or ["English"],
    )
    return CallCentreDashboard(
        summary=summary,
        forecast=CallCentreForecast(
            next_day_expected_calls=max(len(sessions) + 2, round(len(sessions) * 1.2)),
            predicted_peak_issue=cat_ctr.most_common(1)[0][0] if cat_ctr else "General Support",
            predicted_peak_language=lang_ctr.most_common(1)[0][0] if lang_ctr else "English",
        ),
        performance=CallCentrePerformance(
            average_sentiment_score=round(avg_sentiment, 2),
            average_resolution_eta_hours=round(avg_eta, 1),
            response_time_minutes=round(8 + high_priority * 1.5, 1),
            resolution_rate_percent=round(resolution_rate, 1),
        ),
        recurring_issues=[name for name, _ in cat_ctr.most_common(3)],
        multilingual_support=summary.languages_covered,
    )


def get_live_metrics(db: Session, user: Optional["CurrentUser"] = None) -> LiveMetrics:
    tickets = _scoped_tickets(db, user)
    sessions = db.query(CallSession).all()
    today = datetime.utcnow().date()
    resolved_today = sum(1 for t in tickets if t.status == "RESOLVED" and t.resolved_at and t.resolved_at.date() == today)
    active_sessions = sum(1 for s in sessions if s.current_state not in ("ended", "resolved"))
    avg_sentiment = sum(t.sentiment_score for t in tickets) / max(len(tickets), 1)
    recent = sorted(tickets, key=lambda t: t.created_at or datetime.min)[-7:]
    calls_by_lang: dict[str, int] = {}
    calls_by_cat: dict[str, int] = {}
    for t in tickets:
        calls_by_lang[t.language] = calls_by_lang.get(t.language, 0) + 1
        calls_by_cat[t.category] = calls_by_cat.get(t.category, 0) + 1
    return LiveMetrics(
        active_sessions=active_sessions,
        total_tickets=len(tickets),
        open_tickets=sum(1 for t in tickets if t.status == "OPEN"),
        resolved_today=resolved_today,
        avg_sentiment=round(avg_sentiment, 2),
        high_priority=sum(1 for t in tickets if t.priority == "HIGH"),
        calls_by_language=calls_by_lang,
        calls_by_category=calls_by_cat,
        sentiment_trend=[round(t.sentiment_score, 2) for t in recent],
    )
