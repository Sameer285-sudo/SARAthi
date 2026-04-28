from __future__ import annotations

from pydantic import BaseModel, Field


class SmartAllotRecommendation(BaseModel):
    fps_id: str
    fps_name: str
    district: str
    mandal: str
    commodity: str
    beneficiary_count: int
    current_stock: int
    forecast: int
    safety_stock: int
    recommended_allotment: int
    stock_coverage_days: float
    shortage_risk: float
    overstock_risk: float
    confidence_score: float
    explanation: list[str]


class SmartAllotMLRecommendation(BaseModel):
    forecast_for_month: str
    state_name: str
    district_name: str
    district_code: int
    item_name: str
    forecast_next_month: float
    safety_stock: float
    carryover_stock_proxy: float
    recommended_allotment: float
    volatility_proxy: float
    last_month_distributed: float
    last_month_allocated: float
    model_strategy: str


class SmartAllotSummary(BaseModel):
    total_fps: int
    total_forecast: int
    total_recommended_allotment: int
    high_risk_fps: int
    highest_priority: SmartAllotRecommendation | SmartAllotMLRecommendation | None


class SmartAllotMetrics(BaseModel):
    train_rows: int
    test_rows: int
    mae: float
    rmse: float
    mape_percent: float
    wape_percent: float


class SmartAllotDatasetInfo(BaseModel):
    raw_file: str
    cleaned_rows: int
    item_panel_rows: int | None = None
    training_rows: int
    states: int
    districts: int
    date_min: str
    date_max: str
    items: list[str] = []


class SmartAllotModelInfo(BaseModel):
    model_loaded: bool
    model_path: str
    recommendations_path: str
    metrics_path: str
    dataset: SmartAllotDatasetInfo
    metrics: SmartAllotMetrics


class SmartAllotFilterMetadata(BaseModel):
    district_names: list[str]
    district_codes: list[int]
    items: list[str]


class AnomalyAlert(BaseModel):
    shipment_id: str
    fps_id: str
    risk_score: float
    severity: str
    quantity_mismatch: int
    delay_hours: int
    transaction_spike: float
    anomaly_detected: bool
    reasons: list[str]


class AnomalySummary(BaseModel):
    total_shipments: int
    flagged_shipments: int
    high_severity: int
    open_investigation_queue: int


class BotQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    role: str = "citizen"
    language: str = "English"


class BotQueryResponse(BaseModel):
    role: str
    language: str = "English"
    intent: str
    answer: str
    detected_entities: dict[str, str | int | None] = {}
    insights: list[str] = []
    suggestions: list[str] = []


class CallCentreTicket(BaseModel):
    call_id: str
    caller_name: str
    language: str
    category: str
    priority: str
    sentiment_score: float
    sentiment_label: str
    transcript: str
    summary: str
    assigned_team: str
    next_action: str
    resolution_eta_hours: int
    channel: str
    ticket_id: str
    status: str
    district_name: str | None = None
    fps_reference: str | None = None
    created_at: str | None = None


class TicketStatusUpdateRequest(BaseModel):
    status: str


class CallCentreSummary(BaseModel):
    total_calls: int
    open_tickets: int
    high_priority_tickets: int
    languages_covered: list[str]


class CallCentreForecast(BaseModel):
    next_day_expected_calls: int
    predicted_peak_issue: str
    predicted_peak_language: str


class CallCentrePerformance(BaseModel):
    average_sentiment_score: float
    average_resolution_eta_hours: float
    response_time_minutes: float
    resolution_rate_percent: float


class CallCentreDashboard(BaseModel):
    summary: CallCentreSummary
    forecast: CallCentreForecast
    performance: CallCentrePerformance
    recurring_issues: list[str]
    multilingual_support: list[str]


class LiveMetrics(BaseModel):
    active_sessions: int
    total_tickets: int
    open_tickets: int
    resolved_today: int
    avg_sentiment: float
    high_priority: int
    calls_by_language: dict[str, int]
    calls_by_category: dict[str, int]
    sentiment_trend: list[float]


class VoiceSessionStartRequest(BaseModel):
    caller_name: str = "Guest Caller"
    caller_type: str = "public"
    source_channel: str = "chat"


class VoiceLanguageSelectionRequest(BaseModel):
    session_id: str
    language_option: int


class VoiceTurnRequest(BaseModel):
    session_id: str
    utterance: str = Field(..., min_length=1)


class VoiceMessage(BaseModel):
    speaker: str
    text: str


class VoiceTicketInfo(BaseModel):
    ticket_id: str
    category: str
    priority: str
    assigned_team: str
    status: str


class VoiceSessionResponse(BaseModel):
    session_id: str
    caller_name: str
    caller_type: str
    language: str | None
    current_state: str
    agent_message: str
    transcript: list[VoiceMessage]
    sentiment_score: float | None = None
    sentiment_label: str | None = None
    created_ticket: VoiceTicketInfo | None = None


class AudioTranscriptResponse(BaseModel):
    transcript: str
    language_detected: str
    sentiment_score: float
    sentiment_label: str
    created_ticket: VoiceTicketInfo | None = None


class DashboardOverview(BaseModel):
    smart_allot: SmartAllotSummary
    anomalies: AnomalySummary
    call_centre: CallCentreSummary
    operational_highlights: list[str]


# ── Transaction / Distribution schemas ────────────────────────────────────────

class TransactionOut(BaseModel):
    id: int
    year: int
    month: str
    district: str
    afso: str
    fps_id: str
    commodity: str
    quantity_kgs: float
    cards: int

    class Config:
        from_attributes = True


class TransactionFilterOptions(BaseModel):
    years: list[int]
    months: list[str]
    districts: list[str]
    afsos: list[str]                   # keyed by district for cascading
    fps_ids: list[str]                 # keyed by afso for cascading
    afsos_by_district: dict[str, list[str]]
    fps_by_afso: dict[str, list[str]]
    commodities: list[str]


class CommodityTotal(BaseModel):
    commodity: str
    total_kgs: float


class TransactionSummary(BaseModel):
    total_fps: int
    total_cards: int
    total_quantity_kgs: float
    commodity_totals: list[CommodityTotal]
    months_covered: list[str]
    districts_covered: list[str]


class ChartDataPoint(BaseModel):
    label: str          # district / afso / fps_id / month
    value: float
    commodity: str | None = None


class TransactionChartData(BaseModel):
    group_by: str
    series: list[ChartDataPoint]
    monthly_trend: list[dict]   # [{month, commodity, quantity_kgs}]
