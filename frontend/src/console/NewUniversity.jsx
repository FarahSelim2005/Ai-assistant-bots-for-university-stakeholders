import { useState } from "react";

const STEPS = ["Name", "Subdomain", "Look", "Assistants", "First admin"];

// The "New university" wizard, inside the console: name -> subdomain -> colours and logo ->
// assistants -> first admin. Step 4 makes any number of assistants with the university's own
// names (and, if wanted, ready-made ones from the templates, renamed here too), up to the
// plan's limit. Everything is made in one go at the end (POST /console/universities).
export default function NewUniversity({ call, plans, templates, onDone, onCancel }) {
  const [step, setStep] = useState(0);
  const [made, setMade] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [values, setValues] = useState({
    name: "", short_name: "", slug: "", host: "", brand_primary: "#1f4e79", brand_accent: "#e8a317", brand_dark: "#1a1a1a",
    logo_url: "", plan: "free", admin: { email: "", name: "", password: "" },
  });
  // The assistants to make: { key (for React), name, description, template_key? }
  const [assistants, setAssistants] = useState([]);
  const [draft, setDraft] = useState({ name: "", description: "" });
  const [template, setTemplate] = useState("");
  const set = (key) => (e) => setValues((v) => ({ ...v, [key]: e.target.value }));
  const setAdmin = (key) => (e) => setValues((v) => ({ ...v, admin: { ...v.admin, [key]: e.target.value } }));
  const plan = plans.find((p) => p.key === values.plan);
  const limit = plan?.max_assistants ?? null;
  const full = limit !== null && assistants.length >= limit;
  const slug = values.slug || values.short_name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  function pickLogo(event) {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 300 * 1024) return setError("The logo must be smaller than 300 KB.");
    const reader = new FileReader();
    reader.onload = () => { setValues((v) => ({ ...v, logo_url: reader.result })); setError(""); };
    reader.readAsDataURL(file);
  }

  function addOwn(event) {
    event.preventDefault();
    if (!draft.name.trim() || full) return;
    setAssistants((list) => [...list, { key: crypto.randomUUID(), name: draft.name.trim(), description: draft.description.trim() }]);
    setDraft({ name: "", description: "" });
  }

  function addTemplate() {
    const t = templates.find((x) => x.key === template);
    if (!t || full) return;
    setAssistants((list) => [...list, { key: crypto.randomUUID(), name: t.name, description: t.summary, template_key: t.key }]);
    setTemplate("");
  }

  const change = (key, field, value) => setAssistants((list) => list.map((a) => (a.key === key ? { ...a, [field]: value } : a)));

  const ready = [
    values.name.trim() && values.short_name.trim(),
    /^[a-z0-9][a-z0-9-]{0,39}$/.test(slug),
    true,
    assistants.every((a) => a.name.trim()) && (limit === null || assistants.length <= limit),
    values.admin.email.includes("@") && values.admin.password.length >= 10,
  ];

  async function create() {
    setBusy(true);
    setError("");
    try {
      const body = { ...values, slug, host: values.host || null, templates: [],
                     assistants: assistants.map(({ name, description, template_key }) => ({ name, description, template_key: template_key || null })) };
      setMade(await call("/console/universities", { method: "POST", body }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (made) {
    return (
      <>
        <div className="crow"><h3>{values.name} is ready</h3></div>
        <div className="panel">
          <div className="field"><span>Chat</span><a href={made.url} target="_blank" rel="noreferrer"><code>{made.url}</code></a></div>
          <div className="field"><span>Admin</span><span><a href={made.admin_url} target="_blank" rel="noreferrer"><code>{made.admin_url}</code></a> · log in as {values.admin.email}</span></div>
          <div className="field"><span>Assistants</span><span>{assistants.map((a) => a.name).join(", ") || "none yet"}</span></div>
          <p className="note">Give the admin their password yourself. The assistants answer once the university adds documents on its Documents page.</p>
          <div><button type="button" onClick={() => onDone(`${values.name} was created.`)}>Back to the universities</button></div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="crow">
        <h3>New university</h3>
        <button type="button" className="ghost" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
      <ol className="steps">
        {STEPS.map((title, index) => (
          <li key={title} className={index === step ? "on" : index < step ? "done" : ""}>{index + 1} {title}</li>
        ))}
      </ol>

      <div className="panel">
        {step === 0 && (
          <>
            <h4>Name</h4>
            <label className="field"><span>Name</span><input className="finput" value={values.name} onChange={set("name")} placeholder="e.g. Nile Valley University" autoFocus /></label>
            <label className="field"><span>Short name</span><input className="finput" value={values.short_name} onChange={set("short_name")} placeholder="e.g. NVU (used in texts)" maxLength={30} /></label>
          </>
        )}
        {step === 1 && (
          <>
            <h4>Subdomain</h4>
            <label className="field"><span>Subdomain</span><input className="finput" value={slug} onChange={(e) => setValues((v) => ({ ...v, slug: e.target.value.toLowerCase() }))} maxLength={40} /></label>
            <label className="field"><span>Own address</span><input className="finput" value={values.host} onChange={set("host")} placeholder={`${slug || "name"}.localhost (optional)`} /></label>
            <p className="note">The chat will be at <code>http://{values.host || `${slug || "name"}.localhost`}:5173</code>.</p>
          </>
        )}
        {step === 2 && (
          <>
            <h4>Colours and logo</h4>
            {[["brand_primary", "Main"], ["brand_accent", "Accent"], ["brand_dark", "Dark"]].map(([key, title]) => (
              <label className="field" key={key}><span>{title}</span>
                <span className="opts"><input type="color" value={values[key]} onChange={set(key)} aria-label={`${title} colour`} /><code>{values[key]}</code></span>
              </label>
            ))}
            <div className="field"><span>Logo</span>
              <span className="opts">
                {values.logo_url ? <img src={values.logo_url} alt="Logo" style={{ height: 40 }} />
                  : <span className="clogo" style={{ background: values.brand_primary, color: "#fff", width: 40, height: 40 }}>{values.short_name || "?"}</span>}
                <label><span className="pill acc" style={{ cursor: "pointer" }}>Choose a picture</span>
                  <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={pickLogo} hidden /></label>
                {values.logo_url && <button type="button" className="ghost" onClick={() => setValues((v) => ({ ...v, logo_url: "" }))}>No logo</button>}
              </span>
            </div>
          </>
        )}
        {step === 3 && (
          <>
            <div className="crow">
              <h4>Assistants{limit !== null ? ` · ${assistants.length} of ${limit}` : ` · ${assistants.length}`}</h4>
              <label className="opts" style={{ alignItems: "center" }}>
                <span className="note">Plan</span>
                <select className="finput" style={{ width: "auto" }} value={values.plan} onChange={set("plan")}>
                  {plans.map((p) => <option key={p.key} value={p.key}>{p.name} ({p.max_assistants ?? "any number of"} assistants)</option>)}
                </select>
              </label>
            </div>
            {assistants.length === 0 && <p className="note">No assistants yet. Add your own below, or a ready-made one. You can also add them later on the admin page.</p>}
            {assistants.map((a) => (
              <div className="wizrow" key={a.key}>
                <input className="finput" value={a.name} onChange={(e) => change(a.key, "name", e.target.value)} maxLength={80} aria-label="Assistant name" />
                <span>
                  <input className="finput" value={a.description} onChange={(e) => change(a.key, "description", e.target.value)} maxLength={600}
                         aria-label="What it handles" placeholder="What it handles" />
                  {a.template_key && <small>from the template {a.template_key}</small>}
                </span>
                <button type="button" className="ghost" onClick={() => setAssistants((list) => list.filter((x) => x.key !== a.key))}>Remove</button>
              </div>
            ))}
            <form className="wizrow" onSubmit={addOwn}>
              <input className="finput" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} maxLength={80}
                     placeholder="Name, e.g. Ask Admissions" aria-label="New assistant's name" disabled={full} />
              <input className="finput" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} maxLength={600}
                     placeholder="What it handles, e.g. applying, deadlines and fees" aria-label="What the new assistant handles" disabled={full} />
              <button type="submit" disabled={!draft.name.trim() || full}>＋ Add assistant</button>
            </form>
            <div className="wizrow">
              <select className="finput" value={template} onChange={(e) => setTemplate(e.target.value)} disabled={full} aria-label="Ready-made assistant">
                <option value="">Or a ready-made one…</option>
                {templates.map((t) => <option key={t.key} value={t.key}>{t.name}</option>)}
              </select>
              <span className="note">{templates.find((t) => t.key === template)?.summary ?? "Its instructions and texts are copied; rename it above."}</span>
              <button type="button" className="ghost" onClick={addTemplate} disabled={!template || full}>Add</button>
            </div>
            {full && <p className="note">The {plan.name} plan allows {limit} assistants. Choose a bigger plan above for more.</p>}
            <p className="note">A new assistant answers only from the documents the university adds for it (no CV rewrites or campus map yet).</p>
          </>
        )}
        {step === 4 && (
          <>
            <h4>First admin</h4>
            <label className="field"><span>Email</span><input className="finput" type="email" value={values.admin.email} onChange={setAdmin("email")} /></label>
            <label className="field"><span>Name</span><input className="finput" value={values.admin.name} onChange={setAdmin("name")} /></label>
            <label className="field"><span>Password</span><input className="finput" type="password" value={values.admin.password} onChange={setAdmin("password")}
                                                             autoComplete="new-password" placeholder="at least 10 characters" /></label>
          </>
        )}
        {error && <p className="error">{error}</p>}
        <div className="crow">
          <span>{step > 0 && <button type="button" className="ghost" onClick={() => setStep(step - 1)} disabled={busy}>← Back</button>}</span>
          {step < STEPS.length - 1
            ? <button type="button" onClick={() => setStep(step + 1)} disabled={!ready[step]}>Next →</button>
            : <button type="button" onClick={create} disabled={busy || !ready.every(Boolean)}>{busy ? "Creating…" : "Create university"}</button>}
        </div>
      </div>
    </>
  );
}
