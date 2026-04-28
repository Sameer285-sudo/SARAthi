"""
All FastAPI route handlers for the anomaly detection service.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from models.schemas import IngestRequest, IngestResponse
from services.ingestion import add_rolling_features, preprocess
from services.detector  import engine as det_engine
from services.alerts    import build_alerts
from services import simulator
from utils.store import (
    count_anomalies, count_transactions,
    get_alerts, get_anomalies, get_transactions,
    get_trend_data, get_anomaly_timeline, get_location_stats,
    get_delay_distribution,
    insert_alerts_bulk, upsert_anomalies_bulk, upsert_transactions_bulk,
    acknowledge_alert,
)
from utils.cache import alert_cache, chart_cache
from visualization.charts import (
    build_anomaly_timeline, build_delay_histogram,
    build_location_summary, build_trend_chart, trend_as_png,
)

log = logging.getLogger(__name__)

router = APIRouter()

# ── Ingest ────────────────────────────────────────────────────────────────────

@router.post("/ingest-data", response_model=IngestResponse)
def ingest_data(body: IngestRequest):
    """
    Ingest one or more transaction records.
    Runs the full pipeline: preprocess → feature engineering → anomaly detection → alerts.
    """
    raw = [t.model_dump() for t in body.transactions]

    # 1. Preprocess + feature engineering
    records = preprocess(raw)
    if not records:
        raise HTTPException(status_code=422, detail="No valid records after preprocessing.")
    records = add_rolling_features(records)

    # 2. Store transactions
    upsert_transactions_bulk(records)

    # 3. Refit IForest on accumulated data if needed
    all_tx = get_transactions(limit=5000)
    det_engine.maybe_refit(all_tx)

    # 4. Detect anomalies
    results = det_engine.detect_batch(records)
    anomalous = [r for r in results if r.get("is_anomaly")]

    # 5. Persist anomalies
    upsert_anomalies_bulk(results)

    # 6. Generate and persist alerts
    alerts = build_alerts(anomalous)
    insert_alerts_bulk(alerts)

    # 7. Invalidate caches
    chart_cache.invalidate()
    alert_cache.invalidate()

    sev_counts: dict[str, int] = {}
    for a in anomalous:
        sev = a.get("severity", "LOW")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1

    return IngestResponse(
        ingested=len(records),
        anomalies_detected=len(anomalous),
        alerts_generated=len(alerts),
        summary={
            "total_ingested":     len(records),
            "anomaly_count":      len(anomalous),
            "alert_count":        len(alerts),
            "severity_breakdown": sev_counts,
            "skipped":            len(raw) - len(records),
        },
    )


# ── Anomalies ─────────────────────────────────────────────────────────────────

@router.get("/anomalies")
def anomalies_list(
    location: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO date, e.g. 2024-01-01"),
    date_to:   Optional[str] = Query(default=None),
    limit:     int           = Query(default=200, ge=1, le=5000),
):
    """List detected anomalies with optional filters."""
    rows = get_anomalies(
        location=location, severity=severity,
        date_from=date_from, date_to=date_to, limit=limit,
    )
    return {
        "module": "AnomalyDetection",
        "total": len(rows),
        "filters": {"location": location, "severity": severity, "date_from": date_from, "date_to": date_to},
        "anomalies": rows,
    }


@router.get("/alerts")
def alerts_list(
    location:     Optional[str]  = Query(default=None),
    severity:     Optional[str]  = Query(default=None),
    date_from:    Optional[str]  = Query(default=None),
    date_to:      Optional[str]  = Query(default=None),
    acknowledged: Optional[bool] = Query(default=None),
    limit:        int            = Query(default=200, ge=1, le=2000),
):
    """List generated alerts."""
    cache_key = f"alerts:{location}:{severity}:{date_from}:{date_to}:{acknowledged}:{limit}"
    cached = alert_cache.get(cache_key)
    if cached:
        return cached

    rows = get_alerts(
        location=location, severity=severity,
        date_from=date_from, date_to=date_to,
        acknowledged=acknowledged, limit=limit,
    )
    result = {
        "module": "AnomalyDetection",
        "total": len(rows),
        "filters": {"location": location, "severity": severity},
        "alerts": rows,
    }
    alert_cache.set(cache_key, result)
    return result


@router.patch("/alerts/{alert_id}/acknowledge")
def ack_alert(alert_id: str):
    """Mark an alert as acknowledged."""
    ok = acknowledge_alert(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found.")
    alert_cache.invalidate("alerts:")
    return {"module": "AnomalyDetection", "alert_id": alert_id, "acknowledged": True}


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def summary():
    """Quick dashboard stats."""
    cache_key = "summary"
    cached = chart_cache.get(cache_key)
    if cached:
        return cached

    total_tx   = count_transactions()
    total_anom = count_anomalies()
    result = {
        "module": "AnomalyDetection",
        "total_transactions": total_tx,
        "total_anomalies":    total_anom,
        "anomaly_rate_pct":   round(total_anom / max(total_tx, 1) * 100, 2),
        "model_fitted":       det_engine._if_model is not None,
        "simulation_running": simulator.is_running(),
    }
    chart_cache.set(cache_key, result, ttl=15.0)
    return result


# ── Visualizations ────────────────────────────────────────────────────────────

@router.get("/visualization/trends")
def viz_trends(
    granularity: str           = Query(default="day", enum=["hour", "day", "month"]),
    location:    Optional[str] = Query(default=None),
    date_from:   Optional[str] = Query(default=None),
    date_to:     Optional[str] = Query(default=None),
    as_image:    bool          = Query(default=False, description="Return PNG image instead of JSON"),
):
    """
    Demand vs Delivered trend data.
    Returns JSON (preferred) or PNG image when as_image=true.
    """
    cache_key = f"trends:{granularity}:{location}:{date_from}:{date_to}"
    cached = chart_cache.get(cache_key)
    if not cached:
        rows = get_trend_data(granularity=granularity, location=location, date_from=date_from, date_to=date_to)
        cached = build_trend_chart(rows, granularity=granularity, location=location, date_from=date_from, date_to=date_to)
        chart_cache.set(cache_key, cached)

    if as_image:
        rows = get_trend_data(granularity=granularity, location=location, date_from=date_from, date_to=date_to)
        png = trend_as_png(rows)
        return Response(content=png, media_type="image/png")

    return cached


@router.get("/visualization/anomalies")
def viz_anomalies(
    location:  Optional[str] = Query(default=None),
    severity:  Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to:   Optional[str] = Query(default=None),
    limit:     int           = Query(default=500),
):
    """
    Anomalies over time — scatter chart data.
    Returns: { labels, scores, severities, points, datasets }
    """
    cache_key = f"viz_anom:{location}:{severity}:{date_from}:{date_to}:{limit}"
    cached = chart_cache.get(cache_key)
    if cached:
        return cached

    rows = get_anomaly_timeline(location=location, severity=severity, date_from=date_from, date_to=date_to, limit=limit)
    result = build_anomaly_timeline(rows, location=location, severity=severity, date_from=date_from, date_to=date_to)
    chart_cache.set(cache_key, result)
    return result


@router.get("/visualization/location-summary")
def viz_location_summary(
    date_from: Optional[str] = Query(default=None),
    date_to:   Optional[str] = Query(default=None),
):
    """
    Location-wise anomaly summary — bar chart data.
    Returns: { labels, anomaly_counts, anomaly_rates, buckets }
    """
    cache_key = f"viz_loc:{date_from}:{date_to}"
    cached = chart_cache.get(cache_key)
    if cached:
        return cached

    rows = get_location_stats(date_from=date_from, date_to=date_to)
    result = build_location_summary(rows, date_from=date_from, date_to=date_to)
    chart_cache.set(cache_key, result)
    return result


@router.get("/visualization/delay-distribution")
def viz_delay_histogram(
    location:  Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to:   Optional[str] = Query(default=None),
    bins:      int           = Query(default=12, ge=3, le=50),
):
    """
    Delivery delay histogram — normal vs anomalous.
    Returns: { bin_labels, counts, anomalous_counts, stats }
    """
    cache_key = f"viz_delay:{location}:{date_from}:{date_to}:{bins}"
    cached = chart_cache.get(cache_key)
    if cached:
        return cached

    rows = get_delay_distribution(location=location, date_from=date_from, date_to=date_to)
    result = build_delay_histogram(rows, bins=bins, location=location, date_from=date_from, date_to=date_to)
    chart_cache.set(cache_key, result)
    return result


# ── Simulation ────────────────────────────────────────────────────────────────

@router.post("/simulation/start")
def sim_start(
    interval_seconds: float = Query(default=3.0, ge=0.5, le=60.0),
    anomaly_rate:     float = Query(default=0.15, ge=0.0, le=1.0),
):
    """Start real-time transaction simulation."""
    status = simulator.start(interval_seconds=interval_seconds, anomaly_rate=anomaly_rate)
    return {"module": "AnomalyDetection", "simulation": status, "interval_seconds": interval_seconds}


@router.post("/simulation/stop")
def sim_stop():
    """Stop the real-time simulation."""
    status = simulator.stop()
    return {"module": "AnomalyDetection", "simulation": status}


@router.get("/simulation/status")
def sim_status():
    return {"module": "AnomalyDetection", "running": simulator.is_running()}


# ── Transactions (raw) ────────────────────────────────────────────────────────

@router.get("/transactions")
def transactions_list(
    location:  Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to:   Optional[str] = Query(default=None),
    limit:     int           = Query(default=100, ge=1, le=2000),
):
    """List ingested transactions (for debugging / audit)."""
    rows = get_transactions(location=location, date_from=date_from, date_to=date_to, limit=limit)
    return {"module": "AnomalyDetection", "total": len(rows), "transactions": rows}
