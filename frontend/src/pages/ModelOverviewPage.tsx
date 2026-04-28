import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { MapContainer, TileLayer, CircleMarker, Tooltip } from "react-leaflet";
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Legend
} from "recharts";
import { 
  Map, BarChart2, AlertTriangle, X, TrendingUp, Layers, CheckCircle
} from "lucide-react";
import { SarathiInsightsCard } from "../components/SarathiInsightsCard";
import { 
  fetchRecommendations,
  fetchTransactionFilters,
  fetchTransactionChartData,
  fetchTxAnomalies,
  fetchTxMapData,
} from "../api";

// District centroids aligned with the real dataset currently loaded into the DB.
// If you add more districts to the dataset, extend this map.
const AP_COORDS: Record<string, [number, number]> = {
  "Annamayya": [14.05, 78.75],
  "Chittoor":  [13.22, 79.10],
};

const DEFAULT_COORD: [number, number] = [14.0, 79.0];

const MAP_LAYERS = {
  landscape: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
  satellite: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
};

type MapLayer = "demand" | "allocation" | "anomaly";

export function ModelOverviewPage() {
  const navigate = useNavigate();
  const [activeLayer, setActiveLayer] = useState<MapLayer>("demand");
  const [mapType, setMapType] = useState<"landscape" | "satellite">("landscape");
  const [selectedDistrict, setSelectedDistrict] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<{
    level: "district" | "afso" | "fps";
    label: string;
    district: string;
    afso: string;
  } | null>(null);
  const [districtFilter, setDistrictFilter] = useState<string>("");
  const [afsoFilter, setAfsoFilter] = useState<string>("");
  const [fpsFilter, setFpsFilter] = useState<string>("");
  const [commodityFilter, setCommodityFilter] = useState<string>("");
  const [monthFilter, setMonthFilter] = useState<string>("");
  const [yearFilter, setYearFilter] = useState<number | "">("");

  // Queries
  const filtersQ = useQuery({
    queryKey: ["tx-filters"],
    queryFn: () => fetchTransactionFilters().catch(() => ({ filters: { districts: [], commodities: [], months: [] } } as any)),
  });

  const recQ = useQuery({
    queryKey: ["alloc-rec", districtFilter, commodityFilter],
    queryFn: () => fetchRecommendations({
      districtName: districtFilter || undefined,
      itemName: commodityFilter || undefined,
    }).catch(() => ({ recommendations: [] })),
  });

  const anomQ = useQuery({
    queryKey: ["tx-anoms", yearFilter, districtFilter, afsoFilter, fpsFilter, commodityFilter, monthFilter],
    queryFn: () => fetchTxAnomalies({
      year: typeof yearFilter === "number" ? yearFilter : undefined,
      district: districtFilter || undefined,
      afso: afsoFilter || undefined,
      fps_id: fpsFilter || undefined,
      commodity: commodityFilter || undefined,
      month: monthFilter || undefined,
      limit: 2000,
    }).catch(() => ({ anomalies: [] } as any)),
  });

  const recs = recQ.data?.recommendations ?? [];
  const anoms = (anomQ.data as any)?.anomalies ?? [];

  const districts: string[] = (filtersQ.data as any)?.filters?.districts ?? [];
  const commodities: string[] = (filtersQ.data as any)?.filters?.commodities ?? [];
  const months: string[] = (filtersQ.data as any)?.filters?.months ?? [];
  const years: number[] = (filtersQ.data as any)?.filters?.years ?? [];
  const afsos: string[] = districtFilter ? ((filtersQ.data as any)?.filters?.afsos_by_district?.[districtFilter] ?? []) : [];
  const fpsIds: string[] = afsoFilter ? ((filtersQ.data as any)?.filters?.fps_by_afso?.[afsoFilter] ?? []) : [];

  const effectiveMapLevel: "district" | "afso" | "fps" =
    fpsFilter ? "fps" : (afsoFilter ? "fps" : (districtFilter ? "afso" : "district"));

  const mapQ = useQuery({
    queryKey: ["tx-map", effectiveMapLevel, yearFilter, districtFilter, afsoFilter, fpsFilter, monthFilter, commodityFilter],
    queryFn: () => fetchTxMapData(effectiveMapLevel, {
      year: typeof yearFilter === "number" ? yearFilter : undefined,
      district: districtFilter || undefined,
      afso: afsoFilter || undefined,
      fps_id: fpsFilter || undefined,
      month: monthFilter || undefined,
      commodity: commodityFilter || undefined,
    }).catch(() => ({ markers: [] } as any)),
  });

  const trendQ = useQuery({
    queryKey: ["tx-trend", selectedNode?.level, selectedNode?.label, selectedNode?.district, commodityFilter],
    enabled: !!selectedNode,
    queryFn: () => fetchTransactionChartData("month", {
      year: typeof yearFilter === "number" ? yearFilter : undefined,
      district: selectedNode?.district ?? undefined,
      afso: selectedNode?.level === "afso" ? selectedNode.label : (selectedNode?.level === "fps" ? selectedNode.afso : undefined),
      fps_id: selectedNode?.level === "fps" ? selectedNode.label : undefined,
      commodity: commodityFilter || undefined,
    }).catch(() => ({ chart_data: { monthly_trend: [] } } as any)),
  });

  // Group recommendations by district for quick access
  const districtData = useMemo(() => {
    const data: Record<string, {
      demand: number, 
      allocated: number, 
      recommended: number,
      anomalies: number,
      critical: number,
      high: number,
      medium: number,
      low: number
    }> = {};

    // Merge Allocation & Demand
    recs.forEach(r => {
      const dName = r.district_name;
      if (!data[dName]) data[dName] = { demand: 0, allocated: 0, recommended: 0, anomalies: 0, critical: 0, high: 0, medium: 0, low: 0 };
      data[dName].demand += r.forecast_next_month || 0;
      data[dName].allocated += r.last_month_allocated || 0;
      data[dName].recommended += r.recommended_allotment || 0;
    });

    // Merge Transaction-based anomalies (/api/transactions/anomalies)
    anoms.forEach((a: any) => {
      const dName = String(a.district || "Unknown");
      if (!data[dName]) data[dName] = { demand: 0, allocated: 0, recommended: 0, anomalies: 0, critical: 0, high: 0, medium: 0, low: 0 };
      data[dName].anomalies += 1;
      const sev = String(a.severity || "").toUpperCase();
      if (sev === "CRITICAL") data[dName].critical += 1;
      else if (sev === "HIGH") data[dName].high += 1;
      else if (sev === "MEDIUM") data[dName].medium += 1;
      else data[dName].low += 1;
    });

    return data;
  }, [anoms, recs]);

  const mapMarkers = useMemo(() => {
    const markersRaw: any[] = (mapQ.data as any)?.markers ?? [];
    const markers = fpsFilter
      ? markersRaw.filter((m) => String(m.label) === String(fpsFilter))
      : markersRaw;

    const countsByLabel: Record<string, number> = {};
    for (const a of anoms as any[]) {
      const key =
        effectiveMapLevel === "district" ? String(a.district) :
        effectiveMapLevel === "afso"     ? String(a.afso) :
        String(a.fps_id);
      countsByLabel[key] = (countsByLabel[key] || 0) + 1;
    }

    const maxQty = Math.max(1, ...markers.map((m) => Number(m.qty_kgs || 0)));
    const maxAnom = Math.max(1, ...Object.values(countsByLabel));

    return markers.map((m) => {
      const coords: [number, number] = [Number(m.lat) || DEFAULT_COORD[0], Number(m.lng) || DEFAULT_COORD[1]];
      const label = String(m.label ?? "");
      const qty = Number(m.qty_kgs || 0);
      const anom = countsByLabel[label] || 0;

      let fillColor = "#cbd5e1";
      let color = "#94a3b8";
      let radius = 10;

      if (activeLayer === "demand") {
        const t = Math.sqrt(qty / maxQty);
        radius = 10 + t * 14;
        fillColor = "#fbbf24";
        color = "#b45309";
      } else if (activeLayer === "allocation") {
        const t = Math.sqrt(qty / maxQty);
        radius = 10 + t * 14;
        fillColor = "#60a5fa";
        color = "#1d4ed8";
      } else {
        const t = Math.sqrt(anom / maxAnom);
        radius = 10 + t * 14;
        fillColor = anom > 0 ? "#ef4444" : "#22c55e";
        color = anom > 0 ? "#991b1b" : "#166534";
      }

      const tooltipContent = (
        <div>
          <strong>{label}</strong><br />
          District: {String(m.district || "—")}<br />
          Quantity: {qty.toLocaleString("en-IN")} kg<br />
          FPS Count: {Number(m.fps_count || 0).toLocaleString("en-IN")}<br />
          Anomalies: {anom.toLocaleString("en-IN")}<br />
          <em>Click for details</em>
        </div>
      );

      return {
        district: String(m.district || label),
        afso: String(m.afso || ""),
        label,
        coords,
        fillColor,
        color,
        radius,
        tooltipContent,
      };
    });
  }, [activeLayer, anoms, effectiveMapLevel, fpsFilter, mapQ.data]);

  // Selected District Data
  const selectedStats = selectedDistrict ? districtData[selectedDistrict] : null;

  const demandTrendData = useMemo(() => {
    if (!selectedStats) return [];
    const trend = (trendQ.data as any)?.chart_data?.monthly_trend ?? [];
    const byMonth: Record<string, number> = {};
    trend.forEach((t: any) => {
      byMonth[t.month] = (byMonth[t.month] || 0) + Number(t.quantity_kgs || 0);
    });
    return Object.entries(byMonth).map(([month, qty]) => ({ month, Demand: qty }));
  }, [selectedStats, trendQ.data]);

  const allocationBarData = useMemo(() => {
    if (!selectedStats) return [];
    return [{
      name: "Allocation",
      Current: selectedStats.allocated,
      Recommended: selectedStats.recommended
    }];
  }, [selectedStats]);

  const anomalyPieData = useMemo(() => {
    if (!selectedStats) return [];
    return [
      { name: "Critical", value: selectedStats.critical, fill: "#ef4444" },
      { name: "High", value: selectedStats.high, fill: "#f97316" },
      { name: "Medium", value: selectedStats.medium, fill: "#eab308" },
      { name: "Low", value: selectedStats.low, fill: "#22c55e" },
    ].filter(d => d.value > 0);
  }, [selectedStats]);

  type ExplainableInsight = { text: string; source: string; derived?: boolean };
  const aiInsights: ExplainableInsight[] = useMemo(() => {
    const out: ExplainableInsight[] = [];

    const markers: any[] = (mapQ.data as any)?.markers ?? [];
    const topMarker = markers.reduce((best, cur) => (Number(cur.qty_kgs || 0) > Number(best?.qty_kgs || 0) ? cur : best), markers[0]);

    const critical = anoms.filter((a: any) => String(a.severity || "").toUpperCase() === "CRITICAL").length;
    const topIssueDistrict = anoms.reduce((acc: Record<string, number>, a: any) => {
      const k = String(a.district || "Unknown");
      acc[k] = (acc[k] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
    const topHotspot = (Object.entries(topIssueDistrict) as [string, number][]).sort((a, b) => b[1] - a[1])[0];

    if (activeLayer === "demand" && topMarker) {
      out.push({
        text: `Top distribution volume (proxy for demand) in current scope: ${String(topMarker.label)} = ${Number(topMarker.qty_kgs || 0).toLocaleString("en-IN")} kg.`,
        source: "Source: /api/transactions/map-data → markers[].qty_kgs (max)",
      });
    }

    if (activeLayer === "allocation") {
      const byDistrict = recs.reduce((acc: Record<string, number>, r: any) => {
        acc[String(r.district_name)] = (acc[String(r.district_name)] || 0) + Number(r.recommended_allotment || 0);
        return acc;
      }, {} as Record<string, number>);
      const top = Object.entries(byDistrict).sort((a, b) => b[1] - a[1])[0];
      if (top) {
        out.push({
          text: `Highest recommended allotment district in current scope: ${top[0]} = ${Number(top[1]).toLocaleString("en-IN")} kg.`,
          source: "Source: /api/smart-allot/recommendations → recommendations[].recommended_allotment (sum by district_name)",
        });
      }
    }

    if (activeLayer === "anomaly") {
      out.push({
        text: critical > 0 ? `CRITICAL anomalies in current scope: ${critical}.` : "No CRITICAL anomalies in current scope.",
        source: "Source: /api/transactions/anomalies → anomalies[].severity",
      });
      if (topHotspot) {
        out.push({
          text: `Top anomaly hotspot (district): ${topHotspot[0]} (${topHotspot[1]} anomalies).`,
          source: "Source: /api/transactions/anomalies → anomalies[].district (count)",
        });
      }
    }

    out.push({
      text: `Filters: District=${districtFilter || "All"}, AFSO=${afsoFilter || "All"}, FPS=${fpsFilter || "All"}, Month=${monthFilter || "All"}, Commodity=${commodityFilter || "All"}.`,
      source: "Source: UI filters → applied to /api/transactions/* and /api/smart-allot/recommendations",
      derived: true,
    });

    return out;
  }, [activeLayer, afsoFilter, commodityFilter, districtFilter, fpsFilter, monthFilter, anoms, mapQ.data, recs]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px", animation: "fadeIn 0.4s ease-out", height: "calc(100vh - 150px)" }}>
      
      {/* Header & Controls */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "var(--card-glass)", padding: "16px 24px", borderRadius: "16px", boxShadow: "0 18px 46px rgba(30,134,214,0.10)", border: "1px solid rgba(255,255,255,0.55)", backdropFilter: "blur(12px)" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "1.5rem", color: "var(--navy)", fontWeight: 800, display: "flex", alignItems: "center", gap: "10px" }}>
            <Map color="var(--primary)" size={28} />
            Command Map Overview
          </h2>
          <p style={{ margin: "4px 0 0 0", color: "var(--muted)", fontSize: "0.9rem" }}>Geographic intelligence for Demand, Allocation, and Anomalies.</p>
        </div>

        <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
          <select
            value={yearFilter === "" ? "" : String(yearFilter)}
            onChange={(e) => setYearFilter(e.target.value ? Number(e.target.value) : "")}
            style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800, color: "var(--text)" }}
          >
            <option value="">All Years</option>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <select
            value={districtFilter}
            onChange={(e) => {
              setDistrictFilter(e.target.value);
              setAfsoFilter("");
              setFpsFilter("");
              setSelectedDistrict(null);
              setSelectedNode(null);
            }}
            style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800, color: "var(--text)" }}
          >
            <option value="">All Districts</option>
            {districts.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <select
            value={afsoFilter}
            onChange={(e) => { setAfsoFilter(e.target.value); setFpsFilter(""); setSelectedDistrict(null); setSelectedNode(null); }}
            disabled={!districtFilter}
            style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: districtFilter ? "var(--control-glass)" : "var(--control-glass-disabled)", backdropFilter: "blur(10px)", fontWeight: 800, color: "var(--text)" }}
          >
            <option value="">All AFSOs</option>
            {afsos.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <select
            value={fpsFilter}
            onChange={(e) => { setFpsFilter(e.target.value); setSelectedDistrict(null); setSelectedNode(null); }}
            disabled={!afsoFilter}
            style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: afsoFilter ? "var(--control-glass)" : "var(--control-glass-disabled)", backdropFilter: "blur(10px)", fontWeight: 800, color: "var(--text)" }}
          >
            <option value="">All FPSs</option>
            {fpsIds.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
          <select value={commodityFilter} onChange={(e) => setCommodityFilter(e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800, color: "var(--text)" }}>
            <option value="">All Items</option>
            {commodities.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={monthFilter} onChange={(e) => setMonthFilter(e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--control-glass)", backdropFilter: "blur(10px)", fontWeight: 800, color: "var(--text)" }}>
            <option value="">All Months</option>
            {months.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>

          <div style={{ display: "flex", gap: "8px", background: "rgba(254,255,209,0.55)", padding: "6px", borderRadius: "12px", border: "1px solid var(--line)", backdropFilter: "blur(10px)" }}>
            {(["demand", "allocation", "anomaly"] as MapLayer[]).map(layer => (
              <button
                key={layer}
                onClick={() => setActiveLayer(layer)}
                style={{
                  padding: "8px 16px",
                  borderRadius: "8px",
                  border: "none",
                  background: activeLayer === layer ? "rgba(255,255,255,0.86)" : "transparent",
                  color: activeLayer === layer ? "var(--navy)" : "var(--muted)",
                  fontWeight: activeLayer === layer ? 800 : 600,
                  fontSize: "0.9rem",
                  cursor: "pointer",
                  boxShadow: activeLayer === layer ? "0 10px 18px rgba(30,134,214,0.10)" : "none",
                  display: "flex", alignItems: "center", gap: "8px",
                  transition: "all 0.2s"
                }}
              >
                {layer === "demand" && <TrendingUp size={16} color={activeLayer === layer ? "#eab308" : "currentColor"} />}
                {layer === "allocation" && <Layers size={16} color={activeLayer === layer ? "#3b82f6" : "currentColor"} />}
                {layer === "anomaly" && <AlertTriangle size={16} color={activeLayer === layer ? "#ef4444" : "currentColor"} />}
                {layer.charAt(0).toUpperCase() + layer.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main Map & Panel Area */}
      <div style={{ display: "flex", gap: "24px", flex: 1, minHeight: 0 }}>
        
        {/* Map Container */}
        <div style={{ flex: 1, background: "var(--card-glass)", borderRadius: "16px", overflow: "hidden", boxShadow: "0 18px 46px rgba(30,134,214,0.10)", border: "1px solid rgba(255,255,255,0.55)", backdropFilter: "blur(12px)", position: "relative" }}>
          
          {/* Map Type Toggle */}
          <div style={{ position: "absolute", top: "16px", right: "16px", zIndex: 1000, display: "flex", background: "rgba(254,255,209,0.55)", backdropFilter: "blur(10px)", borderRadius: "10px", padding: "4px", border: "1px solid var(--line)", boxShadow: "0 14px 30px rgba(30,134,214,0.12)" }}>
             <button onClick={() => setMapType("landscape")} style={{ padding: "4px 12px", border: "none", borderRadius: "8px", background: mapType === "landscape" ? "rgba(255,255,255,0.86)" : "transparent", boxShadow: mapType === "landscape" ? "0 10px 18px rgba(30,134,214,0.10)" : "none", fontSize: "0.75rem", fontWeight: 800, cursor: "pointer", color: mapType === "landscape" ? "var(--navy)" : "var(--muted)", transition: "all 0.2s" }}>Landscape</button>
             <button onClick={() => setMapType("satellite")} style={{ padding: "4px 12px", border: "none", borderRadius: "8px", background: mapType === "satellite" ? "rgba(255,255,255,0.86)" : "transparent", boxShadow: mapType === "satellite" ? "0 10px 18px rgba(30,134,214,0.10)" : "none", fontSize: "0.75rem", fontWeight: 800, cursor: "pointer", color: mapType === "satellite" ? "var(--navy)" : "var(--muted)", transition: "all 0.2s" }}>Satellite</button>
          </div>

          <MapContainer center={[16.5, 80.6]} zoom={6.5} scrollWheelZoom={true} style={{ height: "100%", width: "100%", zIndex: 1 }}>
            <TileLayer url={MAP_LAYERS[mapType]} attribution="&copy; OpenStreetMap &copy; CARTO" />
            
            {mapMarkers.map((m, _mi) => (
              <CircleMarker
                key={`${effectiveMapLevel}-${m.label}-${_mi}`}
                center={m.coords} 
                radius={m.radius} 
                fillColor={m.fillColor} 
                color={m.color} 
                weight={selectedDistrict === m.district ? 4 : 2} 
                opacity={0.9} 
                fillOpacity={0.6}
                eventHandlers={{
                  click: () => {
                    setSelectedDistrict(m.district);
                    setSelectedNode({
                      level: effectiveMapLevel,
                      label: m.label,
                      district: m.district,
                      afso: m.afso ?? "",
                    });
                  }
                }}
              >
                <Tooltip>{m.tooltipContent}</Tooltip>
              </CircleMarker>
            ))}
          </MapContainer>

          {/* AI Insights Floating Widget inside Map */}
          <div style={{ position: "absolute", bottom: "24px", left: "24px", zIndex: 1000, width: "340px" }}>
            <SarathiInsightsCard
              variant="compact"
              title="SARATHI AI Insights"
              sections={aiInsights.slice(0, 3).map((ins, idx) => ({
                heading: idx === 0 ? "Current Scope" : idx === 1 ? "Demand / Allocation" : "Anomaly Watch",
                body: <span style={{ fontWeight: 650 }}>{ins.text}</span>,
              }))}
            />
          </div>
        </div>

        {/* Side Insight Panel */}
        {selectedDistrict && selectedStats && (
          <div style={{ width: "400px", background: "#fff", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(0,0,0,0.03)", display: "flex", flexDirection: "column", gap: "24px", overflowY: "auto", animation: "slideInRight 0.3s ease-out" }}>
            
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "1.4rem", color: "var(--navy)", fontWeight: 800 }}>{selectedDistrict}</h3>
                <p style={{ margin: "4px 0 0 0", fontSize: "0.85rem", color: "var(--muted)" }}>District Overview & Analytics</p>
              </div>
              <button onClick={() => setSelectedDistrict(null)} style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--muted)" }}>
                <X size={20} />
              </button>
            </div>

            {/* Demand Mini Chart */}
            <div style={{ padding: "16px", background: "#f8fafc", borderRadius: "12px", border: "1px solid #e2e8f0" }}>
              <h4 style={{ margin: "0 0 12px 0", fontSize: "0.9rem", color: "var(--navy)", display: "flex", alignItems: "center", gap: "6px" }}><TrendingUp size={16} /> Demand Trend</h4>
              <div style={{ height: "120px" }}>
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <LineChart data={demandTrendData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="month" hide />
                    <RechartsTooltip cursor={{fill: 'transparent'}} contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }} />
                    <Line type="monotone" dataKey="Demand" stroke="#eab308" strokeWidth={3} dot={{r: 4, fill: "#eab308", strokeWidth: 0}} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Allocation Mini Chart */}
            <div style={{ padding: "16px", background: "#f8fafc", borderRadius: "12px", border: "1px solid #e2e8f0" }}>
              <h4 style={{ margin: "0 0 12px 0", fontSize: "0.9rem", color: "var(--navy)", display: "flex", alignItems: "center", gap: "6px" }}><Layers size={16} /> Allocation Comparison</h4>
              <div style={{ height: "120px" }}>
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <BarChart data={allocationBarData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
                    <XAxis type="number" hide />
                    <YAxis dataKey="name" type="category" hide />
                    <RechartsTooltip cursor={{fill: 'transparent'}} contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }} />
                    <Bar dataKey="Current" fill="#94a3b8" radius={[0, 4, 4, 0]} barSize={20} />
                    <Bar dataKey="Recommended" fill="#3b82f6" radius={[0, 4, 4, 0]} barSize={20} />
                    <Legend iconType="circle" wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Anomaly Mini Chart */}
            <div style={{ padding: "16px", background: "#f8fafc", borderRadius: "12px", border: "1px solid #e2e8f0" }}>
              <h4 style={{ margin: "0 0 12px 0", fontSize: "0.9rem", color: "var(--navy)", display: "flex", alignItems: "center", gap: "6px" }}><AlertTriangle size={16} /> Anomalies Found</h4>
              {anomalyPieData.length > 0 ? (
                <div style={{ height: "140px", display: "flex", alignItems: "center" }}>
                  <ResponsiveContainer width="50%" height="100%" minWidth={0}>
                    <PieChart>
                      <Pie data={anomalyPieData} innerRadius={30} outerRadius={50} paddingAngle={2} dataKey="value">
                        {anomalyPieData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.fill} />
                        ))}
                      </Pie>
                      <RechartsTooltip contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "8px", paddingLeft: "10px" }}>
                    {anomalyPieData.map(d => (
                      <div key={d.name} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.8rem", color: "var(--navy)", fontWeight: 600 }}>
                        <span style={{ display: "flex", alignItems: "center", gap: "6px" }}><span style={{ width: "8px", height: "8px", borderRadius: "50%", background: d.fill }} /> {d.name}</span>
                        <span>{d.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div style={{ height: "120px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "var(--muted)" }}>
                  <CheckCircle size={32} color="#22c55e" style={{ marginBottom: "8px" }} />
                  <span style={{ fontSize: "0.9rem", fontWeight: 600 }}>No anomalies detected</span>
                </div>
              )}
            </div>
            
            <button
              onClick={() => {
                const params = new URLSearchParams();

                const district = districtFilter || selectedDistrict || "";
                if (!district) return;

                if (yearFilter !== "" && yearFilter != null) params.set("year", String(yearFilter));
                params.set("district", district);
                if (afsoFilter) params.set("afso", afsoFilter);
                if (fpsFilter) params.set("fps_id", fpsFilter);
                if (monthFilter) params.set("month", monthFilter);
                if (commodityFilter) params.set("commodity", commodityFilter);

                navigate(`/smart-allot?${params.toString()}`);
              }}
              disabled={!(districtFilter || selectedDistrict)}
              style={{ width: "100%", padding: "12px", background: "var(--primary-gradient)", color: "#fff", border: "none", borderRadius: "10px", fontWeight: 700, fontSize: "0.95rem", cursor: (districtFilter || selectedDistrict) ? "pointer" : "not-allowed", opacity: (districtFilter || selectedDistrict) ? 1 : 0.65, boxShadow: "0 4px 15px rgba(30,58,138,0.2)" }}
            >
              View Full District Report
            </button>

          </div>
        )}

      </div>
    </div>
  );
}
