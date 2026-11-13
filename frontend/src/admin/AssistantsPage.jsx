import { useEffect, useRef, useState } from "react";
import {
  createAgent, deleteAgent, getBranding, listAgents, listTemplates, request, updateAgent,
} from "./api.js";

// The six skills, as the design names them
const SKILLS = {
  files: "Questions about uploaded files",
  images: "Questions about pictures",
  cv: "CV rewrites (PDF and Word)",
  editor: "Edit Word, Excel and PDF files",
  map: "Campus map and room codes",
  voice: "Voice call",
};
const MODES = { docs: "Documents only", advice: "Documents + general advice" };
// Settings edited here (the rest of the row is not sent)
const FIELDS = ["name", "description", "audiences", "answer_mode", "skills", "summary", "subtitle", "welcome", "placeholder",
                "examples", "instructions", "prompt_mode", "fallback_en", "fallback_ar", "model", "similarity_threshold", "max_answer_tokens"];

const toDraft = (agent) => ({
  ...Object.fromEntries(FIELDS.map((f) => [f, agent[f]])),
  examples: (agent.examples ?? []).join("\n"), model: agent.model ?? "", similarity_threshold: agent.similarity_threshold ?? "",
});

// The Assistants page, like the design's adminView(): numbers for the last 30 days, then the
// university's assistants on the left (name, who uses it, documents, live or hidden) and the
// selected one's settings on the right. "{university}" in a text becomes the short name.
export default function AssistantsPage({ call, onChanged, openDocuments }) {
  const [agents, setAgents] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [audiences, setAudiences] = useState([]);
  const [numbers, setNumbers] = useState(null);
  const [selected, setSelected] = useState(null);
  const [draft, setDraft] = useState(null);
  const [menu, setMenu] = useState(false); // the "Start from a template" list
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const nameRef = useRef(null);
  const agent = agents.find((a) => a.id === selected) ?? null;
  const dirty = agent && draft && JSON.stringify(draft) !== JSON.stringify(toDraft(agent));

  async function reload(select = selected) {
    try {
      const [list, ready, branding] = await Promise.all([call(listAgents), call(listTemplates), call(getBranding)]);
      setAgents(list);
      setTemplates(ready);
      setAudiences(branding.audiences);
      const chosen = list.find((a) => a.id === select) ?? list[0] ?? null;
      setSelected(chosen?.id ?? null);
      setDraft(chosen ? toDraft(chosen) : null);
      onChanged?.();
    } catch (err) {
      setError(`Could not load the assistants: ${err.message}`);
    }
  }

  useEffect(() => {
    reload();
    call((token) => request("/admin/analytics", { token })).then(setNumbers).catch(() => {});
  }, []);

  function pick(id) {
    if (dirty && !window.confirm("Leave without saving your changes?")) return;
    const chosen = agents.find((a) => a.id === id);
    setSelected(id);
    setDraft(toDraft(chosen));
    setNotice("");
    setError("");
  }

  async function run(action, done, select) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await call(action);
      if (done) setNotice(done);
      await reload(select ?? result?.id ?? selected);
      return result;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function newAssistant() {
    const made = await run((token) => createAgent(token, { name: "New assistant", live: false }),
      "A new, hidden assistant: give it a name and say what it handles, then make it live.");
    if (made) setTimeout(() => { nameRef.current?.focus(); nameRef.current?.select(); }, 50);
  }

  async function fromTemplate(key) {
    setMenu(false);
    await run((token) => createAgent(token, { template_key: key, live: false }),
      "Added from the template, hidden for now. Rename or change it, then make it live.");
  }

  function save() {
    const body = {
      ...draft,
      examples: draft.examples.split("\n").map((e) => e.trim()).filter(Boolean).slice(0, 6),
      model: draft.model.trim() || null,
      similarity_threshold: draft.similarity_threshold === "" ? null : Number(draft.similarity_threshold),
      max_answer_tokens: Number(draft.max_answer_tokens) || 400,
    };
    run((token) => updateAgent(token, agent.id, body), `Saved ${draft.name}.`);
  }

  function remove() {
    if (!window.confirm(`Delete "${agent.name}"? It disappears for everyone. Its chats and documents are kept.`)) return;
    run((token) => deleteAgent(token, agent.id), `Deleted ${agent.name}.`, "");
  }

  const set = (key) => (e) => setDraft((d) => ({ ...d, [key]: e.target.value }));
  const flip = (key, value) => setDraft((d) => ({ ...d, [key]: d[key].includes(value) ? d[key].filter((x) => x !== value) : [...d[key], value] }));
  const audienceTitle = (key) => audiences.find((a) => a.key === key)?.title ?? key;

  return (
    <>
      <div className="crow">
        <h3>Assistants</h3>
        <div className="actions">
          <span className="menu-wrap">
            <button type="button" className="ghost" onClick={() => setMenu(!menu)} aria-expanded={menu} disabled={busy}>Start from a template</button>
            {menu && (
              <span className="menu" role="menu">
                {templates.map((t) => (
                  <button key={t.key} type="button" role="menuitem" onClick={() => fromTemplate(t.key)}>
                    <b>{t.name}</b><small>{t.summary}</small>
                  </button>
                ))}
              </span>
            )}
          </span>
          <button type="button" onClick={newAssistant} disabled={busy}>＋ New assistant</button>
        </div>
      </div>

      <div className="kpis">
        <div className="kpi"><span>Questions, 30 days</span><b>{numbers ? numbers.questions_30d.toLocaleString("en") : "…"}</b><small>to all assistants</small></div>
        <div className="kpi"><span>Active users</span><b>{numbers ? numbers.chats_30d.toLocaleString("en") : "…"}</b><small>chats started, 30 days</small></div>
        <div className="kpi"><span>Unanswered</span><b>{numbers ? `${numbers.unanswered_pct}%` : "…"}</b>
          <small>{numbers ? `${numbers.unanswered_30d} of ${numbers.questions_30d} questions` : ""}</small></div>
        <div className="kpi"><span>Average rating</span><b>{numbers?.average_rating ? `${numbers.average_rating.toFixed(1)} / 5` : "–"}</b>
          <small>{numbers ? `${numbers.ratings} rating${numbers.ratings === 1 ? "" : "s"}` : ""}</small></div>
      </div>

      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}

      <div className="panel-grid">
        <div className="panel">
          <h4>{agents.length} assistant{agents.length === 1 ? "" : "s"}</h4>
          {agents.map((a) => (
            <div className="pickrow" key={a.id}>
              <button type="button" className="agentpick" aria-pressed={a.id === selected} onClick={() => pick(a.id)}>
                <span><b>{a.name}</b><small>{a.audiences.map(audienceTitle).join(", ") || "nobody yet"} · {a.documents} doc{a.documents === 1 ? "" : "s"}</small></span>
              </button>
              <button type="button" className="toggle-button" disabled={busy} title={a.live ? "Live: click to hide" : "Hidden: click to make live"}
                      aria-label={`${a.name}: ${a.live ? "live" : "hidden"}`} aria-pressed={a.live}
                      onClick={() => run((token) => updateAgent(token, a.id, { live: !a.live }), `${a.name} is ${a.live ? "hidden" : "live"}.`, selected)}>
                <span className={`toggle ${a.live ? "on" : ""}`} />
              </button>
            </div>
          ))}
          {agents.length === 0 && <p className="note">No assistants yet. Create the first one with “New assistant”.</p>}
        </div>

        {!agent || !draft ? (
          <div className="panel"><h4>No assistant selected</h4><p className="note">Create one with “New assistant”, or start from a template.</p></div>
        ) : (
          <div className="panel">
            <div className="crow">
              <h4>Edit assistant</h4>
              <span className="actions">
                <button type="button" className="ghost" disabled={busy}
                        onClick={() => run((token) => updateAgent(token, agent.id, { live: !agent.live }), `${agent.name} is ${agent.live ? "hidden" : "live"}.`)}>
                  {agent.live ? "Hide from users" : "Make live"}
                </button>
                <button type="button" className="ghost" onClick={remove} disabled={busy}>Delete</button>
              </span>
            </div>
            <label className="field"><span>Name</span>
              <input ref={nameRef} className="finput" value={draft.name} onChange={set("name")} maxLength={80} placeholder="e.g. Ask Admissions" /></label>
            <label className="field"><span>What it handles</span>
              <textarea className="finput" rows={3} value={draft.description} onChange={set("description")} maxLength={3000} dir="auto"
                        placeholder="Used to greet users and to send questions to the right assistant" /></label>
            <div className="field"><span>Who can use it</span><span className="opts">
              {audiences.map((a) => <button key={a.key} type="button" className="opt" aria-pressed={draft.audiences.includes(a.key)} onClick={() => flip("audiences", a.key)}>{a.title}</button>)}
            </span></div>
            <div className="field"><span>Answers from</span><span className="opts">
              {Object.entries(MODES).map(([key, title]) => <button key={key} type="button" className="opt" aria-pressed={draft.answer_mode === key}
                                                                   onClick={() => setDraft((d) => ({ ...d, answer_mode: key }))}>{title}</button>)}
            </span></div>
            <div className="field"><span>Skills</span><span className="opts">
              {Object.entries(SKILLS).map(([key, title]) => <button key={key} type="button" className="opt" aria-pressed={draft.skills.includes(key)}
                                                                    onClick={() => flip("skills", key)}>{title}</button>)}
            </span></div>
            {agent.skills.some((s) => !agent.active_skills.includes(s)) && (
              <div className="field"><span /><span className="note">Not available at this university: {agent.skills.filter((s) => !agent.active_skills.includes(s)).map((s) => SKILLS[s]).join(", ")}.</span></div>
            )}
            <div className="field"><span>Documents</span><span className="opts">
              <span className="fval">{agent.documents} file{agent.documents === 1 ? "" : "s"} · in <code>{agent.folder}/</code></span>
              <button type="button" className="ghost" onClick={() => openDocuments(agent.id)}>Open documents</button>
            </span></div>

            <details>
              <summary>More settings: texts, instructions, model</summary>
              <div className="moregrid">
                <label className="field"><span>Short description</span><input className="finput" value={draft.summary} onChange={set("summary")} maxLength={200} placeholder="On the start screen" /></label>
                <label className="field"><span>Subtitle</span><input className="finput" value={draft.subtitle} onChange={set("subtitle")} maxLength={200} placeholder="Under the name in the chat" /></label>
                <label className="field"><span>Welcome</span><input className="finput" value={draft.welcome} onChange={set("welcome")} maxLength={300} /></label>
                <label className="field"><span>Placeholder</span><input className="finput" value={draft.placeholder} onChange={set("placeholder")} maxLength={200} placeholder="In the message box" /></label>
                <label className="field"><span>Example questions</span>
                  <textarea className="finput" rows={4} value={draft.examples} onChange={set("examples")} dir="auto" placeholder="One per line, up to 6" /></label>
                <div className="field"><span>Prompt</span><span className="opts">
                  {[["composed", "Built from the instructions"], ["complete", "Instructions are the whole prompt"]].map(([key, title]) => (
                    <button key={key} type="button" className="opt" aria-pressed={draft.prompt_mode === key}
                            onClick={() => setDraft((d) => ({ ...d, prompt_mode: key }))}>{title}</button>))}
                </span></div>
                <label className="field"><span>Instructions</span>
                  <textarea className="finput" rows={draft.prompt_mode === "complete" ? 12 : 5} value={draft.instructions} onChange={set("instructions")} dir="auto" /></label>
                <label className="field"><span>No information (EN)</span><textarea className="finput" rows={2} value={draft.fallback_en} onChange={set("fallback_en")} maxLength={500} /></label>
                <label className="field"><span>No information (AR)</span><textarea className="finput" rows={2} value={draft.fallback_ar} onChange={set("fallback_ar")} maxLength={500} dir="rtl" /></label>
                <label className="field"><span>Model</span><input className="finput" value={draft.model} onChange={set("model")} placeholder="Empty: the platform's" /></label>
                <label className="field"><span>Threshold</span><input className="finput" type="number" min="0" max="1" step="0.01" value={draft.similarity_threshold}
                                                                      onChange={set("similarity_threshold")} placeholder="Empty: the platform's" /></label>
                <label className="field"><span>Longest answer</span><input className="finput" type="number" min="50" max="4000" value={draft.max_answer_tokens}
                                                                           onChange={set("max_answer_tokens")} /></label>
              </div>
            </details>

            <div className="crow">
              <span className="note">{dirty ? "Unsaved changes" : agent.live ? "Live: users can use it" : "Hidden from users"}</span>
              <span className="actions">
                {dirty && <button type="button" className="ghost" onClick={() => setDraft(toDraft(agent))} disabled={busy}>Undo</button>}
                <button type="button" onClick={save} disabled={busy || !dirty || !draft.name.trim() || !draft.audiences.length}>Save changes</button>
              </span>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
