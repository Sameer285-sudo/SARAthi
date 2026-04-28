"""
Data ingestion and feature engineering for the anomaly service.

Input: raw TransactionInput records
Output: preprocessed dicts ready for anomaly detection + DB storage
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_TS_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
]


def _parse_ts(raw: str) -> datetime:
    raw = raw.strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {raw!r}")


def _ts_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ── Preprocessing ─────────────────────────────────────────────────────────────

def preprocess(transactions: list[dict]) -> list[dict]:
    """
    Cleans and enriches raw transaction dicts.
    Returns preprocessed list sorted by timestamp.
    """
    out = []
    for raw in transactions:
        try:
            processed = _process_one(raw)
            out.append(processed)
        except Exception as exc:
            tid = raw.get("transaction_id", "?")
            log.warning("Skipping transaction %s: %s", tid, exc)

    # Sort by timestamp ascending (needed for rolling features)
    out.sort(key=lambda r: r["timestamp"])
    return out


def _process_one(raw: dict) -> dict:
    tid    = str(raw["transaction_id"]).strip()
    loc    = str(raw.get("location", "unknown")).strip()

    # Parse timestamps
    ts  = _parse_ts(str(raw["timestamp"]))
    exp = _parse_ts(str(raw["expected_delivery_time"]))
    act = _parse_ts(str(raw["actual_delivery_time"]))

    # Quantities — clip to zero floor (can't be negative)
    disp = max(0.0, float(raw.get("dispatch_quantity", 0) or 0))
    dlvd = max(0.0, float(raw.get("delivered_quantity", 0) or 0))
    sb   = float(raw.get("stock_before", 0) or 0)
    sa   = float(raw.get("stock_after",  0) or 0)

    # ── Feature engineering ──────────────────────────────────────────────────

    # Delivery delay in hours (positive = late, negative = early)
    delay_hours = (act - exp).total_seconds() / 3600.0

    # Quantity mismatch (positive = shortfall)
    mismatch = disp - dlvd

    # Mismatch percentage of dispatched
    mismatch_pct = (mismatch / disp * 100.0) if disp > 0 else 0.0

    # Stock variation: how much stock changed vs what was delivered
    stock_variation = sa - sb  # expected ≈ dlvd - consumption

    return {
        "transaction_id":       tid,
        "timestamp":            _ts_str(ts),
        "location":             loc,
        "dispatch_quantity":    disp,
        "delivered_quantity":   dlvd,
        "expected_delivery_time": _ts_str(exp),
        "actual_delivery_time":   _ts_str(act),
        "stock_before":         sb,
        "stock_after":          sa,
        # engineered
        "delivery_delay_hours": round(delay_hours, 3),
        "quantity_mismatch":    round(mismatch, 3),
        "mismatch_pct":         round(mismatch_pct, 3),
        "stock_variation":      round(stock_variation, 3),
    }


def add_rolling_features(records: list[dict], window: int = 5) -> list[dict]:
    """
    Add rolling mean features grouped by location.
    Mutates records in-place (appends rolling_* keys).
    """
    from collections import defaultdict

    # Group indices by location
    loc_idx: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        loc_idx[r["location"]].append(i)

    for indices in loc_idx.values():
        # These are already sorted by timestamp
        delays    = [records[i]["delivery_delay_hours"] for i in indices]
        mismatches = [records[i]["mismatch_pct"] for i in indices]

        for j, idx in enumerate(indices):
            start = max(0, j - window + 1)
            records[idx]["rolling_avg_delay"]    = round(sum(delays[start:j+1]) / (j - start + 1), 3)
            records[idx]["rolling_avg_mismatch"] = round(sum(mismatches[start:j+1]) / (j - start + 1), 3)

    return records
