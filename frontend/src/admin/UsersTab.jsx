import { useEffect, useState } from "react";
import { createUser, listUsers, updateUser } from "./api.js";

const ROLES = [
  { key: "tenant_admin", title: "Admin", text: "everything: assistants, documents, branding, users" },
  { key: "editor", title: "Editor", text: "documents only" },
];

// The people who can log in to this admin page. Accounts are deactivated, not deleted; the
// university always keeps at least one active admin.
export default function UsersTab({ call, me }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ email: "", name: "", role: "editor", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function reload() {
    try {
      setUsers(await call(listUsers));
    } catch (err) {
      setError(`Could not load the users: ${err.message}`);
    }
  }

  useEffect(() => { reload(); }, []);

  async function run(action, done) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await call(action);
      setNotice(done);
      await reload();
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add(event) {
    event.preventDefault();
    if (await run((token) => createUser(token, form), `Account made for ${form.email}. Give them the password yourself.`)) {
      setForm({ email: "", name: "", role: "editor", password: "" });
    }
  }

  function newPassword(user) {
    const password = window.prompt(`New password for ${user.email} (at least 10 characters):`);
    if (password) run((token) => updateUser(token, user.id, { password }), `New password set for ${user.email}.`);
  }

  return (
    <section className="admin-card">
      <h2>Users</h2>
      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}
      <table className="doc-table">
        <thead><tr><th>Email</th><th>Role</th><th>Last login</th><th /></tr></thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id} className={user.active ? "" : "hidden-row"}>
              <td>{user.name ? <><b>{user.name}</b><div className="hint">{user.email}</div></> : user.email}
                {user.email === me.email && <span className="tag">You</span>}
                {!user.active && <span className="tag">Deactivated</span>}</td>
              <td>
                <select value={user.role} disabled={busy} aria-label={`Role of ${user.email}`}
                        onChange={(e) => run((token) => updateUser(token, user.id, { role: e.target.value }), "Role changed.")}>
                  {ROLES.map((role) => <option key={role.key} value={role.key}>{role.title}</option>)}
                </select>
              </td>
              <td className="hint">{user.last_login_at ? new Date(user.last_login_at).toLocaleString() : "never"}</td>
              <td className="row-actions">
                <button className="secondary" onClick={() => newPassword(user)} disabled={busy}>New password</button>
                <button className={user.active ? "danger" : "secondary"} disabled={busy}
                        onClick={() => run((token) => updateUser(token, user.id, { active: !user.active }),
                                           `${user.email} is ${user.active ? "deactivated" : "active again"}.`)}>
                  {user.active ? "Deactivate" : "Activate"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <form className="add-user" onSubmit={add}>
        <h3>Add a user</h3>
        <div className="form-grid">
          <label>Email<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></label>
          <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label>Role
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {ROLES.map((role) => <option key={role.key} value={role.key}>{role.title}: {role.text}</option>)}
            </select>
          </label>
          <label>Password (at least 10 characters)
            <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
                   autoComplete="new-password" minLength={10} required />
          </label>
        </div>
        <button type="submit" disabled={busy}>Add user</button>
      </form>
    </section>
  );
}
