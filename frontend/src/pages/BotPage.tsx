import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { chatWithBot, clearBotSession } from "../api";
import type { ChatMessage } from "../types";
import { MessageSquare, X, Send, Info, Trash2, Volume2, VolumeX, Mic } from "lucide-react";
import ReactMarkdown from "react-markdown";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from "recharts";
import { speak, stopSpeech } from "../utils/tts";

// ── Helpers ───────────────────────────────────────────────────────────────────

function genId() { return Math.random().toString(36).slice(2, 10); }
function fmtTs(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const INTENT_COLORS: Record<string, string> = {
  stock_check:              "#2563eb",
  anomaly_check:            "#dc2626",
  demand_prediction:        "#7c3aed",
  allocation_recommendation:"#16a34a",
  delivery_status:          "#ea580c",
  grievance:                "#d97706",
  compliance_check:         "#be123c",
  entitlement_query:        "#0891b2",
  beneficiary_lookup:       "#0891b2",
  distribution_schedule:    "#0891b2",
  fps_location:             "#0891b2",
  complaint_fraud:          "#dc2626",
  general_query:            "#6b7280",
  greeting:                 "#6b7280",
  help:                     "#6b7280",
  farewell:                 "#6b7280",
};

const INTENT_LABELS: Record<string, string> = {
  stock_check:              "Stock Check",
  anomaly_check:            "Anomaly",
  demand_prediction:        "Forecast",
  allocation_recommendation:"Allocation",
  delivery_status:          "Delivery",
  grievance:                "Grievance",
  compliance_check:         "Compliance",
  entitlement_query:        "Entitlement",
  beneficiary_lookup:       "Beneficiary",
  distribution_schedule:    "Schedule",
  fps_location:             "FPS Location",
  complaint_fraud:          "Fraud Report",
  general_query:            "General",
  greeting:                 "Greeting",
  help:                     "Help",
  farewell:                 "Farewell",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function IntentBadge({ intent, confidence }: { intent?: string; confidence?: number }) {
  if (!intent) return null;
  const color = INTENT_COLORS[intent] ?? "#6b7280";
  const label = INTENT_LABELS[intent] ?? intent.replace(/_/g, " ");
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "3px",
      fontSize: "0.62rem", fontWeight: 700, color,
      background: `${color}15`, border: `1px solid ${color}35`,
      borderRadius: "6px", padding: "2px 7px",
      letterSpacing: "0.04em", textTransform: "uppercase",
    }}>
      {label}
      {confidence != null && <span style={{ opacity: 0.65 }}>· {Math.round(confidence * 100)}%</span>}
    </span>
  );
}

function TypingIndicator() {
  return (
    <div style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: "10px", padding: "12px 16px", background: "#fff", borderRadius: "18px 18px 18px 4px", boxShadow: "0 2px 8px rgba(0,0,0,0.08)", border: "1px solid rgba(0,0,0,0.06)" }}>
      <style>{`
        @keyframes botBounce {
          0%,80%,100% { transform: translateY(0); opacity: 0.4; }
          40%          { transform: translateY(-5px); opacity: 1; }
        }
      `}</style>
      <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
        {[0, 0.18, 0.36].map((delay, i) => (
          <span key={i} style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#2563eb", animation: `botBounce 1.1s ease-in-out ${delay}s infinite` }} />
        ))}
      </div>
      <span style={{ fontSize: "0.78rem", color: "#94a3b8", fontStyle: "italic" }}>SARATHI is thinking…</span>
    </div>
  );
}

// Animated voice wave while speaking
function VoiceWave() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "2px", marginLeft: "4px" }}>
      <style>{`
        @keyframes wave { 0%,100%{height:4px} 50%{height:12px} }
      `}</style>
      {[0, 0.1, 0.2, 0.1, 0].map((delay, i) => (
        <span key={i} style={{ display: "inline-block", width: "3px", height: "8px", background: "#2563eb", borderRadius: "2px", animation: `wave 0.8s ease-in-out ${delay}s infinite` }} />
      ))}
    </span>
  );
}

function SpeakerButton({ msgId, text, language, speakingId, setSpeakingId }: {
  msgId: string; text: string; language: string;
  speakingId: string | null; setSpeakingId: (id: string | null) => void;
}) {
  const isMe = speakingId === msgId;
  function toggle() {
    if (isMe) {
      stopSpeech();
      setSpeakingId(null);
    } else {
      stopSpeech();
      setSpeakingId(msgId);
      speak(text, language, undefined, () => setSpeakingId(null));
    }
  }
  return (
    <button onClick={toggle} title={isMe ? "Stop voice" : "Listen"}
      style={{ background: isMe ? "#eff6ff" : "transparent", border: isMe ? "1px solid #bfdbfe" : "1px solid transparent", borderRadius: "8px", padding: "3px 7px", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: "4px", color: isMe ? "#2563eb" : "#94a3b8", transition: "all 0.15s" }}
      onMouseEnter={(e) => { if (!isMe) { e.currentTarget.style.color = "#2563eb"; e.currentTarget.style.borderColor = "#bfdbfe"; e.currentTarget.style.background = "#f0f7ff"; } }}
      onMouseLeave={(e) => { if (!isMe) { e.currentTarget.style.color = "#94a3b8"; e.currentTarget.style.borderColor = "transparent"; e.currentTarget.style.background = "transparent"; } }}
    >
      {isMe ? <><VolumeX size={13} /><VoiceWave /></> : <Volume2 size={13} />}
    </button>
  );
}

// Recharts mini-chart for forecast / anomaly data
function MiniChart({ data, intent }: { data: Record<string, unknown>; intent?: string }) {
  // Forecast / stock / allocation bar chart
  const recs = data.recommendations as Array<Record<string, unknown>> | undefined;
  if (
    recs && recs.length > 0 &&
    (intent === "stock_check" || intent === "demand_prediction" || intent === "allocation_recommendation")
  ) {
    const chartData = recs.slice(0, 8).map((r) => ({
      name: String(r.item_name ?? r.commodity ?? "").slice(0, 10),
      Forecast:  Math.round(Number(r.forecast_next_month  ?? r.predicted_demand         ?? 0)),
      Allotment: Math.round(Number(r.recommended_allotment ?? r.recommended_allocation ?? 0)),
    }));
    return (
      <div style={{ marginTop: "12px", padding: "12px 14px 8px", background: "rgba(241,245,249,0.9)", borderRadius: "12px", border: "1px solid rgba(37,99,235,0.12)" }}>
        <p style={{ margin: "0 0 8px", fontSize: "0.68rem", fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Forecast vs Allotment (kg)
        </p>
        <div style={{ minWidth: 0, width: "100%" }}>
          <ResponsiveContainer width="100%" height={150} minWidth={0}>
            <BarChart data={chartData} margin={{ top: 2, right: 6, left: -22, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
              <XAxis dataKey="name" tick={{ fontSize: 9, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 9, fill: "#64748b" }} />
              <Tooltip
                formatter={(v) => (v != null ? `${Number(v).toLocaleString()} kg` : "")}
                contentStyle={{ fontSize: "0.72rem", borderRadius: "8px", border: "1px solid #e2e8f0" }}
              />
              <Bar dataKey="Forecast"  fill="#818cf8" radius={[3, 3, 0, 0]} />
              <Bar dataKey="Allotment" fill="#34d399" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div style={{ display: "flex", gap: "14px", justifyContent: "center", marginTop: "4px" }}>
          {[["#818cf8", "Forecast"], ["#34d399", "Allotment"]].map(([c, lbl]) => (
            <span key={lbl} style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "0.66rem", color: "#64748b" }}>
              <span style={{ width: "9px", height: "9px", background: c, borderRadius: "2px", display: "inline-block" }} />
              {lbl}
            </span>
          ))}
        </div>
      </div>
    );
  }

  // Anomaly severity bar chart
  const summary = data.summary as Record<string, unknown> | undefined;
  if (intent === "anomaly_check" && summary?.severity_breakdown) {
    const sb = summary.severity_breakdown as Record<string, number>;
    const chartData = Object.entries(sb).map(([k, v]) => ({ name: k, Count: v }));
    return (
      <div style={{ marginTop: "12px", padding: "12px 14px 8px", background: "rgba(254,242,242,0.9)", borderRadius: "12px", border: "1px solid rgba(220,38,38,0.12)" }}>
        <p style={{ margin: "0 0 8px", fontSize: "0.68rem", fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Anomaly Severity
        </p>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={chartData} margin={{ top: 2, right: 6, left: -22, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
            <XAxis dataKey="name" tick={{ fontSize: 9, fill: "#64748b" }} />
            <YAxis tick={{ fontSize: 9, fill: "#64748b" }} allowDecimals={false} />
            <Tooltip contentStyle={{ fontSize: "0.72rem", borderRadius: "8px", border: "1px solid #e2e8f0" }} />
            <Bar dataKey="Count" radius={[3, 3, 0, 0]}
              // colour each bar by severity
              label={false}
              fill="#f87171"
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return null;
}

// ReactMarkdown components — prose styling without external CSS
const MD_COMPONENTS: React.ComponentProps<typeof ReactMarkdown>["components"] = {
  p:          ({ children }) => <p style={{ margin: "0 0 7px 0", lineHeight: 1.6 }}>{children}</p>,
  strong:     ({ children }) => <strong style={{ fontWeight: 700, color: "#1e293b" }}>{children}</strong>,
  em:         ({ children }) => <em style={{ color: "#475569" }}>{children}</em>,
  ul:         ({ children }) => <ul style={{ margin: "5px 0 7px", paddingLeft: "18px" }}>{children}</ul>,
  ol:         ({ children }) => <ol style={{ margin: "5px 0 7px", paddingLeft: "18px" }}>{children}</ol>,
  li:         ({ children }) => <li style={{ marginBottom: "3px", lineHeight: 1.55 }}>{children}</li>,
  h1:         ({ children }) => <h1 style={{ fontSize: "1rem", fontWeight: 700, margin: "10px 0 5px", color: "#1e293b" }}>{children}</h1>,
  h2:         ({ children }) => <h2 style={{ fontSize: "0.92rem", fontWeight: 700, margin: "9px 0 5px", color: "#1e293b" }}>{children}</h2>,
  h3:         ({ children }) => <h3 style={{ fontSize: "0.88rem", fontWeight: 700, margin: "8px 0 4px", color: "#334155" }}>{children}</h3>,
  code:       ({ children }) => <code style={{ background: "#f1f5f9", padding: "1px 5px", borderRadius: "4px", fontSize: "0.8rem", fontFamily: "monospace", color: "#1e293b" }}>{children}</code>,
  blockquote: ({ children }) => <blockquote style={{ borderLeft: "3px solid #2563eb", paddingLeft: "10px", margin: "6px 0", color: "#475569", fontStyle: "italic" }}>{children}</blockquote>,
  hr:         () => <hr style={{ border: "none", borderTop: "1px solid #e2e8f0", margin: "8px 0" }} />,
  a:          ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: "#2563eb", textDecoration: "underline" }}>{children}</a>,
};

function MessageBubble({ msg, onSuggestion, language, speakingId, setSpeakingId }: {
  msg: ChatMessage; onSuggestion: (s: string) => void;
  language: string; speakingId: string | null; setSpeakingId: (id: string | null) => void;
}) {
  const isUser = msg.role === "user";
  const intentColor = (msg.intent && INTENT_COLORS[msg.intent]) ?? "#6b7280";

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start", gap: "5px", animation: "msgIn 0.22s ease-out" }}>
      <style>{`
        @keyframes msgIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>

      {/* Bubble */}
      <div style={{
        maxWidth: "88%",
        background:    isUser ? "linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)" : "#fff",
        color:         isUser ? "#fff" : "#1e293b",
        borderRadius:  isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
        padding:       "12px 15px",
        fontSize:      "0.875rem",
        lineHeight:    1.6,
        boxShadow:     isUser ? "0 4px 14px rgba(30,58,138,0.28)" : "0 2px 8px rgba(0,0,0,0.08)",
        border:        isUser ? "none" : "1px solid rgba(0,0,0,0.06)",
        wordBreak:     "break-word",
      }}>
        {isUser ? (
          <span style={{ whiteSpace: "pre-wrap" }}>{msg.content}</span>
        ) : (
          <>
            <ReactMarkdown components={MD_COMPONENTS}>{msg.content}</ReactMarkdown>

            {/* Mini chart */}
            {msg.data && Object.keys(msg.data).length > 0 && (
              <MiniChart data={msg.data} intent={msg.intent} />
            )}

            {/* Insight pills */}
            {msg.insights && msg.insights.length > 0 && (
              <div style={{ marginTop: "10px", display: "flex", flexDirection: "column", gap: "4px" }}>
                {msg.insights.map((ins, i) => (
                  <div key={i} style={{
                    display: "flex", alignItems: "flex-start", gap: "6px",
                    fontSize: "0.7rem", color: "#475569",
                    background: `${intentColor}09`,
                    borderLeft: `3px solid ${intentColor}50`,
                    padding: "5px 9px", borderRadius: "0 6px 6px 0",
                  }}>
                    <Info size={11} style={{ marginTop: "1px", flexShrink: 0, color: intentColor }} />
                    {ins}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Meta row */}
      <div style={{ display: "flex", gap: "7px", alignItems: "center", paddingLeft: isUser ? 0 : "2px", flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.65rem", color: "#94a3b8" }}>{fmtTs(msg.timestamp)}</span>
        {!isUser && <IntentBadge intent={msg.intent} confidence={msg.intent_confidence} />}
        {!isUser && (
          <SpeakerButton
            msgId={msg.id} text={msg.content} language={language}
            speakingId={speakingId} setSpeakingId={setSpeakingId}
          />
        )}
      </div>

      {/* Suggestion chips */}
      {!isUser && msg.suggestions && msg.suggestions.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "5px", maxWidth: "88%" }}>
          {msg.suggestions.map((s) => {
            const label = s.replace(/^(Ask|Try): /, "");
            return (
              <button key={s} onClick={() => onSuggestion(label)}
                style={{ fontSize: "0.71rem", padding: "4px 11px", borderRadius: "12px", border: "1px solid #bfdbfe", background: "#eff6ff", color: "#1d4ed8", cursor: "pointer", fontWeight: 600, transition: "background 0.15s" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "#dbeafe"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "#eff6ff"; }}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Role / Language selectors ─────────────────────────────────────────────────

const ROLES    = ["admin", "field_staff", "citizen"] as const;
const LANGS    = ["English", "Telugu", "Hindi", "Tamil", "Kannada"] as const;
const ROLE_LABELS: Record<string, string> = { admin: "Admin", field_staff: "Field Staff", citizen: "Citizen" };

function RolePill({ role, active, onClick }: { role: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      fontSize: "0.68rem", padding: "3px 10px", borderRadius: "10px", border: "none", cursor: "pointer", fontWeight: 700,
      background: active ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.12)",
      color: active ? "#fff" : "rgba(255,255,255,0.65)",
      transition: "background 0.15s",
    }}>{ROLE_LABELS[role] ?? role}</button>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

const WELCOME: ChatMessage = {
  id: "welcome", role: "assistant", timestamp: Date.now(),
  content: "**Namaste! I'm SARATHI** — your AI assistant for the Public Distribution System.\n\nI can help you with:\n- 📦 **Stock levels** and demand forecasts\n- ⚠️ **Anomaly detection** and compliance\n- 🧾 **Entitlements** and distribution schedules\n- 📍 **FPS shop locations** and grievance filing\n\nAsk me anything in **English, Telugu, Hindi, Tamil, or Kannada**!",
  suggestions: ["Show stock levels in Chittoor", "Predict demand for Fine Rice", "Check anomalies today"],
};

export function FloatingBot() {
  const [isOpen,     setIsOpen]     = useState(false);
  const [role,       setRole]       = useState<typeof ROLES[number]>("admin");
  const [language,   setLanguage]   = useState<typeof LANGS[number]>("English");
  const [input,      setInput]      = useState("");
  const [sessionId,  setSessionId]  = useState<string | null>(null);
  const [messages,   setMessages]   = useState<ChatMessage[]>([WELCOME]);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [autoSpeak,  setAutoSpeak]  = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, isOpen]);

  // Stop speech when window closes
  useEffect(() => { if (!isOpen) { stopSpeech(); setSpeakingId(null); } }, [isOpen]);

  const sendMutation = useMutation({
    mutationFn: (text: string) => chatWithBot(text, role, sessionId, "web-user", language),
    onSuccess: (data, text) => {
      if (!sessionId) setSessionId(data.session_id);
      const botId = genId();
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== "__pending__"),
        { id: genId(), role: "user",      content: text, timestamp: Date.now() - 60 },
        { id: botId,   role: "assistant", content: data.response,
          intent: data.intent, intent_confidence: data.intent_confidence,
          source: data.source, insights: data.insights,
          suggestions: data.suggestions,
          data: data.data as Record<string, unknown>,
          timestamp: Date.now() },
      ]);
      if (autoSpeak) {
        setSpeakingId(botId);
        speak(data.response, language, undefined, () => setSpeakingId(null));
      }
    },
    onError: (_err, text) => {
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== "__pending__"),
        { id: genId(), role: "user",      content: text, timestamp: Date.now() - 60 },
        { id: genId(), role: "assistant", content: "⚠️ Could not reach SARATHI (port 8004). Please check the service.", timestamp: Date.now() },
      ]);
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => sessionId ? clearBotSession(sessionId) : Promise.resolve({ session_id: "", status: "cleared" }),
    onSuccess: () => {
      setSessionId(null);
      setMessages([{ ...WELCOME, id: genId(), timestamp: Date.now() }]);
    },
  });

  function send(text: string) {
    const t = text.trim();
    if (!t || sendMutation.isPending) return;
    setInput("");
    setMessages((prev) => [...prev, { id: "__pending__", role: "user", content: t, timestamp: Date.now() }]);
    sendMutation.mutate(t);
  }

  return (
    <div style={{ position: "fixed", bottom: "28px", right: "28px", zIndex: 9999, display: "flex", flexDirection: "column", alignItems: "flex-end" }}>

      {/* ── Chat Window ───────────────────────────────────────────────────── */}
      {isOpen && (
        <div style={{
          width: "420px", height: "680px",
          background: "#f8fafc",
          borderRadius: "22px",
          boxShadow: "0 24px 80px rgba(0,0,0,0.18), 0 4px 20px rgba(0,0,0,0.08)",
          display: "flex", flexDirection: "column",
          overflow: "hidden",
          marginBottom: "18px",
          border: "1px solid rgba(255,255,255,0.7)",
          animation: "slideUp 0.28s cubic-bezier(0.16,1,0.3,1)",
        }}>
          <style>{`
            @keyframes slideUp { from { opacity:0; transform:translateY(20px) scale(0.97); } to { opacity:1; transform:translateY(0) scale(1); } }
          `}</style>

          {/* Header */}
          <header style={{ background: "linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)", color: "#fff", padding: "14px 18px 10px", flexShrink: 0 }}>
            {/* Top row */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "11px" }}>
                <div style={{ width: "38px", height: "38px", borderRadius: "12px", background: "rgba(255,255,255,0.22)", display: "flex", alignItems: "center", justifyContent: "center", backdropFilter: "blur(6px)" }}>
                  <MessageSquare size={19} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 700, letterSpacing: "-0.01em" }}>SARATHI</h3>
                  <p style={{ margin: 0, fontSize: "0.72rem", opacity: 0.75 }}>PDS AI Assistant · Online</p>
                </div>
              </div>
              <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                <button
                  title={autoSpeak ? "Auto-voice ON — click to turn off" : "Auto-voice OFF — click to turn on"}
                  onClick={() => { setAutoSpeak((v) => !v); if (autoSpeak) { stopSpeech(); setSpeakingId(null); } }}
                  style={{ background: autoSpeak ? "rgba(255,255,255,0.28)" : "transparent", border: autoSpeak ? "1px solid rgba(255,255,255,0.5)" : "1px solid transparent", borderRadius: "8px", color: "#fff", cursor: "pointer", opacity: autoSpeak ? 1 : 0.6, display: "flex", alignItems: "center", padding: "3px 7px", gap: "4px", fontSize: "0.65rem", fontWeight: 700 }}
                >
                  <Mic size={13} />
                  {autoSpeak ? "VOICE ON" : "VOICE"}
                </button>
                <button title="Clear session" onClick={() => clearMutation.mutate()} style={{ background: "transparent", border: "none", color: "#fff", cursor: "pointer", opacity: 0.65, display: "flex", alignItems: "center" }}><Trash2 size={16} /></button>
                <button title="Close" onClick={() => setIsOpen(false)} style={{ background: "transparent", border: "none", color: "#fff", cursor: "pointer", opacity: 0.65, display: "flex", alignItems: "center" }}><X size={18} /></button>
              </div>
            </div>

            {/* Role pills */}
            <div style={{ display: "flex", gap: "5px", alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ fontSize: "0.62rem", opacity: 0.6, marginRight: "2px" }}>Role:</span>
              {ROLES.map((r) => (
                <RolePill key={r} role={r} active={role === r} onClick={() => setRole(r)} />
              ))}
              <div style={{ flexGrow: 1 }} />
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value as typeof LANGS[number])}
                style={{ fontSize: "0.68rem", background: "rgba(255,255,255,0.15)", border: "1px solid rgba(255,255,255,0.3)", borderRadius: "8px", color: "#fff", padding: "2px 6px", cursor: "pointer", outline: "none" }}
              >
                {LANGS.map((l) => <option key={l} value={l} style={{ color: "#1e293b", background: "#fff" }}>{l}</option>)}
              </select>
            </div>
          </header>

          {/* Messages */}
          <div style={{ flex: 1, padding: "18px 16px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "16px", background: "#f1f5f9", scrollbarWidth: "thin" }}>
            {messages.map((m) => (
              <MessageBubble key={m.id} msg={m} onSuggestion={send}
                language={language} speakingId={speakingId} setSpeakingId={setSpeakingId} />
            ))}
            {sendMutation.isPending && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div style={{ padding: "12px 14px 14px", background: "#fff", borderTop: "1px solid #e2e8f0", flexShrink: 0 }}>
            <div style={{ display: "flex", gap: "8px", alignItems: "center", background: "#f8fafc", borderRadius: "26px", padding: "6px 6px 6px 16px", border: "1.5px solid #e2e8f0", transition: "border-color 0.15s" }}
              onFocusCapture={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = "#2563eb"; }}
              onBlurCapture={(e)  => { (e.currentTarget as HTMLDivElement).style.borderColor = "#e2e8f0"; }}
            >
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
                placeholder={`Ask SARATHI in ${language}…`}
                style={{ flex: 1, border: "none", background: "transparent", outline: "none", fontSize: "0.9rem", color: "#1e293b" }}
              />
              <button
                onClick={() => send(input)}
                disabled={!input.trim() || sendMutation.isPending}
                style={{
                  width: "36px", height: "36px", borderRadius: "50%",
                  background: input.trim() ? "linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)" : "#e2e8f0",
                  border: "none", color: input.trim() ? "#fff" : "#94a3b8",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  cursor: input.trim() ? "pointer" : "not-allowed",
                  transition: "background 0.2s",
                  flexShrink: 0,
                }}
              >
                <Send size={16} />
              </button>
            </div>
            <p style={{ margin: "6px 0 0", fontSize: "0.62rem", color: "#94a3b8", textAlign: "center" }}>
              Powered by GradientBoosting ML · IsolationForest Anomaly · LangChain
            </p>
          </div>
        </div>
      )}

      {/* ── Floating Toggle Button ──────────────────────────────────────── */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        title={isOpen ? "Close SARATHI" : "Open SARATHI"}
        style={{
          width: "62px", height: "62px", borderRadius: "50%",
          background: "linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)",
          color: "#fff", border: "none", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 8px 26px rgba(30,58,138,0.45)",
          transition: "transform 0.2s, box-shadow 0.2s",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.transform = "scale(1.07)"; e.currentTarget.style.boxShadow = "0 12px 32px rgba(30,58,138,0.55)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)";    e.currentTarget.style.boxShadow = "0 8px 26px rgba(30,58,138,0.45)"; }}
      >
        {isOpen ? <X size={26} /> : <MessageSquare size={26} />}
      </button>

    </div>
  );
}
