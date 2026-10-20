"""The Internship & Career agent: internships, the career fair, CVs, interviews, skills and career paths.

Unlike Labs & Research, it may give general career advice from the model's own knowledge
(marked "General advice:"), but GIU facts still come only from its documents.
"""
from app import config
from app.agents.base import BaseAgent
from app.rag.prompts import CAREER_SYSTEM_PROMPT


class InternshipCareerAgent(BaseAgent):
    name = "internship_career"
    allowed_user_types = ("student",)
    system_prompt = CAREER_SYSTEM_PROMPT
    model = config.LABS_MODEL          # same chat models as the other agents
    backup_models = config.LABS_BACKUP_MODELS
    vision_model = config.VISION_MODEL
    vision_backup_models = config.VISION_BACKUP_MODELS
    answers_without_documents = True  # CV, interview and career-path advice need no GIU document
    max_answer_tokens = 900           # CV reviews are longer than lookup answers
    fallback_message = (
        "Sorry, I don't have information about that. "
        "Please contact the GIU Career Center or your faculty for help."
    )
    fallback_message_ar = (
        "آسف، معنديش معلومات عن ده. "
        "من فضلك تواصل مع الكارير سنتر في الجامعة أو مع الكلية."
    )
