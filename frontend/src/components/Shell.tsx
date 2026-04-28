import { NavLink, useNavigate } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import type { PropsWithChildren } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../context/AuthContext";
import { NAV_ROUTES } from "../rbac";
import type { UserRole } from "../types";
import { fetchCCNotifications } from "../api";
import { 
  Search, Bell, User as UserIcon, LayoutDashboard, 
  BarChart2, MessageSquare, HeadphonesIcon, 
  Ticket, Users, Settings, LogOut, Map, DatabaseZap
} from "lucide-react";
import { FloatingBot } from "../pages/BotPage";

const ROLE_COLOR: Record<UserRole, string> = {
  STATE_ADMIN:        "#072B57", // Deep Brand Blue
  DISTRICT_ADMIN:     "#10B981", // Emerald Green
  MANDAL_ADMIN:       "#F6C54C", // Gold
  AFSO:               "#059669",
  FPS_DEALER:         "#F0B34A", // Saffron
  RATION_CARD_HOLDER: "#6B7280", // Gray
};

const ROLE_LABEL: Record<UserRole, string> = {
  STATE_ADMIN:        "State Admin",
  DISTRICT_ADMIN:     "District Admin",
  MANDAL_ADMIN:       "Mandal Admin",
  AFSO:               "AFSO",
  FPS_DEALER:         "FPS Dealer",
  RATION_CARD_HOLDER: "Citizen",
};

const NAV_ICONS: Record<string, React.ReactNode> = {
  "Overview":     <LayoutDashboard size={14} />,
  "Distribution": <DatabaseZap size={14} />,
  "SMARTAllot":   <BarChart2 size={14} />,
  "Command Map":  <Map size={14} />,
  "Anomalies":    <BarChart2 size={14} />,
  "Call Centre":  <HeadphonesIcon size={14} />,
  "Tickets":      <Ticket size={14} />,
  "Users":        <Users size={14} />,
  "Settings":     <Settings size={14} />,
};

function GovHeader() {
  return (
    <div style={{ display: "flex", flexDirection: "column", width: "100%", zIndex: 1000, position: "fixed", top: 0, left: 0, right: 0, backgroundColor: "rgba(255,255,255,0.92)", backdropFilter: "blur(14px)" }}>
      {/* Top Colored Stripes */}
      <div style={{ display: "flex", width: "100%", height: "3px" }}>
        <div style={{ flex: 1, backgroundColor: "var(--saffron)" }}></div>
        <div style={{ width: "20%" }}></div>
        <div style={{ flex: 1, backgroundColor: "var(--green)" }}></div>
      </div>
      
      {/* Top White Bar */}
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", padding: "6px 8px", minHeight: "44px", borderBottom: "1px solid var(--line)", overflow: "hidden" }}>
        
        {/* India Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", paddingRight: "12px" }}>
          <img src="/logo/india-logo.png" alt="Emblem of India" style={{ height: "30px", objectFit: "contain" }} onError={(e) => { e.currentTarget.src = "/logo/india_emblem.svg"; }} />
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.55rem", fontWeight: 700, color: "var(--navy)", letterSpacing: "0.02em", whiteSpace: "nowrap" }}>GOVERNMENT OF INDIA</span>
            <span style={{ fontSize: "0.45rem", color: "var(--muted)", whiteSpace: "nowrap" }}>Department of Food & Public Distribution</span>
          </div>
        </div>
        
        {/* AP State Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", borderLeft: "1px solid var(--line)", paddingLeft: "12px", paddingRight: "12px" }}>
          <img src="/logo/ap-logo.webp" alt="AP Govt" style={{ height: "28px", objectFit: "contain" }} />
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.5rem", fontWeight: 700, color: "var(--navy)", letterSpacing: "0.02em", whiteSpace: "nowrap" }}>GOVT. OF ANDHRA PRADESH</span>
            <span style={{ fontSize: "0.45rem", color: "var(--muted)", whiteSpace: "nowrap" }}>Department of Food Security</span>
          </div>
        </div>

        {/* APSCSCL Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", borderLeft: "1px solid var(--line)", paddingLeft: "12px", paddingRight: "12px" }}>
          <img src="/logo/fcs-logo.png" alt="APSCSCL" style={{ height: "27px", objectFit: "contain", transform: "scale(1.9)" }} />
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.5rem", fontWeight: 700, color: "var(--navy)", letterSpacing: "0.02em", whiteSpace: "nowrap" }}>APSCSCL</span>
            <span style={{ fontSize: "0.45rem", color: "var(--muted)", whiteSpace: "nowrap" }}>Andhra Pradesh State Civil Supplies Corporation Limited</span>
          </div>
        </div>

        {/* PMGKAY Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", borderLeft: "1px solid var(--line)", paddingLeft: "12px", paddingRight: "12px" }}>
          <img src="/logo/g.png" alt="PMGKAY" style={{ height: "27px", objectFit: "contain", transform: "scale(1.3)" }} onError={(e) => { e.currentTarget.src = "/logo/logo-3.png"; }} />
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.5rem", fontWeight: 700, color: "var(--navy)", letterSpacing: "0.02em", whiteSpace: "nowrap" }}>PMGKAY</span>
            <span style={{ fontSize: "0.45rem", color: "var(--muted)", whiteSpace: "nowrap" }}>Pradhan Mantri Garib Kalyan Anna Yojana</span>
          </div>
        </div>
        
        {/* RTIH Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", borderLeft: "1px solid var(--line)", paddingLeft: "12px", paddingRight: "12px" }}>
          <img src="/logo/rtih-logo.svg" alt="RTIH" style={{ height: "16px", objectFit: "contain" }} />
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.5rem", fontWeight: 700, color: "var(--navy)", letterSpacing: "0.02em", whiteSpace: "nowrap" }}>RATAN TATA INNOVATION HUB</span>
            <span style={{ fontSize: "0.45rem", color: "var(--muted)", whiteSpace: "nowrap" }}>Govt. of Andhra Pradesh</span>
          </div>
        </div>

        {/* Agile CAS Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", borderLeft: "1px solid var(--line)", paddingLeft: "12px" }}>
          <img src="/logo/logo-3.png" alt="Agile CAS" style={{ height: "24px", objectFit: "contain" }} />
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.5rem", fontWeight: 700, color: "var(--navy)", letterSpacing: "0.02em", whiteSpace: "nowrap" }}>AGILE CAS</span>
            <span style={{ fontSize: "0.45rem", color: "var(--muted)", whiteSpace: "nowrap" }}>Consultancy and Advisory Services</span>
          </div>
        </div>

      </div>
      {/* Bottom Navy Bar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0 16px", height: "24px", background: "var(--blue-gradient)", borderBottom: "2px solid var(--saffron)", color: "#fff" }}>
        <span style={{ fontSize: "0.6rem", fontWeight: 700, letterSpacing: "0.05em" }}>PUBLIC DISTRIBUTION SYSTEM COMMAND CENTRE</span>
        <span style={{ fontSize: "0.6rem", fontWeight: 700, letterSpacing: "0.05em" }}>AP SARATHI PORTAL</span>
      </div>
    </div>
  );
}


export function Shell({ children }: PropsWithChildren) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [notifOpen, setNotifOpen] = useState(false);
  const notifWrapRef = useRef<HTMLDivElement | null>(null);

  const notifQ = useQuery({
    queryKey: ["cc-notifications-shell"],
    queryFn: () => fetchCCNotifications(20),
    enabled: notifOpen,
    staleTime: 10_000,
    refetchInterval: notifOpen ? 15_000 : false,
  });

  useEffect(() => {
    function onDocClick(ev: MouseEvent) {
      const el = notifWrapRef.current;
      if (!el) return;
      if (ev.target instanceof Node && !el.contains(ev.target)) setNotifOpen(false);
    }
    if (notifOpen) document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [notifOpen]);

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="app-container" style={{ display: "flex", minHeight: "100vh", background: "var(--bg)", paddingTop: "76px" }}>
      <GovHeader />
      {/* SIDEBAR */}
      <aside className="sidebar" style={{ width: "188px", background: "linear-gradient(180deg, rgba(255,255,255,0.92) 0%, rgba(239,248,255,0.82) 100%)", borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column", position: "fixed", top: "76px", bottom: 0, zIndex: 100, boxShadow: "4px 0 15px rgba(0,0,0,0.03)", backdropFilter: "blur(10px)" }}>
        <div style={{ padding: "16px 13px", display: "flex", alignItems: "center", gap: "8px", borderBottom: "1px solid var(--line)" }}>
          <img src="/logo/LOGO-v2.png" alt="AP SARAthi" style={{ height: "42px", width: "42px", objectFit: "contain", flexShrink: 0 }} />
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 800, color: "var(--navy)", letterSpacing: "0.02em" }}>SARAthi Portal</span>
            <span style={{ fontSize: "0.45rem", color: "var(--saffron)", fontWeight: 700, textTransform: "uppercase" }}>AP Food Civil Supplies</span>
          </div>
        </div>

        <nav style={{ padding: "16px 11px", display: "flex", flexDirection: "column", gap: "4px", flex: 1, overflowY: "auto" }}>
          {NAV_ROUTES.filter(r => !user || r.roles.includes(user.role)).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              style={({ isActive }) => ({
                display: "flex", alignItems: "center", gap: "8px", padding: "8px 11px", borderRadius: "7px", 
                color: isActive ? "#fff" : "var(--muted)",
                background: isActive ? "var(--primary-gradient)" : "transparent",
                fontWeight: isActive ? 600 : 500,
                fontSize: "0.65rem",
                transition: "all 0.2s ease",
                boxShadow: isActive ? "0 10px 18px rgba(30, 134, 214, 0.16)" : "none"
              })}
            >
              {NAV_ICONS[item.label] ?? <LayoutDashboard size={14} />}
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div style={{ padding: "13px 11px", borderTop: "1px solid var(--line)" }}>
          <button
            onClick={handleLogout}
            style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", background: "transparent", border: "1px solid var(--line)", borderRadius: "7px", padding: "8px", color: "var(--muted)", fontWeight: 600, fontSize: "0.6rem", cursor: "pointer", transition: "all 0.2s ease" }}
            onMouseEnter={e => { e.currentTarget.style.background = "#fff0f0"; e.currentTarget.style.color = "var(--red)"; e.currentTarget.style.borderColor = "var(--red)"; }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--muted)"; e.currentTarget.style.borderColor = "var(--line)"; }}
          >
            <LogOut size={12} />
            SIGN OUT
          </button>
        </div>
      </aside>

      {/* MAIN CONTENT WRAPPER */}
      <div style={{ flex: 1, marginLeft: "188px", display: "flex", flexDirection: "column", minWidth: 0 }}>
        
        {/* TOP BAR */}
        <header style={{ position: "sticky", top: 0, zIndex: 50, background: "rgba(255,255,255,0.9)", backdropFilter: "blur(12px)", borderBottom: "1px solid var(--line)", padding: "11px 22px", display: "flex", alignItems: "center", justifyContent: "space-between", boxShadow: "0 1px 3px rgba(0,0,0,0.02)" }}>
          
          <div style={{ display: "flex", alignItems: "center", background: "var(--bg-deep)", borderRadius: "16px", padding: "5px 11px", width: "268px", border: "1px solid var(--line)", transition: "all 0.2s ease" }}>
            <Search size={12} color="var(--muted)" />
            <input type="text" placeholder="Search across portal..." style={{ border: "none", background: "transparent", outline: "none", marginLeft: "7px", width: "100%", fontSize: "0.6rem", color: "var(--text)" }} />
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <div ref={notifWrapRef} style={{ position: "relative" }}>
              <button
                onClick={() => setNotifOpen((v) => !v)}
                style={{ background: "transparent", border: "none", cursor: "pointer", position: "relative", color: "var(--muted)", padding: 6, borderRadius: 10 }}
                aria-label="Notifications"
              >
                <Bell size={15} />
                <span style={{ position: "absolute", top: "4px", right: "4px", background: "var(--red)", width: "6px", height: "6px", borderRadius: "50%" }}></span>
              </button>
              {notifOpen && (
                <div style={{
                  position: "absolute",
                  right: 0,
                  top: 36,
                  width: 340,
                  maxHeight: 420,
                  overflow: "auto",
                  background: "rgba(255,255,255,0.92)",
                  border: "1px solid var(--line)",
                  borderRadius: 14,
                  boxShadow: "0 18px 60px rgba(0,0,0,0.18)",
                  zIndex: 200,
                  backdropFilter: "blur(12px)",
                }}>
                  <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ fontWeight: 900, color: "var(--navy)" }}>Notifications</div>
                    <button onClick={() => setNotifOpen(false)} style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--muted)" }} aria-label="Close notifications">
                      X
                    </button>
                  </div>
                  {notifQ.isLoading && <p className="state" style={{ margin: 0, padding: 14 }}>Loading...</p>}
                  {notifQ.isError && <p className="state error" style={{ margin: 0, padding: 14 }}>Notifications service offline (port 8005).</p>}
                  {!notifQ.isLoading && !notifQ.isError && (notifQ.data?.notifications?.length ?? 0) === 0 && (
                    <p className="state" style={{ margin: 0, padding: 14 }}>No recent notifications.</p>
                  )}
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    {(notifQ.data?.notifications ?? []).map((n: any) => (
                      <div key={n.id ?? n.ts ?? Math.random()} style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)" }}>
                        <div style={{ fontWeight: 800, color: "var(--navy)", fontSize: 13 }}>{n.title ?? n.kind ?? "Alert"}</div>
                        <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 4 }}>{n.message ?? n.text ?? ""}</div>
                        <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 6 }}>{n.ts ?? ""}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {user && (
              <div style={{ display: "flex", alignItems: "center", gap: "8px", paddingLeft: "16px", borderLeft: "1px solid var(--line)" }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
                  <span style={{ fontSize: "0.6rem", fontWeight: 700, color: "var(--navy)" }}>{user.full_name}</span>
                  <span style={{ fontSize: "0.5rem", fontWeight: 700, color: ROLE_COLOR[user.role], background: `${ROLE_COLOR[user.role]}15`, padding: "1px 5px", borderRadius: "8px", marginTop: "1px" }}>
                    {ROLE_LABEL[user.role]}
                  </span>
                </div>
                <div style={{ width: "27px", height: "27px", borderRadius: "50%", background: ROLE_COLOR[user.role], display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, boxShadow: "0 2px 5px rgba(0,0,0,0.15)" }}>
                  <UserIcon size={14} />
                </div>
              </div>
            )}
          </div>
        </header>

        {/* PAGE CONTENT */}
        <main className="content" style={{ padding: "32px", flex: 1, minHeight: "calc(100vh - 76px)" }}>
          {children}
        </main>
        
        {/* GLOBAL CHAT WIDGET */}
        <FloatingBot />
      </div>
    </div>
  );
}
