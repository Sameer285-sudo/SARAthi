"""
SMARTAllot Microservice — port 8002

Full AI/ML pipeline:
  POST /api/smart-allot/upload-data        — upload CSV/Excel, run preprocessing
  POST /api/smart-allot/predict-demand     — ML demand forecast (next N months)
  POST /api/smart-allot/optimize-allocation— LP-based stock allocation
  GET  /api/smart-allot/anomalies          — anomaly detection on loaded data
  POST /api/smart-allot/retrain            — full retraining pipeline
  GET  /api/smart-allot/model-info         — evaluation metrics + model status
  GET  /api/smart-allot/eval-report        — full evaluation report
  GET  /api/smart-allot/recommendations    — DB-backed allotment recommendations
  GET  /api/smart-allot/summary            — quick summary stats
  GET  /api/smart-allot/filters            — filter metadata (districts, items)
  GET  /api/smart-allot/dataset-info       — info about currently loaded dataset
"""

import io
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

# ── Path setup: expose shared + smart_allot_system/src ────────────────────────
_SERVICES_DIR   = Path(__file__).resolve().parents[1]
_ROOT           = _SERVICES_DIR.parent
_ML_SRC         = _ROOT / "smart_allot_system"

for _p in [str(_SERVICES_DIR), str(_ML_SRC)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.auth.dependencies import optional_current_user, CurrentUser
from shared.db import Base, SessionLocal, engine, get_db
from shared.seed import seed_data
from shared.services.smart_allot import get_recommendations as db_recommendations
from shared.services.smart_allot import get_summary as db_summary
from shared.services.smart_allot import get_filter_metadata_db as db_filter_metadata
from shared.services.smart_allot_ml import get_filter_metadata, get_model_info
from shared.services import demand_model as db_demand_model

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("smart_allot")


def _try_import_pandas():
    """
    Pandas is heavy and can fail to import on low-memory Windows machines
    (paging file too small). We keep SMARTAllot online by importing pandas only
    inside endpoints that need it.
    """

    try:
        import pandas as pd  # type: ignore

        return pd
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=503,
            detail=(
                "Pandas is unavailable on this machine (often due to low virtual memory). "
                "Increase the Windows paging file / free RAM and restart the SMARTAllot service. "
                f"Import error: {type(exc).__name__}: {exc}"
            ),
        )


def _try_import_ml_modules():
    """
    Legacy SMARTAllot pipeline (smart_allot_system/src) depends on pandas.
    We lazy-import it so DB-backed endpoints still work without pandas.
    """

    pd = _try_import_pandas()
    from src.data_processing import (  # type: ignore
        clean_data,
        engineer_features,
        load_dataset,
        normalize_features,
        run_pipeline,
        train_test_split_temporal,
        aggregate,
    )
    from src.modeling import BaselineModel, SmartAllotForecaster  # type: ignore
    from src.optimization import (  # type: ignore
        AllocationConfig,
        optimize_allocation,
        results_to_dataframe,
        estimate_required_supply,
    )
    from src.anomaly_detection import AnomalyDetector, AnomalyConfig  # type: ignore
    from src.evaluation import compute_metrics, generate_eval_report  # type: ignore

    return {
        "pd": pd,
        "clean_data": clean_data,
        "engineer_features": engineer_features,
        "load_dataset": load_dataset,
        "normalize_features": normalize_features,
        "run_pipeline": run_pipeline,
        "train_test_split_temporal": train_test_split_temporal,
        "aggregate": aggregate,
        "BaselineModel": BaselineModel,
        "SmartAllotForecaster": SmartAllotForecaster,
        "AllocationConfig": AllocationConfig,
        "optimize_allocation": optimize_allocation,
        "results_to_dataframe": results_to_dataframe,
        "estimate_required_supply": estimate_required_supply,
        "AnomalyDetector": AnomalyDetector,
        "AnomalyConfig": AnomalyConfig,
        "compute_metrics": compute_metrics,
        "generate_eval_report": generate_eval_report,
    }

# ── Paths ──────────────────────────────────────────────────────────────────────
MODELS_DIR  = _ML_SRC / "models"
DATA_DIR    = _ML_SRC / "data"
MODELS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

DEFAULT_DATASET = DATA_DIR / "sample_dataset.csv"
EVAL_REPORT_PATH = MODELS_DIR / "eval_report.json"

# ── In-memory app state ────────────────────────────────────────────────────────
class _State:
    # NOTE: We intentionally keep these as Any to avoid importing pandas at module import time.
    df:         Optional[Any] = None  # full featured dataframe
    raw:        Optional[Any] = None  # raw loaded data
    train:      Optional[Any] = None
    test:       Optional[Any] = None
    forecaster: Optional[Any] = None
    detector:   Optional[Any] = None
    dataset_path: str = ""
    last_trained: str = ""

STATE = _State()


def _load_models() -> None:
    """Load persisted models into STATE if they exist."""
    bl = MODELS_DIR / "baseline.pkl"
    ad = MODELS_DIR / "anomaly_detector.pkl"
    if bl.exists():
        try:
            ml = _try_import_ml_modules()
            STATE.forecaster = ml["SmartAllotForecaster"].load(MODELS_DIR)
            log.info("Loaded forecaster from %s", MODELS_DIR)
        except Exception as exc:
            # Keep service online even if pandas/legacy ML cannot load.
            log.warning("Skipping legacy forecaster load: %s", exc)
    if ad.exists():
        try:
            import joblib

            STATE.detector = joblib.load(ad)
            log.info("Loaded anomaly detector")
        except Exception as exc:
            log.warning("Skipping anomaly detector load: %s", exc)


def _load_default_data() -> None:
    """Pre-load the sample dataset on startup."""
    if DEFAULT_DATASET.exists():
        try:
            ml = _try_import_ml_modules()
            pipeline = ml["run_pipeline"](DEFAULT_DATASET, test_months=3)
            STATE.df   = pipeline["full_df"]
            STATE.raw  = pipeline["raw"]
            STATE.train = pipeline["train"]
            STATE.test  = pipeline["test"]
            STATE.dataset_path = str(DEFAULT_DATASET)
            log.info("Loaded default dataset: %d rows", len(STATE.df))
        except Exception as exc:
            log.warning("Could not load default dataset: %s", exc)


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()
    _load_default_data()
    _load_models()
    yield


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PDS360 — SMARTAllot Service",
    description="AI/ML demand forecasting, LP allocation, anomaly detection for PDS distribution.",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    future_periods: int = Field(default=3, ge=1, le=24)
    year:           Optional[int] = None
    district:       Optional[str] = None
    afso:           Optional[str] = None
    fps_id:         Optional[str] = None
    month:          Optional[str] = None
    commodity:      Optional[str] = None
    source:         str = Field(default="db", description="db | uploaded")

class OptimizeRequest(BaseModel):
    future_periods:  int   = Field(default=3, ge=1, le=24)
    year:            Optional[int] = None
    district:        Optional[str] = None
    afso:            Optional[str] = None
    fps_id:          Optional[str] = None
    month:           Optional[str] = None
    commodity:       Optional[str] = None
    total_supply:    Optional[dict[str, float]] = None  # {"Rice": 500000, ...}
    shortage_weight: float = 3.0
    overstock_weight:float = 1.0
    safety_buffer_pct: float = 0.10
    source:          str = Field(default="db", description="db | uploaded")

class RetrainRequest(BaseModel):
    test_months: int = Field(default=3, ge=1, le=12)
    train_db_demand_model: bool = Field(default=True, description="Also train DB-backed demand model from dataset/clean_transactions.csv")

class AnomalyRequest(BaseModel):
    district:  Optional[str] = None
    commodity: Optional[str] = None
    severity:  Optional[str] = None   # "HIGH" | "MEDIUM" | "LOW" | "CRITICAL"
    limit:     int = 100
    source:    str = Field(default="db", description="db | uploaded")


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "smart_allot",
        "port": 8002,
        "dataset_loaded": STATE.df is not None,
        "models_loaded": STATE.forecaster is not None,
    }


# ── Upload data ────────────────────────────────────────────────────────────────

@app.post("/api/smart-allot/upload-data")
async def upload_data(
    file: UploadFile = File(...),
    test_months: int = Form(default=3),
):
    """Upload a CSV/Excel dataset. Runs full preprocessing pipeline automatically."""
    content = await file.read()
    suffix = Path(file.filename or "data.csv").suffix.lower()

    # Validate the file is parseable before saving
    try:
        pd = _try_import_pandas()
        if suffix in (".xlsx", ".xls"):
            pd.read_excel(io.BytesIO(content), nrows=5)
        else:
            pd.read_csv(io.BytesIO(content), nrows=5)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {exc}")

    # Save to disk so retrain can access it
    save_path = DATA_DIR / (file.filename or "uploaded.csv")
    save_path.write_bytes(content)

    try:
        ml = _try_import_ml_modules()
        pipeline = ml["run_pipeline"](save_path, test_months=test_months)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    STATE.df   = pipeline["full_df"]
    STATE.raw  = pipeline["raw"]
    STATE.train = pipeline["train"]
    STATE.test  = pipeline["test"]
    STATE.dataset_path = str(save_path)

    df = STATE.df
    return {
        "module": "SMARTAllot",
        "status": "uploaded_and_preprocessed",
        "file": file.filename,
        "rows": len(df),
        "date_range": f"{df['date'].min().date()} to {df['date'].max().date()}",
        "districts": sorted(df["district"].unique().tolist()),
        "commodities": sorted(df["commodity"].unique().tolist()),
        "fps_count": df["fps_id"].nunique(),
        "missing_pct": round(STATE.raw.isnull().mean().mean() * 100, 2),
        "train_rows": len(STATE.train),
        "test_rows": len(STATE.test),
    }


# ── Dataset info ───────────────────────────────────────────────────────────────

@app.get("/api/smart-allot/dataset-info")
def dataset_info():
    if STATE.df is None:
        raise HTTPException(status_code=404, detail="No dataset loaded. POST to /upload-data first.")
    df = STATE.df
    return {
        "module": "SMARTAllot",
        "dataset_path": STATE.dataset_path,
        "total_rows": len(df),
        "date_range": {"from": str(df["date"].min().date()), "to": str(df["date"].max().date())},
        "districts": sorted(df["district"].unique().tolist()),
        "mandals": sorted(df["mandal"].unique().tolist()),
        "fps_ids": sorted(df["fps_id"].unique().tolist()),
        "commodities": sorted(df["commodity"].unique().tolist()),
        "warehouses": sorted(df["warehouse"].unique().tolist()) if "warehouse" in df.columns else [],
        "columns": list(df.columns),
        "missing_values": {col: int(df[col].isnull().sum()) for col in df.columns if df[col].isnull().any()},
        "train_rows": len(STATE.train) if STATE.train is not None else 0,
        "test_rows": len(STATE.test) if STATE.test is not None else 0,
    }


# ── Predict demand ─────────────────────────────────────────────────────────────

@app.post("/api/smart-allot/predict-demand")
def predict_demand(body: PredictRequest, db: Session = Depends(get_db)):
    """
    Forecast demand for the next N months.
    Uses trained Prophet (if available) or Ridge regression.
    """
    # ── Fast path: pre-computed GradientBoosting CSV (sub-second response) ───────
    # When no FPS/AFSO-level filter is set, serve district-level forecasts directly
    # from the pre-computed ML artifacts. Avoids live DB inference (~minutes → <1s).
    _is_fps_query = bool(body.fps_id or body.afso)
    if not _is_fps_query and body.source != "uploaded":
        try:
            from shared.services.smart_allot_ml import get_recommendations as _ml_recs
            recs = _ml_recs(
                district_name=body.district or None,
                item_name=body.commodity or None,
            )
            if recs:
                predictions_fast = []
                for r in recs:
                    f = float(r.forecast_next_month)
                    s = float(r.safety_stock)
                    predictions_fast.append({
                        "location":        r.district_name,
                        "district":        r.district_name,
                        "commodity":       r.item_name,
                        "date":            r.forecast_for_month,
                        "predicted_demand": round(f, 2),
                        "lower_bound":     round(max(f - s * 0.5, 0.0), 2),
                        "upper_bound":     round(f + s, 2),
                        "confidence_score": 0.85,
                        "model_used":      "GradientBoosting_CSV_V1",
                    })
                return {
                    "module": "SMARTAllot",
                    "future_periods": body.future_periods,
                    "filters": {"district": body.district, "commodity": body.commodity},
                    "count": len(predictions_fast),
                    "predictions": predictions_fast,
                }
        except Exception:
            pass  # Fall through to live DB inference if CSV unavailable

    # ── In-memory uploaded pipeline ───────────────────────────────────────────
    if body.source == "uploaded" and STATE.forecaster is not None and STATE.forecaster.is_trained and STATE.df is not None:
        ref = STATE.df.copy()
        if body.district:
            ref = ref[ref["district"].str.lower() == body.district.lower()]
        if body.commodity:
            ref = ref[ref["commodity"].str.lower() == body.commodity.lower()]

        predictions = STATE.forecaster.predict_future(
            future_periods=body.future_periods,
            reference_df=ref if not ref.empty else STATE.df,
        )

        if body.district:
            predictions = [p for p in predictions if p.district.lower() == body.district.lower()]
        if body.commodity:
            predictions = [p for p in predictions if p.commodity.lower() == body.commodity.lower()]

        return {
            "module": "SMARTAllot",
            "future_periods": body.future_periods,
            "filters": {"district": body.district, "commodity": body.commodity},
            "count": len(predictions),
            "predictions": [asdict(p) for p in predictions],
        }

    # Default: DB path (supports unit-level filters). Prefer trained DB model if present.
    from shared.models import TransactionRecord
    from sqlalchemy import func

    month_order = ["January","February","March","April","May","June","July","August","September","October","November","December"]
    month_idx = {m: i + 1 for i, m in enumerate(month_order)}

    # Normalize commodity aliases (e.g., "rice" -> "FRice (Kgs)")
    normalized_commodity = db_demand_model.normalize_commodity(body.commodity)

    # Pick aggregation granularity based on filters:
    # FPS selected    -> group by fps_id
    # AFSO selected   -> group by afso  (aggregate across FPS)
    # District selected (or none) -> group by district (aggregate across AFSO/FPS)
    #
    # NOTE: It's critical we *don't* keep grouping by fps_id when the user wants
    # AFSO- or district-level totals, otherwise the "series" mixes many FPS rows
    # and produces inflated / unstable baselines and wrong y-axis scaling in the UI.
    if body.fps_id:
        agg_level = "fps"
    elif body.afso:
        agg_level = "afso"
    else:
        agg_level = "district"

    cols = [
        TransactionRecord.year,
        TransactionRecord.month,
        TransactionRecord.commodity,
        func.sum(TransactionRecord.quantity_kgs).label("qty"),
    ]
    group_cols = [
        TransactionRecord.year,
        TransactionRecord.month,
        TransactionRecord.commodity,
    ]

    if agg_level == "district":
        cols.extend([
            TransactionRecord.district.label("district"),
            TransactionRecord.district.label("group_label"),
        ])
        group_cols.append(TransactionRecord.district)
    elif agg_level == "afso":
        cols.extend([
            TransactionRecord.district.label("district"),
            TransactionRecord.afso.label("group_label"),
        ])
        group_cols.extend([TransactionRecord.district, TransactionRecord.afso])
    else:  # fps
        cols.extend([
            TransactionRecord.district.label("district"),
            TransactionRecord.afso.label("afso"),
            TransactionRecord.fps_id.label("group_label"),
        ])
        group_cols.extend([TransactionRecord.district, TransactionRecord.afso, TransactionRecord.fps_id])

    q = db.query(*cols).group_by(*group_cols)
    if body.year:
        q = q.filter(TransactionRecord.year == body.year)
    if body.district:
        q = q.filter(TransactionRecord.district == body.district)
    if body.afso:
        q = q.filter(TransactionRecord.afso == body.afso)
    if body.fps_id:
        q = q.filter(TransactionRecord.fps_id == body.fps_id)
    if normalized_commodity:
        q = q.filter(TransactionRecord.commodity == normalized_commodity)

    rows = q.all()
    if not rows:
        raise HTTPException(status_code=404, detail="No transaction data found for the given filters.")

    # As-of cutoff: if month/year filters provided, restrict training window to <= that point.
    # If only month is provided, assume max year in scope.
    as_of_year = body.year
    as_of_month = body.month
    if as_of_month and as_of_year is None:
        as_of_year = max(int(r.year) for r in rows)

    as_of_pair: tuple[int, int] | None = None
    if as_of_year and as_of_month and as_of_month in month_idx:
        as_of_pair = (int(as_of_year), int(month_idx[as_of_month]))

    series: dict[tuple[str, str, str], list[tuple[int, int, float]]] = {}
    # key: (group_label, district, commodity)
    for r in rows:
        mi = month_idx.get(str(r.month), 1)
        y = int(r.year)
        if as_of_pair is not None and (y, mi) > as_of_pair:
            continue
        key = (str(r.group_label), str(getattr(r, "district", body.district or "")), str(r.commodity))
        series.setdefault(key, []).append((y, mi, float(r.qty or 0.0)))

    if not series:
        raise HTTPException(status_code=404, detail="No transaction data found within the selected month/year scope.")

    max_y, max_m = max((y, m) for pts in series.values() for (y, m, _) in pts)

    def _advance(y: int, m: int, steps: int) -> tuple[int, int]:
        total = (y * 12 + (m - 1)) + steps
        return total // 12, (total % 12) + 1

    def _date_str(y: int, m: int) -> str:
        return f"{y:04d}-{m:02d}-01"

    predictions_out = []

    # If the trained DB regressor exists, use it for per-FPS time-series forecasting (better than moving avg).
    # For district/AFSO scope: we still forecast at FPS level and return aggregated totals by the selected scope label
    # so the UI y-axis scales correctly.
    if db_demand_model.is_trained():
        try:
            # Build raw history rows (not aggregated) limited to the chosen scope so lags are meaningful.
            hist_q = db.query(
                TransactionRecord.year,
                TransactionRecord.month,
                TransactionRecord.district,
                TransactionRecord.afso,
                TransactionRecord.fps_id,
                TransactionRecord.commodity,
                TransactionRecord.quantity_kgs,
                TransactionRecord.cards,
            )
            if body.year:
                hist_q = hist_q.filter(TransactionRecord.year == body.year)
            if body.district:
                hist_q = hist_q.filter(TransactionRecord.district == body.district)
            if body.afso:
                hist_q = hist_q.filter(TransactionRecord.afso == body.afso)
            if body.fps_id:
                hist_q = hist_q.filter(TransactionRecord.fps_id == body.fps_id)
            if normalized_commodity:
                hist_q = hist_q.filter(TransactionRecord.commodity == normalized_commodity)

            hist_rows = [
                {
                    "year": int(r.year),
                    "month": str(r.month),
                    "district": str(r.district),
                    "afso": str(r.afso),
                    "fps_id": str(r.fps_id),
                    "commodity": str(r.commodity),
                    "quantity_kgs": float(r.quantity_kgs or 0.0),
                    "cards": int(r.cards or 0),
                }
                for r in hist_q.all()
            ]

            preds = db_demand_model.predict_future_from_db(db_rows=hist_rows, future_periods=body.future_periods)
            if not preds:
                raise HTTPException(status_code=404, detail="Not enough history to generate ML forecasts for this scope.")

            # Aggregate by the chosen label so the UI displays the correct scale for district/AFSO/FPS.
            label_key = "district" if agg_level == "district" else ("afso" if agg_level == "afso" else "location")
            grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
            for p in preds:
                date = str(p["date"])
                commodity = str(p["commodity"])
                if label_key == "district":
                    label = str(p["district"])
                elif label_key == "afso":
                    label = str(p.get("afso") or body.afso or p["district"])
                else:
                    label = str(p["location"])

                k = (label, commodity, date)
                if k not in grouped:
                    grouped[k] = {**p, "location": label}
                else:
                    grouped[k]["predicted_demand"] += float(p["predicted_demand"])
                    grouped[k]["lower_bound"] += float(p["lower_bound"])
                    grouped[k]["upper_bound"] += float(p["upper_bound"])

            predictions_out = [
                {
                    "location": v["location"],
                    "district": v.get("district") if agg_level != "afso" else (body.district or v.get("district")),
                    "commodity": v["commodity"],
                    "date": v["date"],
                    "predicted_demand": round(float(v["predicted_demand"]), 2),
                    "lower_bound": round(float(v["lower_bound"]), 2),
                    "upper_bound": round(float(v["upper_bound"]), 2),
                    "confidence_score": float(v["confidence_score"]),
                    "model_used": "DB_GBR_V1",
                }
                for v in grouped.values()
            ]
            predictions_out.sort(key=lambda x: (x["location"], x["commodity"], x["date"]))

            return {
                "module": "SMARTAllot",
                "future_periods": body.future_periods,
                "filters": {
                    "year": body.year,
                    "month": body.month,
                    "district": body.district,
                    "afso": body.afso,
                    "fps_id": body.fps_id,
                    "commodity": normalized_commodity,
                },
                "count": len(predictions_out),
                "predictions": predictions_out,
            }
        except HTTPException:
            raise
        except Exception as exc:
            # If pandas cannot import (low paging file) or any other unexpected issue,
            # fall back to deterministic DB baseline instead of failing hard.
            log.warning("DB demand model inference failed; falling back to DB_MOVING_AVG_V1. Error: %s", exc)

    for (group_label, district, commodity), pts in series.items():
        pts.sort(key=lambda x: (x[0], x[1]))
        tail = pts[-3:]
        qtys = [p[2] for p in tail]
        ma = sum(qtys) / max(len(qtys), 1)
        growth = 0.0
        if len(tail) >= 2 and tail[0][2] > 0:
            growth = (tail[-1][2] - tail[0][2]) / tail[0][2]
        base = max(ma * (1.0 + growth * 0.25), 0.0)

        mean = ma
        if len(qtys) >= 2 and mean > 0:
            var = sum((x - mean) ** 2 for x in qtys) / len(qtys)
            std = var ** 0.5
            vol = min(std / mean, 1.0)
        else:
            vol = 0.0
        conf = round(max(0.55, min(0.9, 0.82 - vol * 0.25)), 2)

        for i in range(1, body.future_periods + 1):
            fy, fm = _advance(max_y, max_m, i)
            pred = base * (1.0 + 0.01 * (i - 1))
            band = pred * (0.10 + vol * 0.15)
            predictions_out.append({
                "location": group_label,
                "district": district,
                "commodity": commodity,
                "date": _date_str(fy, fm),
                "predicted_demand": round(pred, 2),
                "lower_bound": round(max(pred - band, 0.0), 2),
                "upper_bound": round(pred + band, 2),
                "confidence_score": conf,
                "model_used": "DB_MOVING_AVG_V1",
            })

    return {
        "module": "SMARTAllot",
        "future_periods": body.future_periods,
        "filters": {
            "year": body.year,
            "month": body.month,
            "district": body.district,
            "afso": body.afso,
            "fps_id": body.fps_id,
            "commodity": body.commodity,
        },
        "count": len(predictions_out),
        "predictions": predictions_out,
    }


# ── Optimize allocation ────────────────────────────────────────────────────────

@app.post("/api/smart-allot/optimize-allocation")
def optimize(body: OptimizeRequest, db: Session = Depends(get_db)):
    """
    Run LP-based allocation on predicted demand.
    Returns per-location recommended allocations with risk metrics.
    """
    ml = _try_import_ml_modules()
    pd = ml["pd"]
    AllocationConfig = ml["AllocationConfig"]
    optimize_allocation = ml["optimize_allocation"]
    results_to_dataframe = ml["results_to_dataframe"]
    estimate_required_supply = ml["estimate_required_supply"]

    predictions = None
    if body.source == "uploaded" and STATE.forecaster is not None and STATE.forecaster.is_trained and STATE.df is not None:
        predictions = STATE.forecaster.predict_future(
            future_periods=body.future_periods,
            reference_df=STATE.df,
        )

    # DB fallback: build per-FPS forecast from last months in TransactionRecord
    if not predictions:
        from shared.models import TransactionRecord
        from sqlalchemy import func

        month_order = ["January","February","March","April","May","June","July","August","September","October","November","December"]
        month_idx = {m: i+1 for i, m in enumerate(month_order)}

        # Aggregate per fps_id × district × afso × commodity × (year, month)
        q = (
            db.query(
                TransactionRecord.year,
                TransactionRecord.month,
                TransactionRecord.district,
                TransactionRecord.afso,
                TransactionRecord.fps_id,
                TransactionRecord.commodity,
                func.sum(TransactionRecord.quantity_kgs).label("qty"),
            )
            .group_by(
                TransactionRecord.year,
                TransactionRecord.month,
                TransactionRecord.district,
                TransactionRecord.afso,
                TransactionRecord.fps_id,
                TransactionRecord.commodity,
            )
        )
        if body.year:
            q = q.filter(TransactionRecord.year == body.year)
        if body.district:
            q = q.filter(TransactionRecord.district == body.district)
        if body.afso:
            q = q.filter(TransactionRecord.afso == body.afso)
        if body.fps_id:
            q = q.filter(TransactionRecord.fps_id == body.fps_id)
        if body.commodity:
            q = q.filter(TransactionRecord.commodity == body.commodity)
        rows = q.all()
        if not rows:
            raise HTTPException(status_code=404, detail="No transaction data found to build allocation plan.")

        # As-of cutoff: if only month is provided, assume max year in scope.
        as_of_year = body.year
        as_of_month = body.month
        if as_of_month and as_of_year is None:
            as_of_year = max(int(r.year) for r in rows)
        as_of_pair: tuple[int, int] | None = None
        if as_of_year and as_of_month and as_of_month in month_idx:
            as_of_pair = (int(as_of_year), int(month_idx[as_of_month]))

        series: dict[tuple[str, str, str, str], list[tuple[int, int, float]]] = {}
        max_y, max_m = (0, 1)
        for r in rows:
            mi = month_idx.get(str(r.month), 1)
            if as_of_pair is not None and (int(r.year), mi) > as_of_pair:
                continue
            max_y, max_m = max((max_y, max_m), (int(r.year), mi))
            key = (r.district, r.afso, r.fps_id, r.commodity)
            series.setdefault(key, []).append((int(r.year), mi, float(r.qty or 0.0)))

        if not series:
            raise HTTPException(status_code=404, detail="No transaction data found within the selected month/year scope.")

        def _advance(y: int, m: int, steps: int) -> tuple[int, int]:
            total = (y * 12 + (m - 1)) + steps
            return total // 12, (total % 12) + 1

        def _date_str(y: int, m: int) -> str:
            return f"{y:04d}-{m:02d}-01"

        predictions = []
        for (district, mandal, fps_id, commodity), pts in series.items():
            pts.sort(key=lambda x: (x[0], x[1]))
            tail = pts[-3:]
            qtys = [p[2] for p in tail]
            ma = sum(qtys) / max(len(qtys), 1)
            base = max(ma, 0.0)
            for i in range(1, body.future_periods + 1):
                fy, fm = _advance(max_y, max_m, i)
                predictions.append({
                    "location": f"{district}/{mandal}/{fps_id}",
                    "district": district,
                    "mandal": mandal,
                    "fps_id": fps_id,
                    "commodity": commodity,
                    "date": _date_str(fy, fm),
                    "predicted_demand": round(base, 2),
                    "lower_bound": round(base * 0.9, 2),
                    "upper_bound": round(base * 1.1, 2),
                    "confidence_score": 0.7,
                    "model_used": "DB_MOVING_AVG_V1",
                })

    # Build forecast DataFrame for optimizer
    forecast_df = pd.DataFrame(predictions)

    cfg = AllocationConfig(
        shortage_weight=body.shortage_weight,
        overstock_weight=body.overstock_weight,
        safety_buffer_pct=body.safety_buffer_pct,
    )

    results = optimize_allocation(
        forecast_df,
        total_supply_by_commodity=body.total_supply,
        cfg=cfg,
    )

    results_df = results_to_dataframe(results)
    required = estimate_required_supply(forecast_df, cfg)

    summary = {
        "total_predicted_demand": round(float(results_df["predicted_demand"].sum()), 1),
        "total_recommended_allocation": round(float(results_df["recommended_allocation"].sum()), 1),
        "avg_shortage_risk_pct": round(float(results_df["shortage_risk_pct"].mean()), 2),
        "avg_overstock_risk_pct": round(float(results_df["overstock_risk_pct"].mean()), 2),
        "estimated_required_supply": required,
        "supply_provided": body.total_supply or "unlimited",
    }

    return {
        "module": "SMARTAllot",
        "summary": summary,
        "allocations": [asdict(r) for r in results],
    }


# ── Anomaly detection ──────────────────────────────────────────────────────────

@app.get("/api/smart-allot/anomalies")
def anomalies(
    district:  Optional[str] = Query(default=None),
    commodity: Optional[str] = Query(default=None),
    severity:  Optional[str] = Query(default=None),
    limit:     int           = Query(default=100, ge=1, le=5000),
    source:    str           = Query(default="db", enum=["db", "uploaded"]),
    db: Session = Depends(get_db),
):
    """Detect anomalous demand records in the loaded dataset."""
    # Only use uploaded dataset if explicitly requested
    if source == "uploaded" and STATE.df is not None:
        ml = _try_import_ml_modules()
        AnomalyDetector = ml["AnomalyDetector"]

        df = STATE.df.copy()
        if district:
            df = df[df["district"].str.lower() == district.lower()]
        if commodity:
            df = df[df["commodity"].str.lower() == commodity.lower()]

        detector = STATE.detector or AnomalyDetector()
        if STATE.detector is None:
            detector.fit(df)

        scored = detector.detect(df)
        anomalous = scored[scored["is_anomaly"]].copy()

        if severity:
            anomalous = anomalous[anomalous["severity"].str.upper() == severity.upper()]

        anomalous = anomalous.sort_values("anomaly_score", ascending=False).head(limit)

        records = []
        for _, row in anomalous.iterrows():
            records.append({
                "fps_id":        row.get("fps_id", ""),
                "district":      row.get("district", ""),
                "mandal":        row.get("mandal", ""),
                "commodity":     row.get("commodity", ""),
                "date":          str(row.get("date", ""))[:10],
                "demand_kg":     round(float(row.get("demand_kg", 0)), 1),
                "anomaly_score": round(float(row.get("anomaly_score", 0)), 3),
                "severity":      row.get("severity", "LOW"),
                "reasons":       row.get("anomaly_reasons", []),
                "is_anomaly":    bool(row.get("is_anomaly", False)),
            })

        total_scored = len(scored)
        total_anomalies = int(scored["is_anomaly"].sum())
        severity_counts = scored[scored["is_anomaly"]]["severity"].value_counts().to_dict()

        return {
            "module": "SMARTAllot",
            "total_records_scanned": total_scored,
            "total_anomalies": total_anomalies,
            "anomaly_rate_pct": round(total_anomalies / max(total_scored, 1) * 100, 2),
            "severity_breakdown": severity_counts,
            "returned": len(records),
            "anomalies": records,
        }

    # Default: transaction-record anomalies from the shared DB
    result = tx_svc.get_anomalies(
        db, year=None, month=None, district=district, afso=None, fps_id=None, commodity=commodity, threshold_std=2.0, limit=limit
    )
    records = []
    sev_counts: dict[str, int] = {}
    for a in result["anomalies"]:
        sev = str(a["severity"]).upper()
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
        # Convert month/year to an ISO-ish date
        month_order = ["January","February","March","April","May","June","July","August","September","October","November","December"]
        try:
            m = month_order.index(a["month"]) + 1
        except ValueError:
            m = 1
        records.append({
            "fps_id": a["fps_id"],
            "district": a["district"],
            "mandal": a["afso"],
            "commodity": a["commodity"],
            "date": f"{a['year']:04d}-{m:02d}-01",
            "demand_kg": round(float(a["quantity_kgs"]), 1),
            "anomaly_score": 0.9 if sev == "CRITICAL" else 0.7 if sev == "HIGH" else 0.5 if sev == "MEDIUM" else 0.3,
            "severity": sev,
            "reasons": [a["detail"]],
            "is_anomaly": True,
        })

    return {
        "module": "SMARTAllot",
        "total_records_scanned": int(result.get("records_scanned", 0)),
        "total_anomalies": int(result.get("total", 0)),
        "anomaly_rate_pct": float(result.get("anomaly_rate_pct", 0.0)),
        "severity_breakdown": sev_counts,
        "returned": len(records),
        "anomalies": records,
    }


# ── Retrain ────────────────────────────────────────────────────────────────────

@app.post("/api/smart-allot/retrain")
def retrain(body: RetrainRequest):
    """
    Full retraining pipeline:
    1. Preprocess loaded dataset
    2. Train Ridge baseline
    3. Train anomaly detector
    4. Generate evaluation report
    5. Save all artifacts to models/
    """
    if STATE.df is None and not DEFAULT_DATASET.exists():
        raise HTTPException(status_code=503, detail="No dataset available. POST to /upload-data first.")

    t0 = time.time()
    ml = _try_import_ml_modules()
    SmartAllotForecaster = ml["SmartAllotForecaster"]
    AnomalyDetector = ml["AnomalyDetector"]
    generate_eval_report = ml["generate_eval_report"]


    # Use currently loaded or reload default
    dataset_path = STATE.dataset_path or str(DEFAULT_DATASET)
    try:
        pipeline = ml["run_pipeline"](dataset_path, test_months=body.test_months)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Pipeline failed: {exc}")

    STATE.df    = pipeline["full_df"]
    STATE.raw   = pipeline["raw"]
    STATE.train = pipeline["train"]
    STATE.test  = pipeline["test"]

    # Train forecaster
    forecaster = SmartAllotForecaster(models_dir=MODELS_DIR)
    metrics = forecaster.fit(STATE.train, STATE.test)
    forecaster.save()
    STATE.forecaster = forecaster

    # Train anomaly detector
    detector = AnomalyDetector()
    detector.fit(STATE.df)
    import joblib
    joblib.dump(detector, MODELS_DIR / "anomaly_detector.pkl")
    STATE.detector = detector

    # Anomaly count in training data
    scored = detector.detect(STATE.df)
    anomaly_count = int(scored["is_anomaly"].sum())

    # Full eval report
    report = generate_eval_report(STATE.train, STATE.test, forecaster.baseline)
    report["anomalies_in_training_set"] = anomaly_count
    report["training_duration_seconds"] = round(time.time() - t0, 1)
    EVAL_REPORT_PATH.write_text(json.dumps(report, indent=2))
    from datetime import datetime

    STATE.last_trained = datetime.now().isoformat()

    # Train the DB-backed demand model (clean_transactions.csv) so chatbot + UI can show
    # training curves, confusion matrix, and real ML predictions on the dataset.
    db_demand = None
    if body.train_db_demand_model:
        try:
            csv_path = _ROOT / "dataset" / "clean_transactions.csv"
            if csv_path.exists():
                trained = db_demand_model.train_from_clean_transactions(csv_path)
                db_demand = {
                    "status": "trained",
                    "trained_at": trained.trained_at,
                    "metrics_path": str(db_demand_model.METRICS_PATH),
                    "plots": trained.metrics.get("plots", []),
                }
            else:
                db_demand = {"status": "skipped", "reason": "dataset/clean_transactions.csv not found"}
        except Exception as exc:
            db_demand = {"status": "error", "error": str(exc)}

    return {
        "module": "SMARTAllot",
        "status": "retrained",
        "train_rows": len(STATE.train),
        "test_rows": len(STATE.test),
        "metrics": metrics,
        "anomalies_detected_in_training": anomaly_count,
        "training_duration_seconds": report["training_duration_seconds"],
        "artifacts_saved_to": str(MODELS_DIR),
        "db_demand_model": db_demand,
    }


# ── Model info ─────────────────────────────────────────────────────────────────

@app.get("/api/smart-allot/model-info")
def model_info():
    """Current model status and evaluation metrics."""
    trained = STATE.forecaster is not None and STATE.forecaster.is_trained

    eval_report = {}
    if EVAL_REPORT_PATH.exists():
        eval_report = json.loads(EVAL_REPORT_PATH.read_text())

    db_metrics = db_demand_model.load_metrics() or {}

    return {
        "module": "SMARTAllot",
        "models_trained": trained,
        "models_directory": str(MODELS_DIR),
        "dataset_loaded": STATE.df is not None,
        "dataset_path": STATE.dataset_path,
        "last_trained": STATE.last_trained,
        "baseline_available": (MODELS_DIR / "baseline.pkl").exists(),
        "prophet_available": (MODELS_DIR / "prophet" / "prophet_meta.json").exists(),
        "anomaly_detector_available": (MODELS_DIR / "anomaly_detector.pkl").exists(),
        "overall_metrics": eval_report.get("overall_metrics", {}),
        "improvement_over_naive": eval_report.get("improvement_over_naive", {}),
        "db_demand_model_available": db_demand_model.is_trained(),
        "db_demand_model_metrics": {
            "trained_at_utc": db_metrics.get("trained_at_utc"),
            "rows_long": db_metrics.get("rows_long"),
            "rows_trainable": db_metrics.get("rows_trainable"),
            "regression": db_metrics.get("regression"),
            "classification_movement": {
                "labels": (db_metrics.get("classification_movement") or {}).get("labels"),
            },
            "plots": db_metrics.get("plots", []),
        },
    }


@app.post("/api/smart-allot/train-demand-model")
def train_demand_model():
    """
    Train the DB-backed demand forecast model from dataset/clean_transactions.csv.
    Produces plots: training curve, residuals, learning curve, feature importance,
    confusion matrix, ROC and PR curves.
    """
    csv_path = _ROOT / "dataset" / "clean_transactions.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset not found: {csv_path}")

    try:
        trained = db_demand_model.train_from_clean_transactions(csv_path)
        return {
            "module": "SMARTAllot",
            "status": "trained",
            "trained_at": trained.trained_at,
            "metrics_path": str(db_demand_model.METRICS_PATH),
            "plots": trained.metrics.get("plots", []),
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Training failed: {exc}")


@app.get("/api/smart-allot/demand-model/plots/{filename}")
def demand_model_plot(filename: str):
    """Serve generated evaluation plots as PNG (for the frontend dashboard)."""
    safe = Path(filename).name
    path = db_demand_model.PLOTS_DIR / safe
    if not path.exists() or path.suffix.lower() != ".png":
        raise HTTPException(status_code=404, detail="Plot not found")
    return FileResponse(path)


# ── Evaluation report ──────────────────────────────────────────────────────────

@app.get("/api/smart-allot/eval-report")
def eval_report():
    """Full evaluation report including per-district and per-commodity breakdown."""
    if not EVAL_REPORT_PATH.exists():
        raise HTTPException(status_code=404, detail="No evaluation report found. POST to /retrain first.")
    report = json.loads(EVAL_REPORT_PATH.read_text())
    return {"module": "SMARTAllot", "report": report}


# ── Trends (aggregated time-series) ───────────────────────────────────────────

@app.get("/api/smart-allot/trends")
def trends(
    level:     str           = Query(default="district", enum=["district", "mandal", "fps"]),
    district:  Optional[str] = Query(default=None),
    commodity: Optional[str] = Query(default=None),
):
    """Return aggregated time-series data for trend charts."""
    if STATE.df is None:
        raise HTTPException(status_code=503, detail="No dataset loaded.")

    ml = _try_import_ml_modules()
    aggregate = ml["aggregate"]

    df = STATE.raw if STATE.raw is not None else STATE.df
    if district:
        df = df[df["district"].str.lower() == district.lower()]
    if commodity:
        df = df[df["commodity"].str.lower() == commodity.lower()]

    agg = aggregate(df.copy(), level=level)
    agg["date"] = agg["date"].astype(str)

    return {
        "module": "SMARTAllot",
        "level": level,
        "filters": {"district": district, "commodity": commodity},
        "rows": len(agg),
        "data": agg.to_dict(orient="records"),
    }


# ── Download allocation plan ───────────────────────────────────────────────────

@app.post("/api/smart-allot/optimize-allocation/download")
def download_allocation(body: OptimizeRequest):
    """Run optimization and return results as a CSV file download."""
    result = optimize(body)
    allocations = result["allocations"]
    pd = _try_import_pandas()
    df_out = pd.DataFrame(allocations)
    csv_bytes = df_out.to_csv(index=False).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=allocation_plan.csv"},
    )


# ── DB-backed routes (fallback) ────────────────────────────────────────────────

@app.get("/api/smart-allot/recommendations")
def recommendations(
    district_name: Optional[str] = Query(default=None),
    district_code: Optional[int] = Query(default=None),
    item_name:     Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(optional_current_user),
):
    return {
        "module": "SMARTAllot",
        "source": "ml_artifacts_or_db",
        "filters": {"district_name": district_name, "district_code": district_code, "item_name": item_name},
        "recommendations": db_recommendations(db, user=user, district_name=district_name, district_code=district_code, item_name=item_name),
    }


@app.get("/api/smart-allot/summary")
def summary(
    district_name: Optional[str] = Query(default=None),
    district_code: Optional[int] = Query(default=None),
    item_name:     Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(optional_current_user),
):
    # Augment with live ML data if available
    db_sum = db_summary(db, user=user, district_name=district_name, district_code=district_code, item_name=item_name)
    extra = {}
    if STATE.df is not None:
        df = STATE.df
        extra = {
            "dataset_rows": len(df),
            "date_range": f"{df['date'].min().date()} to {df['date'].max().date()}",
            "fps_count": df["fps_id"].nunique(),
            "districts_covered": df["district"].nunique(),
        }
    return {"module": "SMARTAllot", "summary": db_sum, "dataset": extra}


@app.get("/api/smart-allot/model-info-ml")
def model_info_ml():
    """ML artifact info from the original training pipeline."""
    try:
        return {"module": "SMARTAllot", "model_info": get_model_info()}
    except FileNotFoundError:
        return {"module": "SMARTAllot", "model_info": None, "note": "ML artifacts not found in ml/smart_allot/artifacts/"}


@app.get("/api/smart-allot/filters")
def filters(db: Session = Depends(get_db)):
    """
    Filter metadata for the SmartAllot UI.

    Priority:
    1. Shared DB (seeded from dataset/clean_transactions.csv) so filters always match "real" data.
    2. Artifact-based ML file list (if present).
    3. In-memory uploaded dataset (STATE.df) as last fallback.
    """
    try:
        return {"module": "SMARTAllot", "filters": db_filter_metadata(db)}
    except Exception:
        # Keep legacy artifact path for backwards compatibility if DB isn't ready.
        try:
            return {"module": "SMARTAllot", "filters": get_filter_metadata()}
        except FileNotFoundError:
            if STATE.df is not None:
                df = STATE.df
                return {
                    "module": "SMARTAllot",
                    "filters": {
                        "district_names": sorted(df["district"].unique().tolist()),
                        "commodities": sorted(df["commodity"].unique().tolist()),
                        "mandals": sorted(df["mandal"].unique().tolist()),
                    },
                }
            return {"module": "SMARTAllot", "filters": {}}


# ── Transaction / Distribution endpoints (real CSV data) ──────────────────────

from shared.services import transactions as tx_svc  # noqa: E402 (late import fine)
from shared.models import TransactionRecord, FPSStockMetric  # noqa: E402


@app.get("/api/transactions/filters")
def transaction_filters(db: Session = Depends(get_db)):
    """
    Returns all unique filter values for cascading dropdowns:
    district → afso → fps_id → month → commodity.
    """
    return {"module": "SMARTAllot", "filters": tx_svc.get_filter_options(db)}


@app.post("/api/transactions/reload")
def transaction_reload(db: Session = Depends(get_db)):
    """
    Force reload of dataset/clean_transactions.csv into the shared DB.

    Useful when the CSV changes but the DB already has rows (seed_data is otherwise idempotent).
    """
    db.query(TransactionRecord).delete()
    db.query(FPSStockMetric).delete()
    db.commit()
    seed_data(db)
    return {
        "module": "SMARTAllot",
        "status": "reloaded",
        "transaction_rows": db.query(TransactionRecord).count(),
        "fps_metric_rows": db.query(FPSStockMetric).count(),
    }


@app.get("/api/transactions/summary")
def transaction_summary(
    year:      Optional[int] = Query(default=None),
    month:     Optional[str] = Query(default=None),
    district:  Optional[str] = Query(default=None),
    afso:      Optional[str] = Query(default=None),
    fps_id:    Optional[str] = Query(default=None),
    commodity: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Aggregated KPI stats for the selected scope."""
    return {
        "module": "SMARTAllot",
        "filters": {"year": year, "month": month, "district": district,
                    "afso": afso, "fps_id": fps_id, "commodity": commodity},
        "summary": tx_svc.get_summary(
            db, year=year, month=month, district=district,
            afso=afso, fps_id=fps_id, commodity=commodity,
        ),
    }


@app.get("/api/transactions")
def transaction_records(
    year:      Optional[int] = Query(default=None),
    month:     Optional[str] = Query(default=None),
    district:  Optional[str] = Query(default=None),
    afso:      Optional[str] = Query(default=None),
    fps_id:    Optional[str] = Query(default=None),
    commodity: Optional[str] = Query(default=None),
    skip:      int            = Query(default=0, ge=0),
    limit:     int            = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Paginated distribution records with full filter support."""
    total, records = tx_svc.get_transactions(
        db, year=year, month=month, district=district,
        afso=afso, fps_id=fps_id, commodity=commodity,
        skip=skip, limit=limit,
    )
    return {
        "module": "SMARTAllot",
        "total": total,
        "skip": skip,
        "limit": limit,
        "records": records,
    }


@app.get("/api/transactions/chart-data")
def transaction_chart_data(
    group_by:  str           = Query(default="district",
                                     enum=["district", "afso", "fps_id", "month"]),
    year:      Optional[int] = Query(default=None),
    month:     Optional[str] = Query(default=None),
    district:  Optional[str] = Query(default=None),
    afso:      Optional[str] = Query(default=None),
    fps_id:    Optional[str] = Query(default=None),
    commodity: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Chart-ready data grouped by district / afso / fps_id / month."""
    return {
        "module": "SMARTAllot",
        "chart_data": tx_svc.get_chart_data(
            db, group_by=group_by, year=year, month=month,
            district=district, afso=afso, fps_id=fps_id, commodity=commodity,
        ),
    }


@app.get("/api/transactions/fps-detail/{fps_id}")
def fps_detail(
    fps_id: str,
    year:   Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Full monthly × commodity breakdown for a single FPS."""
    detail = tx_svc.get_fps_detail(db, fps_id=fps_id, year=year)
    if not detail:
        raise HTTPException(status_code=404, detail=f"FPS '{fps_id}' not found.")
    return {"module": "SMARTAllot", "detail": detail}


@app.get("/api/transactions/anomalies")
def transaction_anomalies(
    year:          Optional[int]   = Query(default=None),
    month:         Optional[str]   = Query(default=None),
    district:      Optional[str]   = Query(default=None),
    afso:          Optional[str]   = Query(default=None),
    fps_id:        Optional[str]   = Query(default=None),
    commodity:     Optional[str]   = Query(default=None),
    threshold_std: float           = Query(default=2.0, ge=0.5, le=5.0),
    limit:         int             = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """
    Detect real anomalies from distribution data:
    ZERO_DISTRIBUTION, LOW_DRAWL_RATIO, OUTLIER_HIGH, OUTLIER_LOW.
    Supports full District → AFSO → FPS → Month → Commodity filter cascade.
    """
    result = tx_svc.get_anomalies(
        db, year=year, month=month, district=district,
        afso=afso, fps_id=fps_id, commodity=commodity,
        threshold_std=threshold_std, limit=limit,
    )
    return {"module": "SMARTAllot", **result}


@app.get("/api/transactions/map-data")
def transaction_map_data(
    level:     str           = Query(default="district",
                                     enum=["district", "afso", "fps"]),
    year:      Optional[int] = Query(default=None),
    month:     Optional[str] = Query(default=None),
    district:  Optional[str] = Query(default=None),
    afso:      Optional[str] = Query(default=None),
    fps_id:    Optional[str] = Query(default=None),
    commodity: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Geographic aggregates with lat/lng for map visualisation.
    level=district → 2 markers (Annamayya, Chittoor)
    level=afso     → up to 51 AFSO markers
    level=fps      → top 50 FPS by quantity
    """
    markers = tx_svc.get_map_data(
        db, level=level, year=year, month=month,
        district=district, afso=afso, fps_id=fps_id, commodity=commodity,
    )
    return {"module": "SMARTAllot", "level": level, "markers": markers}


@app.get("/api/transactions/fps-list")
def transaction_fps_list(
    year:      Optional[int] = Query(default=None),
    month:     Optional[str] = Query(default=None),
    district:  Optional[str] = Query(default=None),
    afso:      Optional[str] = Query(default=None),
    commodity: Optional[str] = Query(default=None),
    skip:      int            = Query(default=0, ge=0),
    limit:     int            = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Paginated FPS summary with total_qty_kgs, cards and months_active."""
    total, fps = tx_svc.get_fps_list(
        db, year=year, month=month, district=district,
        afso=afso, commodity=commodity, skip=skip, limit=limit,
    )
    return {"module": "SMARTAllot", "total": total, "skip": skip,
            "limit": limit, "fps_list": fps}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
