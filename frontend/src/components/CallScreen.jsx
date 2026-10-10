// "Call the agent": a hands-free voice conversation.
// Speech -> text: the microphone is recorded in the browser and sent to the backend,
// where Whisper (running locally) detects Arabic or English by itself.
// Text -> speech: the browser's built-in voices (an Arabic or English voice per answer).
// Each question goes through the normal chat (onAsk), so the agent and its rules are
// exactly the same as when typing.
// Loop: listen -> (user pauses) -> understanding -> thinking -> speak -> listen ...
import { useEffect, useRef, useState } from "react";
import { transcribe } from "../api.js";

export const callSupported = Boolean(
  navigator.mediaDevices?.getUserMedia && window.MediaRecorder && window.speechSynthesis,
);

const GREETING_EN = "Hello! This is the GIU Labs and Research assistant. Ask me in English or Arabic.";
const GREETING_AR = "أهلاً! اسألني بالعربي أو بالإنجليزي.";
const NO_ANSWER = {
  en: "Sorry, I couldn't get an answer right now. Please try again in a moment.",
  ar: "آسف، مقدرتش أجيب إجابة دلوقتي. حاول تاني بعد شوية.",
};
const STATUS_TEXT = {
  listening: "Listening… speak in Arabic or English",
  understanding: "Understanding…",
  thinking: "Thinking…",
  speaking: "Speaking… tap the circle to interrupt",
  muted: "Microphone muted",
};
const ARABIC_LETTERS = /[؀-ۿ]/;

// When to stop recording: after the user spoke and then was quiet for a moment.
const SILENCE_MS = 1000;      // pause that ends a question
const MAX_QUESTION_MS = 15000;
const MAX_WAIT_MS = 12000;    // nobody spoke: start a fresh recording
const CALIBRATE_MS = 300;     // measure the room noise first
const MIN_LEVEL = 0.015;      // volume that counts as speech, at least

// Pick a voice that matches the text: Arabic text gets an Arabic voice, otherwise English.
function voiceFor(text) {
  const wanted = ARABIC_LETTERS.test(text) ? "ar" : "en";
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith(wanted));
  const preferred = wanted === "ar" ? "ar-eg" : "en-us";
  return (
    voices.find((v) => v.lang.toLowerCase() === preferred && /natural|online/i.test(v.name)) ||
    voices.find((v) => v.lang.toLowerCase() === preferred) ||
    voices[0] ||
    null
  );
}

export default function CallScreen({ onAsk, onHangUp }) {
  const [status, setStatus] = useState("speaking");
  const [heard, setHeard] = useState("");  // what the user said (after Whisper)
  const [reply, setReply] = useState("");  // what the agent said last
  const [level, setLevel] = useState(0);   // microphone volume, drives the circle's glow
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");

  // Refs hold values the audio callbacks need right now (state in old callbacks is stale).
  const activeRef = useRef(true);
  const mutedRef = useRef(false);
  const languageRef = useRef("en");      // language of the last question
  const streamRef = useRef(null);        // microphone
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const recorderRef = useRef(null);
  const timerRef = useRef(null);         // volume check while recording
  const lastUtteranceRef = useRef(null);
  const onAskRef = useRef(onAsk);
  onAskRef.current = onAsk;

  // Call timer
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // Start: open the microphone, greet, then listen. Stop everything when the screen closes.
  useEffect(() => {
    activeRef.current = true;
    let cancelled = false; // this run was cleaned up (React runs effects twice in development)
    navigator.mediaDevices
      .getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const context = new AudioContext();
        const analyser = context.createAnalyser();
        analyser.fftSize = 1024;
        context.createMediaStreamSource(stream).connect(analyser);
        audioContextRef.current = context;
        analyserRef.current = analyser;
        greetWhenVoicesReady();
      })
      .catch(() => {
        if (cancelled) return;
        activeRef.current = false;
        setError("Microphone access is blocked. Allow the microphone for this site and call again.");
      });
    return () => {
      cancelled = true;
      stopEverything();
    };
  }, []);

  function stopEverything() {
    activeRef.current = false;
    clearInterval(timerRef.current);
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.onstop = null;
      recorderRef.current.stop();
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    audioContextRef.current?.close();
    window.speechSynthesis.cancel();
  }

  // Browsers load their voices a moment after the page opens; wait for them (max 1 s).
  function greetWhenVoicesReady() {
    let greeted = false;
    const greet = () => {
      if (greeted || !activeRef.current) return;
      greeted = true;
      speak([GREETING_EN, GREETING_AR]);
    };
    setTimeout(greet, 1000);
    if (window.speechSynthesis.getVoices().length) greet();
    else window.speechSynthesis.addEventListener("voiceschanged", greet, { once: true });
  }

  // Speak one or more sentences (each with a matching voice), then listen again.
  function speak(texts) {
    window.speechSynthesis.cancel();
    let last = null;
    for (const text of texts) {
      const utterance = new SpeechSynthesisUtterance(text);
      const voice = voiceFor(text);
      if (voice) utterance.voice = voice;
      utterance.lang = voice?.lang || (ARABIC_LETTERS.test(text) ? "ar-EG" : "en-US");
      window.speechSynthesis.speak(utterance);
      last = utterance;
    }
    // Only the latest sentence may continue the loop (cancel() also fires "end").
    last.onend = () => {
      if (activeRef.current && lastUtteranceRef.current === last) listen();
    };
    lastUtteranceRef.current = last;
    setReply(texts.join("\n"));
    setStatus("speaking");
  }

  // Current microphone volume (0 = silence, ~0.1+ = loud speech).
  function currentLevel() {
    const samples = new Float32Array(analyserRef.current.fftSize);
    analyserRef.current.getFloatTimeDomainData(samples);
    return Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length);
  }

  // Record until the user has spoken and then paused, then send the recording to Whisper.
  function listen() {
    if (!activeRef.current || !streamRef.current) return;
    if (mutedRef.current) {
      setStatus("muted");
      return;
    }
    const chunks = [];
    const recorder = new MediaRecorder(streamRef.current);
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorderRef.current = recorder;

    const startedAt = Date.now();
    let noise = 0;
    let noiseSamples = 0;
    let spokeAt = null;    // when speech started
    let quietSince = null; // when the current silence started

    recorder.onstop = () => {
      clearInterval(timerRef.current);
      setLevel(0);
      if (!activeRef.current || mutedRef.current) return;
      if (spokeAt) understand(new Blob(chunks, { type: recorder.mimeType }));
      else listen(); // nobody spoke: start a fresh recording
    };

    timerRef.current = setInterval(() => {
      const volume = currentLevel();
      const now = Date.now();
      setLevel(volume);
      if (now - startedAt < CALIBRATE_MS) {
        noise += volume;
        noiseSamples += 1;
        return;
      }
      const threshold = Math.max(MIN_LEVEL, (noise / Math.max(noiseSamples, 1)) * 2.5);
      if (volume > threshold) {
        spokeAt ??= now;
        quietSince = null;
      } else if (spokeAt) {
        quietSince ??= now;
      }
      const finished = spokeAt && quietSince && now - quietSince > SILENCE_MS;
      const tooLong = spokeAt && now - spokeAt > MAX_QUESTION_MS;
      const nobodySpoke = !spokeAt && now - startedAt > MAX_WAIT_MS;
      if (finished || tooLong || nobodySpoke) recorder.stop();
    }, 50);

    recorder.start();
    setHeard("");
    setStatus("listening");
  }

  // Whisper turns the recording into text; then the question goes to the agent.
  async function understand(recording) {
    setStatus("understanding");
    try {
      const { text, language } = await transcribe(recording);
      if (!activeRef.current) return;
      if (!text.trim()) {
        listen(); // only noise was recorded
        return;
      }
      languageRef.current = language;
      setHeard(text);
      setStatus("thinking");
      const answer = await onAskRef.current(text); // the normal chat request
      if (activeRef.current) speak([answer || NO_ANSWER[languageRef.current] || NO_ANSWER.en]);
    } catch {
      if (activeRef.current) speak([NO_ANSWER[languageRef.current] || NO_ANSWER.en]);
    }
  }

  function toggleMute() {
    const nowMuted = !mutedRef.current;
    mutedRef.current = nowMuted;
    setMuted(nowMuted);
    if (nowMuted && status === "listening") {
      recorderRef.current?.stop(); // onstop sees "muted" and does not send anything
      setStatus("muted");
    } else if (!nowMuted && status === "muted") {
      listen();
    }
  }

  function interrupt() {
    if (status !== "speaking") return;
    lastUtteranceRef.current = null;
    window.speechSynthesis.cancel();
    listen();
  }

  function hangUp() {
    stopEverything();
    onHangUp();
  }

  const time = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  // The circle grows with the voice while listening, so users see they are heard.
  const glow = status === "listening" ? Math.min(level * 400, 40) : 0;

  return (
    <div className="call" role="dialog" aria-label="Voice call with the assistant">
      <div className="call-top">
        <img src="/giu-logo.jpg" alt="German International University" className="call-logo" />
        <span className="call-languages-note">العربية · English</span>
        <span className="call-time">{time}</span>
      </div>

      <div className="call-center">
        <button className={`call-avatar ${status}`} onClick={interrupt} aria-label="Interrupt"
                style={glow ? { boxShadow: `0 0 0 ${glow}px rgba(196, 22, 28, 0.35)` } : undefined}>
          GIU
        </button>
        <h2>Labs &amp; Research Assistant</h2>
        <p className="call-status">{error || STATUS_TEXT[status]}</p>

        <div className="call-text">
          {status === "listening" || status === "understanding" || status === "thinking" ? (
            <p className="call-heard" dir="auto">{heard || "…"}</p>
          ) : (
            <p className="call-reply" dir="auto">{reply}</p>
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
