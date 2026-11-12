// Page for a link to an assistant this university does not have (or no longer shows), such
// as an old "/?agent=..." link.
import { tenant } from "../tenant.js";
import BrandLogo from "./BrandLogo.jsx";

export default function ComingSoon() {
  const university = tenant();

  return (
    <div className="start">
      <section className="start-intro">
        <div className="flag-stripe vertical" />
        <p className="eyebrow">Not available</p>
        <h1>{university.short_name} Chatbot</h1>
        <p>This link leads to an assistant that is not available.</p>
      </section>

      <section className="start-choice">
        <BrandLogo className="start-logo" />
        <h2>This assistant is not available</h2>
        <p className="muted">
          It may have been renamed or removed. Please choose one of the {university.name} assistants,
          or contact the relevant office directly.
        </p>
        <div className="choice-cards">
          <a href="/" className="choice-card coming-back">
            <span className="choice-title">← Choose an assistant</span>
            <span className="choice-text">Back to the start screen</span>
          </a>
        </div>
      </section>
    </div>
  );
}
