import { useEffect, useRef, useState } from "react";
import { sendFeedback, sendMessage, startSession } from "./api.js";
import Message from "./components/Message.jsx";
import StartScreen from "./components/StartScreen.jsx";

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

  async function handleSubmit(event) {
    event.preventDefault();
    const query = input.trim();
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
      <header>
        <h1>Labs & Research Assistant</h1>
        <span className="badge">{userType === "staff" ? "Staff" : "Student"}</span>
        <button className="link" onClick={newChat}>New chat</button>
      </header>

      <main className="messages">
        {messages.length === 0 && (
          <p className="hint">Hi! Ask me something like "Where is the AI lab?"</p>
        )}
        {messages.map((message, index) => (
          <Message key={index} message={message} onRate={handleRate} />
        ))}
        {loading && (
          <div className="message assistant">
            <div className="bubble typing">Thinking<span>.</span><span>.</span><span>.</span></div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      {error && <p className="error">{error}</p>}

      <form className="composer" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Type your question..."
          maxLength={1000}
          autoFocus
        />
        <button type="submit" disabled={loading || !input.trim()}>Send</button>
      </form>
    </div>
  );
}
