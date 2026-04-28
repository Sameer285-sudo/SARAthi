import React, { useEffect, useRef, useState, useMemo, startTransition } from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { MapContainer, TileLayer, CircleMarker, Tooltip as LeafletTooltip } from "react-leaflet";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer,
  ComposedChart, PieChart, Pie, Cell, ReferenceLine
} from "recharts";
import { Zap, ChevronRight, TrendingUp, AlertTriangle, Layers, Map as MapIcon, CheckCircle, ChevronDown, ChevronUp } from "lucide-react";
import { SarathiInsightsCard } from "../components/SarathiInsightsCard";
import {
  fetchMLModelStatus,
  fetchMLDatasetInfo,
  fetchMLPredictions,
  fetchMLAllocation,
  fetchMLAnomalies,
  triggerMLRetrain,
  uploadMLDataset,
  trainDbDemandModel,
  getDbDemandPlotUrl,
  fetchRecommendations,
  fetchTransactionFilters,
  fetchTransactionSummary,
  fetchTransactionChartData,
  fetchTxMapData,
  fetchTxAnomalies,
  type TxFilters,
  reloadTransactions,
} from "../api";

const AP_COORDS: Record<string, [number, number]> = {
  // New dataset districts
  "Annamayya": [14.05, 78.75],
  "Chittoor":  [13.22, 79.10],
  // Legacy LP-model districts (kept for AllocateTab fallback)
  "Visakhapatnam-District": [17.6868, 83.2185],
  "Guntur-District": [16.3067, 80.4365],
  "Krishna-District": [16.2998, 81.1121],
  "Kurnool-District": [15.8281, 78.0373],
  "Tirupati-District": [13.6288, 79.4192],
  "Anantapur-District": [14.6819, 77.6006],
  "Prakasam-District": [15.5015, 79.9696],
  "Nandyal-District": [15.4855, 78.4842],
  "Palnadu-District": [16.2415, 79.7423],
};
const DEFAULT_COORD: [number, number] = [15.9129, 79.7400];

function kgScaleFor(maxKg: number) {
  const m = Math.max(0, Number(maxKg) || 0);
  if (m >= 10_000_000) return { div: 10_000_000, unit: "Cr" }; // crore
  if (m >= 1_000_000) return { div: 1_000_000, unit: "M" };
  if (m >= 100_000) return { div: 100_000, unit: "L" }; // lakh
  if (m >= 10_000) return { div: 1_000, unit: "K" };
  return { div: 1, unit: "" };
}

function fmtKg(v: unknown, scale?: { div: number; unit: string }) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "â€”";
  const s = scale ?? kgScaleFor(n);
  const d = s.div;
  const decimals = d >= 1_000_000 ? 2 : d >= 100_000 ? 2 : d >= 1_000 ? 1 : 0;
  return `${(n / d).toFixed(decimals)}${s.unit} kg`;
}

const MAP_LAYERS = {
  landscape: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
  satellite: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
};

type Tab = "overview" | "predict" | "allocate" | "anomalies" | "data";

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: "#ef4444",
  HIGH: "#f97316",
  MEDIUM: "#eab308",
  LOW: "#22c55e",
};

type ExplainableInsight = {
  text: string;
  source: string;
  derived?: boolean;
};

function fmt(v: unknown, decimals = 2) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(decimals) : "—";
}

function colorForLabel(label: string) {
  // Deterministic HSL from a string hash so each commodity stays distinct.
  let h = 0;
  for (let i = 0; i < label.length; i++) h = (h * 31 + label.charCodeAt(i)) >>> 0;
  const hue = h % 360;
  const sat = 62 + (h % 18);
  const lit = 42 + (h % 14);
  return `hsl(${hue} ${sat}% ${lit}%)`;
}

function paletteForLabels(labels: string[]) {
  // Guaranteed-distinct palette by index (golden-angle hues).
  const out: Record<string, string> = {};
  const uniq = Array.from(new Set(labels)).sort((a, b) => a.localeCompare(b));
  for (let i = 0; i < uniq.length; i++) {
    const hue = (i * 137.508) % 360;
    out[uniq[i]] = `hsl(${hue} 70% 48%)`;
  }
  return out;
}

function Badge({ text, color }: { text: string; color?: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 700,
        background: color ?? "#334155",
        color: "#fff",
        letterSpacing: "0.04em",
      }}
    >
      {text}
    </span>
  );
}

function ChartSkeleton({ height }: { height: number }) {
  return (
    <div style={{
      height,
      background: "linear-gradient(90deg, rgba(226,232,240,0.5) 25%, rgba(241,245,249,0.8) 50%, rgba(226,232,240,0.5) 75%)",
      backgroundSize: "200% 100%",
      animation: "shimmer 1.5s infinite",
      borderRadius: 8,
    }} />
  );
}

// ── Overview tab ───────────────────────────────────────────────────────────────

function OverviewTab({
  tx,
  meta,
  setField,
}: {
  tx: TxFilters;
  meta: any;
  setField: (k: keyof TxFilters, v: any) => void;
}) {
  const recsQ = useQuery({
    queryKey: ["recommendations", tx.district, tx.commodity],
    queryFn: () => fetchRecommendations({
      districtName: tx.district || undefined,
      itemName: tx.commodity || undefined,
    }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  // Real monthly totals from DB (used for the timeline chart; not a mock)
  const monthlyQ = useQuery({
    queryKey: ["tx-monthly-trend", tx.year, tx.district, tx.afso, tx.fps_id, tx.commodity],
    queryFn: () => fetchTransactionChartData("month", {
      year: tx.year,
      district: tx.district,
      afso: tx.afso,
      fps_id: tx.fps_id,
      commodity: tx.commodity,
    } as any).catch(() => ({ chart_data: { monthly_trend: [] } } as any)),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  // DB forecast for the same unit scope (district/afso/fps) so the timeline scale stays consistent.
  const timelineForecastQ = useQuery({
    queryKey: ["ml-predictions-timeline", tx.year, tx.month, tx.district, tx.afso, tx.fps_id, tx.commodity],
    queryFn: () => fetchMLPredictions(1, tx).catch(() => ({ predictions: [] } as any)),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const [activeLayer, setActiveLayer] = useState<"demand" | "allocation" | "gap">("gap");
  const [mapType, setMapType] = useState<"landscape" | "satellite">("landscape");
  const [expandedDistrict, setExpandedDistrict] = useState<string | null>(null);

  const years: number[] = meta?.years ?? [];
  const districts: string[] = meta?.districts ?? [];
  const months: string[] = meta?.months ?? [];
  const commodities: string[] = meta?.commodities ?? [];
  const afsos: string[] = tx.district ? (meta?.afsos_by_district?.[tx.district] ?? []) : [];
  const fpsIds: string[] = tx.afso ? (meta?.fps_by_afso?.[tx.afso] ?? []) : [];

  const mapLevel: "district" | "afso" | "fps" =
    tx.afso ? "fps" : (tx.district ? "afso" : "district");

  const mapQ = useQuery({
    queryKey: ["tx-map-smartallot", mapLevel, tx.district, tx.afso, tx.fps_id, tx.month, tx.commodity, tx.year],
    queryFn: () => fetchTxMapData(mapLevel, {
      district: tx.district,
      afso: tx.afso,
      fps_id: tx.fps_id,
      month: tx.month,
      commodity: tx.commodity,
      year: tx.year,
    }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const recs = recsQ.data?.recommendations || [];
  const markersRaw = (mapQ.data as any)?.markers ?? [];
  const markers = tx.fps_id ? markersRaw.filter((m: any) => String(m.label) === String(tx.fps_id)) : markersRaw;
  const isUpdating = recsQ.isFetching || mapQ.isFetching || monthlyQ.isFetching || timelineForecastQ.isFetching;
  const isFirstLoad = recsQ.isLoading && recs.length === 0;

  // Group by district_name
  const districtMap = new Map<string, any>();
  recs.forEach(r => {
    if (!districtMap.has(r.district_name)) {
      districtMap.set(r.district_name, {
        name: r.district_name,
        predicted: 0,
        recommended: 0,
        safetyStock: 0,
        commodities: {},
        rows: []
      });
    }
    const d = districtMap.get(r.district_name);
    d.predicted    += r.forecast_next_month;
    d.recommended  += r.recommended_allotment;
    d.safetyStock  += r.safety_stock;
    d.commodities[r.item_name] = (d.commodities[r.item_name] || 0) + r.forecast_next_month;
    d.rows.push(r);
  });

  const distData = Array.from(districtMap.values()).map(d => ({
    ...d,
    gap: d.recommended - d.predicted,
    // Safety stock is always positive; flag only if it's unusually high (>25%) or low (<8%)
    status: (d.safetyStock / Math.max(d.predicted, 1)) > 0.25
      ? "HIGH BUFFER"
      : (d.safetyStock / Math.max(d.predicted, 1)) < 0.08
        ? "LOW BUFFER"
        : "ON TRACK",
  }));

  // Aggregated totals
  const totalPredicted  = distData.reduce((sum, d) => sum + d.predicted, 0);
  const totalRecommended = distData.reduce((sum, d) => sum + d.recommended, 0);
  const totalGap        = totalRecommended - totalPredicted;
  const dvMax = Math.max(
    0,
    totalPredicted,
    totalRecommended,
    ...distData.map((d) => Math.max(Number(d.predicted || 0), Number(d.recommended || 0), Number(d.safetyStock || 0))),
  );
  const dvScale = kgScaleFor(dvMax);
  const dvTick = (v: any) => `${(Number(v) / dvScale.div).toFixed(dvScale.div >= 1_000 ? 1 : 0)}${dvScale.unit}`;

  // Commodity split (across all districts)
  const commData = recs.reduce((acc: any, r) => {
    acc[r.item_name] = (acc[r.item_name] || 0) + r.forecast_next_month;
    return acc;
  }, {});
  const piePalette = paletteForLabels(Object.keys(commData));
  const pieData = Object.keys(commData).map((k) => ({
    name: k,
    value: commData[k],
    fill: piePalette[k] ?? colorForLabel(k),
  }));

  const forecastMonthLabel = recs[0]?.forecast_for_month ?? "Next month";

  // Explainable insights (computed from real API outputs)
  const insights: ExplainableInsight[] = [];
  const topDistrict = distData.reduce((a, b) => (a.predicted > b.predicted ? a : b), distData[0]);
  if (topDistrict?.name) {
    insights.push({
      text: `${topDistrict.name} has the highest forecast demand for ${forecastMonthLabel}: ${fmtKg(topDistrict.predicted)} (current scope).`,
      source: "Source: /api/smart-allot/recommendations → recommendations[].forecast_next_month (aggregated by district_name)",
    });
  }
  const topItem = Object.entries(commData as Record<string, number>).reduce((a, b) => (a[1] > b[1] ? a : b), ["", 0] as [string, number]);
  if (topItem[0]) {
    insights.push({
      text: `${topItem[0]} is the top commodity forecast for ${forecastMonthLabel}: ${fmtKg(topItem[1])} (current scope).`,
      source: "Source: /api/smart-allot/recommendations → recommendations[].forecast_next_month (aggregated by item_name)",
    });
  }
  insights.push({
    text: `Total recommended allotment for ${forecastMonthLabel}: ${fmtKg(totalRecommended)}.`,
    source: "Source: /api/smart-allot/recommendations → recommendations[].recommended_allotment (sum)",
  });
  insights.push({
    text: `Filters: District=${tx.district || "All"}, AFSO=${tx.afso || "All"}, FPS=${tx.fps_id || "All"}, Month(as-of)=${tx.month || "All"}, Commodity=${tx.commodity || "All"}.`,
    source: "Source: UI filter state → applied to /api/smart-allot/* and /api/transactions/* calls",
    derived: true,
  });

  // Real monthly actuals from DB transactions + next-month forecast (timeline)
  const monthlyTrend = (monthlyQ.data as any)?.chart_data?.monthly_trend ?? [];
  const actualByMonth: Record<string, number> = {};
  for (const r of monthlyTrend as any[]) {
    actualByMonth[String(r.month)] = (actualByMonth[String(r.month)] || 0) + Number(r.quantity_kgs || 0);
  }
  const monthOrder = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  const timeData = monthOrder
    .filter((m) => actualByMonth[m] != null)
    .map((m) => ({ month: m, Actual: actualByMonth[m], Predicted: null as any }));

  const preds: any[] = (timelineForecastQ.data as any)?.predictions ?? [];
  const nextDate = preds.map((p) => String(p.date || "")).filter(Boolean).sort()[0] ?? "";
  const nextDateTotal = nextDate
    ? preds.filter((p) => String(p.date) === nextDate).reduce((s, p) => s + Number(p.predicted_demand || 0), 0)
    : totalPredicted;

  const monthNames = monthOrder;
  const forecastMonthName = nextDate ? monthNames[Math.max(0, Math.min(11, Number(nextDate.split("-")[1]) - 1))] : String(forecastMonthLabel).split(" ")[0];
  timeData.push({ month: forecastMonthName, Actual: null as any, Predicted: nextDateTotal });

  const timelineMax = Math.max(
    0,
    ...timeData.map((r) => Math.max(Number(r.Actual ?? 0), Number(r.Predicted ?? 0))),
  );
  const yScale = kgScaleFor(timelineMax);
  const yTick = (v: any) => `${(Number(v) / yScale.div).toFixed(yScale.div >= 1_000 ? 1 : 0)}${yScale.unit}`;
  const yDomainMax = Math.max(10, Math.ceil(timelineMax * 1.15));

  const timelineTitle =
    tx.fps_id ? `FPS ${tx.fps_id} Demand Forecast Timeline` :
    tx.afso ? `${tx.afso} Demand Forecast Timeline` :
    tx.district ? `${tx.district} Demand Forecast Timeline` :
    "Statewide Demand Forecast Timeline";

  if (recsQ.isError && recs.length === 0) {
    return <p className="state error">Failed to load recommendations. Is the smart-allot service running?</p>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px", animation: "fadeIn 0.3s ease" }}>
      {/* 1. Top Section: AI Insights & KPI Summaries */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "20px" }}>
        
        {/* AI Insights */}
        <div style={{ background: "var(--insights-gradient)", borderRadius: "20px", padding: "24px", color: "white", boxShadow: "0 10px 30px rgba(30,58,138,0.25)", position: "relative", overflow: "hidden" }}>
          <div style={{ position: "absolute", right: -20, top: -20, opacity: 0.1 }}><Zap size={140} /></div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px", zIndex: 1, position: "relative" }}>
            <Zap size={24} color="var(--insights-accent)" />
            <h3 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700 }}>SARATHI AI Insights</h3>
            {isUpdating && (
              <span style={{ position: "absolute", right: 14, top: 14, fontSize: 12, fontWeight: 900, opacity: 0.95, background: "rgba(255,255,255,0.14)", padding: "6px 10px", borderRadius: 999 }}>
                Updating…
              </span>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "16px", zIndex: 1, position: "relative" }}>
            {insights.map((ins, i) => (
              <div key={i} style={{ background: "var(--insights-surface)", borderRadius: "12px", padding: "16px", lineHeight: 1.45 }}>
                <strong style={{ display: "block", color: "var(--insights-accent)", marginBottom: "4px", fontSize: "0.85rem", letterSpacing: "0.06em" }}>
                  {(i === 0 ? "DEMAND SIGNAL" : i === 1 ? "TOP COMMODITY" : i === 2 ? "ALLOTMENT SUMMARY" : "SCOPE FILTERS")}
                </strong>
                <span style={{ fontWeight: 600, fontSize: "0.95rem" }}>{ins.text}</span>
              </div>
            ))}
          </div>
        </div>

        {/* District Summaries Scroll View */}
        <div style={{ display: "flex", gap: "16px", overflowX: "auto", paddingBottom: "10px" }}>
          {distData.map(d => (
            <div key={d.name} style={{ minWidth: "260px", background: "var(--card-glass)", border: "1px solid var(--line)", borderRadius: "16px", padding: "20px", boxShadow: "0 4px 15px rgba(0,0,0,0.03)", backdropFilter: "blur(12px)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
                <h4 style={{ margin: 0, fontSize: "1.1rem", color: "var(--navy)", fontWeight: 800 }}>{d.name.replace("-District", "")}</h4>
                <Badge text={d.status} color={d.status === "LOW BUFFER" ? "#ef4444" : (d.status === "HIGH BUFFER" ? "#f59e0b" : "#22c55e")} />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "0.9rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ color: "var(--muted)" }}>Forecast (May):</span> <strong style={{ color: "var(--text)" }}>{fmtKg(d.predicted)}</strong></div>
                <div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ color: "var(--muted)" }}>Allotment:</span> <strong style={{ color: "var(--text)" }}>{fmtKg(d.recommended)}</strong></div>
                <div style={{ display: "flex", justifyContent: "space-between", borderTop: "1px dashed var(--line)", paddingTop: "8px", marginTop: "4px" }}>
                  <span style={{ color: "var(--muted)" }}>Safety Buffer:</span>
                  <strong style={{ color: "var(--green)" }}>+{fmtKg(d.safetyStock)}</strong>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 2. Visual Analytics Row 1 */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "24px" }}>
        
        {/* Demand vs Allocation Graph */}
        <div style={{ background: "var(--card-glass)", borderRadius: "16px", padding: "24px", border: "1px solid var(--line)", boxShadow: "0 4px 15px rgba(0,0,0,0.03)", backdropFilter: "blur(12px)" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Demand vs Recommended Allocation</h3>
          <div style={{ height: "300px" }}>
            {isFirstLoad ? <ChartSkeleton height={300} /> : (
            <ResponsiveContainer width="100%" height={300} minWidth={0}>
              <ComposedChart data={distData} margin={{ top: 10, right: 10, left: 10, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tickFormatter={(v) => v.replace("-District", "")} axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                <YAxis tickFormatter={dvTick} axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                <RechartsTooltip formatter={(val: any) => `${val.toLocaleString()} kg`} contentStyle={{ borderRadius: "10px", border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.1)" }} />
                <Legend wrapperStyle={{ paddingTop: "20px" }} />
                <Bar dataKey="predicted" name="Predicted Demand" fill="#94a3b8" radius={[4, 4, 0, 0]} maxBarSize={40} />
                <Line type="monotone" dataKey="recommended" name="Recommended" stroke="#10b981" strokeWidth={4} dot={{ r: 6, fill: "#10b981", strokeWidth: 2, stroke: "#fff" }} />
              </ComposedChart>
            </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Commodity Split Donut */}
        <div style={{ background: "var(--card-glass)", borderRadius: "16px", padding: "24px", border: "1px solid var(--line)", boxShadow: "0 4px 15px rgba(0,0,0,0.03)", display: "flex", flexDirection: "column", backdropFilter: "blur(12px)" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Commodity Split</h3>
          <div style={{ flex: 1, minHeight: "250px" }}>
            {isFirstLoad ? <ChartSkeleton height={250} /> : (
            <ResponsiveContainer width="100%" height={250} minWidth={0}>
                <PieChart>
                   <Pie data={pieData} innerRadius={60} outerRadius={85} paddingAngle={3} dataKey="value">
                   {pieData.map((entry, index) => (
                     <Cell key={`cell-${index}`} fill={(entry as any).fill ?? colorForLabel(entry.name)} />
                   ))}
                   </Pie>
                <RechartsTooltip formatter={(val: any) => `${(val/1000).toFixed(1)}k kg`} contentStyle={{ borderRadius: "10px", border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.1)" }} />
              </PieChart>
            </ResponsiveContainer>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, paddingTop: 10 }}>
            {pieData.map((d: any) => (
              <div key={d.name} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--navy)", fontWeight: 700 }}>
                <span style={{ width: 10, height: 10, borderRadius: "50%", background: d.fill ?? colorForLabel(d.name) }} />
                <span>{d.name}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 3. Visual Analytics Row 2 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "24px" }}>
        
        {/* Gap Visualization */}
        <div style={{ background: "var(--card-glass)", borderRadius: "16px", padding: "24px", border: "1px solid var(--line)", boxShadow: "0 4px 15px rgba(0,0,0,0.03)", backdropFilter: "blur(12px)" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Allocation Gap Analysis</h3>
          <div style={{ height: "300px" }}>
            {isFirstLoad ? <ChartSkeleton height={300} /> : (
            <ResponsiveContainer width="100%" height={300} minWidth={0}>
              <BarChart data={distData} layout="vertical" margin={{ left: 30, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
                <XAxis type="number" tickFormatter={dvTick} axisLine={false} tickLine={false} />
                <YAxis dataKey="name" type="category" tickFormatter={(v) => v.replace("-District", "")} axisLine={false} tickLine={false} />
                <RechartsTooltip formatter={(val: any) => `${val > 0 ? '+' : ''}${val.toLocaleString()} kg`} contentStyle={{ borderRadius: "10px", border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.1)" }} />
                <ReferenceLine x={0} stroke="#000" />
                <Bar dataKey="gap" name="Gap (Recommended - Predicted)">
                  {distData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.gap < 0 ? "#ef4444" : "#10b981"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Interactive Map */}
        <div style={{ background: "var(--card-glass)", borderRadius: "16px", padding: "20px", border: "1px solid var(--line)", boxShadow: "0 4px 15px rgba(0,0,0,0.03)", display: "flex", flexDirection: "column", backdropFilter: "blur(12px)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", gap: 12, flexWrap: "wrap" }}>
            <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.1rem" }}>Geographic Overlay</h3>
            <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
              {/* Map Filters (same style as Command Map) */}
              <select value={tx.year ?? ""} onChange={(e) => setField("year", e.target.value ? Number(e.target.value) : undefined)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", fontWeight: 700, backdropFilter: "blur(8px)" }}>
                <option value="">All Years</option>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
              <select value={tx.district ?? ""} onChange={(e) => setField("district", e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", fontWeight: 700, backdropFilter: "blur(8px)" }}>
                <option value="">All Districts</option>
                {districts.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
              <select value={tx.afso ?? ""} onChange={(e) => setField("afso", e.target.value)} disabled={!tx.district} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: !tx.district ? "var(--control-glass-disabled)" : "var(--control-glass)", fontWeight: 700, backdropFilter: "blur(8px)" }}>
                <option value="">All AFSOs</option>
                {afsos.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              <select value={tx.fps_id ?? ""} onChange={(e) => setField("fps_id", e.target.value)} disabled={!tx.afso} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: !tx.afso ? "var(--control-glass-disabled)" : "var(--control-glass)", fontWeight: 700, backdropFilter: "blur(8px)" }}>
                <option value="">All FPSs</option>
                {fpsIds.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
              <select value={tx.commodity ?? ""} onChange={(e) => setField("commodity", e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", fontWeight: 700, minWidth: 180, backdropFilter: "blur(8px)" }}>
                <option value="">All Items</option>
                {commodities.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={tx.month ?? ""} onChange={(e) => setField("month", e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", fontWeight: 700, backdropFilter: "blur(8px)" }}>
                <option value="">All Months</option>
                {months.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>

              <div style={{ display: "flex", gap: "8px", background: "rgba(239,248,255,0.65)", padding: "4px", borderRadius: "10px", border: "1px solid var(--line)", backdropFilter: "blur(8px)" }}>
                {(["gap", "demand", "allocation"] as const).map(layer => (
                  <button
                    key={layer}
                    onClick={() => setActiveLayer(layer)}
                    style={{ padding: "6px 12px", borderRadius: "8px", border: "none", background: activeLayer === layer ? "rgba(255,255,255,0.86)" : "transparent", color: activeLayer === layer ? "var(--navy)" : "var(--muted)", fontWeight: activeLayer === layer ? 800 : 600, fontSize: "0.8rem", cursor: "pointer", boxShadow: activeLayer === layer ? "0 10px 18px rgba(30,134,214,0.10)" : "none" }}
                  >
                    {layer.toUpperCase()}
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", background: "var(--bg)", borderRadius: "8px", padding: "4px", border: "1px solid var(--line)" }}>
                <button onClick={() => setMapType("landscape")} style={{ padding: "4px 12px", border: "none", borderRadius: "6px", background: mapType === "landscape" ? "#fff" : "transparent", boxShadow: mapType === "landscape" ? "0 2px 4px rgba(0,0,0,0.1)" : "none", fontSize: "0.75rem", fontWeight: 600, cursor: "pointer", color: mapType === "landscape" ? "var(--navy)" : "var(--muted)", transition: "all 0.2s" }}>Landscape</button>
                <button onClick={() => setMapType("satellite")} style={{ padding: "4px 12px", border: "none", borderRadius: "6px", background: mapType === "satellite" ? "#fff" : "transparent", boxShadow: mapType === "satellite" ? "0 2px 4px rgba(0,0,0,0.1)" : "none", fontSize: "0.75rem", fontWeight: 600, cursor: "pointer", color: mapType === "satellite" ? "var(--navy)" : "var(--muted)", transition: "all 0.2s" }}>Satellite</button>
              </div>
            </div>
          </div>
          <div style={{ flex: 1, borderRadius: "12px", overflow: "hidden", minHeight: "300px", zIndex: 1, position: "relative" }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}>
              <MapContainer center={[16.5, 80.6]} zoom={6.5} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
                <TileLayer url={MAP_LAYERS[mapType]} attribution="&copy; OpenStreetMap &copy; CARTO" />
              {(markers.length ? markers : distData).map((d: any, _mapIdx: number) => {
                const isTx = d?.lat != null && d?.lng != null;
                const name = isTx ? String(d.label) : String(d.name);
                const coords: [number, number] = isTx
                  ? [Number(d.lat), Number(d.lng)]
                  : (AP_COORDS[name] ?? DEFAULT_COORD);

                let color = "#94a3b8", fillColor = "#cbd5e1", radius = 12;

                if (isTx) {
                  const qty = Number(d.qty_kgs ?? 0);
                  // Use qty to size markers; color based on the active layer theme.
                  radius = Math.max(10, Math.min(22, Math.sqrt(qty) / 8));
                  if (activeLayer === "allocation") { color = "#1d4ed8"; fillColor = "#3b82f6"; }
                  else if (activeLayer === "demand") { color = "#166534"; fillColor = "#22c55e"; }
                  else { color = "#a16207"; fillColor = "#eab308"; }
                } else {
                  if (activeLayer === "gap") {
                    if (d.status === "SHORTAGE") { color = "#991b1b"; fillColor = "#ef4444"; radius = 16; }
                    else if (d.status === "OVERSTOCK") { color = "#a16207"; fillColor = "#eab308"; radius = 14; }
                    else { color = "#166534"; fillColor = "#22c55e"; radius = 12; }
                  } else if (activeLayer === "demand") {
                    if (d.predicted > 500000) { color = "#991b1b"; fillColor = "#ef4444"; radius = 18; }
                    else { color = "#166534"; fillColor = "#22c55e"; radius = 12; }
                  } else if (activeLayer === "allocation") {
                    color = "#1d4ed8"; fillColor = "#3b82f6";
                    radius = Math.max(10, Math.min(24, (d.recommended / 500000) * 10));
                  }
                }

                return (
                  <CircleMarker key={`${name}-${_mapIdx}`} center={coords} radius={radius} color={color} fillColor={fillColor} weight={2} fillOpacity={0.7}>
                    <LeafletTooltip>
                      <div style={{ padding: "4px" }}>
                        <strong>{name}</strong><br/>
                        {isTx ? (
                          <>
                            District: {d.district}<br/>
                            AFSO: {d.afso}<br/>
                            Qty: {Number(d.qty_kgs ?? 0).toLocaleString("en-IN")} kg<br/>
                            FPS count: {Number(d.fps_count ?? 0).toLocaleString("en-IN")}
                          </>
                        ) : (
                          <>
                            Predicted: {d.predicted.toLocaleString()} kg<br/>
                            Recommended: {d.recommended.toLocaleString()} kg<br/>
                            Gap: {d.gap.toLocaleString()} kg
                          </>
                        )}
                      </div>
                    </LeafletTooltip>
                  </CircleMarker>
                );
              })}
              </MapContainer>
            </div>
          </div>
        </div>
      </div>

      {/* 4. Time-Based Forecast */}
      <div style={{ background: "var(--card-glass)", borderRadius: "16px", padding: "24px", border: "1px solid rgba(255,255,255,0.55)", boxShadow: "0 18px 46px rgba(30,134,214,0.10)", backdropFilter: "blur(12px)" }}>
        <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>{timelineTitle}</h3>
        <div style={{ height: "250px" }}>
          {isFirstLoad ? <ChartSkeleton height={250} /> : (
          <ResponsiveContainer width="100%" height={250} minWidth={0}>
            <LineChart data={timeData}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="month" axisLine={false} tickLine={false} />
              <YAxis domain={[0, yDomainMax]} tickFormatter={yTick} axisLine={false} tickLine={false} />
              <RechartsTooltip formatter={(val: any) => `${val.toLocaleString()} kg`} contentStyle={{ borderRadius: "10px", border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.1)" }} />
              <Legend />
              <Line type="monotone" dataKey="Actual" stroke="#1E3A8A" strokeWidth={3} dot={{ r: 4 }} />
              <Line type="monotone" dataKey="Predicted" stroke="#F59E0B" strokeWidth={3} strokeDasharray="5 5" dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* 5. Smart Table — district × commodity breakdown */}
      <div style={{ background: "var(--card-glass)", borderRadius: "16px", padding: "24px", border: "1px solid rgba(255,255,255,0.55)", boxShadow: "0 18px 46px rgba(30,134,214,0.10)", backdropFilter: "blur(12px)" }}>
        <h3 style={{ margin: "0 0 4px 0", color: "var(--navy)", fontSize: "1.1rem" }}>May 2026 Commodity Allocation Detail</h3>
        <p style={{ margin: "0 0 20px 0", color: "var(--muted)", fontSize: "0.8rem" }}>Model: GradientBoosting · Safety buffer: 15%</p>
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {distData.map(d => (
            <div key={d.name} style={{ border: "1px solid var(--line)", borderRadius: "10px", overflow: "hidden" }}>
              <div
                onClick={() => setExpandedDistrict(expandedDistrict === d.name ? null : d.name)}
                style={{ padding: "16px", background: expandedDistrict === d.name ? "rgba(254,255,209,0.58)" : "var(--control-glass)", display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", fontWeight: 800, color: "var(--navy)", backdropFilter: "blur(10px)" }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                  {expandedDistrict === d.name ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                  {d.name}
                </div>
                <div style={{ display: "flex", gap: "24px", fontSize: "0.9rem", color: "var(--text)" }}>
                  <span>Forecast: <strong>{(d.predicted / 1000).toFixed(1)}k kg</strong></span>
                  <span>Allotment: <strong>{(d.recommended / 1000).toFixed(1)}k kg</strong></span>
                  <span>Safety: <strong style={{ color: "var(--green)" }}>+{(d.safetyStock / 1000).toFixed(1)}k kg</strong></span>
                </div>
              </div>

              {expandedDistrict === d.name && (
                <div style={{ borderTop: "1px solid var(--line)" }}>
                  <table className="data-table" style={{ margin: 0, border: "none", borderRadius: 0, boxShadow: "none" }}>
                    <thead style={{ background: "rgba(239,248,255,0.55)" }}>
                      <tr>
                        <th>Commodity</th>
                        <th>May Forecast (kg)</th>
                        <th>Safety Stock (kg)</th>
                        <th>Recommended Allotment (kg)</th>
                        <th>Apr Distributed (kg)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.rows.map((r: any, i: number) => (
                        <tr key={i}>
                          <td><strong>{r.item_name}</strong></td>
                          <td>{Math.round(r.forecast_next_month).toLocaleString()}</td>
                          <td style={{ color: "#059669" }}>{Math.round(r.safety_stock).toLocaleString()}</td>
                          <td><strong>{Math.round(r.recommended_allotment).toLocaleString()}</strong></td>
                          <td style={{ color: "var(--muted)" }}>{Math.round(r.last_month_distributed).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Predict tab ────────────────────────────────────────────────────────────────

function PredictTab({ tx }: { tx: TxFilters }) {
  const [periods, setPeriods] = useState(3);
  const [triggered, setTriggered] = useState(false);

  const predictQ = useQuery({
    queryKey: ["ml-predictions", periods, tx.year, tx.month, tx.district, tx.afso, tx.fps_id, tx.commodity],
    queryFn: () => fetchMLPredictions(periods, tx),
    enabled: triggered,
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <article 
        className="panel" 
        style={{ 
          background: "linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(255, 255, 255, 0.75) 100%)",
          border: "1px solid rgba(255,255,255,0.8)",
          boxShadow: "0 8px 32px rgba(11, 28, 60, 0.05)",
          marginBottom: "16px"
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "20px" }}>
          <div style={{ background: "var(--primary-gradient)", color: "white", width: "32px", height: "32px", borderRadius: "8px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1.2rem", boxShadow: "0 4px 10px rgba(249, 115, 22, 0.3)" }}>📈</div>
          <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.2rem", fontWeight: 800 }}>Forecast Configuration</h3>
        </div>
        
        <div className="filter-grid" style={{ gap: "24px", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
          <label className="field" style={{ gap: "8px" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Future Months</span>
            <select value={periods} onChange={(e) => setPeriods(Number(e.target.value))}>
              {[1, 2, 3, 6, 9, 12].map((n) => <option key={n} value={n}>{n} Months</option>)}
            </select>
          </label>
          <div className="field" style={{ gap: "8px", display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Year (from filters)</span>
            <div style={{ padding: "12px 12px", borderRadius: 12, border: "1px solid var(--line)", background: "#fff", fontWeight: 800, color: "var(--navy)" }}>
              {tx.year ?? "All Years"}
            </div>
          </div>
          <div className="field" style={{ gap: "8px", display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>District (from filters)</span>
            <div style={{ padding: "12px 12px", borderRadius: 12, border: "1px solid var(--line)", background: "#fff", fontWeight: 800, color: "var(--navy)" }}>
              {tx.district || "All Districts"}
            </div>
          </div>
          <div className="field" style={{ gap: "8px", display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>AFSO (from filters)</span>
            <div style={{ padding: "12px 12px", borderRadius: 12, border: "1px solid var(--line)", background: "#fff", fontWeight: 800, color: "var(--navy)" }}>
              {tx.afso || "All AFSOs"}
            </div>
          </div>
          <div className="field" style={{ gap: "8px", display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>FPS (from filters)</span>
            <div style={{ padding: "12px 12px", borderRadius: 12, border: "1px solid var(--line)", background: "#fff", fontWeight: 800, color: "var(--navy)" }}>
              {tx.fps_id || "All FPSs"}
            </div>
          </div>
          <div className="field" style={{ gap: "8px", display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Month (from filters)</span>
            <div style={{ padding: "12px 12px", borderRadius: 12, border: "1px solid var(--line)", background: "#fff", fontWeight: 800, color: "var(--navy)" }}>
              {tx.month || "All Months"}
            </div>
          </div>
          <div className="field" style={{ gap: "8px", display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Commodity (from filters)</span>
            <div style={{ padding: "12px 12px", borderRadius: 12, border: "1px solid var(--line)", background: "#fff", fontWeight: 800, color: "var(--navy)" }}>
              {tx.commodity || "All Commodities"}
            </div>
          </div>
          <label className="field" style={{ justifyContent: "flex-end", gap: "8px" }}>
            <span style={{ fontSize: "0.8rem", opacity: 0 }}>Action</span>
            <button
              className="btn-primary"
              onClick={() => { setTriggered(true); }}
              style={{ 
                marginTop: "auto", 
                height: "48px", 
                display: "flex", 
                alignItems: "center", 
                justifyContent: "center", 
                gap: "8px", 
                borderRadius: "12px",
                width: "100%",
                fontSize: "1rem",
                letterSpacing: "0.02em"
              }}
            >
              <span>Generate Forecast</span>
              <span style={{ fontSize: "1.2rem", filter: "drop-shadow(0 2px 2px rgba(0,0,0,0.1))" }}>✨</span>
            </button>
          </label>
        </div>
      </article>

      {predictQ.isLoading && <p className="state">Running forecast model…</p>}
      {predictQ.isError && <p className="state error">Forecast failed. Ensure models are trained (Data tab → Retrain).</p>}

      {predictQ.data && (
        <>
          <p style={{ color: "#94a3b8", fontSize: 13 }}>
            {predictQ.data.count} predictions · Model: {predictQ.data.predictions[0]?.model_used ?? "—"}
          </p>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Unit</th>
                  <th>District</th>
                  <th>Commodity</th>
                  <th>Date</th>
                  <th>Predicted Demand (kg)</th>
                  <th>Lower Bound</th>
                  <th>Upper Bound</th>
                  <th>Confidence</th>
                  <th>Model</th>
                </tr>
              </thead>
              <tbody>
                {predictQ.data.predictions.map((p, i) => (
                  <tr key={i}>
                    <td style={{ fontSize: 12, color: "#0f172a" }}><strong>{p.location}</strong></td>
                    <td><strong>{p.district}</strong></td>
                    <td>{p.commodity}</td>
                    <td>{p.date}</td>
                    <td><strong>{p.predicted_demand.toLocaleString()}</strong></td>
                    <td style={{ color: "#94a3b8" }}>{p.lower_bound.toLocaleString()}</td>
                    <td style={{ color: "#94a3b8" }}>{p.upper_bound.toLocaleString()}</td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <div style={{ width: 48, height: 6, background: "#1e293b", borderRadius: 3, overflow: "hidden" }}>
                          <div style={{ width: `${p.confidence_score * 100}%`, height: "100%", background: "#3b82f6" }} />
                        </div>
                        <span style={{ fontSize: 12 }}>{fmt(p.confidence_score * 100)}%</span>
                      </div>
                    </td>
                    <td><Badge text={p.model_used} color={p.model_used === "Prophet" ? "#7c3aed" : "#1e40af"} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ── Allocate tab ───────────────────────────────────────────────────────────────

function AllocateTab({ tx }: { tx: TxFilters }) {
  const [periods, setPeriods] = useState(3);
  const [triggered, setTriggered] = useState(false);

  const allocQ = useQuery({
    queryKey: ["ml-allocation", periods, tx.year, tx.month, tx.district, tx.afso, tx.fps_id, tx.commodity],
    queryFn: () => fetchMLAllocation(periods, undefined, tx),
    enabled: triggered,
  });

  const sum = allocQ.data?.summary;
  const filteredAllocations = useMemo(() => {
    const rows = allocQ.data?.allocations ?? [];
    return rows.filter((a) => {
      if (tx.district && a.district !== tx.district) return false;
      if (tx.afso && a.mandal !== tx.afso) return false;
      if (tx.fps_id && String(a.fps_id) !== String(tx.fps_id)) return false;
      if (tx.commodity && a.commodity !== tx.commodity) return false;
      return true;
    });
  }, [allocQ.data, tx.afso, tx.commodity, tx.district, tx.fps_id]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <article className="panel bot-panel">
        <div className="filter-grid">
          <label className="field">
            <span>Future Months</span>
            <select value={periods} onChange={(e) => setPeriods(Number(e.target.value))}>
              {[1, 2, 3, 6].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="field" style={{ justifyContent: "flex-end" }}>
            <span>&nbsp;</span>
            <button className="btn-primary" onClick={() => setTriggered(true)} style={{ marginTop: "auto" }}>
              Run LP Optimization
            </button>
          </label>
        </div>
      </article>

      {allocQ.isLoading && <p className="state">Running LP allocation solver…</p>}
      {allocQ.isError && <p className="state error">Allocation failed. Ensure models are trained.</p>}

      {sum && (
        <div className="stats-grid">
          <article className="stat-card">
            <span className="accent blue" />
            <p className="stat-label">Total Predicted Demand</p>
            <h3>{sum.total_predicted_demand.toLocaleString()} kg</h3>
          </article>
          <article className="stat-card">
            <span className="accent green" />
            <p className="stat-label">Total Recommended</p>
            <h3>{sum.total_recommended_allocation.toLocaleString()} kg</h3>
          </article>
          <article className="stat-card">
            <span className="accent red" />
            <p className="stat-label">Avg Shortage Risk</p>
            <h3>{fmt(sum.avg_shortage_risk_pct)}%</h3>
          </article>
          <article className="stat-card">
            <span className="accent amber" />
            <p className="stat-label">Avg Overstock Risk</p>
            <h3>{fmt(sum.avg_overstock_risk_pct)}%</h3>
          </article>
        </div>
      )}

      {allocQ.data && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>District</th>
                <th>FPS</th>
                <th>Commodity</th>
                <th>Date</th>
                <th>Predicted (kg)</th>
                <th>Recommended (kg)</th>
                <th>Shortage Risk</th>
                <th>Overstock Risk</th>
                <th>Method</th>
              </tr>
            </thead>
            <tbody>
              {filteredAllocations.map((a, i) => (
                <tr key={i}>
                  <td><strong>{a.district}</strong><span className="subtle-line">{a.mandal}</span></td>
                  <td style={{ fontSize: 12 }}>{a.fps_id}</td>
                  <td>{a.commodity}</td>
                  <td>{a.date}</td>
                  <td>{a.predicted_demand.toLocaleString()}</td>
                  <td><strong>{a.recommended_allocation.toLocaleString()}</strong></td>
                  <td>
                    <span style={{ color: a.shortage_risk_pct > 10 ? "#ef4444" : "#94a3b8" }}>
                      {fmt(a.shortage_risk_pct)}%
                    </span>
                  </td>
                  <td>
                    <span style={{ color: a.overstock_risk_pct > 20 ? "#f97316" : "#94a3b8" }}>
                      {fmt(a.overstock_risk_pct)}%
                    </span>
                  </td>
                  <td><Badge text={a.allocation_method.toUpperCase()} color="#0f172a" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Anomalies tab ──────────────────────────────────────────────────────────────

function AnomaliesTab({ tx }: { tx: TxFilters }) {
  const [severity, setSeverity] = useState("");

  const anomalyQ = useQuery({
    queryKey: ["tx-anomalies-smartallot", tx.year, tx.month, tx.district, tx.afso, tx.fps_id, tx.commodity],
    queryFn: () => fetchTxAnomalies({
      year: tx.year,
      month: tx.month,
      district: tx.district,
      afso: tx.afso,
      fps_id: tx.fps_id,
      commodity: tx.commodity,
      threshold_std: 2.0,
      limit: 2000,
    }),
  });

  const d = anomalyQ.data as any;
  const rows = (d?.anomalies ?? []) as any[];
  const filtered = severity ? rows.filter((r) => String(r.severity).toUpperCase() === severity) : rows;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <article className="panel bot-panel">
        <div className="filter-grid">
          <label className="field">
            <span>Severity Filter</span>
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="">All Severities</option>
              <option value="CRITICAL">CRITICAL</option>
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
            </select>
          </label>
        </div>
      </article>

      {anomalyQ.isLoading && <p className="state">Scanning for anomalies…</p>}
      {anomalyQ.isError && <p className="state error">Anomaly detection failed. Is the SMARTAllot service running?</p>}

      {d && (
        <>
          <div className="stats-grid">
            <article className="stat-card">
              <span className="accent blue" />
              <p className="stat-label">Records Scanned</p>
              <h3>{Number(d.records_scanned ?? 0).toLocaleString("en-IN")}</h3>
            </article>
            <article className="stat-card">
              <span className="accent red" />
              <p className="stat-label">Anomalies Found</p>
              <h3>{Number(d.total ?? 0).toLocaleString("en-IN")}</h3>
            </article>
            <article className="stat-card">
              <span className="accent amber" />
              <p className="stat-label">Anomaly Rate</p>
              <h3>{fmt(d.anomaly_rate_pct)}%</h3>
            </article>
            <article className="stat-card">
              <span className="accent red" />
              <p className="stat-label">Critical / High</p>
              <h3>{(d.severity_breakdown?.CRITICAL ?? 0) + (d.severity_breakdown?.HIGH ?? 0)}</h3>
            </article>
          </div>

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Commodity</th>
                  <th>District</th>
                  <th>AFSO</th>
                  <th>FPS</th>
                  <th>Month</th>
                  <th>Qty (kg)</th>
                  <th>Cards</th>
                  <th>Type</th>
                  <th>Severity</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a, i) => (
                  <tr key={i}>
                    <td>{a.commodity}</td>
                    <td><strong>{a.district}</strong></td>
                    <td style={{ fontSize: 12 }}>{a.afso}</td>
                    <td style={{ fontSize: 12 }}>{a.fps_id}</td>
                    <td>{a.month} {a.year}</td>
                    <td><strong>{Number(a.quantity_kgs).toLocaleString("en-IN")}</strong></td>
                    <td>{Number(a.cards).toLocaleString("en-IN")}</td>
                    <td>{a.anomaly_type}</td>
                    <td>
                      <Badge text={a.severity} color={SEVERITY_COLOR[a.severity] ?? "#64748b"} />
                    </td>
                    <td style={{ fontSize: 11, color: "#94a3b8", maxWidth: 260 }}>
                      {a.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ── Data tab ───────────────────────────────────────────────────────────────────

function DataTab() {
  const qc = useQueryClient();
  const statusQ = useQuery({ queryKey: ["ml-model-status"], queryFn: fetchMLModelStatus });
  const s = statusQ.data;
  const txFiltersQ = useQuery({ queryKey: ["tx-filters"], queryFn: fetchTransactionFilters });
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [retrainStatus, setRetrainStatus] = useState<string | null>(null);
  const [reloadStatus, setReloadStatus] = useState<string | null>(null);
  const [dbModelStatus, setDbModelStatus] = useState<string | null>(null);
  const [dbPlots, setDbPlots] = useState<string[]>([]);

  const reloadMut = useMutation({
    mutationFn: () => reloadTransactions(),
    onSuccess: (data) => {
      setReloadStatus(`Reloaded DB: ${data.transaction_rows.toLocaleString("en-IN")} transaction rows`);
      void qc.invalidateQueries(); // refresh all dashboards/maps
    },
    onError: () => setReloadStatus("Reload failed."),
  });

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadMLDataset(file),
    onSuccess: (data) => {
      setUploadStatus(`Uploaded & preprocessed: ${data.rows?.toLocaleString()} rows`);
      void qc.invalidateQueries({ queryKey: ["ml-dataset-info"] });
      void qc.invalidateQueries({ queryKey: ["ml-model-status"] });
    },
    onError: () => setUploadStatus("Upload failed. Check file format."),
  });

  const retrainMut = useMutation({
    mutationFn: () => triggerMLRetrain(3),
    onSuccess: (data) => {
      const m = data.metrics ?? {};
      setRetrainStatus(
        `Retrained in ${data.training_duration_seconds}s · MAE ${fmt(m.mae)} · WAPE ${fmt(m.wape_pct)}%`
      );
      void qc.invalidateQueries({ queryKey: ["ml-model-status"] });
      void qc.invalidateQueries({ queryKey: ["ml-predictions"] });
    },
    onError: () => setRetrainStatus("Retrain failed."),
  });

  const trainDbModelMut = useMutation({
    mutationFn: () => trainDbDemandModel(),
    onSuccess: (data) => {
      setDbModelStatus(`DB demand model trained at ${data.trained_at}`);
      setDbPlots(data.plots ?? []);
      void qc.invalidateQueries({ queryKey: ["ml-model-status"] });
      void qc.invalidateQueries({ queryKey: ["ml-predictions"] });
    },
    onError: (e: any) => setDbModelStatus(`DB model training failed: ${String(e?.message ?? e)}`),
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <article className="panel" style={{ border: "1px solid var(--line)" }}>
        <h3 style={{ marginBottom: 8 }}>Database Dataset (Production Source)</h3>
        <p style={{ color: "#94a3b8", fontSize: 13, marginBottom: 12 }}>
          SMARTAllot dashboards use the shared DB seeded from <code>dataset/clean_transactions.csv</code>. Use reload when you update the CSV.
        </p>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn-primary" onClick={() => reloadMut.mutate()} disabled={reloadMut.isPending}>
            {reloadMut.isPending ? "Reloading…" : "Reload Dataset Into DB"}
          </button>
          {reloadStatus && <span style={{ fontSize: 13, color: reloadMut.isError ? "#ef4444" : "#22c55e" }}>{reloadStatus}</span>}
          <span style={{ fontSize: 12, color: "#94a3b8" }}>
            Districts: {((txFiltersQ.data as any)?.filters?.districts?.length ?? 0)} ·
            Commodities: {((txFiltersQ.data as any)?.filters?.commodities?.length ?? 0)} ·
            Months: {((txFiltersQ.data as any)?.filters?.months?.length ?? 0)}
          </span>
        </div>
      </article>

      {/* Train DB Demand Model */}
      <article className="panel">
        <h3 style={{ marginBottom: 8 }}>Train DB Demand Model (Evidence Pack)</h3>
        <p style={{ color: "#94a3b8", fontSize: 13, marginBottom: 12 }}>
          Trains an open-source ML forecaster on <code>dataset/clean_transactions.csv</code> and generates model evidence:
          training curve, residuals, learning curve, feature importance, confusion matrix, ROC and PR curves.
        </p>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn-primary" onClick={() => trainDbModelMut.mutate()} disabled={trainDbModelMut.isPending}>
            {trainDbModelMut.isPending ? "Training DB Modelâ€¦" : "Train DB Demand Model"}
          </button>
          {dbModelStatus && (
            <span style={{ fontSize: 13, color: trainDbModelMut.isError ? "#ef4444" : "#22c55e" }}>
              {dbModelStatus}
            </span>
          )}
          {(s as any)?.db_demand_model_available && (
            <span style={{ fontSize: 12, color: "#94a3b8" }}>
              Current model: {(s as any)?.db_demand_model_metrics?.regression?.test_mae != null
                ? `Test MAE ${(s as any)?.db_demand_model_metrics?.regression?.test_mae?.toFixed?.(1)} kg`
                : "trained"}
            </span>
          )}
        </div>

        {(dbPlots.length > 0 || (((s as any)?.db_demand_model_metrics?.plots?.length ?? 0) > 0)) && (
          <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 14 }}>
            {((dbPlots.length ? dbPlots : (((s as any)?.db_demand_model_metrics?.plots ?? []) as string[])) as string[]).map((p) => (
              <div
                key={p}
                style={{
                  background: "rgba(255,255,255,0.45)",
                  border: "1px solid rgba(255,255,255,0.55)",
                  borderRadius: 14,
                  padding: 12,
                  backdropFilter: "blur(12px)",
                  boxShadow: "0 12px 30px rgba(30,134,214,0.10)",
                }}
              >
                <div style={{ fontWeight: 900, color: "var(--navy)", fontSize: 12, letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 8 }}>
                  {p.replace(/_/g, " ").replace(/\\.png$/i, "")}
                </div>
                <img
                  src={getDbDemandPlotUrl(p)}
                  alt={p}
                  style={{
                    width: "100%",
                    height: 220,
                    objectFit: "contain",
                    borderRadius: 10,
                    background: "rgba(254,255,209,0.45)",
                    border: "1px solid rgba(15,23,42,0.08)",
                  }}
                />
              </div>
            ))}
          </div>
        )}
      </article>

      {/* Upload */}
      <article className="panel">
        <h3 style={{ marginBottom: 8 }}>Upload Dataset</h3>
        <p style={{ color: "#94a3b8", fontSize: 13, marginBottom: 16 }}>
          Accepts CSV or Excel with columns: date, district, mandal, fps_id, commodity,
          beneficiary_count, demand_kg, stock_allocated_kg.
        </p>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) uploadMut.mutate(f);
            }}
          />
          <button
            className="btn-primary"
            onClick={() => fileRef.current?.click()}
            disabled={uploadMut.isPending}
          >
            {uploadMut.isPending ? "Uploading…" : "Choose File & Upload"}
          </button>
          {uploadStatus && (
            <span style={{ fontSize: 13, color: uploadMut.isError ? "#ef4444" : "#22c55e" }}>
              {uploadStatus}
            </span>
          )}
        </div>
      </article>

      {/* Retrain */}
      <article className="panel">
        <h3 style={{ marginBottom: 8 }}>Retrain Models</h3>
        <p style={{ color: "#94a3b8", fontSize: 13, marginBottom: 16 }}>
          Runs full pipeline: data preprocessing → Ridge baseline training →
          anomaly detector → evaluation report. Takes ~10–30 seconds.
        </p>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <button
            className="btn-primary"
            onClick={() => retrainMut.mutate()}
            disabled={retrainMut.isPending}
            style={{ background: "#7c3aed" }}
          >
            {retrainMut.isPending ? "Training…" : "Retrain Now"}
          </button>
          {retrainStatus && (
            <span style={{ fontSize: 13, color: retrainMut.isError ? "#ef4444" : "#22c55e" }}>
              {retrainStatus}
            </span>
          )}
        </div>
      </article>

      {/* Metrics table */}
      {s?.overall_metrics && Object.keys(s.overall_metrics).length > 0 && (
        <article className="panel">
          <h3 style={{ marginBottom: 12 }}>Evaluation Metrics (Test Set)</h3>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Value</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["MAE", fmt(s.overall_metrics.mae), "Mean Absolute Error (kg)"],
                  ["RMSE", fmt(s.overall_metrics.rmse), "Root Mean Squared Error (kg)"],
                  ["MAPE", `${fmt(s.overall_metrics.mape_pct)}%`, "Mean Absolute Percentage Error"],
                  ["WAPE", `${fmt(s.overall_metrics.wape_pct)}%`, "Weighted Absolute Percentage Error"],
                  ["R²", fmt(s.overall_metrics.r2, 4), "Coefficient of determination"],
                  ["Bias", fmt(s.overall_metrics.bias), "Systematic over/under prediction"],
                  ["Test rows", String(s.overall_metrics.n ?? "—"), "Records evaluated"],
                ].map(([m, v, desc]) => (
                  <tr key={m}>
                    <td><strong>{m}</strong></td>
                    <td>{v}</td>
                    <td style={{ color: "#94a3b8", fontSize: 13 }}>{desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      )}

      {/* Pipeline steps */}
      <article className="panel">
        <h3 style={{ marginBottom: 12 }}>Pipeline Steps</h3>
        {[
          ["1", "Data Preprocessing", "Missing value imputation, outlier clipping, feature engineering (lag, rolling, seasonal)"],
          ["2", "Ridge Regression", "Baseline model trained on 16 engineered features at FPS × commodity granularity"],
          ["3", "Anomaly Detector", "Isolation Forest + Z-score + IQR + spike detection on full dataset"],
          ["4", "Evaluation Report", "MAE, RMSE, WAPE, R² on held-out test set with per-district breakdown"],
          ["5", "LP Optimization", "SciPy HiGHS solver minimizes shortage + overstock given supply constraints"],
        ].map(([num, title, desc]) => (
          <div
            key={num}
            style={{
              display: "flex",
              gap: 16,
              padding: "12px 0",
              borderBottom: "1px solid #1e293b",
            }}
          >
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: "50%",
                background: "#3b82f6",
                color: "#fff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 12,
                fontWeight: 700,
                flexShrink: 0,
              }}
            >
              {num}
            </div>
            <div>
              <p style={{ fontWeight: 600, marginBottom: 2 }}>{title}</p>
              <p style={{ fontSize: 12, color: "#94a3b8" }}>{desc}</p>
            </div>
          </div>
        ))}
      </article>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function SmartAllotPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [tx, setTx] = useState<TxFilters>({});
  const [searchParams] = useSearchParams();
  const appliedUrlRef = useRef(false);

  // Allow deep-linking into scoped views, e.g. /smart-allot?district=Annamayya&afso=B%20Kothakota&fps_id=1005001
  useEffect(() => {
    if (appliedUrlRef.current) return;
    appliedUrlRef.current = true;

    const next: TxFilters = {};
    const year = searchParams.get("year");
    const district = searchParams.get("district");
    const afso = searchParams.get("afso");
    const fps_id = searchParams.get("fps_id");
    const month = searchParams.get("month");
    const commodity = searchParams.get("commodity");

    if (year && !Number.isNaN(Number(year))) next.year = Number(year);
    if (district) next.district = district;
    if (afso) next.afso = afso;
    if (fps_id) next.fps_id = fps_id;
    if (month) next.month = month;
    if (commodity) next.commodity = commodity;

    if (Object.keys(next).length) setTx(next);
  }, [searchParams]);
  const txFiltersQ = useQuery({ queryKey: ["tx-filters"], queryFn: fetchTransactionFilters });
  const meta = (txFiltersQ.data as any)?.filters ?? {};
  const years: number[] = meta.years ?? [];
  const districts: string[] = meta.districts ?? [];
  const months: string[] = meta.months ?? [];
  const commodities: string[] = meta.commodities ?? [];
  const afsos: string[] = tx.district ? (meta.afsos_by_district?.[tx.district] ?? []) : [];
  const fpsIds: string[] = tx.afso ? (meta.fps_by_afso?.[tx.afso] ?? []) : [];

  const setField = (k: keyof TxFilters, v: any) => {
    startTransition(() => {
      setTx((cur) => {
        const next = { ...cur, [k]: v || undefined };
        if (k === "district") {
          next.afso = undefined;
          next.fps_id = undefined;
        }
        if (k === "afso") {
          next.fps_id = undefined;
        }
        return next;
      });
    });
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview",  label: "Model Overview" },
    { id: "predict",   label: "Demand Forecast" },
    { id: "allocate",  label: "Allocation Plan" },
    { id: "anomalies", label: "Anomaly Detection" },
    { id: "data",      label: "Data & Retrain" },
  ];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">SMARTAllot</p>
          <h2>AI-powered demand forecasting and optimized stock allocation</h2>
        </div>
      </header>

      {/* Global Filters (DB-backed) */}
      <div style={{
        background: "#fff",
        border: "1px solid var(--line)",
        borderRadius: 16,
        padding: "14px 16px",
        boxShadow: "var(--shadow-soft)",
        marginBottom: 16,
        display: "flex",
        gap: 12,
        flexWrap: "wrap",
        alignItems: "flex-end",
      }}>
        <div style={{ fontWeight: 800, color: "var(--navy)", marginRight: 8 }}>Filters</div>
        <label className="field" style={{ minWidth: 120 }}>
          <span>Year</span>
          <select value={tx.year ?? ""} onChange={(e) => setField("year", e.target.value ? Number(e.target.value) : undefined)}>
            <option value="">All Years</option>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
        <label className="field" style={{ minWidth: 180 }}>
          <span>District</span>
          <select value={tx.district ?? ""} onChange={(e) => setField("district", e.target.value)}>
            <option value="">All Districts</option>
            {districts.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label className="field" style={{ minWidth: 180 }}>
          <span>AFSO</span>
          <select value={tx.afso ?? ""} onChange={(e) => setField("afso", e.target.value)} disabled={!tx.district}>
            <option value="">All AFSOs</option>
            {afsos.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="field" style={{ minWidth: 160 }}>
          <span>FPS</span>
          <select value={tx.fps_id ?? ""} onChange={(e) => setField("fps_id", e.target.value)} disabled={!tx.afso}>
            <option value="">All FPSs</option>
            {fpsIds.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        <label className="field" style={{ minWidth: 160 }}>
          <span>Month</span>
          <select value={tx.month ?? ""} onChange={(e) => setField("month", e.target.value)}>
            <option value="">All Months</option>
            {months.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        <label className="field" style={{ minWidth: 220 }}>
          <span>Commodity</span>
          <select value={tx.commodity ?? ""} onChange={(e) => setField("commodity", e.target.value)}>
            <option value="">All Commodities</option>
            {commodities.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>

      {/* Tab bar */}
      <nav className="cc-tabs" style={{ marginBottom: 24 }}>
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`cc-tab ${tab === id ? "active" : ""}`}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "overview"  && <OverviewTab tx={tx} meta={meta} setField={setField} />}
      {tab === "predict"   && <PredictTab tx={tx} />}
      {tab === "allocate"  && <AllocateTab tx={tx} />}
      {tab === "anomalies" && <AnomaliesTab tx={tx} />}
      {tab === "data"      && <DataTab />}
    </section>
  );
}
