import { useEffect, useState } from "react";

const STEPS = ["Name", "Subdomain", "Look", "Assistants", "First admin"];

// The "New university" wizard: name -> subdomain -> colours and logo -> plan and assistants ->
// first admin. Everything is made in one go at the end (POST /console/universities).
export default function NewUniversity({ call, plans, onDone, onCancel }) {
  const [step, setStep] = useState(0);
  const [templates, setTemplates] = useState([]);
  const [made, setMade] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [values, setValues] = useState({
    name: "", short_name: "", slug: "", host: "", brand_primary: "#1f4e79", brand_accent: "#e8a317", brand_dark: "#1a1a1a",
    logo_url: "", plan: "free", templates: ["labs_research"], admin: { email: "", name: "", password: "" },
  });
  const set = (key) => (e) => setValues((v) => ({ ...v, [key]: e.target.value }));
  const setAdmin = (key) => (e) => setValues((v) => ({ ...v, admin: { ...v.admin, [key]: e.target.value } }));
  const plan = plans.find((p) => p.key === values.plan);
  const slug = values.slug || values.short_name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  useEffect(() => { call("/console/templates").then(setTemplates).catch((err) => setError(err.message)); }, []);

  function pickLogo(event) {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 300 * 1024) return setError("The logo must be smaller than 300 KB.");
    const reader = new FileReader();
    reader.onload = () => { setValues((v) => ({ ...v, logo_url: reader.result })); setError(""); };
    reader.readAsDataURL(file);
  }

  function toggleTemplate(key) {
    setValues((v) => ({ ...v, templates: v.templates.includes(key) ? v.templates.filter((k) => k !== key) : [...v.templates, key] }));
  }

  const ready = [
    values.name.trim() && values.short_name.trim(),
    /^[a-z0-9][a-z0-9-]{0,39}$/.test(slug),
    true,
    !plan?.max_assistants || values.templates.length <= plan.max_assistants,
    values.admin.email.includes("@") && values.admin.password.length >= 10,
  ];

  async function create() {
    setBusy(true);
    setError("");
    try {
      setMade(await call("/console/universities", { method: "POST", body: { ...values, slug, host: values.host || null } }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (made) {
    return (
      <section className="admin-card">
        <h2>{values.name} is ready</h2>
        <p>Chat: <a href={made.url} target="_blank" rel="noreferrer">{made.url}</a></p>
        <p>Admin: <a href={made.admin_url} target="_blank" rel="noreferrer">{made.admin_url}</a> (log in as {values.admin.email})</p>
        <p className="hint">Give the admin their password yourself. They can add documents to the assistants on the Documents tab.</p>
        <button onClick={() => onDone(`${values.name} was created.`)}>Back to the universities</button>
      </section>
    );
  }

  return (
    <section className="admin-card wizard">
      <h2>New university</h2>
      <ol className="wizard-steps">
        {STEPS.map((title, index) => (
          <li key={title} className={index === step ? "current" : index < step ? "done" : ""}>{index + 1}. {title}</li>
        ))}
      </ol>

      {step === 0 && (
        <div className="form-grid">
          <label>Name<input value={values.name} onChange={set("name")} placeholder="e.g. Nile Valley University" autoFocus /></label>
          <label>Short name (used in texts)<input value={values.short_name} onChange={set("short_name")} placeholder="e.g. NVU" maxLength={30} /></label>
        </div>
      )}
      {step === 1 && (
        <>
          <label>Subdomain<input value={slug} onChange={(e) => setValues((v) => ({ ...v, slug: e.target.value.toLowerCase() }))} maxLength={40} /></label>
          <p className="hint">The chat will be at <b>http://{values.host || `${slug}.localhost`}:5173</b>.</p>
          <label>Its own address (optional)<input value={values.host} onChange={set("host")} placeholder={`${slug || "name"}.localhost`} /></label>
        </>
      )}
      {step === 2 && (
        <>
          <div className="colour-row">
            {[["brand_primary", "Main"], ["brand_accent", "Accent"], ["brand_dark", "Dark"]].map(([key, title]) => (
              <label key={key} className="colour">{title}<input type="color" value={values[key]} onChange={set(key)} /><code>{values[key]}</code></label>
            ))}
          </div>
          <div className="logo-row">
            {values.logo_url ? <img src={values.logo_url} alt="Logo" className="logo-preview" />
              : <span className="text-logo logo-preview" style={{ background: values.brand_primary }}>{values.short_name || "Logo"}</span>}
            <label className="file-pick"><span className="button-like secondary">Choose a logo</span>
              <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={pickLogo} hidden /></label>
            {values.logo_url && <button type="button" className="secondary" onClick={() => setValues((v) => ({ ...v, logo_url: "" }))}>No logo</button>}
          </div>
        </>
      )}
      {step === 3 && (
        <>
          <label>Plan
            <select value={values.plan} onChange={set("plan")}>
              {plans.map((p) => <option key={p.key} value={p.key}>{p.name} ({p.max_assistants ?? "any number of"} assistants)</option>)}
            </select>
          </label>
          <fieldset>
            <legend>Ready-made assistants to start with</legend>
            {templates.map((t) => (
              <label key={t.key} className="check">
                <input type="checkbox" checked={values.templates.includes(t.key)} onChange={() => toggleTemplate(t.key)} />
                <span><b>{t.name}</b> <span className="hint">{t.summary}</span></span>
              </label>
            ))}
            {!ready[3] && <p className="error">The {plan.name} plan allows {plan.max_assistants} assistants.</p>}
          </fieldset>
          <p className="hint">The admin can rename and change them, and add more, on the admin page.</p>
        </>
      )}
      {step === 4 && (
        <div className="form-grid">
          <label>Admin email<input type="email" value={values.admin.email} onChange={setAdmin("email")} /></label>
          <label>Name<input value={values.admin.name} onChange={setAdmin("name")} /></label>
          <label>Password (at least 10 characters)
            <input type="password" value={values.admin.password} onChange={setAdmin("password")} autoComplete="new-password" />
          </label>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      <div className="form-actions">
        {step > 0 && <button type="button" className="secondary" onClick={() => setStep(step - 1)} disabled={busy}>← Back</button>}
        {step < STEPS.length - 1
          ? <button type="button" onClick={() => setStep(step + 1)} disabled={!ready[step]}>Next →</button>
          : <button type="button" onClick={create} disabled={busy || !ready.every(Boolean)}>{busy ? "Creating…" : "Create university"}</button>}
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </section>
  );
}
