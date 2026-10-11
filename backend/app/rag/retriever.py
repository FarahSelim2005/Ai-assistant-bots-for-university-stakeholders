"""Find the chunks most similar to a question.

Embeddings are stored as DOUBLE PRECISION[] (pgvector is not installed), so the
similarity is computed in Python with numpy. Only `cosine_similarity` would need
to change if pgvector is added later.
"""
from dataclasses import dataclass

import numpy as np

from app import config
from app.db import get_connection
from app.rag.embeddings import embed_text


@dataclass
class RetrievedChunk:
    content: str
    source: str
    score: float


def cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity between one query vector and every row of `matrix`."""
    return (matrix @ query) / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(query))


def load_chunks(agent: str, user_type: str) -> list[tuple[str, str, list[float]]]:
    """Return (content, source, embedding) for the agent's chunks visible to this user type."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT content, source, embedding FROM chunks "
            "WHERE agent = %s AND %s = ANY(audience)",
            (agent, user_type),
        ).fetchall()


def retrieve(question: str, agent: str, user_type: str,
             top_k: int = config.TOP_K) -> list[RetrievedChunk]:
    """Return the top_k chunks most similar to the question, best first, with scores."""
    rows = load_chunks(agent, user_type)
    if not rows:
        return []

    query = np.array(embed_text(question))
    matrix = np.array([row[2] for row in rows])
    scores = cosine_similarity(query, matrix)

    best = np.argsort(scores)[::-1][:top_k]
    return [RetrievedChunk(content=rows[i][0], source=rows[i][1], score=float(scores[i]))
            for i in best]


def retrieve_best(questions: list[str], agent: str, user_type: str,
                  top_k: int = config.TOP_K) -> list[RetrievedChunk]:
    """Search with several wordings of the same question and keep, for each chunk, its
    best score (used for English words written in Arabic letters)."""
    best: dict[str, RetrievedChunk] = {}
    for question in questions:
        for chunk in retrieve(question, agent, user_type, top_k):
            if chunk.content not in best or chunk.score > best[chunk.content].score:
                best[chunk.content] = chunk
    return sorted(best.values(), key=lambda c: c.score, reverse=True)[:top_k]
