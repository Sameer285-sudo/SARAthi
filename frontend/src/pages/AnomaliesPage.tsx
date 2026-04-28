import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchTransactionFilters,
  fetchTxAnomalies,
  fetchTxMapData,
} from "../api";
import { MapContainer, TileLayer, CircleMarker, Tooltip } from "react-leaflet";
import {
  PieChart, Pie, Cell, ResponsiveContainer,
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  BarChart, Bar, Legend
} from "recharts";
import { 
  AlertTriangle, Activity, TrendingUp, ShieldAlert,
  Search, CheckCircle, Bell, MapPin
} from "lucide-react";
import { SarathiInsightsCard } from "../components/SarathiInsightsCard";
import type { TxAnomalyRecord, MapMarker } from "../api";

const DEFAULT_COORD: [number, number] = [14.0, 79.0];

const SEV_COLOR: Record<string, string> = {
  CRITICAL: "#ef4444",
  HIGH:     "#f97316",
  MEDIUM:   "#eab308",
  LOW:      "#22c55e",
};

// --- Sub-components ---

function KPICard({ title, value, icon: Icon, color, percentChange }: any) {
  const isPositive = percentChange > 0;
  return (
    <div style={{ background: "var(--card-glass)", borderRadius: "16px", padding: "20px", display: "flex", alignItems: "center", gap: "16px", boxShadow: "0 18px 46px rgba(30,134,214,0.10)", position: "relative", overflow: "hidden", border: "1px solid rgba(255,255,255,0.55)", backdropFilter: "blur(12px)" }}>
      <div style={{ position: "absolute", top: 0, left: 0, bottom: 0, width: "4px", background: color }} />
      <div style={{ width: "48px", height: "48px", borderRadius: "12px", background: `${color}15`, color, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Icon size={24} />
      </div>
      <div style={{ flex: 1 }}>
        <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)", fontWeight: 600 }}>{title}</p>
        <h3 style={{ margin: "4px 0 0 0", fontSize: "1.75rem", color: "var(--navy)", fontWeight: 800 }}>{value}</h3>
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
        <span style={{ fontSize: "0.8rem", fontWeight: 700, color: isPositive ? "#ef4444" : "#22c55e", display: "flex", alignItems: "center", gap: "4px", background: isPositive ? "#fef2f2" : "#f0fdf4", padding: "4px 8px", borderRadius: "8px" }}>
          {isPositive ? "+" : "-"} {Math.abs(percentChange)}%
        </span>
        <span style={{ fontSize: "0.7rem", color: "var(--muted)", marginTop: "4px" }}>vs yesterday</span>
      </div>
    </div>
  );
}

function SevBadge({ sev }: { sev: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", padding: "4px 10px", borderRadius: "6px", fontSize: "0.75rem", fontWeight: 700, background: `${SEV_COLOR[sev] ?? "#94a3b8"}20`, color: SEV_COLOR[sev] ?? "#64748b" }}>
      <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: SEV_COLOR[sev] ?? "#64748b" }} />
      {sev}
    </span>
  );
}

// --- Main Page Component ---

const MAP_LAYERS = {
  landscape: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
  satellite: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
};

export function AnomaliesPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [sevFilter, setSevFilter] = useState("ALL");
  const [mapType, setMapType] = useState<"landscape" | "satellite">("landscape");
  const [mapLevel, setMapLevel] = useState<"district" | "afso" | "fps">("district");
  const [year, setYear] = useState<number | "">("");
  const [district, setDistrict] = useState("");
  const [afso, setAfso] = useState("");
  const [fpsId, setFpsId] = useState("");
  const [month, setMonth] = useState("");
  const [commodity, setCommodity] = useState("");
  const [selectedAnomaly, setSelectedAnomaly] = useState<TxAnomalyRecord | null>(null);

  // Data Fetching
  const filtersQ = useQuery({
    queryKey: ["tx-filters"],
    queryFn: () => fetchTransactionFilters().catch(() => ({ filters: { districts: [], months: [], commodities: [] } } as any)),
  });

  const anomQ = useQuery({
    queryKey: ["tx-anomalies", year, district, afso, fpsId, month, commodity],
    queryFn: () => fetchTxAnomalies({
      year: typeof year === "number" ? year : undefined,
      district: district || undefined,
      afso: afso || undefined,
      fps_id: fpsId || undefined,
      month: month || undefined,
      commodity: commodity || undefined,
      threshold_std: 2.0,
      limit: 2000,
    }).catch(() => ({ anomalies: [] } as any)),
  });

  const mapQ = useQuery({
    queryKey: ["tx-map", mapLevel, year, district, afso, fpsId, month, commodity],
    queryFn: () => fetchTxMapData(mapLevel, {
      year: typeof year === "number" ? year : undefined,
      district: district || undefined,
      afso: afso || undefined,
      fps_id: fpsId || undefined,
      month: month || undefined,
      commodity: commodity || undefined,
    }).catch(() => ({ markers: [] } as any)),
  });

  const anomalies: TxAnomalyRecord[] = (anomQ.data as any)?.anomalies ?? [];
  const markers: MapMarker[] = (mapQ.data as any)?.markers ?? [];

  const stats = useMemo(() => {
    const sev = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 } as Record<string, number>;
    anomalies.forEach(a => { sev[String(a.severity).toUpperCase()] = (sev[String(a.severity).toUpperCase()] || 0) + 1; });
    return {
      total_anomalies: anomalies.length,
      severity: sev,
    };
  }, [anomalies]);

  // Legacy-shaped "locations" so the existing UI can render counts per district.
  const locations = useMemo(() => {
    const byDistrict: Record<string, { anomaly_count: number; critical_count: number; high_count: number; medium_count: number; low_count: number }> = {};
    anomalies.forEach(a => {
      const d = a.district || "Unknown";
      if (!byDistrict[d]) byDistrict[d] = { anomaly_count: 0, critical_count: 0, high_count: 0, medium_count: 0, low_count: 0 };
      byDistrict[d].anomaly_count += 1;
      const sev = String(a.severity || "").toUpperCase();
      if (sev === "CRITICAL") byDistrict[d].critical_count += 1;
      else if (sev === "HIGH") byDistrict[d].high_count += 1;
      else if (sev === "MEDIUM") byDistrict[d].medium_count += 1;
      else byDistrict[d].low_count += 1;
    });
    return Object.entries(byDistrict).map(([location, v]) => ({
      location,
      total_transactions: 0,
      anomaly_rate_pct: 0,
      ...v,
    }));
  }, [anomalies]);

  // UI "alert feed" derived from current anomalies (since we're using the transaction-backed anomaly endpoint here).
  const alerts = useMemo(() => {
    const now = new Date();
    return anomalies
      .filter(a => ["CRITICAL", "HIGH"].includes(String(a.severity || "").toUpperCase()))
      .slice(0, 50)
      .map(a => ({
        alert_id: `TX-${a.id}`,
        severity: String(a.severity || "LOW").toUpperCase(),
        message: `${a.anomaly_type}: ${a.detail}`,
        location: a.district,
        timestamp: now.toISOString(),
      }));
  }, [anomalies]);

  const mapBuckets = useMemo(() => {
    const bucket: Record<string, { anomaly_count: number; critical_count: number; high_count: number; medium_count: number; low_count: number }> = {};
    const keyOf = (a: TxAnomalyRecord) => {
      if (mapLevel === "afso") return a.afso || "Unknown";
      if (mapLevel === "fps") return a.fps_id || "Unknown";
      return a.district || "Unknown";
    };
    anomalies.forEach(a => {
      const k = keyOf(a);
      if (!bucket[k]) bucket[k] = { anomaly_count: 0, critical_count: 0, high_count: 0, medium_count: 0, low_count: 0 };
      bucket[k].anomaly_count += 1;
      const sev = String(a.severity || "").toUpperCase();
      if (sev === "CRITICAL") bucket[k].critical_count += 1;
      else if (sev === "HIGH") bucket[k].high_count += 1;
      else if (sev === "MEDIUM") bucket[k].medium_count += 1;
      else bucket[k].low_count += 1;
    });

    // De-dupe markers because upstream map-data can include repeated label+lat+lng entries.
    const byKey = new Map<string, any>();
    for (const m of markers) {
      const key = `${m.label}|${m.lat}|${m.lng}`;
      const c = bucket[m.label] ?? { anomaly_count: 0, critical_count: 0, high_count: 0, medium_count: 0, low_count: 0 };
      if (!byKey.has(key)) {
        byKey.set(key, { ...m, ...c });
      } else {
        // Merge counts if duplicates appear
        const cur = byKey.get(key);
        cur.anomaly_count += c.anomaly_count;
        cur.critical_count += c.critical_count;
        cur.high_count += c.high_count;
        cur.medium_count += c.medium_count;
        cur.low_count += c.low_count;
      }
    }

    return Array.from(byKey.values()).filter(m => m.anomaly_count > 0 || mapLevel === "district");
  }, [anomalies, markers, mapLevel]);

  // Filtered Table Data
  const tableData = useMemo(() => {
    return anomalies.filter(a => {
      const hay = [
        a.district, a.afso, a.fps_id, a.month, a.commodity, a.anomaly_type, a.detail,
      ].filter(Boolean).join(" ").toLowerCase();
      const matchSearch = hay.includes(searchTerm.toLowerCase());
      const matchSev = sevFilter === "ALL" || String(a.severity).toUpperCase() === sevFilter;
      return matchSearch && matchSev;
    });
  }, [anomalies, searchTerm, sevFilter]);

  type ExplainableInsight = { text: string; source: string; derived?: boolean };
  const insights: ExplainableInsight[] = useMemo(() => {
    const criticals = anomalies.filter(a => String(a.severity).toUpperCase() === "CRITICAL").length;
    const byDistrict: Record<string, number> = {};
    const byType: Record<string, number> = {};
    anomalies.forEach(a => {
      byDistrict[a.district] = (byDistrict[a.district] || 0) + 1;
      const t = String(a.anomaly_type || "Unknown");
      byType[t] = (byType[t] || 0) + 1;
    });
    const topDistrict = Object.entries(byDistrict).sort((a, b) => b[1] - a[1])[0];
    const topType = Object.entries(byType).sort((a, b) => b[1] - a[1])[0];

    const out: ExplainableInsight[] = [];
    out.push({
      text: topDistrict ? `Highest anomaly concentration: ${topDistrict[0]} (${topDistrict[1]} anomalies in current scope).` : "No anomalies detected in the current scope.",
      source: "Source: /api/transactions/anomalies → anomalies[].district (count)",
    });
    out.push({
      text: topType ? `Most frequent anomaly type: ${topType[0]} (${topType[1]} records).` : "No anomaly types available for the current scope.",
      source: "Source: /api/transactions/anomalies → anomalies[].anomaly_type (count)",
    });
    out.push({
      text: criticals > 0 ? `Urgent: ${criticals} CRITICAL anomalies require immediate review.` : "No CRITICAL anomalies in the current scope.",
      source: "Source: /api/transactions/anomalies → anomalies[].severity (filter=CRITICAL)",
    });
    out.push({
      text: `Filters: District=${district || "All"}, AFSO=${afso || "All"}, FPS=${fpsId || "All"}, Month=${month || "All"}, Commodity=${commodity || "All"}.`,
      source: "Source: UI filter state → applied to /api/transactions/anomalies and /api/transactions/map-data",
      derived: true,
    });
    return out;
  }, [anomalies, commodity, month, district, afso, fpsId]);

  // Transform Data for Donut Chart (Types)
  const pieData = useMemo(() => {
    const types: Record<string, number> = {};
    anomalies.forEach(a => { types[a.anomaly_type || "Unknown"] = (types[a.anomaly_type || "Unknown"] || 0) + 1; });
    return Object.entries(types).map(([name, value]) => ({ name, value }));
  }, [anomalies]);
  const PIE_COLORS = ["#072B57", "#1E86D6", "#49C4FF", "#F6C54C", "#10B981", "#EF4444"];

  // Transform Data for Bar Chart (Severity by Location)
  const barData = useMemo(() => {
    const byDistrict: Record<string, { Critical: number; High: number; Medium: number; Low: number; total: number }> = {};
    anomalies.forEach(a => {
      const d = a.district || "Unknown";
      if (!byDistrict[d]) byDistrict[d] = { Critical: 0, High: 0, Medium: 0, Low: 0, total: 0 };
      const sev = String(a.severity || "").toUpperCase();
      if (sev === "CRITICAL") byDistrict[d].Critical += 1;
      else if (sev === "HIGH") byDistrict[d].High += 1;
      else if (sev === "MEDIUM") byDistrict[d].Medium += 1;
      else byDistrict[d].Low += 1;
      byDistrict[d].total += 1;
    });
    return Object.entries(byDistrict)
      .sort((a, b) => b[1].total - a[1].total)
      .slice(0, 8)
      .map(([name, v]) => ({ name, ...v }));
  }, [anomalies]);

  // Transform Data for Area Chart (Trend)
  const areaData = useMemo(() => {
    const byMonth: Record<string, number> = {};
    anomalies.forEach(a => { byMonth[a.month] = (byMonth[a.month] || 0) + 1; });
    return Object.entries(byMonth).map(([name, count]) => ({ name, Anomalies: count }));
  }, [anomalies]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px", animation: "fadeIn 0.4s ease-out" }}>

      {/* Filters */}
      <div style={{ background: "var(--card-glass)", borderRadius: "16px", padding: "16px 20px", boxShadow: "0 18px 46px rgba(30,134,214,0.10)", border: "1px solid rgba(255,255,255,0.55)", backdropFilter: "blur(12px)", display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ fontWeight: 800, color: "var(--navy)", display: "flex", alignItems: "center", gap: 8 }}>
          <ShieldAlert size={18} /> Transaction Anomalies
        </div>
        <select
          value={year === "" ? "" : String(year)}
          onChange={(e) => setYear(e.target.value ? Number(e.target.value) : "")}
          style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800 }}
        >
          <option value="">All Years</option>
          {(((filtersQ.data as any)?.filters?.years ?? []) as number[]).map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select
          value={district}
          onChange={(e) => { setDistrict(e.target.value); setAfso(""); setFpsId(""); }}
          style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800 }}
        >
          <option value="">All Districts</option>
          {((filtersQ.data as any)?.filters?.districts ?? []).map((d: string) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select
          value={afso}
          onChange={(e) => { setAfso(e.target.value); setFpsId(""); }}
          disabled={!district}
          style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--line)", background: district ? "var(--control-glass)" : "var(--control-glass-disabled)", backdropFilter: "blur(10px)", fontWeight: 800 }}
        >
          <option value="">All AFSOs</option>
          {(((filtersQ.data as any)?.filters?.afsos_by_district?.[district] ?? []) as string[]).map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <select
          value={fpsId}
          onChange={(e) => setFpsId(e.target.value)}
          disabled={!afso}
          style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--line)", background: afso ? "var(--control-glass)" : "var(--control-glass-disabled)", backdropFilter: "blur(10px)", fontWeight: 800 }}
        >
          <option value="">All FPSs</option>
          {(((filtersQ.data as any)?.filters?.fps_by_afso?.[afso] ?? []) as string[]).map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
        <select value={month} onChange={(e) => setMonth(e.target.value)} style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800 }}>
          <option value="">All Months</option>
          {((filtersQ.data as any)?.filters?.months ?? []).map((m: string) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select value={commodity} onChange={(e) => setCommodity(e.target.value)} style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800, minWidth: 220 }}>
          <option value="">All Items</option>
          {((filtersQ.data as any)?.filters?.commodities ?? []).map((c: string) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={sevFilter} onChange={(e) => setSevFilter(e.target.value)} style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800 }}>
          {["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={mapLevel} onChange={(e) => setMapLevel(e.target.value as any)} style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800 }}>
          <option value="district">Map: District</option>
          <option value="afso">Map: AFSO</option>
          <option value="fps">Map: FPS</option>
        </select>
        <div style={{ marginLeft: "auto", color: "var(--muted)", fontWeight: 700, fontSize: "0.85rem" }}>
          Showing {tableData.length.toLocaleString("en-IN")} / {anomalies.length.toLocaleString("en-IN")} anomalies
        </div>
      </div>
      
      {/* 1. KPIs Section */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "20px" }}>
        <KPICard title="Total Anomalies Today" value={stats?.total_anomalies ?? "—"} icon={Activity} color="#1E86D6" percentChange={+12.4} />
        <KPICard title="Critical Alerts" value={locations.reduce((sum, l) => sum + l.critical_count, 0) || "—"} icon={AlertTriangle} color="#ef4444" percentChange={+5.2} />
        <KPICard title="Medium Alerts" value={locations.reduce((sum, l) => sum + l.high_count + l.medium_count, 0) || "—"} icon={ShieldAlert} color="#f97316" percentChange={-2.1} />
        <KPICard title="Low Alerts" value={locations.reduce((sum, l) => sum + l.low_count, 0) || "—"} icon={CheckCircle} color="#22c55e" percentChange={-14.5} />
      </div>

      {/* 2. Map & Insights Row */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "24px" }}>
        <div style={{ display: "flex", flexDirection: "column", background: "var(--card-glass)", borderRadius: "16px", padding: "20px", boxShadow: "0 18px 46px rgba(30,134,214,0.10)", border: "1px solid rgba(255,255,255,0.55)", backdropFilter: "blur(12px)", minHeight: "450px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", gap: 12, flexWrap: "wrap" }}>
            <h3 style={{ margin: 0, fontSize: "1.1rem", color: "var(--navy)" }}>Geographic Distribution</h3>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
              {/* Map Filters */}
              <select value={year === "" ? "" : String(year)} onChange={(e) => setYear(e.target.value ? Number(e.target.value) : "")} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800 }}>
                <option value="">All Years</option>
                {(((filtersQ.data as any)?.filters?.years ?? []) as number[]).map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
              <select value={district} onChange={(e) => { setDistrict(e.target.value); setAfso(""); setFpsId(""); }} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800 }}>
                <option value="">All Districts</option>
                {((filtersQ.data as any)?.filters?.districts ?? []).map((d: string) => <option key={d} value={d}>{d}</option>)}
              </select>
              <select value={afso} onChange={(e) => { setAfso(e.target.value); setFpsId(""); }} disabled={!district} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: district ? "var(--control-glass)" : "var(--control-glass-disabled)", backdropFilter: "blur(10px)", fontWeight: 800 }}>
                <option value="">All AFSOs</option>
                {(((filtersQ.data as any)?.filters?.afsos_by_district?.[district] ?? []) as string[]).map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              <select value={fpsId} onChange={(e) => setFpsId(e.target.value)} disabled={!afso} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: afso ? "var(--control-glass)" : "var(--control-glass-disabled)", backdropFilter: "blur(10px)", fontWeight: 800 }}>
                <option value="">All FPSs</option>
                {(((filtersQ.data as any)?.filters?.fps_by_afso?.[afso] ?? []) as string[]).map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
              <select value={commodity} onChange={(e) => setCommodity(e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800, minWidth: 180 }}>
                <option value="">All Items</option>
                {((filtersQ.data as any)?.filters?.commodities ?? []).map((c: string) => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={month} onChange={(e) => setMonth(e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800 }}>
                <option value="">All Months</option>
                {((filtersQ.data as any)?.filters?.months ?? []).map((m: string) => <option key={m} value={m}>{m}</option>)}
              </select>

              <div style={{ display: "flex", background: "rgba(254,255,209,0.55)", borderRadius: "10px", padding: "4px", border: "1px solid var(--line)", backdropFilter: "blur(10px)" }}>
              <button onClick={() => setMapType("landscape")} style={{ padding: "4px 12px", border: "none", borderRadius: "8px", background: mapType === "landscape" ? "rgba(255,255,255,0.86)" : "transparent", boxShadow: mapType === "landscape" ? "0 10px 18px rgba(30,134,214,0.10)" : "none", fontSize: "0.75rem", fontWeight: 800, cursor: "pointer", color: mapType === "landscape" ? "var(--navy)" : "var(--muted)", transition: "all 0.2s" }}>Landscape</button>
              <button onClick={() => setMapType("satellite")} style={{ padding: "4px 12px", border: "none", borderRadius: "8px", background: mapType === "satellite" ? "rgba(255,255,255,0.86)" : "transparent", boxShadow: mapType === "satellite" ? "0 10px 18px rgba(30,134,214,0.10)" : "none", fontSize: "0.75rem", fontWeight: 800, cursor: "pointer", color: mapType === "satellite" ? "var(--navy)" : "var(--muted)", transition: "all 0.2s" }}>Satellite</button>
              </div>
            </div>
          </div>
          <div style={{ flex: 1, borderRadius: "12px", overflow: "hidden", border: "1px solid var(--line)", position: "relative", minHeight: "350px" }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}>
              <MapContainer center={[16.5, 80.6]} zoom={6} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
                <TileLayer url={MAP_LAYERS[mapType]} attribution="&copy; OpenStreetMap" />
              {mapBuckets.map((loc: any, idx: number) => {
                const coords: [number, number] = [loc.lat, loc.lng];
                const isCritical = loc.critical_count > 0;
                return (
                  <CircleMarker 
                    // Upstream can still produce duplicate label/lat/lng rows in edge cases;
                    // include index to guarantee uniqueness and avoid React key warnings.
                    key={`${mapLevel}-${loc.label}-${loc.lat}-${loc.lng}-${idx}`} 
                    center={coords} 
                    radius={Math.max(8, Math.min(24, loc.anomaly_count * 0.5))} 
                    fillColor={isCritical ? "#ef4444" : "#f97316"} 
                    color={isCritical ? "#991b1b" : "#c2410c"} 
                    weight={2} 
                    opacity={0.8} 
                    fillOpacity={0.5}
                  >
                    <Tooltip>
                      <div style={{ padding: "4px" }}>
                        <strong>{loc.label}</strong><br/>
                        Total Anomalies: {loc.anomaly_count}<br/>
                        Critical: {loc.critical_count}
                      </div>
                    </Tooltip>
                  </CircleMarker>
                );
              })}
              </MapContainer>
            </div>
          </div>
        </div>

        {/* AI Insights & Alerts */}
        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          {/* Insights Panel */}
          <SarathiInsightsCard
            title="SARATHI AI Insights"
            sections={insights.slice(0, 4).map((ins, idx) => ({
              heading: idx === 0 ? "Hotspot" : idx === 1 ? "Top Type" : idx === 2 ? "Critical Watch" : "Scope Filters",
              body: <span style={{ fontWeight: 650 }}>{ins.text}</span>,
            }))}
          />
          
          {/* Alert Feed */}
          <div style={{ background: "#fff", borderRadius: "16px", padding: "20px", boxShadow: "0 4px 20px rgba(0,0,0,0.03)", flex: 1, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
              <Bell size={20} color="var(--red)" />
              <h3 style={{ margin: 0, fontSize: "1.1rem", color: "var(--navy)" }}>Live Alerts</h3>
            </div>
            <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: "12px", maxHeight: "200px" }}>
              {alerts.slice(0, 4).map(al => (
                <div key={al.alert_id} style={{ display: "flex", gap: "12px", padding: "12px", border: "1px solid var(--line)", borderRadius: "10px", background: al.severity === "CRITICAL" ? "#fef2f2" : "#fff" }}>
                  <div style={{ width: "8px", borderRadius: "4px", background: SEV_COLOR[al.severity] }} />
                  <div>
                    <p style={{ margin: "0 0 4px 0", fontSize: "0.85rem", fontWeight: 600, color: "var(--navy)" }}>{al.message}</p>
                    <span style={{ fontSize: "0.7rem", color: "var(--muted)", display: "flex", alignItems: "center", gap: "4px" }}>
                      <MapPin size={10} /> {al.location} • {new Date(al.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 3. Charts Row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "24px" }}>
        
        {/* Trend Area Chart */}
        <div style={{ background: "#fff", borderRadius: "16px", padding: "20px", boxShadow: "0 4px 20px rgba(0,0,0,0.03)", gridColumn: "span 2" }}>
          <h3 style={{ margin: "0 0 16px 0", fontSize: "1.1rem", color: "var(--navy)" }}>Anomaly Trend Analysis</h3>
          <div style={{ height: "250px" }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <AreaChart data={areaData}>
                <defs>
                  <linearGradient id="colorAnom" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                <RechartsTooltip contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }} />
                <Area type="monotone" dataKey="Anomalies" stroke="#ef4444" strokeWidth={3} fillOpacity={1} fill="url(#colorAnom)" activeDot={{ r: 6, strokeWidth: 0 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Breakdown Pie Chart */}
        <div style={{ background: "#fff", borderRadius: "16px", padding: "20px", boxShadow: "0 4px 20px rgba(0,0,0,0.03)" }}>
          <h3 style={{ margin: "0 0 16px 0", fontSize: "1.1rem", color: "var(--navy)" }}>Anomaly Types</h3>
          <div style={{ height: "250px" }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                  {pieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <RechartsTooltip contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }} />
                <Legend verticalAlign="bottom" height={36} iconType="circle" wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* 4. Severity Bar Chart */}
      <div style={{ background: "#fff", borderRadius: "16px", padding: "20px", boxShadow: "0 4px 20px rgba(0,0,0,0.03)" }}>
        <h3 style={{ margin: "0 0 16px 0", fontSize: "1.1rem", color: "var(--navy)" }}>Severity by District</h3>
        <div style={{ height: "250px" }}>
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <BarChart data={barData} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
              <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
              <RechartsTooltip cursor={{ fill: "transparent" }} contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: "12px" }} />
              <Bar dataKey="Critical" stackId="a" fill="#ef4444" radius={[0,0,4,4]} barSize={30} />
              <Bar dataKey="High" stackId="a" fill="#f97316" />
              <Bar dataKey="Medium" stackId="a" fill="#eab308" />
              <Bar dataKey="Low" stackId="a" fill="#22c55e" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 5. Smart Table Section */}
      <div style={{ background: "#fff", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(0,0,0,0.03)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
          <h3 style={{ margin: 0, fontSize: "1.2rem", color: "var(--navy)" }}>Anomaly Log</h3>
          <div style={{ display: "flex", gap: "12px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", background: "var(--bg)", border: "1px solid var(--line)", padding: "8px 12px", borderRadius: "8px" }}>
              <Search size={16} color="var(--muted)" />
              <input type="text" placeholder="Search anomalies..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} style={{ border: "none", background: "transparent", outline: "none", fontSize: "0.9rem" }} />
            </div>
            <select value={sevFilter} onChange={e => setSevFilter(e.target.value)} style={{ background: "var(--bg)", border: "1px solid var(--line)", padding: "8px 12px", borderRadius: "8px", fontSize: "0.9rem", color: "var(--navy)", outline: "none" }}>
              <option value="ALL">All Severities</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </select>
          </div>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--bg-deep)", borderBottom: "1px solid var(--line)", textAlign: "left" }}>
                <th style={{ padding: "16px", fontSize: "0.75rem", fontWeight: 700, color: "var(--navy)", textTransform: "uppercase" }}>ID</th>
                <th style={{ padding: "16px", fontSize: "0.75rem", fontWeight: 700, color: "var(--navy)", textTransform: "uppercase" }}>Location</th>
                <th style={{ padding: "16px", fontSize: "0.75rem", fontWeight: 700, color: "var(--navy)", textTransform: "uppercase" }}>Type</th>
                <th style={{ padding: "16px", fontSize: "0.75rem", fontWeight: 700, color: "var(--navy)", textTransform: "uppercase" }}>Severity</th>
                <th style={{ padding: "16px", fontSize: "0.75rem", fontWeight: 700, color: "var(--navy)", textTransform: "uppercase" }}>Time</th>
                <th style={{ padding: "16px", fontSize: "0.75rem", fontWeight: 700, color: "var(--navy)", textTransform: "uppercase" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {tableData.slice(0, 15).map(row => (
                <tr
                  key={`${row.id}-${row.fps_id}-${row.commodity}`}
                  onClick={() => setSelectedAnomaly(row)}
                  style={{ borderBottom: "1px solid var(--line)", cursor: "pointer", transition: "background 0.2s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--bg)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                >
                  <td style={{ padding: "16px", fontSize: "0.85rem", color: "var(--muted)", fontFamily: "monospace" }}>{String(row.id)}</td>
                  <td style={{ padding: "16px", fontSize: "0.9rem", color: "var(--navy)", fontWeight: 500 }}>
                    {row.district} / {row.afso} / FPS {row.fps_id}
                  </td>
                  <td style={{ padding: "16px", fontSize: "0.9rem", color: "var(--text)" }}>{row.anomaly_type}</td>
                  <td style={{ padding: "16px" }}><SevBadge sev={row.severity} /></td>
                  <td style={{ padding: "16px", fontSize: "0.85rem", color: "var(--muted)" }}>{row.month} {row.year}</td>
                  <td style={{ padding: "16px" }}>
                    <span style={{ fontSize: "0.75rem", padding: "4px 8px", borderRadius: "12px", background: "#fef2f2", color: "#ef4444", fontWeight: 600 }}>
                      Pending
                    </span>
                  </td>
                </tr>
              ))}
              {tableData.length === 0 && (
                <tr><td colSpan={6} style={{ padding: "40px", textAlign: "center", color: "var(--muted)" }}>No anomalies found matching criteria.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Slide-out Detail Panel */}
      <div style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: "400px", background: "#fff", boxShadow: "-5px 0 30px rgba(0,0,0,0.1)", transform: selectedAnomaly ? "translateX(0)" : "translateX(100%)", transition: "transform 0.3s cubic-bezier(0.16, 1, 0.3, 1)", zIndex: 1000, display: "flex", flexDirection: "column" }}>
        {selectedAnomaly && (
          <>
            <div style={{ padding: "24px", borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "flex-start", background: "var(--bg-deep)" }}>
              <div>
                <SevBadge sev={selectedAnomaly.severity} />
                <h2 style={{ margin: "12px 0 4px 0", fontSize: "1.4rem", color: "var(--navy)" }}>{selectedAnomaly.anomaly_type}</h2>
                <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)", fontFamily: "monospace" }}>ID: {selectedAnomaly.id}</p>
              </div>
              <button onClick={() => setSelectedAnomaly(null)} style={{ background: "rgba(0,0,0,0.05)", border: "none", width: "32px", height: "32px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>✕</button>
            </div>
            
            <div style={{ flex: 1, padding: "24px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "20px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                <div>
                  <label style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 600, textTransform: "uppercase" }}>Location</label>
                  <p style={{ margin: "4px 0 0 0", fontSize: "1rem", color: "var(--navy)", fontWeight: 500 }}>{selectedAnomaly.district} / {selectedAnomaly.afso} / FPS {selectedAnomaly.fps_id}</p>
                </div>
                <div>
                  <label style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 600, textTransform: "uppercase" }}>Period</label>
                  <p style={{ margin: "4px 0 0 0", fontSize: "1rem", color: "var(--navy)", fontWeight: 500 }}>{selectedAnomaly.month} {selectedAnomaly.year}</p>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                <div>
                  <label style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 600, textTransform: "uppercase" }}>Commodity</label>
                  <p style={{ margin: "4px 0 0 0", fontSize: "1rem", color: "var(--navy)", fontWeight: 500 }}>{selectedAnomaly.commodity}</p>
                </div>
                <div>
                  <label style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 600, textTransform: "uppercase" }}>Cards</label>
                  <p style={{ margin: "4px 0 0 0", fontSize: "1rem", color: "var(--navy)", fontWeight: 500 }}>{selectedAnomaly.cards}</p>
                </div>
              </div>

              <div style={{ background: "var(--bg)", padding: "16px", borderRadius: "12px", border: "1px solid var(--line)" }}>
                <h4 style={{ margin: "0 0 12px 0", fontSize: "0.9rem", color: "var(--navy)" }}>Discrepancy Details</h4>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                  <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>Observed Qty:</span>
                  <span style={{ fontWeight: 600, color: "var(--navy)" }}>{selectedAnomaly.quantity_kgs} kg</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                  <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>Expected Qty (Proxy):</span>
                  <span style={{ fontWeight: 600, color: "var(--navy)" }}>{selectedAnomaly.expected_qty} kg</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", paddingTop: "8px", borderTop: "1px dashed var(--line)" }}>
                  <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>Kg / Card:</span>
                  <span style={{ fontWeight: 700, color: "var(--red)" }}>
                    {selectedAnomaly.cards > 0 ? (selectedAnomaly.quantity_kgs / selectedAnomaly.cards).toFixed(2) : "—"}
                  </span>
                </div>
              </div>

              <div>
                <h4 style={{ margin: "0 0 12px 0", fontSize: "0.9rem", color: "var(--navy)" }}>AI Diagnosis Reasons</h4>
                <ul style={{ margin: 0, paddingLeft: "20px", display: "flex", flexDirection: "column", gap: "6px" }}>
                  <li style={{ fontSize: "0.9rem", color: "var(--text)" }}>{selectedAnomaly.detail}</li>
                  {selectedAnomaly.expected_qty > 0 && (
                    <li style={{ fontSize: "0.9rem", color: "var(--text)" }}>Expected quantity proxy: {selectedAnomaly.expected_qty} kg.</li>
                  )}
                </ul>
              </div>
            </div>

            <div style={{ padding: "24px", borderTop: "1px solid var(--line)", background: "var(--bg)", display: "flex", gap: "12px" }}>
              <button style={{ flex: 1, padding: "12px", background: "var(--primary-gradient)", color: "#fff", border: "none", borderRadius: "10px", fontWeight: 600, cursor: "pointer", transition: "opacity 0.2s" }} onMouseEnter={e=>e.currentTarget.style.opacity="0.9"} onMouseLeave={e=>e.currentTarget.style.opacity="1"}>
                Mark as Resolved
              </button>
              <button style={{ flex: 1, padding: "12px", background: "#fff", color: "var(--red)", border: "1px solid var(--red)", borderRadius: "10px", fontWeight: 600, cursor: "pointer", transition: "background 0.2s" }} onMouseEnter={e=>e.currentTarget.style.background="#fef2f2"} onMouseLeave={e=>e.currentTarget.style.background="#fff"}>
                Escalate Issue
              </button>
            </div>
          </>
        )}
      </div>

      {/* Overlay for Drawer */}
      {selectedAnomaly && (
        <div onClick={() => setSelectedAnomaly(null)} style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.3)", zIndex: 999, backdropFilter: "blur(2px)", animation: "fadeIn 0.3s ease-out" }} />
      )}

    </div>
  );
}
