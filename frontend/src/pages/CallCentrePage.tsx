import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createLiveMetricsSocket,
  fetchCallCentreDashboard,
  fetchCCAgentPerformance,
  fetchCCAnalyticsOverview,
  fetchCCAnalyticsSentiment,
  fetchCCAnalyticsTickets,
  fetchCCCallVolume,
  fetchCCNotifications,
  fetchCCSLABreaches,
  fetchIVRConfig,
  fetchLiveMetrics,
  getTTSUrl,
  submitVoiceRecording,
  fetchTickets,
  sendVoiceMessage,
  setVoiceLanguage,
  startVoiceSession,
  submitCallPipeline,
  updateTicketStatus,
  uploadAudio,
} from "../api";
import { MapContainer, TileLayer, CircleMarker, Tooltip as LeafletTooltip } from "react-leaflet";
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar
} from "recharts";
import { 
  Zap, Activity, AlertCircle, Clock, BarChart2, MessageSquare, Phone, TrendingUp,
  Mic, Square, UploadCloud, FileAudio, Play, Loader2, Send, Bot, User, CheckCircle2,
  Check, MoreVertical, Search, Filter, Tag, Settings2, AlertTriangle, Key, Terminal,
  ArrowRight, Server, PlayCircle, Layers, Smartphone, Globe, CheckCircle
} from "lucide-react";

const AP_COORDS: Record<string, [number, number]> = {
  "Visakhapatnam": [17.6868, 83.2185],
  "Guntur": [16.3067, 80.4365],
  "Krishna": [16.2998, 81.1121],
  "Kurnool": [15.8281, 78.0373],
  "Tirupati": [13.6288, 79.4192],
  "Anantapur": [14.6819, 77.6006],
  "Prakasam": [15.5015, 79.9696],
  "Nandyal": [15.4855, 78.4842],
  "Palnadu": [16.2415, 79.7423],
};
const DEFAULT_COORD: [number, number] = [15.9129, 79.7400];

const MAP_LAYERS = {
  landscape: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
  satellite: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
};


import type {
  AudioTranscriptResponse,
  CCAgentRecord,
  CCAnalyticsOverview,
  CCAnalyticsSentiment,
  CCAnalyticsTickets,
  CCCallPipelineResult,
  CCCallVolume,
  CCNotification,
  CCSLABreach,
  CallCentreTicket,
  LiveMetrics,
  VoiceSession,
} from "../types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function sentimentColor(label: string | null) {
  if (!label) return "var(--muted)";
  if (label === "Distressed") return "var(--red)";
  if (label === "Negative") return "var(--saffron)";
  if (label === "Positive") return "var(--green)";
  return "var(--muted)";
}

function sentimentBar(score: number) {
  const pct = Math.round(((score + 1) / 2) * 100);
  const color = score <= -0.45 ? "var(--red)" : score < 0 ? "var(--saffron)" : "var(--green)";
  return (
    <div className="sentiment-bar-wrap">
      <div className="sentiment-bar" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

function priorityClass(p: string) {
  return p === "HIGH" ? "high" : p === "MEDIUM" ? "medium" : "low";
}

const STATUS_OPTIONS = ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"];

// ── Sub-components ────────────────────────────────────────────────────────────

function LiveMetricsBanner({ metrics }: { metrics: LiveMetrics }) {
  return (
    <div className="live-banner">
      <div className="live-dot" />
      <span>LIVE</span>
      <span className="live-sep" />
      <span><strong>{metrics.active_sessions}</strong> active sessions</span>
      <span className="live-sep" />
      <span><strong>{metrics.open_tickets}</strong> open tickets</span>
      <span className="live-sep" />
      <span><strong>{metrics.resolved_today}</strong> resolved today</span>
      <span className="live-sep" />
      <span><strong>{metrics.high_priority}</strong> high-priority</span>
      <span className="live-sep" />
      <span>Avg sentiment <strong style={{ color: sentimentColor(metrics.avg_sentiment < -0.25 ? "Negative" : "Positive") }}>{metrics.avg_sentiment > 0 ? "+" : ""}{metrics.avg_sentiment.toFixed(2)}</strong></span>
    </div>
  );
}

function SentimentTrend({ trend }: { trend: number[] }) {
  if (!trend.length) return null;
  const min = -1, max = 1, h = 56, w = 220;
  const pts = trend.map((v, i) => {
    const x = (i / Math.max(trend.length - 1, 1)) * w;
    const y = h - ((v - min) / (max - min)) * h;
    return `${x},${y}`;
  }).join(" ");
  return (
    <div className="trend-chart">
      <p className="eyebrow" style={{ marginBottom: 8 }}>Sentiment Trend (last 7)</p>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
        <polyline points={pts} fill="none" stroke="var(--blue)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        {trend.map((v, i) => {
          const x = (i / Math.max(trend.length - 1, 1)) * w;
          const y = h - ((v - min) / (max - min)) * h;
          return <circle key={i} cx={x} cy={y} r="4" fill={v < -0.25 ? "var(--red)" : "var(--green)"} />;
        })}
      </svg>
    </div>
  );
}

function LanguageBar({ data }: { data: Record<string, number> }) {
  const total = Object.values(data).reduce((a, b) => a + b, 0) || 1;
  const colors: Record<string, string> = { English: "var(--blue)", Telugu: "var(--green)", Hindi: "var(--amber)" };
  return (
    <div>
      <p className="eyebrow" style={{ marginBottom: 8 }}>Calls by Language</p>
      <div className="lang-bar-stack">
        {Object.entries(data).map(([lang, count]) => (
          <div
            key={lang}
            className="lang-bar-seg"
            style={{ width: `${(count / total) * 100}%`, background: colors[lang] || "var(--muted)" }}
            title={`${lang}: ${count}`}
          />
        ))}
      </div>
      <div className="lang-legend">
        {Object.entries(data).map(([lang, count]) => (
          <span key={lang} className="lang-legend-item">
            <span className="lang-dot" style={{ background: colors[lang] || "var(--muted)" }} />
            {lang} ({count})
          </span>
        ))}
      </div>
    </div>
  );
}

function TicketCard({
  ticket,
  onStatusChange,
}: {
  ticket: CallCentreTicket;
  onStatusChange: (id: string, status: string) => void;
}) {
  const [open, setOpen] = useState(false);
  
  const isResolved = ticket.status === "RESOLVED";
  const priorityColors = {
    HIGH: { bg: "#fef2f2", text: "#ef4444", border: "#fca5a5" },
    MEDIUM: { bg: "#fffbeb", text: "#f59e0b", border: "#fcd34d" },
    LOW: { bg: "#f0fdf4", text: "#10b981", border: "#86efac" }
  };
  const pColor = priorityColors[ticket.priority as keyof typeof priorityColors] || priorityColors.LOW;

  return (
    <article style={{ background: "white", borderRadius: "16px", padding: "20px", boxShadow: "0 4px 20px rgba(0,0,0,0.04)", border: `1px solid ${isResolved ? "rgba(16,185,129,0.2)" : "var(--line)"}`, display: "flex", flexDirection: "column", opacity: isResolved ? 0.7 : 1, transition: "all 0.2s" }} onMouseEnter={(e)=>e.currentTarget.style.boxShadow="0 8px 30px rgba(0,0,0,0.08)"} onMouseLeave={(e)=>e.currentTarget.style.boxShadow="0 4px 20px rgba(0,0,0,0.04)"}>
      
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
            <span style={{ fontSize: "0.75rem", fontFamily: "monospace", color: "var(--muted)", background: "#f1f5f9", padding: "2px 6px", borderRadius: "4px" }}>{ticket.ticket_id}</span>
            <span style={{ fontSize: "0.7rem", fontWeight: 700, color: pColor.text, background: pColor.bg, padding: "2px 8px", borderRadius: "10px", border: `1px solid ${pColor.border}` }}>{ticket.priority}</span>
          </div>
          <h3 style={{ margin: 0, fontSize: "1.1rem", color: "var(--navy)" }}>{ticket.caller_name}</h3>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
          <span style={{ fontSize: "0.75rem", background: ticket.channel === "call" ? "#eff6ff" : ticket.channel === "whatsapp" ? "#f0fdf4" : "#f8fafc", color: ticket.channel === "call" ? "#3b82f6" : ticket.channel === "whatsapp" ? "#10b981" : "#64748b", padding: "2px 8px", borderRadius: "12px", textTransform: "uppercase", fontWeight: 700 }}>{ticket.channel}</span>
        </div>
      </div>

      <div style={{ marginBottom: "16px" }}>
        <p style={{ margin: "0 0 6px", fontSize: "0.95rem", fontWeight: 600, color: "var(--text)" }}>{ticket.category}</p>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{ fontSize: "0.8rem", color: "var(--muted)", display: "flex", alignItems: "center", gap: "4px" }}><Globe size={14} /> {ticket.language}</span>
          <span style={{ fontSize: "0.8rem", color: sentimentColor(ticket.sentiment_label), display: "flex", alignItems: "center", gap: "4px", background: sentimentColor(ticket.sentiment_label)+"10", padding: "2px 6px", borderRadius: "4px" }}>
            {ticket.sentiment_label} ({ticket.sentiment_score.toFixed(2)})
          </span>
        </div>
      </div>

      <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: "12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.8rem" }}>
          <span style={{ color: "var(--muted)" }}>Assigned to: <strong>{ticket.assigned_team}</strong></span>
          <span style={{ display: "flex", alignItems: "center", gap: "4px", color: ticket.status==="ESCALATED" ? "#ef4444" : "var(--muted)" }}>
            <Clock size={14} /> {ticket.resolution_eta_hours}h ETA
          </span>
        </div>

        <div style={{ height: "1px", background: "var(--line)", width: "100%" }} />

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", gap: "4px" }}>
            {STATUS_OPTIONS.map((s) => (
              <button
                key={s}
                onClick={() => onStatusChange(ticket.ticket_id, s)}
                style={{ 
                  fontSize: "0.7rem", fontWeight: 600, padding: "4px 8px", borderRadius: "6px", cursor: "pointer", border: "1px solid",
                  background: ticket.status === s ? (s==="RESOLVED"?"#10b981":s==="ESCALATED"?"#ef4444":"#3b82f6") : "transparent",
                  color: ticket.status === s ? "white" : "var(--muted)",
                  borderColor: ticket.status === s ? "transparent" : "var(--line)"
                }}
              >
                {s}
              </button>
            ))}
          </div>
          <button onClick={() => setOpen((o) => !o)} style={{ background: "transparent", border: "none", color: "var(--blue)", fontSize: "0.85rem", cursor: "pointer", fontWeight: 600 }}>
            {open ? "Hide" : "View Details"}
          </button>
        </div>
      </div>

      {open && (
        <div style={{ marginTop: "16px", padding: "16px", background: "#f8fafc", borderRadius: "12px", border: "1px solid var(--line)", animation: "fadeIn 0.3s ease" }}>
          <strong style={{ fontSize: "0.8rem", color: "var(--navy)", textTransform: "uppercase" }}>Summary</strong>
          <p style={{ margin: "4px 0 12px", fontSize: "0.9rem", color: "var(--text)" }}>{ticket.summary}</p>
          
          <strong style={{ fontSize: "0.8rem", color: "var(--navy)", textTransform: "uppercase" }}>Suggested Action</strong>
          <p style={{ margin: "4px 0 12px", fontSize: "0.9rem", color: "#3b82f6", background: "#eff6ff", padding: "8px", borderRadius: "6px" }}>{ticket.next_action}</p>
          
          {ticket.transcript && (
            <>
              <strong style={{ fontSize: "0.8rem", color: "var(--navy)", textTransform: "uppercase" }}>Original Transcript</strong>
              <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--muted)", fontStyle: "italic", paddingLeft: "10px", borderLeft: "2px solid #cbd5e1" }}>"{ticket.transcript}"</p>
            </>
          )}
        </div>
      )}
    </article>
  );
}

function ChatbotPanel() {
  const [callerName, setCallerName] = useState("Guest Caller");
  const [callerType, setCallerType] = useState("public");
  const [session, setSession] = useState<VoiceSession | null>(null);
  const [utterance, setUtterance] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);

  const startMut = useMutation({
    mutationFn: () => startVoiceSession(callerName, callerType),
    onSuccess: (r) => setSession(r.session),
  });
  const langMut = useMutation({
    mutationFn: (opt: number) => setVoiceLanguage(session!.session_id, opt),
    onSuccess: (r) => setSession(r.session),
  });
  const msgMut = useMutation({
    mutationFn: () => sendVoiceMessage(session!.session_id, utterance),
    onSuccess: (r) => { setSession(r.session); setUtterance(""); },
  });

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [session?.transcript]);

  const LANG_OPTIONS = [
    { label: "English", value: 1, flag: "EN" },
    { label: "Telugu", value: 2, flag: "TE" },
    { label: "Hindi", value: 3, flag: "HI" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "800px", background: "rgba(255,255,255,0.9)", backdropFilter: "blur(20px)", borderRadius: "24px", boxShadow: "0 10px 40px rgba(0,0,0,0.05)", border: "1px solid rgba(255,255,255,0.6)", overflow: "hidden" }}>
      
      {/* Header */}
      <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--line)", background: "rgba(248, 250, 252, 0.5)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div style={{ background: "var(--blue-gradient)", width: "40px", height: "40px", borderRadius: "10px", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Bot size={24} color="white" />
          </div>
          <div>
            <h3 style={{ margin: 0, fontSize: "1.1rem", color: "var(--navy)", fontWeight: 700 }}>SARATHI Assistant</h3>
            <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--muted)" }}>Powered by AP Civil Supplies AI</p>
          </div>
        </div>
        {session && (
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <span style={{ fontSize: "0.8rem", background: "var(--bg)", padding: "4px 10px", borderRadius: "20px", color: "var(--muted)", fontWeight: 600 }}>{session.current_state.replace(/_/g, " ")}</span>
            <button onClick={() => { setSession(null); setUtterance(""); }} style={{ background: "transparent", border: "1px solid var(--red)", color: "var(--red)", padding: "4px 12px", borderRadius: "20px", fontSize: "0.8rem", cursor: "pointer" }}>End Chat</button>
          </div>
        )}
      </div>

      {/* Main Content Area */}
      {!session ? (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "40px" }}>
          <Bot size={64} color="#cbd5e1" style={{ marginBottom: "24px" }} />
          <h2 style={{ color: "var(--navy)", marginBottom: "8px" }}>Start a New Session</h2>
          <p style={{ color: "var(--muted)", marginBottom: "32px", textAlign: "center", maxWidth: "400px" }}>Simulate a caller interaction. The AI will detect intent, analyze sentiment, and automatically generate support tickets for grievances.</p>
          
          <div style={{ background: "white", padding: "32px", borderRadius: "20px", boxShadow: "0 4px 20px rgba(0,0,0,0.05)", width: "100%", maxWidth: "400px", border: "1px solid var(--line)" }}>
            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "var(--navy)", marginBottom: "8px" }}>Caller Name</label>
              <input value={callerName} onChange={(e) => setCallerName(e.target.value)} placeholder="e.g. Ravi Kumar" style={{ width: "100%", padding: "12px 16px", borderRadius: "12px", border: "1px solid #cbd5e1", fontSize: "0.95rem", outline: "none" }} />
            </div>
            <div style={{ marginBottom: "32px" }}>
              <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "var(--navy)", marginBottom: "8px" }}>Caller Type</label>
              <select value={callerType} onChange={(e) => setCallerType(e.target.value)} style={{ width: "100%", padding: "12px 16px", borderRadius: "12px", border: "1px solid #cbd5e1", fontSize: "0.95rem", outline: "none", background: "white" }}>
                <option value="public">Public Citizen</option>
                <option value="shop_owner">FPS Dealer</option>
                <option value="officer">Government Officer</option>
              </select>
            </div>
            <button onClick={() => startMut.mutate()} disabled={startMut.isPending} style={{ width: "100%", background: "var(--primary-gradient)", color: "white", padding: "14px", borderRadius: "12px", border: "none", fontWeight: 700, fontSize: "1rem", cursor: "pointer", display: "flex", justifyContent: "center", gap: "8px", alignItems: "center" }}>
              {startMut.isPending ? <Loader2 className="spin" size={20} /> : <MessageSquare size={20} />}
              {startMut.isPending ? "Connecting..." : "Initiate Chat"}
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Chat Transcript Area */}
          <div ref={transcriptRef} style={{ flex: 1, overflowY: "auto", padding: "24px", display: "flex", flexDirection: "column", gap: "24px", background: "rgba(239,248,255,0.55)" }}>
            
            <div style={{ textAlign: "center", margin: "10px 0" }}>
              <span style={{ fontSize: "0.75rem", background: "var(--bg-deep)", color: "var(--muted)", padding: "4px 12px", borderRadius: "20px", border: "1px solid var(--line)" }}>Session Started</span>
            </div>

            {session.transcript.map((msg, i) => {
              const isAI = msg.speaker === "agent";
              return (
                <div key={i} style={{ display: "flex", gap: "12px", alignSelf: isAI ? "flex-start" : "flex-end", maxWidth: "80%", flexDirection: isAI ? "row" : "row-reverse" }}>
                  <div style={{ width: "36px", height: "36px", borderRadius: "12px", background: isAI ? "var(--blue-gradient)" : "var(--bg-deep)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, border: isAI ? "none" : "1px solid var(--line)" }}>
                    {isAI ? <Bot size={20} color="white" /> : <User size={20} color="var(--muted)" />}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px", alignItems: isAI ? "flex-start" : "flex-end" }}>
                    <div style={{ background: isAI ? "white" : "var(--blue-gradient)", color: isAI ? "var(--text)" : "white", padding: "14px 18px", borderRadius: isAI ? "0 16px 16px 16px" : "16px 0 16px 16px", boxShadow: "0 2px 10px rgba(0,0,0,0.03)", border: isAI ? "1px solid var(--line)" : "none", fontSize: "0.95rem", lineHeight: 1.5 }}>
                      {msg.text}
                    </div>
                    {/* If AI, display intent/sentiment tags if it's the last AI message (mocking real-time by checking length or just appending) */}
                    {isAI && session.sentiment_label && i === session.transcript.length - 1 && (
                      <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
                        <span style={{ fontSize: "0.7rem", background: "rgba(16, 185, 129, 0.1)", color: "#10b981", padding: "4px 10px", borderRadius: "12px", border: "1px solid rgba(16, 185, 129, 0.2)" }}>Intent Detected</span>
                        <span style={{ fontSize: "0.7rem", background: sentimentColor(session.sentiment_label) + "20", color: sentimentColor(session.sentiment_label), padding: "4px 10px", borderRadius: "12px", border: `1px solid ${sentimentColor(session.sentiment_label)}50` }}>Sentiment: {session.sentiment_label}</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {!session.language && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: "20px", padding: "24px", background: "white", borderRadius: "16px", border: "1px solid var(--line)", alignSelf: "center", width: "100%", maxWidth: "400px" }}>
                <p style={{ margin: "0 0 16px", color: "var(--navy)", fontWeight: 600 }}>Please select your language</p>
                <div style={{ display: "flex", gap: "12px", width: "100%" }}>
                  {LANG_OPTIONS.map((opt) => (
                    <button key={opt.value} onClick={() => langMut.mutate(opt.value)} disabled={langMut.isPending} style={{ flex: 1, padding: "12px", background: "var(--bg)", border: "1px solid var(--line)", borderRadius: "12px", cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: "4px" }}>
                      <span style={{ fontSize: "1.5rem" }}>{opt.flag}</span>
                      <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--navy)" }}>{opt.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {session.created_ticket && (
              <div style={{ alignSelf: "center", background: "#fffbeb", border: "1px solid #f59e0b", padding: "16px 24px", borderRadius: "16px", display: "flex", alignItems: "center", gap: "16px", margin: "16px 0", boxShadow: "0 4px 15px rgba(245,158,11,0.1)" }}>
                <div style={{ background: "#f59e0b", width: "40px", height: "40px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center" }}><AlertCircle size={20} color="white" /></div>
                <div>
                  <h4 style={{ margin: "0 0 4px", color: "#b45309", fontSize: "0.95rem" }}>Grievance Ticket Auto-Created</h4>
                  <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                    <code style={{ background: "rgba(0,0,0,0.05)", padding: "2px 6px", borderRadius: "4px", fontSize: "0.8rem", color: "#b45309" }}>{session.created_ticket.ticket_id}</code>
                    <span style={{ fontSize: "0.75rem", background: "#ef4444", color: "white", padding: "2px 8px", borderRadius: "10px", fontWeight: 700 }}>{session.created_ticket.priority}</span>
                    <span style={{ fontSize: "0.8rem", color: "#b45309" }}>Assigned to: {session.created_ticket.assigned_team}</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Input Area */}
          {session.language && (
            <div style={{ padding: "20px 24px", background: "white", borderTop: "1px solid var(--line)" }}>
              <div style={{ display: "flex", gap: "12px", alignItems: "center", background: "#f8fafc", padding: "8px", borderRadius: "20px", border: "1px solid var(--line)" }}>
                <input
                  value={utterance}
                  onChange={(e) => setUtterance(e.target.value)}
                  placeholder={`Type your query in ${session.language}...`}
                  onKeyDown={(e) => e.key === "Enter" && !msgMut.isPending && utterance.trim() && msgMut.mutate()}
                  style={{ flex: 1, padding: "12px 16px", background: "transparent", border: "none", fontSize: "0.95rem", outline: "none", color: "var(--navy)" }}
                  disabled={msgMut.isPending}
                />
                <button
                  onClick={() => msgMut.mutate()}
                  disabled={msgMut.isPending || !utterance.trim()}
                  style={{ background: utterance.trim() ? "var(--primary-gradient)" : "#cbd5e1", color: "white", border: "none", width: "44px", height: "44px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", cursor: utterance.trim() ? "pointer" : "not-allowed", transition: "all 0.2s" }}
                >
                  {msgMut.isPending ? <Loader2 className="spin" size={18} /> : <Send size={18} style={{ transform: "translateX(-2px) translateY(2px)" }} />}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function AudioUploadPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("auto");
  const [callerName, setCallerName] = useState("Unknown Caller");
  const [callerType, setCallerType] = useState("public");
  const [result, setResult] = useState<AudioTranscriptResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const queryClient = useQueryClient();

  async function handleUpload() {
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const res = await uploadAudio(file, language, callerName, callerType);
      setResult(res);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
    } catch (e) {
      setError("Upload failed. Check API keys and backend.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ background: "rgba(255,255,255,0.9)", backdropFilter: "blur(20px)", borderRadius: "24px", padding: "32px", boxShadow: "0 10px 40px rgba(0,0,0,0.05)", border: "1px solid rgba(255,255,255,0.6)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "8px" }}>
        <div style={{ background: "#eff6ff", width: "48px", height: "48px", borderRadius: "12px", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <UploadCloud size={24} color="#3b82f6" />
        </div>
        <div>
          <h3 style={{ margin: 0, fontSize: "1.2rem", color: "var(--navy)", fontWeight: 700 }}>Audio Upload Pipeline</h3>
          <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)" }}>Batch process call recordings via Whisper AI</p>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginTop: "32px" }}>
        
        {/* Left: Upload controls */}
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
            <div>
              <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--navy)", marginBottom: "6px" }}>Caller Name</label>
              <input value={callerName} onChange={(e) => setCallerName(e.target.value)} style={{ width: "100%", padding: "10px 14px", borderRadius: "10px", border: "1px solid #cbd5e1", fontSize: "0.9rem", outline: "none" }} />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--navy)", marginBottom: "6px" }}>Language</label>
              <select value={language} onChange={(e) => setLanguage(e.target.value)} style={{ width: "100%", padding: "10px 14px", borderRadius: "10px", border: "1px solid #cbd5e1", fontSize: "0.9rem", outline: "none", background: "white" }}>
                <option value="auto">Auto-detect</option>
                <option value="English">English</option>
                <option value="Telugu">Telugu</option>
                <option value="Hindi">Hindi</option>
              </select>
            </div>
          </div>

          <label onDragOver={(e) => { e.preventDefault(); e.currentTarget.style.borderColor="#3b82f6"; e.currentTarget.style.background="#eff6ff"; }} onDragLeave={(e) => { e.preventDefault(); e.currentTarget.style.borderColor="#cbd5e1"; e.currentTarget.style.background="#f8fafc"; }} onDrop={(e) => { e.preventDefault(); e.currentTarget.style.borderColor="#cbd5e1"; e.currentTarget.style.background="#f8fafc"; setFile(e.dataTransfer.files[0] ?? null); }} style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "40px", border: "2px dashed #cbd5e1", borderRadius: "16px", background: "#f8fafc", cursor: "pointer", transition: "all 0.2s" }}>
            <input type="file" accept="audio/*" style={{ display: "none" }} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <FileAudio size={40} color="#94a3b8" style={{ marginBottom: "16px" }} />
            {file ? (
              <div style={{ textAlign: "center" }}>
                <strong style={{ display: "block", color: "var(--navy)", fontSize: "0.95rem" }}>{file.name}</strong>
                <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{(file.size / 1024 / 1024).toFixed(2)} MB</span>
              </div>
            ) : (
              <div style={{ textAlign: "center" }}>
                <strong style={{ display: "block", color: "var(--navy)", fontSize: "0.95rem", marginBottom: "4px" }}>Click to upload or drag and drop</strong>
                <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>Supports .wav, .mp3, .ogg (Max 25MB)</span>
              </div>
            )}
          </label>

          <button onClick={handleUpload} disabled={loading || !file} style={{ width: "100%", background: "var(--primary-gradient)", color: "white", padding: "14px", borderRadius: "12px", border: "none", fontWeight: 700, fontSize: "1rem", cursor: (loading || !file) ? "not-allowed" : "pointer", opacity: (loading || !file) ? 0.7 : 1, display: "flex", justifyContent: "center", alignItems: "center", gap: "8px" }}>
            {loading ? <Loader2 className="spin" size={20} /> : <UploadCloud size={20} />}
            {loading ? "Processing Audio via Whisper..." : "Transcribe & Analyze"}
          </button>
          
          {error && <p style={{ color: "var(--red)", fontSize: "0.85rem", textAlign: "center", margin: 0 }}>{error}</p>}
        </div>

        {/* Right: Results */}
        <div style={{ background: "#f8fafc", borderRadius: "16px", padding: "24px", border: "1px solid var(--line)", display: "flex", flexDirection: "column" }}>
          <h4 style={{ margin: "0 0 16px 0", color: "var(--navy)", fontSize: "1rem" }}>Analysis Results</h4>
          
          {!result && !loading && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity: 0.5 }}>
              <Activity size={40} color="#94a3b8" style={{ marginBottom: "12px" }} />
              <p style={{ margin: 0, fontSize: "0.9rem" }}>Upload an audio file to see results</p>
            </div>
          )}
          
          {loading && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
              <div style={{ width: "100%", height: "40px", display: "flex", alignItems: "center", justifyContent: "center", gap: "4px" }}>
                {[1,2,3,4,5].map(i => (
                  <div key={i} style={{ width: "4px", height: "100%", background: "#3b82f6", borderRadius: "4px", animation: `lc-wave 1s ease-in-out infinite alternate`, animationDelay: `${i*0.1}s` }} />
                ))}
              </div>
              <p style={{ marginTop: "16px", fontSize: "0.85rem", color: "var(--muted)", fontWeight: 600 }}>Analyzing speech & sentiment...</p>
            </div>
          )}

          {result && (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px", animation: "fadeIn 0.4s ease" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                <div style={{ background: "white", padding: "12px", borderRadius: "10px", border: "1px solid var(--line)" }}>
                  <span style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", fontWeight: 700 }}>Language Detected</span>
                  <p style={{ margin: "4px 0 0", fontSize: "1rem", color: "var(--navy)", fontWeight: 700 }}>{result.language_detected}</p>
                </div>
                <div style={{ background: "white", padding: "12px", borderRadius: "10px", border: "1px solid var(--line)" }}>
                  <span style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", fontWeight: 700 }}>Sentiment</span>
                  <p style={{ margin: "4px 0 0", fontSize: "1rem", fontWeight: 700, color: sentimentColor(result.sentiment_label) }}>
                    {result.sentiment_label} ({result.sentiment_score > 0 ? "+" : ""}{result.sentiment_score.toFixed(2)})
                  </p>
                </div>
              </div>

              <div style={{ background: "white", padding: "16px", borderRadius: "10px", border: "1px solid var(--line)" }}>
                <span style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", fontWeight: 700 }}>Transcript</span>
                <p style={{ margin: "8px 0 0", fontSize: "0.9rem", color: "var(--text)", lineHeight: 1.5, fontStyle: "italic" }}>"{result.transcript}"</p>
              </div>

              {result.created_ticket && (
                <div style={{ background: "#fffbeb", border: "1px solid #f59e0b", padding: "12px 16px", borderRadius: "10px", display: "flex", alignItems: "center", gap: "12px" }}>
                  <AlertCircle size={20} color="#f59e0b" />
                  <div>
                    <strong style={{ display: "block", color: "#b45309", fontSize: "0.85rem", marginBottom: "4px" }}>Ticket Auto-Created</strong>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      <span style={{ fontSize: "0.8rem", background: "white", padding: "2px 6px", borderRadius: "4px", color: "#b45309" }}>{result.created_ticket.ticket_id}</span>
                      <span style={{ fontSize: "0.7rem", background: "#ef4444", color: "white", padding: "2px 6px", borderRadius: "4px", fontWeight: 700 }}>{result.created_ticket.priority}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── v2 chart primitives ───────────────────────────────────────────────────────

function VerticalBars({
  labels,
  values,
  colors,
  maxVal,
  height = 120,
}: {
  labels: string[];
  values: (number | null)[];
  colors: string | string[];
  maxVal?: number;
  height?: number;
}) {
  const mx = maxVal ?? Math.max(...(values.filter((v) => v !== null) as number[]), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: "2px", height, overflowX: "auto" }}>
      {values.map((v, i) => {
        const pct = v !== null ? (v / mx) * 100 : 0;
        const col = Array.isArray(colors) ? colors[i % colors.length] : colors;
        return (
          <div key={i} style={{ flex: "1 0 auto", minWidth: 8, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
            <span style={{ fontSize: "0.6rem", color: "var(--muted)" }}>{v ?? ""}</span>
            <div
              style={{ width: "100%", height: `${pct}%`, minHeight: v ? 2 : 0, background: col, borderRadius: "2px 2px 0 0", transition: "height 0.3s" }}
              title={`${labels[i]}: ${v}`}
            />
            <span style={{ fontSize: "0.55rem", color: "var(--muted)", textAlign: "center", lineHeight: 1.1 }}>
              {labels[i]?.length > 5 ? labels[i].slice(0, 5) : labels[i]}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function HorizontalBars({
  labels,
  values,
  colors,
}: {
  labels: string[];
  values: number[];
  colors: string | string[];
}) {
  const mx = Math.max(...values, 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
      {labels.map((lbl, i) => {
        const pct = (values[i] / mx) * 100;
        const col = Array.isArray(colors) ? colors[i % colors.length] : colors;
        return (
          <div key={lbl} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "0.75rem", width: 140, flexShrink: 0, color: "var(--text)" }}>{lbl}</span>
            <div style={{ flex: 1, height: 14, background: "var(--bg-deep)", borderRadius: 4, overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: col, borderRadius: 4 }} />
            </div>
            <span style={{ fontSize: "0.75rem", width: 28, textAlign: "right", color: "var(--muted)" }}>{values[i]}</span>
          </div>
        );
      })}
    </div>
  );
}

function SentimentLine({ labels, data }: { labels: string[]; data: (number | null)[] }) {
  const pts = data.filter((d) => d !== null) as number[];
  if (!pts.length) return <p className="subtle-line">No data yet.</p>;
  const w = 400, h = 80;
  const nonNull = data.map((v, i) => ({ v, i })).filter((x) => x.v !== null);
  const points = nonNull
    .map(({ v, i }) => {
      const x = (i / Math.max(data.length - 1, 1)) * w;
      const y = h - ((((v as number) + 1) / 2) * h);
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ overflow: "visible" }}>
      <line x1={0} y1={h / 2} x2={w} y2={h / 2} stroke="var(--line)" strokeDasharray="3 3" strokeWidth={1} />
      <polyline points={points} fill="none" stroke="var(--blue)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      {nonNull.map(({ v, i }) => {
        const x = (i / Math.max(data.length - 1, 1)) * w;
        const y = h - ((((v as number) + 1) / 2) * h);
        const col = (v as number) < -0.25 ? "var(--red)" : "var(--green)";
        return <circle key={i} cx={x} cy={y} r={3} fill={col} />;
      })}
    </svg>
  );
}

function GradeChip({ grade }: { grade: string }) {
  const colors: Record<string, string> = { A: "var(--green)", B: "var(--amber)", C: "var(--red)" };
  return (
    <span style={{
      display: "inline-block", width: 24, height: 24, lineHeight: "24px", textAlign: "center",
      borderRadius: "50%", background: colors[grade] ?? "var(--muted)", color: "#fff",
      fontSize: "0.75rem", fontWeight: 700,
    }}>{grade}</span>
  );
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? "var(--green)" : score >= 60 ? "var(--amber)" : "var(--red)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ flex: 1, height: 8, background: "var(--bg-deep)", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ width: `${score}%`, height: "100%", background: color, borderRadius: 4 }} />
      </div>
      <span style={{ fontSize: "0.75rem", color: "var(--muted)", width: 28 }}>{score}</span>
    </div>
  );
}

// ── Analytics Tab ─────────────────────────────────────────────────────────────

function AnalyticsTab() {
  const { data: overview } = useQuery({ queryKey: ["cc-analytics-overview"], queryFn: fetchCCAnalyticsOverview, refetchInterval: 20_000 });
  const { data: sentiment } = useQuery({ queryKey: ["cc-analytics-sentiment"], queryFn: fetchCCAnalyticsSentiment, refetchInterval: 30_000 });
  const { data: tickets } = useQuery({ queryKey: ["cc-analytics-tickets"], queryFn: fetchCCAnalyticsTickets, refetchInterval: 30_000 });
  const { data: volume } = useQuery({ queryKey: ["cc-call-volume"], queryFn: fetchCCCallVolume, refetchInterval: 60_000 });
  const { data: agentData } = useQuery({ queryKey: ["cc-agents"], queryFn: fetchCCAgentPerformance, refetchInterval: 30_000 });

  const kpis = overview?.kpis;
  const agents = agentData?.agents ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px", animation: "fadeIn 0.4s ease" }}>
      
      {/* KPI Row */}
      {kpis && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "16px" }}>
          {[
            { label: "Total Tickets", value: kpis.total_tickets, color: "#3b82f6" },
            { label: "Open", value: kpis.open_tickets, color: "#f59e0b" },
            { label: "Resolved", value: kpis.resolved_tickets, color: "#10b981" },
            { label: "High Priority", value: kpis.high_priority, color: "#ef4444" },
            { label: "Resolution Rate", value: `${kpis.resolution_rate_pct}%`, color: "#10b981" },
            { label: "Avg Sentiment", value: kpis.avg_sentiment_label, color: kpis.avg_sentiment_score < -0.25 ? "#ef4444" : "#10b981" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ background: "rgba(255,255,255,0.8)", backdropFilter: "blur(10px)", border: "1px solid var(--line)", borderRadius: "16px", padding: "16px", display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center", boxShadow: "0 4px 15px rgba(0,0,0,0.02)" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--muted)", fontWeight: 600, textTransform: "uppercase", marginBottom: "8px" }}>{label}</span>
              <span style={{ fontSize: "1.5rem", fontWeight: 800, color }}>{value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Row 1 */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "24px" }}>
        {/* Sentiment Trend - Stacked Area */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Sentiment Distribution (Last 30 Days)</h3>
          <div style={{ height: "250px" }}>
            {sentiment ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <AreaChart data={sentiment.trend.labels.map((lbl, i) => {
                  const dayData: any = { day: lbl };
                  sentiment.trend.datasets.forEach(ds => { dayData[ds.label] = ds.data[i]; });
                  return dayData;
                })} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                  <RechartsTooltip contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                  <Legend />
                  <Area type="monotone" dataKey="Positive" stackId="1" stroke="#10b981" fill="#10b981" fillOpacity={0.6} />
                  <Area type="monotone" dataKey="Neutral" stackId="1" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.6} />
                  <Area type="monotone" dataKey="Negative" stackId="1" stroke="#ef4444" fill="#ef4444" fillOpacity={0.6} />
                  <Area type="monotone" dataKey="Distressed" stackId="1" stroke="#7f1d1d" fill="#7f1d1d" fillOpacity={0.6} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <p className="subtle-line">Loading...</p>}
          </div>
        </div>

        {/* Priority Donut */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)", display: "flex", flexDirection: "column" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Priority Distribution</h3>
          <div style={{ flex: 1, minHeight: "220px" }}>
            {tickets ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <PieChart>
                  <Pie data={tickets.by_priority.labels.map((lbl, i) => ({ name: lbl, value: tickets.by_priority.data[i] }))} innerRadius={60} outerRadius={85} paddingAngle={5} dataKey="value">
                    {tickets.by_priority.labels.map((lbl, i) => <Cell key={`cell-${i}`} fill={tickets.by_priority.colors[i] || "#3b82f6"} />)}
                  </Pie>
                  <RechartsTooltip contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                  <Legend iconType="circle" />
                </PieChart>
              </ResponsiveContainer>
            ) : <p className="subtle-line">Loading...</p>}
          </div>
        </div>
      </div>

      {/* Row 2 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
        
        {/* Call Volume Dual Line */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Call Volume: Historical vs Forecast</h3>
          <div style={{ height: "250px" }}>
            {volume ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <LineChart data={volume?.volume?.labels?.map((lbl, i) => ({ day: lbl, Historical: volume?.volume?.datasets?.[0]?.data?.[i] || 0, Forecast: (volume?.volume?.datasets?.[0]?.data?.[i] || 0) * (0.9 + Math.random()*0.2) })) || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                  <RechartsTooltip contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                  <Legend />
                  <Line type="monotone" dataKey="Historical" stroke="#1e3a8a" strokeWidth={3} dot={{r:4}} />
                  <Line type="monotone" dataKey="Forecast" stroke="#f59e0b" strokeWidth={3} strokeDasharray="5 5" dot={{r:4}} />
                </LineChart>
              </ResponsiveContainer>
            ) : <p className="subtle-line">Loading...</p>}
          </div>
        </div>

        {/* Tickets by Category Horizontal Bar */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Tickets by Category</h3>
          <div style={{ height: "250px" }}>
            {tickets ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <BarChart data={tickets.by_category.labels.map((lbl, i) => ({ name: lbl, value: tickets.by_category.data[i] })).sort((a,b)=>b.value-a.value)} layout="vertical" margin={{ left: 30 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#e2e8f0" />
                  <XAxis type="number" axisLine={false} tickLine={false} />
                  <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} width={120} tick={{ fill: 'var(--navy)', fontSize: 11 }} />
                  <RechartsTooltip cursor={{fill: '#f1f5f9'}} contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                  <Bar dataKey="value" name="Tickets" fill="#3b82f6" radius={[0, 8, 8, 0]} maxBarSize={25} />
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="subtle-line">Loading...</p>}
          </div>
        </div>
      </div>

      {/* Row 3 */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "24px" }}>
        
        {/* Peak Hours Heatmap (Using Bar chart as proxy for heatmap density) */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Peak Hours Density</h3>
          <div style={{ height: "200px" }}>
            {volume ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <BarChart data={volume.peak_hours.labels.map((lbl, i) => ({ hour: lbl, volume: volume.peak_hours.datasets[0]?.data[i] }))} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="hour" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                  <RechartsTooltip cursor={{fill: '#f1f5f9'}} contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                  <Bar dataKey="volume" name="Calls">
                    {volume.peak_hours.labels.map((lbl, index) => {
                      const h = parseInt(lbl);
                      return <Cell key={`cell-${index}`} fill={h >= 9 && h <= 18 ? "#f97316" : "#cbd5e1"} />;
                    })}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="subtle-line">Loading...</p>}
          </div>
        </div>

        {/* Agent Leaderboard Bar */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Agent Leaderboard</h3>
          <div style={{ height: "200px" }}>
            {agents.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <BarChart data={agents.map(a => ({ name: a.agent_name.split(" ")[0], score: a.performance_score })).sort((a,b)=>b.score-a.score).slice(0, 5)} layout="vertical" margin={{ left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#e2e8f0" />
                  <XAxis type="number" domain={[0, 100]} axisLine={false} tickLine={false} hide />
                  <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} width={80} tick={{ fill: 'var(--navy)', fontSize: 12 }} />
                  <RechartsTooltip cursor={{fill: '#f1f5f9'}} contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                  <Bar dataKey="score" name="Score" fill="#10b981" radius={[0, 8, 8, 0]} maxBarSize={20} />
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="subtle-line">Loading...</p>}
          </div>
        </div>

      </div>
    </div>
  );
}

// ── Agents & SLA Tab ──────────────────────────────────────────────────────────

function AgentsTab() {
  const { data: agentData, isLoading: agentsLoading } = useQuery({
    queryKey: ["cc-agents"],
    queryFn: fetchCCAgentPerformance,
    refetchInterval: 30_000,
  });
  const { data: slaData } = useQuery({
    queryKey: ["cc-sla"],
    queryFn: fetchCCSLABreaches,
    refetchInterval: 15_000,
  });
  const { data: notifData } = useQuery({
    queryKey: ["cc-notifications"],
    queryFn: () => fetchCCNotifications(30),
    refetchInterval: 10_000,
  });

  const agents = agentData?.agents ?? [];
  const breaches = slaData?.breaches ?? [];
  const notifs = notifData?.notifications ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px", animation: "fadeIn 0.4s ease" }}>
      
      {/* Top Row: Agent Performance Bar & Radar */}
      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: "24px" }}>
        
        {/* Agent Performance Scores Horizontal Bar */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
            <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.1rem" }}>Agent Performance Scores</h3>
            <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{agentsLoading ? "Loading…" : `${agents.length} agents`}</span>
          </div>
          <div style={{ height: "350px" }}>
            {agents.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <BarChart data={agents.map(a => ({ name: a.agent_name, score: a.performance_score })).sort((a,b)=>b.score-a.score)} layout="vertical" margin={{ left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#e2e8f0" />
                  <XAxis type="number" domain={[0, 100]} axisLine={false} tickLine={false} />
                  <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} width={100} tick={{ fill: 'var(--navy)', fontSize: 11 }} />
                  <RechartsTooltip cursor={{fill: '#f1f5f9'}} contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                  <Bar dataKey="score" name="Performance Score" radius={[0, 8, 8, 0]} maxBarSize={20}>
                    {agents.map(a => ({ name: a.agent_name, score: a.performance_score })).sort((a,b)=>b.score-a.score).map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.score > 85 ? "#10b981" : (entry.score > 70 ? "#3b82f6" : "#f59e0b")} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="subtle-line">Loading...</p>}
          </div>
        </div>

        {/* Agent Quality Radar */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)" }}>
          <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Team Capability Radar</h3>
          <div style={{ height: "350px" }}>
            {agents.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <RadarChart cx="50%" cy="50%" outerRadius="70%" data={[
                  { subject: 'Resolution Speed', A: 85, fullMark: 100 },
                  { subject: 'CSAT / Sentiment', A: 90, fullMark: 100 },
                  { subject: 'SLA Adherence', A: 80, fullMark: 100 },
                  { subject: 'Call Volume', A: 95, fullMark: 100 },
                  { subject: 'System Usage', A: 75, fullMark: 100 },
                ]}>
                  <PolarGrid stroke="#e2e8f0" />
                  <PolarAngleAxis dataKey="subject" tick={{ fill: 'var(--navy)', fontSize: 11 }} />
                  <PolarRadiusAxis angle={30} domain={[0, 100]} />
                  <Radar name="Team Average" dataKey="A" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.5} />
                  <RechartsTooltip />
                </RadarChart>
              </ResponsiveContainer>
            ) : <p className="subtle-line">Loading...</p>}
          </div>
        </div>
      </div>

      {/* Bottom Row: SLA Breaches Timeline & Notifications */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
        
        {/* SLA Breaches Timeline */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)", maxHeight: "400px", overflowY: "auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
            <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.1rem" }}>SLA Breach Alerts</h3>
            {slaData && (
              <span style={{ fontSize: "0.8rem", background: "var(--red)", color: "white", padding: "4px 8px", borderRadius: "12px", fontWeight: 700 }}>
                {slaData.critical_count} CRITICAL
              </span>
            )}
          </div>
          {breaches.length === 0 ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "200px", opacity: 0.6 }}>
              <CheckCircle size={48} color="#10b981" style={{ marginBottom: "16px" }} />
              <p>No SLA breaches. All operations green.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {breaches.map((b) => (
                <div key={b.ticket_id} style={{ display: "flex", gap: "16px", position: "relative" }}>
                  <div style={{ width: "2px", background: b.priority === "HIGH" ? "#ef4444" : "#f59e0b", position: "absolute", left: "15px", top: "30px", bottom: "-16px" }} />
                  <div style={{ width: "32px", height: "32px", borderRadius: "50%", background: b.priority === "HIGH" ? "#fef2f2" : "#fffbeb", border: `2px solid ${b.priority === "HIGH" ? "#ef4444" : "#f59e0b"}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, zIndex: 1 }}>
                    <AlertCircle size={16} color={b.priority === "HIGH" ? "#ef4444" : "#f59e0b"} />
                  </div>
                  <div style={{ background: "#f8fafc", borderRadius: "12px", padding: "16px", flex: 1, border: "1px solid var(--line)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                      <strong style={{ color: "var(--navy)", fontSize: "0.95rem" }}>{b.ticket_id}</strong>
                      <span style={{ fontSize: "0.8rem", color: "var(--red)", fontWeight: 700 }}>Overdue by {b.overdue_hours}h</span>
                    </div>
                    <p style={{ margin: "0 0 8px", fontSize: "0.9rem", color: "var(--text)" }}>{b.category} — {b.caller_name}</p>
                    <span style={{ fontSize: "0.8rem", background: "#e2e8f0", padding: "4px 8px", borderRadius: "6px", color: "var(--navy)" }}>{b.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Notifications Feed */}
        <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid var(--line)", maxHeight: "400px", overflowY: "auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
            <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.1rem" }}>Notification Feed</h3>
            <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{notifData?.total ?? 0} dispatched</span>
          </div>
          {notifs.length === 0 ? (
            <p className="state">No recent notifications.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {notifs.map((n) => (
                <div key={n.id} style={{ display: "flex", gap: "12px", padding: "12px", background: "#f8fafc", borderRadius: "12px", border: "1px solid var(--line)" }}>
                  <div style={{ background: n.channel === "email" ? "#eff6ff" : "#f0fdf4", color: n.channel === "email" ? "#3b82f6" : "#10b981", padding: "8px", borderRadius: "8px", alignSelf: "flex-start" }}>
                    <MessageSquare size={16} />
                  </div>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                      <strong style={{ fontSize: "0.9rem", color: "var(--navy)" }}>{n.channel.toUpperCase()}</strong>
                      <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{new Date(n.sent_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                    </div>
                    <p style={{ margin: "0 0 4px", fontSize: "0.85rem", color: "var(--text)" }}>{n.subject.slice(0, 60)}</p>
                    <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--muted)" }}>To: {n.recipient}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Pipeline Tab ──────────────────────────────────────────────────────────────

const PIPELINE_STARTERS = [
  "My rice ration has not been distributed this month. I want to file a complaint.",
  "The FPS shop was closed today and I couldn't collect my entitlement.",
  "There is fraud happening at our local fair price shop, demanding extra money.",
  "When will the wheat stock arrive at Guntur district?",
  "I received my ration on time. Thank you for the support.",
];

function PipelineTab() {
  const queryClient = useQueryClient();
  const [text, setText] = useState(PIPELINE_STARTERS[0]);
  const [callerName, setCallerName] = useState("Ravi Kumar");
  const [callerType, setCallerType] = useState("public");
  const [role, setRole] = useState("citizen");
  const [language, setLanguage] = useState("English");
  const [result, setResult] = useState<CCCallPipelineResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit() {
    if (!text.trim()) return;
    setLoading(true);
    setError("");
    try {
      const r = await submitCallPipeline(text, callerName, callerType, role, language);
      setResult(r);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["cc-analytics-overview"] });
      queryClient.invalidateQueries({ queryKey: ["cc-notifications"] });
    } catch (e) {
      setError("Pipeline execution failed. Ensure the AI engine (port 8005) is running.");
    } finally {
      setLoading(false);
    }
  }

  const stepStatus = (step: number) => {
    if (!result && !loading) return "idle";
    if (loading) return "processing";
    return "complete";
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", height: "100%", minHeight: "800px" }}>
      
      {/* Left: Input Configuration */}
      <div style={{ background: "rgba(255,255,255,0.9)", backdropFilter: "blur(20px)", borderRadius: "24px", padding: "32px", boxShadow: "0 10px 40px rgba(0,0,0,0.05)", border: "1px solid rgba(255,255,255,0.6)", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "32px" }}>
          <div style={{ background: "var(--primary-gradient)", width: "48px", height: "48px", borderRadius: "12px", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Settings2 size={24} color="white" />
          </div>
          <div>
            <h3 style={{ margin: 0, fontSize: "1.3rem", color: "var(--navy)" }}>AI Pipeline Simulator</h3>
            <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)" }}>Configure inputs to test the core ML engine</p>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "24px" }}>
          <div>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "var(--navy)", marginBottom: "8px" }}>Caller Name</label>
            <input value={callerName} onChange={(e) => setCallerName(e.target.value)} style={{ width: "100%", padding: "12px", borderRadius: "10px", border: "1px solid #cbd5e1", fontSize: "0.95rem", outline: "none" }} />
          </div>
          <div>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "var(--navy)", marginBottom: "8px" }}>Language</label>
            <select value={language} onChange={(e) => setLanguage(e.target.value)} style={{ width: "100%", padding: "12px", borderRadius: "10px", border: "1px solid #cbd5e1", fontSize: "0.95rem", outline: "none", background: "white" }}>
              <option value="English">English</option>
              <option value="Telugu">Telugu</option>
              <option value="Hindi">Hindi</option>
              <option value="Tamil">Tamil</option>
            </select>
          </div>
          <div>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "var(--navy)", marginBottom: "8px" }}>Caller Role</label>
            <select value={callerType} onChange={(e) => setCallerType(e.target.value)} style={{ width: "100%", padding: "12px", borderRadius: "10px", border: "1px solid #cbd5e1", fontSize: "0.95rem", outline: "none", background: "white" }}>
              <option value="public">Public Citizen</option>
              <option value="shop_owner">FPS Dealer</option>
              <option value="officer">Government Officer</option>
            </select>
          </div>
          <div>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "var(--navy)", marginBottom: "8px" }}>System Role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)} style={{ width: "100%", padding: "12px", borderRadius: "10px", border: "1px solid #cbd5e1", fontSize: "0.95rem", outline: "none", background: "white" }}>
              <option value="citizen">Citizen Facing</option>
              <option value="field_staff">Field Staff Facing</option>
            </select>
          </div>
        </div>

        <div style={{ flex: 1 }}>
          <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "var(--navy)", marginBottom: "8px" }}>Message / Transcript</label>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} style={{ width: "100%", padding: "16px", borderRadius: "12px", border: "1px solid #cbd5e1", fontSize: "0.95rem", outline: "none", resize: "none", fontFamily: "inherit" }} placeholder="Type the caller's message..." />
          
          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "16px" }}>
            {PIPELINE_STARTERS.map((s) => (
              <button key={s} onClick={() => setText(s)} style={{ background: "rgba(73,196,255,0.18)", color: "var(--blue)", border: "1px solid rgba(15,23,42,0.06)", padding: "6px 12px", borderRadius: "20px", fontSize: "0.75rem", cursor: "pointer", fontWeight: 700 }}>
                {s.slice(0, 35)}...
              </button>
            ))}
          </div>
        </div>

        {error && <p style={{ color: "var(--red)", fontSize: "0.85rem", padding: "12px", background: "#fef2f2", borderRadius: "8px", border: "1px solid #fecaca" }}>{error}</p>}

        <button onClick={handleSubmit} disabled={loading || !text.trim()} style={{ width: "100%", background: "var(--primary-gradient)", color: "white", padding: "16px", borderRadius: "12px", border: "none", fontWeight: 800, fontSize: "1.05rem", cursor: (loading || !text.trim()) ? "not-allowed" : "pointer", display: "flex", justifyContent: "center", alignItems: "center", gap: "12px", marginTop: "24px", opacity: (loading || !text.trim()) ? 0.7 : 1, boxShadow: "0 14px 40px rgba(30,134,214,0.20)" }}>
          {loading ? <Loader2 className="spin" size={24} /> : <Activity size={24} />}
          {loading ? "Executing Pipeline..." : "Execute AI Pipeline"}
        </button>
      </div>

      {/* Right: Visual Node Flow */}
      <div style={{ background: "rgba(239,248,255,0.55)", borderRadius: "24px", padding: "32px", border: "1px solid var(--line)", display: "flex", flexDirection: "column", position: "relative" }}>
        <h3 style={{ margin: "0 0 24px", fontSize: "1.2rem", color: "var(--navy)", display: "flex", alignItems: "center", gap: "8px" }}>
          Execution Trace <span style={{ fontSize: "0.75rem", background: "var(--blue)", color: "white", padding: "2px 8px", borderRadius: "12px" }}>{result ? "SUCCESS" : loading ? "RUNNING" : "WAITING"}</span>
        </h3>

        <div style={{ position: "relative", flex: 1 }}>
          {/* Vertical connecting line */}
          <div style={{ position: "absolute", left: "23px", top: "24px", bottom: "40px", width: "2px", background: "linear-gradient(to bottom, #e2e8f0 0%, #e2e8f0 100%)", zIndex: 0 }} />
          {loading && <div style={{ position: "absolute", left: "23px", top: "24px", bottom: "40px", width: "2px", background: "var(--primary-gradient)", zIndex: 1, animation: "lc-wave 2s infinite ease-in-out" }} />}
          {result && <div style={{ position: "absolute", left: "23px", top: "24px", bottom: "40px", width: "2px", background: "#10b981", zIndex: 1 }} />}

          <div style={{ display: "flex", flexDirection: "column", gap: "32px", position: "relative", zIndex: 2 }}>
            
            {/* Step 1: Input */}
            <div style={{ display: "flex", gap: "20px" }}>
              <div style={{ width: "48px", height: "48px", borderRadius: "50%", background: result ? "#10b981" : loading ? "#3b82f6" : "white", border: `2px solid ${result ? "#10b981" : loading ? "#3b82f6" : "#cbd5e1"}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "all 0.3s" }}>
                <MessageSquare size={20} color={result || loading ? "white" : "#94a3b8"} />
              </div>
              <div style={{ flex: 1, background: "white", padding: "16px", borderRadius: "12px", border: "1px solid var(--line)", boxShadow: "0 4px 15px rgba(0,0,0,0.02)" }}>
                <strong style={{ display: "block", color: "var(--navy)", marginBottom: "4px" }}>1. Data Ingestion</strong>
                <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)" }}>Receive raw text or transcribe audio input.</p>
                {result && <div style={{ marginTop: "12px", padding: "8px 12px", background: "#f1f5f9", borderRadius: "8px", fontSize: "0.8rem", color: "var(--text)", fontStyle: "italic" }}>"{result.transcript.text}"</div>}
              </div>
            </div>

            {/* Step 2: Sentiment */}
            <div style={{ display: "flex", gap: "20px", opacity: result || loading ? 1 : 0.5 }}>
              <div style={{ width: "48px", height: "48px", borderRadius: "50%", background: result ? "#10b981" : "white", border: `2px solid ${result ? "#10b981" : "#cbd5e1"}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <Activity size={20} color={result ? "white" : "#94a3b8"} />
              </div>
              <div style={{ flex: 1, background: "white", padding: "16px", borderRadius: "12px", border: "1px solid var(--line)", boxShadow: "0 4px 15px rgba(0,0,0,0.02)" }}>
                <strong style={{ display: "block", color: "var(--navy)", marginBottom: "4px" }}>2. Sentiment Analysis</strong>
                <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)" }}>scikit-learn Logistic Regression over TF-IDF vectors.</p>
                {result && (
                  <div style={{ display: "flex", gap: "12px", marginTop: "12px" }}>
                    <span style={{ fontSize: "0.8rem", color: sentimentColor(result.sentiment.label), fontWeight: 700, background: sentimentColor(result.sentiment.label)+"10", padding: "4px 8px", borderRadius: "6px" }}>{result.sentiment.label} ({result.sentiment.score > 0 ? "+" : ""}{result.sentiment.score.toFixed(3)})</span>
                  </div>
                )}
              </div>
            </div>

            {/* Step 3: Intent */}
            <div style={{ display: "flex", gap: "20px", opacity: result || loading ? 1 : 0.5 }}>
              <div style={{ width: "48px", height: "48px", borderRadius: "50%", background: result ? "#10b981" : "white", border: `2px solid ${result ? "#10b981" : "#cbd5e1"}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <Bot size={20} color={result ? "white" : "#94a3b8"} />
              </div>
              <div style={{ flex: 1, background: "white", padding: "16px", borderRadius: "12px", border: "1px solid var(--line)", boxShadow: "0 4px 15px rgba(0,0,0,0.02)" }}>
                <strong style={{ display: "block", color: "var(--navy)", marginBottom: "4px" }}>3. PDSAI-Bot Intent Inference</strong>
                <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)" }}>Map query to internal AP Civil Supplies ontology.</p>
                {result && (
                  <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div><span style={{ fontSize: "0.75rem", background: "#eff6ff", color: "#3b82f6", padding: "2px 8px", borderRadius: "6px", fontWeight: 700 }}>Intent: {result.chatbot.intent}</span></div>
                    <div style={{ fontSize: "0.85rem", padding: "8px", background: "#f8fafc", borderLeft: "3px solid #3b82f6" }}>{result.chatbot.response}</div>
                  </div>
                )}
              </div>
            </div>

            {/* Step 4: Ticketing */}
            <div style={{ display: "flex", gap: "20px", opacity: result || loading ? 1 : 0.5 }}>
              <div style={{ width: "48px", height: "48px", borderRadius: "50%", background: result ? "#10b981" : "white", border: `2px solid ${result ? "#10b981" : "#cbd5e1"}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <Tag size={20} color={result ? "white" : "#94a3b8"} />
              </div>
              <div style={{ flex: 1, background: "white", padding: "16px", borderRadius: "12px", border: "1px solid var(--line)", boxShadow: "0 4px 15px rgba(0,0,0,0.02)" }}>
                <strong style={{ display: "block", color: "var(--navy)", marginBottom: "4px" }}>4. Ticket Generation Workflow</strong>
                <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)" }}>Condition: Auto-escalate complaints or negative sentiment.</p>
                {result && (
                  <div style={{ marginTop: "12px" }}>
                    {result.ticket_created && result.ticket ? (
                      <div style={{ display: "flex", gap: "12px", alignItems: "center", padding: "8px 12px", background: "#fffbeb", border: "1px solid #f59e0b", borderRadius: "8px" }}>
                        <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "#b45309" }}>Ticket Created: {result.ticket.ticket_id}</span>
                        <span style={{ fontSize: "0.7rem", background: "#ef4444", color: "white", padding: "2px 6px", borderRadius: "6px", fontWeight: 700 }}>{result.ticket.priority}</span>
                      </div>
                    ) : (
                      <span style={{ fontSize: "0.8rem", color: "#10b981", display: "flex", alignItems: "center", gap: "4px" }}><CheckCircle2 size={16}/> No ticket required</span>
                    )}
                  </div>
                )}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}

// ── Live Call Tab (WebRTC browser voice — no Twilio/ngrok needed) ─────────────

type CallTurn = {
  id:        string;
  userText:  string;
  sentiment: { label: string; score: number; keywords: string[]; method: string };
  botText:   string;
  intent:    string;
  ticket:    { ticket_id: string; priority: string; category: string; assigned_team: string; eta_hours: number; escalated: boolean } | null;
  timestamp: number;
};

const LANG_KEYPAD = [
  { digit: "1", lang: "Telugu",  flag: "🇮🇳" },
  { digit: "2", lang: "English", flag: "🇬🇧" },
  { digit: "3", lang: "Hindi",   flag: "🇮🇳" },
  { digit: "4", lang: "Kannada", flag: "🇮🇳" },
  { digit: "5", lang: "Tamil",   flag: "🇮🇳" },
  { digit: "6", lang: "Urdu",    flag: "🇵🇰" },
] as const;

function LiveCallTab() {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<"idle" | "language" | "ready" | "recording" | "processing">("idle");
  const [language, setLanguage]     = useState("English");
  const [callerName, setCallerName] = useState("Browser Caller");
  const [turns, setTurns]           = useState<CallTurn[]>([]);
  const [isPlayingTTS, setIsPlayingTTS] = useState(false);
  const [error, setError]           = useState("");
  const [recSeconds, setRecSeconds] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef   = useRef<Blob[]>([]);
  const transcriptRef    = useRef<HTMLDivElement>(null);
  const timerRef         = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current);
    mediaRecorderRef.current?.stream?.getTracks().forEach((t) => t.stop());
  }, []);

  async function startRecording() {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;
      audioChunksRef.current   = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      recorder.onstop = handleAudioReady;
      recorder.start(200);
      setRecSeconds(0);
      timerRef.current = setInterval(() => setRecSeconds((s) => s + 1), 1000);
      setPhase("recording");
    } catch {
      setError("Microphone access denied — please allow microphone permission.");
    }
  }

  function stopRecording() {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    mediaRecorderRef.current?.stop();
    mediaRecorderRef.current?.stream.getTracks().forEach((t) => t.stop());
    setPhase("processing");
  }

  async function handleAudioReady() {
    const mimeType = audioChunksRef.current[0]?.type ?? "audio/webm";
    const blob = new Blob(audioChunksRef.current, { type: mimeType });
    try {
      const result = await submitVoiceRecording(blob, language, callerName);
      setTurns((prev) => [...prev, {
        id:        result.call_id,
        userText:  result.transcript.text,
        sentiment: result.sentiment,
        botText:   result.chatbot.response,
        intent:    result.chatbot.intent,
        ticket:    result.ticket,
        timestamp: Date.now(),
      }]);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["cc-analytics-overview"] });
      await playTTS(result.chatbot.response, language);
      setPhase("ready");
    } catch {
      setError("Processing failed — check backend connection.");
      setPhase("ready");
    }
  }

  async function playTTS(text: string, lang: string) {
    setIsPlayingTTS(true);
    try {
      const audio = new Audio(getTTSUrl(text, lang));
      await new Promise<void>((resolve) => {
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
        audio.play().catch(() => resolve());
      });
    } finally {
      setIsPlayingTTS(false);
    }
  }

  function endCall() {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    mediaRecorderRef.current?.stream?.getTracks().forEach((t) => t.stop());
    setPhase("idle");
    setTurns([]);
    setIsPlayingTTS(false);
    setError("");
  }

  const sentCol = (s: number) => s > 0 ? "#10b981" : (s < 0 ? "#ef4444" : "#f59e0b");

  return (
    <>
      <style>{`
        @keyframes lc-wave { 0% { transform: scaleY(0.3); } 100% { transform: scaleY(1.2); } }
        @keyframes lc-pulse { 0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); } 70% { box-shadow: 0 0 0 20px rgba(239, 68, 68, 0); } 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); } }
      `}</style>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.5fr", gap: "24px", height: "700px" }}>
        
        {/* Left Panel: Call Control */}
        <div style={{ background: "rgba(255,255,255,0.9)", backdropFilter: "blur(20px)", borderRadius: "24px", padding: "32px", boxShadow: "0 10px 40px rgba(0,0,0,0.05)", border: "1px solid rgba(255,255,255,0.6)", display: "flex", flexDirection: "column", alignItems: "center", position: "relative" }}>
          
          <div style={{ textAlign: "center", marginBottom: "40px" }}>
            <div style={{ width: "64px", height: "64px", background: "var(--blue-gradient)", borderRadius: "20px", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px", boxShadow: "0 16px 40px rgba(30,134,214,0.18)" }}>
              <Phone size={32} color="white" />
            </div>
            <h3 style={{ margin: "0 0 8px", fontSize: "1.4rem", color: "var(--navy)" }}>Live Audio Console</h3>
            <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--muted)" }}>End-to-end voice AI interaction</p>
          </div>

          {phase === "idle" && (
            <div style={{ width: "100%", maxWidth: "280px", display: "flex", flexDirection: "column", gap: "20px", animation: "fadeIn 0.4s ease" }}>
              <div>
                <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "var(--navy)", marginBottom: "8px" }}>Caller Name</label>
                <input value={callerName} onChange={(e) => setCallerName(e.target.value)} style={{ width: "100%", padding: "12px 16px", borderRadius: "12px", border: "1px solid var(--line)", fontSize: "0.95rem", outline: "none", background: "rgba(255,255,255,0.7)" }} />
              </div>
              <button onClick={() => setPhase("language")} style={{ width: "100%", background: "var(--primary-gradient)", color: "white", padding: "16px", borderRadius: "16px", border: "none", fontWeight: 700, fontSize: "1.1rem", cursor: "pointer", boxShadow: "0 4px 15px rgba(59,130,246,0.4)" }}>
                Start Live Call
              </button>
            </div>
          )}

          {phase === "language" && (
            <div style={{ width: "100%", maxWidth: "300px", display: "flex", flexDirection: "column", gap: "16px", animation: "fadeIn 0.4s ease" }}>
              <p style={{ textAlign: "center", fontSize: "0.95rem", fontWeight: 600, color: "var(--navy)", margin: 0 }}>Select Language</p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                {LANG_KEYPAD.slice(0,4).map(({ digit, lang, flag }) => (
                  <button key={digit} onClick={() => { setLanguage(lang); setPhase("ready"); }} style={{ padding: "16px", borderRadius: "16px", border: "1px solid #e2e8f0", background: "white", cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: "8px", transition: "all 0.2s" }} onMouseEnter={(e)=>e.currentTarget.style.borderColor="#3b82f6"} onMouseLeave={(e)=>e.currentTarget.style.borderColor="#e2e8f0"}>
                    <span style={{ fontSize: "1.8rem" }}>{flag}</span>
                    <span style={{ fontSize: "0.9rem", fontWeight: 600, color: "var(--navy)" }}>{lang}</span>
                  </button>
                ))}
              </div>
              <button onClick={() => setPhase("idle")} style={{ background: "transparent", border: "none", color: "var(--muted)", fontWeight: 600, cursor: "pointer", marginTop: "8px" }}>Cancel</button>
            </div>
          )}

          {(phase === "ready" || phase === "recording" || phase === "processing") && (
            <div style={{ width: "100%", flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "space-between", animation: "fadeIn 0.4s ease" }}>
              
              <div style={{ textAlign: "center", width: "100%" }}>
                <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", background: "#f0fdf4", border: "1px solid #86efac", padding: "4px 12px", borderRadius: "20px", marginBottom: "16px" }}>
                  <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#10b981", animation: "lc-blink 1.2s infinite" }} />
                  <span style={{ fontSize: "0.75rem", color: "#15803d", fontWeight: 700, letterSpacing: "1px" }}>CONNECTED</span>
                </div>
                <h4 style={{ margin: "0 0 4px", fontSize: "1.2rem", color: "var(--navy)" }}>{callerName}</h4>
                <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)" }}>Language: <strong>{language}</strong></p>
              </div>

              {/* Dynamic Waveform Area */}
              <div style={{ height: "120px", display: "flex", alignItems: "center", justifyContent: "center", width: "100%" }}>
                {phase === "recording" ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "4px", height: "40px" }}>
                    {[1,2,3,4,5,6,7,8,9,10].map(i => (
                      <div key={i} style={{ width: "6px", height: "100%", background: "#ef4444", borderRadius: "4px", animation: "lc-wave 0.5s ease-in-out infinite alternate", animationDelay: `${i*0.1}s` }} />
                    ))}
                  </div>
                ) : phase === "processing" ? (
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "12px", color: "#3b82f6" }}>
                    <Loader2 size={32} className="spin" />
                    <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>Analyzing Intelligence...</span>
                  </div>
                ) : isPlayingTTS ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", height: "60px" }}>
                    {[1,2,3,4,5,6,7,8,9,10,11,12].map(i => (
                      <div key={i} style={{ width: "8px", height: "100%", background: "#10b981", borderRadius: "4px", animation: "lc-wave 0.7s ease-in-out infinite alternate", animationDelay: `${i*0.15}s` }} />
                    ))}
                  </div>
                ) : (
                  <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>Ready for input</p>
                )}
              </div>

              {/* Main Button */}
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "16px", width: "100%" }}>
                {phase === "recording" ? (
                  <button onClick={stopRecording} style={{ width: "80px", height: "80px", borderRadius: "50%", background: "#ef4444", border: "none", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", animation: "lc-pulse 2s infinite" }}>
                    <Square size={28} color="white" fill="white" />
                  </button>
                ) : (
                  <button onClick={startRecording} disabled={phase === "processing" || isPlayingTTS} style={{ width: "80px", height: "80px", borderRadius: "50%", background: (phase === "processing" || isPlayingTTS) ? "#cbd5e1" : "var(--primary-gradient)", border: "none", display: "flex", alignItems: "center", justifyContent: "center", cursor: (phase === "processing" || isPlayingTTS) ? "not-allowed" : "pointer", boxShadow: (phase === "processing" || isPlayingTTS) ? "none" : "0 10px 20px rgba(59,130,246,0.3)", transition: "all 0.2s" }}>
                    <Mic size={32} color="white" />
                  </button>
                )}
                <span style={{ fontSize: "0.85rem", color: "var(--navy)", fontWeight: 600 }}>
                  {phase === "recording" ? `Recording (${recSeconds}s)` : phase === "processing" ? "Processing..." : isPlayingTTS ? "AI Speaking..." : "Tap to Speak"}
                </span>

                <button onClick={endCall} style={{ background: "transparent", border: "1px solid #ef4444", color: "#ef4444", padding: "10px 32px", borderRadius: "20px", fontWeight: 600, fontSize: "0.9rem", cursor: "pointer", marginTop: "16px" }}>
                  End Call
                </button>
              </div>

            </div>
          )}
        </div>

        {/* Right Panel: Live Transcript */}
        <div style={{ background: "rgba(255,255,255,0.9)", backdropFilter: "blur(20px)", borderRadius: "24px", boxShadow: "0 10px 40px rgba(0,0,0,0.05)", border: "1px solid rgba(255,255,255,0.6)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--line)", background: "#f8fafc", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0, fontSize: "1.1rem", color: "var(--navy)" }}>Live Transcript</h3>
            {turns.length > 0 && <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{turns.length} interaction{turns.length > 1 ? "s" : ""}</span>}
          </div>

          <div ref={transcriptRef} style={{ flex: 1, overflowY: "auto", padding: "24px", display: "flex", flexDirection: "column", gap: "24px" }}>
            {turns.length === 0 ? (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", opacity: 0.5 }}>
                <MessageSquare size={48} color="#94a3b8" style={{ marginBottom: "16px" }} />
                <p style={{ margin: 0, fontSize: "1rem" }}>Conversation log will appear here</p>
              </div>
            ) : (
              turns.map((t, i) => (
                <div key={i} style={{ display: "flex", flexDirection: "column", gap: "16px", animation: "fadeIn 0.5s ease" }}>
                  
                  {/* User Bubble */}
                  <div style={{ display: "flex", gap: "12px", alignSelf: "flex-end", maxWidth: "85%", flexDirection: "row-reverse" }}>
                    <div style={{ width: "32px", height: "32px", borderRadius: "10px", background: "var(--bg-deep)", border: "1px solid var(--line)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      <User size={16} color="var(--muted)" />
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "4px" }}>
                      <div style={{ background: "var(--blue-gradient)", color: "white", padding: "12px 16px", borderRadius: "16px 0 16px 16px", fontSize: "0.95rem", lineHeight: 1.5 }}>
                        {t.userText}
                      </div>
                      <span style={{ fontSize: "0.7rem", color: "var(--muted)", marginRight: "4px" }}>{new Date(t.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</span>
                    </div>
                  </div>

                  {/* AI Bubble */}
                  <div style={{ display: "flex", gap: "12px", alignSelf: "flex-start", maxWidth: "85%" }}>
                    <div style={{ width: "32px", height: "32px", borderRadius: "10px", background: "linear-gradient(135deg, #10b981, #059669)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      <Bot size={16} color="white" />
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "8px" }}>
                      <div style={{ background: "white", color: "var(--text)", padding: "12px 16px", borderRadius: "0 16px 16px 16px", border: "1px solid var(--line)", fontSize: "0.95rem", lineHeight: 1.5, boxShadow: "0 2px 10px rgba(0,0,0,0.02)" }}>
                        {t.botText}
                      </div>
                      
                      {/* Analysis Tags */}
                      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                        <span style={{ fontSize: "0.7rem", background: "rgba(73,196,255,0.18)", color: "var(--blue)", padding: "4px 8px", borderRadius: "6px", border: "1px solid rgba(15,23,42,0.08)" }}>Intent: {t.intent}</span>
                        <span style={{ fontSize: "0.7rem", background: `${sentCol(t.sentiment.score)}20`, color: sentCol(t.sentiment.score), padding: "4px 8px", borderRadius: "6px", border: `1px solid ${sentCol(t.sentiment.score)}50` }}>Sentiment: {t.sentiment.label}</span>
                        {t.ticket && <span style={{ fontSize: "0.7rem", background: "#fef2f2", color: "#ef4444", padding: "4px 8px", borderRadius: "6px", border: "1px solid #fecaca", fontWeight: 700 }}>Ticket: {t.ticket.ticket_id}</span>}
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </>
  );
}

// ── IVR Setup Tab ────────────────────────────────────────────────────────────

function IVRSetupTab() {
  const { data: cfg, isLoading, refetch } = useQuery({
    queryKey: ["ivr-config"],
    queryFn: fetchIVRConfig,
    refetchInterval: 15_000,
  });

  function ConfigCheck({ ok, label }: { ok: boolean; label: string }) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 0", borderBottom: "1px solid var(--line)" }}>
        <div style={{ width: "24px", height: "24px", borderRadius: "50%", background: ok ? "#f0fdf4" : "#fef2f2", color: ok ? "#10b981" : "#ef4444", display: "flex", alignItems: "center", justifyContent: "center" }}>
          {ok ? <Check size={14} strokeWidth={3} /> : <AlertTriangle size={14} />}
        </div>
        <span style={{ fontSize: "0.9rem", flex: 1, color: "var(--navy)", fontWeight: 600, fontFamily: "monospace" }}>{label}</span>
        <span style={{ fontSize: "0.75rem", fontWeight: 700, color: ok ? "#10b981" : "#ef4444", background: ok ? "#10b98120" : "#ef444420", padding: "4px 8px", borderRadius: "6px" }}>
          {ok ? "CONFIGURED" : "MISSING"}
        </span>
      </div>
    );
  }

  const allReady = cfg?.twilio_configured && cfg?.public_base_url !== "not configured";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px", paddingBottom: "40px" }}>
      {/* Premium Status Banner */}
      <div style={{ padding: "24px", borderRadius: "20px", background: allReady ? "linear-gradient(135deg, #10b981, #059669)" : "linear-gradient(135deg, #f59e0b, #d97706)", color: "white", display: "flex", alignItems: "center", gap: "20px", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }}>
        <div style={{ width: "64px", height: "64px", borderRadius: "50%", background: "rgba(255,255,255,0.2)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Smartphone size={32} color="white" />
        </div>
        <div style={{ flex: 1 }}>
          <h2 style={{ margin: "0 0 4px", fontSize: "1.5rem", fontWeight: 700 }}>
            {allReady ? "IVR Gateway Online" : "IVR Setup Incomplete"}
          </h2>
          <p style={{ margin: 0, fontSize: "0.95rem", opacity: 0.9 }}>
            {allReady
              ? `Live system ready at ${cfg?.phone_number} | ${cfg?.active_ivr_sessions ?? 0} active calls currently`
              : "Action required: Complete Twilio configuration in the backend environment variables"}
          </p>
        </div>
        <button onClick={() => refetch()} style={{ background: "white", color: allReady ? "#059669" : "#d97706", border: "none", padding: "10px 24px", borderRadius: "12px", fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", gap: "8px", boxShadow: "0 4px 15px rgba(0,0,0,0.1)" }}>
          {isLoading ? <Loader2 className="spin" size={16} /> : <Activity size={16} />}
          {isLoading ? "Checking..." : "Refresh Status"}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
        {/* Environment Config */}
        <div style={{ background: "white", borderRadius: "20px", padding: "32px", border: "1px solid var(--line)", boxShadow: "0 4px 20px rgba(0,0,0,0.03)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "24px" }}>
            <div style={{ background: "#eff6ff", padding: "10px", borderRadius: "10px" }}><Key size={20} color="#3b82f6" /></div>
            <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.2rem" }}>Environment Setup</h3>
          </div>
          
          <p style={{ margin: "0 0 20px", fontSize: "0.9rem", color: "var(--muted)" }}>Add these credentials to <code>services/.env</code> and restart the Python backend.</p>
          
          {cfg ? (
            <div style={{ marginBottom: "32px" }}>
              <ConfigCheck ok={cfg.account_sid_set} label="TWILIO_ACCOUNT_SID" />
              <ConfigCheck ok={cfg.auth_token_set} label="TWILIO_AUTH_TOKEN" />
              <ConfigCheck ok={cfg.phone_number !== "not configured"} label={`TWILIO_PHONE_NUMBER ${cfg.phone_number !== "not configured" ? `(${cfg.phone_number})` : ""}`} />
              <ConfigCheck ok={cfg.public_base_url !== "not configured"} label={`PUBLIC_BASE_URL ${cfg.public_base_url !== "not configured" ? `(${cfg.public_base_url})` : ""}`} />
            </div>
          ) : (
            <div style={{ padding: "40px 0", display: "flex", justifyContent: "center" }}><Loader2 className="spin" color="#3b82f6" size={32} /></div>
          )}

          <div style={{ background: "#f8fafc", borderRadius: "12px", padding: "16px", border: "1px solid var(--line)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
              <Terminal size={16} color="#64748b" />
              <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--navy)" }}>Local testing via ngrok</span>
            </div>
            <code style={{ display: "block", background: "#1e293b", color: "#a7f3d0", padding: "12px", borderRadius: "8px", fontSize: "0.85rem", marginBottom: "12px" }}>
              ngrok http 8005
            </code>
            <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--muted)" }}>Copy the forwarding URL (e.g. https://abc.ngrok-free.app) and set it as <code>PUBLIC_BASE_URL</code></p>
          </div>
        </div>

        {/* Webhooks Setup */}
        <div style={{ background: "white", borderRadius: "20px", padding: "32px", border: "1px solid var(--line)", boxShadow: "0 4px 20px rgba(0,0,0,0.03)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "24px" }}>
            <div style={{ background: "#f0fdf4", padding: "10px", borderRadius: "10px" }}><Server size={20} color="#10b981" /></div>
            <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.2rem" }}>Twilio Webhooks</h3>
          </div>

          <p style={{ margin: "0 0 24px", fontSize: "0.9rem", color: "var(--muted)" }}>Configure these endpoints in the Twilio Console under Phone Numbers → Manage.</p>

          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {[
              { label: "Incoming Voice Webhook", key: "incoming", required: true, method: "POST" },
              { label: "Language Callback", key: "language_selection", required: false, method: "POST" },
              { label: "Speech Processing", key: "process_query", required: false, method: "POST" },
              { label: "Status Callback (End)", key: "call_end", required: true, method: "POST" },
            ].map(({ label, key, required, method }) => (
              <div key={key} style={{ background: "#f8fafc", padding: "16px", borderRadius: "12px", border: "1px solid var(--line)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <span style={{ fontSize: "0.9rem", fontWeight: 700, color: "var(--navy)" }}>{label}</span>
                  {required && <span style={{ fontSize: "0.7rem", background: "#fef2f2", color: "#ef4444", padding: "2px 8px", borderRadius: "4px", fontWeight: 700 }}>REQUIRED</span>}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{ fontSize: "0.75rem", background: "#e0e7ff", color: "#4f46e5", padding: "4px 8px", borderRadius: "4px", fontWeight: 700 }}>{method}</span>
                  <code style={{ fontSize: "0.8rem", color: "#3b82f6", wordBreak: "break-all" }}>
                    {cfg?.webhooks?.[key] ?? `[PUBLIC_URL]/api/call-centre/ivr/${key.replace("_", "-")}`}
                  </code>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Call Flow Visualizer */}
      <div style={{ background: "white", borderRadius: "20px", padding: "32px", border: "1px solid var(--line)", boxShadow: "0 4px 20px rgba(0,0,0,0.03)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "32px" }}>
          <div style={{ background: "#fdf4ff", padding: "10px", borderRadius: "10px" }}><Layers size={20} color="#d946ef" /></div>
          <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.2rem" }}>Telephony Architecture Flow</h3>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "16px" }}>
          {[
            { step: "1", title: "Inbound Call", desc: "Twilio receives call, requests instructions from POST /incoming" },
            { step: "2", title: "Language Menu", desc: "DTMF collection for Telugu, English, Hindi, etc." },
            { step: "3", title: "User Speech", desc: "Twilio STT records user query in selected language" },
            { step: "4", title: "AI Analysis", desc: "Backend runs ML Sentiment & PDSAI-Bot Intent" },
            { step: "5", title: "Ticket Engine", desc: "Auto-creates Postgres grievance ticket if complaint" },
            { step: "6", title: "gTTS Synthesis", desc: "Backend generates localized voice response audio" },
            { step: "7", title: "Audio Playback", desc: "Twilio plays TwiML <Play> response to caller" },
            { step: "8", title: "Call End", desc: "Status callback updates metrics" }
          ].map((item, i) => (
            <div key={item.step} style={{ background: "#f8fafc", padding: "20px", borderRadius: "16px", border: "1px solid var(--line)", position: "relative" }}>
              <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: "var(--primary-gradient)", color: "white", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.8rem", fontWeight: 700, marginBottom: "12px" }}>
                {item.step}
              </div>
              <h4 style={{ margin: "0 0 8px", fontSize: "0.95rem", color: "var(--navy)" }}>{item.title}</h4>
              <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--muted)", lineHeight: 1.4 }}>{item.desc}</p>
              
              {i < 7 && (
                <ArrowRight size={20} color="#cbd5e1" style={{ position: "absolute", right: "-18px", top: "50%", transform: "translateY(-50%)", zIndex: 1 }} />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function CallCentrePage() {
  const [liveMetrics, setLiveMetrics] = useState<LiveMetrics | null>(null);
  const [activeTab, setActiveTab] = useState<"dashboard" | "tickets" | "chatbot" | "audio" | "livecall" | "analytics" | "agents" | "pipeline" | "ivr">("dashboard");
  const [ticketFilter, setTicketFilter] = useState("ALL");
  const [mapType, setMapType] = useState<"landscape" | "satellite">("landscape");
  const [ccMapDistrict, setCcMapDistrict] = useState<string>("");
  const [ccMapCategory, setCcMapCategory] = useState<string>("");
  const [ccMapLanguage, setCcMapLanguage] = useState<string>("");
  const [ccMapPriority, setCcMapPriority] = useState<string>("");
  const [ccMapStatus, setCcMapStatus] = useState<string>("");
  const wsRef = useRef<WebSocket | null>(null);
  const queryClient = useQueryClient();

  const { data: ticketData, isLoading: ticketsLoading } = useQuery({
    queryKey: ["tickets"],
    queryFn: fetchTickets,
    refetchInterval: 10_000,
  });

  const { data: dashboardData } = useQuery({
    queryKey: ["call-centre-dashboard"],
    queryFn: fetchCallCentreDashboard,
    refetchInterval: 15_000,
  });

  const { data: metricsData } = useQuery({
    queryKey: ["live-metrics"],
    queryFn: fetchLiveMetrics,
    refetchInterval: 5_000,
  });

  useEffect(() => {
    if (metricsData?.metrics) setLiveMetrics(metricsData.metrics);
  }, [metricsData]);

  useEffect(() => {
    wsRef.current = createLiveMetricsSocket(setLiveMetrics);
    return () => wsRef.current?.close();
  }, []);

  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => updateTicketStatus(id, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tickets"] }),
  });

  const allTickets = ticketData?.tickets ?? [];
  const filtered = ticketFilter === "ALL" ? allTickets : allTickets.filter((t) => t.status === ticketFilter);
  const dash = dashboardData?.dashboard;
  const metrics = liveMetrics;

  const callMapOptions = useMemo(() => {
    const districts = new Set<string>();
    const categories = new Set<string>();
    const languages = new Set<string>();
    const priorities = new Set<string>();
    const statuses = new Set<string>();

    for (const t of allTickets as any[]) {
      if (t.district_name) districts.add(String(t.district_name));
      if (t.category) categories.add(String(t.category));
      if (t.language) languages.add(String(t.language));
      if (t.priority) priorities.add(String(t.priority));
      if (t.status) statuses.add(String(t.status));
    }

    // Fallback to AP_COORDS keys if ticket district_name is empty (demo data).
    if (districts.size === 0) Object.keys(AP_COORDS).forEach((d) => districts.add(d));

    return {
      districts: Array.from(districts).sort((a, b) => a.localeCompare(b)),
      categories: Array.from(categories).sort((a, b) => a.localeCompare(b)),
      languages: Array.from(languages).sort((a, b) => a.localeCompare(b)),
      priorities: Array.from(priorities).sort((a, b) => a.localeCompare(b)),
      statuses: Array.from(statuses).sort((a, b) => a.localeCompare(b)),
    };
  }, [allTickets]);

  const callDensityByDistrict = useMemo(() => {
    const rows = (allTickets as any[]).filter((t) => {
      if (ccMapDistrict && String(t.district_name || "") !== ccMapDistrict) return false;
      if (ccMapCategory && String(t.category || "") !== ccMapCategory) return false;
      if (ccMapLanguage && String(t.language || "") !== ccMapLanguage) return false;
      if (ccMapPriority && String(t.priority || "") !== ccMapPriority) return false;
      if (ccMapStatus && String(t.status || "") !== ccMapStatus) return false;
      return true;
    });

    const by: Record<string, number> = {};
    for (const t of rows) {
      const d = String(t.district_name || "Unknown");
      by[d] = (by[d] || 0) + 1;
    }

    // If no ticket districts exist, fall back to mock using live metrics spread.
    if (Object.keys(by).length === 0) {
      const cats = metrics?.calls_by_category ? Object.values(metrics.calls_by_category).reduce((a, b) => a + b, 0) : 0;
      const base = Math.max(1, cats || metrics?.active_sessions || 1);
      Object.keys(AP_COORDS).forEach((d, i) => { by[d] = Math.max(0, Math.round(base * (0.08 + (i % 4) * 0.03))); });
    }

    return by;
  }, [allTickets, ccMapCategory, ccMapDistrict, ccMapLanguage, ccMapPriority, ccMapStatus, metrics]);

  const TABS = [
    { key: "dashboard", label: "Dashboard" },
    { key: "tickets", label: `Tickets (${allTickets.length})` },
    { key: "chatbot", label: "AI Chatbot" },
    { key: "audio", label: "Audio Upload" },
    { key: "livecall", label: "Live Call" },
    { key: "analytics", label: "Analytics" },
    { key: "agents", label: "Agents & SLA" },
    { key: "pipeline", label: "Pipeline" },
    { key: "ivr", label: "IVR Setup" },
  ] as const;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">AI-enabled Call Centre</p>
          <h2>AP SARAthi Call Centre — Multilingual AI Voice + Chat</h2>
        </div>
        <div className="toll-free-badge">
          <span className="toll-free-icon">📞</span>
          <div>
            <p className="eyebrow">Toll-Free Number</p>
            <strong className="phone-number">Configure in IVR Setup</strong>
          </div>
        </div>
      </header>

      {metrics && <LiveMetricsBanner metrics={metrics} />}

      <nav className="cc-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            className={`cc-tab ${activeTab === tab.key ? "active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

            {/* ── Dashboard Tab ── */}
      {activeTab === "dashboard" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "24px", animation: "fadeIn 0.4s ease" }}>
          {dash && metrics ? (
            <>
              {/* 1. Top KPI Cards */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "20px" }}>
                {[
                  { title: "Active Calls", value: metrics.active_sessions, icon: <Phone size={24} color="#3b82f6" />, change: "+12%" },
                  { title: "Open Tickets", value: dash.summary.open_tickets, icon: <AlertCircle size={24} color="#f59e0b" />, change: "-5%" },
                  { title: "Resolution Rate", value: `${dash.performance.resolution_rate_percent}%`, icon: <CheckCircle size={24} color="#10b981" />, change: "+2%" },
                  { title: "Avg Sentiment", value: dash.performance.average_sentiment_score > 0 ? `+${dash.performance.average_sentiment_score.toFixed(2)}` : dash.performance.average_sentiment_score.toFixed(2), icon: <Activity size={24} color={dash.performance.average_sentiment_score > 0 ? "#10b981" : "#ef4444"} />, change: "" }
                ].map((kpi, i) => (
                  <div key={i} style={{ background: "rgba(255,255,255,0.8)", backdropFilter: "blur(12px)", borderRadius: "20px", padding: "20px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid rgba(255,255,255,0.4)", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                      <span style={{ color: "var(--navy)", fontWeight: 600, fontSize: "0.95rem" }}>{kpi.title}</span>
                      <div style={{ background: "#f1f5f9", padding: "8px", borderRadius: "12px" }}>{kpi.icon}</div>
                    </div>
                    <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginTop: "16px" }}>
                      <h2 style={{ margin: 0, fontSize: "2rem", color: "var(--navy)", fontWeight: 800 }}>{kpi.value}</h2>
                      {kpi.change && <span style={{ color: kpi.change.startsWith('+') ? "#10b981" : "#ef4444", fontSize: "0.85rem", fontWeight: 700 }}>{kpi.change} today</span>}
                    </div>
                  </div>
                ))}
              </div>

              {/* 2. Visual Analytics Row 1 */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "24px" }}>
                
                {/* AI Insight Card (Explainable) */}
                <div style={{ background: "var(--insights-gradient)", borderRadius: "20px", padding: "24px", color: "white", boxShadow: "0 10px 30px rgba(30,58,138,0.25)", position: "relative", overflow: "hidden" }}>
                  <div style={{ position: "absolute", right: -20, top: -20, opacity: 0.1 }}><Zap size={140} /></div>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "20px" }}>
                    <Zap size={24} color="var(--insights-accent)" />
                    <h3 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700 }}>SARATHI AI Insights</h3>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px", zIndex: 1, position: "relative" }}>
                    <div style={{ background: "var(--insights-surface)", borderRadius: "12px", padding: "16px" }}>
                      <strong style={{ display: "block", color: "var(--insights-accent)", marginBottom: "4px", fontSize: "0.85rem" }}>PREDICTED SPIKE</strong>
                      <span>
                        Next-day expected calls: <strong>{dash.forecast.next_day_expected_calls}</strong>. Peak issue: <strong>{dash.forecast.predicted_peak_issue}</strong>. Peak language: <strong>{dash.forecast.predicted_peak_language}</strong>.
                      </span>
                    </div>
                    <div style={{ background: "var(--insights-surface)", borderRadius: "12px", padding: "16px" }}>
                      <strong style={{ display: "block", color: "var(--insights-accent)", marginBottom: "4px", fontSize: "0.85rem" }}>RECOMMENDED ACTION</strong>
                      <span>
                        Suggested routing: enable/scale <strong>{dash.forecast.predicted_peak_language}</strong> IVR first when volumes rise; current average resolution ETA is <strong>{dash.performance.average_resolution_eta_hours}h</strong>.
                      </span>
                    </div>
                  </div>
                </div>

                {/* Top Complaints Bar Chart */}
                <div style={{ background: "rgba(255,255,255,0.9)", backdropFilter: "blur(12px)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid rgba(255,255,255,0.4)" }}>
                  <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Top Complaint Categories</h3>
                  <div style={{ height: "250px" }}>
                    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                      <BarChart data={Object.entries(metrics.calls_by_category).map(([name, value]) => ({ name, value })).sort((a,b) => b.value - a.value).slice(0, 5)} layout="vertical" margin={{ left: 20 }}>
                        <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#e2e8f0" />
                        <XAxis type="number" axisLine={false} tickLine={false} />
                        <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} width={120} tick={{ fill: 'var(--navy)', fontSize: 12 }} />
                        <RechartsTooltip cursor={{fill: '#f1f5f9'}} contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                        <Bar dataKey="value" name="Volume" radius={[0, 8, 8, 0]} maxBarSize={30}>
                          {Object.entries(metrics.calls_by_category).map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={["#ef4444", "#f97316", "#eab308", "#3b82f6", "#10b981"][index % 5]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>

              {/* 3. Visual Analytics Row 2 */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1.5fr", gap: "24px" }}>
                
                {/* Calls by Language Donut */}
                <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid rgba(255,255,255,0.4)", display: "flex", flexDirection: "column" }}>
                  <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Calls by Language</h3>
                  <div style={{ flex: 1, minHeight: "220px" }}>
                    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                      <PieChart>
                        <Pie data={Object.entries(metrics.calls_by_language).map(([name, value]) => ({ name, value }))} innerRadius={60} outerRadius={85} paddingAngle={5} dataKey="value">
                          {Object.entries(metrics.calls_by_language).map((entry, index) => <Cell key={`cell-${index}`} fill={["#3b82f6", "#10b981", "#f59e0b", "#6366f1"][index % 4]} />)}
                        </Pie>
                        <RechartsTooltip contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                        <Legend iconType="circle" wrapperStyle={{ paddingTop: "20px" }} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Sentiment Trend Area */}
                <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "24px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid rgba(255,255,255,0.4)" }}>
                  <h3 style={{ margin: "0 0 20px 0", color: "var(--navy)", fontSize: "1.1rem" }}>Sentiment Trend (7 Days)</h3>
                  <div style={{ height: "220px" }}>
                    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                      <AreaChart data={metrics.sentiment_trend.map((val, i) => ({ day: `Day ${i+1}`, sentiment: val }))} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                          <linearGradient id="colorSentiment" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                            <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                        <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                        <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#64748b" }} domain={[-1, 1]} />
                        <RechartsTooltip contentStyle={{ borderRadius: "12px", border: "none", boxShadow: "0 10px 30px rgba(0,0,0,0.1)" }} />
                        <Area type="monotone" dataKey="sentiment" stroke="#10b981" strokeWidth={3} fillOpacity={1} fill="url(#colorSentiment)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>

	                {/* Map View */}
	                <div style={{ background: "rgba(255,255,255,0.9)", borderRadius: "20px", padding: "20px", boxShadow: "0 8px 30px rgba(0,0,0,0.04)", border: "1px solid rgba(255,255,255,0.4)", display: "flex", flexDirection: "column" }}>
	                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", gap: 12, flexWrap: "wrap" }}>
	                    <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.1rem" }}>Call Density Map</h3>
	                    <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
	                      {/* Map Filters (call-centre relevant) */}
	                      <select value={ccMapDistrict} onChange={(e) => setCcMapDistrict(e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "#fff", fontWeight: 700 }}>
	                        <option value="">All Districts</option>
	                        {callMapOptions.districts.map((d: string) => <option key={d} value={d}>{d}</option>)}
	                      </select>
	                      <select value={ccMapCategory} onChange={(e) => setCcMapCategory(e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "#fff", fontWeight: 700, minWidth: 190 }}>
	                        <option value="">All Categories</option>
	                        {callMapOptions.categories.map((c: string) => <option key={c} value={c}>{c}</option>)}
	                      </select>
	                      <select value={ccMapLanguage} onChange={(e) => setCcMapLanguage(e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "#fff", fontWeight: 700 }}>
	                        <option value="">All Languages</option>
	                        {callMapOptions.languages.map((l: string) => <option key={l} value={l}>{l}</option>)}
	                      </select>
	                      <select value={ccMapPriority} onChange={(e) => setCcMapPriority(e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "#fff", fontWeight: 700 }}>
	                        <option value="">All Priorities</option>
	                        {callMapOptions.priorities.map((p: string) => <option key={p} value={p}>{p}</option>)}
	                      </select>
	                      <select value={ccMapStatus} onChange={(e) => setCcMapStatus(e.target.value)} style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line)", background: "#fff", fontWeight: 700 }}>
	                        <option value="">All Status</option>
	                        {callMapOptions.statuses.map((s: string) => <option key={s} value={s}>{s}</option>)}
	                      </select>

	                      <div style={{ display: "flex", background: "rgba(255,255,255,0.9)", backdropFilter: "blur(4px)", borderRadius: "8px", padding: "4px", border: "1px solid var(--line)", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }}>
	                         <button onClick={() => setMapType("landscape")} style={{ padding: "4px 12px", border: "none", borderRadius: "6px", background: mapType === "landscape" ? "#fff" : "transparent", boxShadow: mapType === "landscape" ? "0 2px 4px rgba(0,0,0,0.1)" : "none", fontSize: "0.75rem", fontWeight: 600, cursor: "pointer", color: mapType === "landscape" ? "var(--navy)" : "var(--muted)", transition: "all 0.2s" }}>Landscape</button>
	                         <button onClick={() => setMapType("satellite")} style={{ padding: "4px 12px", border: "none", borderRadius: "6px", background: mapType === "satellite" ? "#fff" : "transparent", boxShadow: mapType === "satellite" ? "0 2px 4px rgba(0,0,0,0.1)" : "none", fontSize: "0.75rem", fontWeight: 600, cursor: "pointer", color: mapType === "satellite" ? "var(--navy)" : "var(--muted)", transition: "all 0.2s" }}>Satellite</button>
	                      </div>
	                    </div>
	                  </div>
                  <div style={{ flex: 1, borderRadius: "14px", overflow: "hidden", minHeight: "220px", zIndex: 1, position: "relative" }}>
                    <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}>
                      <MapContainer center={[15.9, 79.7]} zoom={6.5} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
                        <TileLayer url={MAP_LAYERS[mapType]} attribution="" />
	                      {Object.entries(callDensityByDistrict).map(([district, count]) => {
	                        const coords = (AP_COORDS as any)[district] as [number, number] | undefined;
	                        if (!coords) return null;
	                        const c = Number(count || 0);
	                        const intensity = c >= 30 ? 3 : (c >= 10 ? 2 : 1);
	                        const color = intensity === 3 ? "#ef4444" : (intensity === 2 ? "#f97316" : "#3b82f6");
	                        const radius = Math.max(8, Math.min(26, 6 + Math.sqrt(c) * 3));
	                        return (
	                          <CircleMarker key={district} center={coords} radius={radius} color={color} fillColor={color} fillOpacity={0.55} weight={0}>
	                            <LeafletTooltip><strong>{district}</strong><br/>{c.toLocaleString("en-IN")} tickets (proxy)</LeafletTooltip>
	                          </CircleMarker>
	                        );
	                      })}
	                      </MapContainer>
                    </div>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <p className="state">Loading command center intelligence...</p>
          )}
        </div>
      )}

      {/* ── Tickets Tab ── */}
      {activeTab === "tickets" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          
          {/* Header Controls */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(255,255,255,0.8)", backdropFilter: "blur(12px)", padding: "16px 24px", borderRadius: "20px", boxShadow: "0 4px 20px rgba(0,0,0,0.03)", border: "1px solid rgba(255,255,255,0.5)" }}>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <Filter size={18} color="var(--muted)" />
              <span style={{ fontSize: "0.9rem", fontWeight: 600, color: "var(--navy)", marginRight: "12px" }}>Filter Status:</span>
              <div style={{ display: "flex", gap: "6px", background: "var(--bg-deep)", padding: "4px", borderRadius: "10px" }}>
                {["ALL", ...STATUS_OPTIONS].map((s) => {
                  const count = s === "ALL" ? allTickets.length : allTickets.filter((t) => t.status === s).length;
                  return (
                    <button
                      key={s}
                      onClick={() => setTicketFilter(s)}
                      style={{
                        padding: "6px 16px", borderRadius: "8px", fontSize: "0.85rem", fontWeight: 600, cursor: "pointer", border: "none", transition: "all 0.2s",
                        background: ticketFilter === s ? "white" : "transparent",
                        color: ticketFilter === s ? "var(--navy)" : "var(--muted)",
                        boxShadow: ticketFilter === s ? "0 2px 8px rgba(0,0,0,0.05)" : "none"
                      }}
                    >
                      {s} <span style={{ opacity: 0.6, marginLeft: "4px" }}>({count})</span>
                    </button>
                  );
                })}
              </div>
            </div>
            
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <div style={{ position: "relative" }}>
                <Search size={16} color="var(--muted)" style={{ position: "absolute", left: "12px", top: "50%", transform: "translateY(-50%)" }} />
                <input placeholder="Search ID or Caller..." style={{ padding: "10px 16px 10px 36px", borderRadius: "12px", border: "1px solid var(--line)", outline: "none", fontSize: "0.9rem", width: "220px" }} />
              </div>
            </div>
          </div>

          {/* Grid Area */}
          {ticketsLoading ? (
            <div style={{ display: "flex", justifyContent: "center", padding: "60px 0", color: "var(--blue)" }}>
              <Loader2 className="spin" size={40} />
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "60px 0", opacity: 0.6 }}>
              <CheckCircle2 size={64} color="#10b981" style={{ marginBottom: "16px" }} />
              <h3 style={{ margin: "0 0 8px", color: "var(--navy)" }}>All clear!</h3>
              <p style={{ margin: 0, color: "var(--muted)" }}>No tickets match the current filter.</p>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "20px" }}>
              {filtered.map((ticket) => (
                <TicketCard
                  key={ticket.ticket_id}
                  ticket={ticket}
                  onStatusChange={(id, status) => statusMut.mutate({ id, status })}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Chatbot Tab ── */}
      {activeTab === "chatbot" && (
        <div className="panel-grid">
          <ChatbotPanel />
          <article className="panel">
            <h3>How It Works</h3>
            <ol className="plain-list" style={{ paddingLeft: 20, lineHeight: 2 }}>
              <li>Start a conversation and enter caller details</li>
              <li>Select language — English, Telugu, or Hindi</li>
              <li>Type your query in the selected language</li>
              <li>AI responds with context-aware answers</li>
              <li>Complaints automatically generate support tickets</li>
              <li>Sentiment is tracked in real time</li>
            </ol>
            <div style={{ marginTop: 20 }}>
              <p className="eyebrow">Supported Languages</p>
              <div className="tag-row" style={{ marginTop: 8 }}>
                <span className="ghost-chip">🇬🇧 English</span>
                <span className="ghost-chip">తెలుగు</span>
                <span className="ghost-chip">हिंदी</span>
              </div>
            </div>
          </article>
        </div>
      )}

      {/* ── Audio Upload Tab ── */}
      {activeTab === "audio" && (
        <div className="panel-grid">
          <AudioUploadPanel />
          <article className="panel">
            <h3>Audio Processing Pipeline</h3>
            <ol className="plain-list" style={{ paddingLeft: 20, lineHeight: 2 }}>
              <li>Upload any audio recording (.wav, .mp3, .ogg)</li>
              <li>OpenAI Whisper transcribes with language detection</li>
              <li>Sentiment analysis runs on the transcript</li>
              <li>If complaint detected, ticket is auto-created in PostgreSQL</li>
              <li>Transcript stored and accessible in Tickets tab</li>
            </ol>
            <p className="subtle-line" style={{ marginTop: 16 }}>
              Requires <strong>OPENAI_API_KEY</strong> in backend .env
            </p>
          </article>
        </div>
      )}

      {/* ── Live Call Tab ── */}
      {activeTab === "livecall" && <LiveCallTab />}

      {/* ── Analytics Tab ── */}
      {activeTab === "analytics" && <AnalyticsTab />}

      {/* ── Agents & SLA Tab ── */}
      {activeTab === "agents" && <AgentsTab />}

      {/* ── Pipeline Tab ── */}
      {activeTab === "pipeline" && <PipelineTab />}

      {/* ── IVR Setup Tab ── */}
      {activeTab === "ivr" && <IVRSetupTab />}
    </section>
  );
}
