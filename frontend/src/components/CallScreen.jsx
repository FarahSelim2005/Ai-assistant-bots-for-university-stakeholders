// "Call the agent": a hands-free voice conversation using the browser's built-in
// speech recognition (speech -> text) and speech synthesis (text -> speech).
// Each spoken question is sent through the normal chat (onAsk), so the agent,
// its rules and the saved messages are exactly the same as when typing.
// Loop: listen -> (user stops talking) -> thinking -> speak the answer -> listen ...
import { useEffect, useRef, useState } from "react";

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
export const callSupported = Boolean(SpeechRecognition && window.speechSynthesis);

const LANGUAGE = "en-US";
const GREETING = "Hello, this is the GIU Labs and Research assistant. How can I help you?";
const NO_ANSWER = "Sorry, I couldn't get an answer right now. Please try again in a moment.";
const STATUS_TEXT = {
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking… tap the circle to interrupt",
  muted: "Microphone muted",
};

export default function CallScreen({ onAsk, onHangUp }) {
  const [status, setStatus] = useState("speaking");
  const [heard, setHeard] = useState("");      // what the user is saying, live
  const [reply, setReply] = useState(GREETING); // what the agent said last
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");

  // Refs hold values that the speech callbacks need to see right now
  // (callbacks created earlier would otherwise keep old state values).
  const activeRef = useRef(true);          // false after hang up: stop everything
  const mutedRef = useRef(false);
  const recognitionRef = useRef(null);     // the current listening session
  const utteranceRef = useRef(null);       // the sentence being spoken
  const onAskRef = useRef(onAsk);
  onAskRef.current = onAsk;

  // Call timer
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // Start the call with a greeting; stop all audio when the screen closes.
  useEffect(() => {
    activeRef.current = true;
    speak(GREETING);
    return () => {
      activeRef.current = false;
      recognitionRef.current?.abort();
      window.speechSynthesis.cancel();
    };
  }, []);

  function speak(text) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = LANGUAGE;
    // Only the latest sentence may continue the loop (cancel() also fires "end").
    utterance.onend = () => {
      if (activeRef.current && utteranceRef.current === utterance) listen();
    };
    utteranceRef.current = utterance;
    window.speechSynthesis.cancel();
    setReply(text);
    setStatus("speaking");
    window.speechSynthesis.speak(utterance);
  }

  function listen() {
    if (!activeRef.current) return;
    if (mutedRef.current) {
      setStatus("muted");
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = LANGUAGE;
    recognition.interimResults = true; // show words while the user is talking
    let finalText = "";

    recognition.onresult = (event) => {
      const text = Array.from(event.results).map((r) => r[0].transcript).join("");
      setHeard(text);
      if (event.results[event.results.length - 1].isFinal) finalText = text;
    };
    recognition.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return; // keep listening
      activeRef.current = false;
      setError(event.error === "not-allowed" || event.error === "service-not-allowed"
        ? "Microphone access is blocked. Allow the microphone for this site and call again."
        : `Voice recognition stopped (${event.error}). Please hang up and call again.`);
    };
    // Recognition ends when the user stops talking (or after silence).
    recognition.onend = () => {
      if (!activeRef.current || recognitionRef.current !== recognition) return;
      if (finalText.trim()) ask(finalText.trim());
      else listen(); // nothing was said: keep listening
    };

    recognitionRef.current = recognition;
    setHeard("");
    setStatus("listening");
    recognition.start();
  }

  async function ask(question) {
    recognitionRef.current = null;
    setStatus("thinking");
    const answer = await onAskRef.current(question); // the normal chat request
    if (activeRef.current) speak(answer || NO_ANSWER);
  }

  function toggleMute() {
    const nowMuted = !mutedRef.current;
    mutedRef.current = nowMuted;
    setMuted(nowMuted);
    if (nowMuted && status === "listening") {
      const recognition = recognitionRef.current;
      recognitionRef.current = null;
      recognition?.abort();
      setStatus("muted");
    } else if (!nowMuted && status === "muted") {
      listen();
    }
  }

  function interrupt() {
    if (status !== "speaking") return;
    utteranceRef.current = null;
    window.speechSynthesis.cancel();
    listen();
  }

  function hangUp() {
    activeRef.current = false;
    recognitionRef.current?.abort();
    window.speechSynthesis.cancel();
    onHangUp();
  }

  const time = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <div className="call" role="dialog" aria-label="Voice call with the assistant">
      <div className="call-top">
        <img src="/giu-logo.jpg" alt="German International University" className="call-logo" />
        <span className="call-time">{time}</span>
      </div>

      <div className="call-center">
        <button className={`call-avatar ${status}`} onClick={interrupt} aria-label="Interrupt">
          GIU
        </button>
        <h2>Labs &amp; Research Assistant</h2>
        <p className="call-status">{error || STATUS_TEXT[status]}</p>

        <div className="call-text">
          {status === "listening" || status === "thinking" ? (
            <p className="call-heard">{heard || "Ask your question…"}</p>
          ) : (
            <p className="call-reply">{reply}</p>
          )}
        </div>
      </div>

      <div className="call-buttons">
        <button className={`call-round secondary ${muted ? "on" : ""}`} onClick={toggleMute}
                aria-label={muted ? "Unmute" : "Mute"}>
          <span className="call-icon">{muted ? "🔇" : "🎤"}</span>
          <span className="call-label">{muted ? "Unmute" : "Mute"}</span>
        </button>
        <button className="call-round hang-up" onClick={hangUp} aria-label="Hang up">
          <span className="call-icon">📞</span>
          <span className="call-label">Hang up</span>
        </button>
      </div>
    </div>
  );
}
