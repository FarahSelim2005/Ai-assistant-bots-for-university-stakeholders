"""All four GIU agents, and which one a question probably belongs to.

Used when an agent has no answer: instead of a dead end, the user gets a link to
the agent that handles that topic. The match uses the same embeddings as retrieval
(no chat model call): the question is compared with each agent's description.
"""
from dataclasses import dataclass

import httpx
import numpy as np

from app import config
from app.rag.embeddings import embed_text, embed_texts
from app.rag.retriever import cosine_similarity


@dataclass(frozen=True)
class AgentInfo:
    key: str
    name: str
    description: str             # what the agent handles; used for matching
    user_types: tuple[str, ...]  # who may use it


AGENT_DIRECTORY = [
    AgentInfo(
        "graduation_advising", "Graduation & Advising Assistant",
        "Degree requirements, credit hours, prerequisites, course planning, study plan, "
        "which courses to take next semester, GPA, graduation timeline, graduation "
        "requirements, academic advising and advisors. "
        "التخرج، الساعات المعتمدة، المواد، الخطة الدراسية، الجي بي إيه، المرشد الأكاديمي.",
        ("student", "staff"),
    ),
    AgentInfo(
        "hr_policies", "HR & Policies Assistant",
        "Staff leave types (annual, sick, maternity and unpaid leave), salaries, benefits, "
        "medical insurance for employees, staff policies and regulations, contracts, "
        "working hours and staff complaints. "
        "الإجازات، إجازة سنوية، إجازة مرضية، المرتبات، التأمين الطبي، لوائح الموظفين، الشكاوى.",
        ("staff",),
    ),
    AgentInfo(
        "orientation", "Orientation Assistant",
        "New student orientation, campus map, buildings and facilities, how to find places "
        "on campus, gym, cafeteria, parking, transportation, registration, student ID, "
        "student services, clubs and activities. "
        "الجيم، الكافيتيريا، الباركينج، المواصلات، الأتوبيس، خريطة الجامعة، المباني، "
        "الكارنيه، الأنشطة الطلابية.",
        ("student", "staff"),
    ),
    AgentInfo(
        "labs_research", "Labs & Research Assistant",
        "Lab access, lab rooms and opening hours, lab supervisors, equipment and booking, "
        "research funding and grants, research resources, thesis support and publications. "
        "المعامل، الأجهزة، منحة البحث، البحث العلمي، الرسالة، النشر.",
        ("student", "staff"),
    ),
]


@dataclass
class AgentLink:
    agent: str  # key, e.g. "orientation"
    name: str   # e.g. "Orientation Assistant"
    url: str    # where the frontend sends the user


_description_vectors: np.ndarray | None = None  # computed once, on first use


def suggest_agent(question: str, current_agent: str, user_type: str) -> AgentLink | None:
    """The agent whose description best matches the question, or None when the best
    match is the current agent, an agent this user may not use, or nothing fits."""
    global _description_vectors
    try:
        if _description_vectors is None:
            _description_vectors = np.array(embed_texts([a.description for a in AGENT_DIRECTORY]))
        scores = cosine_similarity(np.array(embed_text(question)), _description_vectors)
    except httpx.HTTPError:
        return None  # no link is better than a broken answer

    best = int(np.argmax(scores))
    agent = AGENT_DIRECTORY[best]
    if (scores[best] < config.AGENT_LINK_THRESHOLD
            or agent.key == current_agent
            or user_type not in agent.user_types):
        return None
    return AgentLink(agent=agent.key, name=agent.name, url=f"/?agent={agent.key}")
