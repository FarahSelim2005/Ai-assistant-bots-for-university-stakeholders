import { useEffect, useState } from "react";
import { UnauthorizedError, request } from "../admin/api.js";
import NewUniversity from "./NewUniversity.jsx";
import "../admin/admin.css";
import "./console.css";

const SESSION_KEY = "consoleSession";
// The console has the platform's own look, not a university's.
const PLATFORM_COLOURS = { "--brand-primary": "#334e68", "--brand-primary-dark": "#243b53", "--brand-accent": "#3ebd93", "--brand-dark": "#102a43" };

function savedSession() {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY)) || null;
  } catch {
    return null;
  }
}

const number = (n) => (n ?? 0).toLocaleString();

// /console: the platform owner's view of every university: status, plan, assistants, users,
// chats and token use; a "New university" wizard; suspend or reactivate; change the plan.
export default function ConsolePage() {
  const [session, setSession] = useState(savedSession);
  const [universities, setUniversities] = useState([]);
  const [plans, setPlans] = useState([]);
  const [wizard, setWizard] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    Object.entries(PLATFORM_COLOURS).forEach(([key, value]) => document.documentElement.style.setProperty(key, value));
    document.title = "Platform console";
  }, []);

  function saveSession(value) {
    setSession(value);
    try {
      if (value) sessionStorage.setItem(SESSION_KEY, JSON.stringify(value));
      else sessionStorage.removeItem(SESSION_KEY);
    } catch { /* the session stays in memory only */ }
  }

  async function call(path, options = {}) {
    try {
      return await request(path, { ...options, token: session.token });
    } catch (err) {
      if (err instanceof UnauthorizedError) saveSession(null);
      throw err;
    }
  }

  async function reload() {
    try {
      const [list, planList] = await Promise.all([call("/console/universities"), call("/console/plans")]);
      setUniversities(list);
      setPlans(planList);
    } catch (err) {
      setError(`Could not load the universities: ${err.message}`);
    }
  }

  useEffect(() => { if (session) reload(); }, [session]);

  async function change(university, values, done) {
    if (values.status === "suspended" && !window.confirm(`Suspend ${university.name}? Its chat and admin pages stop working until you reactivate it.`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await call(`/console/universities/${university.id}`, { method: "PUT", body: values });
      setNotice(done);
      await reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin console">
      <header className="topbar">
        <span className="topbar-logo text-logo">◎</span>
        <div className="topbar-title">
          <h1>Platform console</h1>
          <span>{session ? session.user.email : "Universities, plans and usage"}</span>
        </div>
        {session && <button className="secondary" onClick={() => { call("/console/logout", { method: "POST" }).catch(() => {}); saveSession(null); }}>Log out</button>}
      </header>
      <div className="flag-stripe" />
      <main className="admin-main console-main">
        {!session ? <Login onLogin={saveSession} /> : wizard ? (
          <NewUniversity call={call} plans={plans} onDone={(message) => { setWizard(false); setNotice(message); reload(); }}
                         onCancel={() => setWizard(false)} />
        ) : (
          <section className="admin-card">
            <div className="list-header">
              <h2>Universities</h2>
              <button onClick={() => { setWizard(true); setNotice(""); }}>+ New university</button>
            </div>
            {notice && <p className="notice">{notice}</p>}
            {error && <p className="error">{error}</p>}
            <table className="doc-table console-table">
              <thead>
                <tr><th>University</th><th>Status</th><th>Plan</th><th>Assistants</th><th>Users</th><th>Chats</th><th>Tokens this month</th><th /></tr>
              </thead>
              <tbody>
                {universities.map((u) => {
                  const share = u.monthly_token_cap ? Math.min(100, (100 * u.tokens_month) / u.monthly_token_cap) : 0;
                  return (
                    <tr key={u.id} className={u.status === "active" ? "" : "hidden-row"}>
                      <td>
                        <span className="colour-dot" style={{ background: u.colour }} />
                        <b>{u.name}</b>
                        <div className="hint">{u.hosts.map((host) => (
                          <a key={host} href={`http://${host}:5173`} target="_blank" rel="noreferrer">{host}</a>
                        ))}</div>
                      </td>
                      <td><span className={`status ${u.status}`}>{u.status === "active" ? "Active" : "Suspended"}</span></td>
                      <td>
                        <select value={u.plan} disabled={busy} aria-label={`Plan of ${u.name}`}
                                onChange={(e) => change(u, { plan: e.target.value }, `${u.name} is on the ${e.target.value} plan.`)}>
                          {plans.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
                        </select>
                      </td>
                      <td>{u.assistants}{u.max_assistants ? ` / ${u.max_assistants}` : ""}</td>
                      <td title={u.users.map((x) => `${x.email} (${x.role}${x.active ? "" : ", deactivated"})`).join("\n")}>
                        {u.users.filter((x) => x.active).length}
                      </td>
                      <td>{number(u.conversations)}</td>
                      <td>
                        {number(u.tokens_month)}{u.monthly_token_cap ? ` / ${number(u.monthly_token_cap)}` : ""}
                        {u.monthly_token_cap > 0 && <div className="usage-bar"><span style={{ width: `${share}%` }} className={share >= 90 ? "full" : ""} /></div>}
                        <div className="hint">{number(u.tokens_total)} in total</div>
                      </td>
                      <td className="row-actions">
                        {u.status === "active"
                          ? <button className="danger" disabled={busy} onClick={() => change(u, { status: "suspended" }, `${u.name} is suspended.`)}>Suspend</button>
                          : <button className="secondary" disabled={busy} onClick={() => change(u, { status: "active" }, `${u.name} is active again.`)}>Reactivate</button>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="hint">Plans: {plans.map((p) => `${p.name}: ${p.monthly_token_cap ? number(p.monthly_token_cap) + " tokens a month" : "no token limit"}, ${p.max_assistants ?? "any number of"} assistants`).join(" · ")}</p>
          </section>
        )}
      </main>
    </div>
  );
}

function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await request("/console/login", { method: "POST", body: { email, password } }));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <form className="admin-card login-form" onSubmit={submit}>
      <h2>Platform console</h2>
      <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" autoFocus /></label>
      <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={!email || !password || busy}>{busy ? "Logging in…" : "Log in"}</button>
    </form>
  );
}
