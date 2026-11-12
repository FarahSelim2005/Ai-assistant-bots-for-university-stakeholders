import { useEffect, useRef, useState } from "react";
import { checkAddress, egp, getPlans, planFeatures, sendNewCode, signupStatus, startSignup, subscribe, verifyCode } from "./api.js";
import "../platform.css";

// /signup: the public sign-up, like the design's signupView(). A university chooses a plan,
// proves its email with a 6-digit code, picks its address, colour, logo and assistants, then
// starts its free trial or pays on the payment page (test mode for now). The form is kept in
// sessionStorage (never the password), so coming back from the payment page continues it.
const STEPS = ["Plan", "Your account", "University", "Address & look", "Assistants", "Subscribe"];
const COLORS = ["#c2410c", "#1f4fa3", "#137a4b", "#0f766e", "#7c3aed", "#be123c", "#334155"];
const KEY = "signup";
const MAX_LOGO_BYTES = 300 * 1024;
const fresh = () => ({ step: 0, plan: "standard", person: "", email: "", uni: "", short: "", slug: "", primary: COLORS[0],
  logo: null, agents: [{ name: "", description: "" }], id: null, sentTo: null, verified: false });

function saved() {
  try { return { ...fresh(), ...JSON.parse(sessionStorage.getItem(KEY)) }; } catch { return fresh(); }
}

const slugFrom = (text) => text.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 30);

export default function SignupPage() {
  const [form, setForm] = useState(saved);
  const [password, setPassword] = useState("");
  const [catalog, setCatalog] = useState({ plans: [], templates: [] });
  const [code, setCode] = useState("");
  const [address, setAddress] = useState(null); // {available, problem} for form.slug
  const [status, setStatus] = useState(null);   // the finished sign-up (done or waiting for review)
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const firstNew = useRef(null);
  const set = (changes) => setForm((f) => ({ ...f, ...changes }));
  const plan = catalog.plans.find((p) => p.key === form.plan) || catalog.plans[0];
  const named = form.agents.filter((a) => a.name.trim());
  const domain = (form.email.split("@")[1] || "").toLowerCase();

  useEffect(() => { document.title = "Sign up · UniBots"; }, []);
  useEffect(() => { getPlans().then(setCatalog).catch((e) => setError(e.message)); }, []);
  useEffect(() => { try { sessionStorage.setItem(KEY, JSON.stringify(form)); } catch { /* storage blocked: kept in memory */ } }, [form]);

  // Back from the payment page (/signup?id=...): where is the sign-up now?
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id") || (form.step === 6 ? form.id : null);
    if (!id) return;
    signupStatus(id).then((s) => {
      if (s.state === "done" || s.state === "review") { setStatus(s); set({ id, step: 6 }); }
      else if (s.state === "payment_failed") { set({ id, step: 5, verified: true }); setError("The payment did not go through. Nothing was charged. You can try again."); }
      else if (s.state === "checkout") set({ id, step: 5, verified: true });
      else if (s.state === "error") { set({ id, step: 5 }); setError(s.error || "Your payment was received but the university could not be made. Please contact us."); }
    }).catch((e) => setError(e.message));
  }, []);

  // Is the address free? (checked shortly after typing stops)
  useEffect(() => {
    if (form.step !== 3 || form.slug.length < 2) { setAddress(null); return undefined; }
    const timer = setTimeout(() => checkAddress(form.slug).then(setAddress).catch(() => setAddress(null)), 350);
    return () => clearTimeout(timer);
  }, [form.slug, form.step]);

  function go(step) { setError(""); setNote(""); set({ step }); window.scrollTo(0, 0); }

  async function run(action) {
    setBusy(true); setError(""); setNote("");
    try { await action(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  async function next() {
    const step = form.step;
    if (step === 0) return go(1);
    if (step === 1) {
      if (!form.person.trim()) return setError("Enter your name.");
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email)) return setError("Enter your university email address.");
      if (form.id && form.sentTo === form.email.trim().toLowerCase() && !password) return go(2); // already sent
      if (password.length < 10) return setError("Choose a password of at least 10 characters.");
      return run(async () => {
        const made = await startSignup({ plan: form.plan, person: form.person, email: form.email, password });
        set({ id: made.id, sentTo: made.email, verified: false, step: 2 });
        setCode("");
      });
    }
    if (step === 2) {
      if (!form.uni.trim()) return setError("Enter the university's name.");
      if (!form.short.trim()) return setError("Enter a short name, for example CTU.");
      if (!form.verified) return setError("Enter the 6-digit code we emailed you.");
      if (!form.slug) set({ slug: slugFrom(form.short) });
      return go(3);
    }
    if (step === 3) {
      if (form.slug.length < 2) return setError("Choose an address of at least 2 letters.");
      return run(async () => {
        const check = await checkAddress(form.slug);
        if (!check.available) throw new Error(check.problem);
        go(4);
      });
    }
    if (step === 4) {
      if (!named.length) return setError("Add at least one assistant.");
      if (plan?.max_assistants && named.length > plan.max_assistants) {
        return setError(`The ${plan.name} plan allows ${plan.max_assistants} assistants. Remove some or choose a bigger plan.`);
      }
      return go(5);
    }
    if (step === 5) {
      return run(async () => {
        const result = await subscribe(form.id, {
          plan: form.plan, university: form.uni, short_name: form.short, slug: form.slug, brand_primary: form.primary,
          logo_url: form.logo, assistants: named.map((a) => ({ name: a.name.trim(), description: a.description.trim(), template_key: a.template_key || null })),
        });
        if (result.done) {
          setStatus(await signupStatus(form.id));
          go(6);
        } else {
          window.location.href = result.checkout_url; // the payment page
        }
      });
    }
    return undefined;
  }

  function verify() {
    if (!/^\d{6}$/.test(code.trim())) return setError("Enter the 6 digits from the email.");
    return run(async () => { await verifyCode(form.id, code.trim()); set({ verified: true }); });
  }

  function resend() {
    return run(async () => { await sendNewCode(form.id); setNote(`A new code was sent to ${form.sentTo}.`); });
  }

  function chooseLogo(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > MAX_LOGO_BYTES) { setError("The logo must be smaller than 300 KB."); return; }
    const reader = new FileReader();
    reader.onload = () => set({ logo: reader.result });
    reader.readAsDataURL(file);
  }

  function setAgent(index, changes) {
    set({ agents: form.agents.map((a, i) => (i === index ? { ...a, ...changes } : a)) });
  }

  function addAgent(agent = { name: "", description: "" }) {
    const empty = form.agents.findIndex((a) => !a.name.trim() && !a.description.trim());
    const agents = empty >= 0 && agent.name ? form.agents.map((a, i) => (i === empty ? agent : a)) : [...form.agents, agent];
    set({ agents });
    if (!agent.name) setTimeout(() => firstNew.current?.focus(), 0);
  }

  function restart() {
    setForm(fresh()); setStatus(null); setPassword(""); setCode(""); setError(""); setNote("");
    window.history.replaceState(null, "", "/signup");
  }

  const done = form.step === 6 && status;
  let body;
  if (done) {
    body = status.state === "review" ? (
      <div className="done-box">
        <h3>Thank you. {form.short || status.university} is waiting for approval</h3>
        <p>We check every new university before it goes live, usually within a working day. Once it is approved, log in at{" "}
          <code>{status.admin_url}</code> with <b>{status.email}</b> and your password.</p>
      </div>
    ) : (
      <div className="done-box">
        <h3>{form.short || status.university}'s chatbot is ready</h3>
        <p>It's live at <code>{status.host}</code> with {status.assistants} assistant{status.assistants === 1 ? "" : "s"}. Next:</p>
        <ol>
          <li>Upload documents for each assistant on the admin page. Assistants answer only from them.</li>
          <li>Invite colleagues as editors.</li>
          <li>Share the link with students and staff, or add it to your university portal.</li>
        </ol>
        <div className="crow" style={{ justifyContent: "flex-start" }}>
          <a className="btnlink" href={status.login_url || status.admin_url}>Open admin</a>
          <a className="btnlink ghost" href={status.url}>Open the chat</a>
          <button type="button" className="ghost" onClick={restart}>Start another sign-up</button>
        </div>
      </div>
    );
  } else if (form.step === 0) {
    body = (
      <>
        <div className="sform" style={{ maxWidth: "none" }}>
          <h3>Give your university its own AI assistants</h3>
          <p className="note">Students and staff get answers from your own documents, in English and Arabic. Choose a plan. You can change it later.</p>
        </div>
        <div className="plans">
          {catalog.plans.map((p) => (
            <button key={p.key} type="button" className="plan" aria-pressed={form.plan === p.key} onClick={() => set({ plan: p.key })}>
              <span className="pname">{p.name}{p.key === "standard" && <span className="pill acc">Most chosen</span>}</span>
              <span className="price">{p.price_egp ? egp(p.price_egp) : "Free"} <small>{p.trial_days ? `for ${p.trial_days} days` : "/ month"}</small></span>
              {p.description && <span className="note">{p.description}</span>}
              <ul>{planFeatures(p).map((f) => <li key={f}>{f}</li>)}</ul>
            </button>
          ))}
        </div>
      </>
    );
  } else if (form.step === 1) {
    body = (
      <div className="sform">
        <h3>Create your account</h3>
        <p className="note">You become the first admin of your university's chatbot. You can invite colleagues later.</p>
        <label className="field"><span>Your name</span>
          <input className="finput" value={form.person} onChange={(e) => set({ person: e.target.value })} autoComplete="name" placeholder="Mona Hassan" /></label>
        <label className="field"><span>University email</span>
          <input className="finput" type="email" value={form.email} onChange={(e) => set({ email: e.target.value, verified: false })}
                 autoComplete="email" placeholder="m.hassan@your-university.edu.eg" /></label>
        <label className="field"><span>Password</span>
          <input className="finput" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password"
                 placeholder={form.id && form.sentTo === form.email.trim().toLowerCase() ? "(already set)" : "At least 10 characters"} /></label>
      </div>
    );
  } else if (form.step === 2) {
    body = (
      <div className="sform">
        <h3>Your university</h3>
        <label className="field"><span>Full name</span>
          <input className="finput" value={form.uni} onChange={(e) => set({ uni: e.target.value })} placeholder="Cairo Tech University" /></label>
        <label className="field"><span>Short name</span>
          <input className="finput" value={form.short} maxLength={12} onChange={(e) => set({ short: e.target.value })} placeholder="CTU" /></label>
        <div className="field"><span>Email domain</span><span className="fval">{domain || "—"}</span></div>
        <div className="panel">
          <h4>Prove you work there</h4>
          <p className="note">So nobody can open a chatbot in another university's name, we emailed a 6-digit code to {form.sentTo}.
            Only addresses on <b>@{domain}</b> can sign in as this university's staff.</p>
          <div className="crow" style={{ justifyContent: "flex-start" }}>
            {form.verified ? <span className="okline">✓ Email confirmed</span> : (
              <>
                <input className="finput codeinput" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                       inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" aria-label="Verification code"
                       onKeyDown={(e) => { if (e.key === "Enter") verify(); }} />
                <button type="button" className="ghost" onClick={verify} disabled={busy}>Confirm code</button>
                <button type="button" className="link" onClick={resend} disabled={busy}>Send a new code</button>
              </>
            )}
          </div>
        </div>
      </div>
    );
  } else if (form.step === 3) {
    body = (
      <div className="sform">
        <h3>Address and look</h3>
        <label className="field"><span>Address</span>
          <span style={{ display: "flex", gap: 6, alignItems: "center", minWidth: 0 }}>
            <input className="finput" value={form.slug} onChange={(e) => set({ slug: slugFrom(e.target.value) })} aria-label="Address" />
            <span className="mono" style={{ whiteSpace: "nowrap" }}>.localhost</span>
          </span></label>
        {address && <div className="field"><span /><span className={address.available ? "okline" : "err"}>
          {address.available ? `✓ ${form.slug}.localhost is free` : address.problem}</span></div>}
        <div className="field"><span>Main colour</span>
          <span className="colors">
            {COLORS.map((c) => <button key={c} type="button" className="colorbtn" aria-pressed={form.primary === c} aria-label={`Colour ${c}`}
                                       style={{ background: c }} onClick={() => set({ primary: c })} />)}
            <input type="color" value={form.primary} onChange={(e) => set({ primary: e.target.value })} aria-label="Another colour" />
          </span></div>
        <div className="field"><span>Logo</span>
          <span className="colors">
            <label className="btnlink ghost" style={{ cursor: "pointer" }}>Upload PNG or SVG
              <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" hidden onChange={chooseLogo} /></label>
            {form.logo ? <button type="button" className="link" onClick={() => set({ logo: null })}>Remove</button>
              : <span className="note">Optional: the short name is used until then.</span>}
          </span></div>
        <div className="field"><span>Preview</span>
          <div className="mini" style={{ "--su-primary": form.primary }}>
            <div className="ms">{form.logo ? <img src={form.logo} alt="" /> : <b>{form.short}</b>}
              {named.slice(0, 4).map((a, i) => <i key={i}>{a.name}</i>)}</div>
            <div className="mm"><span className="b">When is the deadline?</span><span className="a">Applications close on 15 August…</span></div>
          </div></div>
      </div>
    );
  } else if (form.step === 4) {
    const limit = plan?.max_assistants;
    body = (
      <div className="sform wide">
        <h3>Your assistants</h3>
        <p className="note">Create as many as your plan allows and name them however you like. {named.length} of {limit || "unlimited"} used.
          You add their documents after sign-up.</p>
        {form.agents.map((a, i) => (
          <div className="suagent" key={i}>
            <input className="finput" ref={i === form.agents.length - 1 ? firstNew : null} value={a.name} placeholder="Name, e.g. Ask Admissions"
                   aria-label={`Assistant ${i + 1} name`} onChange={(e) => setAgent(i, { name: e.target.value })} />
            <input className="finput" value={a.description} placeholder="What it handles" aria-label={`Assistant ${i + 1} topics`}
                   onChange={(e) => setAgent(i, { description: e.target.value })} />
            <button type="button" className="ghost" aria-label={`Remove assistant ${i + 1}`}
                    onClick={() => set({ agents: form.agents.filter((_, j) => j !== i) })}>✕</button>
          </div>
        ))}
        <div className="crow" style={{ justifyContent: "flex-start" }}>
          <button type="button" className="ghost" onClick={() => addAgent()} disabled={Boolean(limit) && form.agents.length >= limit}>＋ Add assistant</button>
        </div>
        <div className="field"><span>Or start from</span>
          <span className="opts">
            {catalog.templates.map((t) => (
              <button key={t.key} type="button" className="opt" title={t.summary}
                      onClick={() => addAgent({ name: t.name, description: t.summary, template_key: t.key })}>＋ {t.name}</button>
            ))}
          </span></div>
      </div>
    );
  } else if (form.step === 5 && plan) {
    body = (
      <div className="sform">
        <h3>{plan.trial_days ? "Start your free trial" : "Subscribe"}</h3>
        <div className="tablewrap"><table className="sumtable"><tbody>
          <tr><td>University</td><td>{form.uni} ({form.short})</td></tr>
          <tr><td>Address</td><td><code>{form.slug}.localhost</code></td></tr>
          <tr><td>Assistants</td><td>{named.map((a) => a.name).join(", ")}</td></tr>
          <tr><td>Plan</td><td>{plan.name} · {plan.price_egp ? `${egp(plan.price_egp)} / month` : `free for ${plan.trial_days} days`}</td></tr>
          <tr><td>Includes</td><td>{planFeatures(plan).slice(0, 2).join(" · ")}</td></tr>
        </tbody></table></div>
        <p className="note">{plan.trial_days
          ? `No card needed. After ${plan.trial_days} days the chatbot pauses until you choose a plan. Nothing is deleted.`
          : "You pay on the secure payment page. The subscription renews monthly and you can cancel any time from the admin page."}</p>
      </div>
    );
  }

  return (
    <div className="pf">
      <div className="signup">
        <div className="stopbar">
          <span className="brandp"><span className="blogo">UB</span>UniBots · AI assistants for universities</span>
          <span className="note">Already a customer? Log in on your university's admin page.</span>
        </div>
        <div className="sbody">
          {!done && (
            <div className="steps">
              {STEPS.map((name, i) => (
                <button key={name} type="button" className={`stp ${i === form.step ? "on" : i < form.step ? "done" : ""}`}
                        disabled={i >= form.step} onClick={() => go(i)}>{i + 1}. {name}</button>
              ))}
            </div>
          )}
          {body}
          {!done && (
            <div className="crow" style={{ justifyContent: "flex-start" }}>
              {form.step > 0 && <button type="button" className="ghost" onClick={() => go(form.step - 1)} disabled={busy}>← Back</button>}
              <button type="button" onClick={next} disabled={busy || !plan}>
                {busy ? "Please wait…" : form.step === 5 ? (plan?.trial_days ? "Start free trial" : "Go to payment")
                  : form.step === 0 ? `Choose ${plan?.name ?? "a plan"}` : "Next →"}
              </button>
            </div>
          )}
          {note && <p className="okline">{note}</p>}
          {error && <p className="err" role="alert">{error}</p>}
          {form.step === 6 && !status && !error && <p className="note">Loading…</p>}
        </div>
      </div>
    </div>
  );
}
