"""Logins: email + password per user (the users table, migration 007).

Roles: "tenant_admin" (everything of its university: assistants, documents, branding, users),
"editor" (its university's documents) and "platform_owner" (the platform console, /console).
University users log in on their university's host (the tenant of the request); platform
owners have no university and are read with the owner connection, never by the app's role.

Passwords are stored as scrypt hashes (Python's standard library). A login gives a random
token for the "Authorization: Bearer <token>" header; tokens live in memory for
ADMIN_TOKEN_HOURS (a restart logs everyone out) and only work for the university (or the
console) they were issued for.
"""
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from app import config, tenants
from app.db import get_admin_connection, get_connection

TENANT_ROLES = ("tenant_admin", "editor")
PLATFORM_OWNER = "platform_owner"
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


@dataclass(frozen=True)
class Session:
    user_id: uuid.UUID
    email: str
    name: str
    role: str
    tenant_id: uuid.UUID | None  # None: a platform owner
    expiry: float


_sessions: dict[str, Session] = {}


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        mine = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), dklen=32, n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(mine.hex(), digest)


def password_problem(password: str) -> str | None:
    """Why a new password is not accepted (None: it is fine)."""
    if len(password) < 10:
        return "The password must have at least 10 characters."
    return None


# ---------------------------------------------------------------- logging in

USER_COLUMNS = "id, email, name, role, tenant_id, password_hash, active"


def log_in(email: str, password: str, console: bool = False) -> tuple[str, Session] | None:
    """A token and its session for a correct email and password, else None. University users
    log in on their university's host; platform owners on the console."""
    email = email.strip().lower()
    if console:
        with get_admin_connection() as conn:
            row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE email = %s AND role = %s",
                               (email, PLATFORM_OWNER)).fetchone()
    else:
        tenant_id = tenants.current_id()
        with get_connection(tenant_id) as conn:
            row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE email = %s AND tenant_id = %s",
                               (email, tenant_id)).fetchone()
    if row is None:
        check_password(password, hash_password("not a user"))  # same time as a wrong password
        return None
    user_id, email, name, role, tenant_id, password_hash, active = row
    if not active or not check_password(password, password_hash):
        return None
    with (get_admin_connection() if console else get_connection(tenant_id)) as conn:
        conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
    return new_session(user_id, email, name, role, tenant_id)


def new_session(user_id, email: str, name: str, role: str, tenant_id) -> tuple[str, Session]:
    now = time.time()
    for token, session in list(_sessions.items()):  # forget expired sessions
        if session.expiry < now:
            del _sessions[token]
    token = secrets.token_urlsafe(32)
    _sessions[token] = Session(user_id, email, name, role, tenant_id, now + config.ADMIN_TOKEN_HOURS * 3600)
    return token, _sessions[token]


# One-time login links: after the public sign-up, the new admin is logged in on the new
# university's address (another site, so the sign-up page cannot hand over a session). A
# ticket works once, for TICKET_SECONDS, and only on its own university's host.
TICKET_SECONDS = 600
_tickets: dict[str, tuple[uuid.UUID, uuid.UUID, float]] = {}  # ticket -> (user id, tenant id, expiry)


def issue_ticket(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    now = time.time()
    for ticket, (_, _, expiry) in list(_tickets.items()):
        if expiry < now:
            del _tickets[ticket]
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (user_id, tenant_id, now + TICKET_SECONDS)
    return ticket


def redeem_ticket(ticket: str) -> tuple[str, Session] | None:
    """A session for a valid ticket of this request's university (the ticket is used up)."""
    found = _tickets.pop(ticket, None)
    if found is None or found[2] < time.time() or found[1] != tenants.current_id():
        return None
    with get_connection(found[1]) as conn:
        row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = %s AND tenant_id = %s",
                           (found[0], found[1])).fetchone()
        if row is None or not row[6]:
            return None
        conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (found[0],))
    return new_session(row[0], row[1], row[2], row[3], row[4])


def log_out(token: str) -> None:
    _sessions.pop(token, None)


def session_of(authorization: str) -> Session | None:
    session = _sessions.get(authorization.removeprefix("Bearer ").strip())
    return session if session and session.expiry > time.time() else None


# ---------------------------------------------------------------- route dependencies

def university_user(authorization: str = Header(default="")) -> Session:
    """A logged-in user of this request's university (any role)."""
    session = session_of(authorization)
    if session is None or session.role not in TENANT_ROLES or session.tenant_id != tenants.current_id():
        raise HTTPException(401, "Please log in again.")
    return session


def tenant_admin(session: Session = Depends(university_user)) -> Session:
    """A tenant_admin of this request's university."""
    if session.role != "tenant_admin":
        raise HTTPException(403, "Only a university admin can do this.")
    return session


def platform_owner(authorization: str = Header(default="")) -> Session:
    """A logged-in platform owner (the console). With APP_ENV=development (your own computer)
    no login is needed: the console opens directly. On a server it always needs one."""
    session = session_of(authorization)
    if session is not None and session.role == PLATFORM_OWNER:
        return session
    if config.is_development():
        return Session(uuid.UUID(int=0), "development", "Development", PLATFORM_OWNER, None, time.time() + 3600)
    raise HTTPException(401, "Please log in again.")
