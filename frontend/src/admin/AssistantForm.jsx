import { useState } from "react";
import { tenant } from "../tenant.js";

const SKILLS = [
  { key: "files", title: "Files", text: "reads attached documents (PDF, Word, Excel, PowerPoint, text)" },
  { key: "images", title: "Pictures", text: "reads attached pictures" },
  { key: "editor", title: "Editor", text: "edits, translates and converts documents" },
  { key: "cv", title: "CV rewrites", text: "restructures CVs (needs a CV model trained for this university)" },
  { key: "map", title: "Campus map", text: "rooms, buildings and places (needs this university's campus map)" },
  { key: "voice", title: "Voice", text: "the voice call button" },
];
const TEXT_FIELDS = ["name", "summary", "subtitle", "description", "instructions", "fallback_en", "fallback_ar",
                     "welcome", "placeholder", "model"];

// Every setting of one assistant. `agent`: the assistant, or { isNew: true } for a new one.
// "{university}" in any text becomes the university's short name.
export default function AssistantForm({ agent, audiences, onSave, onCancel }) {
  const isNew = Boolean(agent.isNew);
  const [values, setValues] = useState(() => ({
    name: agent.name ?? "", summary: agent.summary ?? "", subtitle: agent.subtitle ?? "",
    description: agent.description ?? "", audiences: agent.audiences ?? audiences.map((a) => a.key),
    answer_mode: agent.answer_mode ?? "docs", prompt_mode: agent.prompt_mode ?? "composed",
    instructions: agent.instructions ?? "", fallback_en: agent.fallback_en ?? "Sorry, I don't have information about that.",
    fallback_ar: agent.fallback_ar ?? "", welcome: agent.welcome ?? "", placeholder: agent.placeholder ?? "",
    examples: (agent.examples ?? []).join("\n"), skills: agent.skills ?? ["files", "images", "editor", "voice"],
    model: agent.model ?? "", similarity_threshold: agent.similarity_threshold ?? "",
    max_answer_tokens: agent.max_answer_tokens ?? 400, live: agent.live ?? true,
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = (key) => (event) => setValues((v) => ({ ...v, [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value }));
  const toggle = (key, item) => setValues((v) => ({
    ...v, [key]: v[key].includes(item) ? v[key].filter((x) => x !== item) : [...v[key], item],
  }));

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const body = {
      ...Object.fromEntries(TEXT_FIELDS.map((key) => [key, values[key]])),
      model: values.model.trim() || null,
      audiences: values.audiences, answer_mode: values.answer_mode, prompt_mode: values.prompt_mode,
      examples: values.examples.split("\n").map((e) => e.trim()).filter(Boolean).slice(0, 6),
      skills: values.skills, live: values.live,
      max_answer_tokens: Number(values.max_answer_tokens) || 400,
      similarity_threshold: values.similarity_threshold === "" ? null : Number(values.similarity_threshold),
    };
    try {
      await onSave(body);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  }

  const inactive = (agent.skills ?? []).filter((s) => !(agent.active_skills ?? []).includes(s));
  return (
    <form className="admin-card assistant-form" onSubmit={handleSubmit}>
      <h2>{isNew ? "New assistant" : `Edit ${agent.name}`}</h2>
      {!isNew && <p className="hint">Documents folder: <code>{agent.folder}/</code> · "{"{university}"}" in a text becomes "{tenant().short_name}".</p>}

      <div className="form-grid">
        <label>Name<input value={values.name} onChange={set("name")} required maxLength={80} /></label>
        <label>Short description (start screen)<input value={values.summary} onChange={set("summary")} maxLength={200} /></label>
        <label>Subtitle (chat header)<input value={values.subtitle} onChange={set("subtitle")} maxLength={200} /></label>
        <label>Placeholder (message box)<input value={values.placeholder} onChange={set("placeholder")} maxLength={200} /></label>
      </div>

      <fieldset>
        <legend>For</legend>
        {audiences.map((a) => (
          <label key={a.key} className="check">
            <input type="checkbox" checked={values.audiences.includes(a.key)} onChange={() => toggle("audiences", a.key)} />
            {a.title}
          </label>
        ))}
      </fieldset>

      <div className="form-grid">
        <label>
          Answers
          <select value={values.answer_mode} onChange={set("answer_mode")}>
            <option value="docs">Only from its documents</option>
            <option value="advice">From its documents, plus general advice</option>
          </select>
        </label>
        <label>
          Prompt
          <select value={values.prompt_mode} onChange={set("prompt_mode")}>
            <option value="composed">Built from the instructions below (recommended)</option>
            <option value="complete">The instructions are the whole prompt</option>
          </select>
        </label>
      </div>

      <label>
        What it handles
        <span className="hint">Decides which questions are handed over to this assistant.</span>
        <textarea rows={3} value={values.description} onChange={set("description")} maxLength={3000} dir="auto" />
      </label>
      <label>
        Instructions
        <span className="hint">What it does and how, in a few sentences. The platform adds the rules for answering from documents.</span>
        <textarea rows={values.prompt_mode === "complete" ? 14 : 6} value={values.instructions} onChange={set("instructions")} dir="auto" />
      </label>

      <div className="form-grid">
        <label>"No information" answer (English)<textarea rows={2} value={values.fallback_en} onChange={set("fallback_en")} maxLength={500} /></label>
        <label>"No information" answer (Arabic)<textarea rows={2} value={values.fallback_ar} onChange={set("fallback_ar")} maxLength={500} dir="rtl" /></label>
      </div>
      <label>Welcome text<input value={values.welcome} onChange={set("welcome")} maxLength={300} /></label>
      <label>
        Example questions
        <span className="hint">One per line, up to 6: shown as buttons in an empty chat.</span>
        <textarea rows={4} value={values.examples} onChange={set("examples")} dir="auto" />
      </label>

      <fieldset>
        <legend>Skills</legend>
        {SKILLS.map((skill) => (
          <label key={skill.key} className="check">
            <input type="checkbox" checked={values.skills.includes(skill.key)} onChange={() => toggle("skills", skill.key)} />
            <span><b>{skill.title}</b> <span className="hint">{skill.text}</span></span>
          </label>
        ))}
        {inactive.length > 0 && <p className="hint">Not available at this university: {inactive.join(", ")}.</p>}
      </fieldset>

      <details>
        <summary>Advanced</summary>
        <div className="form-grid">
          <label>Model (empty: the platform's)<input value={values.model} onChange={set("model")} placeholder="provider/model-name" /></label>
          <label>Similarity threshold (empty: the platform's)
            <input type="number" min="0" max="1" step="0.01" value={values.similarity_threshold} onChange={set("similarity_threshold")} />
          </label>
          <label>Longest answer (tokens)<input type="number" min="50" max="4000" value={values.max_answer_tokens} onChange={set("max_answer_tokens")} /></label>
        </div>
      </details>

      <label className="check"><input type="checkbox" checked={values.live} onChange={set("live")} /> Shown to users</label>

      {error && <p className="error">{error}</p>}
      <div className="form-actions">
        <button type="submit" disabled={saving || !values.name.trim() || !values.audiences.length}>{saving ? "Saving…" : "Save"}</button>
        <button type="button" className="secondary" onClick={onCancel} disabled={saving}>Cancel</button>
      </div>
    </form>
  );
}
