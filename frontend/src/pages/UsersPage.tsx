import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, MoreVertical, Shield, UserPlus, X } from "lucide-react";
import { fetchUsers, registerUser, updateUser } from "../api";
import type { AuthUser, UserRole } from "../types";

const roleBadgeColor = (r: UserRole) => {
  switch (r) {
    case "STATE_ADMIN": return "var(--blue)";
    case "DISTRICT_ADMIN": return "var(--green)";
    case "MANDAL_ADMIN": return "var(--gold)";
    case "FPS_DEALER": return "var(--saffron)";
    case "AFSO": return "#059669";
    case "RATION_CARD_HOLDER": return "var(--muted)";
    default: return "var(--muted)";
  }
};

const roleLabel = (r: UserRole) => r.replace(/_/g, " ");

export function UsersPage() {
  const [filter, setFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const qc = useQueryClient();

  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: () => fetchUsers(),
    staleTime: 30_000,
  });

  const createM = useMutation({
    mutationFn: (body: Parameters<typeof registerUser>[0]) => registerUser(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      setCreateOpen(false);
    },
  });

  const updateM = useMutation({
    mutationFn: ({ user_id, body }: { user_id: string; body: Parameters<typeof updateUser>[1] }) =>
      updateUser(user_id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  const users = (usersQ.data ?? []) as AuthUser[];
  const filtered = useMemo(() => {
    const s = search.toLowerCase().trim();
    return users.filter((u) =>
      (filter === "ALL" || u.role === filter) &&
      (!s || u.full_name.toLowerCase().includes(s) || u.email.toLowerCase().includes(s) || u.username.toLowerCase().includes(s))
    );
  }, [users, filter, search]);

  const [form, setForm] = useState({
    username: "",
    email: "",
    password: "",
    full_name: "",
    role: "FPS_DEALER" as UserRole,
    district_id: "",
    mandal_id: "",
    fps_id: "",
  });

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: "24px", height: "100%" }}>
      
      {/* Header & Controls */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <p className="eyebrow">Identity & Access Management</p>
          <h2 style={{ fontSize: "2rem", color: "var(--navy)", margin: "4px 0 0", display: "flex", alignItems: "center", gap: "10px" }}>
            <Shield size={28} color="var(--blue)" /> Role-Based Access Control
          </h2>
        </div>
        
        <div style={{ display: "flex", gap: "12px" }}>
          <div style={{ display: "flex", alignItems: "center", background: "var(--control-glass)", borderRadius: "10px", padding: "8px 16px", border: "1px solid var(--line)", boxShadow: "0 12px 26px rgba(30,134,214,0.08)", backdropFilter: "blur(10px)" }}>
            <Search size={16} color="var(--muted)" />
            <input 
              type="text" 
              placeholder="Search users..." 
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ border: "none", background: "transparent", outline: "none", marginLeft: "8px", fontSize: "0.9rem", width: "200px" }} 
            />
          </div>
          <button
            onClick={() => setCreateOpen(true)}
            style={{ display: "flex", alignItems: "center", gap: "8px", background: "var(--primary-gradient)", border: "none", padding: "10px 16px", borderRadius: "10px", cursor: "pointer", fontWeight: 700, color: "#fff", boxShadow: "0 4px 12px rgba(30,58,138,0.2)" }}
          >
            <UserPlus size={16} /> Add User
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="cc-tabs" style={{ maxWidth: "fit-content" }}>
        {["ALL", "STATE_ADMIN", "DISTRICT_ADMIN", "MANDAL_ADMIN", "FPS_DEALER", "RATION_CARD_HOLDER"].map(s => (
          <button key={s} className={`cc-tab ${filter === s ? "active" : ""}`} onClick={() => setFilter(s)}>
            {s.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {/* Table */}
      <div style={{ background: "var(--card-glass)", borderRadius: "16px", border: "1px solid var(--line)", boxShadow: "var(--shadow)", overflow: "hidden", flex: 1, backdropFilter: "blur(12px)" }}>
        {usersQ.isLoading && <p className="state">Loading users...</p>}
        {usersQ.isError && <p className="state error">Failed to load users. Ensure the Auth service (port 8000) is running and you are logged in.</p>}
        <div className="table-wrap" style={{ margin: 0, border: "none" }}>
          <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead style={{ background: "var(--bg-deep)", borderBottom: "2px solid var(--line)" }}>
              <tr>
                <th style={{ padding: "16px 24px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>User Details</th>
                <th style={{ padding: "16px 24px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Role Level</th>
                <th style={{ padding: "16px 24px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Status</th>
                <th style={{ padding: "16px 24px", textAlign: "left", fontSize: "0.85rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Last Login</th>
                <th style={{ padding: "16px 24px" }}></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(u => (
                <tr 
                  key={u.user_id} 
                  style={{ borderBottom: "1px solid var(--line)", transition: "background 0.2s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--bg)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                >
                  <td style={{ padding: "16px 24px" }}>
                    <div style={{ display: "flex", flexDirection: "column" }}>
                      <span style={{ fontWeight: 700, color: "var(--navy)", fontSize: "1rem" }}>{u.full_name}</span>
                      <span style={{ fontSize: "0.85rem", color: "var(--muted)" }}>{u.email}</span>
                      <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>@{u.username}</span>
                    </div>
                  </td>
                  <td style={{ padding: "16px 24px" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", background: `${roleBadgeColor(u.role)}15`, color: roleBadgeColor(u.role), border: `1px solid ${roleBadgeColor(u.role)}30`, padding: "6px 12px", borderRadius: "12px", fontSize: "0.75rem", fontWeight: 800 }}>
                      <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: roleBadgeColor(u.role) }} />
                      {roleLabel(u.role)}
                    </span>
                  </td>
                  <td style={{ padding: "16px 24px" }}>
                    <span style={{ fontWeight: 700, fontSize: "0.85rem", color: u.is_active ? "var(--green)" : "var(--muted)" }}>
                      {u.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td style={{ padding: "16px 24px", fontSize: "0.9rem", color: "var(--muted)" }}>â€”</td>
                  <td style={{ padding: "16px 24px", textAlign: "right", color: "var(--muted)", position: "relative" }}>
                    <button
                      onClick={() => setMenuFor((cur) => (cur === u.user_id ? null : u.user_id))}
                      style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--muted)" }}
                      aria-label="User actions"
                    >
                      <MoreVertical size={18} />
                    </button>
                    {menuFor === u.user_id && (
                      <div style={{
                        position: "absolute",
                        right: 14,
                        top: 46,
                        background: "var(--card-glass)",
                        border: "1px solid rgba(255,255,255,0.55)",
                        borderRadius: 12,
                        boxShadow: "0 18px 60px rgba(0,0,0,0.16)",
                        padding: 8,
                        minWidth: 180,
                        zIndex: 20,
                        backdropFilter: "blur(14px)",
                      }}>
                        <button
                          onClick={() => { updateM.mutate({ user_id: u.user_id, body: { is_active: !u.is_active } }); setMenuFor(null); }}
                          style={{ width: "100%", textAlign: "left", background: "transparent", border: "none", padding: "10px 10px", borderRadius: 10, cursor: "pointer", fontWeight: 700, color: u.is_active ? "var(--red)" : "var(--green)" }}
                        >
                          {u.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button
                          onClick={() => { navigator.clipboard?.writeText(u.user_id); setMenuFor(null); }}
                          style={{ width: "100%", textAlign: "left", background: "transparent", border: "none", padding: "10px 10px", borderRadius: 10, cursor: "pointer", fontWeight: 700, color: "var(--navy)" }}
                        >
                          Copy User ID
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create user modal */}
      {createOpen && (
        <div
          onClick={() => !createM.isPending && setCreateOpen(false)}
          style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.35)", zIndex: 80, display: "flex", alignItems: "center", justifyContent: "center", padding: 18 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ width: "min(720px, 100%)", background: "var(--card-glass)", borderRadius: 18, border: "1px solid rgba(255,255,255,0.55)", boxShadow: "0 22px 80px rgba(0,0,0,0.20)", padding: 18, backdropFilter: "blur(18px)" }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
              <div>
                <div style={{ fontWeight: 900, color: "var(--navy)", fontSize: "1.05rem" }}>Add User</div>
                <div style={{ color: "var(--muted)", fontSize: 13 }}>Creates a real user in the Auth service database.</div>
              </div>
              <button onClick={() => setCreateOpen(false)} style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--muted)" }} aria-label="Close">
                <X size={18} />
              </button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <label className="field">
                <span>Username</span>
                <input value={form.username} onChange={(e) => setForm((p) => ({ ...p, username: e.target.value }))} />
              </label>
              <label className="field">
                <span>Full Name</span>
                <input value={form.full_name} onChange={(e) => setForm((p) => ({ ...p, full_name: e.target.value }))} />
              </label>
              <label className="field">
                <span>Email</span>
                <input value={form.email} onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))} />
              </label>
              <label className="field">
                <span>Password</span>
                <input type="password" value={form.password} onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))} />
              </label>
              <label className="field">
                <span>Role</span>
                <select value={form.role} onChange={(e) => setForm((p) => ({ ...p, role: e.target.value as UserRole }))}>
                  {(["STATE_ADMIN","DISTRICT_ADMIN","MANDAL_ADMIN","AFSO","FPS_DEALER","RATION_CARD_HOLDER"] as UserRole[]).map((r) => (
                    <option key={r} value={r}>{r.replace(/_/g, " ")}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>District ID (optional)</span>
                <input value={form.district_id} onChange={(e) => setForm((p) => ({ ...p, district_id: e.target.value }))} />
              </label>
              <label className="field">
                <span>Mandal/AFSO ID (optional)</span>
                <input value={form.mandal_id} onChange={(e) => setForm((p) => ({ ...p, mandal_id: e.target.value }))} />
              </label>
              <label className="field">
                <span>FPS ID (optional)</span>
                <input value={form.fps_id} onChange={(e) => setForm((p) => ({ ...p, fps_id: e.target.value }))} />
              </label>
            </div>

            {createM.isError && <p className="state error" style={{ marginTop: 10 }}>{String((createM.error as any)?.message ?? "Create user failed")}</p>}

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 14 }}>
              <button className="btn" onClick={() => setCreateOpen(false)} disabled={createM.isPending}>Cancel</button>
              <button
                className="btn-primary"
                onClick={() => createM.mutate({
                  username: form.username.trim(),
                  email: form.email.trim(),
                  password: form.password,
                  full_name: form.full_name.trim(),
                  role: form.role,
                  district_id: form.district_id.trim() || null,
                  mandal_id: form.mandal_id.trim() || null,
                  fps_id: form.fps_id.trim() || null,
                })}
                disabled={createM.isPending || !form.username.trim() || !form.email.trim() || !form.password || !form.full_name.trim()}
              >
                {createM.isPending ? "Creatingâ€¦" : "Create User"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
