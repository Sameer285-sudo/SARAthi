import { useQuery } from "@tanstack/react-query";
import { fetchOverview, fetchTransactionChartData } from "../api";
import { 
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, 
  AreaChart, Area, ComposedChart, XAxis, YAxis, CartesianGrid, 
  Tooltip, Legend, ResponsiveContainer 
} from "recharts";
import { Activity, Ticket, Package, AlertTriangle, Filter } from "lucide-react";

// Static mock (call volume + ticket categories stay as demo)
const callVolumeData = [
  { time: "08:00", calls: 120 }, { time: "10:00", calls: 210 }, 
  { time: "12:00", calls: 180 }, { time: "14:00", calls: 300 }, 
  { time: "16:00", calls: 240 }, { time: "18:00", calls: 150 }
];

const ticketCategories = [
  { name: "Ration Issue", value: 45 }, { name: "Dealer Complaint", value: 25 },
  { name: "Card Update", value: 20 }, { name: "Other", value: 10 }
];
const COLORS = ["#072B57", "#10B981", "#F6C54C", "#EF4444"];

const MONTH_ORDER = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

// --- Components ---

function StatCard({ title, value, subtext, icon, trend }: { title: string, value: string | number, subtext: string, icon: React.ReactNode, trend: "up" | "down" }) {
  return (
    <article style={{ background: "var(--card-glass)", borderRadius: "16px", padding: "20px", display: "flex", flexDirection: "column", gap: "12px", boxShadow: "var(--shadow)", border: "1px solid var(--line)", position: "relative", overflow: "hidden", backdropFilter: "blur(12px)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "0.9rem", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{title}</span>
        <div style={{ padding: "8px", borderRadius: "10px", background: "var(--bg-deep)", color: "var(--navy)" }}>{icon}</div>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: "12px" }}>
        <h3 style={{ fontSize: "2rem", fontWeight: 800, color: "var(--text)", margin: 0 }}>{value}</h3>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.85rem", fontWeight: 600 }}>
        <span style={{ color: trend === "up" ? "var(--green)" : "var(--red)" }}>
          {trend === "up" ? "+" : "-"} {subtext}
        </span>
        <span style={{ color: "var(--muted)" }}>vs last month</span>
      </div>
    </article>
  );
}

export function OverviewPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["overview"], queryFn: fetchOverview });

  // Real district totals from transactions API
  const { data: chartData } = useQuery({
    queryKey: ["tx-chart-district"],
    queryFn: () => fetchTransactionChartData("district"),
    staleTime: 5 * 60 * 1000,
  });

  // Real monthly trend (FRice commodity for overview)
  const { data: monthChartData } = useQuery({
    queryKey: ["tx-chart-month"],
    queryFn: () => fetchTransactionChartData("month"),
    staleTime: 5 * 60 * 1000,
  });

  // Transform district series → { name, value }
  const districtData = (chartData?.chart_data?.series ?? []).map(s => ({
    name: s.label, value: Math.round(s.value),
  }));

  // Transform monthly trend → { month, stock, demand } (rice as "stock", total as "demand")
  const monthlyTrend = chartData?.chart_data?.monthly_trend ?? [];
  const pivotMap: Record<string, { month: string; stock: number; demand: number }> = {};
  for (const r of monthlyTrend) {
    const key = r.month.slice(0, 3);
    if (!pivotMap[key]) pivotMap[key] = { month: key, stock: 0, demand: 0 };
    if (r.commodity === "FRice (Kgs)") pivotMap[key].stock  += r.quantity_kgs;
    else                               pivotMap[key].demand += r.quantity_kgs;
  }
  const stockTrends = MONTH_ORDER
    .map(m => pivotMap[m.slice(0, 3)])
    .filter(Boolean);

  if (isLoading) return <p className="state">Loading operational overview...</p>;
  if (error || !data) return <p className="state error">Unable to load overview.</p>;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: "24px", maxWidth: "1600px", margin: "0 auto" }}>
      
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <p className="eyebrow">Enterprise Dashboard</p>
          <h2 style={{ fontSize: "2rem", color: "var(--navy)", margin: "4px 0 0" }}>System Overview</h2>
        </div>
        <button style={{ display: "flex", alignItems: "center", gap: "8px", background: "var(--control-glass)", border: "1px solid var(--line)", padding: "10px 16px", borderRadius: "12px", cursor: "pointer", fontWeight: 800, color: "var(--text)", boxShadow: "0 14px 30px rgba(30,134,214,0.10)", backdropFilter: "blur(10px)" }}>
          <Filter size={16} /> Filters
        </button>
      </div>

      {/* KPI Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "20px" }}>
        <StatCard title="Total Requests" value="12,450" subtext="+14.5%" icon={<Activity size={24} />} trend="up" />
        <StatCard title="Active Tickets" value={data.call_centre.open_tickets} subtext="-5.2%" icon={<Ticket size={24} />} trend="down" />
        <StatCard title="Forecast Units" value={data.smart_allot.total_forecast} subtext="+8.1%" icon={<Package size={24} />} trend="up" />
        <StatCard title="Alerts/Anomalies" value={data.anomalies.flagged_shipments} subtext="+2.4%" icon={<AlertTriangle size={24} />} trend="down" />
      </div>

      {/* Charts Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: "20px" }}>
        
        {/* Area Chart: Rice vs Other Commodities */}
        <article style={{ gridColumn: "span 8", background: "var(--card-glass)", borderRadius: "16px", padding: "24px", boxShadow: "var(--shadow)", border: "1px solid var(--line)", backdropFilter: "blur(12px)" }}>
          <h3 style={{ fontSize: "1.1rem", color: "var(--navy)", marginBottom: "20px" }}>
            Monthly Distribution — Rice vs Other Commodities
            {stockTrends.length === 0 && <span style={{ fontSize: "0.75rem", color: "var(--muted)", marginLeft: 8 }}>(loading...)</span>}
          </h3>
          <div style={{ height: "300px" }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <AreaChart data={stockTrends.length > 0 ? stockTrends : []} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorStock" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--blue)" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="var(--blue)" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorDemand" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--green)" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="var(--green)" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)" />
                <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "var(--muted)" }} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "var(--muted)" }} dx={-10}
                  tickFormatter={(v: number) => v >= 1000000 ? `${(v/1000000).toFixed(1)}M` : v >= 1000 ? `${(v/1000).toFixed(0)}K` : String(v)} />
                <Tooltip
                  formatter={(val: unknown, name: unknown) => [`${Number(val).toLocaleString("en-IN")} Kgs`, String(name) === "stock" ? "FRice" : "Other Commodities"]}
                  contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "var(--shadow)" }} />
                <Legend iconType="circle" wrapperStyle={{ paddingTop: "10px" }}
                  formatter={(v: string) => v === "stock" ? "FRice (Kgs)" : "Other Commodities (Kgs)"} />
                <Area type="monotone" dataKey="stock" stroke="var(--blue)" strokeWidth={3} fillOpacity={1} fill="url(#colorStock)" />
                <Area type="monotone" dataKey="demand" stroke="var(--green)" strokeWidth={3} fillOpacity={1} fill="url(#colorDemand)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </article>

        {/* Pie Chart: Ticket Categories */}
        <article style={{ gridColumn: "span 4", background: "var(--card-glass)", borderRadius: "16px", padding: "24px", boxShadow: "var(--shadow)", border: "1px solid var(--line)", backdropFilter: "blur(12px)" }}>
          <h3 style={{ fontSize: "1.1rem", color: "var(--navy)", marginBottom: "20px" }}>Ticket Categories</h3>
          <div style={{ height: "300px" }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <PieChart>
                <Pie data={ticketCategories} cx="50%" cy="50%" innerRadius={70} outerRadius={100} paddingAngle={5} dataKey="value" stroke="none">
                  {ticketCategories.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "var(--shadow)" }} />
                <Legend iconType="circle" />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </article>

        {/* Bar Chart: Real District Distribution */}
        <article style={{ gridColumn: "span 6", background: "var(--card-glass)", borderRadius: "16px", padding: "24px", boxShadow: "var(--shadow)", border: "1px solid var(--line)", backdropFilter: "blur(12px)" }}>
          <h3 style={{ fontSize: "1.1rem", color: "var(--navy)", marginBottom: "20px" }}>
            Quantity Distributed by District
            <span style={{ fontSize: "0.72rem", color: "var(--muted)", fontWeight: 400, marginLeft: 8 }}>— Real data from CSV</span>
          </h3>
          <div style={{ height: "250px" }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <BarChart data={districtData.length > 0 ? districtData : [{ name: "Loading...", value: 0 }]}
                margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted)" }} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "var(--muted)" }}
                  tickFormatter={(v: number) => v >= 1000000 ? `${(v/1000000).toFixed(1)}M` : v >= 1000 ? `${(v/1000).toFixed(0)}K` : String(v)} />
                <Tooltip
                  formatter={(val: unknown) => [`${Number(val).toLocaleString("en-IN")} Kgs`, "Quantity"]}
                  cursor={{ fill: "var(--bg)" }} contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "var(--shadow)" }} />
                <Bar dataKey="value" fill="var(--blue)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>

        {/* Line Chart: Call Volume */}
        <article style={{ gridColumn: "span 6", background: "var(--card-glass)", borderRadius: "16px", padding: "24px", boxShadow: "var(--shadow)", border: "1px solid var(--line)", backdropFilter: "blur(12px)" }}>
          <h3 style={{ fontSize: "1.1rem", color: "var(--navy)", marginBottom: "20px" }}>Live Call Volume</h3>
          <div style={{ height: "250px" }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <LineChart data={callVolumeData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)" />
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "var(--muted)" }} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "var(--muted)" }} />
                <Tooltip contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "var(--shadow)" }} />
                <Line type="monotone" dataKey="calls" stroke="var(--amber)" strokeWidth={4} dot={{ r: 6, fill: "var(--amber)", strokeWidth: 2, stroke: "#fff" }} activeDot={{ r: 8 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </article>

      </div>
    </section>
  );
}
