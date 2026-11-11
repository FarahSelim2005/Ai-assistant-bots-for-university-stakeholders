"""Tenants (universities): which one a request is for, and the tenant of the current request.

A request's tenant comes from its host name: the tenant_domains table maps hosts such as
"giu.localhost" or plain "localhost" to a tenant. Only with APP_ENV=development, an
"X-Tenant: <slug>" header wins over the host, for tests and tools like curl.

TenantMiddleware keeps the tenant in a context variable for the whole request, so the
database code deep inside the agents (retriever, ingest) filters by it without passing it
through every function. Scripts and tests set it with `using(tenant)`.
"""
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

import psycopg
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from app import config
from app.db import get_connection

CACHE_SECONDS = 60     # a new or changed host works after at most a minute
CACHE_MAX_HOSTS = 1000  # unknown hosts are cached too; this keeps the cache small
OPEN_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}  # no tenant needed


@dataclass(frozen=True)
class Tenant:
    id: uuid.UUID
    slug: str    # also the subdomain, e.g. "giu"
    name: str
    status: str = "active"
    short_name: str = ""         # e.g. "GIU": used in prompts and texts ("{university}")
    has_cv_model: bool = False   # a CV model trained on its CV templates: the "cv" skill works
    campus_map: bool = False     # campus buildings, rooms and map: the "map" skill works (GIU only)

    @property
    def short(self) -> str:
        """The short name, or the full name when it has none."""
        return self.short_name or self.name


_current: ContextVar[Tenant | None] = ContextVar("tenant", default=None)
_by_host: dict[str, tuple[float, Tenant | None]] = {}  # host -> (expiry, tenant or None)


def current() -> Tenant:
    """The tenant of this request (or of `using(...)` in a script or test)."""
    tenant = _current.get()
    if tenant is None:
        raise RuntimeError("No tenant is set: requests get one from TenantMiddleware, scripts use tenants.using().")
    return tenant


def current_id() -> uuid.UUID:
    return current().id


def current_or_none() -> Tenant | None:
    """The tenant of this request or script, or None outside one (low-level code that also
    runs without a tenant, such as the model client)."""
    return _current.get()


@contextmanager
def using(tenant: Tenant):
    """Run the code inside `with using(tenant):` as that tenant."""
    token = _current.set(tenant)
    try:
        yield tenant
    finally:
        _current.reset(token)


def data_dir(tenant: Tenant) -> Path:
    """The tenant's document folder (one subfolder per agent). GIU's stay in data/raw/."""
    return config.RAW_DATA_DIR if tenant.slug == config.DEFAULT_TENANT else config.TENANTS_DATA_DIR / tenant.slug


# ---------------------------------------------------------------- finding a tenant

TENANT_COLUMNS = "t.id, t.slug, t.name, t.status, t.short_name, t.has_cv_model, t.campus_map"
SELECT_TENANT = f"SELECT {TENANT_COLUMNS} FROM tenants t "


def by_slug(slug: str) -> Tenant | None:
    with get_connection() as conn:
        row = conn.execute(SELECT_TENANT + "WHERE t.slug = %s", (slug.strip().lower(),)).fetchone()
    return Tenant(*row) if row else None


def by_host(host: str) -> Tenant | None:
    """The tenant of a host name (without port), cached for CACHE_SECONDS."""
    now = time.time()
    cached = _by_host.get(host)
    if cached and cached[0] > now:
        return cached[1]
    with get_connection() as conn:
        row = conn.execute(SELECT_TENANT + "JOIN tenant_domains d ON d.tenant_id = t.id WHERE d.host = %s",
                           (host,)).fetchone()
    if len(_by_host) >= CACHE_MAX_HOSTS:
        _by_host.clear()
    _by_host[host] = (now + CACHE_SECONDS, Tenant(*row) if row else None)
    return _by_host[host][1]


def host_name(host_header: str) -> str:
    """"GIU.localhost:8000" -> "giu.localhost", "[::1]:8000" -> "::1"."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.split(":", 1)[0].rstrip(".")


def resolve(host_header: str, tenant_header: str | None) -> Tenant | None:
    """The tenant of a request: the X-Tenant header (development only, ignored otherwise),
    else the host."""
    if tenant_header and config.is_development():
        return by_slug(tenant_header)
    return by_host(host_name(host_header))


def for_script(slug: str) -> Tenant:
    """The tenant a script works on (its --tenant option); stops with a message if unknown."""
    tenant = by_slug(slug)
    if tenant is None:
        raise SystemExit(f"No tenant '{slug}' in the tenants table.")
    return tenant


def use_for_script(slug: str) -> Tenant:
    """Make `slug` the tenant for the rest of a command-line script."""
    tenant = for_script(slug)
    _current.set(tenant)
    return tenant


class TenantMiddleware:
    """Finds the tenant of every HTTP request and sets it for the code that handles it.
    Unknown host -> 404, suspended tenant -> 403. A plain ASGI middleware (not
    BaseHTTPMiddleware), so the chat's "Stop" detection keeps working."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        try:
            tenant = await run_in_threadpool(resolve, headers.get("host", ""), headers.get("x-tenant"))
        except psycopg.Error:
            await JSONResponse({"detail": "The database is not available."}, 503)(scope, receive, send)
            return
        if tenant is None:
            await JSONResponse({"detail": "No university is set up for this address."}, 404)(scope, receive, send)
            return
        if tenant.status != "active":
            await JSONResponse({"detail": f"The {tenant.name} assistant is not available."}, 403)(scope, receive, send)
            return
        with using(tenant):
            await self.app(scope, receive, send)
