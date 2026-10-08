// Page for the other GIU agents (opened from a redirect link such as /?agent=orientation).
// Only the Labs & Research agent is built so far; the others show this placeholder.
// Keys and names must match backend/app/agents/directory.py.
const AGENTS = {
  graduation_advising: {
    name: "Graduation & Advising Assistant",
    handles: "Degree requirements, course planning, graduation timeline and advising.",
  },
  hr_policies: {
    name: "HR & Policies Assistant",
    handles: "Leave types, benefits, staff policies and complaints.",
  },
  orientation: {
    name: "Orientation Assistant",
    handles: "Campus map, buildings, registration and student services.",
  },
};

export default function ComingSoon({ agentKey }) {
  const agent = AGENTS[agentKey] || { name: "This assistant", handles: "" };

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
          relevant office directly, or go back to the Labs &amp; Research Assistant.
        </p>
        <div className="choice-cards">
          <a href="/" className="choice-card coming-back">
            <span className="choice-title">← Labs &amp; Research Assistant</span>
            <span className="choice-text">Labs, research, campus buildings and offices</span>
          </a>
        </div>
      </section>
    </div>
  );
}
