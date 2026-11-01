import CampusMap from "./CampusMap.jsx";

const ARABIC_LETTERS = /[؀-ۿ]/;

// One chat message. Assistant messages also show a map (if rooms or places are mentioned),
// their sources and a 1-5 star rating.
export default function Message({ message, onRate }) {
  if (message.role === "user") {
    const file = message.attachment;
    return (
      <div className="message user">
        <div className="user-body">
          {file && (file.isImage ? (
            <img className="attached-image" src={file.dataUrl} alt={file.filename} />
          ) : (
            <span className="attached-file">📄 {file.filename}</span>
          ))}
          <div className="bubble" dir="auto">{message.content}</div>
        </div>
      </div>
    );
  }

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
                ? <>السؤال ده غالباً تبع <b>{message.redirect.name}</b></>
                : <>This looks like a question for the <b>{message.redirect.name}</b>.</>}
            </span>
            {/* Opens in a new tab so this conversation stays open */}
            <a href={message.redirect.url} target="_blank" rel="noreferrer" className="redirect-button">
              Ask the {message.redirect.name} →
            </a>
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
