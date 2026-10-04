// First screen: the user says whether they are a student or staff member.
export default function StartScreen({ onChoose, loading, error }) {
  return (
    <div className="start">
      <h1>Labs & Research Assistant</h1>
      <p>Ask about labs, rooms, opening hours, equipment, research funding and thesis support.</p>
      <p className="start-question">Who are you?</p>
      <div className="start-buttons">
        <button onClick={() => onChoose("student")} disabled={loading}>Student</button>
        <button onClick={() => onChoose("staff")} disabled={loading}>Staff</button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
