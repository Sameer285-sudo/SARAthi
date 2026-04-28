"""
Pydantic schemas for the anomaly detection service.
All input validation and response shapes live here.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ── Ingest ────────────────────────────────────────────────────────────────────

class TransactionInput(BaseModel):
    transaction_id: str
    timestamp: str
    location: str
    dispatch_quantity: float = Field(ge=0)
    delivered_quantity: float = Field(ge=0)
    expected_delivery_time: str
    actual_delivery_time: str
    stock_before: float
    stock_after: float

class IngestRequest(BaseModel):
    transactions: list[TransactionInput]

class IngestResponse(BaseModel):
    module: str = "AnomalyDetection"
    ingested: int
    anomalies_detected: int
    alerts_generated: int
    summary: dict


# ── Anomaly record ────────────────────────────────────────────────────────────

class AnomalyRecord(BaseModel):
    transaction_id: str
    timestamp: str
    location: str
    dispatch_quantity: float
    delivered_quantity: float
    stock_before: float
    stock_after: float
    # engineered features
    delivery_delay_hours: float
    quantity_mismatch: float
    mismatch_pct: float
    stock_variation: float
    # detection output
    isolation_score: float
    zscore_max: float
    anomaly_score: float        # composite 0-1
    anomaly_type: str           # "isolation_forest" | "zscore" | "rule_based" | "combined"
    severity: str               # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    reasons: list[str]
    is_anomaly: bool


# ── Alert ─────────────────────────────────────────────────────────────────────

class AlertRecord(BaseModel):
    alert_id: str
    transaction_id: str
    location: str
    timestamp: str
    severity: str
    message: str
    reasons: list[str]
    created_at: str
    acknowledged: bool = False


# ── Visualization payloads ────────────────────────────────────────────────────

class TrendPoint(BaseModel):
    label: str
    dispatch: float
    delivered: float
    mismatch: float

class TrendResponse(BaseModel):
    module: str = "AnomalyDetection"
    granularity: str
    filters: dict
    labels: list[str]
    dispatch: list[float]
    delivered: list[float]
    mismatch: list[float]
    points: list[TrendPoint]

class AnomalyTimePoint(BaseModel):
    timestamp: str
    location: str
    transaction_id: str
    anomaly_score: float
    severity: str
    reasons: list[str]

class AnomalyTimelineResponse(BaseModel):
    module: str = "AnomalyDetection"
    filters: dict
    total: int
    labels: list[str]                  # timestamps
    scores: list[float]                # anomaly scores
    severities: list[str]              # per point
    points: list[AnomalyTimePoint]

class LocationBucket(BaseModel):
    location: str
    total_transactions: int
    anomaly_count: int
    anomaly_rate_pct: float
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int

class LocationSummaryResponse(BaseModel):
    module: str = "AnomalyDetection"
    filters: dict
    labels: list[str]
    anomaly_counts: list[int]
    anomaly_rates: list[float]
    buckets: list[LocationBucket]

class DelayHistogramResponse(BaseModel):
    module: str = "AnomalyDetection"
    filters: dict
    bin_edges: list[float]
    bin_labels: list[str]
    counts: list[int]
    anomalous_counts: list[int]        # subset that are anomalies


# ── Filters ───────────────────────────────────────────────────────────────────

class QueryFilters(BaseModel):
    location: Optional[str] = None
    severity: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    limit: int = Field(default=200, ge=1, le=5000)
