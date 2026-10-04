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

export function sendMessage(conversationId, query) {
  return post("/chat", { conversation_id: conversationId, query }); // -> { answer, sources, message_id }
}

export function sendFeedback(messageId, rating) {
  return post("/feedback", { message_id: messageId, rating }); // -> { feedback_id }
}
