import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import ComingSoon from "./components/ComingSoon.jsx";
import "./App.css";

// "/?agent=orientation" opens another GIU agent; only Labs & Research exists so far.
const agent = new URLSearchParams(window.location.search).get("agent");
const page = agent && agent !== "labs_research" ? <ComingSoon agentKey={agent} /> : <App />;

createRoot(document.getElementById("root")).render(<StrictMode>{page}</StrictMode>);
