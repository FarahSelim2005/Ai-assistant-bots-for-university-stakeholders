// The university this page belongs to (from the backend's GET /tenant, chosen by the host name:
// giu.localhost:5173 is GIU, demo.localhost:5173 is demo, plain localhost is GIU). Loaded once
// before the first render (main.jsx); every screen reads it from here: name, logo, colours,
// start screen texts, audiences, and the live assistants with the skills that work here.
import { API_URL } from "./api.js";

let current = null;

export async function loadTenant() {
  const response = await fetch(`${API_URL}/tenant`).catch(() => null);
  if (!response) throw new Error("The server could not be reached. Is the backend running?");
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Could not load this university (${response.status}).`);
  current = data;
  applyBrand(data);
  return data;
}

export function tenant() {
  return current;
}

// The colours become CSS variables (--brand-primary, --brand-primary-dark, --brand-accent,
// --brand-dark), so the whole page follows the university's look; the title follows its name.
function applyBrand(data) {
  const style = document.documentElement.style;
  style.setProperty("--brand-primary", data.colors.primary);
  style.setProperty("--brand-primary-dark", darker(data.colors.primary));
  style.setProperty("--brand-accent", data.colors.accent);
  style.setProperty("--brand-dark", data.colors.dark);
  document.title = `${data.short_name} Assistants`;
  // The tab icon is the logo the university chose (sign-up or admin page), else its initials on
  // its colour, the same as the page header shows.
  setFavicon(initialsIcon(initials(data), data.colors.primary));
  if (data.logo_url) {
    const logo = new Image();
    logo.onload = () => setFavicon(squareIcon(logo));
    logo.src = data.logo_url;
  }
}

// The logo fitted whole into a square (a tab icon is square): a wide logo is made smaller, not squashed.
function squareIcon(image) {
  const size = 64, canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const scale = size / Math.max(image.width, image.height), w = image.width * scale, h = image.height * scale;
  canvas.getContext("2d").drawImage(image, (size - w) / 2, (size - h) / 2, w, h);
  return canvas.toDataURL("image/png");
}

// The browser tab's icon: the university's own, instead of the platform's UniBots icon.
function setFavicon(href) {
  const link = document.querySelector("link[rel='icon']");
  link.removeAttribute("type");
  link.href = href;
}

// A university without a logo: its initials on its main colour.
function initialsIcon(text, colour) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="${colour}"/>`
    + `<text x="32" y="41" text-anchor="middle" font-family="Arial, sans-serif" font-size="${text.length > 2 ? 22 : 28}" `
    + `font-weight="700" fill="#ffffff">${text.replace(/[<&>"]/g, "")}</text></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

// "#c4161c" -> about 20% darker, for hovered buttons.
function darker(hex) {
  const channels = [1, 3, 5].map((i) => Math.round(parseInt(hex.slice(i, i + 2), 16) * 0.805));
  return `#${channels.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

export function assistantsFor(audience) {
  return (current?.assistants ?? []).filter((assistant) => assistant.audiences.includes(audience));
}

// By id, or by the old key of one of GIU's assistants in old links (/?agent=labs_research).
export function findAssistant(key) {
  const assistants = current?.assistants ?? [];
  return assistants.find((a) => a.id === key) || assistants.find((a) => a.template_key === key) || null;
}

export function hasSkill(assistant, skill) {
  return Boolean(assistant?.skills.includes(skill));
}

export function audienceTitle(key) {
  return current?.audiences.find((audience) => audience.key === key)?.title ?? key;
}

// The short name for a small logo square: "GIU" as it is; a longer one as initials ("Demo University" -> "DU").
export function initials(university = current) {
  const name = university?.short_name || university?.name || "";
  if (name.length <= 4) return name;
  return name.split(/\s+/).filter(Boolean).map((word) => word[0].toUpperCase()).join("").slice(0, 3);
}
