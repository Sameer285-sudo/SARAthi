from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd

from shared.config import settings
from shared.schemas import (
    SmartAllotFilterMetadata,
    SmartAllotMLRecommendation,
    SmartAllotMetrics,
    SmartAllotModelInfo,
    SmartAllotSummary,
)

ARTIFACTS_DIR = Path(settings.smart_allot_artifacts_dir)
MODEL_PATH = ARTIFACTS_DIR / "smart_allot_model.joblib"
METRICS_PATH = ARTIFACTS_DIR / "model_metrics.json"
RECOMMENDATIONS_PATH = ARTIFACTS_DIR / "andhra_pradesh_recommendations.csv"

# File-mtime caches — auto-reload whenever the artifact files change on disk
_model_mtime: float = 0.0
_model_obj = None

_metrics_mtime: float = 0.0
_metrics_obj: dict | None = None

_recs_mtime: float = 0.0
_recs_df: pd.DataFrame | None = None


def load_model():
    global _model_mtime, _model_obj
    if not MODEL_PATH.exists():
        return None
    mtime = MODEL_PATH.stat().st_mtime
    if _model_obj is None or mtime != _model_mtime:
        _model_obj = joblib.load(MODEL_PATH)
        _model_mtime = mtime
    return _model_obj


def load_metrics_payload() -> dict:
    global _metrics_mtime, _metrics_obj
    if not METRICS_PATH.exists():
        raise FileNotFoundError(f"SMARTAllot metrics file not found: {METRICS_PATH}")
    mtime = METRICS_PATH.stat().st_mtime
    if _metrics_obj is None or mtime != _metrics_mtime:
        _metrics_obj = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        _metrics_mtime = mtime
    return _metrics_obj


def load_recommendations_frame() -> pd.DataFrame:
    global _recs_mtime, _recs_df
    if not RECOMMENDATIONS_PATH.exists():
        raise FileNotFoundError(f"SMARTAllot recommendations file not found: {RECOMMENDATIONS_PATH}")
    mtime = RECOMMENDATIONS_PATH.stat().st_mtime
    if _recs_df is None or mtime != _recs_mtime:
        df = pd.read_csv(RECOMMENDATIONS_PATH)
        df["forecast_for_month"] = df["forecast_for_month"].astype(str)
        _recs_df = df
        _recs_mtime = mtime
    return _recs_df


def _to_records(df: pd.DataFrame) -> list[SmartAllotMLRecommendation]:
    records = []
    for row in df.to_dict(orient="records"):
        records.append(SmartAllotMLRecommendation(
            forecast_for_month=str(row["forecast_for_month"]),
            state_name=str(row["state_name"]),
            district_name=str(row["district_name"]),
            district_code=int(row["district_code"]),
            item_name=str(row["item_name"]),
            forecast_next_month=float(row["forecast_next_month"]),
            safety_stock=float(row["safety_stock"]),
            carryover_stock_proxy=float(row["carryover_stock_proxy"]),
            recommended_allotment=float(row["recommended_allotment"]),
            volatility_proxy=float(row["volatility_proxy"]),
            last_month_distributed=float(row["distributed_qty_lag_1"]),
            last_month_allocated=float(row["allocated_qty_lag_1"]),
            model_strategy=str(row["model_strategy"]),
        ))
    return records


def get_filter_metadata() -> SmartAllotFilterMetadata:
    df = load_recommendations_frame()
    return SmartAllotFilterMetadata(
        district_names=sorted(df["district_name"].dropna().astype(str).unique().tolist()),
        district_codes=sorted(pd.to_numeric(df["district_code"], errors="coerce").dropna().astype(int).unique().tolist()),
        items=sorted(df["item_name"].dropna().astype(str).unique().tolist()),
    )


def get_recommendations(
    district_name: str | None = None,
    district_code: int | None = None,
    item_name: str | None = None,
) -> list[SmartAllotMLRecommendation]:
    df = load_recommendations_frame().copy()
    if district_name:
        df = df[df["district_name"].astype(str).str.lower() == district_name.strip().lower()]
    if district_code is not None:
        df = df[pd.to_numeric(df["district_code"], errors="coerce") == district_code]
    if item_name:
        df = df[df["item_name"].astype(str).str.lower() == item_name.strip().lower()]
    df = df.sort_values(["district_name", "item_name", "forecast_for_month"]).reset_index(drop=True)
    return _to_records(df)


def get_summary(
    district_name: str | None = None,
    district_code: int | None = None,
    item_name: str | None = None,
) -> SmartAllotSummary:
    recommendations = get_recommendations(district_name=district_name, district_code=district_code, item_name=item_name)
    total_forecast = round(sum(r.forecast_next_month for r in recommendations))
    total_allotment = round(sum(r.recommended_allotment for r in recommendations))
    high_risk = [
        r for r in recommendations
        if r.forecast_next_month > 0
        and (r.recommended_allotment - r.forecast_next_month) / r.forecast_next_month >= 0.08
    ]
    highest_priority = max(high_risk, key=lambda r: r.recommended_allotment, default=None)
    return SmartAllotSummary(
        total_fps=len(recommendations),
        total_forecast=total_forecast,
        total_recommended_allotment=total_allotment,
        high_risk_fps=len(high_risk),
        highest_priority=highest_priority,
    )


def get_model_info() -> SmartAllotModelInfo:
    payload = load_metrics_payload()
    model = load_model()
    return SmartAllotModelInfo(
        model_loaded=model is not None,
        model_path=str(MODEL_PATH),
        recommendations_path=str(RECOMMENDATIONS_PATH),
        metrics_path=str(METRICS_PATH),
        dataset=payload["dataset"],
        metrics=SmartAllotMetrics(**payload["metrics"]),
    )
