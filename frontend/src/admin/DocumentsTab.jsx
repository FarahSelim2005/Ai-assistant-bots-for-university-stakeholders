import { useEffect, useState } from "react";
import { createDocument, deleteDocument, getDocument, listAgents, listDocuments, updateDocument } from "./api.js";
import DocumentForm from "./DocumentForm.jsx";

// The documents each assistant answers from: list (per assistant), add, edit, move, delete.
// Every change is re-indexed by the backend at once.
export default function DocumentsTab({ call }) {
  const [documents, setDocuments] = useState([]);
  const [agents, setAgents] = useState([]); // this university's assistants
  const [filter, setFilter] = useState(""); // "" = all assistants
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(""); // e.g. "Saved and re-indexed (12 chunks)"
  const [form, setForm] = useState(null); // null, { mode: "add" } or { mode: "edit", doc }
  const [busyId, setBusyId] = useState(null); // document being opened or deleted
  const agentLabel = (id) => agents.find((agent) => agent.id === id)?.name ?? "Deleted assistant";

  async function reload() {
    setLoading(true);
    setError("");
    try {
      const [docs, assistants] = await Promise.all([call(listDocuments), call(listAgents)]);
      setDocuments(docs);
      setAgents(assistants);
    } catch (err) {
      setError(`Could not load the documents: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { reload(); }, []);

  async function openEditor(id) {
    setBusyId(id);
    setError("");
    setNotice("");
    try {
      setForm({ mode: "edit", doc: await call((token) => getDocument(token, id)) });
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
      await call((token) => deleteDocument(token, doc.id));
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
    const result = await call((token) => (form.mode === "edit"
      ? updateDocument(token, form.doc.id, values)
      : createDocument(token, values)));
    setForm(null);
    setNotice(`Saved and re-indexed (${result.chunks} chunks).`);
    reload();
  }

  if (form) {
    return <DocumentForm key={form.doc?.id ?? "new"} initial={form.doc ?? (filter ? { agent: filter, isNew: true } : null)}
                         agents={agents} onSave={save} onCancel={() => setForm(null)} />;
  }

  const shown = filter ? documents.filter((d) => d.agent === filter) : documents;
  return (
    <section className="admin-card">
      <div className="list-header">
        <h2>Documents</h2>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by assistant">
          <option value="">All assistants</option>
          {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <button onClick={() => { setForm({ mode: "add" }); setNotice(""); }} disabled={!agents.length}>+ Add document</button>
      </div>

      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}

      {loading ? (
        <p className="muted">Loading documents…</p>
      ) : shown.length === 0 ? (
        <p className="muted">{filter ? `No documents for ${agentLabel(filter)} yet.` : "No documents yet."}</p>
      ) : (
        <table className="doc-table">
          <thead>
            <tr><th>File name</th><th>Assistant</th><th>Last updated</th><th /></tr>
          </thead>
          <tbody>
            {shown.map((doc) => (
              <tr key={doc.id}>
                <td>{doc.filename}</td>
                <td>{agentLabel(doc.agent)} <span className="hint">({doc.folder}/)</span></td>
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
