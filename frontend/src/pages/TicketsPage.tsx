import { useState } from "react";
import { Filter, Search, MoreVertical, X, AlertCircle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { fetchTickets } from "../api";
import type { CallCentreTicket } from "../types";

const priorityColor = (p: string) => {
  if (p === "HIGH") return "var(--red)";
  if (p === "MEDIUM") return "var(--amber)";
  return "var(--green)";
};

const statusColor = (s: string) => {
  if (s === "OPEN") return "var(--blue)";
  if (s === "IN_PROGRESS") return "var(--amber)";
  if (s === "RESOLVED") return "var(--green)";
  return "var(--muted)";
};

export function TicketsPage() {
  const { data, isLoading } = useQuery({ queryKey: ["tickets"], queryFn: fetchTickets });
  const [filter, setFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [selectedTicket, setSelectedTicket] = useState<CallCentreTicket | null>(null);

  const tickets = data?.tickets ?? [];
  const filtered = tickets.filter(t => 
    (filter === "ALL" || t.status === filter) &&
    (t.ticket_id.toLowerCase().includes(search.toLowerCase()) || 
     t.caller_name.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: "24px", height: "100%", position: "relative" }}>
      
      {/* Header & Controls */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <p className="eyebrow">Service Desk</p>
          <h2 style={{ fontSize: "2rem", color: "var(--navy)", margin: "4px 0 0" }}>Ticket Management</h2>
        </div>
        
        <div style={{ display: "flex", gap: "12px" }}>
          <div style={{ display: "flex", alignItems: "center", background: "var(--control-glass)", borderRadius: "10px", padding: "8px 16px", border: "1px solid var(--line)", boxShadow: "0 14px 30px rgba(30,134,214,0.10)", backdropFilter: "blur(10px)" }}>
            <Search size={16} color="var(--muted)" />
            <input 
              type="text" 
              placeholder="Search ID or Name..." 
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ border: "none", background: "transparent", outline: "none", marginLeft: "8px", fontSize: "0.9rem", width: "200px" }} 
            />
          </div>
          <button style={{ display: "flex", alignItems: "center", gap: "8px", background: "var(--control-glass)", border: "1px solid var(--line)", padding: "10px 16px", borderRadius: "10px", cursor: "pointer", fontWeight: 800, color: "var(--text)", boxShadow: "0 14px 30px rgba(30,134,214,0.10)", backdropFilter: "blur(10px)" }}>
            <Filter size={16} /> Filters
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="cc-tabs" style={{ maxWidth: "fit-content" }}>
        {["ALL", "OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"].map(s => (
          <button key={s} className={`cc-tab ${filter === s ? "active" : ""}`} onClick={() => setFilter(s)}>
            {s.replace("_", " ")}
          </button>
        ))}
      </div>

      {/* Table */}
      <div style={{ background: "var(--card-glass)", borderRadius: "16px", border: "1px solid var(--line)", boxShadow: "var(--shadow)", overflow: "hidden", flex: 1, backdropFilter: "blur(12px)" }}>
        {isLoading ? (
          <div style={{ padding: "40px", textAlign: "center", color: "var(--muted)" }}>Loading tickets...</div>
        ) : (
          <div className="table-wrap" style={{ margin: 0, border: "none" }}>
            <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead style={{ background: "var(--bg-deep)", borderBottom: "2px solid var(--line)" }}>
                <tr>
                  <th style={{ padding: "16px 20px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Ticket ID</th>
                  <th style={{ padding: "16px 20px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Caller Name</th>
                  <th style={{ padding: "16px 20px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Category</th>
                  <th style={{ padding: "16px 20px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Priority</th>
                  <th style={{ padding: "16px 20px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Status</th>
                  <th style={{ padding: "16px 20px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Assigned</th>
                  <th style={{ padding: "16px 20px" }}></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(t => (
                  <tr 
                    key={t.ticket_id} 
                    onClick={() => setSelectedTicket(t)}
                    style={{ borderBottom: "1px solid var(--line)", cursor: "pointer", transition: "background 0.2s" }}
                    onMouseEnter={e => e.currentTarget.style.background = "var(--bg)"}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                  >
                    <td style={{ padding: "16px 20px", fontWeight: 700, color: "var(--navy)" }}>{t.ticket_id}</td>
                    <td style={{ padding: "16px 20px", fontWeight: 600 }}>{t.caller_name}</td>
                    <td style={{ padding: "16px 20px", color: "var(--muted)" }}>{t.category}</td>
                    <td style={{ padding: "16px 20px" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", background: `${priorityColor(t.priority)}15`, color: priorityColor(t.priority), padding: "4px 10px", borderRadius: "12px", fontSize: "0.75rem", fontWeight: 800 }}>
                        <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: priorityColor(t.priority) }} />
                        {t.priority}
                      </span>
                    </td>
                    <td style={{ padding: "16px 20px" }}>
                      <span style={{ display: "inline-block", background: `${statusColor(t.status)}15`, color: statusColor(t.status), border: `1px solid ${statusColor(t.status)}30`, padding: "4px 10px", borderRadius: "6px", fontSize: "0.75rem", fontWeight: 800 }}>
                        {t.status.replace("_", " ")}
                      </span>
                    </td>
                    <td style={{ padding: "16px 20px", fontSize: "0.9rem" }}>{t.assigned_team}</td>
                    <td style={{ padding: "16px 20px", textAlign: "right", color: "var(--muted)" }}>
                      <MoreVertical size={18} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Drawer Overlay */}
      {selectedTicket && (
        <>
          <div 
            style={{ position: "fixed", inset: 0, background: "rgba(15, 23, 42, 0.4)", backdropFilter: "blur(4px)", zIndex: 1000 }}
            onClick={() => setSelectedTicket(null)}
          />
          <div style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: "450px", background: "#fff", zIndex: 1001, boxShadow: "-10px 0 30px rgba(0,0,0,0.1)", display: "flex", flexDirection: "column", transform: "translateX(0)", transition: "transform 0.3s ease-out" }}>
            
            <header style={{ padding: "24px", borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center", background: "var(--bg)" }}>
              <div>
                <p className="eyebrow" style={{ marginBottom: "4px" }}>Ticket Details</p>
                <h3 style={{ margin: 0, color: "var(--navy)", fontSize: "1.2rem" }}>{selectedTicket.ticket_id}</h3>
              </div>
              <button onClick={() => setSelectedTicket(null)} style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--muted)", padding: "8px", borderRadius: "50%" }} onMouseEnter={e => e.currentTarget.style.background = "#e2e8f0"} onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                <X size={20} />
              </button>
            </header>

            <div style={{ padding: "24px", flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: "24px" }}>
              
              {/* Status Banner */}
              <div style={{ background: `${statusColor(selectedTicket.status)}10`, border: `1px solid ${statusColor(selectedTicket.status)}30`, padding: "16px", borderRadius: "12px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 700, color: statusColor(selectedTicket.status) }}>{selectedTicket.status.replace("_", " ")}</span>
                <span style={{ fontSize: "0.85rem", color: "var(--muted)", fontWeight: 600 }}>ETA: {selectedTicket.resolution_eta_hours}h</span>
              </div>

              {/* Info Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                <div>
                  <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 700, textTransform: "uppercase" }}>Caller</span>
                  <p style={{ margin: "4px 0 0", fontWeight: 600 }}>{selectedTicket.caller_name}</p>
                </div>
                <div>
                  <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 700, textTransform: "uppercase" }}>Priority</span>
                  <p style={{ margin: "4px 0 0", fontWeight: 700, color: priorityColor(selectedTicket.priority) }}>{selectedTicket.priority}</p>
                </div>
                <div>
                  <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 700, textTransform: "uppercase" }}>Language</span>
                  <p style={{ margin: "4px 0 0", fontWeight: 600 }}>{selectedTicket.language}</p>
                </div>
                <div>
                  <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 700, textTransform: "uppercase" }}>Sentiment</span>
                  <p style={{ margin: "4px 0 0", fontWeight: 600, display: "flex", alignItems: "center", gap: "4px" }}>
                    {selectedTicket.sentiment_score < -0.3 && <AlertCircle size={14} color="var(--red)" />}
                    {selectedTicket.sentiment_label} ({selectedTicket.sentiment_score.toFixed(2)})
                  </p>
                </div>
              </div>

              <hr style={{ border: "none", borderTop: "1px dashed var(--line)" }} />

              {/* Description */}
              <div>
                <span style={{ fontSize: "0.85rem", color: "var(--navy)", fontWeight: 800, textTransform: "uppercase" }}>Summary</span>
                <p style={{ margin: "8px 0 0", lineHeight: 1.6, color: "var(--text)", fontSize: "0.95rem" }}>
                  {selectedTicket.summary}
                </p>
              </div>

              <div>
                <span style={{ fontSize: "0.85rem", color: "var(--navy)", fontWeight: 800, textTransform: "uppercase" }}>Next Action</span>
                <div style={{ background: "var(--bg)", padding: "16px", borderRadius: "8px", borderLeft: "4px solid var(--blue)", marginTop: "8px" }}>
                  <p style={{ margin: 0, fontSize: "0.9rem", fontWeight: 500 }}>{selectedTicket.next_action}</p>
                </div>
              </div>

              {selectedTicket.transcript && (
                <div>
                  <span style={{ fontSize: "0.85rem", color: "var(--navy)", fontWeight: 800, textTransform: "uppercase" }}>Call Transcript</span>
                  <div style={{ background: "#f1f5f9", padding: "16px", borderRadius: "8px", marginTop: "8px", border: "1px solid #e2e8f0" }}>
                    <p style={{ margin: 0, fontSize: "0.85rem", fontStyle: "italic", color: "var(--muted)", lineHeight: 1.6 }}>"{selectedTicket.transcript}"</p>
                  </div>
                </div>
              )}
            </div>

            <footer style={{ padding: "20px 24px", borderTop: "1px solid var(--line)", background: "var(--bg)", display: "flex", gap: "12px" }}>
              <button style={{ flex: 1, padding: "12px", borderRadius: "8px", border: "1px solid var(--line)", background: "#fff", fontWeight: 600, cursor: "pointer", color: "var(--navy)" }}>Escalate</button>
              <button style={{ flex: 2, padding: "12px", borderRadius: "8px", border: "none", background: "var(--primary-gradient)", color: "#fff", fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 12px rgba(30,58,138,0.3)" }}>Mark Resolved</button>
            </footer>
          </div>
        </>
      )}
    </section>
  );
}
