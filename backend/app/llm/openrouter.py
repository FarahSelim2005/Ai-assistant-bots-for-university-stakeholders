"""Minimal client for OpenRouter's chat completions API."""
import time

import httpx

from app import config

# One shared client reuses the HTTPS connection, which saves time on every call.
_client = httpx.Client(base_url=config.OPENROUTER_BASE_URL, timeout=30.0)


class LLMError(Exception):
    """The model returned no usable answer."""


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
    # Content can be empty, e.g. when a reasoning model spends all tokens on thinking.
    content = response.json()["choices"][0]["message"].get("content")
    if not content or not content.strip():
        raise LLMError(f"Model '{model}' returned an empty answer.")
    return content.strip()


def chat_with_backup(messages: list[dict], models: list[str], rounds: int = 2) -> str:
    """Try the models in order and return the first answer.

    Free models are often rate-limited (daily limit or busy provider), so if one
    fails we move on to the next. If all fail, wait a second and try once more,
    because "provider busy" errors usually clear quickly. Empty entries (an unset
    backup model) are skipped.
    """
    last_error: Exception = LLMError("No chat model given. Set LABS_MODEL in backend/.env")
    for round_number in range(rounds):
        if round_number > 0:
            time.sleep(1)
        for model in [m for m in models if m]:
            try:
                return chat(messages, model)
            except (httpx.HTTPError, LLMError) as error:
                last_error = error
    raise last_error
