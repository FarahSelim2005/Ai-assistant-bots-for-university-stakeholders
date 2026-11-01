"""The HR & Policies agent (staff only): leave, maternity and family leave, contracts, raises,
resignation and notice, official public holidays and other employment rules.

Like Labs & Research it answers only from its documents, because HR rules must never be
guessed. Its document separates Egyptian labour law from GIU's own policies, and the answers
keep that distinction.
"""
from app import config
from app.agents.base import BaseAgent
from app.rag.prompts import HR_SYSTEM_PROMPT


class HrPoliciesAgent(BaseAgent):
    name = "hr_policies"
    allowed_user_types = ("staff",)
    system_prompt = HR_SYSTEM_PROMPT
    model = config.LABS_MODEL          # same chat models as the other agents
    backup_models = config.LABS_BACKUP_MODELS
    vision_model = config.VISION_MODEL
    vision_backup_models = config.VISION_BACKUP_MODELS
    fallback_message = (
        "Sorry, I don't have information about that. "
        "Please contact the GIU Human Resources (HR) department."
    )
    fallback_message_ar = (
        "آسف، معنديش معلومات عن ده. "
        "من فضلك تواصل مع إدارة الموارد البشرية (HR) في الجامعة."
    )
