"""The Internship & Career agent: internships, the career fair, CVs, interviews, skills and career paths.

Unlike Labs & Research, it may give general career advice from the model's own knowledge
(marked "General advice:"), but GIU facts still come only from its documents.
"""
import re

from app import config
from app.agents.base import BaseAgent
from app.attachments import Attachment
from app.rag.prompts import CAREER_SYSTEM_PROMPT

# Words of a "restructure my CV" request, as in the fine-tuning data: "Please rewrite my CV.",
# "Can you fix my CV?", "Make my CV look professional.", "Use the London template ...",
# "Can you put my CV in ...", "رتبلي السي في", "ظبطلي الـ CV".
CV_REWRITE_WORDS = re.compile(r"rewrite|re-write|fix|restructure|template|professional|put my cv|رتب|ظبط", re.IGNORECASE)


class InternshipCareerAgent(BaseAgent):
    name = "internship_career"
    allowed_user_types = ("student",)
    system_prompt = CAREER_SYSTEM_PROMPT
    model = config.CAREER_MODEL        # e.g. the fine-tuned CV model ollama/giu-cv
    backup_models = config.CAREER_BACKUP_MODELS
    vision_model = config.VISION_MODEL
    vision_backup_models = config.VISION_BACKUP_MODELS
    answers_without_documents = True  # CV, interview and career-path advice need no GIU document
    max_answer_tokens = 1500          # a full CV rewrite is long
    full_local_prompt = True          # giu-cv must get the exact prompt it was trained on
    fallback_message = (
        "Sorry, I don't have information about that. "
        "Please contact the GIU Career Center or your faculty for help."
    )
    fallback_message_ar = (
        "آسف، معنديش معلومات عن ده. "
        "من فضلك تواصل مع الكارير سنتر في الجامعة أو مع الكلية."
    )

    def history_for(self, question: str, history: list[dict] | None,
                    attachment: Attachment | None) -> list[dict] | None:
        """No earlier messages for a CV rewrite with an attached document: the fine-tuned CV
        model was trained without history, and with the previous CV answer in the history
        it repeated that answer instead of reading the newly attached CV."""
        if attachment and attachment.text and CV_REWRITE_WORDS.search(question):
            return []
        return history
