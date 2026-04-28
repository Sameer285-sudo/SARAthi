import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell,
} from "recharts";
import {
  fetchTransactionFilters,
  fetchTransactionSummary,
  fetchTransactions,
  fetchTransactionChartData,
  type TxFilters,
} from "../api";
import {
  Package, Users, Database, TrendingUp, ChevronDown, RefreshCw,
  BarChart2, Table, Filter,
} from "lucide-react";

// ── Colour palette ─────────────────────────────────────────────────────────────
const COMMODITY_COLORS: Record<string, string> = {
  "FRice (Kgs)":           "#1E3A8A",
  "Jowar (Kgs)":           "#10B981",
  "Raagi (Kgs)":           "#F59E0B",
  "SUGAR HALF KG (Kgs)":   "#EF4444",
  "WM Atta Pkt (Kgs)":     "#8B5CF6",
  "Whole Wheat Atta (Kgs)":"#06B6D4",
  "Flood Dal (Kgs)":       "#F97316",
  "Flood Rice (Kgs)":      "#14B8A6",
};

const MONTH_ORDER = ["January", "February", "March", "April",
  "May", "June", "July", "August", "September", "October", "November", "December"];

// ── Tiny sub-components ────────────────────────────────────────────────────────

function KpiCard({
  icon, title, value, sub, color = "var(--navy)",
}: { icon: React.ReactNode; title: string; value: string | number; sub?: string; color?: string }) {
  return (
    <article style={{
      background: "var(--card-glass)", borderRadius: 16, padding: "20px 24px",
      boxShadow: "var(--shadow)", border: "1px solid rgba(255,255,255,0.55)",
      backdropFilter: "blur(12px)",
      display: "flex", flexDirection: "column", gap: 8,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          {title}
        </span>
        <div style={{ padding: 8, borderRadius: 10, background: "var(--bg-deep)", color }}>{icon}</div>
      </div>
      <h3 style={{ fontSize: "1.9rem", fontWeight: 800, color: "var(--text)", margin: 0, lineHeight: 1 }}>
        {typeof value === "number" ? value.toLocaleString("en-IN") : value}
      </h3>
      {sub && <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--muted)" }}>{sub}</p>}
    </article>
  );
}

function Select({
  label, value, options, onChange, disabled = false,
}: {
  label: string; value: string; options: string[];
  onChange: (v: string) => void; disabled?: boolean;
}) {
  // Defensive default: when the backend is down `options` can be `undefined`
  // through intermediate states (or older callers). Avoid crashing the page.
  const safeOptions = Array.isArray(options) ? options : [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 160 }}>
      <label style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </label>
      <div style={{ position: "relative" }}>
        <select
          value={value}
          disabled={disabled || safeOptions.length === 0}
          onChange={e => onChange(e.target.value)}
          style={{
            appearance: "none", width: "100%", padding: "9px 36px 9px 12px",
            borderRadius: 10, border: "1.5px solid var(--line)",
            background: disabled ? "var(--control-glass-disabled)" : "var(--control-glass)",
            backdropFilter: "blur(10px)",
            color: "var(--text)", fontSize: "0.88rem", fontWeight: 500,
            cursor: disabled ? "not-allowed" : "pointer",
            outline: "none", transition: "border 0.15s",
          }}
        >
          <option value="">All {label}s</option>
          {safeOptions.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
        <ChevronDown size={14} style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--muted)" }} />
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function DistributionPage() {
  const [filters, setFilters] = useState<TxFilters>({});
  const [groupBy, setGroupBy] = useState<"district" | "afso" | "fps_id" | "month">("district");
  const [view, setView] = useState<"chart" | "table">("chart");
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 100;

  // ── Data fetches ────────────────────────────────────────────────────────────
  const { data: filterData, isLoading: filtersLoading } = useQuery({
    queryKey: ["tx-filters"],
    queryFn: fetchTransactionFilters,
    staleTime: 5 * 60 * 1000,
  });

  const { data: summaryData, isLoading: summaryLoading } = useQuery({
    queryKey: ["tx-summary", filters],
    queryFn: () => fetchTransactionSummary(filters),
  });

  const { data: chartData, isLoading: chartLoading } = useQuery({
    queryKey: ["tx-chart", groupBy, filters],
    queryFn: () => fetchTransactionChartData(groupBy, filters),
  });

  const { data: tableData, isLoading: tableLoading } = useQuery({
    queryKey: ["tx-records", filters, page],
    queryFn: () => fetchTransactions({ ...filters, skip: page * PAGE_SIZE, limit: PAGE_SIZE }),
    enabled: view === "table",
  });

  // ── Cascading filter options ─────────────────────────────────────────────────
  const fd = filterData?.filters;
  const districts = fd?.districts ?? [];
  const afsos = useMemo(() => {
    if (!fd) return [];
    if (!filters.district) return fd.afsos;
    return fd.afsos_by_district[filters.district] ?? [];
  }, [fd, filters.district]);

  const fpsList = useMemo(() => {
    if (!fd) return [];
    if (!filters.afso) return fd.fps_ids;
    return fd.fps_by_afso[filters.afso] ?? [];
  }, [fd, filters.afso]);

  const months = fd?.months ?? [];
  const commodities = fd?.commodities ?? [];

  // ── Handlers ─────────────────────────────────────────────────────────────────
  const setFilter = (key: keyof TxFilters, val: string) => {
    setPage(0);
    setFilters(prev => {
      const next = { ...prev, [key]: val || undefined };
      // Reset child filters when parent changes
      if (key === "district") { delete next.afso; delete next.fps_id; }
      if (key === "afso")     { delete next.fps_id; }
      return next;
    });
  };

  const resetFilters = () => { setFilters({}); setPage(0); };

  // ── Derived chart data ────────────────────────────────────────────────────────
  const barSeries = chartData?.chart_data.series ?? [];
  const monthlyTrend = chartData?.chart_data.monthly_trend ?? [];

  // Pivot monthly trend to recharts format: [{month, FRice, Jowar, ...}]
  const pivotedTrend = useMemo(() => {
    const map: Record<string, Record<string, number>> = {};
    for (const r of monthlyTrend) {
      if (!map[r.month]) map[r.month] = { month: r.month as unknown as number };
      map[r.month][r.commodity] = r.quantity_kgs;
    }
    return MONTH_ORDER.filter(m => m in map).map(m => map[m]);
  }, [monthlyTrend]);

  const topCommodities = useMemo(() => {
    const set = new Set(monthlyTrend.map(r => r.commodity));
    return [...set].slice(0, 5);
  }, [monthlyTrend]);

  const summary = summaryData?.summary;
  const isLoading = filtersLoading || summaryLoading;

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 1600, margin: "0 auto" }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
        <div>
          <p className="eyebrow">Real Dataset · 2026</p>
          <h2 style={{ fontSize: "2rem", color: "var(--navy)", margin: "4px 0 0" }}>Distribution Dashboard</h2>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          {/* View toggle */}
          {[["chart", <BarChart2 size={15} />], ["table", <Table size={15} />]].map(([v, icon]) => (
            <button key={v as string} onClick={() => setView(v as "chart" | "table")} style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "8px 14px", borderRadius: 10, border: "1.5px solid var(--line)",
              background: view === v ? "var(--navy)" : "var(--control-glass)",
              color: view === v ? "#fff" : "var(--text)",
              fontWeight: 600, fontSize: "0.85rem", cursor: "pointer",
              backdropFilter: "blur(10px)",
            }}>
              {icon}{(v as string).charAt(0).toUpperCase() + (v as string).slice(1)}
            </button>
          ))}
          <button onClick={resetFilters} style={{
            display: "flex", alignItems: "center", gap: 6, padding: "8px 14px",
            borderRadius: 10, border: "1.5px solid var(--line)", background: "var(--control-glass)",
            color: "var(--muted)", fontWeight: 800, fontSize: "0.85rem", cursor: "pointer",
            boxShadow: "0 14px 30px rgba(30,134,214,0.10)", backdropFilter: "blur(10px)",
          }}>
            <RefreshCw size={14} /> Reset
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div style={{
        background: "var(--card-glass)", borderRadius: 16, padding: "18px 24px",
        boxShadow: "0 18px 46px rgba(30,134,214,0.10)", border: "1px solid rgba(255,255,255,0.55)",
        display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-end",
        backdropFilter: "blur(12px)",
      }}>
        <div style={{ color: "var(--navy)", display: "flex", alignItems: "center", gap: 6, fontWeight: 700 }}>
          <Filter size={16} /> Filters
        </div>
        <Select label="District"  value={filters.district  ?? ""} options={districts}  onChange={v => setFilter("district",  v)} />
        <Select label="AFSO"      value={filters.afso      ?? ""} options={afsos}      onChange={v => setFilter("afso",      v)} disabled={!filters.district} />
        <Select label="FPS"       value={filters.fps_id    ?? ""} options={fpsList}    onChange={v => setFilter("fps_id",    v)} disabled={!filters.afso} />
        <Select label="Month"     value={filters.month     ?? ""} options={months}     onChange={v => setFilter("month",     v)} />
        <Select label="Commodity" value={filters.commodity ?? ""} options={commodities} onChange={v => setFilter("commodity", v)} />
      </div>

      {/* KPI Cards */}
      {isLoading ? (
        <p className="state">Loading data...</p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 18 }}>
          <KpiCard icon={<Package size={22} />}    title="Total FPS"        value={summary?.total_fps ?? 0}           sub="Fair Price Shops" />
          <KpiCard icon={<Users size={22} />}       title="Ration Cards"     value={summary?.total_cards ?? 0}         sub="Beneficiary cards" color="#10B981" />
          <KpiCard icon={<Database size={22} />}    title="Total Qty (Kgs)"  value={Math.round(summary?.total_quantity_kgs ?? 0).toLocaleString("en-IN")} sub="All commodities" color="#F59E0B" />
          <KpiCard icon={<TrendingUp size={22} />}  title="Months Covered"   value={(summary?.months_covered ?? []).join(", ") || "—"} sub="Data period" color="#8B5CF6" />
          {(summary?.commodity_totals ?? []).slice(0, 1).map(ct => (
            <KpiCard key={ct.commodity} icon={<Package size={22} />} title={ct.commodity.replace(" (Kgs)", "")}
              value={Math.round(ct.total_kgs).toLocaleString("en-IN") + " Kgs"} sub="Top commodity" color="#EF4444" />
          ))}
        </div>
      )}

      {view === "chart" ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 20 }}>

          {/* Bar chart — grouped by */}
          <article style={{
            gridColumn: "span 8", background: "var(--card-glass)", borderRadius: 16,
            padding: 24, boxShadow: "var(--shadow)", border: "1px solid rgba(255,255,255,0.55)",
            backdropFilter: "blur(12px)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20, flexWrap: "wrap", gap: 10 }}>
              <h3 style={{ fontSize: "1.05rem", color: "var(--navy)", margin: 0 }}>
                Quantity Distributed by {groupBy.charAt(0).toUpperCase() + groupBy.slice(1).replace("_", " ")}
              </h3>
              <div style={{ display: "flex", gap: 8 }}>
                {(["district", "afso", "fps_id", "month"] as const).map(g => (
                  <button key={g} onClick={() => setGroupBy(g)} style={{
                    padding: "5px 10px", borderRadius: 8, border: "1.5px solid var(--line)",
                    background: groupBy === g ? "var(--navy)" : "var(--control-glass)",
                    color: groupBy === g ? "#fff" : "var(--muted)",
                    fontSize: "0.78rem", fontWeight: 600, cursor: "pointer",
                  }}>
                    {g === "fps_id" ? "FPS" : g.charAt(0).toUpperCase() + g.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            {chartLoading ? <p className="state">Loading chart...</p> : (
              <div style={{ height: 300 }}>
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <BarChart data={barSeries.slice(0, 20)} margin={{ top: 5, right: 20, left: 0, bottom: 40 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)" />
                    <XAxis dataKey="label" axisLine={false} tickLine={false}
                      tick={{ fontSize: 11, fill: "var(--muted)" }}
                      angle={barSeries.length > 6 ? -35 : 0} textAnchor={barSeries.length > 6 ? "end" : "middle"}
                      dy={barSeries.length > 6 ? 10 : 8} />
                    <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted)" }}
                      tickFormatter={(v: number) => v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v)} />
                    <Tooltip
                      formatter={(val: unknown) => [`${Number(val).toLocaleString("en-IN")} Kgs`, "Quantity"]}
                      contentStyle={{ borderRadius: 12, border: "none", boxShadow: "var(--shadow)" }} />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                      {barSeries.slice(0, 20).map((_, i) => (
                        <Cell key={i} fill={Object.values(COMMODITY_COLORS)[i % Object.values(COMMODITY_COLORS).length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </article>

          {/* Commodity Breakdown list */}
          <article style={{
            gridColumn: "span 4", background: "var(--card-glass)", borderRadius: 16,
            padding: 24, boxShadow: "var(--shadow)", border: "1px solid rgba(255,255,255,0.55)",
            backdropFilter: "blur(12px)",
            display: "flex", flexDirection: "column", gap: 14,
          }}>
            <h3 style={{ fontSize: "1.05rem", color: "var(--navy)", margin: 0 }}>Commodity Breakdown</h3>
            {summaryLoading ? <p className="state">Loading…</p> : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10, overflowY: "auto", maxHeight: 320 }}>
                {(summary?.commodity_totals ?? []).map((ct, i) => {
                  const max = Math.max(...(summary?.commodity_totals ?? []).map(x => x.total_kgs), 1);
                  const pct = (ct.total_kgs / max) * 100;
                  const color = COMMODITY_COLORS[ct.commodity] ?? `hsl(${i * 40}, 70%, 50%)`;
                  return (
                    <div key={ct.commodity}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82rem", fontWeight: 600, marginBottom: 4 }}>
                        <span style={{ color: "var(--text)" }}>{ct.commodity.replace(" (Kgs)", "")}</span>
                        <span style={{ color: "var(--muted)" }}>{Math.round(ct.total_kgs).toLocaleString("en-IN")} Kgs</span>
                      </div>
                      <div style={{ height: 6, borderRadius: 4, background: "var(--bg-deep)" }}>
                        <div style={{ height: "100%", width: `${pct}%`, borderRadius: 4, background: color, transition: "width 0.4s" }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </article>

          {/* Monthly Trend Area Chart */}
          <article style={{
            gridColumn: "span 12", background: "var(--card-glass)", borderRadius: 16,
            padding: 24, boxShadow: "var(--shadow)", border: "1px solid rgba(255,255,255,0.55)",
            backdropFilter: "blur(12px)",
          }}>
            <h3 style={{ fontSize: "1.05rem", color: "var(--navy)", margin: "0 0 20px" }}>Monthly Distribution Trend</h3>
            {chartLoading ? <p className="state">Loading…</p> : (
              <div style={{ height: 280 }}>
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <AreaChart data={pivotedTrend} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                    <defs>
                      {topCommodities.map((c, i) => {
                        const col = COMMODITY_COLORS[c] ?? `hsl(${i * 60}, 70%, 50%)`;
                        return (
                          <linearGradient key={c} id={`grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%"  stopColor={col} stopOpacity={0.25} />
                            <stop offset="95%" stopColor={col} stopOpacity={0} />
                          </linearGradient>
                        );
                      })}
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)" />
                    <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "var(--muted)" }} dy={8} />
                    <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted)" }}
                      tickFormatter={(v: number) => v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v)} />
                    <Tooltip
                      formatter={(val: unknown, name: unknown) => [`${Number(val).toLocaleString("en-IN")} Kgs`, String(name).replace(" (Kgs)", "")]}
                      contentStyle={{ borderRadius: 12, border: "none", boxShadow: "var(--shadow)" }} />
                    <Legend iconType="circle" formatter={(v: string) => v.replace(" (Kgs)", "")} />
                    {topCommodities.map((c, i) => {
                      const col = COMMODITY_COLORS[c] ?? `hsl(${i * 60}, 70%, 50%)`;
                      return (
                        <Area key={c} type="monotone" dataKey={c} stroke={col} strokeWidth={2.5}
                          fill={`url(#grad-${i})`} dot={{ r: 4, fill: col, strokeWidth: 2, stroke: "#fff" }} />
                      );
                    })}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </article>
        </div>
      ) : (
        /* Table view */
        <article style={{
          background: "var(--card-glass)", borderRadius: 16, padding: 24,
          boxShadow: "var(--shadow)", border: "1px solid rgba(255,255,255,0.55)", overflow: "hidden",
          backdropFilter: "blur(12px)",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
            <h3 style={{ fontSize: "1.05rem", color: "var(--navy)", margin: 0 }}>
              Distribution Records
              {tableData && <span style={{ marginLeft: 10, fontSize: "0.82rem", color: "var(--muted)", fontWeight: 500 }}>({tableData.total.toLocaleString("en-IN")} total)</span>}
            </h3>
            <div style={{ display: "flex", gap: 8 }}>
              <button disabled={page === 0} onClick={() => setPage(p => p - 1)} style={{
                padding: "6px 14px", borderRadius: 8, border: "1.5px solid var(--line)",
                background: page === 0 ? "var(--control-glass-disabled)" : "var(--control-glass)", cursor: page === 0 ? "default" : "pointer",
                color: page === 0 ? "var(--muted)" : "var(--text)", fontWeight: 600, fontSize: "0.82rem",
              }}>← Prev</button>
              <span style={{ padding: "6px 12px", fontSize: "0.82rem", color: "var(--muted)", fontWeight: 600 }}>
                Page {page + 1} / {tableData ? Math.ceil(tableData.total / PAGE_SIZE) : "..."}
              </span>
              <button
                disabled={!tableData || (page + 1) * PAGE_SIZE >= tableData.total}
                onClick={() => setPage(p => p + 1)}
                style={{
                  padding: "6px 14px", borderRadius: 8, border: "1.5px solid var(--line)",
                  background: "var(--control-glass)", cursor: "pointer", color: "var(--text)", fontWeight: 600, fontSize: "0.82rem", backdropFilter: "blur(10px)",
                }}>Next →</button>
            </div>
          </div>

          {tableLoading ? <p className="state">Loading records...</p> : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
                <thead>
                  <tr style={{ background: "var(--bg-deep)" }}>
                    {["Year", "Month", "District", "AFSO", "FPS ID", "Commodity", "Qty (Kgs)", "Cards"].map(h => (
                      <th key={h} style={{
                        padding: "10px 14px", textAlign: "left", fontWeight: 700,
                        color: "var(--muted)", fontSize: "0.75rem", textTransform: "uppercase",
                        letterSpacing: "0.05em", borderBottom: "2px solid var(--line)", whiteSpace: "nowrap",
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(tableData?.records ?? []).map((r, i) => (
                    <tr key={r.id} style={{ background: i % 2 === 0 ? "rgba(255,255,255,0.42)" : "rgba(239,248,255,0.48)", transition: "background 0.15s" }}>
                      <td style={{ padding: "9px 14px", color: "var(--muted)" }}>{r.year}</td>
                      <td style={{ padding: "9px 14px", fontWeight: 600, color: "var(--navy)" }}>{r.month}</td>
                      <td style={{ padding: "9px 14px" }}>{r.district}</td>
                      <td style={{ padding: "9px 14px" }}>{r.afso}</td>
                      <td style={{ padding: "9px 14px", fontFamily: "monospace", color: "var(--blue)" }}>{r.fps_id}</td>
                      <td style={{ padding: "9px 14px" }}>
                        <span style={{
                          background: COMMODITY_COLORS[r.commodity] ? `${COMMODITY_COLORS[r.commodity]}18` : "var(--bg-deep)",
                          color: COMMODITY_COLORS[r.commodity] ?? "var(--text)",
                          padding: "2px 8px", borderRadius: 6, fontWeight: 600, fontSize: "0.78rem",
                        }}>
                          {r.commodity.replace(" (Kgs)", "")}
                        </span>
                      </td>
                      <td style={{ padding: "9px 14px", fontWeight: 700, textAlign: "right" }}>
                        {r.quantity_kgs.toLocaleString("en-IN")}
                      </td>
                      <td style={{ padding: "9px 14px", textAlign: "right", color: "var(--muted)" }}>
                        {r.cards.toLocaleString("en-IN")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      )}
    </section>
  );
}
