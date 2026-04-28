"""
Chart data builders.

All functions return plain Python dicts/lists — no Matplotlib/Plotly objects.
The frontend (React / any chart library) consumes this JSON directly.

Optional: each function also accepts a `as_image=True` flag that returns
a base64-encoded PNG using Matplotlib (for quick debugging / standalone use).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


# ── Trend chart (dispatch vs delivered) ───────────────────────────────────────

def build_trend_chart(
    rows: list[dict],
    granularity: str = "day",
    location: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """
    Returns JSON-ready data for a line chart:
      { labels, dispatch, delivered, mismatch, points }
    """
    labels    = [r["label"] for r in rows]
    dispatch  = [round(float(r.get("dispatch", 0) or 0), 1) for r in rows]
    delivered = [round(float(r.get("delivered", 0) or 0), 1) for r in rows]
    mismatch  = [round(float(r.get("mismatch", 0) or 0), 1) for r in rows]

    points = [
        {"label": r["label"], "dispatch": d, "delivered": v, "mismatch": m}
        for r, d, v, m in zip(rows, dispatch, delivered, mismatch)
    ]

    return {
        "module":      "AnomalyDetection",
        "chart_type":  "line",
        "title":       "Dispatch vs Delivered Trend",
        "granularity": granularity,
        "filters":     {"location": location, "date_from": date_from, "date_to": date_to},
        "labels":      labels,
        "datasets": [
            {"label": "Dispatch",  "data": dispatch,  "color": "#3b82f6"},
            {"label": "Delivered", "data": delivered, "color": "#22c55e"},
            {"label": "Mismatch",  "data": mismatch,  "color": "#ef4444"},
        ],
        "points": points,
    }


# ── Anomaly timeline chart ────────────────────────────────────────────────────

_SEVERITY_COLORS = {
    "CRITICAL": "#ef4444",
    "HIGH":     "#f97316",
    "MEDIUM":   "#eab308",
    "LOW":      "#22c55e",
}


def build_anomaly_timeline(
    rows: list[dict],
    location: str | None = None,
    severity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """
    Scatter/line chart: anomaly score over time, colored by severity.
    """
    labels     = [r["timestamp"][:10] for r in rows]
    scores     = [round(float(r.get("anomaly_score", 0) or 0), 4) for r in rows]
    severities = [r.get("severity", "LOW") for r in rows]
    colors     = [_SEVERITY_COLORS.get(s, "#94a3b8") for s in severities]

    points = [
        {
            "timestamp":    r["timestamp"],
            "location":     r.get("location", ""),
            "transaction_id": r.get("transaction_id", ""),
            "anomaly_score":  round(float(r.get("anomaly_score", 0) or 0), 4),
            "severity":     r.get("severity", "LOW"),
            "reasons":      r.get("reasons", []),
            "color":        _SEVERITY_COLORS.get(r.get("severity", "LOW"), "#94a3b8"),
        }
        for r in rows
    ]

    # Severity breakdown counts
    from collections import Counter
    breakdown = dict(Counter(severities))

    return {
        "module":     "AnomalyDetection",
        "chart_type": "scatter",
        "title":      "Anomalies Over Time",
        "filters":    {"location": location, "severity": severity, "date_from": date_from, "date_to": date_to},
        "total":      len(rows),
        "severity_breakdown": breakdown,
        "labels":     labels,
        "scores":     scores,
        "severities": severities,
        "colors":     colors,
        "datasets": [
            {
                "label": sev,
                "data": [
                    {"x": p["timestamp"], "y": p["anomaly_score"]}
                    for p in points if p["severity"] == sev
                ],
                "color": _SEVERITY_COLORS.get(sev, "#94a3b8"),
            }
            for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        ],
        "points": points,
    }


# ── Location summary bar chart ────────────────────────────────────────────────

def build_location_summary(
    rows: list[dict],
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """
    Bar chart: anomaly count and rate per location.
    """
    buckets = []
    labels: list[str] = []
    anomaly_counts: list[int] = []
    anomaly_rates: list[float] = []
    stacked: dict[str, list[int]] = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}

    for r in rows:
        loc   = r["location"]
        total = int(r.get("total_tx", 0) or 0)
        anom  = int(r.get("anomaly_count", 0) or 0)
        rate  = round(anom / total * 100, 2) if total > 0 else 0.0

        labels.append(loc)
        anomaly_counts.append(anom)
        anomaly_rates.append(rate)
        stacked["CRITICAL"].append(int(r.get("critical_count", 0) or 0))
        stacked["HIGH"].append(int(r.get("high_count", 0) or 0))
        stacked["MEDIUM"].append(int(r.get("medium_count", 0) or 0))
        stacked["LOW"].append(int(r.get("low_count", 0) or 0))

        buckets.append({
            "location":          loc,
            "total_transactions": total,
            "anomaly_count":     anom,
            "anomaly_rate_pct":  rate,
            "critical_count":    int(r.get("critical_count", 0) or 0),
            "high_count":        int(r.get("high_count", 0) or 0),
            "medium_count":      int(r.get("medium_count", 0) or 0),
            "low_count":         int(r.get("low_count", 0) or 0),
        })

    return {
        "module":     "AnomalyDetection",
        "chart_type": "bar",
        "title":      "Location-wise Anomaly Summary",
        "filters":    {"date_from": date_from, "date_to": date_to},
        "labels":     labels,
        "anomaly_counts": anomaly_counts,
        "anomaly_rates":  anomaly_rates,
        "datasets": [
            {"label": "Total Anomalies", "data": anomaly_counts, "color": "#3b82f6"},
            {"label": "Anomaly Rate %", "data": anomaly_rates,  "color": "#f97316"},
        ],
        "stacked_by_severity": {
            sev: {"label": sev, "data": vals, "color": _SEVERITY_COLORS.get(sev, "#94a3b8")}
            for sev, vals in stacked.items()
        },
        "buckets": buckets,
    }


# ── Delay histogram ───────────────────────────────────────────────────────────

def build_delay_histogram(
    rows: list[dict],
    bins: int = 12,
    location: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """
    Histogram of delivery_delay_hours split by normal vs anomalous.
    """
    if not rows:
        return {
            "module": "AnomalyDetection", "chart_type": "histogram",
            "title": "Delivery Delay Distribution",
            "filters": {"location": location, "date_from": date_from, "date_to": date_to},
            "bin_edges": [], "bin_labels": [], "counts": [], "anomalous_counts": [],
        }

    delays_all  = np.array([float(r.get("delivery_delay_hours", 0) or 0) for r in rows])
    is_anomaly  = np.array([bool(int(r.get("is_anomaly", 0) or 0)) for r in rows])
    delays_anom = delays_all[is_anomaly]

    bin_edges = np.linspace(delays_all.min(), delays_all.max(), bins + 1)

    counts_all  = np.histogram(delays_all,  bins=bin_edges)[0].tolist()
    counts_anom = np.histogram(delays_anom, bins=bin_edges)[0].tolist() if len(delays_anom) else [0] * bins

    bin_labels = [
        f"{bin_edges[i]:.1f}h – {bin_edges[i+1]:.1f}h"
        for i in range(bins)
    ]

    return {
        "module":     "AnomalyDetection",
        "chart_type": "histogram",
        "title":      "Delivery Delay Distribution",
        "filters":    {"location": location, "date_from": date_from, "date_to": date_to},
        "bin_edges":  [round(float(e), 2) for e in bin_edges],
        "bin_labels": bin_labels,
        "datasets": [
            {"label": "All Transactions", "data": counts_all,  "color": "#3b82f6"},
            {"label": "Anomalous",        "data": counts_anom, "color": "#ef4444"},
        ],
        "counts":          counts_all,
        "anomalous_counts": counts_anom,
        "stats": {
            "mean_delay":   round(float(delays_all.mean()), 2),
            "median_delay": round(float(np.median(delays_all)), 2),
            "max_delay":    round(float(delays_all.max()), 2),
            "pct_late":     round(float((delays_all > 0).mean() * 100), 1),
        },
    }


# ── Optional PNG export ───────────────────────────────────────────────────────

def trend_as_png(rows: list[dict]) -> bytes:
    """Render dispatch vs delivered as a Matplotlib PNG. Returns raw bytes."""
    try:
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        labels    = [r["label"] for r in rows]
        dispatch  = [float(r.get("dispatch", 0) or 0) for r in rows]
        delivered = [float(r.get("delivered", 0) or 0) for r in rows]

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(labels, dispatch,  label="Dispatch",  color="#3b82f6", linewidth=2)
        ax.plot(labels, delivered, label="Delivered", color="#22c55e", linewidth=2)
        ax.fill_between(labels,
                        [min(d, v) for d, v in zip(dispatch, delivered)],
                        [max(d, v) for d, v in zip(dispatch, delivered)],
                        alpha=0.15, color="#ef4444", label="Gap")
        ax.set_title("Dispatch vs Delivered Trend", fontsize=14)
        ax.set_xlabel("Date")
        ax.set_ylabel("Quantity (kg)")
        ax.legend()
        ax.tick_params(axis="x", rotation=45)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except ImportError:
        raise RuntimeError("matplotlib not installed. pip install matplotlib")
