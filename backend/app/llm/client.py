"""Minimal chat-completions client for OpenRouter and for local Ollama models.

Both speak the same OpenAI-style API. A model written as "ollama/<name>" (for example
"ollama/gemma4:e4b") runs on this computer through Ollama: free, unlimited, offline,
but slower. Every other model name goes to OpenRouter.
"""
import time

import httpx

from app import config

OLLAMA_PREFIX = "ollama/"

# Shared clients reuse their connections, which saves time on every call.
# Local models on a laptop are slow, so Ollama gets a much longer timeout.
_openrouter = httpx.Client(base_url=config.OPENROUTER_BASE_URL, timeout=30.0)
_ollama = httpx.Client(base_url=config.OLLAMA_BASE_URL, timeout=config.OLLAMA_TIMEOUT)


class LLMError(Exception):
    """The model returned no usable answer."""


def chat(messages: list[dict], model: str,
         temperature: float = 0.1, max_tokens: int = 400) -> str:
    """Send chat messages to `model` and return the reply text.

    `messages` uses the OpenAI format: [{"role": "system"|"user"|"assistant", "content": "..."}].
    A low temperature keeps answers close to the given context.
    """
    if not model:
        raise RuntimeError("No chat model given. Set LABS_MODEL in backend/.env")

    body = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if model.startswith(OLLAMA_PREFIX):
        client, headers = _ollama, {}
        body["model"] = model.removeprefix(OLLAMA_PREFIX)
        # Models like Gemma 4 otherwise "think" silently first: ~300 tokens instead
        # of ~40, which took 2 minutes instead of 35 seconds on a laptop.
        body["reasoning_effort"] = "none"
    else:
        if not config.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not set in backend/.env")
        client, headers = _openrouter, {"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"}
        body["model"] = model

    response = client.post("/chat/completions", headers=headers, json=body)
    response.raise_for_status()
    data = response.json()
    # OpenRouter can answer "200 OK" with an error instead of choices (e.g. the provider
    # failed or a limit was hit mid-request).
    if not data.get("choices"):
        reason = (data.get("error") or {}).get("message", "no choices in the response")
        raise LLMError(f"Model '{model}' returned no answer: {reason}")
    # Content can be empty, e.g. when a reasoning model spends all tokens on thinking.
    content = data["choices"][0].get("message", {}).get("content")
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
