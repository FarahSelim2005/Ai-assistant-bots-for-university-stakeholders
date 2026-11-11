// All calls to the backend's /admin routes. Every route except login needs the token
// from login in the "Authorization: Bearer <token>" header.
import { API_URL as CHAT_API_URL } from "../api.js";

// VITE_API_URL (in frontend/.env) wins; otherwise the same backend as the chat.
const API_URL = import.meta.env.VITE_API_URL || CHAT_API_URL;

// Thrown when the backend answers 401: the page then shows the login form again.
export class UnauthorizedError extends Error {}

async function request(path, { method = "GET", token, body } = {}) {
  let response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("The server could not be reached. Is the backend running?");
  }
  if (response.status === 401) throw new UnauthorizedError("Please log in again.");
  const data = await response.json().catch(() => ({})); // DELETE may send no body
  if (!response.ok) {
    // FastAPI sends a string for our own errors and a list for validation errors.
    const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail;
    // FastAPI's own 404 ("Not Found"): the backend does not have this route (yet).
    if (response.status === 404 && (!detail || detail === "Not Found")) {
      throw new Error(`The backend does not have this admin route yet (${method} ${path}).`);
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

export function login(password) {
  return request("/admin/login", { method: "POST", body: { password } }); // -> { token }
}

// This university's assistants: [{id, name, folder, ...}]
export function listAgents(token) {
  return request("/admin/agents", { token });
}

export function listDocuments(token) {
  return request("/admin/documents", { token }); // -> [{ id, agent, filename, updated_at }]
}

export function getDocument(token, id) {
  return request(`/admin/documents/${id}`, { token }); // -> { id, agent, filename, content }
}

// `doc` is { agent, filename, content }. Both return { id, chunks }.
export function createDocument(token, doc) {
  return request("/admin/documents", { method: "POST", token, body: doc });
}

export function updateDocument(token, id, doc) {
  return request(`/admin/documents/${id}`, { method: "PUT", token, body: doc });
}

export function deleteDocument(token, id) {
  return request(`/admin/documents/${id}`, { method: "DELETE", token });
}
