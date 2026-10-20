import { useEffect, useRef, useState } from "react";
import { findAgent } from "./agents.js";
import { sendFeedback, sendMessage, startSession } from "./api.js";
import CallScreen, { callSupported } from "./components/CallScreen.jsx";
import Message from "./components/Message.jsx";
import StartScreen from "./components/StartScreen.jsx";

// Must match the backend (app/attachments.py and MAX_UPLOAD_MB in config.py).
const ACCEPTED_FILES = ".pdf,.txt,.md,.png,.jpg,.jpeg,.webp";
const MAX_UPLOAD_MB = 5;
const CV_QUESTION = "Please analyze my CV and suggest improvements.";

export default function App({ initialAgent }) {
  const [userType, setUserType] = useState(null);
  const [agentKey, setAgentKey] = useState(null); // which assistant this chat is with
  const [conversationId, setConversationId] = useState(null);
  // Each message: { role, content, attachment?, sources?, locations?, places?, redirect?, messageId?, rating? }
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  // File chosen for the next message: { filename, dataUrl, isImage }
  const [attachment, setAttachment] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [calling, setCalling] = useState(false);
  const [slow, setSlow] = useState(false); // the answer takes long: explain why
  const bottomRef = useRef(null);
  const fileInputRef = useRef(null);
  const cvReviewRef = useRef(false); // the next chosen file is a CV to analyse right away
  const agent = findAgent(agentKey) || findAgent("labs_research");

  // After 8 seconds of waiting, explain the delay (usually the free online models are
  // busy and the backup model on this computer is answering).
  useEffect(() => {
    if (!loading) {
      setSlow(false);
      return undefined;
    }
    const timer = setTimeout(() => setSlow(true), 8000);
    return () => clearTimeout(timer);
  }, [loading]);

  // Keep the newest message in view.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function choose(type, chosenAgent) {
    setLoading(true);
    setError("");
    try {
      const data = await startSession(type, chosenAgent);
      setUserType(type);
      setAgentKey(chosenAgent);
      setConversationId(data.conversation_id);
    } catch (err) {
      setError(`Could not start the chat: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  function handleFileChosen(event) {
    const file = event.target.files[0];
    event.target.value = ""; // so choosing the same file again still triggers onChange
    if (!file) return;
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(`The file is larger than ${MAX_UPLOAD_MB} MB.`);
      return;
    }
    // Read the file as a data URL ("data:<type>;base64,<content>") to send it as JSON.
    const reader = new FileReader();
    reader.onload = () => {
      const chosen = { filename: file.name, dataUrl: reader.result, isImage: file.type.startsWith("image/") };
      if (cvReviewRef.current) {
        cvReviewRef.current = false;
        send(CV_QUESTION, chosen); // "Analyze my CV": send the CV straight away
      } else {
        setAttachment(chosen);
      }
    };
    reader.onerror = () => setError("The file could not be read.");
    reader.readAsDataURL(file);
    setError("");
  }

  // "Analyze my CV": pick a file, which is then sent with CV_QUESTION.
  function analyzeCv() {
    cvReviewRef.current = true;
    fileInputRef.current.click();
  }

  function handleSubmit(event) {
    event.preventDefault();
    // A file can be sent without typing; then the agent is asked to explain it.
    const query = input.trim() || (attachment ? "Please explain this file." : "");
    send(query, attachment);
  }

  // Sends a question and returns the answer text (or null), so the call screen can speak it.
  async function send(query, file = null) {
    if (!query || loading) return null;

    setMessages((prev) => [...prev, { role: "user", content: query, attachment: file }]);
    setInput("");
    setAttachment(null);
    setLoading(true);
    setError("");
    try {
      const data = await sendMessage(conversationId, query, file);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer,
          sources: data.sources,
          locations: data.locations,
          places: data.places,
          redirect: data.redirect,
          messageId: data.message_id,
        },
      ]);
      return data.answer;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }

  async function handleRate(messageId, rating) {
    try {
      await sendFeedback(messageId, rating);
      setMessages((prev) => prev.map((m) => (m.messageId === messageId ? { ...m, rating } : m)));
    } catch (err) {
      setError(`Could not save your rating: ${err.message}`);
    }
  }

  function newChat() {
    setUserType(null);
    setAgentKey(null);
    setConversationId(null);
    setMessages([]);
    setAttachment(null);
    setError("");
  }

  if (!conversationId) {
    return <StartScreen onChoose={choose} loading={loading} error={error} initialAgent={initialAgent} />;
  }

  return (
    <div className="chat">
      <header className="topbar">
        <img src="/giu-logo.jpg" alt="German International University" className="topbar-logo" />
        <div className="topbar-title">
          <h1>{agent.name}</h1>
          <span>{agent.subtitle}</span>
        </div>
        <span className="badge">{userType === "staff" ? "Staff" : "Student"}</span>
        {callSupported && (
          <button className="call-start" onClick={() => setCalling(true)} title="Talk to the assistant by voice">
            📞 Call
          </button>
        )}
        <button className="secondary" onClick={newChat}>New chat</button>
      </header>
      <div className="flag-stripe" />

      {calling && (
        <CallScreen onAsk={(question) => send(question)} onHangUp={() => setCalling(false)} agentName={agent.name} />
      )}

      <main className="messages">
        <div className="messages-inner">
          {messages.length === 0 && (
            <div className="welcome">
              <h2>How can I help you today?</h2>
              <p className="muted">{agent.welcome}</p>
              {agent.cvReview && (
                <button className="cv-button" onClick={analyzeCv} disabled={loading}>
                  📄 Analyze my CV
                  <span>Upload your CV (PDF) and get concrete improvements</span>
                </button>
              )}
              <div className="suggestions">
                {agent.examples.map((question) => (
                  <button key={question} className="suggestion" onClick={() => send(question)}>
                    {question}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message, index) => (
            <Message key={index} message={message} onRate={handleRate} />
          ))}
          {loading && (
            <div className="message assistant">
              <div className="avatar">GIU</div>
              <div className="assistant-body">
                <div className="bubble typing"><span /><span /><span /></div>
                {slow && (
                  <p className="slow-note">
                    Still working… The free online models seem busy, so a backup model on this
                    computer is answering. This can take up to a minute.
                  </p>
                )}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </main>

      <footer className="composer-area">
        {error && <p className="error">{error}</p>}
        {attachment && (
          <div className="pending-file">
            {attachment.isImage ? (
              <img src={attachment.dataUrl} alt="" />
            ) : (
              <span className="file-icon">📄</span>
            )}
            <span className="pending-name">{attachment.filename}</span>
            <button type="button" onClick={() => setAttachment(null)} aria-label="Remove file">×</button>
          </div>
        )}
        <form className="composer" onSubmit={handleSubmit}>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_FILES}
            onChange={handleFileChosen}
            hidden
          />
          <button
            type="button"
            className="attach"
            onClick={() => fileInputRef.current.click()}
            title="Attach a picture or document (PDF, TXT, MD, PNG, JPG, WEBP)"
            aria-label="Attach file"
          >
            📎
          </button>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={attachment ? "Ask about your file..." : agent.placeholder}
            maxLength={1000}
            dir="auto"
            autoFocus
          />
          {agent.cvReview && (
            <button type="button" className="attach" onClick={analyzeCv} disabled={loading}
                    title="Analyze my CV" aria-label="Analyze my CV">
              📄
            </button>
          )}
          <button type="submit" disabled={loading || (!input.trim() && !attachment)}>Send</button>
        </form>
      </footer>
    </div>
  );
}
