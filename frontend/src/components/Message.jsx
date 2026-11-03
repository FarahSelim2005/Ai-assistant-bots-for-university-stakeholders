import { useState } from "react";
import { findAgent } from "../agents.js";
import CampusMap from "./CampusMap.jsx";

const ARABIC_LETTERS = /[؀-ۿ]/;
const USERS = { student: { en: "students", ar: "للطلبة" }, staff: { en: "staff", ar: "للموظفين" } };

// One chat message. Assistant messages also show a map (if rooms or places are mentioned),
// their sources and a 1-5 star rating.
export default function Message({ message, onRate, onResend, busy }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState(false);

  if (message.role === "user") {
    function copy() {
      navigator.clipboard.writeText(message.content).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }).catch(() => {});
    }

    function startEditing() {
      setDraft(message.content);
      setEditing(true);
    }

    function sendEdited(event) {
      event.preventDefault();
      if (!draft.trim()) return;
      setEditing(false);
      onResend(draft.trim());
    }

    return (
      <div className="message user">
        <div className="user-body">
          {(message.attachments || []).map((file, index) => (file.isImage ? (
            <img key={index} className="attached-image" src={file.dataUrl} alt={file.filename} />
          ) : (
            <span key={index} className="attached-file">📄 {file.filename}</span>
          )))}
          {editing ? (
            <form className="edit-message" onSubmit={sendEdited}>
              <textarea value={draft} onChange={(event) => setDraft(event.target.value)} dir="auto" maxLength={1000}
                        rows={Math.min(6, Math.max(2, Math.ceil(draft.length / 60)))} autoFocus
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && !event.shiftKey) sendEdited(event);
                          if (event.key === "Escape") setEditing(false);
                        }} />
              <div className="edit-message-buttons">
                <button type="button" className="secondary" onClick={() => setEditing(false)}>Cancel</button>
                <button type="submit" disabled={busy || !draft.trim()}>Send</button>
              </div>
            </form>
          ) : (
            <div className="bubble" dir="auto">{message.content}</div>
          )}
          {/* A stopped question: send it again, change it, or copy it */}
          {message.stopped && !editing && (
            <div className="message-actions">
              <span className="muted">Stopped</span>
              <button type="button" onClick={() => onResend(message.content)} disabled={busy}
                      title="Retry" aria-label="Retry">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v5h-5" /></svg>
              </button>
              <button type="button" onClick={startEditing} disabled={busy} title="Edit" aria-label="Edit">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4" /></svg>
              </button>
              <button type="button" onClick={copy} title={copied ? "Copied" : "Copy"} aria-label="Copy">
                {copied ? (
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l5 5 9-10" /></svg>
                ) : (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h8" />
                  </svg>
                )}
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Who the suggested agent is for, when this user may not use it
  const onlyFor = message.redirect?.available === false
    ? (findAgent(message.redirect.agent)?.userTypes.includes("staff") ? USERS.staff : USERS.student)
    : null;

  return (
    <div className="message assistant">
      <div className="avatar">GIU</div>
      <div className="assistant-body">
        {!message.mapOnly && <div className="bubble" dir="auto">{message.content}</div>}

        {message.file && (
          <div className="file-card">
            <span className="file-card-icon">📄</span>
            <span className="file-card-name">{message.file.download_name}</span>
            <a className="doc-view" href={message.file.view_url} target="_blank" rel="noreferrer">View</a>
            <a className="doc-download" href={message.file.url} download={message.file.download_name}>Download</a>
            {message.file.word_url && (
              <a className="doc-view" href={message.file.word_url} download={message.file.word_name}
                 title="The same CV as a Word file, to fill in the [placeholders]">Word</a>
            )}
          </div>
        )}
        {message.changes?.length > 0 && (
          <details className="changes">
            <summary>Show changes ({message.changes.length})</summary>
            <ul>
              {message.changes.map((change, i) => (
                <li key={i} dir="auto">
                  {change.before && <span className="change-before">{change.before}</span>}
                  {change.before && change.after && <span className="change-arrow"> → </span>}
                  {change.after && <span className="change-after">{change.before ? "" : "Added: "}{change.after}</span>}
                </li>
              ))}
            </ul>
          </details>
        )}

        {(message.locations?.length > 0 || message.places?.length > 0 || message.buildings?.length > 0) && (
          <CampusMap locations={message.locations} places={message.places} askedBuildings={message.buildings} />
        )}

        {message.redirect && (
          <div className="redirect-card" dir="auto">
            <span>
              {ARABIC_LETTERS.test(message.content)
                ? <>السؤال ده غالباً تبع <b>{message.redirect.name}</b>{onlyFor && ` (${onlyFor.ar} بس)`}</>
                : <>This looks like a question for the <b>{message.redirect.name}</b>{onlyFor && `, which is for ${onlyFor.en} only`}.</>}
            </span>
            {/* Opens in a new tab so this conversation stays open. No button for an agent
                this user may not use (staff asking a Career question): it would refuse them. */}
            {!onlyFor && (
              <a href={message.redirect.url} target="_blank" rel="noreferrer" className="redirect-button">
                Ask the {message.redirect.name} →
              </a>
            )}
          </div>
        )}

        {message.sources?.length > 0 && (
          <div className="sources">
            {message.sources.map((source) => (
              <span key={source} className="source-chip" title="Source document">📄 {source}</span>
            ))}
          </div>
        )}

        {message.messageId && (
          <div className="rating">
            {message.rating ? (
              <span className="muted">Thanks! You rated this {message.rating}/5</span>
            ) : (
              <>
                <span className="muted">Rate this answer</span>
                <span className="stars">
                  {/* Stars are shown 5..1 so the CSS can highlight a star and all stars before it on hover */}
                  {[5, 4, 3, 2, 1].map((value) => (
                    <button
                      key={value}
                      onClick={() => onRate(message.messageId, value)}
                      aria-label={`Rate ${value} out of 5`}
                      title={`${value}/5`}
                    >
                      ★
                    </button>
                  ))}
                </span>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
