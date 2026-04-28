import type {
  AnomalyAlert,
  AnomalyAlertRecord,
  AnomalyResult,
  AnomalySummaryStats,
  AnomalyTimelineData,
  AnomalyTransaction,
  AudioTranscriptResponse,
  AuthUser,
  BotResponse,
  ChatResponse,
  CallCentreDashboard,
  CallCentreTicket,
  CCAgentRecord,
  CCAnalyticsOverview,
  CCAnalyticsSentiment,
  CCAnalyticsTickets,
  CCCallPipelineResult,
  CCCallVolume,
  CCNotification,
  CCSLABreach,
  DashboardOverview,
  DelayHistogramData,
  IngestResponse,
  LiveMetrics,
  LocationSummaryData,
  LoginResponse,
  MLAllocation,
  MLAllocationSummary,
  MLAnomaly,
  MLDatasetInfo,
  MLModelStatus,
  MLPrediction,
  SmartAllotFilters,
  SmartAllotModelInfo,
  SmartAllotRecommendation,
  TrendChartData,
  VoiceSession,
  UserRole,
} from "./types";
import { getStoredToken } from "./context/AuthContext";

const SVC = {
  auth:        import.meta.env.VITE_AUTH_URL         ?? "http://localhost:8000",
  overview:    import.meta.env.VITE_OVERVIEW_URL      ?? "http://localhost:8001",
  smartAllot:  import.meta.env.VITE_SMART_ALLOT_URL   ?? "http://localhost:8002",
  anomalies:   import.meta.env.VITE_ANOMALIES_URL     ?? "http://localhost:8003",
  pdsaibot:    import.meta.env.VITE_PDSAIBOT_URL      ?? "http://localhost:8004",
  callCentre:  import.meta.env.VITE_CALL_CENTRE_URL   ?? "http://localhost:8005",
};

type TxFilterLike = {
  year?: number;
  month?: string;
  district?: string;
  afso?: string;
  fps_id?: string;
  commodity?: string;
};

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...authHeaders() },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.json().then((j: { detail?: string }) => j.detail).catch(() => null);
    throw new Error(detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(username: string, password: string): Promise<LoginResponse> {
  const response = await fetch(`${SVC.auth}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    const detail = await response.json().then((j: { detail?: string }) => j.detail).catch(() => null);
    throw new Error(detail ?? "Login failed");
  }
  return response.json() as Promise<LoginResponse>;
}

export function fetchUsers(role?: UserRole | string) {
  const qs = role ? `?role=${encodeURIComponent(String(role))}` : "";
  return request<AuthUser[]>(`${SVC.auth}/auth/users${qs}`);
}

export function registerUser(body: {
  username: string;
  email: string;
  password: string;
  full_name: string;
  role: UserRole;
  state_id?: string | null;
  district_id?: string | null;
  mandal_id?: string | null;
  fps_id?: string | null;
  ration_card_id?: string | null;
}) {
  return request<AuthUser>(`${SVC.auth}/auth/register`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateUser(user_id: string, body: Partial<{
  full_name: string;
  role: UserRole;
  is_active: boolean;
  state_id: string | null;
  district_id: string | null;
  mandal_id: string | null;
  fps_id: string | null;
}>) {
  return request<AuthUser>(`${SVC.auth}/auth/users/${encodeURIComponent(user_id)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

// ── Overview ──────────────────────────────────────────────────────────────────

export function fetchOverview() {
  return request<DashboardOverview>(`${SVC.overview}/api/overview`);
}

// ── SMARTAllot ────────────────────────────────────────────────────────────────

export function fetchRecommendations(filters?: {
  districtName?: string;
  districtCode?: string;
  itemName?: string;
}) {
  const params = new URLSearchParams();
  if (filters?.districtName) params.set("district_name", filters.districtName);
  if (filters?.districtCode) params.set("district_code", filters.districtCode);
  if (filters?.itemName) params.set("item_name", filters.itemName);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request<{ module: string; recommendations: SmartAllotRecommendation[] }>(
    `${SVC.smartAllot}/api/smart-allot/recommendations${qs}`,
  );
}

export function fetchSmartAllotModelInfo() {
  return request<{ module: string; model_info: SmartAllotModelInfo }>(
    `${SVC.smartAllot}/api/smart-allot/model-info`,
  );
}

export function fetchSmartAllotFilters() {
  return request<{ module: string; filters: SmartAllotFilters }>(
    `${SVC.smartAllot}/api/smart-allot/filters`,
  );
}

// ── Anomalies (legacy) ────────────────────────────────────────────────────────

export function fetchAnomalies() {
  return request<{ module: string; alerts: AnomalyAlert[] }>(`${SVC.anomalies}/api/anomalies`);
}

// ── Anomaly Detection v2 ──────────────────────────────────────────────────────

export function fetchAnomalySummary() {
  return request<AnomalySummaryStats>(`${SVC.anomalies}/api/anomaly/summary`);
}

export function fetchAnomalyList(filters?: {
  location?: string;
  severity?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
}) {
  const p = new URLSearchParams();
  if (filters?.location)  p.set("location", filters.location);
  if (filters?.severity)  p.set("severity", filters.severity);
  if (filters?.date_from) p.set("date_from", filters.date_from);
  if (filters?.date_to)   p.set("date_to",   filters.date_to);
  if (filters?.limit)     p.set("limit",      String(filters.limit));
  const qs = p.toString() ? `?${p}` : "";
  return request<{ module: string; total: number; anomalies: AnomalyResult[] }>(
    `${SVC.anomalies}/api/anomaly/anomalies${qs}`,
  );
}

export function fetchAlertList(filters?: {
  location?: string;
  severity?: string;
  acknowledged?: boolean;
  limit?: number;
}) {
  const p = new URLSearchParams();
  if (filters?.location)            p.set("location",     filters.location);
  if (filters?.severity)            p.set("severity",     filters.severity);
  if (filters?.acknowledged != null) p.set("acknowledged", String(filters.acknowledged));
  if (filters?.limit)               p.set("limit",        String(filters.limit));
  const qs = p.toString() ? `?${p}` : "";
  return request<{ module: string; total: number; alerts: AnomalyAlertRecord[] }>(
    `${SVC.anomalies}/api/anomaly/alerts${qs}`,
  );
}

export function acknowledgeAlert(alertId: string) {
  return request<{ module: string; alert_id: string; acknowledged: boolean }>(
    `${SVC.anomalies}/api/anomaly/alerts/${alertId}/acknowledge`,
    { method: "PATCH" },
  );
}

export function ingestTransactions(transactions: AnomalyTransaction[]) {
  return request<IngestResponse>(`${SVC.anomalies}/api/anomaly/ingest-data`, {
    method: "POST",
    body: JSON.stringify({ transactions }),
  });
}

export function fetchTrendChart(params?: {
  granularity?: string;
  location?: string;
  date_from?: string;
  date_to?: string;
}) {
  const p = new URLSearchParams();
  if (params?.granularity) p.set("granularity", params.granularity);
  if (params?.location)    p.set("location",    params.location);
  if (params?.date_from)   p.set("date_from",   params.date_from);
  if (params?.date_to)     p.set("date_to",     params.date_to);
  const qs = p.toString() ? `?${p}` : "";
  return request<TrendChartData>(`${SVC.anomalies}/api/anomaly/visualization/trends${qs}`);
}

export function fetchAnomalyTimeline(params?: {
  location?: string;
  severity?: string;
  date_from?: string;
  date_to?: string;
}) {
  const p = new URLSearchParams();
  if (params?.location)  p.set("location",  params.location);
  if (params?.severity)  p.set("severity",  params.severity);
  if (params?.date_from) p.set("date_from", params.date_from);
  if (params?.date_to)   p.set("date_to",   params.date_to);
  const qs = p.toString() ? `?${p}` : "";
  return request<AnomalyTimelineData>(`${SVC.anomalies}/api/anomaly/visualization/anomalies${qs}`);
}

export function fetchLocationSummary(params?: { date_from?: string; date_to?: string }) {
  const p = new URLSearchParams();
  if (params?.date_from) p.set("date_from", params.date_from);
  if (params?.date_to)   p.set("date_to",   params.date_to);
  const qs = p.toString() ? `?${p}` : "";
  return request<LocationSummaryData>(`${SVC.anomalies}/api/anomaly/visualization/location-summary${qs}`);
}

export function fetchDelayHistogram(params?: { location?: string; bins?: number }) {
  const p = new URLSearchParams();
  if (params?.location) p.set("location", params.location);
  if (params?.bins)     p.set("bins",     String(params.bins));
  const qs = p.toString() ? `?${p}` : "";
  return request<DelayHistogramData>(`${SVC.anomalies}/api/anomaly/visualization/delay-distribution${qs}`);
}

export function startSimulation(params?: { interval_seconds?: number; anomaly_rate?: number }) {
  const p = new URLSearchParams();
  if (params?.interval_seconds != null) p.set("interval_seconds", String(params.interval_seconds));
  if (params?.anomaly_rate     != null) p.set("anomaly_rate",     String(params.anomaly_rate));
  const qs = p.toString() ? `?${p}` : "";
  return request<{ module: string; simulation: string }>(`${SVC.anomalies}/api/anomaly/simulation/start${qs}`, { method: "POST" });
}

export function stopSimulation() {
  return request<{ module: string; simulation: string }>(`${SVC.anomalies}/api/anomaly/simulation/stop`, { method: "POST" });
}

export function fetchSimulationStatus() {
  return request<{ module: string; running: boolean }>(`${SVC.anomalies}/api/anomaly/simulation/status`);
}

// ── Call Centre — tickets ─────────────────────────────────────────────────────

export function fetchTickets() {
  return request<{ module: string; tickets: CallCentreTicket[] }>(
    `${SVC.callCentre}/api/call-centre/tickets`,
  );
}

export function updateTicketStatus(ticketId: string, status: string) {
  return request<{ module: string; ticket_id: string; status: string }>(
    `${SVC.callCentre}/api/call-centre/tickets/${ticketId}/status`,
    { method: "PATCH", body: JSON.stringify({ status }) },
  );
}

// ── Call Centre — dashboard ───────────────────────────────────────────────────

export function fetchCallCentreDashboard() {
  return request<{ module: string; dashboard: CallCentreDashboard }>(
    `${SVC.callCentre}/api/call-centre/dashboard`,
  );
}

export function fetchLiveMetrics() {
  return request<{ module: string; metrics: LiveMetrics }>(
    `${SVC.callCentre}/api/call-centre/live-metrics`,
  );
}

// ── Call Centre — chatbot session ─────────────────────────────────────────────

export function startVoiceSession(callerName: string, callerType: string) {
  return request<{ module: string; session: VoiceSession }>(
    `${SVC.callCentre}/api/call-centre/voice/session/start`,
    { method: "POST", body: JSON.stringify({ caller_name: callerName, caller_type: callerType, source_channel: "chat" }) },
  );
}

export function setVoiceLanguage(sessionId: string, languageOption: number) {
  return request<{ module: string; session: VoiceSession }>(
    `${SVC.callCentre}/api/call-centre/voice/session/language`,
    { method: "POST", body: JSON.stringify({ session_id: sessionId, language_option: languageOption }) },
  );
}

export function sendVoiceMessage(sessionId: string, utterance: string) {
  return request<{ module: string; session: VoiceSession }>(
    `${SVC.callCentre}/api/call-centre/voice/session/message`,
    { method: "POST", body: JSON.stringify({ session_id: sessionId, utterance }) },
  );
}

// ── Call Centre — audio upload ────────────────────────────────────────────────

export async function uploadAudio(
  file: File,
  language: string,
  callerName: string,
  callerType: string,
): Promise<AudioTranscriptResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("language", language);
  form.append("caller_name", callerName);
  form.append("caller_type", callerType);
  const response = await fetch(`${SVC.callCentre}/api/call-centre/audio/transcribe`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(`Audio upload failed: ${response.status}`);
  return response.json() as Promise<AudioTranscriptResponse>;
}

// ── WebSocket — live metrics ──────────────────────────────────────────────────

export function createLiveMetricsSocket(onMessage: (metrics: LiveMetrics) => void): WebSocket {
  const wsUrl = SVC.callCentre.replace(/^http/, "ws");
  const ws = new WebSocket(`${wsUrl}/api/call-centre/ws/live`);
  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data) as LiveMetrics);
    } catch {
      // ignore malformed frames
    }
  };
  return ws;
}

// ── Call Centre v2 Analytics ─────────────────────────────────────────────────

export function fetchCCAnalyticsOverview() {
  return request<CCAnalyticsOverview>(`${SVC.callCentre}/api/call-centre/analytics/overview`);
}

export function fetchCCAnalyticsSentiment() {
  return request<CCAnalyticsSentiment>(`${SVC.callCentre}/api/call-centre/analytics/sentiment`);
}

export function fetchCCAnalyticsTickets() {
  return request<CCAnalyticsTickets>(`${SVC.callCentre}/api/call-centre/analytics/tickets`);
}

export function fetchCCCallVolume() {
  return request<CCCallVolume>(`${SVC.callCentre}/api/call-centre/analytics/call-volume`);
}

export function fetchCCAgentPerformance() {
  return request<{ module: string; agents: CCAgentRecord[] }>(
    `${SVC.callCentre}/api/call-centre/agents/performance`,
  );
}

export function fetchCCSLABreaches() {
  return request<{ breach_count: number; critical_count: number; breaches: CCSLABreach[] }>(
    `${SVC.callCentre}/api/call-centre/sla/breaches`,
  );
}

export function fetchCCNotifications(limit = 50) {
  return request<{ notifications: CCNotification[]; total: number }>(
    `${SVC.callCentre}/api/call-centre/notifications?limit=${limit}`,
  );
}

export async function submitCallPipeline(
  textInput: string,
  callerName: string,
  callerType: string,
  role: string,
  language = "English",
): Promise<CCCallPipelineResult> {
  const form = new FormData();
  form.append("text_input",  textInput);
  form.append("caller_name", callerName);
  form.append("caller_type", callerType);
  form.append("role",        role);
  form.append("language",    language);
  const response = await fetch(`${SVC.callCentre}/api/call-centre/call`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(`Pipeline failed: ${response.status}`);
  return response.json() as Promise<CCCallPipelineResult>;
}

export function getTTSUrl(text: string, language: string): string {
  return `${SVC.callCentre}/api/call-centre/ivr/tts?text=${encodeURIComponent(text)}&language=${encodeURIComponent(language)}`;
}

export async function submitVoiceRecording(
  audioBlob: Blob,
  language: string,
  callerName = "Browser Caller",
): Promise<CCCallPipelineResult> {
  const mimeType = audioBlob.type || "audio/webm";
  const ext = mimeType.includes("ogg") ? "ogg" : "webm";
  const form = new FormData();
  form.append("audio_file", new File([audioBlob], `recording.${ext}`, { type: mimeType }));
  form.append("language",    language);
  form.append("caller_name", callerName);
  form.append("caller_type", "public");
  form.append("role",        "citizen");
  const resp = await fetch(`${SVC.callCentre}/api/call-centre/call`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(`Voice pipeline failed: ${resp.status}`);
  return resp.json() as Promise<CCCallPipelineResult>;
}

export function fetchIVRConfig() {
  return request<{
    twilio_configured: boolean;
    account_sid_set: boolean;
    auth_token_set: boolean;
    phone_number: string;
    public_base_url: string;
    active_ivr_sessions: number;
    languages_supported: string[];
    webhooks: Record<string, string>;
    setup_instructions: string[];
  }>(`${SVC.callCentre}/api/call-centre/ivr/config`);
}

// ── PDSAIBot ──────────────────────────────────────────────────────────────────

export function askBot(query: string, role: string) {
  return request<{ module: string; response: BotResponse }>(`${SVC.pdsaibot}/api/bot/query`, {
    method: "POST",
    body: JSON.stringify({ query, role }),
  });
}

export function chatWithBot(
  message: string,
  role: string,
  sessionId: string | null,
  userId = "web-user",
  language = "English",
) {
  return request<ChatResponse>(`${SVC.pdsaibot}/api/bot/chat`, {
    method: "POST",
    body: JSON.stringify({ message, role, session_id: sessionId, user_id: userId, language }),
  });
}

export function clearBotSession(sessionId: string) {
  return request<{ session_id: string; status: string }>(
    `${SVC.pdsaibot}/api/bot/sessions/${sessionId}`,
    { method: "DELETE" },
  );
}

export function debugNlu(message: string) {
  return request<{ input: string; intent: string; confidence: number; entities: Record<string, unknown>; source: string }>(
    `${SVC.pdsaibot}/api/bot/debug/nlu`,
    { method: "POST", body: JSON.stringify({ message }) },
  );
}

// ── SMARTAllot ML endpoints ───────────────────────────────────────────────────

export function fetchMLModelStatus() {
  return request<MLModelStatus>(`${SVC.smartAllot}/api/smart-allot/model-info`);
}

export function fetchMLDatasetInfo() {
  return request<{ module: string } & MLDatasetInfo>(`${SVC.smartAllot}/api/smart-allot/dataset-info`);
}

export function fetchMLPredictions(futurePeriods = 3, filters?: TxFilterLike) {
  return request<{ module: string; predictions: MLPrediction[]; count: number }>(
    `${SVC.smartAllot}/api/smart-allot/predict-demand`,
    {
      method: "POST",
      body: JSON.stringify({
        future_periods: futurePeriods,
        year: filters?.year ?? null,
        month: filters?.month ?? null,
        district: filters?.district ?? null,
        afso: filters?.afso ?? null,
        fps_id: filters?.fps_id ?? null,
        commodity: filters?.commodity ?? null,
        source: "db",
      }),
    },
  );
}

export function fetchMLAllocation(
  futurePeriods = 3,
  totalSupply?: Record<string, number>,
  filters?: TxFilterLike,
) {
  return request<{ module: string; summary: MLAllocationSummary; allocations: MLAllocation[] }>(
    `${SVC.smartAllot}/api/smart-allot/optimize-allocation`,
    {
      method: "POST",
      body: JSON.stringify({
        future_periods: futurePeriods,
        year: filters?.year ?? null,
        month: filters?.month ?? null,
        district: filters?.district ?? null,
        afso: filters?.afso ?? null,
        fps_id: filters?.fps_id ?? null,
        commodity: filters?.commodity ?? null,
        total_supply: totalSupply ?? null,
        source: "db",
      }),
    },
  );
}

export function fetchMLAnomalies(district?: string, commodity?: string, severity?: string) {
  const params = new URLSearchParams();
  if (district) params.set("district", district);
  if (commodity) params.set("commodity", commodity);
  if (severity) params.set("severity", severity);
  params.set("source", "db");
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request<{
    module: string;
    total_records_scanned: number;
    total_anomalies: number;
    anomaly_rate_pct: number;
    severity_breakdown: Record<string, number>;
    anomalies: MLAnomaly[];
  }>(`${SVC.smartAllot}/api/smart-allot/anomalies${qs}`);
}

export function triggerMLRetrain(testMonths = 3) {
  return request<{ module: string; status: string; metrics: Record<string, number>; training_duration_seconds: number }>(
    `${SVC.smartAllot}/api/smart-allot/retrain`,
    { method: "POST", body: JSON.stringify({ test_months: testMonths }) },
  );
}

export function trainDbDemandModel() {
  return request<{ module: string; status: string; trained_at: string; plots: string[] }>(
    `${SVC.smartAllot}/api/smart-allot/train-demand-model`,
    { method: "POST" },
  );
}

export function getDbDemandPlotUrl(filename: string) {
  return `${SVC.smartAllot}/api/smart-allot/demand-model/plots/${encodeURIComponent(filename)}`;
}

export async function uploadMLDataset(file: File): Promise<{ module: string; rows: number; status: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${SVC.smartAllot}/api/smart-allot/upload-data`, { method: "POST", body: form });
  if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
  return response.json();
}

// ── Distribution / Transactions (real CSV data) ───────────────────────────────

export interface TxFilters {
  year?: number;
  month?: string;
  district?: string;
  afso?: string;
  fps_id?: string;
  commodity?: string;
}

function buildTxParams(f?: TxFilters): string {
  const p = new URLSearchParams();
  if (f?.year)      p.set("year",      String(f.year));
  if (f?.month)     p.set("month",     f.month);
  if (f?.district)  p.set("district",  f.district);
  if (f?.afso)      p.set("afso",      f.afso);
  if (f?.fps_id)    p.set("fps_id",    f.fps_id);
  if (f?.commodity) p.set("commodity", f.commodity);
  return p.toString() ? `?${p}` : "";
}

export function fetchTransactionFilters() {
  return request<{
    module: string;
    filters: {
      years: number[];
      months: string[];
      districts: string[];
      afsos: string[];
      fps_ids: string[];
      commodities: string[];
      afsos_by_district: Record<string, string[]>;
      fps_by_afso: Record<string, string[]>;
    };
  }>(`${SVC.smartAllot}/api/transactions/filters`);
}

export function fetchTransactionSummary(f?: TxFilters) {
  return request<{
    module: string;
    summary: {
      total_fps: number;
      total_cards: number;
      total_quantity_kgs: number;
      commodity_totals: { commodity: string; total_kgs: number }[];
      months_covered: string[];
      districts_covered: string[];
    };
  }>(`${SVC.smartAllot}/api/transactions/summary${buildTxParams(f)}`);
}

export function fetchTransactions(f?: TxFilters & { skip?: number; limit?: number }) {
  const p = new URLSearchParams();
  if (f?.year)      p.set("year",      String(f.year));
  if (f?.month)     p.set("month",     f.month!);
  if (f?.district)  p.set("district",  f.district!);
  if (f?.afso)      p.set("afso",      f.afso!);
  if (f?.fps_id)    p.set("fps_id",    f.fps_id!);
  if (f?.commodity) p.set("commodity", f.commodity!);
  if (f?.skip  != null) p.set("skip",  String(f.skip));
  if (f?.limit != null) p.set("limit", String(f.limit));
  const qs = p.toString() ? `?${p}` : "";
  return request<{
    module: string;
    total: number;
    skip: number;
    limit: number;
    records: {
      id: number; year: number; month: string; district: string;
      afso: string; fps_id: string; commodity: string;
      quantity_kgs: number; cards: number;
    }[];
  }>(`${SVC.smartAllot}/api/transactions${qs}`);
}

export function fetchTransactionChartData(
  groupBy: "district" | "afso" | "fps_id" | "month" = "district",
  f?: TxFilters,
) {
  const p = new URLSearchParams({ group_by: groupBy });
  if (f?.year)      p.set("year",      String(f.year));
  if (f?.month)     p.set("month",     f.month!);
  if (f?.district)  p.set("district",  f.district!);
  if (f?.afso)      p.set("afso",      f.afso!);
  if (f?.fps_id)    p.set("fps_id",    f.fps_id!);
  if (f?.commodity) p.set("commodity", f.commodity!);
  return request<{
    module: string;
    chart_data: {
      group_by: string;
      series: { label: string; value: number; commodity?: string }[];
      monthly_trend: { month: string; commodity: string; quantity_kgs: number }[];
    };
  }>(`${SVC.smartAllot}/api/transactions/chart-data?${p}`);
}

export function fetchFpsDetail(fpsId: string, year?: number) {
  const qs = year ? `?year=${year}` : "";
  return request<{
    module: string;
    detail: {
      fps_id: string; district: string; afso: string; year: number;
      records: {
        id: number; year: number; month: string; district: string;
        afso: string; fps_id: string; commodity: string;
        quantity_kgs: number; cards: number;
      }[];
    };
  }>(`${SVC.smartAllot}/api/transactions/fps-detail/${fpsId}${qs}`);
}

// ── New: Anomalies / Map / FPS-List ───────────────────────────────────────────

export interface TxAnomalyRecord {
  id: number;
  fps_id: string;
  district: string;
  afso: string;
  month: string;
  year: number;
  commodity: string;
  quantity_kgs: number;
  cards: number;
  anomaly_type: "ZERO_DISTRIBUTION" | "LOW_DRAWL_RATIO" | "OUTLIER_HIGH" | "OUTLIER_LOW";
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  detail: string;
  expected_qty: number;
}

export interface MapMarker {
  label: string;
  district: string;
  afso: string;
  lat: number;
  lng: number;
  qty_kgs: number;
  fps_count: number;
}

export function fetchTxAnomalies(
  f?: TxFilters & { threshold_std?: number; limit?: number }
) {
  const p = new URLSearchParams();
  if (f?.year)           p.set("year",           String(f.year));
  if (f?.month)          p.set("month",           f.month!);
  if (f?.district)       p.set("district",        f.district!);
  if (f?.afso)           p.set("afso",            f.afso!);
  if (f?.fps_id)         p.set("fps_id",          f.fps_id!);
  if (f?.commodity)      p.set("commodity",       f.commodity!);
  if (f?.threshold_std)  p.set("threshold_std",   String(f.threshold_std));
  if (f?.limit)          p.set("limit",           String(f.limit));
  return request<{
    module: string;
    total: number;
    records_scanned: number;
    anomaly_rate_pct: number;
    severity_breakdown: Record<string, number>;
    anomalies: TxAnomalyRecord[];
  }>(`${SVC.smartAllot}/api/transactions/anomalies${p.toString() ? "?" + p : ""}`);
}

export function fetchTxMapData(
  level: "district" | "afso" | "fps" = "district",
  f?: TxFilters
) {
  const p = new URLSearchParams({ level });
  if (f?.year)      p.set("year",      String(f.year));
  if (f?.month)     p.set("month",     f.month!);
  if (f?.district)  p.set("district",  f.district!);
  if (f?.afso)      p.set("afso",      f.afso!);
  if (f?.fps_id)    p.set("fps_id",    f.fps_id!);
  if (f?.commodity) p.set("commodity", f.commodity!);
  return request<{
    module: string;
    level: string;
    markers: MapMarker[];
  }>(`${SVC.smartAllot}/api/transactions/map-data?${p}`);
}

export function fetchTxFpsList(
  f?: TxFilters & { skip?: number; limit?: number }
) {
  const p = new URLSearchParams();
  if (f?.year)      p.set("year",      String(f.year));
  if (f?.month)     p.set("month",     f.month!);
  if (f?.district)  p.set("district",  f.district!);
  if (f?.afso)      p.set("afso",      f.afso!);
  if (f?.commodity) p.set("commodity", f.commodity!);
  if (f?.skip != null)  p.set("skip",  String(f.skip));
  if (f?.limit != null) p.set("limit", String(f.limit));
  return request<{
    module: string;
    total: number;
    fps_list: {
      fps_id: string; district: string; afso: string;
      total_qty_kgs: number; cards: number; months_active: number;
    }[];
  }>(`${SVC.smartAllot}/api/transactions/fps-list${p.toString() ? "?" + p : ""}`);
}

export function reloadTransactions() {
  return request<{
    module: string;
    status: string;
    transaction_rows: number;
    fps_metric_rows: number;
  }>(`${SVC.smartAllot}/api/transactions/reload`, { method: "POST" });
}
