"""
Seed the database from the real dataset.
- TransactionRecord : loaded from dataset/clean_transactions.csv
- FPSStockMetric   : synthesised from the same CSV (monthly averages)
- MovementRecord / CallRecord : kept as demo stubs
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from shared.models import CallRecord, DatasetMeta, FPSStockMetric, MovementRecord, TransactionRecord

log = logging.getLogger(__name__)

# Resolve the CSV path relative to this file:
#   services/shared/seed.py  →  ../..  →  project root  →  dataset/
_CSV_PATH = Path(__file__).resolve().parents[2] / "dataset" / "clean_transactions.csv"

# Commodity columns that exist per-month in the CSV (after stripping ".1" duplicates)
_COMMODITY_COLS: list[str] = [
    "FRice (Kgs)",
    "Flood Dal (Kgs)",
    "Flood Onion (Kgs)",
    "Flood Poil (Kgs)",
    "Flood Potato (Kgs)",
    "Flood Rice (Kgs)",
    "Flood Sugar HK (Kgs)",
    "Jowar (Kgs)",
    "RG Dal One kg Pkt (Kgs)",
    "Raagi (Kgs)",
    "SUGAR HALF KG (Kgs)",
    "WM Atta Pkt (Kgs)",
    "Whole Wheat Atta (Kgs)",
]

_MONTHS = ["January", "February", "March", "April"]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _needs_reseed(db: Session) -> bool:
    """
    True if dataset/clean_transactions.csv changed since the last successful seed.

    Seed is otherwise idempotent and would keep showing old DB rows even after CSV updates.
    """
    if not _CSV_PATH.exists():
        return False

    current_hash = _sha256_file(_CSV_PATH)
    meta = db.query(DatasetMeta).filter(DatasetMeta.name == "clean_transactions.csv").first()
    if meta is None:
        # Older DB without meta: force reseed so we align DB with current CSV.
        return True
    return meta.sha256 != current_hash


def _load_csv() -> list[dict]:
    """Parse clean_transactions.csv → deduplicated list of dicts for TransactionRecord."""
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        log.warning("pandas not installed – skipping CSV seed")
        return []

    if not _CSV_PATH.exists():
        log.warning("Dataset CSV not found at %s – skipping CSV seed", _CSV_PATH)
        return []

    df = pd.read_csv(_CSV_PATH)

    # Aggregate duplicates: use a dict keyed on (year, month, fps_id, commodity)
    # to SUM quantities and take the MAX cards (cards are the same across commodities)
    agg: dict[tuple, dict] = {}

    for _, row in df.iterrows():
        fps_id   = str(int(row["fps"])).strip()
        district = str(row["dtstrict"]).strip()
        afso     = str(row["afso"]).strip()
        year     = int(row["year"])

        for month in _MONTHS:
            # Cards for this month
            cards_col = f"{month}_Cards"
            cards = int(row.get(cards_col, 0) or 0)

            for commodity in _COMMODITY_COLS:
                col = f"{month}_{commodity}"
                if col not in row:
                    continue
                qty = float(row.get(col, 0) or 0)

                key = (year, month, fps_id, commodity)
                if key in agg:
                    agg[key]["quantity_kgs"] += qty
                    agg[key]["cards"] = max(agg[key]["cards"], cards)
                else:
                    agg[key] = dict(
                        year=year, month=month,
                        district=district, afso=afso,
                        fps_id=fps_id, commodity=commodity,
                        quantity_kgs=qty, cards=cards,
                    )

    records = list(agg.values())
    log.info("CSV parsed: %d unique transaction rows from %d raw FPS rows",
             len(records), len(df))
    return records


def _seed_transactions(db: Session) -> None:
    if db.query(TransactionRecord).count() > 0:
        return  # already seeded

    rows = _load_csv()
    if not rows:
        return

    # Bulk insert in batches of 500 for SQLite performance
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        db.bulk_insert_mappings(TransactionRecord, rows[i : i + batch_size])
        db.flush()

    db.commit()
    log.info("Seeded %d TransactionRecord rows", len(rows))

    # Persist dataset signature so we can auto-reseed when the CSV changes.
    try:
        sha = _sha256_file(_CSV_PATH) if _CSV_PATH.exists() else ""
        meta = db.query(DatasetMeta).filter(DatasetMeta.name == "clean_transactions.csv").first()
        if meta is None:
            meta = DatasetMeta(name="clean_transactions.csv", sha256=sha, rows=len(rows))
            db.add(meta)
        else:
            meta.sha256 = sha
            meta.rows = len(rows)
        db.commit()
    except Exception as exc:
        # Don't break the app if meta write fails; the seed itself is complete.
        log.warning("Could not write dataset meta: %s", exc)


def _seed_fps_from_csv(db: Session) -> None:
    """Build FPSStockMetric rows from CSV (monthly rice drawals per FPS), deduplicated."""
    if db.query(FPSStockMetric).count() > 0:
        return

    try:
        import pandas as pd  # type: ignore
    except ImportError:
        return

    if not _CSV_PATH.exists():
        return

    df = pd.read_csv(_CSV_PATH)

    # Deduplicate: aggregate per fps_id (sum monthly drawals, keep first district/mandal)
    fps_data: dict[str, dict] = {}
    for _, row in df.iterrows():
        fps_id = str(int(row["fps"])).strip()
        if fps_id not in fps_data:
            fps_data[fps_id] = {
                "fps_id": fps_id,
                "district": str(row["dtstrict"]).strip(),
                "mandal": str(row["afso"]).strip(),
                "monthly_drawal": [0, 0, 0, 0],
                "beneficiary_count": 0,
            }

        entry = fps_data[fps_id]
        for i, month in enumerate(_MONTHS):
            col = f"{month}_FRice (Kgs)"
            entry["monthly_drawal"][i] += int(row.get(col, 0) or 0)
        # Use max beneficiary count seen
        for month in _MONTHS:
            cards_col = f"{month}_Cards"
            cards = int(row.get(cards_col, 0) or 0)
            entry["beneficiary_count"] = max(entry["beneficiary_count"], cards)

    fps_metrics: list[FPSStockMetric] = []
    for fps_id, entry in fps_data.items():
        monthly_drawal = entry["monthly_drawal"]
        nonzero = [x for x in monthly_drawal if x > 0]
        avg_drawal = sum(nonzero) / max(len(nonzero), 1)
        current_stock = max(int(avg_drawal * 0.25), 10)
        fps_metrics.append(FPSStockMetric(
            fps_id=fps_id,
            fps_name=f"FPS {fps_id}",
            district=entry["district"],
            mandal=entry["mandal"],
            commodity="Rice",
            monthly_drawal=monthly_drawal,
            current_stock=current_stock,
            beneficiary_count=max(entry["beneficiary_count"], 1),
            seasonal_index=1.05,
            lead_time_days=2,
        ))

    db.add_all(fps_metrics)
    db.commit()
    log.info("Seeded %d FPSStockMetric rows from CSV", len(fps_metrics))


def _seed_demo_stubs(db: Session) -> None:
    """Demo data for movement records and call records."""
    if db.query(MovementRecord).count() == 0:
        db.add_all([
            MovementRecord(shipment_id="SHIP-1001", fps_id="1005001",
                           dispatch_qty=540, delivered_qty=540,
                           expected_transit_hours=10, actual_transit_hours=11,
                           transaction_spike=1.05),
            MovementRecord(shipment_id="SHIP-1002", fps_id="1005002",
                           dispatch_qty=480, delivered_qty=450,
                           expected_transit_hours=8, actual_transit_hours=17,
                           transaction_spike=1.12),
            MovementRecord(shipment_id="SHIP-1003", fps_id="1038001",
                           dispatch_qty=620, delivered_qty=620,
                           expected_transit_hours=9, actual_transit_hours=9,
                           transaction_spike=1.62),
            MovementRecord(shipment_id="SHIP-1004", fps_id="1148001",
                           dispatch_qty=95, delivered_qty=92,
                           expected_transit_hours=12, actual_transit_hours=18,
                           transaction_spike=0.98),
        ])

    if db.query(CallRecord).count() == 0:
        db.add_all([
            CallRecord(call_id="CALL-001", caller_name="Lakshmi", language="Telugu",
                       transcript="Rice stock is not available in my fair price shop for the last two days.",
                       sentiment_score=-0.62),
            CallRecord(call_id="CALL-002", caller_name="Ramesh", language="English",
                       transcript="My entitlement is not reflecting correctly in the system.",
                       sentiment_score=-0.34),
            CallRecord(call_id="CALL-003", caller_name="Asha", language="Hindi",
                       transcript="Dispatch came late and distribution was delayed at the FPS.",
                       sentiment_score=-0.51),
        ])

    db.commit()


def seed_data(db: Session) -> None:
    # Auto-reseed derived tables if dataset/clean_transactions.csv changed.
    # Without this, the DB keeps old rows (seed is idempotent) and the UI shows stale analytics.
    if _needs_reseed(db):
        log.info("Dataset changed at %s â†’ reseeding transaction tables", _CSV_PATH)
        db.query(TransactionRecord).delete()
        db.query(FPSStockMetric).delete()
        db.commit()
    _seed_transactions(db)
    _seed_fps_from_csv(db)
    _seed_demo_stubs(db)
