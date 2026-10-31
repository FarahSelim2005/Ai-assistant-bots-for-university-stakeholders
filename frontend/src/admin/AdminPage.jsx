import { useEffect, useState } from "react";
import { ADMIN_AGENTS, agentLabel } from "./agents.js";
import {
  UnauthorizedError, createDocument, deleteDocument, getDocument, listDocuments, login, updateDocument,
} from "./api.js";
import DocumentForm from "./DocumentForm.jsx";
import "./admin.css";

const TOKEN_KEY = "adminToken"; // sessionStorage: kept while the tab is open

function savedToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return ""; // storage blocked: log in again on every visit
  }
}

// /admin: log in with the admin password, then list, add, edit and delete the documents
// the agents answer from. Any 401 answer shows the login form again.
export default function AdminPage() {
  const [token, setToken] = useState(savedToken);
  const [loginError, setLoginError] = useState("");

  function saveToken(value) {
    setToken(value);
    try {
      if (value) sessionStorage.setItem(TOKEN_KEY, value);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch { /* storage blocked: the token stays in memory only */ }
  }

  function loggedOut(message = "") {
    saveToken("");
    setLoginError(message);
  }

  return (
    <div className="admin">
      <header className="topbar">
        <img src="/giu-logo.jpg" alt="German International University" className="topbar-logo" />
        <div className="topbar-title">
          <h1>Admin: documents</h1>
          <span>Add, edit and delete the documents the assistants answer from</span>
        </div>
        {token && <button className="secondary" onClick={() => loggedOut()}>Log out</button>}
      </header>
      <div className="flag-stripe" />
      <main className="admin-main">
        {token
          ? <Documents token={token} onUnauthorized={() => loggedOut("Your session has ended. Please log in again.")} />
          : <LoginForm onLogin={(value) => { saveToken(value); setLoginError(""); }} notice={loginError} />}
      </main>
    </div>
  );
}

function LoginForm({ onLogin, notice }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await login(password);
      onLogin(data.token);
    } catch (err) {
      setError(err instanceof UnauthorizedError ? "Wrong password." : err.message);
      setBusy(false);
    }
  }

  return (
    <form className="admin-card login-form" onSubmit={handleSubmit}>
      <h2>Admin login</h2>
      {notice && <p className="error">{notice}</p>}
      <label>
        Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
      </label>
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={!password || busy}>{busy ? "Logging in…" : "Log in"}</button>
    </form>
  );
}

function Documents({ token, onUnauthorized }) {
  const [documents, setDocuments] = useState([]);
  const [filter, setFilter] = useState(""); // "" = all agents
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(""); // e.g. "Saved and re-indexed (12 chunks)"
  const [form, setForm] = useState(null); // null, { mode: "add" } or { mode: "edit", doc }
  const [busyId, setBusyId] = useState(null); // document being opened or deleted

  // Runs a request; a 401 sends the admin back to the login form.
  async function call(request) {
    try {
      return await request();
    } catch (err) {
      if (err instanceof UnauthorizedError) onUnauthorized();
      throw err;
    }
  }

  async function reload() {
    setLoading(true);
    setError("");
    try {
      setDocuments(await call(() => listDocuments(token)));
    } catch (err) {
      setError(`Could not load the documents: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { reload(); }, [token]);

  async function openEditor(id) {
    setBusyId(id);
    setError("");
    setNotice("");
    try {
      setForm({ mode: "edit", doc: await call(() => getDocument(token, id)) });
    } catch (err) {
      setError(`Could not open the document: ${err.message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function remove(doc) {
    if (!window.confirm(`Delete "${doc.filename}" (${agentLabel(doc.agent)})? The assistant will no longer answer from it.`)) return;
    setBusyId(doc.id);
    setError("");
    setNotice("");
    try {
      await call(() => deleteDocument(token, doc.id));
      setNotice(`Deleted ${doc.filename}.`);
      await reload();
    } catch (err) {
      setError(`Could not delete ${doc.filename}: ${err.message}`);
    } finally {
      setBusyId(null);
    }
  }

  // Called by the form; an error is thrown back so the form shows it.
  async function save(values) {
    const result = await call(() => (form.mode === "edit"
      ? updateDocument(token, form.doc.id, values)
      : createDocument(token, values)));
    setForm(null);
    setNotice(`Saved and re-indexed (${result.chunks} chunks).`);
    reload();
  }

  if (form) {
    return <DocumentForm key={form.doc?.id ?? "new"} initial={form.doc} onSave={save} onCancel={() => setForm(null)} />;
  }

  const shown = filter ? documents.filter((d) => d.agent === filter) : documents;
  return (
    <section className="admin-card">
      <div className="list-header">
        <h2>Documents</h2>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by agent">
          <option value="">All agents</option>
          {ADMIN_AGENTS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
        </select>
        <button onClick={() => { setForm({ mode: "add" }); setNotice(""); }}>+ Add document</button>
      </div>

      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}

      {loading ? (
        <p className="muted">Loading documents…</p>
      ) : shown.length === 0 ? (
        <p className="muted">{filter ? `No documents for ${agentLabel(filter)}.` : "No documents yet."}</p>
      ) : (
        <table className="doc-table">
          <thead>
            <tr><th>File name</th><th>Agent</th><th>Last updated</th><th /></tr>
          </thead>
          <tbody>
            {shown.map((doc) => (
              <tr key={doc.id}>
                <td>{doc.filename}</td>
                <td>{agentLabel(doc.agent)}</td>
                <td>{doc.updated_at ? new Date(doc.updated_at).toLocaleString() : "-"}</td>
                <td className="row-actions">
                  <button className="secondary" onClick={() => openEditor(doc.id)} disabled={busyId !== null}>
                    {busyId === doc.id ? "…" : "Edit"}
                  </button>
                  <button className="danger" onClick={() => remove(doc)} disabled={busyId !== null}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
