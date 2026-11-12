import { useEffect, useState } from "react";
import { initials, tenant } from "../tenant.js";
import { UnauthorizedError, listAgents, login, logout, request } from "./api.js";
import AnalyticsPage from "./AnalyticsPage.jsx";
import AssistantsPage from "./AssistantsPage.jsx";
import BillingPage from "./BillingPage.jsx";
import BrandingTab from "./BrandingTab.jsx";
import DocumentsTab from "./DocumentsTab.jsx";
import SignInPage from "./SignInPage.jsx";
import UsersPage from "./UsersPage.jsx";
import "../platform.css";
import "./admin.css";

const SESSION_KEY = "adminSession"; // sessionStorage: kept while the tab is open

// The admin's sections, like the design's adminView(): which roles see each. A tenant_admin
// manages everything of its university; an editor its documents (and sees the numbers).
const PAGES = [
  { key: "assistants", title: "Assistants", roles: ["tenant_admin"] },
  { key: "documents", title: "Documents", roles: ["tenant_admin", "editor"] },
  { key: "branding", title: "Branding", roles: ["tenant_admin"] },
  { key: "users", title: "Users & audiences", roles: ["tenant_admin"] },
  { key: "analytics", title: "Analytics", roles: ["tenant_admin", "editor"] },
  { key: "billing", title: "Billing", roles: ["tenant_admin"] },
  { key: "signin", title: "Sign-in", roles: ["tenant_admin", "editor"] },
];

function savedSession() {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY)) || null;
  } catch {
    return null; // storage blocked: log in again on every visit
  }
}

// The university's logo in the sidebar, or its short name on its main colour.
export function UniversityMark() {
  const university = tenant();
  return university.logo_url
    ? <span className="clogo"><img src={university.logo_url} alt="" /></span>
    : <span className="clogo" style={{ background: university.colors.primary, color: "#fff" }}>{initials(university)}</span>;
}

// /admin: the university admin. Log in with email and password, then a sidebar with the
// sections and the page of the chosen one. Any 401 answer shows the login form again.
export default function AdminPage() {
  const [session, setSession] = useState(savedSession); // { token, user: { email, name, role } }
  const [notice, setNotice] = useState("");
  // Back from the payment page (/admin?billing=1): open Billing
  const returned = new URLSearchParams(window.location.search).has("billing");
  const [page, setPage] = useState(returned ? "billing" : null);
  const [ticket, setTicket] = useState(() => (window.location.hash.startsWith("#ticket=") ? window.location.hash.slice(8) : ""));
  const [documentsFor, setDocumentsFor] = useState(""); // open Documents filtered to one assistant
  const [counts, setCounts] = useState({ assistants: null, documents: null });
  const pages = PAGES.filter((p) => session && p.roles.includes(session.user.role));
  const current = pages.find((p) => p.key === page) ?? pages[0];

  useEffect(() => { document.title = `${tenant().short_name} admin`; }, []);

  // The one-time login link from the sign-up (#ticket=...): log in with it, then forget it
  useEffect(() => {
    if (!ticket) return;
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    request("/admin/login/ticket", { method: "POST", body: { ticket } })
      .then((value) => { saveSession(value); setNotice(""); })
      .catch((err) => setNotice(err.message))
      .finally(() => setTicket(""));
  }, []);

  function saveSession(value) {
    setSession(value);
    try {
      if (value) sessionStorage.setItem(SESSION_KEY, JSON.stringify(value));
      else sessionStorage.removeItem(SESSION_KEY);
    } catch { /* storage blocked: the session stays in memory only */ }
  }

  // Runs a request with the login token; a 401 sends the user back to the login form.
  async function call(request) {
    try {
      return await request(session.token);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        saveSession(null);
        setNotice("Your session has ended. Please log in again.");
      }
      throw err;
    }
  }

  // The numbers in the sidebar (assistants, documents)
  async function refreshCounts() {
    try {
      const agents = await call(listAgents);
      setCounts({ assistants: agents.length, documents: agents.reduce((n, a) => n + (a.documents || 0), 0) });
    } catch { /* the sidebar just shows no numbers */ }
  }

  useEffect(() => { if (session) refreshCounts(); }, [session]);

  async function signOut() {
    await logout(session.token).catch(() => {});
    saveSession(null);
  }

  function open(key, agentId = "") {
    setPage(key);
    setDocumentsFor(agentId);
  }

  if (ticket) return <div className="pf admin"><div className="signin"><p className="note">Logging you in…</p></div></div>;
  if (!session) {
    return <div className="pf admin"><LoginForm onLogin={(value) => { saveSession(value); setNotice(""); setPage(null); }} notice={notice} /></div>;
  }

  return (
    <div className="pf admin">
      <div className="console">
        <nav className="cnav" aria-label="Admin sections">
          <div className="ctitle"><UniversityMark /><span>{tenant().short_name} admin</span></div>
          {pages.map((p) => (
            <button key={p.key} type="button" className={`navlink ${p.key === current.key ? "on" : ""}`}
                    aria-current={p.key === current.key ? "page" : undefined} onClick={() => open(p.key)}>
              {p.title}
              {p.key === "assistants" && counts.assistants !== null && <span>{counts.assistants}</span>}
              {p.key === "documents" && counts.documents !== null && <span>{counts.documents}</span>}
            </button>
          ))}
          <div className="cuser">
            <span>{session.user.name || session.user.email} · {session.user.role === "tenant_admin" ? "admin" : "editor"}</span>
            <span><a href="/" target="_blank" rel="noreferrer">Open the chat ↗</a> · <button type="button" className="link" onClick={signOut}>Log out</button></span>
          </div>
        </nav>
        <main className="cmain">
          {current.key === "assistants" && <AssistantsPage call={call} onChanged={refreshCounts} openDocuments={(id) => open("documents", id)} />}
          {current.key === "documents" && <DocumentsTab key={documentsFor} call={call} initialFilter={documentsFor} onChanged={refreshCounts} />}
          {current.key === "branding" && <BrandingTab call={call} />}
          {current.key === "users" && <UsersPage call={call} me={session.user} />}
          {current.key === "analytics" && <AnalyticsPage call={call} />}
          {current.key === "signin" && <SignInPage call={call} me={session.user} />}
          {current.key === "billing" && <BillingPage call={call} returned={returned} />}
        </main>
      </div>
    </div>
  );
}

function LoginForm({ onLogin, notice }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await login(email, password));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="signin">
      <form className="panel" onSubmit={handleSubmit}>
        <div className="ctitle"><UniversityMark /> <h3>{tenant().name} admin</h3></div>
        {notice && <p className="error">{notice}</p>}
        <label className="field"><span>Email</span>
          <input className="finput" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" autoFocus /></label>
        <label className="field"><span>Password</span>
          <input className="finput" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={!email || !password || busy}>{busy ? "Logging in…" : "Log in"}</button>
      </form>
    </div>
  );
}
