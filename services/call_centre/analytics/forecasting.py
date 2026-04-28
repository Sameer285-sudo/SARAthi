"""
Call volume and complaint trend forecasting for the PDS Call Centre.

Uses sklearn LinearRegression on historical ticket counts (by date).
Falls back to moving-average heuristic when insufficient data exists.

Public API
----------
get_call_volume_forecast(db) -> dict   — chart-ready JSON for frontend
get_peak_hour_distribution(db) -> dict — 24-hour call distribution
get_complaint_trends(db) -> dict       — category trends over last 30 days
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

_HOUR_WEIGHTS = [
    0.8, 0.4, 0.2, 0.2, 0.3, 0.6,   # 00-05 (night → early morning)
    1.2, 2.5, 3.8, 4.5, 4.2, 3.9,   # 06-11 (morning ramp-up, 09:00 peak)
    3.2, 2.8, 2.9, 3.0, 3.5, 3.8,   # 12-17 (midday dip, afternoon rise)
    3.1, 2.4, 1.9, 1.5, 1.2, 1.0,   # 18-23 (evening decline)
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _date_series(db) -> dict[str, int]:
    """Count tickets created per calendar date, last 60 days."""
    from shared.models import GrievanceTicket
    cutoff = datetime.utcnow() - timedelta(days=60)
    tickets = (
        db.query(GrievanceTicket)
        .filter(GrievanceTicket.created_at >= cutoff)
        .all()
    )
    counts: dict[str, int] = defaultdict(int)
    for t in tickets:
        if t.created_at:
            counts[t.created_at.date().isoformat()] += 1
    return dict(counts)


def _linear_forecast(counts_by_date: dict[str, int], n_days: int = 7) -> list[int]:
    """LinearRegression forecast for the next n_days, fallback to moving average."""
    sorted_dates = sorted(counts_by_date)
    values       = [counts_by_date[d] for d in sorted_dates]

    if len(values) < 4:
        # Not enough history → use moving average of last 3 or all available
        avg = sum(values[-3:]) / max(len(values[-3:]), 1)
        return [max(0, round(avg + i * 0.5)) for i in range(n_days)]

    try:
        import numpy as np
        from sklearn.linear_model import LinearRegression

        X = np.arange(len(values)).reshape(-1, 1)
        y = np.array(values, dtype=float)
        model = LinearRegression().fit(X, y)
        future_X = np.arange(len(values), len(values) + n_days).reshape(-1, 1)
        preds = model.predict(future_X).tolist()
        return [max(0, round(p)) for p in preds]
    except ImportError:
        avg = sum(values) / len(values)
        return [max(0, round(avg)) for _ in range(n_days)]


# ── Public functions ───────────────────────────────────────────────────────────

def get_call_volume_forecast(db) -> dict:
    """
    Returns historical (last 14 days) + forecasted (next 7 days) call volumes
    in chart.js-compatible format.
    """
    counts = _date_series(db)
    today  = datetime.utcnow().date()

    # Historical: last 14 days
    hist_dates  = [(today - timedelta(days=13 - i)).isoformat() for i in range(14)]
    hist_values = [counts.get(d, 0) for d in hist_dates]
    hist_labels = [(today - timedelta(days=13 - i)).strftime("%d %b") for i in range(14)]

    # Forecast: next 7 days
    forecast_values = _linear_forecast(counts, n_days=7)
    forecast_dates  = [(today + timedelta(days=i + 1)).isoformat() for i in range(7)]
    forecast_labels = [(today + timedelta(days=i + 1)).strftime("%d %b") for i in range(7)]

    all_labels = hist_labels + forecast_labels
    all_hist   = hist_values + [None] * 7
    all_fore   = [None] * 14 + forecast_values

    next_day = forecast_values[0] if forecast_values else 0
    avg_last7 = sum(hist_values[-7:]) / max(len(hist_values[-7:]), 1)

    return {
        "module": "Call Centre Analytics",
        "labels": all_labels,
        "datasets": [
            {"label": "Historical Calls", "data": all_hist,  "color": "#185c73", "borderDash": []},
            {"label": "Forecast",          "data": all_fore,  "color": "#f59e0b", "borderDash": [5, 5]},
        ],
        "summary": {
            "next_day_expected":    next_day,
            "avg_last_7_days":      round(avg_last7, 1),
            "total_last_14_days":   sum(hist_values),
            "trend":                "rising" if forecast_values and forecast_values[-1] > avg_last7 else "stable",
        },
        "forecast_dates": forecast_dates,
        "forecast_values": forecast_values,
    }


def get_peak_hour_distribution(db) -> dict:
    """
    Returns call distribution across 24 hours (0–23).
    Uses actual ticket created_at timestamps, supplemented with synthetic weights.
    """
    from shared.models import GrievanceTicket
    tickets = db.query(GrievanceTicket).all()

    hour_counts = [0] * 24
    for t in tickets:
        if t.created_at:
            hour_counts[t.created_at.hour] += 1

    # If all zeros (no data yet), use the synthetic weights
    if sum(hour_counts) == 0:
        total_sim = 100
        hour_counts = [round(w / sum(_HOUR_WEIGHTS) * total_sim) for w in _HOUR_WEIGHTS]

    peak_hour = hour_counts.index(max(hour_counts))
    labels    = [f"{h:02d}:00" for h in range(24)]

    return {
        "labels": labels,
        "datasets": [
            {"label": "Call Volume", "data": hour_counts, "color": "#6366f1"}
        ],
        "peak_hour":       f"{peak_hour:02d}:00",
        "peak_count":      hour_counts[peak_hour],
        "total_calls":     sum(hour_counts),
        "business_hours":  {"start": "09:00", "end": "18:00"},
        "off_hours_pct":   round(
            sum(hour_counts[h] for h in range(24) if h < 9 or h >= 18)
            / max(sum(hour_counts), 1) * 100, 1
        ),
    }


def get_complaint_trends(db) -> dict:
    """
    Returns category trends over the last 30 days as a stacked bar chart.
    """
    from shared.models import GrievanceTicket
    cutoff  = datetime.utcnow() - timedelta(days=30)
    tickets = db.query(GrievanceTicket).filter(GrievanceTicket.created_at >= cutoff).all()

    categories = [
        "Stock Availability", "Supply Delay",
        "Entitlement Verification", "Grievance / Fraud", "General Support",
    ]
    cat_colors = ["#185c73", "#f59e0b", "#10b981", "#ef4444", "#6366f1"]

    # Group by week (last 4 weeks)
    week_labels = []
    week_data: dict[str, list[int]] = {c: [] for c in categories}
    today = datetime.utcnow().date()

    for week_offset in range(4):
        w_end   = today - timedelta(weeks=week_offset)
        w_start = w_end - timedelta(days=6)
        week_labels.insert(0, f"{w_start.strftime('%d %b')} – {w_end.strftime('%d %b')}")
        for cat in categories:
            count = sum(
                1 for t in tickets
                if t.category == cat
                and t.created_at
                and w_start <= t.created_at.date() <= w_end
            )
            week_data[cat].insert(0, count)

    # Top complaint category
    cat_totals = Counter(t.category for t in tickets)
    top_category = cat_totals.most_common(1)[0][0] if cat_totals else "General Support"

    return {
        "labels": week_labels,
        "datasets": [
            {"label": cat, "data": week_data[cat], "color": cat_colors[i]}
            for i, cat in enumerate(categories)
        ],
        "summary": {
            "top_category":   top_category,
            "total_30_days":  len(tickets),
            "by_category":    dict(cat_totals),
        },
    }
