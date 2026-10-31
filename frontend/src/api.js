// All calls to the backend live here. Change API_URL if the backend runs elsewhere.
export const API_URL = "http://localhost:8000";

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

// `attachment` is optional: { filename, dataUrl } where dataUrl is "data:<type>;base64,<content>".
export function sendMessage(conversationId, query, attachment = null, signal = undefined) {
  const body = { conversation_id: conversationId, query };
  if (attachment) {
    body.attachment = { filename: attachment.filename, data_base64: attachment.dataUrl.split(",")[1] };
  }
  return post("/chat", body, signal); // -> { answer, sources, message_id }
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

// Document editor. `document` (optional) is a new file { filename, dataUrl } to edit; without
// it the chat's current document is edited again, which needs its `token` (only this browser
// has it). -> { answer, file: { filename, download_name, url, version }, changes, message_id }
export function editDocument(conversationId, instruction, document = null, token = null, signal = undefined) {
  const body = { conversation_id: conversationId, instruction, document_token: token };
  if (document) {
    body.document = { filename: document.filename, data_base64: document.dataUrl.split(",")[1] };
  }
  return post("/documents/edit", body, signal);
}

// "Stop editing": the backend deletes the document's files.
export function closeDocument(conversationId, token) {
  return fetch(`${API_URL}/documents/${conversationId}/${token}`, { method: "DELETE" });
}

// Download links come as paths ("/documents/12/<token>").
export function fileUrl(path) {
  return `${API_URL}${path}`;
}
