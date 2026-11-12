// First screen, in two steps:
// 1. the user says who they are (the university's audiences, e.g. student or staff);
// 2. they choose one of the assistants for them (with just one, it opens directly).
// A link like "/?agent=<id>" opens that assistant directly once the audience is known.
import { useEffect, useRef, useState } from "react";
import { assistantsFor, tenant } from "../tenant.js";
import BrandLogo from "./BrandLogo.jsx";

// The audience choice is remembered for this browser tab, so "New chat" returns straight to
// the assistant list.
function savedUserType() {
  try {
    const saved = sessionStorage.getItem("userType");
    return tenant().audiences.some((audience) => audience.key === saved) ? saved : null;
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

export default function StartScreen({ onChoose, loading, error, initialAgent }) {
  const university = tenant();
  const [userType, setUserType] = useState(savedUserType);
  const agents = userType ? assistantsFor(userType) : [];
  const audience = university.audiences.find((a) => a.key === userType);

  // Opened from a link to a specific assistant, or there is only one: start it as soon as we
  // know the audience. (The ref makes sure it starts only once, also when React runs effects twice.)
  const started = useRef(false);
  useEffect(() => {
    if (!userType || started.current) return;
    const linked = agents.find((agent) => agent.id === initialAgent || agent.template_key === initialAgent);
    const only = agents.length === 1 ? agents[0] : null;
    if (linked || only) {
      started.current = true;
      if (linked) window.history.replaceState(null, "", "/"); // so "New chat" shows the list again
      onChoose(userType, (linked || only).id);
    }
  }, [userType]);

  function chooseUserType(type) {
    started.current = false;
    saveUserType(type);
    setUserType(type);
  }

  const intro = university.intro
    || `${university.assistants.length === 1 ? "An assistant" : `${university.assistants.length} assistants`} for `
       + `${university.audiences.map((a) => a.title.toLowerCase()).join(" and ")} users. University facts come only `
       + `from official ${university.short_name} documents.`;

  return (
    <div className="start">
      <section className="start-intro">
        <div className="flag-stripe vertical" />
        <p className="eyebrow">AI Assistants</p>
        <h1>{university.short_name} Chatbot</h1>
        <p>{intro}</p>
      </section>

      <section className="start-choice">
        <BrandLogo className="start-logo" />

        {!userType ? (
          <>
            <h2>Who are you?</h2>
            <p className="muted">Choose one to continue.</p>
            <div className="choice-cards">
              {university.audiences.map((type) => (
                <button key={type.key} className="choice-card" onClick={() => chooseUserType(type.key)}>
                  <span className="choice-title">{type.title}</span>
                  {type.text && <span className="choice-text">{type.text}</span>}
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
              {agents.length === 0
                ? `No assistants are available for ${audience?.title.toLowerCase() ?? userType} users yet.`
                : `${agents.length} ${agents.length === 1 ? "assistant is" : "assistants are"} available for `
                  + `${audience?.title.toLowerCase() ?? userType} users.`}
            </p>
            <div className="choice-cards">
              {agents.map((agent) => (
                <button key={agent.id} className="choice-card agent-card"
                        onClick={() => onChoose(userType, agent.id)} disabled={loading}>
                  <span className="choice-title">{agent.name}</span>
                  <span className="choice-text">{agent.summary}</span>
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
