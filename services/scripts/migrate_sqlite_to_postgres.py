from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.sql.sqltypes import JSON as SAJSON

# Ensure `services/` is on sys.path so `shared.*` imports work when running from repo root.
_SERVICES_DIR = Path(__file__).resolve().parents[1]
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))

# Import model metadata (defines Postgres-compatible column types).
from shared.db import Base  # noqa: E402
import shared.models  # noqa: F401,E402  (registers models with Base.metadata)


def normalize_postgres_url(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("postgres://"):
        u = u.replace("postgres://", "postgresql://", 1)
    if u.startswith("postgresql://"):
        # Use psycopg3 driver explicitly for SQLAlchemy.
        u = u.replace("postgresql://", "postgresql+psycopg://", 1)
    return u


def _coerce_row_for_insert(table, row: dict[str, Any]) -> dict[str, Any]:
    """
    SQLite may store JSON as TEXT. Coerce JSON-ish strings into Python objects
    so psycopg can insert into Postgres JSON columns.
    """
    out: dict[str, Any] = dict(row)
    for col in table.columns:
        if isinstance(col.type, SAJSON) and col.name in out:
            v = out[col.name]
            if isinstance(v, str):
                try:
                    out[col.name] = json.loads(v)
                except Exception:
                    # If it's not valid JSON, leave it as-is.
                    pass
    return out


def copy_table(src_engine, dst_engine, table, batch_size: int = 2000) -> int:
    copied = 0
    with src_engine.connect() as src, dst_engine.begin() as dst:
        rows = src.execute(select(table)).mappings()
        buf: list[dict[str, Any]] = []
        for r in rows:
            buf.append(_coerce_row_for_insert(table, dict(r)))
            if len(buf) >= batch_size:
                dst.execute(table.insert(), buf)
                copied += len(buf)
                buf.clear()
        if buf:
            dst.execute(table.insert(), buf)
            copied += len(buf)
    return copied


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Migrate local SQLite DB into Postgres (Render) using SQLAlchemy models."
    )
    ap.add_argument(
        "--sqlite",
        default=str(Path(__file__).resolve().parents[2] / "pds360.db"),
        help="Path to SQLite DB file (default: repo root pds360.db).",
    )
    ap.add_argument(
        "--postgres-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres DATABASE_URL. If omitted, uses env DATABASE_URL.",
    )
    ap.add_argument(
        "--wipe",
        action="store_true",
        help="DANGER: delete destination data before copying (TRUNCATE ALL).",
    )
    args = ap.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite DB not found: {sqlite_path}")

    if not args.postgres_url:
        raise SystemExit("Missing Postgres URL. Pass --postgres-url or set env DATABASE_URL.")

    pg_url = normalize_postgres_url(args.postgres_url)

    src_engine = create_engine(
        f"sqlite:///{sqlite_path}",
        future=True,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )
    dst_engine = create_engine(
        pg_url,
        future=True,
        pool_pre_ping=True,
        connect_args={"sslmode": "require"},
    )

    # Create schema in Postgres from our ORM models (correct types for Postgres).
    Base.metadata.create_all(bind=dst_engine)

    tables = list(Base.metadata.sorted_tables)

    if args.wipe:
        with dst_engine.begin() as dst:
            for t in reversed(tables):
                dst.execute(text(f"TRUNCATE TABLE {t.name} RESTART IDENTITY CASCADE;"))

    total = 0
    for t in tables:
        n = copy_table(src_engine, dst_engine, t)
        total += n
        print(f"{t.name}: copied {n} rows")

    print(f"Done. Total rows copied: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
