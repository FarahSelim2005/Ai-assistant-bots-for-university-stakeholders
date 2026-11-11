"""Database connection helpers (psycopg 3, raw SQL, no ORM).

Row-level security (migration 003): the tables with tenant data only show and accept rows
whose tenant_id equals the setting app.tenant_id. Every connection with a tenant sets it at
the start of its transaction; without one (finding the tenant from the host, which only
reads tenants and tenant_domains) those tables look empty.
"""
import uuid

import psycopg

from app import config


def get_connection(tenant_id: uuid.UUID | None = None) -> psycopg.Connection:
    """Open a connection as the app's login (DB_USER, the giu_app role) for `tenant_id`.

    Use it as `with get_connection(tenant_id) as conn:` so the transaction is committed on
    success, rolled back on error, and the connection closed. The tenant setting lasts for
    that one transaction (set_config(..., true)), so it can never leak into another request.
    """
    return _connect(config.DB_USER, config.DB_PASSWORD, config.DB_NAME, tenant_id)


def get_admin_connection(tenant_id: uuid.UUID | None = None, dbname: str | None = None) -> psycopg.Connection:
    """The same as the owner of the tables (DB_ADMIN_USER): for migrations and ingest."""
    return _connect(config.DB_ADMIN_USER, config.DB_ADMIN_PASSWORD, dbname or config.DB_NAME, tenant_id)


def use_admin_login() -> None:
    """For command-line scripts: every get_connection() from now on logs in as DB_ADMIN_USER."""
    config.DB_USER, config.DB_PASSWORD = config.DB_ADMIN_USER, config.DB_ADMIN_PASSWORD


def set_tenant(conn: psycopg.Connection, tenant_id: uuid.UUID | None) -> None:
    """Make `tenant_id` the tenant of the connection's current transaction ("" = none)."""
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id) if tenant_id else "",))


def _connect(user: str, password: str, dbname: str, tenant_id: uuid.UUID | None) -> psycopg.Connection:
    conn = psycopg.connect(host=config.DB_HOST, port=config.DB_PORT, dbname=dbname, user=user, password=password)
    if tenant_id is not None:
        try:
            set_tenant(conn, tenant_id)
        except psycopg.Error:
            conn.close()
            raise
    return conn
