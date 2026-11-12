import { useEffect, useState } from "react";
import { request } from "./api.js";

// The university's numbers for the last 30 days: questions, chats, unanswered questions (the
// assistant gave its "no information" answer) and ratings; per assistant; and the latest
// unanswered questions, which show which documents are missing.
export default function AnalyticsPage({ call }) {
  const [numbers, setNumbers] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    call((token) => request("/admin/analytics", { token })).then(setNumbers).catch((err) => setError(err.message));
  }, []);

  if (error) return <p className="error">Could not load the numbers: {error}</p>;
  if (!numbers) return <p className="note">Loading…</p>;
  return (
    <>
      <div className="crow"><h3>Analytics</h3><span className="pill">last 30 days</span></div>
      <div className="kpis">
        <div className="kpi"><span>Questions</span><b>{numbers.questions_30d.toLocaleString("en")}</b><small>to all assistants</small></div>
        <div className="kpi"><span>Active users</span><b>{numbers.chats_30d.toLocaleString("en")}</b><small>chats started (users do not sign in)</small></div>
        <div className="kpi"><span>Unanswered</span><b>{numbers.unanswered_pct}%</b><small>{numbers.unanswered_30d} of {numbers.questions_30d} questions</small></div>
        <div className="kpi"><span>Average rating</span><b>{numbers.average_rating ? `${numbers.average_rating.toFixed(1)} / 5` : "–"}</b>
          <small>{numbers.ratings} rating{numbers.ratings === 1 ? "" : "s"}</small></div>
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Assistant</th><th className="num">Questions</th><th>Unanswered</th><th className="num">Rating</th></tr></thead>
          <tbody>
            {numbers.per_assistant.length === 0 && <tr><td colSpan={4} className="note">No questions in the last 30 days.</td></tr>}
            {numbers.per_assistant.map((a) => (
              <tr key={a.id}>
                <td>{a.name}</td>
                <td className="num">{a.questions.toLocaleString("en")}</td>
                <td><div className="bar"><i className={a.unanswered_pct >= 50 ? "full" : ""} style={{ width: `${a.unanswered_pct}%` }} /></div>
                  <span className="note">{a.unanswered_pct}%</span></td>
                <td className="num">{a.average_rating ? a.average_rating.toFixed(1) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h4>Latest unanswered questions</h4>
        <p className="note">The assistant had no document with the answer. Adding one on the Documents page fixes it.</p>
        {numbers.recent_unanswered.length === 0 && <p className="note">None in the last 30 days.</p>}
        {numbers.recent_unanswered.map((q, i) => (
          <div className="agentrow" key={i}>
            <span dir="auto">{q.question}<small>{q.assistant} · {new Date(q.at).toLocaleString()}</small></span>
          </div>
        ))}
      </div>
    </>
  );
}
