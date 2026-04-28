"""
Lightweight SQLite store for the anomaly service.
Uses sqlite3 directly so there's no conflict with the shared SQLAlchemy engine.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).resolve().parents[1] / "anomaly_store.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def conn_ctx():
    c = _get_conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db() -> None:
    with conn_ctx() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id      TEXT PRIMARY KEY,
            timestamp           TEXT NOT NULL,
            location            TEXT NOT NULL,
            dispatch_quantity   REAL NOT NULL,
            delivered_quantity  REAL NOT NULL,
            expected_delivery_time TEXT NOT NULL,
            actual_delivery_time   TEXT NOT NULL,
            stock_before        REAL NOT NULL,
            stock_after         REAL NOT NULL,
            delivery_delay_hours REAL,
            quantity_mismatch   REAL,
            mismatch_pct        REAL,
            stock_variation     REAL,
            created_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS anomalies (
            transaction_id      TEXT PRIMARY KEY,
            timestamp           TEXT NOT NULL,
            location            TEXT NOT NULL,
            dispatch_quantity   REAL,
            delivered_quantity  REAL,
            stock_before        REAL,
            stock_after         REAL,
            delivery_delay_hours REAL,
            quantity_mismatch   REAL,
            mismatch_pct        REAL,
            stock_variation     REAL,
            isolation_score     REAL,
            zscore_max          REAL,
            anomaly_score       REAL,
            anomaly_type        TEXT,
            severity            TEXT,
            reasons             TEXT,   -- JSON array
            is_anomaly          INTEGER,
            created_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS alerts (
            alert_id        TEXT PRIMARY KEY,
            transaction_id  TEXT NOT NULL,
            location        TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            severity        TEXT NOT NULL,
            message         TEXT NOT NULL,
            reasons         TEXT,       -- JSON array
            created_at      TEXT DEFAULT (datetime('now')),
            acknowledged    INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_tx_ts       ON transactions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_tx_loc      ON transactions(location);
        CREATE INDEX IF NOT EXISTS idx_anom_ts     ON anomalies(timestamp);
        CREATE INDEX IF NOT EXISTS idx_anom_loc    ON anomalies(location);
        CREATE INDEX IF NOT EXISTS idx_anom_sev    ON anomalies(severity);
        CREATE INDEX IF NOT EXISTS idx_alert_sev   ON alerts(severity);
        CREATE INDEX IF NOT EXISTS idx_alert_loc   ON alerts(location);
        """)


# ── Transactions ──────────────────────────────────────────────────────────────

def upsert_transaction(row: dict) -> None:
    sql = """
    INSERT OR REPLACE INTO transactions
        (transaction_id, timestamp, location, dispatch_quantity, delivered_quantity,
         expected_delivery_time, actual_delivery_time, stock_before, stock_after,
         delivery_delay_hours, quantity_mismatch, mismatch_pct, stock_variation)
    VALUES
        (:transaction_id, :timestamp, :location, :dispatch_quantity, :delivered_quantity,
         :expected_delivery_time, :actual_delivery_time, :stock_before, :stock_after,
         :delivery_delay_hours, :quantity_mismatch, :mismatch_pct, :stock_variation)
    """
    with conn_ctx() as c:
        c.execute(sql, row)


def upsert_transactions_bulk(rows: list[dict]) -> None:
    sql = """
    INSERT OR REPLACE INTO transactions
        (transaction_id, timestamp, location, dispatch_quantity, delivered_quantity,
         expected_delivery_time, actual_delivery_time, stock_before, stock_after,
         delivery_delay_hours, quantity_mismatch, mismatch_pct, stock_variation)
    VALUES
        (:transaction_id, :timestamp, :location, :dispatch_quantity, :delivered_quantity,
         :expected_delivery_time, :actual_delivery_time, :stock_before, :stock_after,
         :delivery_delay_hours, :quantity_mismatch, :mismatch_pct, :stock_variation)
    """
    with conn_ctx() as c:
        c.executemany(sql, rows)


def get_transactions(
    location: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    where, params = _build_where(location=location, date_from=date_from, date_to=date_to, table="t")
    sql = f"SELECT * FROM transactions t {where} ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with conn_ctx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


# ── Anomalies ─────────────────────────────────────────────────────────────────

def upsert_anomalies_bulk(rows: list[dict]) -> None:
    sql = """
    INSERT OR REPLACE INTO anomalies
        (transaction_id, timestamp, location, dispatch_quantity, delivered_quantity,
         stock_before, stock_after, delivery_delay_hours, quantity_mismatch, mismatch_pct,
         stock_variation, isolation_score, zscore_max, anomaly_score, anomaly_type,
         severity, reasons, is_anomaly)
    VALUES
        (:transaction_id, :timestamp, :location, :dispatch_quantity, :delivered_quantity,
         :stock_before, :stock_after, :delivery_delay_hours, :quantity_mismatch, :mismatch_pct,
         :stock_variation, :isolation_score, :zscore_max, :anomaly_score, :anomaly_type,
         :severity, :reasons, :is_anomaly)
    """
    serialized = []
    for row in rows:
        r = dict(row)
        if isinstance(r.get("reasons"), list):
            r["reasons"] = json.dumps(r["reasons"])
        r["is_anomaly"] = int(bool(r.get("is_anomaly", False)))
        serialized.append(r)
    with conn_ctx() as c:
        c.executemany(sql, serialized)


def get_anomalies(
    location: str | None = None,
    severity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 500,
) -> list[dict]:
    clauses: list[str] = ["a.is_anomaly = 1"]
    params: list[Any] = []
    if location:
        clauses.append("a.location = ?")
        params.append(location)
    if severity:
        clauses.append("a.severity = ?")
        params.append(severity.upper())
    if date_from:
        clauses.append("a.timestamp >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("a.timestamp <= ?")
        params.append(date_to)
    params.append(limit)
    sql = f"SELECT * FROM anomalies a WHERE {' AND '.join(clauses)} ORDER BY a.anomaly_score DESC, a.timestamp DESC LIMIT ?"
    with conn_ctx() as c:
        rows = c.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["reasons"] = json.loads(d.get("reasons") or "[]")
        d["is_anomaly"] = bool(d.get("is_anomaly"))
        result.append(d)
    return result


def count_transactions() -> int:
    with conn_ctx() as c:
        return c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]


def count_anomalies() -> int:
    with conn_ctx() as c:
        return c.execute("SELECT COUNT(*) FROM anomalies WHERE is_anomaly=1").fetchone()[0]


# ── Alerts ────────────────────────────────────────────────────────────────────

def insert_alerts_bulk(rows: list[dict]) -> None:
    sql = """
    INSERT OR IGNORE INTO alerts
        (alert_id, transaction_id, location, timestamp, severity, message, reasons)
    VALUES
        (:alert_id, :transaction_id, :location, :timestamp, :severity, :message, :reasons)
    """
    with conn_ctx() as c:
        rows_serialized = []
        for row in rows:
            r = dict(row)
            if isinstance(r.get("reasons"), list):
                r["reasons"] = json.dumps(r["reasons"])
            rows_serialized.append(r)
        c.executemany(sql, rows_serialized)


def get_alerts(
    location: str | None = None,
    severity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    acknowledged: bool | None = None,
    limit: int = 200,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if location:
        clauses.append("location = ?")
        params.append(location)
    if severity:
        clauses.append("severity = ?")
        params.append(severity.upper())
    if date_from:
        clauses.append("timestamp >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("timestamp <= ?")
        params.append(date_to)
    if acknowledged is not None:
        clauses.append("acknowledged = ?")
        params.append(int(acknowledged))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    sql = f"SELECT * FROM alerts {where} ORDER BY created_at DESC LIMIT ?"
    with conn_ctx() as c:
        rows = c.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["reasons"] = json.loads(d.get("reasons") or "[]")
        d["acknowledged"] = bool(d.get("acknowledged"))
        result.append(d)
    return result


def acknowledge_alert(alert_id: str) -> bool:
    with conn_ctx() as c:
        c.execute("UPDATE alerts SET acknowledged=1 WHERE alert_id=?", (alert_id,))
        return c.execute("SELECT changes()").fetchone()[0] > 0


def count_alerts() -> int:
    with conn_ctx() as c:
        return c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]


# ── Chart data queries ────────────────────────────────────────────────────────

def get_trend_data(
    granularity: str = "day",
    location: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Aggregate dispatch/delivered by time bucket."""
    if granularity == "hour":
        trunc = "strftime('%Y-%m-%d %H:00', timestamp)"
    elif granularity == "month":
        trunc = "strftime('%Y-%m', timestamp)"
    else:
        trunc = "strftime('%Y-%m-%d', timestamp)"

    clauses: list[str] = []
    params: list[Any] = []
    if location:
        clauses.append("location = ?")
        params.append(location)
    if date_from:
        clauses.append("timestamp >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("timestamp <= ?")
        params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    sql = f"""
    SELECT
        {trunc}                            AS label,
        SUM(dispatch_quantity)             AS dispatch,
        SUM(delivered_quantity)            AS delivered,
        SUM(dispatch_quantity - delivered_quantity) AS mismatch,
        COUNT(*)                           AS tx_count
    FROM transactions
    {where}
    GROUP BY label
    ORDER BY label
    """
    with conn_ctx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def get_anomaly_timeline(
    location: str | None = None,
    severity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 500,
) -> list[dict]:
    clauses = ["is_anomaly = 1"]
    params: list[Any] = []
    if location:
        clauses.append("location = ?")
        params.append(location)
    if severity:
        clauses.append("severity = ?")
        params.append(severity.upper())
    if date_from:
        clauses.append("timestamp >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("timestamp <= ?")
        params.append(date_to)
    params.append(limit)
    sql = f"""
    SELECT transaction_id, timestamp, location, anomaly_score, severity, reasons
    FROM anomalies
    WHERE {' AND '.join(clauses)}
    ORDER BY timestamp ASC
    LIMIT ?
    """
    with conn_ctx() as c:
        rows = c.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["reasons"] = json.loads(d.get("reasons") or "[]")
        result.append(d)
    return result


def get_location_stats(
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    clauses_tx: list[str] = []
    clauses_an: list[str] = ["is_anomaly = 1"]
    params_tx: list[Any] = []
    params_an: list[Any] = []
    if date_from:
        clauses_tx.append("timestamp >= ?")
        params_tx.append(date_from)
        clauses_an.append("timestamp >= ?")
        params_an.append(date_from)
    if date_to:
        clauses_tx.append("timestamp <= ?")
        params_tx.append(date_to)
        clauses_an.append("timestamp <= ?")
        params_an.append(date_to)
    where_tx = f"WHERE {' AND '.join(clauses_tx)}" if clauses_tx else ""
    where_an = f"WHERE {' AND '.join(clauses_an)}"

    sql = f"""
    SELECT
        t.location,
        t.total_tx,
        COALESCE(a.anomaly_count, 0)   AS anomaly_count,
        COALESCE(a.critical_count, 0)  AS critical_count,
        COALESCE(a.high_count, 0)      AS high_count,
        COALESCE(a.medium_count, 0)    AS medium_count,
        COALESCE(a.low_count, 0)       AS low_count
    FROM (
        SELECT location, COUNT(*) AS total_tx
        FROM transactions
        {where_tx}
        GROUP BY location
    ) t
    LEFT JOIN (
        SELECT
            location,
            COUNT(*) AS anomaly_count,
            SUM(CASE WHEN severity='CRITICAL' THEN 1 ELSE 0 END) AS critical_count,
            SUM(CASE WHEN severity='HIGH'     THEN 1 ELSE 0 END) AS high_count,
            SUM(CASE WHEN severity='MEDIUM'   THEN 1 ELSE 0 END) AS medium_count,
            SUM(CASE WHEN severity='LOW'      THEN 1 ELSE 0 END) AS low_count
        FROM anomalies
        {where_an}
        GROUP BY location
    ) a ON t.location = a.location
    ORDER BY anomaly_count DESC
    """
    params_combined = params_tx + params_an
    with conn_ctx() as c:
        return [dict(r) for r in c.execute(sql, params_combined).fetchall()]


def get_delay_distribution(
    location: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if location:
        clauses.append("location = ?")
        params.append(location)
    if date_from:
        clauses.append("timestamp >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("timestamp <= ?")
        params.append(date_to)
    clauses.append("t.delivery_delay_hours IS NOT NULL")
    where = f"WHERE {' AND '.join(clauses)}"
    sql = f"""
    SELECT t.delivery_delay_hours, COALESCE(a.is_anomaly, 0) AS is_anomaly
    FROM transactions t
    LEFT JOIN anomalies a ON t.transaction_id = a.transaction_id
    {where}
    """
    with conn_ctx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_where(
    location: str | None = None,
    severity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    table: str = "",
) -> tuple[str, list]:
    prefix = f"{table}." if table else ""
    clauses = []
    params: list[Any] = []
    if location:
        clauses.append(f"{prefix}location = ?")
        params.append(location)
    if severity:
        clauses.append(f"{prefix}severity = ?")
        params.append(severity.upper())
    if date_from:
        clauses.append(f"{prefix}timestamp >= ?")
        params.append(date_from)
    if date_to:
        clauses.append(f"{prefix}timestamp <= ?")
        params.append(date_to)
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params
