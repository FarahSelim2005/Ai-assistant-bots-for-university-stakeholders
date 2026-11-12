import { useEffect, useState } from "react";
import { UnauthorizedError, request } from "../admin/api.js";
import NewUniversity from "./NewUniversity.jsx";
import "../platform.css";
import "../admin/admin.css";

const SESSION_KEY = "consoleSession";
// In development (APP_ENV=development) the backend needs no login: the console opens directly.
const NO_LOGIN = { token: "", open: true, user: { email: "Development: no login needed" } };
const SECTIONS = [
  { key: "universities", title: "Universities" },
  { key: "templates", title: "Templates" },
  { key: "models", title: "Models & keys" },
  { key: "usage", title: "Usage & billing" },
  { key: "audit", title: "Audit log" },
];

function savedSession() {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY)) || null;
  } catch {
    return null;
  }
}

const number = (n) => (n ?? 0).toLocaleString("en");
const short = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : number(n));
const money = (n) => `$${(n ?? 0).toFixed(n >= 100 ? 0 : 2)}`;

// /console: the platform owner's console, like the design's platformView(): a sidebar, then
// the universities with KPI tiles (last 30 days) and a table, and the "New university" wizard.
// It uses the platform's own colours (platform.css), never a university's.
export default function ConsolePage() {
  const [session, setSession] = useState(savedSession);
  const [checking, setChecking] = useState(!savedSession()); // trying without a login first
  const [section, setSection] = useState("universities");
  const [wizard, setWizard] = useState(false);
  const [data, setData] = useState({ universities: [], plans: [], templates: [] });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => { document.title = "Platform console"; }, []);

  function saveSession(value) {
    setSession(value);
    try {
      if (value && !value.open) sessionStorage.setItem(SESSION_KEY, JSON.stringify(value));
      else sessionStorage.removeItem(SESSION_KEY);
    } catch { /* the session stays in memory only */ }
  }

  async function call(path, options = {}) {
    try {
      return await request(path, { ...options, token: session?.token });
    } catch (err) {
      if (err instanceof UnauthorizedError) saveSession(null);
      throw err;
    }
  }

  async function reload() {
    try {
      const [universities, plans, templates] = await Promise.all([
        call("/console/universities"), call("/console/plans"), call("/console/templates")]);
      setData({ universities, plans, templates });
    } catch (err) {
      setError(`Could not load the universities: ${err.message}`);
    }
  }

  useEffect(() => { if (session) reload(); }, [session]);

  // No saved login: open directly if the backend allows it (development), else show the login form.
  useEffect(() => {
    if (!checking) return;
    request("/console/plans").then(() => setSession(NO_LOGIN)).catch(() => {}).finally(() => setChecking(false));
  }, []);

  if (checking) return <div className="pf admin"><div className="signin"><p className="note">Loading…</p></div></div>;
  if (!session) return <div className="pf admin"><Login onLogin={saveSession} /></div>;

  function open(key) {
    setSection(key);
    setWizard(false);
    setNotice("");
    setError("");
  }

  return (
    <div className="pf admin">
      <div className="console">
        <nav className="cnav" aria-label="Console sections">
          <div className="ctitle"><span className="clogo">UB</span><span>Platform</span></div>
          {SECTIONS.map((s) => (
            <button key={s.key} type="button" className={`navlink ${section === s.key ? "on" : ""}`} onClick={() => open(s.key)}
                    aria-current={section === s.key ? "page" : undefined}>
              {s.title}
              {s.key === "universities" && <span>{data.universities.length}</span>}
              {s.key === "templates" && <span>{data.templates.length}</span>}
            </button>
          ))}
          <div className="cuser">
            <span>{session.user.email}</span>
            {!session.open && <button type="button" className="link"
              onClick={() => { call("/console/logout", { method: "POST" }).catch(() => {}); saveSession(null); }}>Log out</button>}
          </div>
        </nav>
        <main className="cmain">
          {error && <p className="error">{error}</p>}
          {section === "universities" && (wizard ? (
            <NewUniversity call={call} plans={data.plans} templates={data.templates}
                           onDone={(message) => { setWizard(false); setNotice(message); reload(); }}
                           onCancel={() => setWizard(false)} />
          ) : (
            <Universities data={data} call={call} reload={reload} notice={notice} setNotice={setNotice} setError={setError}
                          onNew={() => { setWizard(true); setNotice(""); }} />
          ))}
          {section === "templates" && <Templates templates={data.templates} />}
          {section === "models" && <Models call={call} />}
          {section === "usage" && <Usage call={call} universities={data.universities} />}
          {section === "audit" && <Audit />}
        </main>
      </div>
    </div>
  );
}

function Universities({ data, call, reload, notice, setNotice, setError, onNew }) {
  const [busy, setBusy] = useState(false);
  const list = data.universities;
  const most = Math.max(1, ...list.map((u) => u.tokens_30d));
  const suspended = list.filter((u) => u.status !== "active").length;
  const sum = (key) => list.reduce((total, u) => total + (u[key] || 0), 0);

  async function change(university, values, done) {
    if (values.status === "suspended"
        && !window.confirm(`Suspend ${university.name}? Its chat and admin pages stop working until you reactivate it.`)) return;
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
    <>
      <div className="crow"><h3>Universities</h3><button type="button" onClick={onNew}>＋ New university</button></div>
      {notice && <p className="notice">{notice}</p>}
      <div className="kpis">
        <div className="kpi"><span>Universities</span><b>{list.length}</b><small>{suspended ? `${suspended} suspended` : "all active"}</small></div>
        <div className="kpi"><span>Questions, 30 days</span><b>{number(sum("questions_30d"))}</b><small>from all universities</small></div>
        <div className="kpi"><span>Tokens, 30 days</span><b>{short(sum("tokens_30d"))}</b><small>chat, pictures, CVs, embeddings</small></div>
        <div className="kpi"><span>Model cost</span><b>{money(sum("cost_30d"))}</b><small>30 days · as OpenRouter reports</small></div>
      </div>
      <div className="tablewrap">
        <table>
          <thead>
            <tr><th>University</th><th>Address</th><th>Status</th><th>Plan</th><th className="num">Assistants</th>
              <th className="num">Users</th><th>Token use</th><th className="num">Tokens</th><th className="num">Cost</th><th /></tr>
          </thead>
          <tbody>
            {list.map((u) => {
              const capped = u.monthly_token_cap && u.tokens_month >= 0.9 * u.monthly_token_cap;
              return (
                <tr key={u.id}>
                  <td><span className="sw" style={{ background: u.colour }} />{u.name}</td>
                  <td>{u.hosts[0] ? <a href={`http://${u.hosts[0]}:5173`} target="_blank" rel="noreferrer"><code>{u.hosts[0]}</code></a> : "-"}</td>
                  <td><span className={`pill ${u.status === "active" ? "ok" : "warn"}`}>{u.status}</span></td>
                  <td>
                    <select value={u.plan} disabled={busy} aria-label={`Plan of ${u.name}`}
                            onChange={(e) => change(u, { plan: e.target.value }, `${u.name} is on the ${e.target.value} plan.`)}>
                      {data.plans.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
                    </select>
                  </td>
                  <td className="num">{u.assistants}{u.max_assistants ? <span className="note"> / {u.max_assistants}</span> : ""}</td>
                  <td className="num" title={u.users.map((x) => `${x.email} (${x.role}${x.active ? "" : ", deactivated"})`).join("\n")}>
                    {u.users.filter((x) => x.active).length}
                  </td>
                  <td title={u.monthly_token_cap ? `${number(u.tokens_month)} of ${number(u.monthly_token_cap)} tokens this month` : "No monthly cap"}>
                    <div className="bar"><i className={capped ? "full" : ""} style={{ width: `${(100 * u.tokens_30d) / most}%` }} /></div>
                  </td>
                  <td className="num">{short(u.tokens_30d)}</td>
                  <td className="num">{money(u.cost_30d)}</td>
                  <td>
                    {u.status === "active"
                      ? <button type="button" className="ghost" disabled={busy} onClick={() => change(u, { status: "suspended" }, `${u.name} is suspended.`)}>Suspend</button>
                      : <button type="button" className="ghost" disabled={busy} onClick={() => change(u, { status: "active" }, `${u.name} is active again.`)}>Reactivate</button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="note">Tokens and cost: last 30 days. The bar compares the universities; it turns red at 90% of a monthly cap.
        Plans: {data.plans.map((p) => `${p.name} (${p.monthly_token_cap ? `${short(p.monthly_token_cap)} tokens/month` : "no token limit"}, ${p.max_assistants ?? "any number of"} assistants)`).join(" · ")}.</p>
    </>
  );
}

function Templates({ templates }) {
  return (
    <>
      <div className="crow"><h3>Templates</h3></div>
      <p className="note">Ready-made assistants a university can start from (in the wizard, or on its admin page). It can rename and change them.</p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Template</th><th>What it handles</th><th>For</th><th>Skills</th></tr></thead>
          <tbody>
            {templates.map((t) => (
              <tr key={t.key}><td><b>{t.name}</b><div className="note"><code>{t.key}</code></div></td><td className="wrap">{t.summary}</td>
                <td>{t.audiences.join(", ")}</td><td className="wrap">{t.skills.join(", ")}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Models({ call }) {
  const [models, setModels] = useState(null);
  useEffect(() => { call("/console/models").then(setModels).catch(() => setModels({ roles: [], keys: {}, usage_30d: [] })); }, []);
  if (!models) return <p className="note">Loading…</p>;
  return (
    <>
      <div className="crow"><h3>Models &amp; keys</h3></div>
      <p className="note">The platform's models, from <code>backend/.env</code>. Keys are never shown here, only whether they are set.</p>
      <div className="kpis">
        {Object.entries(models.keys).map(([name, set]) => (
          <div className="kpi" key={name}><span>{name} key</span><b><span className={`pill ${set ? "ok" : "warn"}`}>{set ? "set" : "missing"}</span></b></div>
        ))}
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Used for</th><th>Models, in order (backups after the first)</th></tr></thead>
          <tbody>{models.roles.map((r) => <tr key={r.role}><td>{r.role}</td><td className="wrap"><code>{r.models.join("  →  ") || "-"}</code></td></tr>)}</tbody>
        </table>
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Model, last 30 days</th><th>Kind</th><th className="num">Calls</th><th className="num">Tokens</th><th className="num">Cost</th></tr></thead>
          <tbody>
            {models.usage_30d.length === 0 && <tr><td colSpan={5} className="note">No model calls in the last 30 days.</td></tr>}
            {models.usage_30d.map((m) => (
              <tr key={m.model + m.kind}><td><code>{m.model}</code></td><td>{m.kind}</td><td className="num">{number(m.calls)}</td>
                <td className="num">{short(m.tokens)}</td><td className="num">{money(m.cost)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Usage({ call, universities }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { call("/console/usage").then(setRows).catch(() => setRows([])); }, []);
  return (
    <>
      <div className="crow"><h3>Usage &amp; billing</h3></div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>University</th><th>Plan</th><th className="num">Tokens this month</th><th>Monthly cap</th><th className="num">Tokens in total</th></tr></thead>
          <tbody>
            {universities.map((u) => {
              const share = u.monthly_token_cap ? Math.min(100, (100 * u.tokens_month) / u.monthly_token_cap) : 0;
              return (
                <tr key={u.id}><td><span className="sw" style={{ background: u.colour }} />{u.name}</td><td>{u.plan_name}</td>
                  <td className="num">{number(u.tokens_month)}</td>
                  <td>{u.monthly_token_cap ? <><div className="bar"><i className={share >= 90 ? "full" : ""} style={{ width: `${share}%` }} /></div>
                    <span className="note">{Math.round(share)}% of {short(u.monthly_token_cap)}</span></> : <span className="note">no cap</span>}</td>
                  <td className="num">{number(u.tokens_total)}</td></tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Month</th><th>University</th><th className="num">Model calls</th><th className="num">Tokens</th><th className="num">Cost</th></tr></thead>
          <tbody>
            {rows === null && <tr><td colSpan={5} className="note">Loading…</td></tr>}
            {rows?.length === 0 && <tr><td colSpan={5} className="note">No model calls recorded yet.</td></tr>}
            {rows?.map((r) => (
              <tr key={r.month + r.university}><td><code>{r.month}</code></td><td>{r.university}</td><td className="num">{number(r.calls)}</td>
                <td className="num">{number(r.tokens)}</td><td className="num">{money(r.cost)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">A university that reaches its plan's monthly cap gets "allowance used" answers until the next month. There is no invoicing yet: cost is what the model providers report.</p>
    </>
  );
}

function Audit() {
  return (
    <>
      <div className="crow"><h3>Audit log</h3></div>
      <div className="panel">
        <h4>Not recorded yet</h4>
        <p className="note">Changes made in the console and on the universities' admin pages are written to the backend's log
          (for example "Console: new university …", "Admin: changed assistant …"), but not yet stored in the database, so they cannot be shown here.</p>
      </div>
    </>
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
    <div className="signin">
      <form className="panel" onSubmit={submit}>
        <div className="ctitle"><span className="clogo">UB</span> <h3>Platform console</h3></div>
        <label className="field"><span>Email</span><input className="finput" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" autoFocus /></label>
        <label className="field"><span>Password</span><input className="finput" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={!email || !password || busy}>{busy ? "Logging in…" : "Log in"}</button>
      </form>
    </div>
  );
}
