import { useEffect, useRef, useState } from "react";
import { checkAddress, egp, getPlans, planFeatures, sendNewCode, signupStatus, startSignup, subscribe, verifyCode } from "./api.js";
import "../platform.css";
import "./signup.css";

// /signup: the public website and sign-up (the design's signupView()). Step 0 is the website
// (hero, features, how it works, pricing, FAQ); choosing a plan opens the form beside a live
// preview of the university's chat. A university chooses a plan,
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
  const trialPlan = catalog.plans.find((p) => p.trial_days);

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
        set({ id: made.id, sentTo: made.email, codeInLog: Boolean(made.code_in_log), verified: false, step: 2 });
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
    return run(async () => {
      const sent = await sendNewCode(form.id);
      setNote(sent.code_in_log ? "A new code is in the backend's log. The earlier code no longer works."
        : `A new code was sent to ${form.sentTo}. The earlier code no longer works.`);
    });
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

  function choose(key) {
    set({ plan: key });
    go(1);
  }

  const scrollTo = (id) => (event) => { event.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth" }); };
  const price = (p) => (p.price_egp ? <><span className="cur">EGP</span>{p.price_egp.toLocaleString("en")} <small>/ month</small></> : <>Free <small>for {p.trial_days} days</small></>);

  // ---------------------------------------------------------------- the website (step 0)
  if (form.step === 0) {
    return (
      <div className="pf"><div className="site">
        <nav className="site-nav"><div className="wrap">
          <button type="button" className="logo" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}><span className="logo-mark">UB</span>UniBots</button>
          <div className="nav-links">
            <a href="#features" onClick={scrollTo("features")}>Features</a>
            <a href="#how" onClick={scrollTo("how")}>How it works</a>
            <a href="#pricing" onClick={scrollTo("pricing")}>Pricing</a>
            <a href="#faq" onClick={scrollTo("faq")}>FAQ</a>
            <button type="button" className="btn-sm" onClick={() => choose(trialPlan?.key || form.plan)}>Start free trial</button>
          </div>
        </div></nav>

        <header className="hero"><div className="wrap">
          <div>
            <span className="eyebrow"><b>New</b> AI assistants for every office of your university</span>
            <h1>Answers for your students and staff, <em>from your own documents</em>.</h1>
            <p className="lead">Admissions, advising, internships, HR, labs: give each office its own assistant that answers in English and Arabic,
              around the clock, using only the documents you upload.</p>
            <div className="hero-cta">
              <button type="button" className="btn-lg" onClick={() => choose(trialPlan?.key || form.plan)}>Start your free trial <Arrow /></button>
              <a className="btn-ghost btn-lg" href="#pricing" onClick={scrollTo("pricing")}>See plans and prices</a>
            </div>
            <div className="trust">
              <span><Check /> {trialPlan ? `${trialPlan.trial_days}-day free trial` : "Free trial"}</span>
              <span><Check /> No card needed</span>
              <span><Check /> Live in 5 minutes</span>
            </div>
          </div>
          <ChatMock colour="#c2410c" short="CTU" assistants={["Ask Admissions", "Student Help Desk", "Career Office", "Labs & Rooms"]} />
        </div></header>

        <section className="section alt" id="features"><div className="wrap">
          <div className="section-head"><span className="kicker">Why universities choose it</span>
            <h2>Everything a university assistant needs</h2>
            <p>Built for universities: your offices, your documents, your name and colours.</p></div>
          <div className="features">
            <Feature icon={<IconDoc />} title="Answers from your documents">It answers only from the files you upload, and shows which document each answer comes from. No made-up rules.</Feature>
            <Feature icon={<IconGlobe />} title="English and Arabic">Students ask in either language and get answers in the same one, also in Egyptian Arabic typed in Latin letters.</Feature>
            <Feature icon={<IconUsers />} title="One assistant per office">Admissions, advising, careers, HR: each office runs its own assistant, for students, staff or both.</Feature>
            <Feature icon={<IconPalette />} title="Your university's look">Your own address, logo and colours. Students see your university, not ours.</Feature>
          </div>
        </div></section>

        <section className="section" id="how"><div className="wrap">
          <div className="section-head"><span className="kicker">How it works</span><h2>Live in three steps</h2>
            <p>No IT project, no installation. Sign up, upload, share the link.</p></div>
          <div className="howto">
            <div className="how"><h3>Create your chatbot</h3><p>Choose a plan, confirm your university email and pick your address, colours and assistants.</p></div>
            <div className="how"><h3>Upload your documents</h3><p>Add handbooks, regulations and FAQs on your admin page. Each assistant learns from its own folder at once.</p></div>
            <div className="how"><h3>Share the link</h3><p>Put it on your portal or send it to students and staff. See questions, ratings and unanswered topics on your admin page.</p></div>
          </div>
        </div></section>

        <section className="section alt" id="pricing"><div className="wrap">
          <div className="section-head"><span className="kicker">Pricing</span><h2>Simple monthly plans</h2>
            <p>Start free, then choose the plan that fits. Change or cancel any time from your admin page.</p></div>
          <div className="pricing">
            {catalog.plans.map((p) => {
              const featured = p.key === "standard";
              return (
                <div key={p.key} className={`price-card ${featured ? "featured" : ""}`}>
                  {featured && <span className="ribbon">Most chosen</span>}
                  <h3>{p.name}</h3>
                  <div className="amount">{price(p)}</div>
                  <p className="desc">{p.description}</p>
                  <ul className="checks">{planFeatures(p).map((f) => <li key={f}><Check />{f}</li>)}</ul>
                  <button type="button" className={`btn-lg ${featured ? "" : "ghost"}`} onClick={() => choose(p.key)}>
                    {p.trial_days ? "Start free trial" : `Choose ${p.name}`}</button>
                </div>
              );
            })}
          </div>
          {!catalog.plans.length && !error && <p className="price-note">Loading plans…</p>}
          <p className="price-note">Prices in Egyptian pounds, per month. Payment is in test mode for now: no card is charged.</p>
          {error && <p className="form-error" role="alert">{error}</p>}
        </div></section>

        <section className="section" id="faq"><div className="wrap">
          <div className="section-head"><span className="kicker">Questions</span><h2>Frequently asked</h2></div>
          <div className="faq">
            <details><summary>Who can sign up?</summary><p>Staff of a university, with their university email address. We send a 6-digit code to prove it,
              so nobody can open a chatbot in another university's name. Personal addresses such as Gmail are not accepted.</p></details>
            <details><summary>What happens when the free trial ends?</summary><p>The chat pauses until you choose a plan. Your assistants and documents
              are kept, and everything works again as soon as you subscribe.</p></details>
            <details><summary>Does it make things up?</summary><p>Assistants answer from your documents only. When nothing matches, they say they
              don't know and point to the right office, instead of guessing.</p></details>
            <details><summary>Can we use our own address and logo?</summary><p>Yes. You choose your address, colour and logo during sign-up and can change
              them later on your admin page.</p></details>
            <details><summary>What if a payment fails?</summary><p>The chat keeps working for 7 days while you update your payment. After that it pauses;
              nothing is deleted.</p></details>
          </div>
        </div></section>

        <section className="section" style={{ paddingTop: 0 }}><div className="wrap">
          <div className="cta-band">
            <div><h2>Ready to help your students faster?</h2><p>Set up your university's assistants in a few minutes.</p></div>
            <button type="button" className="btn-lg" onClick={() => choose(trialPlan?.key || form.plan)}>Start your free trial <Arrow /></button>
          </div>
        </div></section>

        <footer className="site-foot"><div className="wrap">
          <span>© {new Date().getFullYear()} UniBots · AI assistants for universities</span>
          <span>Already a customer? Log in on your university's admin page.</span>
        </div></footer>
      </div></div>
    );
  }

  // ---------------------------------------------------------------- finished
  const done = form.step === 6 && status;
  const nav = (
    <nav className="site-nav"><div className="wrap">
      <button type="button" className="logo" onClick={() => go(0)}><span className="logo-mark">UB</span>UniBots</button>
      <div className="nav-links"><span className="pill warn">test mode · no real payments</span></div>
    </div></nav>
  );
  if (form.step === 6) {
    return (
      <div className="pf"><div className="site">{nav}
        <div className="done-wrap"><div className="wrap">
          {!done ? <p className="note" style={{ textAlign: "center" }}>{error || "Loading…"}</p> : (
            <div className="done-card">
              <span className="big-check"><Check size={32} /></span>
              {status.state === "review" ? (
                <>
                  <h2>Thank you! {form.short || status.university} is waiting for approval</h2>
                  <p>We check every new university before it goes live, usually within a working day. Once it is approved, log in at{" "}
                    <code>{status.admin_url}</code> with <b>{status.email}</b> and your password.</p>
                </>
              ) : (
                <>
                  <h2>{form.short || status.university}'s chatbot is ready</h2>
                  <p>It's live at <code>{status.host}</code> with {status.assistants} assistant{status.assistants === 1 ? "" : "s"}. Next:</p>
                  <ol>
                    <li>Upload documents for each assistant on the admin page. Assistants answer only from them.</li>
                    <li>Invite colleagues as editors.</li>
                    <li>Share the link with students and staff, or add it to your university portal.</li>
                  </ol>
                  <div className="done-actions">
                    <a className="btn btn-lg" href={status.login_url || status.admin_url}>Open admin <Arrow /></a>
                    <a className="btn-ghost btn-lg" href={status.url}>Open the chat</a>
                  </div>
                </>
              )}
              <button type="button" className="link" onClick={restart}>Start another sign-up</button>
            </div>
          )}
        </div></div>
      </div></div>
    );
  }

  // ---------------------------------------------------------------- the form (steps 1-5)
  const titles = {
    1: ["Create your account", "You become the first admin of your university's chatbot. You can invite colleagues later."],
    2: ["Your university", "Tell us its name, and confirm your email address."],
    3: ["Address and look", "Where students find the chat, and how it looks."],
    4: ["Your assistants", `One per office or topic, with any names. ${named.length} of ${plan?.max_assistants || "unlimited"} on the ${plan?.name ?? ""} plan. You add their documents after sign-up.`],
    5: [plan?.trial_days ? "Start your free trial" : "Review and subscribe", "Check everything before you continue."],
  }[form.step];
  let body = null;
  if (form.step === 1) {
    body = (
      <div className="sgrid">
        <label className="sfield full">Your name
          <input className="sinput" value={form.person} onChange={(e) => set({ person: e.target.value })} autoComplete="name" placeholder="Mona Hassan" autoFocus /></label>
        <label className="sfield full">University email <small>Your work address at the university. Personal addresses such as Gmail are not accepted.</small>
          <input className="sinput" type="email" value={form.email} onChange={(e) => set({ email: e.target.value, verified: false })}
                 autoComplete="email" placeholder="m.hassan@your-university.edu.eg" /></label>
        <label className="sfield full">Password
          <input className="sinput" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password"
                 placeholder={form.id && form.sentTo === form.email.trim().toLowerCase() ? "(already set)" : "At least 10 characters"} /></label>
      </div>
    );
  } else if (form.step === 2) {
    body = (
      <>
        <div className="sgrid">
          <label className="sfield">Full name of the university
            <input className="sinput" value={form.uni} onChange={(e) => set({ uni: e.target.value })} placeholder="Cairo Tech University" autoFocus /></label>
          <label className="sfield">Short name <small>Shown in the chat, for example CTU</small>
            <input className="sinput" value={form.short} maxLength={12} onChange={(e) => set({ short: e.target.value })} placeholder="CTU" /></label>
        </div>
        <div className="verify-box">
          <h3><IconMail /> Confirm your email</h3>
          <p>We sent a 6-digit code to <b>{form.sentTo}</b>. It proves you work at <b>@{domain}</b>, so nobody can open a chatbot in another university's name.</p>
          {form.codeInLog && <p className="form-note" style={{ color: "var(--warn)", background: "var(--warn-soft)" }}>
            Development: no email server is set up (SMTP_HOST in backend/.env), so the code is not emailed. It is printed in the
            backend's terminal, in a line like "Your sign-up code: 123456".</p>}
          {form.verified ? <span className="verified"><Check /> Email confirmed</span> : (
            <div className="verify-row">
              <input className="sinput code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                     inputMode="numeric" autoComplete="one-time-code" placeholder="••••••" aria-label="Verification code"
                     onKeyDown={(e) => { if (e.key === "Enter") verify(); }} />
              <button type="button" className="btn-lg" onClick={verify} disabled={busy}>Confirm</button>
              <button type="button" className="link" onClick={resend} disabled={busy}>Send a new code</button>
            </div>
          )}
        </div>
      </>
    );
  } else if (form.step === 3) {
    body = (
      <>
        <label className="sfield">Address
          <span className="addr"><input className="sinput" value={form.slug} onChange={(e) => set({ slug: slugFrom(e.target.value) })} aria-label="Address" autoFocus />
            <span>.localhost</span></span>
          {address && <small style={{ color: address.available ? "var(--ok)" : "var(--crit)", fontWeight: 600 }}>
            {address.available ? `✓ ${form.slug}.localhost is free` : address.problem}</small>}
        </label>
        <div className="sfield">Main colour <small>Used for the buttons, the questions and the chosen assistant</small>
          <span className="swatches">
            {COLORS.map((c) => <button key={c} type="button" className="swatch" aria-pressed={form.primary === c} aria-label={`Colour ${c}`}
                                       style={{ background: c }} onClick={() => set({ primary: c })} />)}
            <input type="color" value={form.primary} onChange={(e) => set({ primary: e.target.value })} aria-label="Another colour" title="Another colour" />
          </span></div>
        <div className="sfield">Logo <small>Optional. PNG, JPEG, WebP or SVG, up to 300 KB. Until then the short name is shown.</small>
          <span className="upload">
            <label><IconUpload /> {form.logo ? "Change logo" : "Upload logo"}
              <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" hidden onChange={chooseLogo} /></label>
            {form.logo && <><img src={form.logo} alt="Your logo" /><button type="button" className="link" onClick={() => set({ logo: null })}>Remove</button></>}
          </span></div>
      </>
    );
  } else if (form.step === 4) {
    const limit = plan?.max_assistants;
    body = (
      <>
        {form.agents.map((a, i) => (
          <div className="agent-row" key={i}>
            <span className="num">{i + 1}</span>
            <input className="sinput" ref={i === form.agents.length - 1 ? firstNew : null} value={a.name} placeholder="Name, e.g. Ask Admissions"
                   aria-label={`Assistant ${i + 1} name`} onChange={(e) => setAgent(i, { name: e.target.value })} />
            <input className="sinput" value={a.description} placeholder="What it handles" aria-label={`Assistant ${i + 1} topics`}
                   onChange={(e) => setAgent(i, { description: e.target.value })} />
            <button type="button" className="icon-x" aria-label={`Remove assistant ${i + 1}`}
                    onClick={() => set({ agents: form.agents.filter((_, j) => j !== i) })}>✕</button>
          </div>
        ))}
        <div><button type="button" className="ghost" onClick={() => addAgent()} disabled={Boolean(limit) && form.agents.length >= limit}>＋ Add assistant</button></div>
        <div className="sfield">Or start from a ready-made one <small>Its instructions and examples are filled in; rename it as you like.</small>
          <span className="chipset">
            {catalog.templates.map((t) => (
              <button key={t.key} type="button" className="chip" title={t.summary}
                      onClick={() => addAgent({ name: t.name, description: t.summary, template_key: t.key })}>＋ {t.name}</button>
            ))}
          </span></div>
      </>
    );
  } else if (form.step === 5 && plan) {
    body = (
      <>
        <dl className="summary">
          <div><dt>University</dt><dd>{form.uni} ({form.short})</dd></div>
          <div><dt>Address</dt><dd><code>{form.slug}.localhost</code></dd></div>
          <div><dt>Admin</dt><dd>{form.person} · {form.sentTo}</dd></div>
          <div><dt>Assistants</dt><dd>{named.map((a) => a.name).join(", ")}</dd></div>
          <div><dt>Plan</dt><dd>{plan.name} · {planFeatures(plan).slice(0, 2).join(" · ")}</dd></div>
          <div className="total"><dt>{plan.trial_days ? "Today" : "Monthly"}</dt><dd>{plan.price_egp ? egp(plan.price_egp) : `Free for ${plan.trial_days} days`}</dd></div>
        </dl>
        <p className="note">{plan.trial_days
          ? `No card needed. After ${plan.trial_days} days the chatbot pauses until you choose a plan. Nothing is deleted.`
          : "You pay on the secure payment page. The subscription renews monthly and you can cancel any time from the admin page."}</p>
      </>
    );
  }

  return (
    <div className="pf"><div className="site">{nav}
      <div className="wiz"><div className="wrap">
        <div className="progress">
          <div className="progress-steps">
            {STEPS.slice(1).map((name, i) => {
              const step = i + 1;
              return (
                <button key={name} type="button" className={`pstep ${step === form.step ? "on" : step < form.step ? "done" : ""}`}
                        disabled={step >= form.step} onClick={() => go(step)}><i />{step}. {name}</button>
              );
            })}
          </div>
          <div className="progress-mobile">Step {form.step} of 5 · {STEPS[form.step]}</div>
        </div>
        <main className="wiz-card">
          <header><h2>{titles[0]}</h2><p>{titles[1]}</p></header>
          {body}
          {note && <p className="form-note">{note}</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="wiz-actions">
            <button type="button" className="ghost btn-lg" onClick={() => go(form.step - 1)} disabled={busy}>← Back</button>
            <button type="button" className="btn-lg" onClick={next} disabled={busy || !plan}>
              {busy ? "Please wait…" : form.step === 5 ? (plan?.trial_days ? "Start free trial" : `Continue to payment`) : "Continue"} {!busy && <Arrow />}
            </button>
          </div>
        </main>
        <aside className="wiz-side">
          {plan && (
            <div className="side-card">
              <span className="label">Your plan</span>
              <div className="plan-line"><b>{plan.name}</b><span>{plan.price_egp ? `${egp(plan.price_egp)} / mo` : "Free"}</span></div>
              <ul className="checks">{planFeatures(plan).slice(0, 3).map((f) => <li key={f}><Check />{f}</li>)}</ul>
              <button type="button" className="link" onClick={() => { go(0); setTimeout(() => document.getElementById("pricing")?.scrollIntoView(), 50); }}>Change plan</button>
            </div>
          )}
          <div className="side-card">
            <span className="label">Preview</span>
            <ChatMock colour={form.primary} short={form.short || "Your uni"} logo={form.logo} address={form.slug ? `${form.slug}.localhost` : undefined}
                      assistants={named.length ? named.map((a) => a.name) : ["Your first assistant"]} />
          </div>
        </aside>
      </div></div>
    </div></div>
  );
}

// ---------------------------------------------------------------- pieces

function ChatMock({ colour, short, logo, assistants, address }) {
  return (
    <div className="mock" style={{ "--mock": colour }} aria-hidden="true">
      <div className="mock-bar"><i /><i /><i /><span>{address || `${short.toLowerCase().replace(/[^a-z0-9]/g, "") || "your-uni"}.unibots.app`}</span></div>
      <div className="mock-body">
        <div className="mock-side">
          {logo ? <img src={logo} alt="" /> : <b><span>{short.slice(0, 3).toUpperCase()}</span>{short}</b>}
          {assistants.slice(0, 5).map((name, i) => <i key={i} className={i === 0 ? "on" : ""}>{name}</i>)}
        </div>
        <div className="mock-main">
          <span className="u">When is the application deadline?</span>
          <span className="a">Applications for the fall semester close on 15 August. You need your certificate, ID and two photos.
            <small>admissions-guide.pdf</small></span>
          <span className="u ar">ما هي الرسوم الدراسية؟</span>
          <span className="a ar">الرسوم ٤٥٬٠٠٠ جنيه للفصل الدراسي، وتُدفع على قسطين.<small>fees-2026.pdf</small></span>
          <span className="mock-input">Ask anything… <b /></span>
        </div>
      </div>
    </div>
  );
}

function Feature({ icon, title, children }) {
  return <div className="feature"><span className="ico">{icon}</span><h3>{title}</h3><p>{children}</p></div>;
}

const svg = (size, children) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const Check = ({ size = 16 }) => svg(size, <path d="M5 12.5l4.5 4.5L19 7.5" />);
const Arrow = () => svg(16, <path d="M5 12h14M13 6l6 6-6 6" />);
const IconDoc = () => svg(20, <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h4" /></>);
const IconGlobe = () => svg(20, <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>);
const IconUsers = () => svg(20, <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6" /></>);
const IconPalette = () => svg(20, <><path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.5-.8 1.5-1.5 0-1.2-1-1.5-1-2.5s.7-1.5 1.7-1.5H17a4 4 0 0 0 4-4c0-4.7-4-8.5-9-8.5z" /><circle cx="7.5" cy="11" r="1" /><circle cx="10" cy="7" r="1" /><circle cx="15" cy="7.5" r="1" /></>);
const IconMail = () => svg(18, <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></>);
const IconUpload = () => svg(18, <><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></>);
