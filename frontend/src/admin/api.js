// All calls to the backend's /admin routes (the university admin) and /console routes (the
// platform console). Every route except login needs the token from login in the
// "Authorization: Bearer <token>" header.
import { API_URL as CHAT_API_URL } from "../api.js";

// VITE_API_URL (in frontend/.env) wins; otherwise the same backend as the chat.
const API_URL = import.meta.env.VITE_API_URL || CHAT_API_URL;

// Thrown when the backend answers 401: the page then shows the login form again.
export class UnauthorizedError extends Error {}

export async function request(path, { method = "GET", token, body } = {}) {
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
  if (response.status === 401 && !path.endsWith("/login")) throw new UnauthorizedError("Please log in again.");
  const data = await response.json().catch(() => ({})); // DELETE may send no body
  if (!response.ok) {
    // FastAPI sends a string for our own errors and a list for validation errors.
    const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

const send = (method) => (path, token, body) => request(path, { method, token, body });
const get = (path, token) => request(path, { token });
const post = send("POST");
const put = send("PUT");
const del = send("DELETE");

// ---- login (this university) -> { token, user: { email, name, role } }
export const login = (email, password) => post("/admin/login", null, { email, password });
export const logout = (token) => post("/admin/logout", token);
export const me = (token) => get("/admin/me", token);

// ---- assistants
export const listAgents = (token) => get("/admin/agents", token);
export const listTemplates = (token) => get("/admin/agent-templates", token);
export const createAgent = (token, values) => post("/admin/agents", token, values); // -> { id }
export const updateAgent = (token, id, values) => put(`/admin/agents/${id}`, token, values);
export const deleteAgent = (token, id) => del(`/admin/agents/${id}`, token);
export const orderAgents = (token, ids) => post("/admin/agents/order", token, { ids });

// ---- branding and users
export const getBranding = (token) => get("/admin/branding", token);
export const updateBranding = (token, values) => put("/admin/branding", token, values);
export const listUsers = (token) => get("/admin/users", token);
export const createUser = (token, values) => post("/admin/users", token, values);
export const updateUser = (token, id, values) => put(`/admin/users/${id}`, token, values);

// ---- documents: { agent, filename, content }; create and update return { id, chunks }
export const listDocuments = (token) => get("/admin/documents", token);
export const getDocument = (token, id) => get(`/admin/documents/${id}`, token);
export const createDocument = (token, doc) => post("/admin/documents", token, doc);
export const updateDocument = (token, id, doc) => put(`/admin/documents/${id}`, token, doc);
export const deleteDocument = (token, id) => del(`/admin/documents/${id}`, token);
