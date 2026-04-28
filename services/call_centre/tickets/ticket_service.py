"""
Enhanced ticket management for PDS Call Centre.

Extends shared/services/call_centre.py with:
  - ML-informed priority scoring
  - SLA breach detection
  - Auto-escalation for critical tickets
  - Notification simulation (email / SMS)
  - Agent assignment with round-robin load balancing
  - Ticket analytics for dashboard
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# ── Agent pool ─────────────────────────────────────────────────────────────────

_AGENTS = [
    {"id": "AGT-001", "name": "Priya Sharma",   "team": "District Supply Team",       "active_tickets": 0},
    {"id": "AGT-002", "name": "Ravi Kumar",      "team": "Logistics Control Room",     "active_tickets": 0},
    {"id": "AGT-003", "name": "Anitha Reddy",    "team": "Citizen Records Team",       "active_tickets": 0},
    {"id": "AGT-004", "name": "Suresh Babu",     "team": "Vigilance & Enforcement",    "active_tickets": 0},
    {"id": "AGT-005", "name": "Lakshmi Devi",    "team": "Citizen Help Desk",          "active_tickets": 0},
    {"id": "AGT-006", "name": "Venkat Rao",      "team": "District Supply Team",       "active_tickets": 0},
]

_TEAM_AGENTS: dict[str, list[str]] = {}
for _a in _AGENTS:
    _TEAM_AGENTS.setdefault(_a["team"], []).append(_a["id"])

_agent_rr_index: dict[str, int] = {}  # round-robin per team


def assign_agent(team: str) -> dict:
    """Round-robin assign an agent from the given team."""
    agents_in_team = [a for a in _AGENTS if a["team"] == team]
    if not agents_in_team:
        return _AGENTS[4]   # fallback: help desk
    idx = _agent_rr_index.get(team, 0) % len(agents_in_team)
    _agent_rr_index[team] = idx + 1
    agent = agents_in_team[idx]
    agent["active_tickets"] += 1
    return agent


# ── Notification simulation ────────────────────────────────────────────────────

_NOTIFICATION_LOG: list[dict] = []


def _send_notification(
    channel: str,          # "email" | "sms"
    recipient: str,
    subject: str,
    body: str,
    ticket_id: str,
) -> dict:
    """Simulate sending an email or SMS. Logs the notification."""
    record = {
        "id":         str(uuid4())[:8].upper(),
        "channel":    channel,
        "recipient":  recipient,
        "subject":    subject,
        "body":       body[:200],
        "ticket_id":  ticket_id,
        "sent_at":    datetime.utcnow().isoformat(),
        "status":     "delivered",   # simulation always succeeds
    }
    _NOTIFICATION_LOG.append(record)
    log.info("NOTIFY [%s] %s → %s | ticket=%s", channel.upper(), subject, recipient, ticket_id)
    return record


def send_ticket_created(ticket_id: str, caller_name: str, category: str, priority: str, eta_hours: int) -> list[dict]:
    """Send creation notification to caller + duty officer."""
    notes = []
    notes.append(_send_notification(
        "sms", f"+91-XXXXXXXXXX ({caller_name})",
        f"PDS360: Ticket {ticket_id} Created",
        f"Your complaint has been registered as {ticket_id}. Category: {category}. "
        f"Expected resolution: {eta_hours} hours.",
        ticket_id,
    ))
    if priority == "HIGH":
        notes.append(_send_notification(
            "email", "duty.officer@pds360.gov.in",
            f"[HIGH PRIORITY] New Ticket: {ticket_id}",
            f"Caller: {caller_name}\nCategory: {category}\nPriority: HIGH\n"
            f"Immediate action required. ETA: {eta_hours} hours.",
            ticket_id,
        ))
    return notes


def send_escalation_alert(ticket_id: str, reason: str, sentiment_score: float) -> dict:
    """Send escalation alert for critical/distressed tickets."""
    return _send_notification(
        "email", "supervisor@pds360.gov.in",
        f"[ESCALATION ALERT] Ticket {ticket_id} — Immediate Action Required",
        f"Ticket {ticket_id} has been escalated.\n"
        f"Reason: {reason}\nSentiment score: {sentiment_score:.2f}\n"
        f"Please assign a senior officer immediately.",
        ticket_id,
    )


def send_resolution_notification(ticket_id: str, caller_name: str) -> dict:
    """Notify caller when ticket is resolved."""
    return _send_notification(
        "sms", f"+91-XXXXXXXXXX ({caller_name})",
        f"PDS360: Ticket {ticket_id} Resolved",
        f"Your complaint {ticket_id} has been resolved. "
        f"Please call us if the issue persists.",
        ticket_id,
    )


def get_notification_log(limit: int = 50) -> list[dict]:
    return list(reversed(_NOTIFICATION_LOG))[:limit]


# ── Priority scoring ───────────────────────────────────────────────────────────

def compute_priority(sentiment_score: float, category: str) -> str:
    """
    HIGH   : distressed sentiment OR fraud/grievance
    MEDIUM : negative sentiment OR supply/entitlement issues
    LOW    : neutral/positive sentiment, general queries
    """
    if sentiment_score <= -0.55:
        return "HIGH"
    if category == "Grievance / Fraud":
        return "HIGH"
    if sentiment_score <= -0.25 or category in ("Supply Delay", "Entitlement Verification"):
        return "MEDIUM"
    return "LOW"


# ── SLA breach detection ───────────────────────────────────────────────────────

def check_sla_breaches(db: Session) -> list[dict]:
    """Return tickets that have breached their SLA (past ETA without resolution)."""
    try:
        from shared.models import GrievanceTicket
        now = datetime.utcnow()
        open_tickets = (
            db.query(GrievanceTicket)
            .filter(GrievanceTicket.status.in_(["OPEN", "IN_PROGRESS"]))
            .all()
        )
        breaches = []
        for t in open_tickets:
            if not t.created_at:
                continue
            eta = timedelta(hours=t.resolution_eta_hours or 12)
            deadline = t.created_at + eta
            if now > deadline:
                overdue_hours = (now - deadline).total_seconds() / 3600
                breaches.append({
                    "ticket_id":     t.ticket_id,
                    "category":      t.category,
                    "priority":      t.priority,
                    "status":        t.status,
                    "created_at":    t.created_at.isoformat(),
                    "sla_deadline":  deadline.isoformat(),
                    "overdue_hours": round(overdue_hours, 1),
                    "caller_name":   t.caller_name,
                })
        return sorted(breaches, key=lambda x: x["overdue_hours"], reverse=True)
    except Exception as exc:
        log.error("SLA check failed: %s", exc)
        return []


# ── Ticket creation ────────────────────────────────────────────────────────────

def create_ticket(
    db: Session,
    *,
    transcript: str,
    sentiment_score: float,
    sentiment_label: str,
    category: str,
    caller_name: str = "Unknown",
    caller_type: str = "public",
    language: str = "English",
    channel: str = "web",
    district: str = "",
    fps_reference: str = "",
) -> dict:
    """
    Create a ticket with ML-informed priority, agent assignment, and notifications.
    Returns a dict with ticket + agent + notifications.
    """
    from shared.models import GrievanceTicket
    from shared.services.call_centre import (
        assigned_team, next_action, resolution_eta, summarize_transcript
    )

    ticket_id = f"TKT-{str(uuid4())[:8].upper()}"
    priority  = compute_priority(sentiment_score, category)
    team      = assigned_team(category)
    eta       = resolution_eta(priority, category)
    agent     = assign_agent(team)
    summary   = summarize_transcript(transcript, category)
    action    = next_action(category, priority)

    db_ticket = GrievanceTicket(
        ticket_id=ticket_id,
        source_channel=channel,
        caller_name=caller_name,
        caller_type=caller_type,
        language=language,
        category=category,
        priority=priority,
        sentiment_score=sentiment_score,
        sentiment_label=sentiment_label,
        transcript=transcript,
        summary=summary,
        assigned_team=team,
        next_action=action,
        resolution_eta_hours=eta,
        status="OPEN",
        district_name=district or None,
        fps_reference=fps_reference or None,
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)

    # Notifications
    notifications = send_ticket_created(ticket_id, caller_name, category, priority, eta)

    # Auto-escalate distressed tickets
    escalation = None
    if sentiment_score <= -0.55:
        escalation = send_escalation_alert(
            ticket_id,
            f"Caller is distressed (sentiment={sentiment_score:.2f})",
            sentiment_score,
        )

    log.info("Ticket created: %s | priority=%s | team=%s | agent=%s",
             ticket_id, priority, team, agent["name"])

    return {
        "ticket_id":       ticket_id,
        "category":        category,
        "priority":        priority,
        "status":          "OPEN",
        "assigned_team":   team,
        "assigned_agent":  agent,
        "eta_hours":       eta,
        "summary":         summary,
        "next_action":     action,
        "notifications":   notifications,
        "escalated":       escalation is not None,
        "created_at":      db_ticket.created_at.isoformat() if db_ticket.created_at else None,
    }


# ── Agent performance scoring ──────────────────────────────────────────────────

def get_agent_performance(db: Session) -> list[dict]:
    """
    Score each agent based on resolution rate, SLA compliance, and sentiment improvement.
    Simulated scoring based on ticket distribution.
    """
    from shared.models import GrievanceTicket
    tickets = db.query(GrievanceTicket).all()
    resolved = [t for t in tickets if t.status == "RESOLVED"]
    total    = max(len(tickets), 1)

    scores = []
    for a in _AGENTS:
        team_tickets  = [t for t in tickets   if t.assigned_team == a["team"]]
        team_resolved = [t for t in team_tickets if t.status == "RESOLVED"]
        n_team = max(len(team_tickets), 1)

        resolution_rate = len(team_resolved) / n_team * 100
        avg_sentiment   = sum(t.sentiment_score for t in team_resolved) / max(len(team_resolved), 1)
        sla_violations  = sum(
            1 for t in team_tickets
            if t.created_at and (
                datetime.utcnow() - t.created_at > timedelta(hours=t.resolution_eta_hours or 12)
                and t.status not in ("RESOLVED", "CLOSED")
            )
        )
        # Composite score: 0-100
        perf_score = min(100, max(0, round(
            resolution_rate * 0.5
            + min(100, (avg_sentiment + 1) * 50) * 0.3
            + max(0, 100 - sla_violations * 20) * 0.2,
            1
        )))

        scores.append({
            "agent_id":        a["id"],
            "agent_name":      a["name"],
            "team":            a["team"],
            "total_tickets":   len(team_tickets),
            "resolved":        len(team_resolved),
            "resolution_rate": round(resolution_rate, 1),
            "avg_sentiment":   round(avg_sentiment, 2),
            "sla_violations":  sla_violations,
            "performance_score": perf_score,
            "grade": "A" if perf_score >= 80 else "B" if perf_score >= 60 else "C",
        })

    return sorted(scores, key=lambda x: x["performance_score"], reverse=True)
