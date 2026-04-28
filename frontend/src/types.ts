export type SmartAllotRecommendation = {
  forecast_for_month: string;
  state_name: string;
  district_name: string;
  district_code: number;
  item_name: string;
  forecast_next_month: number;
  safety_stock: number;
  carryover_stock_proxy: number;
  recommended_allotment: number;
  volatility_proxy: number;
  last_month_distributed: number;
  last_month_allocated: number;
  model_strategy: string;
};

export type SmartAllotSummary = {
  total_fps: number;
  total_forecast: number;
  total_recommended_allotment: number;
  high_risk_fps: number;
  highest_priority: SmartAllotRecommendation | null;
};

export type SmartAllotModelInfo = {
  model_loaded: boolean;
  model_path: string;
  recommendations_path: string;
  metrics_path: string;
  dataset: {
    raw_file: string;
    cleaned_rows: number;
    item_panel_rows?: number;
    training_rows: number;
    states: number;
    districts: number;
    date_min: string;
    date_max: string;
    items: string[];
  };
  metrics: {
    train_rows: number;
    test_rows: number;
    mae: number;
    rmse: number;
    mape_percent: number;
    wape_percent: number;
  };
};

export type SmartAllotFilters = {
  district_names: string[];
  district_codes: number[];
  items: string[];
};

// ── New ML microservice types ─────────────────────────────────────────────────

export type MLMetrics = {
  mae: number;
  rmse: number;
  mape_pct: number;
  wape_pct: number;
  r2: number;
  bias: number;
  n: number;
};

export type MLModelStatus = {
  module: string;
  models_trained: boolean;
  dataset_loaded: boolean;
  dataset_path: string;
  last_trained: string;
  baseline_available: boolean;
  prophet_available: boolean;
  anomaly_detector_available: boolean;
  overall_metrics: Partial<MLMetrics>;
  improvement_over_naive: { mae_reduction_pct: number; rmse_reduction_pct: number };
};

export type MLPrediction = {
  location: string;
  district: string;
  commodity: string;
  date: string;
  predicted_demand: number;
  lower_bound: number;
  upper_bound: number;
  confidence_score: number;
  model_used: string;
};

export type MLAllocation = {
  location: string;
  district: string;
  mandal: string;
  fps_id: string;
  commodity: string;
  date: string;
  predicted_demand: number;
  recommended_allocation: number;
  confidence_score: number;
  shortage_risk_pct: number;
  overstock_risk_pct: number;
  allocation_method: string;
};

export type MLAllocationSummary = {
  total_predicted_demand: number;
  total_recommended_allocation: number;
  avg_shortage_risk_pct: number;
  avg_overstock_risk_pct: number;
  estimated_required_supply: Record<string, number>;
};

export type MLAnomaly = {
  fps_id: string;
  district: string;
  mandal: string;
  commodity: string;
  date: string;
  demand_kg: number;
  anomaly_score: number;
  severity: string;
  reasons: string[];
  is_anomaly: boolean;
};

export type MLDatasetInfo = {
  total_rows: number;
  date_range: { from: string; to: string };
  districts: string[];
  commodities: string[];
  fps_ids: string[];
  train_rows: number;
  test_rows: number;
  missing_values: Record<string, number>;
};

export type AnomalyAlert = {
  shipment_id: string;
  fps_id: string;
  risk_score: number;
  severity: string;
  quantity_mismatch: number;
  delay_hours: number;
  transaction_spike: number;
  anomaly_detected: boolean;
  reasons: string[];
};

// ── Anomaly Detection v2 (new service endpoints) ──────────────────────────────

export type AnomalyTransaction = {
  transaction_id: string;
  timestamp: string;
  location: string;
  dispatch_quantity: number;
  delivered_quantity: number;
  expected_delivery_time: string;
  actual_delivery_time: string;
  stock_before: number;
  stock_after: number;
};

export type AnomalyResult = {
  transaction_id: string;
  timestamp: string;
  location: string;
  dispatch_quantity: number;
  delivered_quantity: number;
  stock_before: number;
  stock_after: number;
  delivery_delay_hours: number;
  quantity_mismatch: number;
  mismatch_pct: number;
  stock_variation: number;
  isolation_score: number;
  zscore_max: number;
  anomaly_score: number;
  anomaly_type: string;
  severity: string;
  reasons: string[];
  is_anomaly: boolean;
};

export type AnomalyAlertRecord = {
  alert_id: string;
  transaction_id: string;
  location: string;
  timestamp: string;
  severity: string;
  message: string;
  reasons: string[];
  created_at: string;
  acknowledged: boolean;
};

export type AnomalySummaryStats = {
  module: string;
  total_transactions: number;
  total_anomalies: number;
  anomaly_rate_pct: number;
  model_fitted: boolean;
  simulation_running: boolean;
};

export type IngestResponse = {
  module: string;
  ingested: number;
  anomalies_detected: number;
  alerts_generated: number;
  summary: {
    total_ingested: number;
    anomaly_count: number;
    alert_count: number;
    severity_breakdown: Record<string, number>;
    skipped: number;
  };
};

export type TrendDataset = { label: string; data: number[]; color: string };
export type TrendChartData = {
  module: string;
  chart_type: string;
  title: string;
  granularity: string;
  filters: Record<string, string | null>;
  labels: string[];
  datasets: TrendDataset[];
  points: { label: string; dispatch: number; delivered: number; mismatch: number }[];
};

export type AnomalyTimelineData = {
  module: string;
  chart_type: string;
  title: string;
  total: number;
  severity_breakdown: Record<string, number>;
  labels: string[];
  scores: number[];
  severities: string[];
  points: {
    timestamp: string;
    location: string;
    transaction_id: string;
    anomaly_score: number;
    severity: string;
    reasons: string[];
    color: string;
  }[];
};

export type LocationBucket = {
  location: string;
  total_transactions: number;
  anomaly_count: number;
  anomaly_rate_pct: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
};

export type LocationSummaryData = {
  module: string;
  labels: string[];
  anomaly_counts: number[];
  anomaly_rates: number[];
  buckets: LocationBucket[];
};

export type DelayHistogramData = {
  module: string;
  bin_labels: string[];
  datasets: { label: string; data: number[]; color: string }[];
  counts: number[];
  anomalous_counts: number[];
  stats: { mean_delay: number; median_delay: number; max_delay: number; pct_late: number };
};

export type AnomalySummary = {
  total_shipments: number;
  flagged_shipments: number;
  high_severity: number;
  open_investigation_queue: number;
};

export type BotResponse = {
  role: string;
  intent: string;
  answer: string;
  detected_entities: Record<string, string | number | null>;
  insights: string[];
  suggestions: string[];
};

export type ChatResponse = {
  module: string;
  session_id: string;
  user_id: string;
  role: string;
  message: string;
  response: string;
  intent: string;
  intent_confidence: number;
  source: string;
  data: Record<string, unknown>;
  insights: string[];
  suggestions: string[];
  language: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent?: string;
  intent_confidence?: number;
  source?: string;
  insights?: string[];
  suggestions?: string[];
  data?: Record<string, unknown>;
  timestamp: number;
};

// ── Call Centre ───────────────────────────────────────────────────────────────

export type CallCentreTicket = {
  call_id: string;
  caller_name: string;
  language: string;
  category: string;
  priority: string;
  sentiment_score: number;
  sentiment_label: string;
  transcript: string;
  summary: string;
  assigned_team: string;
  next_action: string;
  resolution_eta_hours: number;
  channel: string;
  ticket_id: string;
  status: string;
  district_name?: string | null;
  fps_reference?: string | null;
  created_at?: string | null;
};

export type CallCentreSummary = {
  total_calls: number;
  open_tickets: number;
  high_priority_tickets: number;
  languages_covered: string[];
};

export type CallCentreDashboard = {
  summary: CallCentreSummary;
  forecast: {
    next_day_expected_calls: number;
    predicted_peak_issue: string;
    predicted_peak_language: string;
  };
  performance: {
    average_sentiment_score: number;
    average_resolution_eta_hours: number;
    response_time_minutes: number;
    resolution_rate_percent: number;
  };
  recurring_issues: string[];
  multilingual_support: string[];
};

export type LiveMetrics = {
  active_sessions: number;
  total_tickets: number;
  open_tickets: number;
  resolved_today: number;
  avg_sentiment: number;
  high_priority: number;
  calls_by_language: Record<string, number>;
  calls_by_category: Record<string, number>;
  sentiment_trend: number[];
};

export type AudioTranscriptResponse = {
  transcript: string;
  language_detected: string;
  sentiment_score: number;
  sentiment_label: string;
  created_ticket: VoiceTicketInfo | null;
};

// ── Voice / Chatbot session ───────────────────────────────────────────────────

export type VoiceMessage = {
  speaker: string;
  text: string;
};

export type VoiceTicketInfo = {
  ticket_id: string;
  category: string;
  priority: string;
  assigned_team: string;
  status: string;
};

export type VoiceSession = {
  session_id: string;
  caller_name: string;
  caller_type: string;
  language: string | null;
  current_state: string;
  agent_message: string;
  transcript: VoiceMessage[];
  sentiment_score: number | null;
  sentiment_label: string | null;
  created_ticket: VoiceTicketInfo | null;
};

// ── Call Centre v2 Analytics ─────────────────────────────────────────────────

export type CCChartDataset = {
  label: string;
  data: (number | null)[];
  color: string;
  borderDash?: number[];
};

export type CCChartData = {
  labels: string[];
  datasets: CCChartDataset[];
};

export type CCAnalyticsOverview = {
  module: string;
  kpis: {
    total_tickets: number;
    open_tickets: number;
    resolved_tickets: number;
    high_priority: number;
    today_tickets: number;
    total_sessions: number;
    resolution_rate_pct: number;
    avg_response_time_min: number;
    avg_sentiment_score: number;
    avg_sentiment_label: string;
  };
  top_categories: { name: string; count: number }[];
  language_distribution: Record<string, number>;
  sentiment_distribution: { labels: string[]; data: number[]; colors: string[] };
  priority_distribution: { labels: string[]; data: number[]; colors: string[] };
};

export type CCAnalyticsSentiment = {
  trend: CCChartData;
  distribution: { labels: string[]; data: number[]; colors: string[] };
  by_category: Record<string, number>;
  summary: {
    avg_score: number;
    avg_label: string;
    distressed: number;
    negative: number;
    neutral: number;
    positive: number;
    pct_negative: number;
  };
};

export type CCAnalyticsTickets = {
  by_category: { labels: string[]; data: number[]; colors: string[] };
  by_priority: { labels: string[]; data: number[]; colors: string[] };
  by_status: { labels: string[]; data: number[]; colors: string[] };
  resolution_sla: { labels: string[]; data: number[]; colors: string[] };
  creation_trend: CCChartData;
  open_vs_close: CCChartData;
  summary: {
    total: number;
    open: number;
    in_progress: number;
    resolved: number;
    resolution_rate: number;
  };
};

export type CCCallVolume = {
  module: string;
  volume: {
    labels: string[];
    datasets: CCChartDataset[];
    summary: {
      next_day_expected: number;
      avg_last_7_days: number;
      total_last_14_days: number;
      trend: string;
    };
  };
  peak_hours: {
    labels: string[];
    datasets: CCChartDataset[];
    peak_hour: string;
    peak_count: number;
    total_calls: number;
    off_hours_pct: number;
  };
};

export type CCAgentRecord = {
  agent_id: string;
  agent_name: string;
  team: string;
  total_tickets: number;
  resolved: number;
  resolution_rate: number;
  avg_sentiment: number;
  sla_violations: number;
  performance_score: number;
  grade: string;
};

export type CCNotification = {
  id: string;
  channel: string;
  recipient: string;
  subject: string;
  body: string;
  ticket_id: string;
  sent_at: string;
  status: string;
};

export type CCSLABreach = {
  ticket_id: string;
  category: string;
  priority: string;
  status: string;
  created_at: string;
  sla_deadline: string;
  overdue_hours: number;
  caller_name: string;
};

export type CCCallPipelineResult = {
  module: string;
  call_id: string;
  language: string;
  transcript: {
    text: string;
    confidence_score: number;
    source: string;
    word_count: number;
  };
  sentiment: {
    score: number;
    label: string;
    keywords: string[];
    method: string;
  };
  chatbot: {
    response: string;
    intent: string;
    intent_confidence: number;
    source: string;
    suggestions: string[];
    session_id: string;
  };
  ticket: {
    ticket_id: string;
    category: string;
    priority: string;
    assigned_team: string;
    eta_hours: number;
    escalated: boolean;
  } | null;
  ticket_created: boolean;
};

// ── Auth / RBAC ───────────────────────────────────────────────────────────────

export type UserRole =
  | "STATE_ADMIN"
  | "DISTRICT_ADMIN"
  | "MANDAL_ADMIN"
  | "AFSO"
  | "FPS_DEALER"
  | "RATION_CARD_HOLDER";

export type AuthUser = {
  user_id:     string;
  username:    string;
  email:       string;
  full_name:   string;
  role:        UserRole;
  state_id:    string | null;
  district_id: string | null;
  mandal_id:   string | null;
  fps_id:      string | null;
  is_active:   boolean;
};

export type LoginResponse = {
  access_token: string;
  token_type:   string;
  user:         AuthUser;
};

// ── Dashboard overview ────────────────────────────────────────────────────────

export type DashboardOverview = {
  smart_allot: SmartAllotSummary;
  anomalies: AnomalySummary;
  call_centre: CallCentreSummary;
  operational_highlights: string[];
};
