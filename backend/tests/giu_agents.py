"""GIU's four assistants for tests, without a database: made from app/agents/templates.py
(GIU_AGENTS) with their fixed ids and GIU's tenant settings (CV model, campus map), the same as
migrations 004 and 005 put in the database.

    with giu_agents.active(self):   # or giu_agents.activate(self) in setUp
        ...                         # the tenant is GIU and agents_of() returns these four
"""
from contextlib import contextmanager
from unittest import mock

import app.agents as registry
from app import tenants
from app.agents import GIU_TENANT, giu_agent_from_code
from app.agents import directory
from app.agents.templates import GIU_AGENT_IDS
from app.routers import admin
from scripts import ingest

GIU = GIU_TENANT
AGENTS = {key: giu_agent_from_code(key, agent_id=agent_id) for key, agent_id in GIU_AGENT_IDS.items()}
ID = {key: agent.name for key, agent in AGENTS.items()}  # "labs_research" -> its id (also its folder name)


def agents_of(tenant_id):
    return list(AGENTS.values()) if tenant_id == GIU.id else []


@contextmanager
def active(no_embeddings: bool = True):
    """GIU as the tenant, its four assistants from agents_of(), and (by default) no
    description embeddings, so hand-over suggestions never call the embedding service."""
    patches = [mock.patch.object(module, "agents_of", agents_of) for module in (registry, admin, ingest)]
    if no_embeddings:
        patches.append(mock.patch.object(directory, "description_scores", return_value=None))
    for p in patches:
        p.start()
    try:
        with tenants.using(GIU):
            yield AGENTS
    finally:
        for p in patches:
            p.stop()


def activate(testcase) -> dict:
    """active() for a whole test: started now, stopped after the test."""
    context = active()
    agents = context.__enter__()
    testcase.addCleanup(context.__exit__, None, None, None)
    return agents
