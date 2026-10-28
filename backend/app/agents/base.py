"""Shared flow for every agent: rules -> retrieve -> validate -> generate.

Each concrete agent only sets its name, allowed user types, prompt, models and
fallback message. No HTTP code here: routers call `run()` and save the result.
"""
import re
from dataclasses import dataclass, field

from app import config
from app.agents.directory import AGENT_DIRECTORY, AgentLink, closest_agent, suggest_agent
from app.attachments import Attachment
from app.campus import Location, Place, find_locations, find_places, room_facts, rooms_in_question
from app.llm.client import chat_with_backup
from app.rag.prompts import build_messages
from app.rag.transliteration import search_variants, with_english_terms
from app.rag.retriever import RetrievedChunk, retrieve_best

MAX_QUESTION_LENGTH = 1000
ROOM_FACTS_SOURCE = "Room numbering rules"
ARABIC_LETTERS = re.compile(r"[؀-ۿ]")


@dataclass
class AgentResponse:
    answer: str
    sources: list[str]  # file names of the chunks used; empty for the fallback
    locations: list[Location] = field(default_factory=list)  # rooms in the answer, for the map
    places: list[Place] = field(default_factory=list)  # places outside the buildings, for walking links
    redirect: AgentLink | None = None  # another agent to ask, when this one has no answer


class BaseAgent:
    name: str
    allowed_user_types: tuple[str, ...]
    system_prompt: str
    model: str
    backup_models: list[str]  # tried in order when `model` fails, e.g. a free model is rate-limited
    vision_model: str  # used instead of `model` when the user attaches an image
    vision_backup_models: list[str] = []  # tried in order when `vision_model` fails
    fallback_message: str
    fallback_message_ar: str = ""  # used when the question contains Arabic
    # False: no relevant document -> fallback message without asking the model (Labs).
    # True: the model may still give general advice without documents (Career).
    answers_without_documents: bool = False
    max_answer_tokens: int = 400  # longer for agents that write long answers (CV reviews)

    def run(self, question: str, user_type: str, history: list[dict] | None = None,
            attachment: Attachment | None = None) -> AgentResponse:
        """Answer a question for a user type, optionally using earlier messages
        and a file the user attached to this question."""
        question = question.strip()
        # 1. Rules
        self.check_rules(question, user_type, attachment)
        # English words written in Arabic letters ("فين بسكت بال؟") get their English
        # form added, so the search and place detection understand them.
        search_question = with_english_terms(question)
        # 2. Retrieve (filtered by this agent and the user's type)
        search_texts = [self.search_text(q, history) for q in search_variants(question)]
        chunks = retrieve_best(search_texts, self.name, user_type)
        # 3. Validate: with no relevant chunk and no attachment, skip the model and
        #    return the fallback, with a link to the agent that probably can answer
        relevant = self.validate(chunks)
        # A room code in the question (e.g. "Where is A107?") adds its building and
        # floor from the numbering rules, so any valid room can be answered.
        asked_rooms = rooms_in_question(question)
        if asked_rooms:
            relevant.insert(0, RetrievedChunk(room_facts(asked_rooms), ROOM_FACTS_SOURCE, 1.0))
        best_score = max((c.score for c in chunks), default=0.0)
        if not relevant and attachment is None:
            # Prefer a built agent whose documents have the answer (the gym is in Labs'
            # documents), then the agent whose description fits best.
            redirect = (self.owner_by_documents(search_question, search_texts, user_type, best_score)
                        or suggest_agent(search_question, self.name, user_type))
            # An agent that may answer without documents (Career) still sends the user
            # on when the question clearly belongs to another agent (e.g. credit hours).
            if redirect or not self.answers_without_documents:
                return AgentResponse(answer=self.fallback_for(question), sources=[], redirect=redirect)
        # A question that only weakly matches this agent's documents but clearly belongs
        # to another agent is handed over to it instead of being answered here: first a
        # built agent whose documents answer it better, then by the agents' descriptions.
        # Career also hands over to agents not built yet: otherwise its model would
        # give general advice on e.g. credit hours instead of pointing to Graduation.
        if attachment is None and not asked_rooms and best_score < config.HANDOVER_MAX_SCORE:
            owner = (self.owner_by_documents(search_question, search_texts, user_type, best_score)
                     or suggest_agent(search_question, self.name, user_type, min_gap=config.HANDOVER_MIN_GAP,
                                      built_only=not self.answers_without_documents))
            if owner:
                return AgentResponse(answer=self.fallback_for(question), sources=[], redirect=owner)
        # 4. Generate
        answer = self.generate(question, relevant, history, attachment)
        # Show only the places the user asked about (an answer about the gym may also
        # mention the supermarket next to it); use the answer only if the question
        # names no place, e.g. "where can I work out?".
        places = find_places(search_question) or find_places(answer)
        return AgentResponse(answer=answer, sources=unique_sources(relevant),
                             locations=find_locations(answer), places=places)

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

    def owner_by_documents(self, question: str, search_texts: list[str], user_type: str,
                           own_best: float) -> AgentLink | None:
        """Another built agent whose documents answer the question clearly better than
        ours, e.g. "Where is the admission office?" asked to Career -> Labs & Research
        (its documents list the offices). Not when the question fits this agent's own
        topic best: "How do I get a job in digital marketing?" stays with Career even
        though the Digital Marketing major's description is in Advising's documents."""
        if closest_agent(question) == self.name:
            return None
        for other in AGENT_DIRECTORY:
            if not other.built or other.key == self.name or user_type not in other.user_types:
                continue
            best = max((c.score for c in retrieve_best(search_texts, other.key, user_type)), default=0.0)
            if best >= config.SIMILARITY_THRESHOLD and best - own_best >= config.HANDOVER_MIN_GAP:
                return AgentLink(agent=other.key, name=other.name, url=f"/?agent={other.key}")
        return None

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

    def fallback_for(self, question: str) -> str:
        """The "no information" message, in Arabic if the question contains Arabic."""
        if self.fallback_message_ar and ARABIC_LETTERS.search(question):
            return self.fallback_message_ar
        return self.fallback_message

    def generate(self, question: str, chunks: list[RetrievedChunk],
                 history: list[dict] | None, attachment: Attachment | None = None) -> str:
        """Ask the model to answer from the relevant chunks and the attachment only."""
        messages = build_messages(self.system_prompt, question, chunks, history, attachment)
        if attachment and attachment.is_image:
            return chat_with_backup(messages, [self.vision_model, *self.vision_backup_models],
                                    self.max_answer_tokens)
        return chat_with_backup(messages, [self.model, *self.backup_models], self.max_answer_tokens)


def unique_sources(chunks: list[RetrievedChunk]) -> list[str]:
    """Source file names in order of relevance, without duplicates."""
    return list(dict.fromkeys(c.source for c in chunks))
