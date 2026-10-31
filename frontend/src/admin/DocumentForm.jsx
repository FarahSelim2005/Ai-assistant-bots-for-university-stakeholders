import { useState } from "react";
import { ADMIN_AGENTS } from "./agents.js";

// Form to add a document or edit one. A picked .md/.txt file fills the text box, so it
// can still be edited before saving. Changing the agent of an existing document moves it.
// `onSave({ agent, filename, content })` must return a promise; errors are shown here.
export default function DocumentForm({ initial, onSave, onCancel }) {
  const editing = Boolean(initial);
  const [agent, setAgent] = useState(initial?.agent ?? ""); // no default: the admin must choose
  const [filename, setFilename] = useState(initial?.filename ?? "");
  const [content, setContent] = useState(initial?.content ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function handleFile(event) {
    const file = event.target.files[0];
    event.target.value = ""; // so picking the same file again still works
    if (!file) return;
    if (!/\.(md|txt)$/i.test(file.name)) {
      setError("Only .md or .txt files can be added.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setContent(reader.result);
      setFilename(file.name);
      setError("");
    };
    reader.onerror = () => setError("The file could not be read.");
    reader.readAsText(file);
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSave({ agent, filename: filename.trim() || defaultFilename(content), content });
    } catch (err) {
      setError(err.message);
      setSaving(false); // on success the parent closes the form
    }
  }

  return (
    <form className="admin-card doc-form" onSubmit={handleSubmit}>
      <h2>{editing ? `Edit ${initial.filename}` : "Add document"}</h2>

      <label>
        Agent
        <select value={agent} onChange={(e) => setAgent(e.target.value)} required>
          <option value="" disabled>Choose an agent…</option>
          {ADMIN_AGENTS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
        </select>
      </label>
      {editing && agent !== initial.agent && (
        <p className="muted small">Saving moves this document to the chosen agent.</p>
      )}

      <div className="form-row">
        <label className="grow">
          File name
          <input value={filename} onChange={(e) => setFilename(e.target.value)} placeholder="e.g. advising_rules.md" />
        </label>
        <label className="file-pick">
          <span className="button-like secondary">Pick a .md or .txt file</span>
          <input type="file" accept=".md,.txt" onChange={handleFile} hidden />
        </label>
      </div>

      <label>
        Content
        <span className="hint">Start each topic with a ## Heading. Each section is searched separately.</span>
        <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={18}
                  placeholder={"## First topic\nText about the first topic...\n\n## Second topic\n..."} dir="auto" />
      </label>

      {error && <p className="error">{error}</p>}
      <div className="form-actions">
        <button type="submit" disabled={!agent || !content.trim() || saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={saving}>Cancel</button>
      </div>
    </form>
  );
}

// "document.md", or a name from the first heading ("# Advising rules" -> "advising_rules.md").
function defaultFilename(content) {
  const heading = content.match(/^#+\s*(.+)$/m)?.[1] ?? "document";
  const slug = heading.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return `${slug || "document"}.md`;
}
