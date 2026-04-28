import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login as apiLogin } from "../api";
import { useAuth } from "../context/AuthContext";
import type { UserRole } from "../types";
import { Eye, EyeOff } from "lucide-react";

const DEMO_ACCOUNTS: { role: UserRole; username: string; password: string; label: string; color: string }[] = [
  { role: "STATE_ADMIN",        username: "state_admin",  password: "Admin@1234",  label: "State Admin",        color: "#0B3A73" },
  { role: "DISTRICT_ADMIN",     username: "dist_admin",   password: "Admin@1234",  label: "District Admin",     color: "#1E86D6" },
  { role: "MANDAL_ADMIN",       username: "mandal_admin", password: "Admin@1234",  label: "Mandal Admin",       color: "#49C4FF" },
  { role: "AFSO",               username: "afso_user",    password: "Admin@1234",  label: "AFSO",               color: "#059669" },
  { role: "FPS_DEALER",         username: "fps_dealer",   password: "Dealer@1234", label: "FPS Dealer",         color: "#F0B34A" },
  { role: "RATION_CARD_HOLDER", username: "beneficiary",  password: "User@1234",   label: "Beneficiary",        color: "#EF4444" },
];

const ROLE_BADGE: Record<UserRole, string> = {
  STATE_ADMIN:        "bg-violet-600",
  DISTRICT_ADMIN:     "bg-blue-600",
  MANDAL_ADMIN:       "bg-cyan-600",
  AFSO:               "bg-emerald-600",
  FPS_DEALER:         "bg-amber-600",
  RATION_CARD_HOLDER: "bg-red-600",
};

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [loading,  setLoading]  = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const resp = await apiLogin(username, password);
      login(resp);
      navigate("/", { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const fillDemo = (u: string, p: string) => {
    setUsername(u);
    setPassword(p);
    setError(null);
  };

  return (
    <div className="app-container">
      <div className="tricolor-strip"></div>
      
      {/* Top White Bar */}
      {/* Top White Bar */}
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", padding: "6px 8px", minHeight: "44px", borderBottom: "1px solid var(--line)", background: "rgba(255,255,255,0.92)", backdropFilter: "blur(14px)", overflow: "hidden" }}>
        
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

      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "24px" }}>
        
        {/* Main Content Area */}
        <div style={{ width: "100%", maxWidth: 900, display: "flex", gap: 64, flexWrap: "wrap", alignItems: "center", justifyContent: "center" }}>

          {/* Left: Logos Section */}
          <div style={{ flex: "1 1 300px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "12px", width: "100%", paddingBottom: "20px", borderBottom: "1px solid var(--line)", marginBottom: "8px" }}>
              <div style={{ display: "inline-flex", background: "#fff", border: "1px solid var(--line)", borderRadius: "6px", padding: "8px 20px", boxShadow: "var(--shadow)" }}>
                <img src="/logo/logo-3.png" alt="Company Logo" style={{ height: "32px", objectFit: "contain" }} />
              </div>

              <div style={{ color: "var(--saffron)", fontSize: "0.75rem", fontWeight: 800, letterSpacing: "0.08em", textTransform: "uppercase" }}>presents</div>

              <div style={{ background: "#fff", borderRadius: "8px", padding: "16px 24px", boxShadow: "var(--shadow)", border: "1px solid var(--line)", width: "100%", display: "flex", justifyContent: "center" }}>
                <img src="/logo/LOGO-v2.png" alt="AP SARAthi Logo" style={{ width: "100%", height: "auto", objectFit: "contain" }} />
              </div>
            </div>

            <div className="brand" style={{ textAlign: "center", width: "100%", marginBottom: "20px" }}>
              <p className="eyebrow" style={{ fontSize: "0.6rem", lineHeight: "1.3" }}>Smart AI Resource & Allotment Tracking & Help Interface</p>
              <h1 style={{ fontSize: "2rem" }}>AP SARAthi</h1>
              <p className="muted" style={{ marginTop: "12px", fontSize: "0.95rem" }}>
                Sign in to access your administrative dashboard.
              </p>
            </div>
          </div>

          {/* Right: login form */}
          <div className="panel" style={{ flex: "1 1 360px", padding: "40px", maxWidth: "420px" }}>
            <div style={{ marginBottom: 32, textAlign: "center" }}>
              <h2 style={{ margin: "0 0 8px 0", fontSize: "1.5rem", color: "var(--navy)", fontWeight: 800 }}>Sign in to continue</h2>
              <p className="muted" style={{ margin: 0, fontWeight: 500 }}>Enter your credentials to access the dashboard</p>
            </div>

            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <div className="field">
                <label style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--navy)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Username</label>
                <input
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  required
                  placeholder="Enter username"
                />
              </div>
              <div className="field">
                <label style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--navy)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Password</label>
                <div style={{ position: "relative" }}>
                  <input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    required
                    placeholder="Enter password"
                    style={{ paddingRight: 44 }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(v => !v)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    style={{
                      position: "absolute",
                      right: 10,
                      top: "50%",
                      transform: "translateY(-50%)",
                      width: 30,
                      height: 30,
                      borderRadius: 10,
                      border: "1px solid var(--line)",
                      background: "rgba(255,255,255,0.65)",
                      backdropFilter: "blur(10px)",
                      display: "grid",
                      placeItems: "center",
                      cursor: "pointer",
                      color: "var(--muted)",
                    }}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              {error && (
                <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "8px", padding: "12px 16px", color: "var(--red)", fontSize: "0.9rem", fontWeight: 600 }}>
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="primary-button"
                style={{ width: "100%", marginTop: "8px", opacity: loading ? 0.7 : 1 }}
              >
                {loading ? "Signing in..." : "Sign In"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
