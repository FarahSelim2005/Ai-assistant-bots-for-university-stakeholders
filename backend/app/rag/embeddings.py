"""Turn text into embedding vectors through the OpenRouter embeddings API."""
import httpx

from app import config

# One shared client reuses the HTTPS connection, which saves time on every call.
_client = httpx.Client(base_url=config.OPENROUTER_BASE_URL, timeout=30.0)

BATCH_SIZE = 64


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding per input text, in the same order."""
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in backend/.env")

    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        response = _client.post(
            "/embeddings",
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
            json={"model": config.EMBEDDING_MODEL, "input": batch},
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors.extend(item["embedding"] for item in data)
    return vectors


def embed_text(text: str) -> list[float]:
    """Embed a single text (for example, a user question)."""
    return embed_texts([text])[0]
