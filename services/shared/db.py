from collections.abc import Generator
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

from shared.config import settings

def _normalize_database_url(url: str) -> tuple[str, dict]:
    """
    Normalize DATABASE_URL for SQLAlchemy.

    Render provides URLs like:
      postgresql://user:pass@host:5432/db

    SQLAlchemy needs an explicit driver, e.g.:
      postgresql+psycopg://...

    Also, Render Postgres requires TLS in most setups.
    """
    u = (url or "").strip()
    if u.startswith("postgresql://") or u.startswith("postgres://"):
        u = u.replace("postgres://", "postgresql://", 1)
        u = u.replace("postgresql://", "postgresql+psycopg://", 1)

    connect_args: dict = {}
    parsed = urlparse(u)
    if parsed.scheme.startswith("postgresql+"):
        # If sslmode isn't provided in the query string, default to require.
        q = parsed.query or ""
        if "sslmode=" not in q:
            connect_args["sslmode"] = "require"

    return u, connect_args


db_url, _connect_args = _normalize_database_url(settings.database_url)
_is_sqlite = db_url.startswith("sqlite")

engine = create_engine(
    db_url,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else _connect_args,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
