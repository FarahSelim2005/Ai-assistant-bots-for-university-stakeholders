"""The Labs & Research agent: questions about labs, research facilities and funding."""
from app import config
from app.agents.base import BaseAgent
from app.rag.prompts import LABS_SYSTEM_PROMPT


class LabsResearchAgent(BaseAgent):
    name = "labs_research"
    allowed_user_types = ("student", "staff")
    system_prompt = LABS_SYSTEM_PROMPT
    model = config.LABS_MODEL
    fallback_message = (
        "Sorry, I don't have information about that. "
        "Please contact the relevant department or the lab directly for help."
    )
