"""Which of this university's assistants a question probably belongs to.

Used when an agent has no answer: instead of a dead end, the user gets a link to the
assistant that handles that topic. Only the current tenant's live assistants are
candidates. The match uses the same embeddings as retrieval (no chat model call): the
question is compared with each assistant's description, whose embedding is stored in
agents.description_embedding (computed once, the first time it is needed).
"""
from dataclasses import dataclass

import httpx
import numpy as np

from app import config, tenants
from app.db import get_connection
from app.rag.embeddings import embed_text, embed_texts
from app.rag.retriever import cosine_similarity


@dataclass
class AgentLink:
    agent: str  # the assistant's key in links (its id; GIU's: its template key until the frontend reads ids)
    name: str   # e.g. "Labs & Research Assistant"
    url: str    # where the frontend sends the user
    available: bool = True  # False: this user may not use it (staff asking Career), so no button


# Description embeddings by description text: the vector depends only on the text, so this
# holds no tenant data and is safe to share; it saves recomputing before the row is reloaded.
_vectors_by_text: dict[str, np.ndarray] = {}


def directory_agents() -> list:
    """The current tenant's live assistants, in their order (ConfiguredAgent objects)."""
    from app.agents import agents_of  # here, not at the top: app.agents imports this module
    return [agent for agent in agents_of(tenants.current_id()) if agent.live]


def link_key(agent) -> str:
    """The key used in links and by the current frontend: GIU's template-based assistants keep
    their old key ("labs_research"), others use their id. (Step 2c switches everything to ids.)"""
    from app.agents import public_key
    return public_key(agent)


def link_to(agent, user_type: str) -> AgentLink:
    key = link_key(agent)
    return AgentLink(agent=key, name=agent.display_name, url=f"/?agent={key}",
                     available=user_type in agent.allowed_user_types)


def suggest_agent(question: str, current_agent: str, user_type: str,
                  min_gap: float = config.AGENT_LINK_MIN_GAP, built_only: bool = False) -> AgentLink | None:
    """The assistant whose description best matches the question, or None when the best
    match is the current one or no assistant clearly wins (off-topic questions match all
    of them about equally). One this user may not use is still named, so the user knows
    who handles it, but marked unavailable. (Every stored assistant is built, so
    `built_only` changes nothing; it stays for the callers.)"""
    agents = directory_agents()
    if len(agents) < 2:
        return None
    scores = description_scores(question, agents)
    if scores is None:
        return None  # no link is better than a broken answer

    best, second = np.argsort(scores)[::-1][:2]
    agent = agents[best]
    if (scores[best] - scores[second] < min_gap
            or scores[best] < config.AGENT_LINK_MIN_SCORE
            or agent.name == current_agent):
        return None
    return link_to(agent, user_type)


def closest_agent(question: str) -> str | None:
    """Key (id) of the assistant whose description matches the question best (None if unknown)."""
    agents = directory_agents()
    scores = description_scores(question, agents) if agents else None
    return None if scores is None else agents[int(np.argmax(scores))].name


def description_scores(question: str, agents: list) -> np.ndarray | None:
    """Similarity of the question to every assistant's description (None if embedding fails)."""
    try:
        return cosine_similarity(np.array(embed_text(question)), description_vectors(agents))
    except httpx.HTTPError:
        return None


def description_vectors(agents: list) -> np.ndarray:
    """One row per assistant: its stored embedding, or (the first time) a new one, saved."""
    missing = [a for a in agents if a.settings.description_embedding is None
               and a.settings.description not in _vectors_by_text]
    if missing:
        texts = list(dict.fromkeys(a.settings.description for a in missing))
        for text, vector in zip(texts, embed_texts(texts)):
            _vectors_by_text[text] = np.array(vector)
        save_embeddings(missing)
    return np.array([a.settings.description_embedding if a.settings.description_embedding is not None
                     else _vectors_by_text[a.settings.description] for a in agents])


def save_embeddings(agents: list) -> None:
    """Store new description embeddings, unless the description changed meanwhile."""
    tenant_id = tenants.current_id()
    with get_connection(tenant_id) as conn:
        for agent in agents:
            conn.execute("UPDATE agents SET description_embedding = %s WHERE id = %s AND tenant_id = %s AND description = %s",
                         (_vectors_by_text[agent.settings.description].tolist(), agent.id, tenant_id,
                          agent.settings.description))
