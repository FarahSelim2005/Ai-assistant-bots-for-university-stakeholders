import { useState } from "react";
import { audienceTitle, findAssistant } from "../tenant.js";
import CampusMap from "./CampusMap.jsx";

const ARABIC_LETTERS = /[؀-ۿ]/;
// How the usual audiences are named in a sentence; other audiences use their title.
const USERS = { student: { en: "students", ar: "للطلبة" }, staff: { en: "staff", ar: "للموظفين" } };

// One chat message, in the design's chatView() style: the user's question in the
// university's colour; the answer in white, with the map (rooms, places), a file to view
// and download, a hand-over to another assistant, the source documents and a 1-5 rating.
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
      <div className="mrow u">
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
              <button type="button" className="tbtn ghost" onClick={() => setEditing(false)}>Cancel</button>
              <button type="submit" className="tbtn" disabled={busy || !draft.trim()}>Send</button>
            </div>
          </form>
        ) : (
          <div className="msg u" dir="auto">{message.content}</div>
        )}
        {/* A stopped question: send it again, change it, or copy it */}
        {message.stopped && !editing && (
          <div className="message-actions">
            <span className="muted">Stopped</span>
            <button type="button" onClick={() => onResend(message.content)} disabled={busy} title="Retry" aria-label="Retry">
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
    );
  }

  // Who the suggested assistant is for, when this user may not use it
  const forWhom = findAssistant(message.redirect?.agent)?.audiences ?? [];
  const onlyFor = message.redirect?.available === false && forWhom.length
    ? { en: forWhom.map((key) => USERS[key]?.en ?? audienceTitle(key).toLowerCase()).join(" and "),
        ar: forWhom.map((key) => USERS[key]?.ar ?? audienceTitle(key)).join(" و") }
    : null;

  return (
    <div className="mrow">
      <div className="msg a">
        {!message.mapOnly && <span className="text" dir="auto">{message.content}</span>}

        {message.file && (
          <div className="file-card">
            <span className="file-card-icon">📄</span>
            <span className="file-card-name">{message.file.download_name}</span>
            <a className="tbtn ghost" href={message.file.view_url} target="_blank" rel="noreferrer">View</a>
            <a className="tbtn" href={message.file.url} download={message.file.download_name}>Download</a>
            {message.file.word_url && (
              <a className="tbtn ghost" href={message.file.word_url} download={message.file.word_name}
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
          <div className="handover" dir="auto">
            <span>
              {ARABIC_LETTERS.test(message.content)
                ? <>السؤال ده غالباً تبع <b>{message.redirect.name}</b>{onlyFor && ` (${onlyFor.ar} بس)`}</>
                : <>This looks like a question for the <b>{message.redirect.name}</b>{onlyFor && `, which is for ${onlyFor.en} only`}.</>}
            </span>
            {/* Opens in a new tab so this conversation stays open. No button for an assistant
                this user may not use: it would refuse them. */}
            {!onlyFor && (
              <a href={message.redirect.url} target="_blank" rel="noreferrer" className="tbtn">Open {message.redirect.name} →</a>
            )}
          </div>
        )}

        {message.sources?.length > 0 && (
          <div className="srcs">
            {message.sources.map((source) => <span key={source} className="src" title="Source document">{source}</span>)}
          </div>
        )}

        {message.messageId && (
          <div className="rate">
            <span>{message.rating ? `Thanks! You rated this ${message.rating}/5` : "Rate"}</span>
            {[1, 2, 3, 4, 5].map((value) => (
              <button key={value} type="button" className={message.rating === value ? "on" : ""} disabled={Boolean(message.rating)}
                      onClick={() => onRate(message.messageId, value)} aria-label={`Rate ${value} out of 5`} title={`${value}/5`}>
                {value}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
