"""Registry of available agents, looked up by the name stored in conversations.agent."""
from app.agents.base import BaseAgent
from app.agents.graduation_advising import GraduationAdvisingAgent
from app.agents.internship_career import InternshipCareerAgent
from app.agents.labs_research import LabsResearchAgent

AGENTS: dict[str, BaseAgent] = {
    LabsResearchAgent.name: LabsResearchAgent(),
    InternshipCareerAgent.name: InternshipCareerAgent(),
    GraduationAdvisingAgent.name: GraduationAdvisingAgent(),
}
