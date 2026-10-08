// First screen, in two steps:
// 1. the user says whether they are a student or staff member;
// 2. they choose one of the agents available to them (3 for students, 4 for staff).
// Labs & Research opens the chat; agents that are not built yet open their coming-soon page.
import { useState } from "react";
import { AGENTS } from "../agents.js";

const USER_TYPES = [
  { value: "student", title: "Student", text: "Advising, orientation, labs and research" },
  { value: "staff", title: "Staff", text: "All assistants, including HR & Policies" },
];

// The Student/Staff choice is remembered for this browser tab, so "New chat" and the
// coming-soon page's back link return straight to the assistant list.
function savedUserType() {
  try {
    const saved = sessionStorage.getItem("userType");
    return USER_TYPES.some((type) => type.value === saved) ? saved : null;
  } catch {
    return null;
  }
}

function saveUserType(type) {
  try {
    if (type) sessionStorage.setItem("userType", type);
    else sessionStorage.removeItem("userType");
  } catch {
    // not remembered; the user just picks again
  }
}

export default function StartScreen({ onChoose, loading, error }) {
  const [userType, setUserType] = useState(savedUserType);
  const agents = AGENTS.filter((agent) => agent.userTypes.includes(userType));

  function chooseUserType(type) {
    saveUserType(type);
    setUserType(type);
  }

  function chooseAgent(agent) {
    if (agent.ready) onChoose(userType);
    else window.location.href = `/?agent=${agent.key}`;
  }

  return (
    <div className="start">
      <section className="start-intro">
        <div className="flag-stripe vertical" />
        <p className="eyebrow">AI Assistants</p>
        <h1>GIU Chatbot</h1>
        <p>
          Four assistants for students and staff: graduation and advising, HR and policies,
          orientation, and labs and research. Answers come only from official university
          documents.
        </p>
      </section>

      <section className="start-choice">
        <img src="/giu-logo.jpg" alt="German International University" className="start-logo" />

        {!userType ? (
          <>
            <h2>Who are you?</h2>
            <p className="muted">Choose one to continue.</p>
            <div className="choice-cards">
              {USER_TYPES.map((type) => (
                <button key={type.value} className="choice-card" onClick={() => chooseUserType(type.value)}>
                  <span className="choice-title">{type.title}</span>
                  <span className="choice-text">{type.text}</span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            <button className="back-link" onClick={() => chooseUserType(null)} disabled={loading}>
              ← Back
            </button>
            <h2>Choose an assistant</h2>
            <p className="muted">
              {agents.length} assistants are available for {userType === "staff" ? "staff" : "students"}.
            </p>
            <div className="choice-cards">
              {agents.map((agent) => (
                <button key={agent.key} className="choice-card agent-card"
                        onClick={() => chooseAgent(agent)} disabled={loading}>
                  <span className="choice-title">
                    {agent.name}
                    {!agent.ready && <span className="soon-tag">Coming soon</span>}
                  </span>
                  <span className="choice-text">{agent.handles}</span>
                </button>
              ))}
            </div>
          </>
        )}
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  );
}
