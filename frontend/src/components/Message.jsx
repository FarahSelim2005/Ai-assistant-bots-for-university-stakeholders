import CampusMap from "./CampusMap.jsx";
import PlaceLinks from "./PlaceLinks.jsx";

const ARABIC_LETTERS = /[؀-ۿ]/;

// One chat message. Assistant messages also show a map (if rooms are mentioned),
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
        <div className="bubble" dir="auto">{message.content}</div>

        {message.locations?.length > 0 && <CampusMap locations={message.locations} />}

        {message.places?.length > 0 && <PlaceLinks places={message.places} />}

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
