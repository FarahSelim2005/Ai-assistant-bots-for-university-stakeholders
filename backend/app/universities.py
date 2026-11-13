"""Making a new university: the console's "Add by hand" wizard and the public sign-up both use
create(), so a university is made the same way by either.

In one transaction (the caller's connection, the owner's): the university (name, look, plan),
its address, its assistants (their own, or from a ready-made template) each in its own
folder, and its first admin. Anything refused raises HTTPException and nothing is kept.
"""
import re
import uuid

from fastapi import HTTPException

from app.agents.templates import skills_for

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
LOGO = re.compile(r"^(data:image/(png|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/=]+|/[\w./-]+|https://\S+)$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_AUDIENCES = '[{"key": "student", "title": "Student", "text": ""}, {"key": "staff", "title": "Staff", "text": ""}]'
# Addresses no university may take (the platform's own, and common words)
RESERVED_SLUGS = {"www", "console", "api", "admin", "app", "signup", "billing", "checkout", "mail", "static",
                  "assets", "help", "support", "status", "docs", "login", "platform", "test"}


def default_host(slug: str) -> str:
    return f"{slug}.localhost"


def address_problem(conn, slug: str, host: str | None = None) -> str | None:
    """Why this subdomain (and host) cannot be used, or None."""
    if not SLUG.match(slug):
        return "The address may only have lower case letters, digits and -, up to 40."
    if slug in RESERVED_SLUGS:
        return f"The address '{slug}' is reserved. Try another."
    if conn.execute("SELECT 1 FROM tenants WHERE slug = %s", (slug,)).fetchone():
        return f"The address '{slug}' is taken. Try another."
    if conn.execute("SELECT 1 FROM tenant_domains WHERE host = %s", (host or default_host(slug),)).fetchone():
        return f"The address {host or default_host(slug)} is taken."
    return None


def create(conn, *, name: str, short_name: str, slug: str, host: str | None, plan: str, assistants: list[dict],
           admin_email: str, admin_name: str, password_hash: str, brand_primary: str = "#1f4e79",
           brand_accent: str = "#e8a317", brand_dark: str = "#1a1a1a", logo_url: str | None = None,
           status: str = "active", email_domain: str | None = None, signed_up: bool = False,
           reserved_too: bool = False) -> tuple[uuid.UUID, str]:
    """Make the university; returns (its id, its host). assistants: [{name, description,
    template_key}]. reserved_too: also refuse the reserved addresses (the public sign-up)."""
    slug = slug.strip().lower()
    host = (host or default_host(slug)).strip().lower()
    email = admin_email.strip().lower()
    if not SLUG.match(slug):
        raise HTTPException(400, "The subdomain may only have lower case letters, digits and -, up to 40.")
    if reserved_too and slug in RESERVED_SLUGS:
        raise HTTPException(409, f"The address '{slug}' is reserved. Try another.")
    if not HOST.match(host):
        raise HTTPException(400, "That is not a host name (for example demo.localhost or chat.uni.edu).")
    for colour in (brand_primary, brand_accent, brand_dark):
        if not COLOUR.match(colour):
            raise HTTPException(400, "Colours are written like #c4161c.")
    if logo_url and not LOGO.match(logo_url):
        raise HTTPException(400, "The logo must be a PNG, JPEG, WebP or SVG picture.")
    if not re.match(r"^[^@\s]+@[^@\s]+$", email):
        raise HTTPException(400, "The admin's email is not an email address.")
    if any(not (a.get("name") or "").strip() for a in assistants):
        raise HTTPException(400, "Every assistant needs a name.")
    templates = [a["template_key"] for a in assistants if a.get("template_key")]
    max_assistants = conn.execute("SELECT max_assistants FROM plans WHERE key = %s", (plan,)).fetchone()
    if max_assistants is None:
        raise HTTPException(400, f"Unknown plan '{plan}'.")
    if max_assistants[0] is not None and len(assistants) > max_assistants[0]:
        raise HTTPException(400, f"The {plan} plan allows {max_assistants[0]} assistants.")
    known = {k for (k,) in conn.execute("SELECT key FROM agent_templates WHERE key = ANY(%s)", (templates,))}
    if set(templates) - known:
        raise HTTPException(400, f"Unknown assistants: {', '.join(sorted(set(templates) - known))}.")
    if conn.execute("SELECT 1 FROM tenants WHERE slug = %s", (slug,)).fetchone():
        raise HTTPException(409, f"The subdomain '{slug}' is taken.")
    if conn.execute("SELECT 1 FROM tenant_domains WHERE host = %s", (host,)).fetchone():
        raise HTTPException(409, f"The address {host} is taken.")
    if conn.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone():
        raise HTTPException(409, "This email address already has an account.")
    if email_domain and conn.execute("SELECT 1 FROM tenants WHERE email_domain = %s", (email_domain,)).fetchone():
        raise HTTPException(409, f"A university with @{email_domain} addresses is already signed up.")
    tenant_id = conn.execute(
        "INSERT INTO tenants (slug, name, short_name, plan, brand_primary, brand_accent, brand_dark, logo_url, audiences, "
        "                     status, email_domain, signed_up_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END) RETURNING id",
        (slug, name.strip(), short_name.strip(), plan, brand_primary, brand_accent, brand_dark, logo_url or None,
         DEFAULT_AUDIENCES, status, email_domain, signed_up)).fetchone()[0]
    conn.execute("INSERT INTO tenant_domains (host, tenant_id, is_primary) VALUES (%s, %s, true)", (host, tenant_id))
    # Its assistants, in the order given: a template's settings with the name (and what it
    # handles) chosen here, or a new one from just its name and what it handles. Every one gets
    # all the skills (files, pictures, CV rewrites, editor, voice; no campus map: a new
    # university has none yet). Each gets its own folder.
    skills = skills_for(campus_map=False)
    folders: set[str] = set()
    for position, assistant in enumerate(assistants, start=1):
        name_, description, template_key = assistant["name"].strip(), (assistant.get("description") or "").strip(), assistant.get("template_key")
        folder = unique_folder(template_key or name_, folders)
        if template_key:
            conn.execute("""
                INSERT INTO agents (tenant_id, template_key, name, summary, subtitle, description, audiences,
                                    answer_mode, prompt_mode, instructions, fallback_en, fallback_ar, welcome,
                                    placeholder, examples, skills, max_answer_tokens, position, folder)
                SELECT %s, key, CASE WHEN %s = key THEN name ELSE %s END,
                       CASE WHEN %s = '' THEN summary ELSE %s END, subtitle,
                       CASE WHEN %s = '' THEN description ELSE %s END, audiences, answer_mode, prompt_mode,
                       instructions, fallback_en, fallback_ar, welcome, placeholder, examples,
                       %s, max_answer_tokens, %s, %s
                FROM agent_templates WHERE key = %s""",
                         (tenant_id, name_, name_, description, description, description, description, skills, position,
                          folder, template_key))
        else:
            what = description or f"questions about {name_}"
            conn.execute("""
                INSERT INTO agents (tenant_id, name, summary, description, audiences, answer_mode, instructions,
                                    fallback_en, welcome, skills, position, folder)
                VALUES (%s, %s, %s, %s, '{student,staff}', 'docs', %s, %s, %s, %s, %s, %s)""",
                         (tenant_id, name_, what, what,
                          f"You help {{university}} students and staff with {what[0].lower() + what[1:]}",
                          "Sorry, I don't have information about that. Please contact the relevant {university} office.",
                          "How can I help you? Ask me a question.", skills, position, folder))
    conn.execute("INSERT INTO users (tenant_id, email, name, role, password_hash) VALUES (%s, %s, %s, 'tenant_admin', %s)",
                 (tenant_id, email, admin_name, password_hash))
    return tenant_id, host


# Every table with a university's rows, in an order the foreign keys allow (children first).
# The old `universities` table is not touched.
DELETE_ORDER = ("feedback", "messages", "conversations", "chunks", "usage", "billing_events", "checkouts",
                "signups", "subscriptions", "users", "agents", "tenant_domains")


def delete(conn, tenant_id) -> dict:
    """Delete a university and everything of it, for good (the console's "Delete"; a backup is
    made before, by the caller). Returns how many rows each table lost."""
    removed = {}
    for table in DELETE_ORDER:
        if table == "checkouts":  # also the payment pages of its sign-ups
            sql = ("DELETE FROM checkouts WHERE tenant_id = %s "
                   "OR signup_id IN (SELECT id FROM signups WHERE tenant_id = %s)")
            removed[table] = conn.execute(sql, (tenant_id, tenant_id)).rowcount
        else:
            removed[table] = conn.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant_id,)).rowcount
    removed["tenants"] = conn.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,)).rowcount
    return {k: v for k, v in removed.items() if v}


def unique_folder(name: str, taken: set[str]) -> str:
    """A readable folder name for a new assistant, not yet used by this university's others."""
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "assistant"
    folder, number = base, 1
    while folder in taken:
        number += 1
        folder = f"{base}_{number}"
    taken.add(folder)
    return folder
