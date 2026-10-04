"""Shared flow for every agent: rules -> retrieve -> validate -> generate.

Each concrete agent only sets its name, allowed user types, prompt, models and
fallback message. No HTTP code here: routers call `run()` and save the result.
"""
from dataclasses import dataclass, field

from app import config
from app.attachments import Attachment
from app.campus import Location, find_locations
from app.llm.openrouter import chat
from app.rag.prompts import build_messages
from app.rag.retriever import RetrievedChunk, retrieve

MAX_QUESTION_LENGTH = 1000


@dataclass
class AgentResponse:
    answer: str
    sources: list[str]  # file names of the chunks used; empty for the fallback
    locations: list[Location] = field(default_factory=list)  # rooms in the answer, for the map


class BaseAgent:
    name: str
    allowed_user_types: tuple[str, ...]
    system_prompt: str
    model: str
    vision_model: str  # used instead of `model` when the user attaches an image
    fallback_message: str

    def run(self, question: str, user_type: str, history: list[dict] | None = None,
            attachment: Attachment | None = None) -> AgentResponse:
        """Answer a question for a user type, optionally using earlier messages
        and a file the user attached to this question."""
        question = question.strip()
        # 1. Rules
        self.check_rules(question, user_type, attachment)
        # 2. Retrieve (filtered by this agent and the user's type)
        chunks = retrieve(self.search_text(question, history), self.name, user_type)
        # 3. Validate: with no relevant chunk and no attachment, skip the model
        #    and return the fallback
        relevant = self.validate(chunks)
        if not relevant and attachment is None:
            return AgentResponse(answer=self.fallback_message, sources=[])
        # 4. Generate
        answer = self.generate(question, relevant, history, attachment)
        return AgentResponse(answer=answer, sources=unique_sources(relevant),
                             locations=find_locations(answer))

    def check_rules(self, question: str, user_type: str,
                    attachment: Attachment | None = None) -> None:
        """Reject requests this agent must not handle (raises ValueError)."""
        if user_type not in self.allowed_user_types:
            raise ValueError(f"The {self.name} agent is not available for '{user_type}' users.")
        if not question:
            raise ValueError("The question is empty.")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"The question is longer than {MAX_QUESTION_LENGTH} characters.")
        if attachment and attachment.is_image and not self.vision_model:
            raise ValueError("Image questions are not available yet. Please upload a PDF or text file.")

    def search_text(self, question: str, history: list[dict] | None) -> str:
        """Text used for retrieval. For follow-ups like "when is it open?", the previous
        user question is added so the search still knows what "it" refers to."""
        previous = [m["content"] for m in history or [] if m["role"] == "user"]
        return f"{previous[-1]} {question}" if previous else question

    def validate(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Keep only chunks that pass the similarity threshold.
        An empty result (and no attachment) means the agent has no information
        and must not call the model."""
        return [c for c in chunks if c.score >= config.SIMILARITY_THRESHOLD]

    def generate(self, question: str, chunks: list[RetrievedChunk],
                 history: list[dict] | None, attachment: Attachment | None = None) -> str:
        """Ask the model to answer from the relevant chunks and the attachment only."""
        messages = build_messages(self.system_prompt, question, chunks, history, attachment)
        model = self.vision_model if attachment and attachment.is_image else self.model
        return chat(messages, model=model)


def unique_sources(chunks: list[RetrievedChunk]) -> list[str]:
    """Source file names in order of relevance, without duplicates."""
    return list(dict.fromkeys(c.source for c in chunks))
