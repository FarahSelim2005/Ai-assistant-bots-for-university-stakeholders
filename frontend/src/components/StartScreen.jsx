// First screen: the user says whether they are a student or staff member.
const USER_TYPES = [
  { value: "student", title: "Student", text: "Labs, offices, rooms, equipment and thesis support" },
  { value: "staff", title: "Staff", text: "Research facilities, funding, grants and campus offices" },
];

export default function StartScreen({ onChoose, loading, error }) {
  return (
    <div className="start">
      <section className="start-intro">
        <div className="flag-stripe vertical" />
        <p className="eyebrow">AI Assistant</p>
        <h1>Labs &amp; Research</h1>
        <p>
          Ask about GIU labs, campus buildings and offices, rooms, opening hours, equipment,
          research funding and thesis support. Answers come only from official university
          documents.
        </p>
      </section>

      <section className="start-choice">
        <img src="/giu-logo.jpg" alt="German International University" className="start-logo" />
        <h2>Who are you?</h2>
        <p className="muted">Choose one to start the chat.</p>
        <div className="choice-cards">
          {USER_TYPES.map((type) => (
            <button
              key={type.value}
              className="choice-card"
              onClick={() => onChoose(type.value)}
              disabled={loading}
            >
              <span className="choice-title">{type.title}</span>
              <span className="choice-text">{type.text}</span>
            </button>
          ))}
        </div>
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  );
}
