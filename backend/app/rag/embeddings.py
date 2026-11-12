"""Turn text into embedding vectors through the OpenRouter embeddings API. Every request is
logged as the university's usage, and refused when it has used its monthly allowance."""
from functools import lru_cache

import httpx

from app import config, usage

# One shared client reuses the HTTPS connection, which saves time on every call.
_client = httpx.Client(base_url=config.OPENROUTER_BASE_URL, timeout=30.0)

BATCH_SIZE = 64


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding per input text, in the same order."""
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in backend/.env")

    usage.check_allowance()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        response = _client.post(
            "/embeddings",
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
            json={"model": config.EMBEDDING_MODEL, "input": batch},
        )
        response.raise_for_status()
        tokens = response.json().get("usage") or {}
        usage.record(config.EMBEDDING_MODEL, "embedding", prompt_tokens=tokens.get("prompt_tokens", 0),
                     total_tokens=tokens.get("total_tokens", 0), cost_usd=tokens.get("cost", 0))
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        # float(): the API sometimes sends whole numbers like 0, and PostgreSQL arrays
        # (via psycopg) need every value to have the same type.
        vectors.extend([float(x) for x in item["embedding"]] for item in data)
    return vectors


@lru_cache(maxsize=512)
def embed_text(text: str) -> list[float]:
    """Embed a single text (for example, a user question). Remembered, because one
    question is searched in several agents' documents."""
    return embed_texts([text])[0]
