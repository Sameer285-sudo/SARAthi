"""
Performance metrics engine for PDS Call Centre analytics dashboard.

Returns chart-ready JSON dicts for each analytics endpoint.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _all_tickets(db, user=None):
    from shared.models import GrievanceTicket
    from shared.auth.scope import scope_for_tickets
    q = db.query(GrievanceTicket)
    for col, val in scope_for_tickets(user).items():
        q = q.filter(getattr(GrievanceTicket, col) == val)
    return q.order_by(GrievanceTicket.created_at.asc()).all()


def _all_sessions(db):
    from shared.models import CallSession
    return db.query(CallSession).all()


def _label_from_score(score: float) -> str:
    if score <= -0.55: return "Distressed"
    if score <= -0.25: return "Negative"
    if score <  0.20:  return "Neutral"
    return "Positive"


_LABEL_COLOR = {
    "Distressed": "#ef4444",
    "Negative":   "#f59e0b",
    "Neutral":    "#6b7280",
    "Positive":   "#10b981",
}

_PRIORITY_COLOR = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#10b981"}
_STATUS_COLOR   = {"OPEN": "#6366f1", "IN_PROGRESS": "#f59e0b", "RESOLVED": "#10b981", "CLOSED": "#6b7280"}


# ── Overview metrics ───────────────────────────────────────────────────────────

def get_overview(db, user=None) -> dict:
    """
    Combined KPI overview for the main analytics dashboard card.
    """
    tickets  = _all_tickets(db, user)
    sessions = _all_sessions(db)
    total    = len(tickets)
    resolved = sum(1 for t in tickets if t.status == "RESOLVED")
    open_t   = sum(1 for t in tickets if t.status == "OPEN")
    high_pri = sum(1 for t in tickets if t.priority == "HIGH")
    today    = datetime.utcnow().date()

    today_tickets = sum(
        1 for t in tickets
        if t.created_at and t.created_at.date() == today
    )
    avg_sentiment = sum(t.sentiment_score for t in tickets) / max(total, 1)
    resolution_rate = resolved / max(total, 1) * 100

    # Avg response time: based on priority mix
    high_count = sum(1 for t in tickets if t.priority == "HIGH")
    med_count  = sum(1 for t in tickets if t.priority == "MEDIUM")
    low_count  = total - high_count - med_count
    avg_eta    = (high_count * 4 + med_count * 8 + low_count * 12) / max(total, 1)

    cat_ctr   = Counter(t.category for t in tickets)
    lang_ctr  = Counter(t.language for t in tickets)
    sent_dist = Counter(_label_from_score(t.sentiment_score) for t in tickets)

    return {
        "module": "Call Centre Analytics",
        "kpis": {
            "total_tickets":          total,
            "open_tickets":           open_t,
            "resolved_tickets":       resolved,
            "high_priority":          high_pri,
            "today_tickets":          today_tickets,
            "total_sessions":         len(sessions),
            "resolution_rate_pct":    round(resolution_rate, 1),
            "avg_response_time_min":  round(avg_eta * 60 / max(total, 1), 1),
            "avg_sentiment_score":    round(avg_sentiment, 2),
            "avg_sentiment_label":    _label_from_score(avg_sentiment),
        },
        "top_categories": [
            {"name": name, "count": count}
            for name, count in cat_ctr.most_common(5)
        ],
        "language_distribution": dict(lang_ctr),
        "sentiment_distribution": {
            "labels": list(sent_dist.keys()),
            "data":   list(sent_dist.values()),
            "colors": [_LABEL_COLOR.get(k, "#6b7280") for k in sent_dist.keys()],
        },
        "priority_distribution": {
            "labels": ["HIGH", "MEDIUM", "LOW"],
            "data":   [high_count, med_count, low_count],
            "colors": [_PRIORITY_COLOR["HIGH"], _PRIORITY_COLOR["MEDIUM"], _PRIORITY_COLOR["LOW"]],
        },
    }


# ── Sentiment analytics ────────────────────────────────────────────────────────

def get_sentiment_analytics(db, user=None) -> dict:
    """
    Sentiment trend over last 30 days + distribution breakdown.
    Returns chart-ready JSON.
    """
    tickets = _all_tickets(db, user)
    today   = datetime.utcnow().date()

    # Daily sentiment average — last 30 days
    daily: dict[str, list[float]] = defaultdict(list)
    for t in tickets:
        if t.created_at:
            day = t.created_at.date().isoformat()
            daily[day].append(t.sentiment_score)

    trend_labels, trend_scores, trend_labels_ui = [], [], []
    for i in range(30):
        d = (today - timedelta(days=29 - i)).isoformat()
        trend_labels.append(d)
        trend_labels_ui.append((today - timedelta(days=29 - i)).strftime("%d %b"))
        scores = daily.get(d, [])
        trend_scores.append(round(sum(scores) / max(len(scores), 1), 2) if scores else None)

    # Label distribution
    sent_dist = Counter(_label_from_score(t.sentiment_score) for t in tickets)
    all_labels = ["Distressed", "Negative", "Neutral", "Positive"]

    # Sentiment by category
    cat_sentiment: dict[str, list[float]] = defaultdict(list)
    for t in tickets:
        cat_sentiment[t.category].append(t.sentiment_score)
    cat_avg = {
        cat: round(sum(scores) / max(len(scores), 1), 2)
        for cat, scores in cat_sentiment.items()
    }

    avg_overall = sum(t.sentiment_score for t in tickets) / max(len(tickets), 1)

    return {
        "module": "Call Centre Analytics",
        "trend": {
            "labels":  trend_labels_ui,
            "datasets": [
                {"label": "Avg Sentiment Score", "data": trend_scores, "color": "#6366f1"}
            ],
        },
        "distribution": {
            "labels": all_labels,
            "data":   [sent_dist.get(l, 0) for l in all_labels],
            "colors": [_LABEL_COLOR[l] for l in all_labels],
        },
        "by_category": cat_avg,
        "summary": {
            "avg_score":   round(avg_overall, 2),
            "avg_label":   _label_from_score(avg_overall),
            "distressed":  sent_dist.get("Distressed", 0),
            "negative":    sent_dist.get("Negative", 0),
            "neutral":     sent_dist.get("Neutral", 0),
            "positive":    sent_dist.get("Positive", 0),
            "pct_negative": round(
                (sent_dist.get("Distressed", 0) + sent_dist.get("Negative", 0))
                / max(len(tickets), 1) * 100, 1
            ),
        },
    }


# ── Ticket analytics ──────────────────────────────────────────────────────────

def get_ticket_analytics(db, user=None) -> dict:
    """
    Ticket breakdown by category, priority, status + resolution trend.
    """
    tickets = _all_tickets(db, user)
    today   = datetime.utcnow().date()

    cat_ctr  = Counter(t.category for t in tickets)
    pri_ctr  = Counter(t.priority for t in tickets)
    stat_ctr = Counter(t.status   for t in tickets)

    # Daily ticket creation trend — last 14 days
    daily_counts: dict[str, int] = defaultdict(int)
    for t in tickets:
        if t.created_at:
            daily_counts[t.created_at.date().isoformat()] += 1

    trend_labels = [(today - timedelta(days=13 - i)).strftime("%d %b") for i in range(14)]
    trend_data   = [
        daily_counts.get((today - timedelta(days=13 - i)).isoformat(), 0)
        for i in range(14)
    ]

    # Resolution time distribution (simulated SLA bands)
    resolved = [t for t in tickets if t.status == "RESOLVED"]
    within_4h  = sum(1 for t in resolved if t.resolution_eta_hours <= 4)
    within_8h  = sum(1 for t in resolved if 4 < t.resolution_eta_hours <= 8)
    within_12h = sum(1 for t in resolved if t.resolution_eta_hours > 8)

    # Ticket open/close rate — last 7 days
    open_trend  = []
    close_trend = []
    for i in range(7):
        d = (today - timedelta(days=6 - i)).isoformat()
        open_trend.append(sum(
            1 for t in tickets
            if t.created_at and t.created_at.date().isoformat() == d
        ))
        close_trend.append(sum(
            1 for t in tickets
            if t.status in ("RESOLVED", "CLOSED")
            and t.resolved_at and t.resolved_at.date().isoformat() == d
        ))
    week_labels = [(today - timedelta(days=6 - i)).strftime("%d %b") for i in range(7)]

    return {
        "module": "Call Centre Analytics",
        "by_category": {
            "labels": list(cat_ctr.keys()),
            "data":   list(cat_ctr.values()),
            "colors": ["#185c73", "#f59e0b", "#10b981", "#ef4444", "#6366f1"],
        },
        "by_priority": {
            "labels": ["HIGH", "MEDIUM", "LOW"],
            "data":   [pri_ctr.get("HIGH", 0), pri_ctr.get("MEDIUM", 0), pri_ctr.get("LOW", 0)],
            "colors": [_PRIORITY_COLOR["HIGH"], _PRIORITY_COLOR["MEDIUM"], _PRIORITY_COLOR["LOW"]],
        },
        "by_status": {
            "labels": ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"],
            "data":   [stat_ctr.get(s, 0) for s in ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]],
            "colors": [_STATUS_COLOR[s] for s in ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]],
        },
        "resolution_sla": {
            "labels": ["≤ 4 hours", "4–8 hours", "> 8 hours"],
            "data":   [within_4h, within_8h, within_12h],
            "colors": ["#10b981", "#f59e0b", "#ef4444"],
        },
        "creation_trend": {
            "labels":   trend_labels,
            "datasets": [{"label": "New Tickets", "data": trend_data, "color": "#185c73"}],
        },
        "open_vs_close": {
            "labels": week_labels,
            "datasets": [
                {"label": "Opened",   "data": open_trend,  "color": "#ef4444"},
                {"label": "Resolved", "data": close_trend, "color": "#10b981"},
            ],
        },
        "summary": {
            "total":          len(tickets),
            "open":           stat_ctr.get("OPEN", 0),
            "in_progress":    stat_ctr.get("IN_PROGRESS", 0),
            "resolved":       stat_ctr.get("RESOLVED", 0),
            "resolution_rate": round(stat_ctr.get("RESOLVED", 0) / max(len(tickets), 1) * 100, 1),
        },
    }
