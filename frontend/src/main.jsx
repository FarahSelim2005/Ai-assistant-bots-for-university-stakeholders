import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import AdminPage from "./admin/AdminPage.jsx";
import ConsolePage from "./console/ConsolePage.jsx";
import ComingSoon from "./components/ComingSoon.jsx";
import CheckoutPage from "./signup/CheckoutPage.jsx";
import SignupPage from "./signup/SignupPage.jsx";
import { CONSOLE_HOST, PLATFORM_DOMAIN, SIGNUP_HOST, siteUrl } from "./api.js";
import { findAssistant, loadTenant } from "./tenant.js";
import "./App.css";

// First the university (GET /tenant: its look and assistants), then the page:
// "/admin" opens the university admin, "/checkout/<id>" a payment page; "/?agent=<id>" (e.g. from a hand-over link) opens that
// assistant directly, or a "not available" page if this university has no such assistant.
const root = createRoot(document.getElementById("root"));

// The platform's own addresses belong to no university: console.<domain> is the platform
// console, signup.<domain> (or the bare <domain> on a server) the public sign-up and its payment page.
const host = window.location.hostname;
const startPath = window.location.pathname.replace(/\/+$/, "");
if (host === CONSOLE_HOST) {
  root.render(<StrictMode><ConsolePage /></StrictMode>);
} else if (host === SIGNUP_HOST || (host === PLATFORM_DOMAIN && host !== "localhost")) {
  const page = startPath.startsWith("/checkout/")
    ? <CheckoutPage id={startPath.slice("/checkout/".length)} /> : <SignupPage />;
  root.render(<StrictMode>{page}</StrictMode>);
} else if (startPath === "/console") {
  window.location.replace(siteUrl(CONSOLE_HOST));  // the console is not on a university's address
} else if (startPath === "/signup") {
  window.location.replace(siteUrl(SIGNUP_HOST));  // nor is the sign-up
} else loadTenant().then(() => {
  const agent = new URLSearchParams(window.location.search).get("agent");
  let page = agent && !findAssistant(agent) ? <ComingSoon /> : <App initialAgent={agent} />;
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/admin") page = <AdminPage />;
  if (path.startsWith("/checkout/")) page = <CheckoutPage id={path.slice("/checkout/".length)} />;  // a university's own plan change
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
