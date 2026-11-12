"""The public sign-up (the design's "Sign up (public)"): a university creates its chatbot and
subscribes without the platform owner.

GET  /signup/plans             the public plans (price in EGP) and the ready-made assistants
GET  /signup/address/{slug}    {available, problem}: is <slug>.localhost free?
POST /signup                   {plan, person, email, password} -> {id}: emails a 6-digit code
POST /signup/{id}/code         send a new code
POST /signup/{id}/verify       {code}
POST /signup/{id}/subscribe    {plan, university, short_name, slug, brand_primary, logo_url?, assistants}
                               -> trial: the university is made at once; paid: {checkout_url}
GET  /signup/{id}              where the sign-up is: done (with the addresses and a one-time
                               login link), waiting for review, at the payment page, or not yet

Rules: a university email (personal addresses such as Gmail are refused) proved with a code
(only its hash is stored; it works for SIGNUP_CODE_MINUTES and SIGNUP_CODE_TRIES tries); one
university per email domain, so one trial per domain; reserved and taken addresses refused;
at most SIGNUPS_PER_IP_PER_HOUR sign-ups from one address. The sign-up id (random) is what
the browser keeps; whoever has it can continue that sign-up.

These routes work on any host and use the owner's connection (platform tables).
"""
import hashlib
import logging
import re
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app import auth, config, mail, tenants, universities
from app.billing import service
from app.db import get_admin_connection

router = APIRouter(prefix="/signup")
log = logging.getLogger("uvicorn.error")

PERSONAL_DOMAINS = re.compile(r"^(gmail|googlemail|yahoo|ymail|rocketmail|hotmail|outlook|live|msn|icloud|me|mac|aol|"
                              r"proton|protonmail|pm|yandex|mail|gmx|zoho|inbox|tutanota)\.", re.I)
ACCENT, DARK = "#e5e7eb", "#1d2027"  # the second colour and the sidebar of a new university


class StartIn(BaseModel):
    plan: str = Field(min_length=1, max_length=30)
    person: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)


class AssistantDraft(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=600)
    template_key: str | None = Field(default=None, max_length=40)


class DraftIn(BaseModel):
    plan: str = Field(min_length=1, max_length=30)
    university: str = Field(min_length=2, max_length=120)
    short_name: str = Field(min_length=1, max_length=12)
    slug: str = Field(min_length=1, max_length=40)
    brand_primary: str = "#1f4e79"
    logo_url: str | None = Field(default=None, max_length=400_000)
    assistants: list[AssistantDraft] = Field(min_length=1, max_length=50)


def code_hash(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def signup_row(conn, signup_id: str, lock: bool = False):
    try:
        uuid.UUID(signup_id)
    except ValueError:
        raise HTTPException(404, "This sign-up does not exist. Please start again.")
    row = conn.execute("SELECT id, email, email_domain, person, plan_key, verified_at, tenant_id, draft, code_sent_at, "
                       "codes_sent, created_at FROM signups WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                       (signup_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "This sign-up does not exist. Please start again.")
    return row


def domain_problem(conn, domain: str) -> str | None:
    if conn.execute("SELECT 1 FROM tenants WHERE email_domain = %s", (domain,)).fetchone():
        return (f"A university with @{domain} addresses already has a chatbot. Ask its admin to add you as a "
                "colleague on its admin page.")
    return None


def send_code(conn, signup_id, email: str) -> None:
    """A new 6-digit code: its hash is stored, the code itself is emailed (or logged)."""
    code = f"{secrets.randbelow(10 ** 6):06d}"
    salt = secrets.token_hex(8)
    conn.execute("UPDATE signups SET code_hash = %s, code_salt = %s, code_tries = 0, codes_sent = codes_sent + 1, "
                 "code_sent_at = now(), code_expires_at = now() + make_interval(mins => %s) WHERE id = %s",
                 (code_hash(salt, code), salt, config.SIGNUP_CODE_MINUTES, signup_id))
    try:
        mail.send(email, f"Your sign-up code: {code}",
                  f"Your code is {code}\n\nEnter it on the sign-up page to confirm your email address. It works for "
                  f"{config.SIGNUP_CODE_MINUTES} minutes.\n\nIf you did not start a sign-up, you can ignore this email.")
    except mail.MailError as error:
        raise HTTPException(502, str(error))


# ---------------------------------------------------------------- routes

@router.get("/plans")
def public_plans():
    with get_admin_connection() as conn:
        plans = service.plans(conn, public_only=True)
        templates = conn.execute("SELECT key, name, summary FROM agent_templates ORDER BY position").fetchall()
    return {"plans": plans, "templates": [{"key": k, "name": n, "summary": s} for k, n, s in templates]}


@router.get("/address/{slug}")
def address(slug: str):
    with get_admin_connection() as conn:
        problem = universities.address_problem(conn, slug.strip().lower())
    return {"available": problem is None, "problem": problem, "host": universities.default_host(slug.strip().lower())}


@router.post("")
def start(body: StartIn, request: Request):
    email = body.email.strip().lower()
    if not universities.EMAIL.match(email):
        raise HTTPException(400, "Enter your university email address.")
    domain = email.rsplit("@", 1)[1]
    if PERSONAL_DOMAINS.match(domain):
        raise HTTPException(400, "Use your university email, not a personal one. It proves you work there.")
    problem = auth.password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    client_ip = request.client.host if request.client else ""
    with get_admin_connection() as conn:
        chosen = service.plan(conn, body.plan)
        if chosen is None or not chosen["public"]:
            raise HTTPException(400, "Choose one of the plans.")
        problem = domain_problem(conn, domain)
        if problem:
            raise HTTPException(409, problem)
        if conn.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone():
            raise HTTPException(409, "This email address already has an account. Log in on your university's admin page.")
        recent = conn.execute("SELECT count(*) FROM signups WHERE client_ip = %s AND created_at > now() - interval '1 hour'",
                              (client_ip,)).fetchone()[0]
        if recent >= config.SIGNUPS_PER_IP_PER_HOUR:
            raise HTTPException(429, "Too many sign-ups from your network. Please try again in an hour.")
        signup_id = conn.execute(
            "INSERT INTO signups (email, email_domain, person, password_hash, plan_key, client_ip) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (email, domain, body.person.strip(), auth.hash_password(body.password), body.plan, client_ip)).fetchone()[0]
        send_code(conn, signup_id, email)
    log.info("Sign-up started for @%s", domain)
    return {"id": str(signup_id), "email": email, "domain": domain}


@router.post("/{signup_id}/code")
def new_code(signup_id: str):
    with get_admin_connection() as conn:
        row = signup_row(conn, signup_id, lock=True)
        if row[5]:
            return {"ok": True, "verified": True}
        if row[9] >= config.SIGNUP_CODES_PER_SIGNUP:
            raise HTTPException(429, "Too many codes for this sign-up. Please start again.")
        waited = conn.execute("SELECT %s IS NULL OR now() - %s >= make_interval(secs => %s)",
                              (row[8], row[8], config.SIGNUP_CODE_RESEND_SECONDS)).fetchone()[0]
        if not waited:
            raise HTTPException(429, "Please wait a minute before asking for another code.")
        send_code(conn, row[0], row[1])
    return {"ok": True}


@router.post("/{signup_id}/verify")
def verify(signup_id: str, body: CodeIn):
    code = re.sub(r"\s", "", body.code)
    with get_admin_connection() as conn:
        row = signup_row(conn, signup_id, lock=True)
        if row[5]:
            return {"verified": True}
        stored = conn.execute("SELECT code_hash, code_salt, code_tries, code_expires_at <= now() FROM signups WHERE id = %s",
                              (row[0],)).fetchone()
        hashed, salt, tries, expired = stored
        if hashed is None or expired:
            raise HTTPException(400, "This code has expired. Ask for a new one.")
        if tries >= config.SIGNUP_CODE_TRIES:
            raise HTTPException(400, "Too many wrong tries. Ask for a new code.")
        wrong = not (re.fullmatch(r"\d{6}", code) and secrets.compare_digest(code_hash(salt, code), hashed))
        if wrong:  # the try counts: saved when this block ends, before the error is raised
            conn.execute("UPDATE signups SET code_tries = code_tries + 1 WHERE id = %s", (row[0],))
        else:
            conn.execute("UPDATE signups SET verified_at = now(), code_hash = NULL WHERE id = %s", (row[0],))
    if wrong:
        left = config.SIGNUP_CODE_TRIES - tries - 1
        raise HTTPException(400, f"That code is not right. {left} {'try' if left == 1 else 'tries'} left."
                            if left else "That code is not right. Ask for a new code.")
    return {"verified": True}


@router.post("/{signup_id}/subscribe")
def subscribe(signup_id: str, body: DraftIn):
    slug = body.slug.strip().lower()
    with get_admin_connection() as conn:
        row = signup_row(conn, signup_id, lock=True)
        if row[6]:
            raise HTTPException(409, "This university is already made.")
        if not row[5]:
            raise HTTPException(400, "Confirm your email address with the code first.")
        chosen = service.plan(conn, body.plan)
        if chosen is None or not chosen["public"]:
            raise HTTPException(400, "Choose one of the plans.")
        if chosen["max_assistants"] is not None and len(body.assistants) > chosen["max_assistants"]:
            raise HTTPException(400, f"The {chosen['name']} plan allows {chosen['max_assistants']} assistants. "
                                     "Remove some or choose a bigger plan.")
        problem = universities.address_problem(conn, slug) or domain_problem(conn, row[2])
        if problem:
            raise HTTPException(409, problem)
        if not universities.COLOUR.match(body.brand_primary):
            raise HTTPException(400, "Choose a colour.")
        if body.logo_url and not universities.LOGO.match(body.logo_url):
            raise HTTPException(400, "The logo must be a PNG, JPEG, WebP or SVG picture.")
        draft = {"university": body.university.strip(), "short_name": body.short_name.strip(), "slug": slug,
                 "brand_primary": body.brand_primary, "brand_accent": ACCENT, "brand_dark": DARK,
                 "logo_url": body.logo_url or None, "assistants": [a.model_dump() for a in body.assistants]}
        conn.execute("UPDATE signups SET plan_key = %s, draft = %s WHERE id = %s", (body.plan, Jsonb(draft), row[0]))
        if chosen["price_egp"] == 0:  # the free trial: no payment, made now
            if service.create_from_signup(conn, row[0]) is None:
                raise HTTPException(409, "Your university could not be made. Please check the address and try again.")
            done = True
            url = None
        else:
            done = False
            url = service.open_checkout(conn, "signup", body.plan, signup_id=row[0], university=draft["university"])
    if done:
        tenants._by_host.clear()
    return {"done": done, "checkout_url": url}


@router.get("/{signup_id}")
def status(signup_id: str):
    with get_admin_connection() as conn:
        row = signup_row(conn, signup_id)
        _, email, domain, person, plan_key, verified, tenant_id, draft, _, _, _ = row
        out = {"email": email, "domain": domain, "plan": plan_key, "verified": bool(verified),
               "university": draft.get("university"), "slug": draft.get("slug"), "error": draft.get("error"),
               "state": "account" if not verified else "draft"}
        if tenant_id is None:
            checkout = conn.execute("SELECT status FROM checkouts WHERE signup_id = %s ORDER BY created_at DESC LIMIT 1",
                                    (row[0],)).fetchone()
            if checkout:
                out["state"] = {"open": "checkout", "failed": "payment_failed", "paid": "error"}[checkout[0]]
            return out
        t_status, host = conn.execute("SELECT t.status, d.host FROM tenants t JOIN tenant_domains d ON d.tenant_id = t.id "
                                      "AND d.is_primary WHERE t.id = %s", (tenant_id,)).fetchone()
        user_id = conn.execute("SELECT id FROM users WHERE tenant_id = %s AND email = %s", (tenant_id, email)).fetchone()
        assistants = conn.execute("SELECT count(*) FROM agents WHERE tenant_id = %s AND deleted_at IS NULL",
                                  (tenant_id,)).fetchone()[0]
        recent = conn.execute("SELECT %s > now() - interval '1 day'", (row[10],)).fetchone()[0]
    url = f"http://{host}:5173"
    out.update({"state": "review" if t_status == "review" else "done", "host": host, "url": url,
                "admin_url": f"{url}/admin", "assistants": assistants})
    if t_status == "active" and user_id and recent:
        out["login_url"] = f"{url}/admin#ticket={auth.issue_ticket(user_id[0], tenant_id)}"
    return out
