import { useEffect, useState } from "react";
import { getBranding, updateBranding } from "./api.js";

const MAX_LOGO_KB = 300;

// The university's look: name, short name, logo, colours and start screen text (audiences are
// on the Users & audiences page). Saved changes show for users when they open the page again.
export default function BrandingTab({ call }) {
  const [values, setValues] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    call(getBranding).then(setValues).catch((err) => setError(`Could not load the branding: ${err.message}`));
  }, []);

  if (!values) return <section className="admin-card">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</section>;

  const set = (key) => (event) => setValues((v) => ({ ...v, [key]: event.target.value }));

  function pickLogo(event) {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    if (!/^image\/(png|jpeg|webp|svg\+xml)$/.test(file.type)) return setError("Pick a PNG, JPEG, WebP or SVG picture.");
    if (file.size > MAX_LOGO_KB * 1024) return setError(`The logo must be smaller than ${MAX_LOGO_KB} KB.`);
    const reader = new FileReader();
    reader.onload = () => { setValues((v) => ({ ...v, logo_url: reader.result })); setError(""); };
    reader.readAsDataURL(file);
  }

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const { audiences, ...look } = values; // audiences are saved on the Users & audiences page
      await call((token) => updateBranding(token, look));
      setNotice("Saved. Users see the new look when they open the page again.");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="admin-card" onSubmit={save}>
      <h2>Branding</h2>
      <p className="hint">How the chat looks for {values.name}'s students and staff. The admin pages keep the platform's colours.</p>
      <div className="form-grid">
        <label>Name<input value={values.name} onChange={set("name")} required maxLength={120} /></label>
        <label>Short name (in texts, e.g. "GIU")<input value={values.short_name} onChange={set("short_name")} maxLength={30} /></label>
      </div>

      <fieldset>
        <legend>Logo</legend>
        <div className="logo-row">
          {values.logo_url
            ? <img src={values.logo_url} alt="Logo" className="logo-preview" />
            : <span className="text-logo logo-preview">{values.short_name || values.name}</span>}
          <label className="file-pick">
            <span className="button-like secondary">Choose a picture</span>
            <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={pickLogo} hidden />
          </label>
          {values.logo_url && <button type="button" className="secondary" onClick={() => setValues((v) => ({ ...v, logo_url: "" }))}>No logo</button>}
        </div>
        <p className="hint">Without a logo, the short name is shown on the main colour.</p>
      </fieldset>

      <fieldset>
        <legend>Colours</legend>
        <div className="colour-row">
          {[["brand_primary", "Main (buttons)"], ["brand_accent", "Accent"], ["brand_dark", "Dark (header)"]].map(([key, title]) => (
            <label key={key} className="colour">
              {title}
              <input type="color" value={values[key]} onChange={set(key)} />
              <code>{values[key]}</code>
            </label>
          ))}
        </div>
      </fieldset>

      <label>
        Start screen text
        <span className="hint">Empty: a short text is made from the assistants. "{"{university}"}" becomes the short name.</span>
        <textarea rows={3} value={values.intro} onChange={set("intro")} maxLength={600} dir="auto" />
      </label>


      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}
      <div className="form-actions"><button type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</button></div>
    </form>
  );
}
