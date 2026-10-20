import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { findAgent } from "./agents.js";
import ComingSoon from "./components/ComingSoon.jsx";
import "./App.css";

// "/?agent=<key>" (e.g. from a redirect link) opens that agent directly if it is built,
// otherwise its coming-soon page.
const agent = new URLSearchParams(window.location.search).get("agent");
const page = agent && !findAgent(agent)?.ready ? <ComingSoon agentKey={agent} /> : <App initialAgent={agent} />;

createRoot(document.getElementById("root")).render(<StrictMode>{page}</StrictMode>);
