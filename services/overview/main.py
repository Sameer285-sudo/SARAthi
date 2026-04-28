"""
Overview Microservice — port 8001
Aggregates summary data from all modules into a single dashboard endpoint.
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from shared.auth.dependencies import optional_current_user, CurrentUser
from shared.db import Base, SessionLocal, engine, get_db
from shared.schemas import DashboardOverview
from shared.seed import seed_data
from shared.services.anomaly import get_summary as get_anomaly_summary
from shared.services.call_centre import get_summary as get_call_summary
from shared.services.smart_allot import get_summary as get_smart_summary


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()
    yield


app = FastAPI(title="PDS360 — Overview Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "overview", "port": 8001}


@app.get("/api/overview", response_model=DashboardOverview)
def overview(
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(optional_current_user),
):
    smart     = get_smart_summary(db, user=user)
    anomalies = get_anomaly_summary(db)
    calls     = get_call_summary(db, user=user)
    return DashboardOverview(
        smart_allot=smart,
        anomalies=anomalies,
        call_centre=calls,
        operational_highlights=[
            f"{smart.high_risk_fps} districts need elevated replenishment planning.",
            f"{anomalies.open_investigation_queue} movement anomalies require follow-up.",
            f"{calls.high_priority_tickets} high-priority citizen complaints remain open.",
        ],
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
