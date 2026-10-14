"""Which AI provider the app talks to — OpenAI or DeepSeek.

Every AI call (tailoring, cover letters, answers, resume parsing) gets its API key,
client and model name from here. DeepSeek's API is OpenAI-compatible, so the same
``openai`` client is used with DeepSeek's base URL.

Environment:
  AI_PROVIDER            "openai" or "deepseek". When unset: "deepseek" if only
                         DEEPSEEK_API_KEY is set, otherwise "openai".
  OpenAI:   OPENAI_API_KEY, OPENAI_MODEL / OPENAI_MODEL_WRITE / OPENAI_MODEL_FAST / ...
            (unchanged — see .env.example)
  DeepSeek: DEEPSEEK_API_KEY (required), DEEPSEEK_MODEL (default "deepseek-chat"),
            DEEPSEEK_MODEL_WRITE / DEEPSEEK_MODEL_FAST (optional per-role overrides),
            DEEPSEEK_BASE_URL (default https://api.deepseek.com)
  OPENAI_TIMEOUT_SECONDS applies to either provider.

With DeepSeek, OPENAI_MODEL_* settings are ignored on purpose: an OpenAI model name
("chat-latest", "gpt-4o-mini") sent to DeepSeek would just fail.
"""
from __future__ import annotations

import os

from openai import AsyncOpenAI

DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"


def llm_provider() -> str:
    explicit = os.getenv("AI_PROVIDER", "").strip().lower()
    if explicit in ("openai", "deepseek"):
        return explicit
    if os.getenv("DEEPSEEK_API_KEY", "").strip() and not os.getenv("OPENAI_API_KEY", "").strip():
        return "deepseek"
    return "openai"


def llm_api_key() -> str:
    name = "DEEPSEEK_API_KEY" if llm_provider() == "deepseek" else "OPENAI_API_KEY"
    return os.getenv(name, "").strip()


def llm_configured() -> bool:
    return bool(llm_api_key())


def llm_key_env_name() -> str:
    """For messages telling the operator which setting is missing."""
    return "DEEPSEEK_API_KEY" if llm_provider() == "deepseek" else "OPENAI_API_KEY"


def llm_base_url() -> str | None:
    if llm_provider() == "deepseek":
        return os.getenv("DEEPSEEK_BASE_URL", "").strip() or DEEPSEEK_DEFAULT_BASE_URL
    return None  # OpenAI default (or the openai library's own OPENAI_BASE_URL)


def llm_timeout(max_seconds: float = 300.0) -> float:
    try:
        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120") or "120")
    except ValueError:
        timeout = 120.0
    return max(30.0, min(timeout, max_seconds))


def make_llm_client(*, max_timeout: float = 300.0, api_key: str | None = None) -> AsyncOpenAI:
    """An AsyncOpenAI client pointed at the configured provider."""
    kwargs: dict = {"api_key": api_key or llm_api_key(), "timeout": llm_timeout(max_timeout)}
    base_url = llm_base_url()
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs)


def adapt_request_for_provider(kwargs: dict) -> dict:
    """Small per-provider request fixes, applied to every chat completion.

    DeepSeek's JSON mode rejects a request unless the word "json" appears in the
    messages; OpenAI doesn't require it. Add a one-line hint only when missing.
    """
    if llm_provider() != "deepseek":
        return kwargs
    fmt = kwargs.get("response_format") or {}
    messages = kwargs.get("messages") or []
    if isinstance(fmt, dict) and fmt.get("type") == "json_object":
        mentions_json = any("json" in str(m.get("content") or "").lower() for m in messages if isinstance(m, dict))
        if not mentions_json:
            kwargs["messages"] = [{"role": "system", "content": "Respond with a single valid JSON object."}, *messages]
    return kwargs


def llm_model(*openai_env_vars: str, openai_default: str, role: str = "write") -> str:
    """Model name for one call site.

    OpenAI: the first non-empty of `openai_env_vars`, else `openai_default` (exactly the
    app's previous behavior). DeepSeek: DEEPSEEK_MODEL_<ROLE>, else DEEPSEEK_MODEL, else
    deepseek-chat. `role` is "write" (resume/cover-letter/answer writing) or "fast"
    (parsing/analysis helpers).
    """
    if llm_provider() == "deepseek":
        return (
            os.getenv(f"DEEPSEEK_MODEL_{role.upper()}", "").strip()
            or os.getenv("DEEPSEEK_MODEL", "").strip()
            or DEEPSEEK_DEFAULT_MODEL
        )
    for name in openai_env_vars:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return openai_default
