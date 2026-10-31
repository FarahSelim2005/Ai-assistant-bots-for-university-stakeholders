import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import AdminPage from "./admin/AdminPage.jsx";
import { findAgent } from "./agents.js";
import ComingSoon from "./components/ComingSoon.jsx";
import "./App.css";

// "/admin" opens the admin page (documents). "/?agent=<key>" (e.g. from a redirect link)
// opens that agent directly if it is built, otherwise its coming-soon page.
const agent = new URLSearchParams(window.location.search).get("agent");
let page = agent && !findAgent(agent)?.ready ? <ComingSoon agentKey={agent} /> : <App initialAgent={agent} />;
if (window.location.pathname.replace(/\/+$/, "") === "/admin") page = <AdminPage />;

createRoot(document.getElementById("root")).render(<StrictMode>{page}</StrictMode>);
