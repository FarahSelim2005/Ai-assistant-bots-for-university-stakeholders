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
  { key: "subscriptions", title: "Subscriptions" },
  { key: "plans", title: "Plans & prices" },
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
const egp = (n) => `EGP ${number(n)}`;
const day = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "-");
// A subscription's status as a pill: working (ok), needs attention (warn), stopped (crit)
const SUB_PILL = { trialing: "acc", active: "ok", past_due: "warn", paused: "crit", canceled: "crit" };
const SUB_TEXT = { trialing: "trial", active: "active", past_due: "payment failed", paused: "paused", canceled: "cancelled" };

// /console: the platform owner's console, like the design's platformView(): a sidebar, then
// the universities with KPI tiles (last 30 days) and a table, "Add by hand" (the wizard), the
// subscriptions of the universities that signed up themselves, and the plans with their prices.
// It uses the platform's own colours (platform.css), never a university's.
export default function ConsolePage() {
  const [session, setSession] = useState(savedSession);
  const [checking, setChecking] = useState(!savedSession()); // trying without a login first
  const [section, setSection] = useState("universities");
  const [wizard, setWizard] = useState(false);
  const [data, setData] = useState({ universities: [], plans: [], templates: [], settings: {} });
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
      const [universities, plans, templates, settings] = await Promise.all([
        call("/console/universities"), call("/console/plans"), call("/console/templates"), call("/console/settings")]);
      setData({ universities, plans, templates, settings });
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
              {s.key === "plans" && <span>{data.plans.filter((p) => p.public).length}</span>}
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
          {section === "subscriptions" && <Subscriptions call={call} onChanged={reload} />}
          {section === "plans" && <Plans call={call} plans={data.plans} onChanged={reload} />}
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
  const [deleting, setDeleting] = useState(null); // the university whose deletion is being confirmed
  const [typed, setTyped] = useState("");
  const list = data.universities;
  const most = Math.max(1, ...list.map((u) => u.tokens_30d));
  const trials = list.filter((u) => u.subscription === "trialing").length;
  const waiting = list.filter((u) => u.status === "review").length;
  const sum = (key) => list.reduce((total, u) => total + (u[key] || 0), 0);
  // Paying universities' monthly prices (active, or in the grace days after a failed payment)
  const revenue = list.filter((u) => ["active", "past_due"].includes(u.subscription)).reduce((total, u) => total + u.price_egp, 0);
  const review = Boolean(data.settings.require_review);
  const recent = (u) => u.signed_up_at && Date.now() - new Date(u.signed_up_at) < 30 * 864e5;

  async function change(university, values, done) {
    if (values.status === "suspended"
        && !window.confirm(`Suspend ${university.name}? Its chat and admin pages stop working until you reactivate it.`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (university) await call(`/console/universities/${university.id}`, { method: "PUT", body: values });
      else await call("/console/settings", { method: "PUT", body: values });
      setNotice(done);
      await reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // Delete for good, after typing its subdomain; the backend makes a full backup first
  async function remove(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await call(`/console/universities/${deleting.id}`, { method: "DELETE", body: { confirm: typed } });
      setNotice(`${deleting.name} is deleted with all its data. A backup was saved first: ${result.backup}`);
      setDeleting(null);
      setTyped("");
      await reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="crow"><h3>Universities</h3>
        <span className="actions">
          <button type="button" className="ghost" disabled={busy} aria-pressed={review}
                  title="On: a university that signs up waits until you approve it here"
                  onClick={() => change(null, { require_review: !review }, review ? "New sign-ups go live at once." : "New sign-ups now wait for your approval.")}>
            Require review before going live: {review ? "on" : "off"}</button>
          <button type="button" onClick={onNew}>＋ Add by hand</button>
        </span></div>
      {notice && <p className="notice">{notice}</p>}
      <div className="kpis">
        <div className="kpi"><span>Universities</span><b>{list.length}</b>
          <small>{trials} on trial{waiting ? ` · ${waiting} waiting for review` : ""}</small></div>
        <div className="kpi"><span>Questions, 30 days</span><b>{number(sum("questions_30d"))}</b><small>from all universities</small></div>
        <div className="kpi"><span>Tokens, 30 days</span><b>{short(sum("tokens_30d"))}</b><small>chat, pictures, CVs, embeddings</small></div>
        <div className="kpi"><span>Monthly revenue</span><b>{egp(revenue)}</b><small>model cost {money(sum("cost_30d"))} · 30 days</small></div>
      </div>
      {deleting && (
        <form className="panel danger-zone" onSubmit={remove}>
          <h4>Delete {deleting.name} for good?</h4>
          <p className="note">This removes its assistants, documents, chats, ratings, users, usage, sign-up and payments. It cannot be
            undone from here: a full database backup is saved to <code>db-backups</code> first, and nothing is deleted if the backup fails.
            {deleting.slug === "giu" && <b> This is GIU: its chatbot stops working for everyone.</b>}</p>
          <label className="field"><span>Type <code>{deleting.slug}</code> to confirm</span>
            <input className="finput" value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus aria-label="Type the subdomain to confirm" /></label>
          <div className="crow" style={{ justifyContent: "flex-start" }}>
            <button type="submit" className="danger-solid" disabled={busy || typed.trim().toLowerCase() !== deleting.slug}>
              {busy ? "Backing up and deleting…" : "Delete for good"}</button>
            <button type="button" className="ghost" disabled={busy} onClick={() => { setDeleting(null); setTyped(""); }}>Cancel</button>
          </div>
        </form>
      )}
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
                  <td><span className={`pill ${u.status === "active" ? "ok" : "warn"}`}>{u.status === "review" ? "waiting for review" : u.status}</span>
                    {u.subscription && u.subscription !== "active" && <> <span className={`pill ${SUB_PILL[u.subscription]}`}>{SUB_TEXT[u.subscription]}</span></>}
                    {recent(u) && <> <span className="pill acc">new sign-up</span></>}</td>
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
                    {u.status === "active" && <button type="button" className="ghost" disabled={busy} onClick={() => change(u, { status: "suspended" }, `${u.name} is suspended.`)}>Suspend</button>}
                    {u.status === "suspended" && <button type="button" className="ghost" disabled={busy} onClick={() => change(u, { status: "active" }, `${u.name} is active again.`)}>Reactivate</button>}
                    {u.status === "review" && <button type="button" disabled={busy} onClick={() => change(u, { status: "active" }, `${u.name} is approved and live.`)}>Approve</button>}
                    {" "}<button type="button" className="danger" disabled={busy} onClick={() => { setDeleting(u); setTyped(""); setNotice(""); window.scrollTo(0, 0); }}>Delete</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="panel"><h4>How universities arrive</h4>
        <p className="note">Universities sign up and pay by themselves at <a href="/signup" target="_blank" rel="noreferrer"><code>/signup</code></a>, and
          appear here straight away (marked "new sign-up"). Here you can suspend one, change its plan or approve it (with "Require review" on);
          under Subscriptions you can extend a trial or simulate the next month. "Add by hand" is for a university that pays by invoice:
          it has no subscription and is never paused by billing.</p></div>
      <p className="note">Tokens and cost: last 30 days. The bar compares the universities; it turns red at 90% of a monthly cap.
        Plans: {data.plans.map((p) => `${p.name} (${p.monthly_token_cap ? `${short(p.monthly_token_cap)} tokens/month` : "no token limit"}, ${p.max_assistants ?? "any number of"} assistants)`).join(" · ")}.</p>
    </>
  );
}

function Subscriptions({ call, onChanged }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = () => call("/console/subscriptions").then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function act(path, body, message) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await call(path, { method: "POST", body });
      setNotice(typeof message === "function" ? message(result) : message);
      await load();
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const monthText = (name) => (result) => {
    const after = result.subscription;
    const renewal = { "invoice.paid": "the renewal was paid", "invoice.payment_failed": "the renewal payment failed" }[result.renewal]
      || "there was nothing to charge";
    return `${name}: a month passed and ${renewal}. Now ${SUB_TEXT[after.status]}${after.status === "past_due" ? ` until ${day(after.grace_ends_at)}, then paused` : ""}.`;
  };

  if (!data) return error ? <p className="error">{error}</p> : <p className="note">Loading…</p>;
  return (
    <>
      <div className="crow"><h3>Subscriptions</h3><span className="pill warn">test mode · simulated payments</span></div>
      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}
      <p className="note">The universities that signed up themselves. "Next month" moves a subscription a month ahead: a trial ends, and a paid
        one is renewed with a payment that succeeds or fails (7 days' grace, then the chat pauses). Nothing is ever deleted.</p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>University</th><th>Plan</th><th>Status</th><th>Until</th><th className="num">Paid</th><th>Next month (test)</th><th /></tr></thead>
          <tbody>
            {data.subscriptions.length === 0 && <tr><td colSpan={7} className="note">No sign-ups yet. Try <a href="/signup" target="_blank" rel="noreferrer">/signup</a>.</td></tr>}
            {data.subscriptions.map((s) => {
              const until = s.status === "trialing" ? `trial ends ${day(s.trial_ends_at)}`
                : s.status === "past_due" ? `grace ends ${day(s.grace_ends_at)}`
                  : s.status === "active" ? `${s.cancel_at_period_end ? "ends" : "renews"} ${day(s.current_period_end)}` : "-";
              const trial = s.trial_ends_at && !s.current_period_end && ["trialing", "paused"].includes(s.status);
              return (
                <tr key={s.tenant_id}>
                  <td>{s.university}<div className="note"><code>{s.slug}</code>{s.university_status === "review" ? " · waiting for review" : ""}</div></td>
                  <td>{s.plan_name}<div className="note">{s.price_egp ? `${egp(s.price_egp)} / month` : "free"}</div></td>
                  <td><span className={`pill ${SUB_PILL[s.status]}`}>{SUB_TEXT[s.status]}</span></td>
                  <td>{until}</td>
                  <td className="num">{egp(s.paid_total_egp)}</td>
                  <td>
                    <span className="actions" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <button type="button" className="ghost" disabled={busy}
                              onClick={() => act(`/console/subscriptions/${s.tenant_id}/simulate-month`, { payment: "succeeds" }, monthText(s.university))}>Payment succeeds</button>
                      <button type="button" className="danger" disabled={busy}
                              onClick={() => act(`/console/subscriptions/${s.tenant_id}/simulate-month`, { payment: "fails" }, monthText(s.university))}>Payment fails</button>
                    </span>
                  </td>
                  <td>{trial && <button type="button" className="ghost" disabled={busy}
                                        onClick={() => act(`/console/subscriptions/${s.tenant_id}/extend-trial`, { days: 7 }, `${s.university}'s trial is 7 days longer.`)}>Extend trial 7 days</button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <h4>Latest billing events</h4>
      <div className="tablewrap">
        <table>
          <thead><tr><th>When</th><th>University</th><th>Event</th><th>Plan</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {data.events.length === 0 && <tr><td colSpan={5} className="note">None yet.</td></tr>}
            {data.events.map((e, i) => (
              <tr key={i}><td>{new Date(e.at).toLocaleString("en-GB")}</td><td>{e.university || "-"}</td><td><code>{e.kind}</code></td>
                <td>{e.plan || "-"}</td><td className="num">{e.amount_egp != null ? egp(e.amount_egp) : ""}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Plans({ call, plans, onChanged }) {
  const [rows, setRows] = useState(plans);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { setRows(plans); }, [plans]);

  const setRow = (key, changes) => setRows((all) => all.map((p) => (p.key === key ? { ...p, ...changes } : p)));
  const whole = (value) => (value === "" ? null : Math.max(0, Math.round(Number(value))));

  async function save(plan) {
    setBusy(plan.key); setError(""); setNotice("");
    try {
      await call(`/console/plans/${plan.key}`, { method: "PUT", body: {
        name: plan.name, price_egp: plan.price_egp ?? 0, trial_days: plan.trial_days || null, max_assistants: plan.max_assistants || null,
        monthly_token_cap: plan.monthly_token_cap || null, public: plan.public, description: plan.description } });
      setNotice(`${plan.name} saved. A new price applies from the next payment.`);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="crow"><h3>Plans &amp; prices</h3></div>
      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}
      <p className="note">Prices are per month in EGP. "On sign-up page": offered at /signup. Empty limits mean no limit. A trial plan (with trial days) must be free.</p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Plan</th><th className="num">Price (EGP)</th><th className="num">Trial days</th><th className="num">Assistants</th>
            <th className="num">Tokens / month</th><th>On sign-up page</th><th>Description</th><th /></tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.key}>
                <td><input className="finput" value={p.name} onChange={(e) => setRow(p.key, { name: e.target.value })} aria-label={`Name of ${p.key}`} />
                  <div className="note"><code>{p.key}</code></div></td>
                <td><input className="finput" type="number" min="0" value={p.price_egp ?? 0} style={{ width: 100 }}
                           onChange={(e) => setRow(p.key, { price_egp: whole(e.target.value) ?? 0 })} aria-label={`Price of ${p.name}`} /></td>
                <td><input className="finput" type="number" min="1" value={p.trial_days ?? ""} style={{ width: 70 }} placeholder="-"
                           onChange={(e) => setRow(p.key, { trial_days: whole(e.target.value) })} aria-label={`Trial days of ${p.name}`} /></td>
                <td><input className="finput" type="number" min="1" value={p.max_assistants ?? ""} style={{ width: 70 }} placeholder="any"
                           onChange={(e) => setRow(p.key, { max_assistants: whole(e.target.value) })} aria-label={`Assistants of ${p.name}`} /></td>
                <td><input className="finput" type="number" min="1" value={p.monthly_token_cap ?? ""} style={{ width: 120 }} placeholder="no limit"
                           onChange={(e) => setRow(p.key, { monthly_token_cap: whole(e.target.value) })} aria-label={`Tokens of ${p.name}`} /></td>
                <td><input type="checkbox" checked={p.public} onChange={(e) => setRow(p.key, { public: e.target.checked })} aria-label={`${p.name} on the sign-up page`} /></td>
                <td className="wrap"><input className="finput" value={p.description} onChange={(e) => setRow(p.key, { description: e.target.value })}
                                            aria-label={`Description of ${p.name}`} /></td>
                <td><button type="button" disabled={busy === p.key} onClick={() => save(p)}>{busy === p.key ? "Saving…" : "Save"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
      <p className="note">A university that reaches its plan's monthly cap gets "allowance used" answers until the next month. Payments are under Subscriptions; cost is what the model providers report.</p>
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
