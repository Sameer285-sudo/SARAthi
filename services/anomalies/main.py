"""
Anomaly Detection Microservice — port 8003

Full pipeline:
  POST /api/anomaly/ingest-data              — ingest transactions, detect anomalies
  GET  /api/anomaly/anomalies                — list anomalies (filterable)
  GET  /api/anomaly/alerts                   — list generated alerts
  GET  /api/anomaly/summary                  — dashboard stats
  GET  /api/anomaly/visualization/trends     — dispatch vs delivered chart data
  GET  /api/anomaly/visualization/anomalies  — anomaly timeline chart data
  GET  /api/anomaly/visualization/location-summary — per-location bar chart
  GET  /api/anomaly/visualization/delay-distribution — delay histogram
  POST /api/anomaly/simulation/start         — start real-time sim
  POST /api/anomaly/simulation/stop          — stop simulation
  GET  /api/anomaly/transactions             — raw transaction log

Legacy (backward-compatible with existing frontend):
  GET  /api/anomalies                        — same shape as before
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_SERVICES = Path(__file__).resolve().parents[1]
_HERE     = Path(__file__).resolve().parent
for _p in (str(_SERVICES), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from shared.db import Base, SessionLocal, engine as shared_engine, get_db
from shared.seed import seed_data
from shared.services.anomaly import get_alerts as db_get_alerts, get_summary as db_get_summary

from utils.store import init_db, count_transactions, count_anomalies
from services.ingestion import preprocess, add_rolling_features
from services.detector import engine as det_engine
from services.alerts import build_alerts
from utils.store import (
    upsert_transactions_bulk, upsert_anomalies_bulk,
    insert_alerts_bulk, get_transactions,
)
from api.routes import router

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("anomaly_svc")


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Shared PDS DB setup
    Base.metadata.create_all(bind=shared_engine)
    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()

    # Local anomaly SQLite
    init_db()

    # Seed with sample data if store is empty
    _seed_if_empty()

    yield


def _seed_if_empty() -> None:
    if count_transactions() > 0:
        return
    log.info("Seeding 200 synthetic transactions…")
    try:
        from services.simulator import generate_sample_batch
        batch   = generate_sample_batch(n=200, anomaly_rate=0.12)
        records = preprocess(batch)
        records = add_rolling_features(records)
        upsert_transactions_bulk(records)

        all_tx = get_transactions(limit=2000)
        det_engine.maybe_refit(all_tx)

        results  = det_engine.detect_batch(records)
        upsert_anomalies_bulk(results)

        anomalous = [r for r in results if r.get("is_anomaly")]
        alerts    = build_alerts(anomalous)
        insert_alerts_bulk(alerts)
        log.info(
            "Seed done: %d tx, %d anomalies, %d alerts",
            len(records), len(anomalous), len(alerts),
        )
    except Exception as exc:
        log.warning("Seed failed (non-fatal): %s", exc)


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PDS360 — Anomaly Detection Service",
    description=(
        "Real-time anomaly detection for PDS distribution data.\n\n"
        "**Ingest** transactions → **detect** anomalies (IsolationForest + Z-score + rules) "
        "→ **generate alerts** → **visualize** via chart-data APIs."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# All new routes under /api/anomaly
app.include_router(router, prefix="/api/anomaly", tags=["Anomaly Detection"])


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health():
    return {
        "status":              "ok",
        "service":             "anomalies",
        "port":                8003,
        "transactions_stored": count_transactions(),
        "anomalies_stored":    count_anomalies(),
        "model_fitted":        det_engine._if_model is not None,
    }


# ── Legacy endpoints (keep existing frontend working) ─────────────────────────

@app.get("/api/anomalies", tags=["Legacy"])
def legacy_anomalies(db: Session = Depends(get_db)):
    """Backward-compatible: used by existing frontend Overview page."""
    return {"module": "Anomaly Detection", "alerts": db_get_alerts(db)}


@app.get("/api/anomalies/summary", tags=["Legacy"])
def legacy_summary(db: Session = Depends(get_db)):
    return {"module": "Anomaly Detection", "summary": db_get_summary(db)}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8003,
        reload=True,
        # Only watch .py files — prevents SQLite WAL and __pycache__ writes
        # from triggering an infinite restart loop on startup
        reload_includes=["*.py"],
    )
