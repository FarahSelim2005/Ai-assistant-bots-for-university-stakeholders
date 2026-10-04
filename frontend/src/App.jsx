import { useEffect, useRef, useState } from "react";
import { sendFeedback, sendMessage, startSession } from "./api.js";
import Message from "./components/Message.jsx";
import StartScreen from "./components/StartScreen.jsx";

const EXAMPLE_QUESTIONS = [
  "Where is the AI lab?",
  "Can I borrow an Arduino kit?",
  "When are research grant proposals due?",
  "Which digital libraries can I access?",
];

export default function App() {
  const [userType, setUserType] = useState(null);
  const [conversationId, setConversationId] = useState(null);
  // Each message: { role, content, sources?, messageId?, rating? }
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef(null);

  // Keep the newest message in view.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function choose(type) {
    setLoading(true);
    setError("");
    try {
      const data = await startSession(type);
      setUserType(type);
      setConversationId(data.conversation_id);
    } catch (err) {
      setError(`Could not start the chat: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    send(input.trim());
  }

  async function send(query) {
    if (!query || loading) return;

    setMessages((prev) => [...prev, { role: "user", content: query }]);
    setInput("");
    setLoading(true);
    setError("");
    try {
      const data = await sendMessage(conversationId, query);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.answer, sources: data.sources, messageId: data.message_id },
      ]);
    } catch (err) {
      setError(err.message);
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
    setConversationId(null);
    setMessages([]);
    setError("");
  }

  if (!conversationId) {
    return <StartScreen onChoose={choose} loading={loading} error={error} />;
  }

  return (
    <div className="chat">
      <header className="topbar">
        <img src="/giu-logo.jpg" alt="German International University" className="topbar-logo" />
        <div className="topbar-title">
          <h1>Labs &amp; Research Assistant</h1>
          <span>Answers from official GIU documents</span>
        </div>
        <span className="badge">{userType === "staff" ? "Staff" : "Student"}</span>
        <button className="secondary" onClick={newChat}>New chat</button>
      </header>
      <div className="flag-stripe" />

      <main className="messages">
        <div className="messages-inner">
          {messages.length === 0 && (
            <div className="welcome">
              <h2>How can I help you today?</h2>
              <p className="muted">Ask anything about GIU labs and research, or try one of these:</p>
              <div className="suggestions">
                {EXAMPLE_QUESTIONS.map((question) => (
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
              <div className="bubble typing"><span /><span /><span /></div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </main>

      <footer className="composer-area">
        {error && <p className="error">{error}</p>}
        <form className="composer" onSubmit={handleSubmit}>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask about labs, rooms, equipment, research funding..."
            maxLength={1000}
            autoFocus
          />
          <button type="submit" disabled={loading || !input.trim()}>Send</button>
        </form>
      </footer>
    </div>
  );
}
