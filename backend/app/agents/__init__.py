"""Each university's assistants, loaded from the agents table.

agents_of(tenant_id) returns the tenant's assistants (ConfiguredAgent, or CvAgent for those
that rewrite CVs: the "cv" skill at a university with a trained CV model), cached per tenant
until its row or one of its assistants changes: every call asks the database only for the
tenant's row, the number of assistants and the newest updated_at, and reloads when any changed.
"""
import threading
import uuid

from app.agents.configured import COLUMNS, AgentSettings, ConfiguredAgent
from app.agents.internship_career import CvAgent
from app.agents.templates import giu_agent, template
from app.db import get_connection
from app.tenants import TENANT_COLUMNS, Tenant

_cache: dict[uuid.UUID, tuple[tuple, list[ConfiguredAgent]]] = {}  # tenant id -> (stamp, agents)
_lock = threading.Lock()


def make_agent(settings: AgentSettings, tenant: Tenant) -> ConfiguredAgent:
    rewrites_cvs = "cv" in settings.skills and tenant.has_cv_model
    return (CvAgent if rewrites_cvs else ConfiguredAgent)(settings, tenant)


def agents_of(tenant_id: uuid.UUID) -> list[ConfiguredAgent]:
    """The tenant's assistants (live or not), in their order."""
    with get_connection(tenant_id) as conn:
        stamp = conn.execute(f"SELECT {TENANT_COLUMNS}, count(a.id), max(a.updated_at) FROM tenants t "
                             "LEFT JOIN agents a ON a.tenant_id = t.id WHERE t.id = %s GROUP BY t.id",
                             (tenant_id,)).fetchone()
        if stamp is None:
            return []
        stamp = tuple(stamp)
        cached = _cache.get(tenant_id)
        if cached and cached[0] == stamp:
            return cached[1]
        rows = conn.execute(f"SELECT {COLUMNS} FROM agents WHERE tenant_id = %s ORDER BY position, name, id",
                            (tenant_id,)).fetchall()
    tenant = Tenant(*stamp[:-2])
    agents = [make_agent(AgentSettings.from_row(row), tenant) for row in rows]
    with _lock:
        _cache[tenant_id] = (stamp, agents)
    return agents


def load_agent(tenant_id: uuid.UUID, agent_id: uuid.UUID | str) -> ConfiguredAgent | None:
    """One of the tenant's assistants by id (None if it has no such assistant)."""
    return next((a for a in agents_of(tenant_id) if a.name == str(agent_id)), None)


def find_agent(tenant_id: uuid.UUID, key: str) -> ConfiguredAgent | None:
    """An assistant by id, or by the template key it was made from ("labs_research"), as the
    current frontend, the evaluation CSV and old links still name GIU's assistants."""
    agents = agents_of(tenant_id)
    return (next((a for a in agents if a.name == key.strip().lower()), None)
            or next((a for a in agents if a.settings.template_key == key), None))


def script_agent(tenant_id: uuid.UUID, key: str | None) -> ConfiguredAgent:
    """For command-line scripts: the assistant named by --agent (id or template key), or the
    tenant's first live one; stops with a message listing the assistants if there is none."""
    agent = find_agent(tenant_id, key) if key else next((a for a in agents_of(tenant_id) if a.live), None)
    if agent is None:
        names = ", ".join(f"{a.display_name} ({public_key(a)})" for a in agents_of(tenant_id)) or "none"
        raise SystemExit(f"No assistant '{key}'. This university's assistants: {names}.")
    return agent


def public_key(agent: ConfiguredAgent) -> str:
    """How links and lists name an assistant until the frontend reads ids (step 2c): its
    template key when it is the tenant's only assistant from that template, else its id."""
    key = agent.settings.template_key
    if key and sum(a.settings.template_key == key for a in agents_of(agent.settings.tenant_id)) == 1:
        return key
    return agent.name


# Without the database: tests, and trying a template. GIU's tenant settings as migration 005 sets them.
GIU_TENANT = Tenant(uuid.UUID(int=1), "giu", "German International University", short_name="GIU",
                    has_cv_model=True, campus_map=True)


def agent_from_values(values: dict, tenant: Tenant, agent_id: uuid.UUID | None = None, **changes) -> ConfiguredAgent:
    """An assistant from a template's or GIU agent's values (app/agents/templates.py)."""
    settings = AgentSettings(
        id=agent_id or uuid.uuid4(), tenant_id=tenant.id, template_key=values["key"], name=values["name"],
        summary=values["summary"], subtitle=values["subtitle"], description=values["description"],
        audiences=tuple(values["audiences"]), answer_mode=values["answer_mode"], instructions=values["instructions"],
        fallback_en=values["fallback_en"], fallback_ar=values["fallback_ar"], welcome=values["welcome"],
        placeholder=values["placeholder"], examples=tuple(values["examples"]), skills=tuple(values["skills"]),
        max_answer_tokens=values["max_answer_tokens"], model=None, backup_models=(), similarity_threshold=None,
        position=values["position"], live=True, description_embedding=None, prompt_mode=values["prompt_mode"])
    return make_agent(AgentSettings(**{**settings.__dict__, **changes}), tenant)


def agent_from_template(key: str, tenant: Tenant | None = None, agent_id: uuid.UUID | None = None,
                        **changes) -> ConfiguredAgent:
    """A ready-made assistant for a university (default: a made-up one without CV model or map)."""
    tenant = tenant or Tenant(uuid.uuid4(), "example", "Example University", short_name="EXU")
    return agent_from_values(template(key), tenant, agent_id, **changes)


def giu_agent_from_code(key: str, agent_id: uuid.UUID | None = None, tenant: Tenant = GIU_TENANT,
                        **changes) -> ConfiguredAgent:
    """One of GIU's four assistants as its agents row has it (complete prompt, GIU's texts)."""
    return agent_from_values(giu_agent(key), tenant, agent_id, **changes)
