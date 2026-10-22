"""Minimal chat client for OpenRouter and for a local Ollama model.

The model name "ollama" (or "ollama/<name>") runs on this computer through Ollama:
free, unlimited and offline, but slow on a laptop, so local requests are kept small
(short prompt, short answer, thinking off, model kept in memory). Every other model
name goes to OpenRouter's chat-completions API, except "groq/<name>", which goes to
Groq (same format, free tier, very fast; uses GROQ_API_KEY).
"""
import logging
import time

import httpx

from app import config

OLLAMA_PREFIX = "ollama/"
GROQ_PREFIX = "groq/"
log = logging.getLogger("uvicorn.error")  # shows up in the backend terminal

# Shared clients reuse their connections, which saves time on every call.
_openrouter = httpx.Client(base_url=config.OPENROUTER_BASE_URL, timeout=30.0)
_groq = httpx.Client(base_url=config.GROQ_BASE_URL, timeout=30.0)
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
    if model == "ollama" or model.startswith(OLLAMA_PREFIX):
        return chat_ollama(messages, model.removeprefix(OLLAMA_PREFIX).removeprefix("ollama"))
    if model.startswith(GROQ_PREFIX):  # e.g. groq/llama-3.3-70b-versatile
        client, api_key, key_name = _groq, config.GROQ_API_KEY, "GROQ_API_KEY"
    else:
        client, api_key, key_name = _openrouter, config.OPENROUTER_API_KEY, "OPENROUTER_API_KEY"
    if not api_key:
        raise RuntimeError(f"{key_name} is not set in backend/.env")

    # Groq and OpenRouter use the same request format; Groq wants the name without "groq/".
    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model.removeprefix(GROQ_PREFIX), "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens},
    )
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


def chat_with_backup(messages: list[dict], models: list[str], max_tokens: int = 400,
                     rounds: int = 2) -> str:
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
            started = time.perf_counter()
            try:
                answer = chat(messages, model, max_tokens=max_tokens)
                log.info("Answered by %s in %.1f s", model, time.perf_counter() - started)
                return answer
            except (httpx.HTTPError, LLMError) as error:
                log.warning("%s failed after %.1f s: %s", model, time.perf_counter() - started, describe(error))
                last_error = error
    raise last_error


def describe(error: Exception) -> str:
    """A short reason for the log, e.g. "429 Rate limit exceeded: free-models-per-day"."""
    response = getattr(error, "response", None)
    if response is not None:
        try:
            message = response.json().get("error", {}).get("message", "")
        except ValueError:
            message = response.text[:100]
        return f"{response.status_code} {message}".strip()
    return str(error) or type(error).__name__


# Short instructions for the small local model (the agents' full prompts are long).
LOCAL_SYSTEM_PROMPT = (
    "You are a GIU university assistant. Answer only from the CONTEXT below; if the answer "
    "is not there, say you don't have that information. Answer in 1-3 short sentences. "
    "No lists or headings unless asked. Reply in the language of the question and keep "
    "room codes such as M005 as written."
)


def chat_ollama(messages: list[dict], model: str = "") -> str:
    """Ask the local Ollama model (OLLAMA_MODEL unless a name is given) with a small prompt."""
    model = model or config.OLLAMA_MODEL
    started = time.perf_counter()
    response = _ollama.post("/api/chat", json={
        "model": model,
        "messages": small_prompt(messages),
        "think": False,      # no hidden "thinking" before the answer
        "keep_alive": -1,    # keep the model loaded between questions
        "stream": False,     # the backend needs the whole answer (saving, map, backups)
        "options": {"num_predict": config.OLLAMA_NUM_PREDICT, "num_ctx": config.OLLAMA_NUM_CTX,
                    "temperature": 0.1},
    })
    response.raise_for_status()
    content = (response.json().get("message") or {}).get("content", "")
    log.info("Ollama %s answered in %.1f s", model, time.perf_counter() - started)
    if not content.strip():
        raise LLMError(f"Local model '{model}' returned an empty answer.")
    return content.strip()


def small_prompt(messages: list[dict]) -> list[dict]:
    """The agent's messages made small for a laptop: short instructions, a cut-down
    context, the last few history messages, and text only (no images)."""
    system, *rest = messages
    context = system["content"].split("CONTEXT:", 1)[-1].strip()[:config.OLLAMA_MAX_CONTEXT_CHARS]
    *history, question = rest
    history = history[-config.OLLAMA_HISTORY_MESSAGES:] if config.OLLAMA_HISTORY_MESSAGES else []
    content = question["content"]
    if isinstance(content, list):  # picture questions: keep only the text part
        content = " ".join(part["text"] for part in content if part.get("type") == "text")
    return [
        {"role": "system", "content": f"{LOCAL_SYSTEM_PROMPT}\n\nCONTEXT:\n{context}"},
        *history,
        {"role": "user", "content": content},
    ]


def warm_up_ollama() -> None:
    """Load the local model into memory at start-up, so the first real question does not
    have to wait for it. Does nothing if Ollama is not running."""
    started = time.perf_counter()
    try:
        _ollama.post("/api/chat", json={
            # Same start as every real prompt, so Ollama can reuse the work on it.
            "model": config.OLLAMA_MODEL,
            "messages": [{"role": "system", "content": f"{LOCAL_SYSTEM_PROMPT}\n\nCONTEXT:\n"},
                         {"role": "user", "content": "hi"}],
            # Same num_ctx as real questions: a different value makes Ollama reload the model.
            "think": False, "keep_alive": -1, "stream": False,
            "options": {"num_predict": 1, "num_ctx": config.OLLAMA_NUM_CTX},
        }).raise_for_status()
        log.info("Ollama %s loaded in %.1f s", config.OLLAMA_MODEL, time.perf_counter() - started)
    except httpx.HTTPError as error:
        log.warning("Ollama warm-up skipped: %s", describe(error))
