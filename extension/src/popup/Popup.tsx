import { useEffect, useState } from "react";

import { WEB_ORIGIN } from "../lib/env";
import { bg } from "../lib/messaging";
import type { Application, ApplicationStats } from "../lib/types";

const wrap: React.CSSProperties = { padding: 14 };
const input: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "8px 10px",
  margin: "4px 0",
  borderRadius: 8,
  border: "1px solid #373a40",
  background: "#25262b",
  color: "#e9ecef",
  font: "13px system-ui",
};
const button: React.CSSProperties = {
  width: "100%",
  padding: "9px 12px",
  border: "none",
  borderRadius: 8,
  background: "#20c997",
  color: "#04211a",
  font: "600 13px system-ui",
  cursor: "pointer",
  marginTop: 6,
};

export function Popup() {
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [apps, setApps] = useState<Application[]>([]);
  const [stats, setStats] = useState<ApplicationStats | null>(null);

  const load = async () => {
    const auth = await bg.authGet();
    const signedIn = auth.ok && !!auth.data.token;
    setEmail(signedIn ? auth.data.email : null);
    setLoading(false);
    if (signedIn) {
      const [a, s] = await Promise.all([bg.applications(15), bg.stats()]);
      if (a.ok) setApps(a.data.items);
      if (s.ok) setStats(s.data);
    }
  };
  useEffect(() => {
    load();
  }, []);

  const login = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const r = await bg.login(form.email.trim(), form.password);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    await load();
  };

  if (loading) return <div style={wrap}>Loading…</div>;

  if (!email) {
    return (
      <div style={wrap}>
        <h3 style={{ margin: "0 0 8px", color: "#20c997" }}>Sign in to JobBot</h3>
        <form onSubmit={login}>
          <input
            style={input}
            type="email"
            placeholder="Email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
          <input
            style={input}
            type="password"
            placeholder="Password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
          {error && <p style={{ color: "#ff8787", margin: "4px 0" }}>{error}</p>}
          <button style={button} type="submit">
            Sign in
          </button>
        </form>
        <a href={`${WEB_ORIGIN}/auth`} target="_blank" rel="noreferrer" style={{ color: "#4dabf7", fontSize: 12 }}>
          Create an account
        </a>
      </div>
    );
  }

  return (
    <div style={wrap}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ color: "#20c997" }}>JobBot</strong>
        <button
          onClick={async () => {
            await bg.logout();
            load();
          }}
          style={{ background: "none", border: "none", color: "#868e96", cursor: "pointer" }}
        >
          Sign out
        </button>
      </div>
      <p style={{ margin: "2px 0 10px", color: "#adb5bd", fontSize: 12 }}>{email}</p>

      {stats && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          {Object.entries(stats.by_status).map(([k, v]) => (
            <span key={k} style={{ background: "#25262b", borderRadius: 6, padding: "3px 7px", fontSize: 11 }}>
              {k}: <strong>{v}</strong>
            </span>
          ))}
        </div>
      )}

      <div style={{ maxHeight: 260, overflowY: "auto" }}>
        {apps.length === 0 && <p style={{ color: "#868e96", fontSize: 12 }}>No applications tracked yet.</p>}
        {apps.map((a) => (
          <div key={a.id} style={{ padding: "7px 0", borderTop: "1px solid #2c2e33" }}>
            <div style={{ fontWeight: 600 }}>{a.job_title || a.job_url}</div>
            <div style={{ fontSize: 11, color: "#adb5bd" }}>
              {a.company || a.ats} · <span style={{ color: "#20c997" }}>{a.status}</span>
            </div>
          </div>
        ))}
      </div>

      <a
        href={`${WEB_ORIGIN}/applications`}
        target="_blank"
        rel="noreferrer"
        style={{ ...button, display: "block", textAlign: "center", textDecoration: "none", boxSizing: "border-box" }}
      >
        Open full tracker
      </a>
    </div>
  );
}
