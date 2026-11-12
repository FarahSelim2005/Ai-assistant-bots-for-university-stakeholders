import { useEffect, useState } from "react";
import { egp, getCheckout, simulatePayment } from "./api.js";
import "../platform.css";

// /checkout/<id>: the payment page. For now only the simulated provider exists: this is our
// own test-mode page (no card is asked for, nothing is charged). "Pay" and "Fail payment" send
// the provider's event to our webhook, then the browser goes back to the sign-up or the admin.
export default function CheckoutPage({ id }) {
  const [checkout, setCheckout] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.title = "Payment · UniBots";
    getCheckout(id).then(setCheckout).catch((e) => setError(e.message));
  }, [id]);

  async function finish(outcome) {
    setBusy(true);
    setError("");
    try {
      const result = await simulatePayment(id, outcome);
      setCheckout(result);
      setTimeout(() => { window.location.href = result.return_url; }, outcome === "paid" ? 1200 : 1800);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  const what = checkout && {
    signup: `New chatbot for ${checkout.university}`,
    change_plan: `${checkout.university}: change to the ${checkout.plan_name} plan`,
    pay_now: `${checkout.university}: pay the ${checkout.plan_name} plan`,
  }[checkout.purpose];

  return (
    <div className="pf">
      {checkout?.test_mode !== false && (
        <div className="testbanner" role="note">Test mode, no real payment. No card is needed and nothing is charged.</div>
      )}
      <div className="paybox">
        <span className="brandp"><span className="blogo">UB</span>UniBots</span>
        {!checkout && !error && <p className="note">Loading…</p>}
        {checkout && (
          <>
            <p className="note">{what}</p>
            <div className="amount">{egp(checkout.amount_egp)} <small>/ month · {checkout.plan_name} plan</small></div>
            {checkout.status === "open" && (
              <>
                <div className="card-fake">Card 4242 4242 4242 4242 · 12/30 · 123<br />(simulated: nothing is entered or charged)</div>
                <div className="crow" style={{ justifyContent: "flex-start" }}>
                  <button type="button" onClick={() => finish("paid")} disabled={busy}>Pay {egp(checkout.amount_egp)}</button>
                  <button type="button" className="danger" onClick={() => finish("failed")} disabled={busy}>Fail payment</button>
                </div>
                <p className="note">"Fail payment" shows what happens when a card is declined.</p>
              </>
            )}
            {checkout.status === "paid" && <p className="okline" role="status">✓ Payment received. Taking you back…</p>}
            {checkout.status === "failed" && (
              <p className="err" role="status">The payment did not go through. Taking you back… <a href={checkout.return_url}>Go back now</a></p>
            )}
          </>
        )}
        {error && <p className="err" role="alert">{error}</p>}
      </div>
    </div>
  );
}
