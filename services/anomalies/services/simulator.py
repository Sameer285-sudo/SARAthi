"""
Real-time simulation loop.

Generates synthetic transactions every N seconds and ingests them through
the full detection pipeline. This simulates a live data feed for demo purposes.

Start/stop via the API: POST /simulation/start  and  POST /simulation/stop
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

LOCATIONS = [
    "Guntur-District", "Krishna-District", "Nandyal-District",
    "Kurnool-District", "Palnadu-District", "Tirupati-District",
]

_task: asyncio.Task | None = None
_running = False


def is_running() -> bool:
    return _running


async def _simulate(interval_seconds: float, inject_anomaly_rate: float) -> None:
    global _running
    _running = True
    log.info("Simulation started (interval=%.1fs, anomaly_rate=%.0f%%)",
             interval_seconds, inject_anomaly_rate * 100)

    # Import here to avoid circular at module load
    from services.ingestion import preprocess, add_rolling_features
    from services.detector  import engine as det_engine
    from services.alerts    import build_alerts
    from utils.store        import (
        upsert_transactions_bulk, upsert_anomalies_bulk,
        insert_alerts_bulk, get_transactions,
    )
    from utils.cache import chart_cache, alert_cache

    try:
        while _running:
            tx = _generate_transaction(inject_anomaly=random.random() < inject_anomaly_rate)
            records = preprocess([tx])
            records = add_rolling_features(records)

            upsert_transactions_bulk(records)

            # Refit IForest on accumulated history every 50 new records
            all_tx = get_transactions(limit=2000)
            det_engine.maybe_refit(all_tx)

            results = det_engine.detect_batch(records)

            anomalies = [r for r in results if r.get("is_anomaly")]
            if anomalies:
                upsert_anomalies_bulk(results)
                alerts = build_alerts(anomalies)
                insert_alerts_bulk(alerts)
                chart_cache.invalidate()
                alert_cache.invalidate()

            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        pass
    finally:
        _running = False
        log.info("Simulation stopped")


def start(interval_seconds: float = 3.0, anomaly_rate: float = 0.15) -> str:
    global _task, _running
    if _running:
        return "already_running"
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_simulate(interval_seconds, anomaly_rate))
    return "started"


def stop() -> str:
    global _task, _running
    _running = False
    if _task and not _task.done():
        _task.cancel()
        _task = None
    return "stopped"


# ── Synthetic data generator ──────────────────────────────────────────────────

def _generate_transaction(inject_anomaly: bool = False) -> dict:
    loc  = random.choice(LOCATIONS)
    now  = datetime.now(timezone.utc)
    exp_hours = random.uniform(2, 8)
    exp  = now - timedelta(hours=exp_hours)

    disp = random.uniform(500, 5000)

    if inject_anomaly:
        anomaly_type = random.choice(["delay", "mismatch", "stock_drop"])
        if anomaly_type == "delay":
            actual_delay = exp_hours + random.uniform(10, 30)
            dlvd = disp * random.uniform(0.90, 1.0)
        elif anomaly_type == "mismatch":
            actual_delay = exp_hours + random.uniform(-1, 2)
            dlvd = disp * random.uniform(0.50, 0.70)   # large shortfall
        else:  # stock_drop
            actual_delay = exp_hours + random.uniform(-1, 3)
            dlvd = disp * random.uniform(0.85, 1.0)
    else:
        actual_delay = exp_hours + random.uniform(-0.5, 1.5)
        dlvd = disp * random.uniform(0.93, 1.0)

    act  = exp + timedelta(hours=actual_delay)
    sb   = random.uniform(1000, 10000)
    if inject_anomaly and random.random() < 0.3:
        sa = -random.uniform(10, 500)   # negative stock
    else:
        sa = sb + dlvd - random.uniform(100, disp * 0.5)
        sa = max(0.0, sa)

    ts_fmt = "%Y-%m-%dT%H:%M:%S"
    return {
        "transaction_id":       str(uuid.uuid4()),
        "timestamp":            now.strftime(ts_fmt),
        "location":             loc,
        "dispatch_quantity":    round(disp, 1),
        "delivered_quantity":   round(dlvd, 1),
        "expected_delivery_time": exp.strftime(ts_fmt),
        "actual_delivery_time":   act.strftime(ts_fmt),
        "stock_before":         round(sb, 1),
        "stock_after":          round(sa, 1),
    }


def generate_sample_batch(n: int = 200, anomaly_rate: float = 0.12) -> list[dict]:
    """Generate a static sample batch for seeding / demo."""
    base_time = datetime.now(timezone.utc) - timedelta(days=30)
    out = []
    for i in range(n):
        ts_offset = timedelta(hours=i * 3.6)
        tx = _generate_transaction(inject_anomaly=random.random() < anomaly_rate)
        ts = base_time + ts_offset
        tx["timestamp"] = ts.strftime("%Y-%m-%dT%H:%M:%S")
        out.append(tx)
    return out
