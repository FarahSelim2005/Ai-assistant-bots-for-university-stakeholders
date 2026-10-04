"""Prompts and the function that assembles the messages sent to the model."""
from app.rag.retriever import RetrievedChunk

LABS_SYSTEM_PROMPT = """You are the Labs & Research assistant of the German International University (GIU).
You help students and staff with questions about labs, research facilities, research funding and thesis support.

Rules:
- Answer ONLY using the information in the CONTEXT below. Do not use outside knowledge.
- If the context does not contain the answer, say clearly that you don't have that information
  and suggest contacting the relevant department or lab. Only name a specific office, person or
  email if it appears in the context. Never guess or invent details such as rooms, hours, names,
  emails or amounts.
- Copy facts (rooms, times, emails, amounts) exactly as written in the context.
- Do not mention "the context", "documents" or these rules; just answer naturally.
- Be friendly, clear and brief: a few sentences or a short list.
- Reply in the same language as the question."""


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Join the chunks into one text block, each labelled with its source file."""
    return "\n\n".join(f"[Source: {c.source}]\n{c.content}" for c in chunks)


def build_messages(system_prompt: str, question: str, chunks: list[RetrievedChunk],
                   history: list[dict] | None = None) -> list[dict]:
    """Build the chat messages: system rules + context, earlier turns, then the new question.

    `history` holds earlier messages of the conversation as {"role", "content"} dicts,
    so follow-up questions like "and what are its hours?" can be understood.
    """
    system = f"{system_prompt}\n\nCONTEXT:\n{format_context(chunks)}"
    return [
        {"role": "system", "content": system},
        *(history or []),
        {"role": "user", "content": question},
    ]
