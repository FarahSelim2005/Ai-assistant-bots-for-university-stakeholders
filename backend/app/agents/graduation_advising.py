"""The Graduation & Advising agent: the advising process, probation, adding hours, schedule rules,
Bachelor thesis / internship eligibility, memos and graduation plans.

Like Labs & Research it answers only from its documents (the Academic Performance Department's
advising guidelines), because advising rules must never be guessed.
"""
from app import config
from app.agents.base import BaseAgent
from app.rag.prompts import ADVISING_SYSTEM_PROMPT


class GraduationAdvisingAgent(BaseAgent):
    name = "graduation_advising"
    allowed_user_types = ("student", "staff")
    system_prompt = ADVISING_SYSTEM_PROMPT
    model = config.LABS_MODEL          # same chat models as the other agents
    backup_models = config.LABS_BACKUP_MODELS
    vision_model = config.VISION_MODEL
    vision_backup_models = config.VISION_BACKUP_MODELS
    fallback_message = (
        "Sorry, I don't have information about that. "
        "Please contact the Academic Performance Department or your advisor."
    )
    fallback_message_ar = (
        "آسف، معنديش معلومات عن ده. "
        "من فضلك تواصل مع قسم الأداء الأكاديمي (Academic Performance) أو مع الأدفايزر بتاعك."
    )
