from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.auth.scope import scope_for_fps
from shared.models import FPSStockMetric, TransactionRecord
from shared.schemas import (
    SmartAllotFilterMetadata,
    SmartAllotMLRecommendation,
    SmartAllotRecommendation,
    SmartAllotSummary,
)
from shared.services.smart_allot_ml import get_recommendations as get_ml_recommendations
from shared.services.smart_allot_ml import get_summary as get_ml_summary

if TYPE_CHECKING:
    from shared.auth.dependencies import CurrentUser

MONTH_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _average(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def _recent_growth(history: list[int]) -> float:
    if len(history) < 2:
        return 0
    recent = history[-3:]
    return 0 if recent[0] == 0 else (recent[-1] - recent[0]) / recent[0]


def build_recommendation(record: FPSStockMetric) -> SmartAllotRecommendation:
    ma = _average(record.monthly_drawal[-3:])
    growth = _recent_growth(record.monthly_drawal)
    forecast = round(ma * record.seasonal_index * (1 + growth * 0.35))
    safety_stock = round(forecast * 0.15 + record.lead_time_days * 6)
    recommended_allotment = max(forecast + safety_stock - record.current_stock, 0)
    stock_coverage_days = round((record.current_stock / max(forecast, 1)) * 30, 1)
    shortage_risk = round(_clamp((forecast + safety_stock - record.current_stock) / max(forecast + safety_stock, 1), 0, 1), 2)
    overstock_risk = round(_clamp((record.current_stock - forecast) / max(record.current_stock, 1), 0, 1), 2)
    confidence_score = round(_clamp(0.72 + (len(record.monthly_drawal) / 100), 0, 0.94), 2)
    return SmartAllotRecommendation(
        fps_id=record.fps_id, fps_name=record.fps_name,
        district=record.district, mandal=record.mandal, commodity=record.commodity,
        beneficiary_count=record.beneficiary_count, current_stock=record.current_stock,
        forecast=forecast, safety_stock=safety_stock, recommended_allotment=recommended_allotment,
        stock_coverage_days=stock_coverage_days, shortage_risk=shortage_risk,
        overstock_risk=overstock_risk, confidence_score=confidence_score,
        explanation=[
            f"Recent average drawal is {round(ma)} units.",
            f"Seasonal factor applied: {record.seasonal_index}.",
            f"Lead time of {record.lead_time_days} days increases safety stock.",
        ],
    )


def _district_code(district: str) -> int:
    import hashlib

    # Stable, deterministic code for filtering; not an official govt code.
    return int(hashlib.md5(district.encode("utf-8")).hexdigest()[:6], 16) % 100000


def _next_month(year: int, month: str) -> tuple[int, str]:
    try:
        idx = MONTH_ORDER.index(month)
    except ValueError:
        # Unknown month string, just return as-is.
        return year, month
    if idx == 11:
        return year + 1, MONTH_ORDER[0]
    return year, MONTH_ORDER[idx + 1]


def _db_has_transactions(db: Session) -> bool:
    return bool(db.query(TransactionRecord.id).limit(1).first())


def get_filter_metadata_db(db: Session) -> SmartAllotFilterMetadata:
    """
    DB-backed filter metadata for SmartAllot (districts + commodities).
    This replaces the artifact-based list so UI always reflects the dataset in Postgres/SQLite.
    """
    rows = (
        db.query(TransactionRecord.district, TransactionRecord.commodity)
        .distinct()
        .all()
    )
    districts = sorted({r.district for r in rows})
    items = sorted({r.commodity for r in rows})
    return SmartAllotFilterMetadata(
        district_names=districts,
        district_codes=sorted({_district_code(d) for d in districts}),
        items=items,
    )


def _recommendations_from_db(
    db: Session,
    *,
    district_name: str | None = None,
    item_name: str | None = None,
) -> list[SmartAllotMLRecommendation]:
    """
    Generate SmartAllot recommendations directly from TransactionRecord.

    Why: artifact files go stale and can mismatch UI expectations. This path always reflects
    what's in the shared DB (seeded from dataset/clean_transactions.csv).
    """
    q = (
        db.query(
            TransactionRecord.year,
            TransactionRecord.month,
            TransactionRecord.district,
            TransactionRecord.commodity,
            func.sum(TransactionRecord.quantity_kgs).label("qty_kgs"),
            func.max(TransactionRecord.cards).label("cards"),
        )
        .group_by(
            TransactionRecord.year,
            TransactionRecord.month,
            TransactionRecord.district,
            TransactionRecord.commodity,
        )
    )
    if district_name:
        q = q.filter(TransactionRecord.district == district_name)
    if item_name:
        q = q.filter(TransactionRecord.commodity == item_name)

    # When requesting "All Districts", reduce memory pressure by focusing on the
    # most recent months in the dataset. Forecasting based on very old history
    # isn't useful for the UI and can trigger MemoryError on low-RAM machines.
    #
    # We still keep the full history when a district is explicitly filtered.
    if district_name is None:
        years = [y for (y,) in db.query(TransactionRecord.year).distinct().all()]
        if years:
            max_year = max(int(y) for y in years)
            q = q.filter(TransactionRecord.year >= max_year - 1)

    # `q.all()` can be memory-heavy if the DB has a lot of distinct
    # (year, month, district, commodity) tuples and the machine is low on RAM.
    # Stream rows in chunks instead to keep the service responsive.
    rows = q.yield_per(2000)
    # With streaming results we can't rely on truthiness; we build `series`
    # and check at the end.

    # Build time series per (district, commodity)
    series: dict[tuple[str, str], list[tuple[int, str, float, int]]] = {}
    for r in rows:
        series.setdefault((r.district, r.commodity), []).append(
            (int(r.year), str(r.month), float(r.qty_kgs or 0.0), int(r.cards or 0))
        )
    if not series:
        return []

    recs: list[SmartAllotMLRecommendation] = []
    for (district, commodity), points in series.items():
        # Sort by (year, month index)
        def _k(p):
            y, m, *_ = p
            try:
                mi = MONTH_ORDER.index(m)
            except ValueError:
                mi = 99
            return (y, mi)

        points.sort(key=_k)
        last_year, last_month, last_qty, last_cards = points[-1]

        # Use last up to 3 observations for moving-average + trend
        tail = points[-3:]
        qtys = [p[2] for p in tail]
        ma = sum(qtys) / max(len(qtys), 1)
        growth = 0.0
        if len(tail) >= 2 and tail[0][2] > 0:
            growth = (tail[-1][2] - tail[0][2]) / tail[0][2]

        forecast = max(ma * (1.0 + growth * 0.25), 0.0)

        # Volatility proxy: coefficient of variation (std/mean) on the tail window
        mean = ma
        if len(qtys) >= 2 and mean > 0:
            var = sum((x - mean) ** 2 for x in qtys) / len(qtys)
            std = var ** 0.5
            volatility = std / mean
        else:
            volatility = 0.0

        # Safety stock: base 12% + extra 8% scaled by volatility
        safety_stock = forecast * (0.12 + min(volatility, 1.0) * 0.08)

        # Carryover proxy: assume 18% of last month remains available (simple proxy)
        carryover = last_qty * 0.18

        recommended = max(forecast + safety_stock - carryover, 0.0)

        f_year, f_month = _next_month(last_year, last_month)
        recs.append(SmartAllotMLRecommendation(
            forecast_for_month=f"{f_month} {f_year}",
            state_name="Andhra Pradesh",
            district_name=district,
            district_code=_district_code(district),
            item_name=commodity,
            forecast_next_month=float(round(forecast, 2)),
            safety_stock=float(round(safety_stock, 2)),
            carryover_stock_proxy=float(round(carryover, 2)),
            recommended_allotment=float(round(recommended, 2)),
            volatility_proxy=float(round(volatility, 4)),
            last_month_distributed=float(round(last_qty, 2)),
            last_month_allocated=float(round(last_qty, 2)),
            model_strategy="DB_MOVING_AVG_V1",
        ))

    recs.sort(key=lambda r: (r.district_name, r.item_name, r.forecast_for_month))
    return recs


def _scoped_fps_records(db: Session, user: Optional["CurrentUser"]) -> list[FPSStockMetric]:
    q = db.query(FPSStockMetric)
    for col, val in scope_for_fps(user).items():
        q = q.filter(getattr(FPSStockMetric, col) == val)
    return q.order_by(FPSStockMetric.fps_id).all()


def get_recommendations(
    db: Session,
    user: Optional["CurrentUser"] = None,
    district_name: str | None = None,
    district_code=None,
    item_name: str | None = None,
):
    scope = scope_for_fps(user)
    # If UI sends no district ("All Districts"), we normally apply the user's scope.
    # However, when the database only contains a subset of districts (e.g. demo dataset),
    # a scoped district that isn't present would incorrectly yield an empty result set.
    effective_district = district_name or scope.get("district")
    if district_name is None and effective_district:
        exists = (
            db.query(TransactionRecord.id)
            .filter(TransactionRecord.district == effective_district)
            .limit(1)
            .first()
        )
        if not exists:
            effective_district = None

    # Preferred path: build from DB so the UI always reflects the real dataset.
    # Only use this path when the DB actually returns matching rows; if filters produce nothing
    # (e.g. commodity "Fine Rice" not in old seeded data) fall through to ML CSV.
    if _db_has_transactions(db):
        recs = _recommendations_from_db(
            db,
            district_name=effective_district,
            item_name=item_name,
        )
        if recs:
            return recs

    # Fallback path: artifact-based ML recommendations (if present) or demo FPS metrics.
    try:
        return get_ml_recommendations(
            district_name=effective_district,
            district_code=district_code,
            item_name=item_name,
        )
    except FileNotFoundError:
        records = _scoped_fps_records(db, user)
        return [build_recommendation(r) for r in records]


def get_summary(
    db: Session,
    user: Optional["CurrentUser"] = None,
    district_name: str | None = None,
    district_code=None,
    item_name: str | None = None,
) -> SmartAllotSummary:
    scope = scope_for_fps(user)
    effective_district = district_name or scope.get("district")
    if district_name is None and effective_district:
        exists = (
            db.query(TransactionRecord.id)
            .filter(TransactionRecord.district == effective_district)
            .limit(1)
            .first()
        )
        if not exists:
            effective_district = None

    # Preferred: DB recommendations (same objects as frontend expects)
    if _db_has_transactions(db):
        recs = _recommendations_from_db(db, district_name=effective_district, item_name=item_name)
        total_forecast = round(sum(r.forecast_next_month for r in recs))
        total_allotment = round(sum(r.recommended_allotment for r in recs))
        high_risk = [
            r for r in recs
            if r.forecast_next_month > 0
            and (r.recommended_allotment - r.forecast_next_month) / r.forecast_next_month >= 0.08
        ]
        highest = max(high_risk, key=lambda r: r.recommended_allotment, default=None)
        return SmartAllotSummary(
            total_fps=len(recs),
            total_forecast=total_forecast,
            total_recommended_allotment=total_allotment,
            high_risk_fps=len(high_risk),
            highest_priority=highest,
        )

    # Fallback: artifact ML summary or demo heuristics
    try:
        return get_ml_summary(
            district_name=effective_district,
            district_code=district_code,
            item_name=item_name,
        )
    except FileNotFoundError:
        recommendations = get_recommendations(db, user=user, district_name=district_name, district_code=district_code, item_name=item_name)
        # If we end up here, recommendations may be the demo SmartAllotRecommendation type.
        total_forecast = sum(getattr(r, "forecast", 0) for r in recommendations)
        total_allotment = sum(getattr(r, "recommended_allotment", 0) for r in recommendations)
        high_risk = [r for r in recommendations if getattr(r, "shortage_risk", 0) >= 0.4]
        return SmartAllotSummary(
            total_fps=len(recommendations),
            total_forecast=int(round(total_forecast)),
            total_recommended_allotment=int(round(total_allotment)),
            high_risk_fps=len(high_risk),
            highest_priority=max(high_risk, key=lambda r: getattr(r, "shortage_risk", 0), default=None),
        )
