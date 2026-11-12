// The public sign-up's and the payment page's calls to the backend (/signup, /billing).
import { API_URL } from "../api.js";

async function request(method, path, body) {
  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  }).catch(() => null);
  if (!response) throw new Error("The server could not be reached. Please try again.");
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

export const getPlans = () => request("GET", "/signup/plans");                    // {plans, templates}
export const checkAddress = (slug) => request("GET", `/signup/address/${encodeURIComponent(slug)}`);
export const startSignup = (body) => request("POST", "/signup", body);            // {id, email, domain}
export const sendNewCode = (id) => request("POST", `/signup/${id}/code`);
export const verifyCode = (id, code) => request("POST", `/signup/${id}/verify`, { code });
export const subscribe = (id, body) => request("POST", `/signup/${id}/subscribe`, body); // {done, checkout_url}
export const signupStatus = (id) => request("GET", `/signup/${id}`);
export const getCheckout = (id) => request("GET", `/billing/checkouts/${id}`);
export const simulatePayment = (id, outcome) => request("POST", `/billing/simulated/checkouts/${id}`, { outcome });

// "EGP 7,500"
export const egp = (amount) => `EGP ${Number(amount || 0).toLocaleString("en")}`;

// What a plan includes, for the plan cards (tokens shown as about how many questions)
export function planFeatures(plan) {
  const questions = plan.monthly_token_cap ? Math.round(plan.monthly_token_cap / 2500 / 100) * 100 : null;
  return [
    plan.max_assistants ? `Up to ${plan.max_assistants} assistant${plan.max_assistants === 1 ? "" : "s"}` : "Unlimited assistants",
    questions ? `About ${questions.toLocaleString("en")} questions a month` : "No monthly limit",
    plan.trial_days ? `${plan.trial_days} days, no card needed` : "Your own address, logo and colours",
    "Answers from your own documents, in English and Arabic",
  ];
}
