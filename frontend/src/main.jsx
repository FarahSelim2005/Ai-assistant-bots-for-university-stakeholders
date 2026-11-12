import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import AdminPage from "./admin/AdminPage.jsx";
import ConsolePage from "./console/ConsolePage.jsx";
import ComingSoon from "./components/ComingSoon.jsx";
import CheckoutPage from "./signup/CheckoutPage.jsx";
import SignupPage from "./signup/SignupPage.jsx";
import { findAssistant, loadTenant } from "./tenant.js";
import "./App.css";

// First the university (GET /tenant: its look and assistants), then the page:
// "/admin" opens the university admin, "/console" the platform console, "/signup" the public
// sign-up and "/checkout/<id>" a payment page; "/?agent=<id>" (e.g. from a hand-over link) opens that
// assistant directly, or a "not available" page if this university has no such assistant.
const root = createRoot(document.getElementById("root"));

loadTenant().then(() => {
  const agent = new URLSearchParams(window.location.search).get("agent");
  let page = agent && !findAssistant(agent) ? <ComingSoon /> : <App initialAgent={agent} />;
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/admin") page = <AdminPage />;
  if (path === "/console") page = <ConsolePage />;
  if (path === "/signup") page = <SignupPage />;
  if (path.startsWith("/checkout/")) page = <CheckoutPage id={path.slice("/checkout/".length)} />;
  root.render(<StrictMode>{page}</StrictMode>);
}).catch((error) => {
  root.render(
    <div className="start">
      <section className="start-choice">
        <h2>This page is not available</h2>
        <p className="muted">{error.message}</p>
      </section>
    </div>,
  );
});
