import { useState } from "react";
import { request } from "./api.js";

// How people sign in to this admin page, and changing one's own password.
export default function SignInPage({ call, me }) {
  const [form, setForm] = useState({ current_password: "", new_password: "", repeat: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function save(event) {
    event.preventDefault();
    if (form.new_password !== form.repeat) return setError("The two new passwords are not the same.");
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await call((token) => request("/admin/me/password", { method: "POST", token,
        body: { current_password: form.current_password, new_password: form.new_password } }));
      setNotice("Your password is changed.");
      setForm({ current_password: "", new_password: "", repeat: "" });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  return (
    <>
      <div className="crow"><h3>Sign-in</h3></div>
      <div className="panel">
        <h4>How people sign in</h4>
        <div className="field"><span>Admin page</span><span>Email and password, per user <span className="pill ok">on</span></span></div>
        <div className="field"><span>Single sign-on</span><span>Microsoft Entra or Google <span className="pill">not set up yet</span></span></div>
        <div className="field"><span>Chat</span><span>Students and staff use the chat without signing in; they choose who they are on the start screen.</span></div>
        <p className="note">Add or remove admins and editors on the Users &amp; audiences page.</p>
      </div>
      <form className="panel" onSubmit={save}>
        <h4>Your password</h4>
        <div className="field"><span>Account</span><span className="fval">{me.email}</span></div>
        <label className="field"><span>Current password</span>
          <input className="finput" type="password" value={form.current_password} onChange={set("current_password")} autoComplete="current-password" /></label>
        <label className="field"><span>New password</span>
          <input className="finput" type="password" value={form.new_password} onChange={set("new_password")} autoComplete="new-password" placeholder="at least 10 characters" /></label>
        <label className="field"><span>Again</span>
          <input className="finput" type="password" value={form.repeat} onChange={set("repeat")} autoComplete="new-password" /></label>
        {error && <p className="error">{error}</p>}
        {notice && <p className="notice">{notice}</p>}
        <div><button type="submit" disabled={busy || !form.current_password || form.new_password.length < 10}>Change password</button></div>
      </form>
    </>
  );
}
