"""Usage per university (migration 008): every model call is logged with its tokens, and a
university that has used its plan's monthly token cap gets no more model calls until the next
calendar month (AllowanceUsedUp; the routes answer 429 with a clear message).

The model client (app/llm/client.py) and the embedding client (app/rag/embeddings.py) call
check_allowance() before and record() after each request. Calls outside a university (scripts
without a tenant) are neither checked nor logged. The routes say which assistant a call is
for (for_agent), so the usage can be shown per assistant.
"""
import logging
import uuid
from contextvars import ContextVar

import psycopg

from app import tenants
from app.db import get_connection

log = logging.getLogger("uvicorn.error")
_agent: ContextVar[uuid.UUID | None] = ContextVar("usage_agent", default=None)


class AllowanceUsedUp(Exception):
    """The university has used its plan's tokens for this month."""


def for_agent(agent_id: uuid.UUID | None) -> None:
    """The assistant the following model calls are for (in this request)."""
    _agent.set(agent_id)


def month_usage(tenant_id: uuid.UUID) -> tuple[int, int | None]:
    """(tokens used this calendar month, the plan's monthly cap or None)."""
    with get_connection(tenant_id) as conn:
        used, cap = conn.execute(
            "SELECT (SELECT coalesce(sum(total_tokens), 0) FROM usage WHERE tenant_id = %s "
            "        AND created_at >= date_trunc('month', now())), "
            "       (SELECT p.monthly_token_cap FROM tenants t JOIN plans p ON p.key = t.plan WHERE t.id = %s)",
            (tenant_id, tenant_id)).fetchone()
    return int(used), cap


def check_allowance() -> None:
    """Raise AllowanceUsedUp when the current university is at its monthly cap."""
    tenant = tenants.current_or_none()
    if tenant is None:
        return
    used, cap = month_usage(tenant.id)
    if cap is not None and used >= cap:
        raise AllowanceUsedUp(f"{tenant.name} has used this month's allowance of the assistants. "
                              "Please try again next month or contact the university.")


def record(model: str, kind: str, prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0,
           cost_usd: float = 0.0) -> None:
    """Log one model call for the current university (cost_usd: as the provider reports it, 0 if
    it does not). A failure is only logged: the answer matters more."""
    tenant = tenants.current_or_none()
    if tenant is None:
        return
    total = total_tokens or prompt_tokens + completion_tokens
    try:
        with get_connection(tenant.id) as conn:
            conn.execute("INSERT INTO usage (tenant_id, agent_id, model, kind, prompt_tokens, completion_tokens, "
                         "total_tokens, cost_usd) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                         (tenant.id, _agent.get(), model[:200], kind, prompt_tokens, completion_tokens, total,
                          max(float(cost_usd or 0), 0.0)))
    except psycopg.Error as error:
        log.warning("Usage of %s not logged: %s", model, type(error).__name__)
