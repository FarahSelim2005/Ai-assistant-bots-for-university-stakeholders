import { useEffect, useState } from "react";
import { getBranding, updateBranding } from "./api.js";
import UsersTab from "./UsersTab.jsx";

// Users & audiences: who can log in to this admin page, and who the assistants are for
// (the start screen's "Who are you?" choices).
export default function UsersPage({ call, me }) {
  return (
    <>
      <div className="crow"><h3>Users &amp; audiences</h3></div>
      <UsersTab call={call} me={me} />
      <Audiences call={call} />
    </>
  );
}

function Audiences({ call }) {
  const [audiences, setAudiences] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => { call(getBranding).then((b) => setAudiences(b.audiences)).catch((err) => setError(err.message)); }, []);
  if (!audiences) return error ? <p className="error">{error}</p> : null;

  const change = (index, key, value) => setAudiences((list) => list.map((a, i) => (i === index ? { ...a, [key]: value } : a)));

  async function save() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await call((token) => updateBranding(token, {
        audiences: audiences.map((a) => ({ key: a.key.trim(), title: a.title.trim(), text: (a.text || "").trim() })) }));
      setNotice("Saved. The start screen shows them when it is opened again.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h4>Audiences</h4>
      <p className="note">Who the assistants are for: the cards under “Who are you?” on the start screen. Each assistant is for some of them.
        The key is used inside the system: keep it once assistants use it.</p>
      {audiences.map((audience, index) => (
        <div className="wizrow" key={index}>
          <input className="finput" aria-label="Key" value={audience.key} onChange={(e) => change(index, "key", e.target.value.toLowerCase())}
                 placeholder="key, e.g. applicant" maxLength={30} />
          <span className="opts" style={{ flexWrap: "nowrap" }}>
            <input className="finput" aria-label="Title" value={audience.title} onChange={(e) => change(index, "title", e.target.value)}
                   placeholder="Title, e.g. Applicant" maxLength={40} />
            <input className="finput" aria-label="Text" value={audience.text || ""} onChange={(e) => change(index, "text", e.target.value)}
                   placeholder="Text under the title (optional)" maxLength={160} />
          </span>
          <button type="button" className="ghost" disabled={audiences.length === 1}
                  onClick={() => setAudiences((list) => list.filter((_, i) => i !== index))}>Remove</button>
        </div>
      ))}
      <div className="crow">
        <button type="button" className="ghost" disabled={audiences.length >= 6}
                onClick={() => setAudiences((list) => [...list, { key: "", title: "", text: "" }])}>＋ Add audience</button>
        <button type="button" onClick={save} disabled={busy}>Save audiences</button>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
    </div>
  );
}
