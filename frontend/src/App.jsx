import { useEffect, useRef, useState } from "react";
import { assistantsFor, audienceTitle, findAssistant, hasSkill, initials, tenant } from "./tenant.js";
import { closeDocument, fileUrl, sendFeedback, sendMessage, startSession } from "./api.js";
import CallScreen, { callSupported } from "./components/CallScreen.jsx";
import Message from "./components/Message.jsx";
import StartScreen from "./components/StartScreen.jsx";
import "./chat.css";

// Must match the backend (app/attachments.py, MAX_UPLOAD_MB and DOC_EDIT_MAX_MB in config.py).
// Which of them an assistant accepts follows its skills ("files", "images").
const DOCUMENT_FILES = ".pdf,.txt,.md,.docx,.xlsx,.pptx";
const IMAGE_FILES = ".png,.jpg,.jpeg,.webp";
const MAX_UPLOAD_MB = 10; // files to edit; questions about a file allow 5 MB (checked by the backend)
const MAX_FILES = 5; // files sent with one message (MAX_FILES in the backend's schemas.py)
const CV_QUESTION = "Please analyze my CV and suggest improvements.";
// Questions that ask where a place is or how to get there, in English or Egyptian Arabic.
const WHERE_QUESTION = /\b(where|location|located|direction|directions|how (do|can) i (get|go|reach|find))\b|فين|وين|اين|أين|مكان|اروح|أروح|اوصل|أوصل/i;

export default function App({ initialAgent }) {
  const [userType, setUserType] = useState(null);
  const [agentKey, setAgentKey] = useState(null); // which assistant this chat is with
  const [conversationId, setConversationId] = useState(null);
  // Each message: { role, content, attachments?, sources?, locations?, places?, redirect?, messageId?, rating? }
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  // Files chosen for the next message, each { filename, dataUrl, isImage }
  const [attachments, setAttachments] = useState([]);
  const [menuOpen, setMenuOpen] = useState(false); // the "+" menu (upload files, analyze my CV)
  // The document this chat is working on (the last edited file or restructured CV):
  // { filename, download_name, url, view_url, version, token, word_url?, word_name? }.
  // Edit requests ("now make it shorter") change it; questions are answered as usual.
  const [activeDoc, setActiveDoc] = useState(null);
  const [withFile, setWithFile] = useState(false); // the current request involves a file
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [calling, setCalling] = useState(false);
  const [slow, setSlow] = useState(false); // the answer takes long: explain why
  const bottomRef = useRef(null);
  const fileInputRef = useRef(null);
  const cvReviewRef = useRef(false); // the next chosen file is a CV to analyse right away
  const requestRef = useRef(null); // the answer being waited for: { controller, query, files }
  const menuRef = useRef(null);
  const agent = findAssistant(agentKey) || tenant().assistants[0];
  // What this assistant can do here (its skills, and what the university allows)
  const canCv = hasSkill(agent, "cv");
  const accepted = [hasSkill(agent, "files") && DOCUMENT_FILES, hasSkill(agent, "images") && IMAGE_FILES]
    .filter(Boolean).join(",");

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

  // Close the "+" menu on a click outside it or on Escape.
  useEffect(() => {
    if (!menuOpen) return undefined;
    const closeOutside = (event) => { if (!menuRef.current?.contains(event.target)) setMenuOpen(false); };
    const closeOnEscape = (event) => { if (event.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

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

  // Read a file as a data URL ("data:<type>;base64,<content>") to send it as JSON.
  function readFile(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve({ filename: file.name, dataUrl: reader.result, isImage: file.type.startsWith("image/") });
      reader.onerror = () => reject(new Error(`${file.name} could not be read.`));
      reader.readAsDataURL(file);
    });
  }

  async function handleFilesChosen(event) {
    const reviewCv = cvReviewRef.current;
    cvReviewRef.current = false;
    let files = [...event.target.files];
    event.target.value = ""; // so choosing the same file again still triggers onChange
    if (!files.length) return;
    setError("");
    const tooLarge = files.filter((file) => file.size > MAX_UPLOAD_MB * 1024 * 1024);
    if (tooLarge.length) {
      setError(`Larger than ${MAX_UPLOAD_MB} MB: ${tooLarge.map((f) => f.name).join(", ")}`);
      files = files.filter((file) => !tooLarge.includes(file));
    }
    if (reviewCv) {
      files = files.slice(0, 1); // one CV
    } else if (files.length > MAX_FILES - attachments.length) {
      setError(`You can send up to ${MAX_FILES} files with one message.`);
      files = files.slice(0, Math.max(0, MAX_FILES - attachments.length));
    }
    try {
      const chosen = await Promise.all(files.map(readFile));
      if (!chosen.length) return;
      if (reviewCv) send(CV_QUESTION, chosen); // "Analyze my CV": send the CV straight away
      else setAttachments((prev) => [...prev, ...chosen].slice(0, MAX_FILES));
    } catch (err) {
      setError(err.message);
    }
  }

  // "+" menu: pick files for the next message.
  function pickFiles() {
    setMenuOpen(false);
    fileInputRef.current.click();
  }

  // "Analyze my CV": pick a file, which is then sent with CV_QUESTION.
  function analyzeCv() {
    setMenuOpen(false);
    cvReviewRef.current = true;
    fileInputRef.current.click();
  }

  function handleSubmit(event) {
    event.preventDefault();
    // Files can be sent without typing; then the agent is asked to explain them.
    const explain = attachments.length > 1 ? "Please explain these files." : "Please explain this file.";
    const query = input.trim() || (attachments.length ? explain : "");
    send(query, attachments);
  }

  // "Close": stop editing the document. Its files are kept, so the View and Download links
  // in the chat still work (the backend deletes them after an hour); a new chat deletes them.
  function stopEditing(deleteFiles = false) {
    if (activeDoc && deleteFiles) closeDocument(conversationId, activeDoc.token).catch(() => {});
    setActiveDoc(null);
  }

  // Sends a question and returns the answer text (or null), so the call screen can speak it.
  async function send(query, files = []) {
    if (!query || loading) return null;

    setMessages((prev) => [...prev, { role: "user", content: query, attachments: files }]);
    setInput("");
    setAttachments([]);
    setLoading(true);
    setError("");
    const request = { controller: new AbortController(), query, files };
    requestRef.current = request;
    setWithFile(Boolean(files.length || activeDoc));
    try {
      const data = await sendMessage(conversationId, query, files, request.controller.signal, activeDoc?.token);
      if (requestRef.current !== request) return null; // stopped meanwhile: ignore the late answer
      // An edited file or a restructured CV: show View / Download, and remember it for the
      // next edit request.
      const answerFile = data.file && {
        ...data.file, url: fileUrl(data.file.url), view_url: fileUrl(data.file.view_url),
        word_url: data.file.word_url && fileUrl(data.file.word_url),
      };
      if (answerFile) setActiveDoc(answerFile);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer,
          sources: data.sources,
          locations: data.locations,
          places: data.places,
          buildings: data.buildings,
          redirect: data.redirect,
          // "Where is the gym?": the map card already gives the walking directions, so
          // the text answer would only repeat them; show just the card. Other questions
          // about a place ("gym opening hours?") keep their text answer.
          mapOnly: data.places?.length > 0 && WHERE_QUESTION.test(query),
          file: answerFile,
          changes: data.changes,
          messageId: data.message_id,
        },
      ]);
      return data.answer;
    } catch (err) {
      // AbortError, or a request that was stopped meanwhile: the user pressed Stop
      if (err.name !== "AbortError" && requestRef.current === request) setError(err.message);
      return null;
    } finally {
      if (requestRef.current === request) {
        requestRef.current = null;
        setLoading(false);
      }
    }
  }

  // "Stop": cancel the answer. The question stays in the chat, marked as stopped, with
  // Retry, Edit and Copy under it. The backend does not save a stopped question.
  // It always resets the screen, even if the request cannot be found (for example after
  // the page was updated while a slow answer was still running).
  function stop(event) {
    event?.preventDefault(); // this click must never also send the form
    const request = requestRef.current;
    requestRef.current = null; // any answer that still arrives is ignored
    request?.controller.abort();
    setMessages((prev) => prev.map((m, i) => (i === prev.length - 1 && m.role === "user" ? { ...m, stopped: true } : m)));
    setLoading(false);
  }

  // Retry or Edit on a stopped question: it is removed and sent again (with its files).
  function resend(index, query) {
    if (loading) return;
    const question = messages[index];
    setMessages((prev) => prev.filter((_, i) => i !== index));
    send(query, question.attachments || []);
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
    stopEditing(true);
    setUserType(null);
    setAgentKey(null);
    setConversationId(null);
    setMessages([]);
    setAttachments([]);
    setError("");
  }

  // Another assistant from the sidebar (or "New chat" with the same one): a new conversation.
  async function switchTo(agentId) {
    if (loading) return;
    stopEditing(true);
    setMessages([]);
    setAttachments([]);
    await choose(userType, agentId);
  }

  if (!conversationId) {
    return <StartScreen onChoose={choose} loading={loading} error={error} initialAgent={initialAgent} />;
  }

  const university = tenant();
  const visible = assistantsFor(userType);
  return (
    <div className="tapp">
      <aside className="tside">
        <div className="tbrand">
          {university.logo_url
            ? <span className="tlogo image"><img src={university.logo_url} alt="" /></span>
            : <span className="tlogo">{initials()}</span>}
          <div><b>{university.name}</b><small>AI Assistants</small></div>
        </div>
        <div className="tstripe" />
        <span className="lbl">{visible.length} assistant{visible.length === 1 ? "" : "s"} for {audienceTitle(userType)}</span>
        <nav className="tagents" aria-label="Assistants">
          {visible.map((a) => (
            <button key={a.id} type="button" className="tagent" aria-current={a.id === agent.id} disabled={loading}
                    onClick={() => a.id !== agent.id && switchTo(a.id)}>{a.name}</button>
          ))}
        </nav>
        <div className="tuser">
          <span>Using the chat as {audienceTitle(userType).toLowerCase()}</span>
          <span><button type="button" className="tlink" onClick={newChat}>Change</button></span>
        </div>
      </aside>

      <div className="tmain">
        <header className="thead">
          <div><h3>{agent.name}</h3><p>{agent.subtitle || agent.summary}</p></div>
          <div className="thead-actions">
            <span className="lang" title="Ask in English or Arabic">EN · ع</span>
            <button type="button" className="tbtn ghost" onClick={() => switchTo(agent.id)} disabled={loading}>New chat</button>
          </div>
        </header>

        {calling && (
          <CallScreen onAsk={(question) => send(question)} onHangUp={() => setCalling(false)} agentName={agent.name} />
        )}

        <main className="tbody">
          <div className="tbody-inner">
            {messages.length === 0 && (
              <>
                <div className="mrow">
                  <div className="msg a">
                    <span className="text">Hi! I'm the {agent.name} at {university.short_name}. {agent.welcome}</span>
                    {canCv && (
                      <span><button type="button" className="tbtn" onClick={analyzeCv} disabled={loading}>📄 Analyze my CV</button></span>
                    )}
                  </div>
                </div>
                <div className="chips">
                  {agent.examples.map((question) => (
                    <button key={question} type="button" className="chip" onClick={() => send(question)}>{question}</button>
                  ))}
                </div>
              </>
            )}
            {messages.map((message, index) => (
              <Message key={index} message={message} onRate={handleRate} busy={loading}
                       onResend={(query) => resend(index, query)} />
            ))}
            {loading && (
              <div className="mrow">
                <div className="msg a">
                  <div className="typing-dots"><span /><span /><span /></div>
                  {withFile && <p className="slow-note">Working on your file… Editing or restructuring a document can take a minute.</p>}
                  {slow && !withFile && (
                    <p className="slow-note">Still working… The free online models seem busy, so a backup model on this computer
                      is answering. This can take up to a minute. You can press Stop to edit your message.</p>
                  )}
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </main>

        <footer className="tfoot">
          {error && <p className="error">{error}</p>}
          {activeDoc && (
            <div className="doc-bar">
              <span className="doc-bar-text">
                📝 <b>{activeDoc.download_name}</b>
                <span className="muted"> · ask for more changes, e.g. "make it shorter"</span>
              </span>
              <a className="doc-view" href={activeDoc.view_url} target="_blank" rel="noreferrer">View</a>
              <a className="doc-download" href={activeDoc.url} download={activeDoc.download_name}>Download</a>
              <button type="button" className="secondary" onClick={() => stopEditing()} disabled={loading}
                      title="Stop working on this document">Close</button>
            </div>
          )}
          {attachments.length > 0 && (
            <div className="pending-files">
              {attachments.map((file, index) => (
                <div className="pending-file" key={index}>
                  {file.isImage ? <img src={file.dataUrl} alt="" /> : <span className="file-icon">📄</span>}
                  <span className="pending-name">{file.filename}</span>
                  <button type="button" aria-label={`Remove ${file.filename}`}
                          onClick={() => setAttachments((prev) => prev.filter((_, i) => i !== index))}>×</button>
                </div>
              ))}
            </div>
          )}
          <form className="tinput" onSubmit={handleSubmit}>
            <input ref={fileInputRef} type="file" accept={accepted} onChange={handleFilesChosen} multiple hidden />
            {/* "+": add files, and with the cv skill also "Analyze my CV" */}
            {(accepted || canCv) && <div className="plus-menu-wrap" ref={menuRef}>
              <button type="button" className="tbtn ghost" onClick={() => setMenuOpen((open) => !open)}
                      title="Add files and more" aria-label="Add files and more" aria-expanded={menuOpen}>＋</button>
              {menuOpen && (
                <div className="plus-menu" role="menu">
                  {accepted && <button type="button" role="menuitem" onClick={pickFiles}>
                    <span className="plus-menu-icon">📎</span>
                    <span>Upload files<small>{hasSkill(agent, "files")
                      ? `PDF, Word, Excel, PowerPoint, TXT${hasSkill(agent, "images") ? " or pictures" : ""}`
                      : "Pictures"} (up to {MAX_FILES})</small></span>
                  </button>}
                  {canCv && (
                    <button type="button" role="menuitem" onClick={analyzeCv} disabled={loading}>
                      <span className="plus-menu-icon">📄</span>
                      <span>Analyze my CV<small>Upload your CV and get concrete improvements</small></span>
                    </button>
                  )}
                </div>
              )}
            </div>}
            <input
              className="box"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={attachments.length
                ? `Ask about your file${attachments.length > 1 ? "s" : ""}, or say what to change (e.g. "restructure my CV")...`
                : agent.placeholder || `Ask ${agent.name} anything…`}
              aria-label="Your message"
              maxLength={1000}
              dir="auto"
              autoFocus
            />
            {callSupported && hasSkill(agent, "voice") && (
              <button type="button" className="tbtn ghost" onClick={() => setCalling(true)}
                      title="Talk to the assistant by voice" aria-label="Start a voice call">📞</button>
            )}
            {/* Different keys make these two separate buttons. With one shared button, a
                click on Stop turned it back into Send during the click, and the browser
                then sent the question again. */}
            {loading ? (
              <button key="stop" type="button" className="tbtn dark" onClick={stop} title="Stop and edit your message">Stop</button>
            ) : (
              <button key="send" type="submit" className="tbtn" disabled={!input.trim() && attachments.length === 0}>Send</button>
            )}
          </form>
        </footer>
      </div>
    </div>
  );
}
