// All calls to the backend live here. The backend runs on port 8000 of the same host name
// as this page, so it sees which university is open: giu.localhost:5173 calls
// giu.localhost:8000, demo.localhost:5173 calls demo.localhost:8000 (plain localhost is GIU).
// On a server (built with VITE_API_URL=/api) the backend is behind the same address under /api.
export const API_URL = import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8000`;

// The domain new universities get a subdomain of (<slug>.<domain>), and the address of a
// university's chat. On your own computer: <slug>.localhost and http://<host>:5173.
export const PLATFORM_DOMAIN = import.meta.env.VITE_PLATFORM_DOMAIN || "localhost";
// The platform's own addresses (no university): the console, and the sign-up with its payment page
export const CONSOLE_HOST = `console.${PLATFORM_DOMAIN}`;
export const SIGNUP_HOST = `signup.${PLATFORM_DOMAIN}`;
export function siteUrl(host) {
  return import.meta.env.VITE_PLATFORM_DOMAIN ? `https://${host}` : `http://${host}:5173`;
}

// `signal` (optional) lets the caller cancel the request, e.g. the chat's Stop button.
async function post(path, body, signal) {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // FastAPI sends a string for our own errors and a list for validation errors.
    const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

export function startSession(userType, agent) {
  return post("/session", { user_type: userType, agent }); // -> { conversation_id }
}

// `files` (optional): the attached files, each { filename, dataUrl } where dataUrl is
// "data:<type>;base64,<content>". `documentToken` (optional): the document this chat is working
// on, so a request like "now make it shorter" edits it. The backend decides whether a message
// is an edit or a question.
export function sendMessage(conversationId, query, files = [], signal = undefined, documentToken = null) {
  const body = { conversation_id: conversationId, query, document_token: documentToken };
  if (files.length) {
    body.attachments = files.map((f) => ({ filename: f.filename, data_base64: f.dataUrl.split(",")[1] }));
  }
  return post("/chat", body, signal); // -> { answer, sources, message_id, file?, changes? }
}

export function sendFeedback(messageId, rating) {
  return post("/feedback", { message_id: messageId, rating }); // -> { feedback_id }
}

// Sends a recorded voice question (a Blob from MediaRecorder) to the backend, which
// uses Whisper (Groq, or local as fallback) and detects Arabic or English. -> { text, language }
export async function transcribe(recording) {
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("The recording could not be read."));
    reader.readAsDataURL(recording);
  });
  return post("/transcribe", { audio_base64: dataUrl.split(",")[1], mime_type: recording.type || "audio/webm" });
}

// "Close" the chat's document: the backend deletes its files.
export function closeDocument(conversationId, token) {
  return fetch(`${API_URL}/documents/${conversationId}/${token}`, { method: "DELETE" });
}

// Download links come as paths ("/documents/12/<token>").
export function fileUrl(path) {
  return `${API_URL}${path}`;
}
