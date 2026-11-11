import { useEffect, useState } from "react";
import {
  createAgent, deleteAgent, getBranding, listAgents, listTemplates, orderAgents, updateAgent,
} from "./api.js";
import AssistantForm from "./AssistantForm.jsx";

// This university's assistants: create (from a ready-made template or blank), edit every
// setting, reorder, hide/show and delete. Deleting keeps the assistant's chats and documents.
export default function AssistantsTab({ call }) {
  const [agents, setAgents] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [audiences, setAudiences] = useState([]); // [{ key, title }] of this university
  const [template, setTemplate] = useState("");
  const [editing, setEditing] = useState(null); // an assistant, or { isNew: true }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function reload() {
    setError("");
    try {
      const [list, ready, branding] = await Promise.all([call(listAgents), call(listTemplates), call(getBranding)]);
      setAgents(list);
      setTemplates(ready);
      setAudiences(branding.audiences);
      return list;
    } catch (err) {
      setError(`Could not load the assistants: ${err.message}`);
      return [];
    }
  }

  useEffect(() => { reload(); }, []);

  // Runs a change, shows its result, reloads the list.
  async function run(action, done) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await call(action);
      setNotice(done);
      await reload();
      return result;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function addFromTemplate() {
    const made = await run((token) => createAgent(token, { template_key: template }),
      "Assistant added from the template. Change anything you like, then save.");
    if (made) {
      const list = await reload();
      setEditing(list.find((a) => a.id === made.id) ?? null);
    }
  }

  function move(index, step) {
    const ids = agents.map((a) => a.id);
    [ids[index], ids[index + step]] = [ids[index + step], ids[index]];
    run((token) => orderAgents(token, ids), "Order saved.");
  }

  function remove(agent) {
    if (!window.confirm(`Delete "${agent.name}"? It disappears for everyone; its chats and documents are kept.`)) return;
    run((token) => deleteAgent(token, agent.id), `Deleted ${agent.name}.`);
  }

  async function save(values) {
    await call((token) => (editing.isNew ? createAgent(token, values) : updateAgent(token, editing.id, values)));
    setEditing(null);
    setNotice(`Saved ${values.name ?? editing.name}.`);
    reload();
  }

  if (editing) {
    return <AssistantForm agent={editing} audiences={audiences} onSave={save} onCancel={() => setEditing(null)} />;
  }

  return (
    <section className="admin-card">
      <div className="list-header">
        <h2>Assistants</h2>
        <select value={template} onChange={(e) => setTemplate(e.target.value)} aria-label="Ready-made assistant">
          <option value="">Ready-made assistant…</option>
          {templates.map((t) => <option key={t.key} value={t.key}>{t.name}</option>)}
        </select>
        <button className="secondary" onClick={addFromTemplate} disabled={!template || busy}>Add</button>
        <button onClick={() => setEditing({ isNew: true })} disabled={busy}>+ New assistant</button>
      </div>
      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}
      {agents.length === 0 ? (
        <p className="muted">No assistants yet. Add a ready-made one or make a new one.</p>
      ) : (
        <table className="doc-table">
          <thead>
            <tr><th>Order</th><th>Assistant</th><th>For</th><th>Skills</th><th /></tr>
          </thead>
          <tbody>
            {agents.map((agent, index) => (
              <tr key={agent.id} className={agent.live ? "" : "hidden-row"}>
                <td className="order-cell">
                  <button className="secondary" onClick={() => move(index, -1)} disabled={busy || index === 0}
                          aria-label={`Move ${agent.name} up`}>↑</button>
                  <button className="secondary" onClick={() => move(index, 1)} disabled={busy || index === agents.length - 1}
                          aria-label={`Move ${agent.name} down`}>↓</button>
                </td>
                <td>
                  <b>{agent.name}</b>{!agent.live && <span className="tag">Hidden</span>}
                  <div className="hint">{agent.summary}</div>
                </td>
                <td>{agent.audiences.map((key) => audiences.find((a) => a.key === key)?.title ?? key).join(", ")}</td>
                <td className="hint">{agent.active_skills.join(", ") || "-"}</td>
                <td className="row-actions">
                  <button className="secondary" onClick={() => setEditing(agent)} disabled={busy}>Edit</button>
                  <button className="secondary" disabled={busy}
                          onClick={() => run((token) => updateAgent(token, agent.id, { live: !agent.live }),
                                             `${agent.name} is ${agent.live ? "hidden" : "shown again"}.`)}>
                    {agent.live ? "Hide" : "Show"}
                  </button>
                  <button className="danger" onClick={() => remove(agent)} disabled={busy}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
