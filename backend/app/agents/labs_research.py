"""The Labs & Research agent: labs, research facilities, funding, and campus buildings and offices."""
from app import config
from app.agents.base import BaseAgent
from app.rag.prompts import LABS_SYSTEM_PROMPT


class LabsResearchAgent(BaseAgent):
    name = "labs_research"
    allowed_user_types = ("student", "staff")
    system_prompt = LABS_SYSTEM_PROMPT
    model = config.LABS_MODEL
    vision_model = config.VISION_MODEL
    fallback_message = (
        "Sorry, I don't have information about that. "
        "Please contact the relevant office or department for help."
    )
