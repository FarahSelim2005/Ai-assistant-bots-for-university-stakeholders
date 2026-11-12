"""An assistant as a university configured it in the agents table: any name, any number.

ConfiguredAgent fills in what BaseAgent needs from one row and its university (tenant); the
shared flow (rules -> retrieve -> validate -> generate, BaseAgent.run) is the same for all.
BaseAgent uses `name` as the agent's key for retrieval and hand-overs, so here `name` is the
agent's id; the name people see is `display_name`.

Skills (the row's `skills`):
- files / images: which attachments it reads (a picture also needs VISION_MODEL);
- editor: it edits and converts documents (app/routers/chat.py, documents.py);
- cv: CV rewrites with the fine-tuned CV model, only if the university has one (has_cv_model);
- map: campus rooms, buildings and places, only if the university has a campus map (campus_map);
- voice: the voice call button (shown by the frontend).
"""
import uuid
from dataclasses import dataclass
from datetime import datetime

from app import config
from app.agents.base import BaseAgent
from app.rag.prompts import render, system_prompt
from app.tenants import Tenant

# The agents table's columns, in the order AgentSettings takes them.
COLUMNS = ("id, tenant_id, template_key, name, summary, subtitle, description, audiences, answer_mode, "
           "instructions, fallback_en, fallback_ar, welcome, placeholder, examples, skills, max_answer_tokens, "
           "model, backup_models, similarity_threshold, position, live, description_embedding, prompt_mode, folder, "
           "updated_at")


@dataclass(frozen=True)
class AgentSettings:
    id: uuid.UUID
    tenant_id: uuid.UUID
    template_key: str | None
    name: str
    summary: str
    subtitle: str
    description: str
    audiences: tuple[str, ...]
    answer_mode: str           # "docs": only from documents; "advice": may also give general advice
    instructions: str
    fallback_en: str
    fallback_ar: str
    welcome: str
    placeholder: str
    examples: tuple[str, ...]
    skills: tuple[str, ...]
    max_answer_tokens: int
    model: str | None          # None: LABS_MODEL from .env
    backup_models: tuple[str, ...]  # empty: LABS_BACKUP_MODEL from .env
    similarity_threshold: float | None  # None: SIMILARITY_THRESHOLD
    position: int
    live: bool
    description_embedding: tuple[float, ...] | None
    prompt_mode: str = "composed"  # "complete": the instructions are the whole prompt (GIU's four)
    folder: str = ""               # its document folder's name, readable and unique per university
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row) -> "AgentSettings":
        values = list(row)
        for index in (7, 14, 15, 18):  # TEXT[] columns
            values[index] = tuple(values[index] or ())
        values[22] = tuple(values[22]) if values[22] is not None else None
        return cls(*values)


class ConfiguredAgent(BaseAgent):
    def __init__(self, settings: AgentSettings, tenant: Tenant):
        self.settings = settings
        self.tenant = tenant
        self.id = settings.id
        self.name = str(settings.id)
        self.display_name = settings.name
        self.university = tenant.short
        self.allowed_user_types = tuple(settings.audiences)
        # Skills: what this assistant does, and what its university allows.
        self.reads_files = self.has_skill("files")
        self.reads_images = self.has_skill("images")
        self.edits_documents = self.has_skill("editor")
        self.rewrites_cvs = self.has_skill("cv") and tenant.has_cv_model
        self.campus_map = self.has_skill("map") and tenant.campus_map
        self.system_prompt = system_prompt(settings.name, settings.instructions, settings.answer_mode,
                                           settings.prompt_mode, tenant.short, tenant.name,
                                           files=self.reads_files, images=self.reads_images, campus_map=self.campus_map)
        self.model = settings.model or config.LABS_MODEL
        self.backup_models = list(settings.backup_models) or config.LABS_BACKUP_MODELS
        self.vision_model = config.VISION_MODEL if self.reads_images else ""
        self.vision_backup_models = config.VISION_BACKUP_MODELS if self.reads_images else []
        self.fallback_message = render(settings.fallback_en, tenant.short)
        self.fallback_message_ar = render(settings.fallback_ar, tenant.short)
        self.answers_without_documents = settings.answer_mode == "advice"
        self.max_answer_tokens = settings.max_answer_tokens

    @property
    def live(self) -> bool:
        return self.settings.live

    def has_skill(self, skill: str) -> bool:
        return skill in self.settings.skills

    def active_skills(self) -> list[str]:
        """The skills that work at this university (cv needs a trained CV model, map a campus map)."""
        on = {"files": self.reads_files, "images": self.reads_images, "cv": self.rewrites_cvs,
              "editor": self.edits_documents, "map": self.campus_map, "voice": self.has_skill("voice")}
        return [skill for skill, works in on.items() if works]

    def check_rules(self, question: str, user_type: str, attachment=None) -> None:
        """BaseAgent's rules, plus: only the attachments its skills allow (files, images)."""
        if attachment is not None and user_type in self.allowed_user_types:
            if attachment.is_image and not self.reads_images:
                raise ValueError(f"The {self.display_name} does not read pictures. Please ask in words.")
            if not attachment.is_image and not self.reads_files:
                raise ValueError(f"The {self.display_name} does not read files. Please ask in words.")
        super().check_rules(question, user_type, attachment)

    def validate(self, chunks):
        """Chunks that pass this agent's own threshold, or SIMILARITY_THRESHOLD when it has none."""
        threshold = self.settings.similarity_threshold
        if threshold is None:
            return super().validate(chunks)
        return [c for c in chunks if c.score >= threshold]
