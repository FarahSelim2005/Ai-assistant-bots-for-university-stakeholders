// One chat bubble. Assistant messages also show their sources and a 1-5 rating.
export default function Message({ message, onRate }) {
  const isAssistant = message.role === "assistant";

  return (
    <div className={`message ${message.role}`}>
      <div className="bubble">{message.content}</div>

      {isAssistant && message.sources?.length > 0 && (
        <div className="sources">Sources: {message.sources.join(", ")}</div>
      )}

      {isAssistant && message.messageId && (
        <div className="rating">
          {message.rating ? (
            <span>Thanks for rating this answer {message.rating}/5</span>
          ) : (
            <>
              <span>Was this helpful?</span>
              {[1, 2, 3, 4, 5].map((value) => (
                <button key={value} onClick={() => onRate(message.messageId, value)}>
                  {value}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
