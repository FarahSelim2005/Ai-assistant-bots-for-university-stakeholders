"""Minimal client for OpenRouter's chat completions API."""
import httpx

from app import config

# One shared client reuses the HTTPS connection, which saves time on every call.
_client = httpx.Client(base_url=config.OPENROUTER_BASE_URL, timeout=30.0)


def chat(messages: list[dict], model: str,
         temperature: float = 0.1, max_tokens: int = 400) -> str:
    """Send chat messages to `model` and return the reply text.

    `messages` uses the OpenAI format: [{"role": "system"|"user"|"assistant", "content": "..."}].
    A low temperature keeps answers close to the given context.
    """
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in backend/.env")
    if not model:
        raise RuntimeError("No chat model given. Set LABS_MODEL in backend/.env")

    response = _client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()
