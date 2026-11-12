import { useEffect, useState } from "react";
import { request } from "./api.js";

const egp = (n) => `EGP ${Number(n || 0).toLocaleString("en")}`;
const day = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "");
const EVENTS = {
  "subscription.created": "Subscription started", "checkout.paid": "Payment", "checkout.failed": "Payment failed",
  "invoice.paid": "Monthly renewal paid", "invoice.payment_failed": "Monthly renewal failed",
  "subscription.paused": "Chat paused", "subscription.canceled": "Subscription ended", "subscription.cancel_requested": "Cancelled",
  "trial.extended": "Trial extended",
};

// Billing (tenant_admin): the university's plan and subscription, choosing a paid plan or
// paying after a failed renewal (the payment page), cancelling, and the payment history.
// Universities added by hand (no subscription) see that the platform manages their plan.
export default function BillingPage({ call, returned }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(returned ? "Back from the payment page. The status below is up to date." : "");

  const load = () => call((token) => request("/admin/billing", { token })).then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function act(path, body, message) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await call((token) => request(path, { method: "POST", token, body }));
      if (result.url) { window.location.href = result.url; return; } // the payment page
      setNotice(message);
      await load();
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  }

  if (!data) return error ? <p className="error">{error}</p> : <p className="note">Loading…</p>;
  const sub = data.subscription;
  if (!sub) {
    return (
      <>
        <div className="crow"><h3>Billing</h3></div>
        <div className="panel"><h4>Your plan is managed by the platform</h4>
          <p className="note">Your university was set up by the platform team and is billed by invoice. To change your plan, please contact us.</p></div>
      </>
    );
  }

  const stopped = ["paused", "canceled"].includes(sub.status);
  const state = {
    trialing: [`Free trial until ${day(sub.trial_ends_at)}.`, "Choose a plan before then to keep the chat running. Nothing is deleted when a trial ends."],
    active: [sub.cancel_at_period_end ? `Cancelled: it ends on ${day(sub.current_period_end)}.` : `Active. Renews on ${day(sub.current_period_end)}.`,
      sub.cancel_at_period_end ? "The chat keeps working until then." : `${egp(sub.price_egp)} a month.`],
    past_due: [`The last payment failed. The chat keeps working until ${day(sub.grace_ends_at)}.`, "Pay now to keep it running."],
    paused: ["The chat is paused.", "Students and staff see a \"paused\" message. Your assistants and documents are kept. Choose a plan or pay to start it again."],
    canceled: ["The subscription has ended.", "The chat is paused; nothing is deleted. Choose a plan to start again."],
  }[sub.status];

  return (
    <>
      <div className="crow"><h3>Billing</h3>{sub.provider === "simulated" && <span className="pill warn">test mode · no real payments</span>}</div>
      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}
      <div className="panel">
        <h4>{sub.plan_name} plan <span className={`pill ${stopped ? "crit" : sub.status === "past_due" ? "warn" : "ok"}`}>{sub.status.replace("_", " ")}</span></h4>
        <p><b>{state[0]}</b> <span className="note">{state[1]}</span></p>
        <div className="crow" style={{ justifyContent: "flex-start" }}>
          {["past_due", "paused", "canceled"].includes(sub.status) && sub.price_egp > 0 && (
            <button type="button" disabled={busy} onClick={() => act("/admin/billing/checkout", { plan: sub.plan })}>Pay {egp(sub.price_egp)} now</button>
          )}
          {["active", "past_due"].includes(sub.status) && !sub.cancel_at_period_end && (
            <button type="button" className="danger" disabled={busy}
                    onClick={() => window.confirm("Cancel the subscription? The chat keeps working until the end of the paid month, then pauses. Nothing is deleted.")
                      && act("/admin/billing/cancel", null, "Cancelled. The chat keeps working until the end of the paid month.")}>Cancel subscription</button>
          )}
          {sub.status === "trialing" && (
            <button type="button" className="danger" disabled={busy}
                    onClick={() => window.confirm("End the free trial now? The chat pauses. Nothing is deleted.")
                      && act("/admin/billing/cancel", null, "The trial has ended.")}>End trial</button>
          )}
          {sub.cancel_at_period_end && sub.status === "active" && (
            <button type="button" className="ghost" disabled={busy} onClick={() => act("/admin/billing/resume", null, "Your subscription continues.")}>Keep my subscription</button>
          )}
        </div>
      </div>
      <h4>Plans</h4>
      <div className="plans">
        {data.plans.map((p) => {
          const current = p.key === sub.plan && !stopped && sub.status !== "trialing";
          return (
            <div key={p.key} className="panel">
              <h4>{p.name} {current && <span className="pill acc">your plan</span>}</h4>
              <div><b style={{ fontSize: 20 }}>{egp(p.price_egp)}</b> <span className="note">/ month</span></div>
              <p className="note">{p.max_assistants ? `Up to ${p.max_assistants} assistants` : "Unlimited assistants"} ·{" "}
                {p.monthly_token_cap ? `about ${(Math.round(p.monthly_token_cap / 2500 / 100) * 100).toLocaleString("en")} questions a month` : "no monthly limit"}</p>
              {!current && p.key !== sub.plan && (
                <button type="button" disabled={busy} onClick={() => act("/admin/billing/checkout", { plan: p.key })}>Choose {p.name}</button>
              )}
            </div>
          );
        })}
      </div>
      <h4>History</h4>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Date</th><th>What</th><th>Plan</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {sub.events.map((e, i) => (
              <tr key={i}><td>{new Date(e.at).toLocaleString("en-GB")}</td><td>{EVENTS[e.kind] || e.kind}</td><td>{e.plan || ""}</td>
                <td className="num">{e.amount_egp != null ? egp(e.amount_egp) : ""}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
