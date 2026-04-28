"""
shared/services/transactions.py
Query helpers for the TransactionRecord table.
All filters cascade: district → afso → fps_id → month → commodity.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.models import TransactionRecord
from shared.schemas import (
    ChartDataPoint,
    CommodityTotal,
    TransactionChartData,
    TransactionFilterOptions,
    TransactionOut,
    TransactionSummary,
)

# Canonical month order for consistent display
MONTH_ORDER = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def _apply_filters(query, *, year=None, month=None, district=None,
                   afso=None, fps_id=None, commodity=None):
    if year:
        query = query.filter(TransactionRecord.year == year)
    if month:
        query = query.filter(TransactionRecord.month == month)
    if district:
        query = query.filter(TransactionRecord.district == district)
    if afso:
        query = query.filter(TransactionRecord.afso == afso)
    if fps_id:
        query = query.filter(TransactionRecord.fps_id == fps_id)
    if commodity:
        query = query.filter(TransactionRecord.commodity == commodity)
    return query


def get_filter_options(db: Session) -> TransactionFilterOptions:
    """Return all unique filter values with cascading maps for dropdowns."""
    # Fetch the distinct combos we need in one pass
    rows = (
        db.query(
            TransactionRecord.year,
            TransactionRecord.month,
            TransactionRecord.district,
            TransactionRecord.afso,
            TransactionRecord.fps_id,
            TransactionRecord.commodity,
        )
        .distinct()
        .all()
    )

    years: set[int] = set()
    months_seen: set[str] = set()
    districts: set[str] = set()
    afsos: set[str] = set()
    fps_ids: set[str] = set()
    commodities: set[str] = set()
    afsos_by_district: dict[str, set[str]] = defaultdict(set)
    fps_by_afso: dict[str, set[str]] = defaultdict(set)

    for r in rows:
        years.add(r.year)
        months_seen.add(r.month)
        districts.add(r.district)
        afsos.add(r.afso)
        fps_ids.add(r.fps_id)
        commodities.add(r.commodity)
        afsos_by_district[r.district].add(r.afso)
        fps_by_afso[r.afso].add(r.fps_id)

    sorted_months = [m for m in MONTH_ORDER if m in months_seen]

    return TransactionFilterOptions(
        years=sorted(years),
        months=sorted_months,
        districts=sorted(districts),
        afsos=sorted(afsos),
        fps_ids=sorted(fps_ids),
        commodities=sorted(commodities),
        afsos_by_district={d: sorted(a) for d, a in afsos_by_district.items()},
        fps_by_afso={a: sorted(f) for a, f in fps_by_afso.items()},
    )


def get_transactions(
    db: Session,
    *,
    year: Optional[int] = None,
    month: Optional[str] = None,
    district: Optional[str] = None,
    afso: Optional[str] = None,
    fps_id: Optional[str] = None,
    commodity: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
) -> tuple[int, list[TransactionOut]]:
    """Return (total_count, paginated records)."""
    q = db.query(TransactionRecord)
    q = _apply_filters(q, year=year, month=month, district=district,
                       afso=afso, fps_id=fps_id, commodity=commodity)
    total = q.count()
    records = q.order_by(
        TransactionRecord.district,
        TransactionRecord.afso,
        TransactionRecord.fps_id,
        TransactionRecord.month,
        TransactionRecord.commodity,
    ).offset(skip).limit(limit).all()
    return total, [TransactionOut.model_validate(r) for r in records]


def get_summary(
    db: Session,
    *,
    year: Optional[int] = None,
    month: Optional[str] = None,
    district: Optional[str] = None,
    afso: Optional[str] = None,
    fps_id: Optional[str] = None,
    commodity: Optional[str] = None,
) -> TransactionSummary:
    """Aggregate KPIs for the given filters."""
    q = db.query(TransactionRecord)
    q = _apply_filters(q, year=year, month=month, district=district,
                       afso=afso, fps_id=fps_id, commodity=commodity)

    # Total quantity
    total_qty = db.query(func.sum(TransactionRecord.quantity_kgs))
    total_qty = _apply_filters(total_qty, year=year, month=month, district=district,
                               afso=afso, fps_id=fps_id, commodity=commodity)
    total_qty_val = total_qty.scalar() or 0.0

    # Total cards (distinct fps per month, pick max cards per fps)
    cards_q = (
        db.query(
            TransactionRecord.fps_id,
            TransactionRecord.month,
            func.max(TransactionRecord.cards).label("cards"),
        )
    )
    cards_q = _apply_filters(cards_q, year=year, month=month, district=district,
                              afso=afso, fps_id=fps_id, commodity=commodity)
    cards_rows = cards_q.group_by(TransactionRecord.fps_id, TransactionRecord.month).all()
    total_cards = sum(r.cards for r in cards_rows)

    # Commodity breakdown
    commodity_rows = (
        db.query(
            TransactionRecord.commodity,
            func.sum(TransactionRecord.quantity_kgs).label("total"),
        )
    )
    commodity_rows = _apply_filters(commodity_rows, year=year, month=month, district=district,
                                    afso=afso, fps_id=fps_id, commodity=commodity)
    commodity_rows = (
        commodity_rows
        .group_by(TransactionRecord.commodity)
        .order_by(func.sum(TransactionRecord.quantity_kgs).desc())
        .all()
    )

    # Unique fps, months, districts
    fps_count = q.with_entities(TransactionRecord.fps_id).distinct().count()
    months_covered = sorted(
        {r.month for r in q.with_entities(TransactionRecord.month).distinct().all()},
        key=lambda m: MONTH_ORDER.index(m) if m in MONTH_ORDER else 99,
    )
    districts_covered = sorted(
        {r.district for r in q.with_entities(TransactionRecord.district).distinct().all()}
    )

    return TransactionSummary(
        total_fps=fps_count,
        total_cards=total_cards,
        total_quantity_kgs=round(float(total_qty_val), 1),
        commodity_totals=[
            CommodityTotal(commodity=r.commodity, total_kgs=round(float(r.total), 1))
            for r in commodity_rows
        ],
        months_covered=months_covered,
        districts_covered=districts_covered,
    )


def get_chart_data(
    db: Session,
    *,
    group_by: str = "district",   # "district" | "afso" | "fps_id" | "month"
    year: Optional[int] = None,
    month: Optional[str] = None,
    district: Optional[str] = None,
    afso: Optional[str] = None,
    fps_id: Optional[str] = None,
    commodity: Optional[str] = None,
) -> TransactionChartData:
    """Bar/pie chart data grouped by the specified dimension."""
    valid_groups = {"district", "afso", "fps_id", "month"}
    if group_by not in valid_groups:
        group_by = "district"

    group_col = getattr(TransactionRecord, group_by)

    q = (
        db.query(group_col.label("label"),
                 func.sum(TransactionRecord.quantity_kgs).label("value"))
    )
    q = _apply_filters(q, year=year, month=month, district=district,
                       afso=afso, fps_id=fps_id, commodity=commodity)
    q = q.group_by(group_col).order_by(func.sum(TransactionRecord.quantity_kgs).desc())

    if group_by == "fps_id":
        q = q.limit(30)   # cap FPS list in charts

    series = [
        ChartDataPoint(label=str(r.label), value=round(float(r.value), 1))
        for r in q.all()
    ]

    # Monthly trend: quantity per month × commodity
    trend_q = (
        db.query(
            TransactionRecord.month,
            TransactionRecord.commodity,
            func.sum(TransactionRecord.quantity_kgs).label("qty"),
        )
    )
    trend_q = _apply_filters(trend_q, year=year, district=district,
                              afso=afso, fps_id=fps_id, commodity=commodity)
    trend_rows = (
        trend_q
        .group_by(TransactionRecord.month, TransactionRecord.commodity)
        .all()
    )
    monthly_trend = [
        {"month": r.month, "commodity": r.commodity, "quantity_kgs": round(float(r.qty), 1)}
        for r in sorted(trend_rows, key=lambda x: MONTH_ORDER.index(x.month)
                        if x.month in MONTH_ORDER else 99)
    ]

    return TransactionChartData(
        group_by=group_by,
        series=series,
        monthly_trend=monthly_trend,
    )


def get_fps_detail(
    db: Session,
    fps_id: str,
    year: Optional[int] = None,
) -> dict:
    """Full monthly commodity breakdown for a single FPS."""
    q = db.query(TransactionRecord).filter(TransactionRecord.fps_id == fps_id)
    if year:
        q = q.filter(TransactionRecord.year == year)
    rows = q.order_by(TransactionRecord.month, TransactionRecord.commodity).all()
    if not rows:
        return {}

    first = rows[0]
    return {
        "fps_id": fps_id,
        "district": first.district,
        "afso": first.afso,
        "year": first.year,
        "records": [TransactionOut.model_validate(r) for r in rows],
    }


# ── Approximate centroids (District / AFSO level) ─────────────────────────────

# District centroids
DISTRICT_COORDS: dict[str, tuple[float, float]] = {
    "Annamayya": (14.05, 78.75),
    "Chittoor":  (13.22, 79.10),
}

# AFSO approximate centroids — interpolated around district center
# Format: { afso_name: (lat, lng) }
# Computed at import time from a known seed so they don't jitter on reload.
def _afso_coords(afso: str, district: str) -> tuple[float, float]:
    """Deterministic pseudo-random offset within the district bounding box."""
    import hashlib
    h = int(hashlib.md5(afso.encode()).hexdigest(), 16)
    if district == "Annamayya":
        lat = 13.70 + (h % 1000) / 1000 * 0.80   # 13.70 – 14.50
        lng = 78.40 + (h % 997)  / 997  * 0.80   # 78.40 – 79.20
    else:  # Chittoor
        lat = 12.90 + (h % 1000) / 1000 * 0.70   # 12.90 – 13.60
        lng = 78.85 + (h % 997)  / 997  * 0.60   # 78.85 – 79.45
    return round(lat, 4), round(lng, 4)


# ── Anomaly Detection ──────────────────────────────────────────────────────────

def get_anomalies(
    db: Session,
    *,
    year: Optional[int] = None,
    month: Optional[str] = None,
    district: Optional[str] = None,
    afso: Optional[str] = None,
    fps_id: Optional[str] = None,
    commodity: Optional[str] = None,
    threshold_std: float = 2.0,
    limit: int = 500,
) -> dict:
    """
    Detect anomalous distribution records from TransactionRecord data.

    Anomaly types:
      ZERO_DISTRIBUTION  — FPS distributed 0 kg in a month for a commodity
      LOW_DRAWL_RATIO    — qty_kgs / cards < 1.5 kg/card
      OUTLIER_HIGH       — qty > mean + threshold_std × std (per district+commodity)
      OUTLIER_LOW        — qty < mean − threshold_std × std (per district+commodity)
    """
    import math

    q = db.query(TransactionRecord)
    q = _apply_filters(q, year=year, month=month, district=district,
                       afso=afso, fps_id=fps_id, commodity=commodity)
    rows = q.all()

    if not rows:
        return {"total": 0, "anomalies": [], "summary": {}}

    # Build district×commodity statistics for outlier detection
    from collections import defaultdict
    stats: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        if r.quantity_kgs > 0:
            stats[(r.district, r.commodity)].append(r.quantity_kgs)

    def _mean_std(vals: list[float]) -> tuple[float, float]:
        if len(vals) < 2:
            return (vals[0] if vals else 0.0), 0.0
        m = sum(vals) / len(vals)
        variance = sum((x - m) ** 2 for x in vals) / len(vals)
        return m, math.sqrt(variance)

    stat_map: dict[tuple, tuple[float, float]] = {
        k: _mean_std(v) for k, v in stats.items()
    }

    anomalies = []
    for r in rows:
        issues: list[dict] = []
        key = (r.district, r.commodity)
        mean, std = stat_map.get(key, (0.0, 0.0))

        # 1. Zero distribution
        if r.quantity_kgs == 0 and r.cards > 0:
            issues.append({
                "type": "ZERO_DISTRIBUTION",
                "severity": "HIGH",
                "detail": f"0 kg distributed to {r.cards} cards",
                "expected_qty": round(mean, 1),
            })

        # 2. Low drawl ratio (only if not zero)
        elif r.quantity_kgs > 0 and r.cards > 0:
            ratio = r.quantity_kgs / r.cards
            if ratio < 1.5:
                issues.append({
                    "type": "LOW_DRAWL_RATIO",
                    "severity": "MEDIUM",
                    "detail": f"Only {ratio:.2f} kg/card (expected ≥ 1.5)",
                    "expected_qty": round(1.5 * r.cards, 1),
                })

        # 3. Statistical outliers (only when std > 0)
        if std > 0 and r.quantity_kgs > 0:
            z = (r.quantity_kgs - mean) / std
            if z > threshold_std:
                issues.append({
                    "type": "OUTLIER_HIGH",
                    "severity": "HIGH",
                    "detail": f"Qty {r.quantity_kgs:.0f} is {z:.1f}σ above district mean {mean:.0f}",
                    "expected_qty": round(mean, 1),
                })
            elif z < -threshold_std:
                sev = "CRITICAL" if abs(z) > threshold_std * 1.5 else "MEDIUM"
                issues.append({
                    "type": "OUTLIER_LOW",
                    "severity": sev,
                    "detail": f"Qty {r.quantity_kgs:.0f} is {abs(z):.1f}σ below district mean {mean:.0f}",
                    "expected_qty": round(mean, 1),
                })

        for issue in issues:
            anomalies.append({
                "id": r.id,
                "fps_id": r.fps_id,
                "district": r.district,
                "afso": r.afso,
                "month": r.month,
                "year": r.year,
                "commodity": r.commodity,
                "quantity_kgs": r.quantity_kgs,
                "cards": r.cards,
                "anomaly_type": issue["type"],
                "severity": issue["severity"],
                "detail": issue["detail"],
                "expected_qty": issue.get("expected_qty", 0),
            })
            if len(anomalies) >= limit:
                break
        if len(anomalies) >= limit:
            break

    # Severity counts
    sev_counts: dict[str, int] = defaultdict(int)
    for a in anomalies:
        sev_counts[a["severity"]] += 1

    return {
        "total": len(anomalies),
        "records_scanned": len(rows),
        "anomaly_rate_pct": round(len(anomalies) / max(len(rows), 1) * 100, 2),
        "severity_breakdown": dict(sev_counts),
        "anomalies": anomalies,
    }


# ── Map Data ──────────────────────────────────────────────────────────────────

def get_map_data(
    db: Session,
    *,
    level: str = "district",   # "district" | "afso" | "fps"
    year: Optional[int] = None,
    month: Optional[str] = None,
    district: Optional[str] = None,
    afso: Optional[str] = None,
    fps_id: Optional[str] = None,
    commodity: Optional[str] = None,
) -> list[dict]:
    """
    Return aggregated map markers at district / AFSO / FPS level.
    Each marker has: label, lat, lng, qty_kgs, cards, fps_count, months_count.
    """
    valid_levels = {"district", "afso", "fps"}
    if level not in valid_levels:
        level = "district"

    group_col = {
        "district": TransactionRecord.district,
        "afso": TransactionRecord.afso,
        "fps": TransactionRecord.fps_id,
    }[level]

    q = (
        db.query(
            group_col.label("label"),
            TransactionRecord.district.label("district"),
            TransactionRecord.afso.label("afso"),
            func.sum(TransactionRecord.quantity_kgs).label("qty"),
            func.count(TransactionRecord.quantity_kgs.distinct()).label("fps_count"),
        )
    )
    q = _apply_filters(q, year=year, month=month, district=district,
                       afso=afso, fps_id=fps_id, commodity=commodity)
    q = q.group_by(group_col, TransactionRecord.district, TransactionRecord.afso)

    if level == "fps":
        # If a specific FPS is requested, return it even if it wouldn't be in the "top 50".
        if not fps_id:
            q = q.limit(50)  # cap FPS markers

    markers = []
    for r in q.all():
        dist = r.district if hasattr(r, "district") else (district or "Chittoor")
        afso_val = r.afso if hasattr(r, "afso") else ""

        if level == "district":
            lat, lng = DISTRICT_COORDS.get(str(r.label), (14.0, 79.0))
        elif level == "afso":
            lat, lng = _afso_coords(str(r.label), dist)
        else:  # fps — cluster near AFSO
            lat, lng = _afso_coords(afso_val or str(r.label), dist)
            import hashlib
            h = int(hashlib.md5(str(r.label).encode()).hexdigest(), 16)
            lat += ((h % 200) - 100) / 10000
            lng += ((h % 197) - 98) / 10000

        markers.append({
            "label": str(r.label),
            "district": dist,
            "afso": afso_val,
            "lat": round(lat, 5),
            "lng": round(lng, 5),
            "qty_kgs": round(float(r.qty or 0), 1),
            "fps_count": r.fps_count or 1,
        })

    return markers


# ── FPS List ──────────────────────────────────────────────────────────────────

def get_fps_list(
    db: Session,
    *,
    year: Optional[int] = None,
    month: Optional[str] = None,
    district: Optional[str] = None,
    afso: Optional[str] = None,
    commodity: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[int, list[dict]]:
    """Paginated FPS summary: fps_id, district, afso, total_qty, total_cards, months."""
    q = (
        db.query(
            TransactionRecord.fps_id,
            TransactionRecord.district,
            TransactionRecord.afso,
            func.sum(TransactionRecord.quantity_kgs).label("total_qty"),
            func.max(TransactionRecord.cards).label("cards"),
            func.count(TransactionRecord.month.distinct()).label("months"),
        )
    )
    q = _apply_filters(q, year=year, month=month, district=district,
                       afso=afso, commodity=commodity)
    q = q.group_by(
        TransactionRecord.fps_id,
        TransactionRecord.district,
        TransactionRecord.afso,
    ).order_by(func.sum(TransactionRecord.quantity_kgs).desc())

    total = q.count()
    rows = q.offset(skip).limit(limit).all()

    return total, [
        {
            "fps_id": r.fps_id,
            "district": r.district,
            "afso": r.afso,
            "total_qty_kgs": round(float(r.total_qty or 0), 1),
            "cards": r.cards or 0,
            "months_active": r.months or 0,
        }
        for r in rows
    ]
