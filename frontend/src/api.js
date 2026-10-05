// All calls to the backend live here. Change API_URL if the backend runs elsewhere.
const API_URL = "http://localhost:8000";

async function post(path, body) {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // FastAPI sends a string for our own errors and a list for validation errors.
    const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

export function startSession(userType) {
  return post("/session", { user_type: userType }); // -> { conversation_id }
}

// `attachment` is optional: { filename, dataUrl } where dataUrl is "data:<type>;base64,<content>".
export function sendMessage(conversationId, query, attachment = null) {
  const body = { conversation_id: conversationId, query };
  if (attachment) {
    body.attachment = { filename: attachment.filename, data_base64: attachment.dataUrl.split(",")[1] };
  }
  return post("/chat", body); // -> { answer, sources, message_id }
}

export function sendFeedback(messageId, rating) {
  return post("/feedback", { message_id: messageId, rating }); // -> { feedback_id }
}
