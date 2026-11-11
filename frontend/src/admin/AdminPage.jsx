import { useState } from "react";
import BrandLogo from "../components/BrandLogo.jsx";
import { tenant } from "../tenant.js";
import { UnauthorizedError, login, logout } from "./api.js";
import AssistantsTab from "./AssistantsTab.jsx";
import BrandingTab from "./BrandingTab.jsx";
import DocumentsTab from "./DocumentsTab.jsx";
import UsersTab from "./UsersTab.jsx";
import "./admin.css";

const SESSION_KEY = "adminSession"; // sessionStorage: kept while the tab is open

// Which tabs each role sees: a tenant_admin everything of its university, an editor the documents.
const TABS = [
  { key: "assistants", title: "Assistants", roles: ["tenant_admin"] },
  { key: "documents", title: "Documents", roles: ["tenant_admin", "editor"] },
  { key: "branding", title: "Branding", roles: ["tenant_admin"] },
  { key: "users", title: "Users", roles: ["tenant_admin"] },
];

function savedSession() {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY)) || null;
  } catch {
    return null; // storage blocked: log in again on every visit
  }
}

// /admin: the university admin. Log in with email and password, then manage this university's
// assistants, their documents, its look and its users. Any 401 answer shows the login form again.
export default function AdminPage() {
  const [session, setSession] = useState(savedSession); // { token, user: { email, name, role } }
  const [notice, setNotice] = useState("");
  const tabs = TABS.filter((tab) => session && tab.roles.includes(session.user.role));
  const [tab, setTab] = useState(null);
  const current = tabs.find((t) => t.key === tab) ?? tabs[0];

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

  async function signOut() {
    await logout(session.token).catch(() => {});
    saveSession(null);
  }

  return (
    <div className="admin">
      <header className="topbar">
        <BrandLogo className="topbar-logo" />
        <div className="topbar-title">
          <h1>{tenant().short_name} admin</h1>
          <span>{session ? `${session.user.name || session.user.email} · ${session.user.role === "tenant_admin" ? "Admin" : "Editor"}`
                         : "Assistants, documents, branding and users"}</span>
        </div>
        {session && <button className="secondary" onClick={signOut}>Log out</button>}
      </header>
      <div className="flag-stripe" />
      {session && (
        <nav className="admin-tabs" aria-label="Admin sections">
          {tabs.map((t) => (
            <button key={t.key} className={t.key === current?.key ? "active" : ""} onClick={() => setTab(t.key)}>
              {t.title}
            </button>
          ))}
        </nav>
      )}
      <main className="admin-main">
        {!session ? (
          <LoginForm onLogin={(value) => { saveSession(value); setNotice(""); setTab(null); }} notice={notice} />
        ) : current?.key === "assistants" ? <AssistantsTab call={call} />
          : current?.key === "branding" ? <BrandingTab call={call} />
          : current?.key === "users" ? <UsersTab call={call} me={session.user} />
          : <DocumentsTab call={call} />}
      </main>
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
    <form className="admin-card login-form" onSubmit={handleSubmit}>
      <h2>Log in to {tenant().name}</h2>
      {notice && <p className="error">{notice}</p>}
      <label>
        Email
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" autoFocus />
      </label>
      <label>
        Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      </label>
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={!email || !password || busy}>{busy ? "Logging in…" : "Log in"}</button>
    </form>
  );
}
