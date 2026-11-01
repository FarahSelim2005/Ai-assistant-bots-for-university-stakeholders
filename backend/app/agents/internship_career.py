"""The Internship & Career agent: internships, the career fair, CVs, interviews, skills and career paths.

Unlike Labs & Research, it may give general career advice from the model's own knowledge
(marked "General advice:"), but GIU facts still come only from its documents.

CV rewrites (a CV attached + "rewrite / fix / template ..."): no document search and no
history, so the fine-tuned CV model gets exactly its training format; a CV that is a picture
is first written out as text by the vision model; and years, numbers and links in the answer
that are not in the CV are replaced by placeholders.
"""
import logging
import re

from app import config
from app.agents.base import AgentResponse, BaseAgent
from app.attachments import Attachment
from app.llm.client import chat_with_backup
from app.rag.prompts import CAREER_SYSTEM_PROMPT

log = logging.getLogger("uvicorn.error")  # shows up in the backend terminal

# Words of a "restructure my CV" request, as in the fine-tuning data: "Please rewrite my CV.",
# "Can you fix my CV?", "Make my CV look professional.", "Use the London template ...",
# "Can you put my CV in ...", "رتبلي السي في", "ظبطلي الـ CV".
CV_REWRITE_WORDS = re.compile(r"rewrite|re-write|fix|restructure|template|professional|put my cv|رتب|ظبط", re.IGNORECASE)

# For CVs that are pictures (photos, image-only PDFs such as many Canva CVs): the vision
# model only writes the CV out as text; the fine-tuned CV model then does the rewrite.
TRANSCRIBE_PROMPT = (
    "You transcribe CVs. Write out all the text of the CV in the picture(s) exactly as written, "
    "as plain text: one section after another in reading order (for two columns: the whole "
    "left column, then the whole right column), each bullet on its own line. Keep every name, "
    "date, number, email, phone number and link exactly. Do not correct, translate, summarize, "
    "reorder or add anything. Reply with the CV text only."
)

# Checked in a CV rewrite against the CV text: links, years and numbers of 2+ digits.
URL = re.compile(r"(?<![@\w])(?:https?://)?(?:www\.)?(?:[a-z0-9-]+\.)+(?:com|net|org|io|dev|me|eg|edu|co)"
                 r"(?:/[^\s|,;)]*)?", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d ./–-]*\d|\d")  # digits with spaces, dots, slashes or dashes inside
YEAR = re.compile(r"(?<!\d)(?:19|20)\d\d(?!\d)")
CHANGES_HEADINGS = ("What I changed:", "ما غيرته:")  # the model's own notes: not checked


def is_cv_rewrite(question: str, attachment: Attachment | None) -> bool:
    """A request to restructure an attached CV (a document or a picture)."""
    return bool(attachment and (attachment.text or attachment.is_image) and CV_REWRITE_WORDS.search(question))


def link_key(url: str) -> str:
    """A link without "https://", "www." and a final "/", lowercase, for comparing."""
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower()).rstrip("/.")


def complete_links(answer: str, cv_text: str) -> str:
    """Put back links the CV text cut off: a link split across two lines in the PDF is read
    as "github.com/FarahSelim", while the PDF's link annotation ("Links: ..." in the CV text)
    has the whole "https://github.com/FarahSelim2005". A link in the answer that is the start
    of exactly one longer link there is replaced by that link."""
    full_links = [u.strip() for line in cv_text.splitlines() if line.startswith("Links:")
                  for u in line[len("Links:"):].split(",") if u.strip()]

    def complete(match):
        url = match.group()
        longer = {u for u in full_links if link_key(u).startswith(link_key(url)) and link_key(u) != link_key(url)}
        if len(longer) == 1:
            replacement = longer.pop()
            log.info("CV link completed from the PDF's link annotations")
            return replacement
        return url

    return URL.sub(complete, answer)


def check_against_cv(answer: str, cv_text: str) -> str:
    """Replace links, years and numbers that the model wrote but that are not in the CV.

    The fine-tuned model sometimes invents them (a LinkedIn URL for the text "LinkedIn",
    "2023 - 2025" for "2 years"). Numbers are compared by their digits only, so a phone
    number written with other spaces still counts as present. Only the CV part of the
    answer is checked, not the "What I changed:" notes.
    """
    cv_links = " ".join(link_key(u) for u in re.findall(r"\S+", cv_text))
    cv_digits = re.sub(r"\D", "", cv_text)
    replaced = []

    def link(match):
        url = match.group()
        if link_key(url) in cv_links:
            return url
        replaced.append(url)
        if "linkedin" in url.lower():
            return "[add your LinkedIn link]"
        return "[add your GitHub link]" if "github" in url.lower() else "[add your link]"

    def number(match):
        text = match.group()
        digits = re.sub(r"\D", "", text)
        if len(digits) < 2:
            return text
        years = YEAR.findall(text)
        if years:  # a year or a date range: every year must be in the CV
            if all(year in cv_text for year in years):
                return text
            replaced.append(text)
            return "[add dates]"
        if digits in cv_digits:
            return text
        replaced.append(text)
        return "[add the number]"

    cut = min((answer.find(h) for h in CHANGES_HEADINGS if h in answer), default=len(answer))
    cv_part = NUMBER.sub(number, URL.sub(link, answer[:cut]))
    log.info("CV check: %d replacement(s)%s", len(replaced), f" {replaced}" if replaced else "")
    return cv_part + answer[cut:]


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

    def run(self, question: str, user_type: str, history: list[dict] | None = None,
            attachment: Attachment | None = None) -> AgentResponse:
        """CV rewrites skip the document search (and the hand-over to other agents): the
        fine-tuned CV model was trained with "(no matching GIU documents)" as the context
        and no history, so it gets exactly that. Other questions use the normal flow."""
        question = question.strip()
        if not is_cv_rewrite(question, attachment):
            return super().run(question, user_type, history, attachment)
        self.check_rules(question, user_type, attachment)
        return AgentResponse(answer=self.generate(question, [], [], attachment), sources=[])

    def history_for(self, question: str, history: list[dict] | None,
                    attachment: Attachment | None) -> list[dict] | None:
        """No earlier messages for a CV rewrite with an attached document: the fine-tuned CV
        model was trained without history, and with the previous CV answer in the history
        it repeated that answer instead of reading the newly attached CV."""
        if is_cv_rewrite(question, attachment):
            return []
        return history

    def generate(self, question: str, chunks, history, attachment: Attachment | None = None) -> str:
        """CV rewrites: a picture CV is written out as text first (so the fine-tuned CV model,
        which reads text, does the rewrite), and the answer is checked against the CV."""
        if not is_cv_rewrite(question, attachment):
            return super().generate(question, chunks, history, attachment)
        if attachment.is_image:
            attachment = Attachment(attachment.filename, text=self.transcribe(attachment))
        answer = super().generate(question, chunks, history, attachment)
        return check_against_cv(complete_links(answer, attachment.text), attachment.text)

    def transcribe(self, attachment: Attachment) -> str:
        """The text of a picture CV, written out by the vision model (and its backups)."""
        messages = [
            {"role": "system", "content": TRANSCRIBE_PROMPT},
            {"role": "user", "content": [{"type": "text", "text": f"Transcribe this CV ({attachment.filename})."},
                                         *({"type": "image_url", "image_url": {"url": url}}
                                           for url in attachment.image_urls)]},
        ]
        text = chat_with_backup(messages, [self.vision_model, *self.vision_backup_models], 2000)
        log.info("Picture CV %s written out as text (%d characters)", attachment.filename, len(text))
        return text[:config.MAX_ATTACHMENT_CHARS]
