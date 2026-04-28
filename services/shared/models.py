from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base


class DatasetMeta(Base):
    """
    Tracks which on-disk dataset snapshot was loaded into the DB.

    We use this to auto-reseed TransactionRecord when dataset/clean_transactions.csv changes,
    so the UI doesn't keep showing stale data after CSV updates.
    """

    __tablename__ = "dataset_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    loaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int]            = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str]       = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str]      = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str]         = mapped_column(String(120), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256))
    full_name: Mapped[str]     = mapped_column(String(120))
    role: Mapped[str]          = mapped_column(String(32), index=True)
    state_id: Mapped[str | None]    = mapped_column(String(64), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mandal_id: Mapped[str | None]   = mapped_column(String(64), nullable=True)
    fps_id: Mapped[str | None]      = mapped_column(String(64), nullable=True)
    ration_card_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool]    = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FPSStockMetric(Base):
    __tablename__ = "fps_stock_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fps_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    fps_name: Mapped[str] = mapped_column(String(120))
    district: Mapped[str] = mapped_column(String(120), index=True)
    mandal: Mapped[str] = mapped_column(String(120), index=True)
    commodity: Mapped[str] = mapped_column(String(64))
    monthly_drawal: Mapped[list] = mapped_column(JSON)
    current_stock: Mapped[int] = mapped_column(Integer)
    beneficiary_count: Mapped[int] = mapped_column(Integer)
    seasonal_index: Mapped[float] = mapped_column(Float)
    lead_time_days: Mapped[int] = mapped_column(Integer)


class MovementRecord(Base):
    __tablename__ = "movement_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shipment_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    fps_id: Mapped[str] = mapped_column(String(32), index=True)
    dispatch_qty: Mapped[int] = mapped_column(Integer)
    delivered_qty: Mapped[int] = mapped_column(Integer)
    expected_transit_hours: Mapped[int] = mapped_column(Integer)
    actual_transit_hours: Mapped[int] = mapped_column(Integer)
    transaction_spike: Mapped[float] = mapped_column(Float)


class CallRecord(Base):
    __tablename__ = "call_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    call_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    caller_name: Mapped[str] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(32))
    transcript: Mapped[str] = mapped_column(Text)
    sentiment_score: Mapped[float] = mapped_column(Float)


class GrievanceTicket(Base):
    __tablename__ = "grievance_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticket_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    source_channel: Mapped[str] = mapped_column(String(32), index=True)
    caller_name: Mapped[str] = mapped_column(String(120))
    caller_type: Mapped[str] = mapped_column(String(32), index=True)
    language: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(64), index=True)
    priority: Mapped[str] = mapped_column(String(16), index=True)
    sentiment_score: Mapped[float] = mapped_column(Float)
    sentiment_label: Mapped[str] = mapped_column(String(32))
    transcript: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    assigned_team: Mapped[str] = mapped_column(String(120))
    next_action: Mapped[str] = mapped_column(Text)
    resolution_eta_hours: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), index=True, default="OPEN")
    district_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fps_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CallSession(Base):
    __tablename__ = "call_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    twilio_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(16), index=True)
    caller_name: Mapped[str] = mapped_column(String(120))
    caller_type: Mapped[str] = mapped_column(String(32))
    caller_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_state: Mapped[str] = mapped_column(String(32), default="language_selection")
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ticket_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audio_recording_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class TransactionRecord(Base):
    """Normalized distribution record: one row per FPS per month per commodity.

    Loaded from dataset/clean_transactions.csv.
    Columns sourced:
      slno, year, dtstrict (district), afso (mandal/AFSO), fps (fps_id)
      {Month}_{Commodity} (Kgs) → month, commodity, quantity_kgs
      {Month}_Cards            → cards (beneficiary card count)
    """
    __tablename__ = "transaction_records"

    id:            Mapped[int]  = mapped_column(Integer, primary_key=True, index=True)
    year:          Mapped[int]  = mapped_column(Integer, index=True)
    month:         Mapped[str]  = mapped_column(String(16), index=True)   # "January" .. "April"
    district:      Mapped[str]  = mapped_column(String(120), index=True)  # dtstrict
    afso:          Mapped[str]  = mapped_column(String(120), index=True)  # afso / mandal
    fps_id:        Mapped[str]  = mapped_column(String(32), index=True)   # fps
    commodity:     Mapped[str]  = mapped_column(String(120), index=True)
    quantity_kgs:  Mapped[float] = mapped_column(Float, default=0.0)
    cards:         Mapped[int]  = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("year", "month", "fps_id", "commodity", name="uq_transaction"),
        Index("ix_tx_district_afso", "district", "afso"),
        Index("ix_tx_month_commodity", "month", "commodity"),
    )
