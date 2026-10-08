// Page for the GIU agents that are not built yet (opened from the start screen or from
// a redirect link such as /?agent=orientation).
import { findAgent } from "../agents.js";

export default function ComingSoon({ agentKey }) {
  const agent = findAgent(agentKey) || { name: "This assistant", handles: "" };

  return (
    <div className="start">
      <section className="start-intro">
        <div className="flag-stripe vertical" />
        <p className="eyebrow">Coming soon</p>
        <h1>{agent.name}</h1>
        <p>{agent.handles}</p>
      </section>

      <section className="start-choice">
        <img src="/giu-logo.jpg" alt="German International University" className="start-logo" />
        <h2>This assistant is not available yet</h2>
        <p className="muted">
          It is being built as part of the GIU chatbot. Until then, please contact the
          relevant office directly, or choose another assistant.
        </p>
        <div className="choice-cards">
          <a href="/" className="choice-card coming-back">
            <span className="choice-title">← Choose another assistant</span>
            <span className="choice-text">Back to the start screen</span>
          </a>
        </div>
      </section>
    </div>
  );
}
