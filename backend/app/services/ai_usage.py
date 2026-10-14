"""Per-account OpenAI usage tracking ("who spends the credits?").

Every OpenAI call in the app goes through ``AsyncOpenAI().chat.completions.create``,
so ``install_openai_usage_tracking()`` wraps that one method: after each call it
records the signed-in user, the feature (request path), the model, token counts
and an *estimated* USD cost into the ``ai_usage`` collection. Streaming calls are
asked to include usage in their final chunk. Recording failures never affect the
call itself.

Who made the call comes from context variables: ``get_current_user`` sets the
user, ``UsageContextMiddleware`` sets the request path.
"""
from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("uvicorn.error")

_current_user: ContextVar[Any] = ContextVar("ai_usage_user", default=None)
_current_path: ContextVar[str] = ContextVar("ai_usage_path", default="")

# USD per 1M tokens: (input, output, cached input). Verify on
# https://developers.openai.com/api/docs/pricing and override with
# OPENAI_PRICING_JSON='{"model-name": [input, output, cached_input], ...}' (cached optional).
# Matched by longest model-name prefix, so dated snapshots ("gpt-4o-mini-2024-07-18") work.
# chat-latest / gpt-4o / gpt-4o-mini were checked against that page on 2026-10-14;
# the others are from earlier price lists.
DEFAULT_PRICING: dict[str, tuple[float, float, float | None]] = {
    "chat-latest": (5.00, 30.00, 0.50),  # the app's default writing model — expensive
    "gpt-4o-mini": (0.15, 0.60, 0.075),
    "gpt-4o": (2.50, 10.00, 1.25),
    "gpt-4.1-nano": (0.10, 0.40, None),
    "gpt-4.1-mini": (0.40, 1.60, None),
    "gpt-4.1": (2.00, 8.00, None),
    "o4-mini": (1.10, 4.40, None),
    "o3-mini": (1.10, 4.40, None),
    "gpt-5-nano": (0.05, 0.40, None),
    "gpt-5-mini": (0.25, 2.00, None),
    "gpt-5": (1.25, 10.00, None),
}

# Request path prefix → feature name shown on the AI usage page.
FEATURES: tuple[tuple[str, str], ...] = (
    ("/api/tailor", "Tailored resume"),
    ("/api/extension/tailor", "Tailored resume (extension)"),
    ("/api/extension/autofill", "Autofill answers (extension)"),
    ("/api/cover-letter", "Cover letter"),
    ("/api/application-answer", "Application questions"),
    ("/api/qualification-analysis", "Qualification check"),
    ("/api/parse-sections", "Resume parsing"),
    ("/api/resume", "Resume parsing"),
)


def feature_for_path(path: str) -> str:
    for prefix, label in FEATURES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return label
    return "Other" if path else "Background task"


def set_usage_user(user_doc: dict | None) -> None:
    _current_user.set(user_doc.get("_id") if user_doc else None)


def _pricing() -> dict[str, tuple[float, float, float | None]]:
    prices = dict(DEFAULT_PRICING)
    raw = os.getenv("OPENAI_PRICING_JSON", "").strip()
    if raw:
        try:
            for model, values in json.loads(raw).items():
                cached = float(values[2]) if len(values) > 2 and values[2] is not None else None
                prices[str(model)] = (float(values[0]), float(values[1]), cached)
        except (ValueError, TypeError, IndexError, AttributeError):
            logger.warning("Ignoring invalid OPENAI_PRICING_JSON")
    return prices


def estimate_cost_usd(
    model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0
) -> float | None:
    """Estimated USD for one call, or None when the model has no known price.

    `cached_tokens` (part of `prompt_tokens`) are billed at the cheaper cached-input
    rate when the model has one.
    """
    name = (model or "").strip().lower()
    prices = _pricing()
    match = max((key for key in prices if name.startswith(key.lower())), key=len, default=None)
    if match is None:
        return None
    price_in, price_out, price_cached = prices[match]
    cached = min(max(cached_tokens, 0), prompt_tokens) if price_cached is not None else 0
    cost = (
        (prompt_tokens - cached) / 1_000_000 * price_in
        + cached / 1_000_000 * (price_cached or 0.0)
        + completion_tokens / 1_000_000 * price_out
    )
    return round(cost, 6)


async def record_usage(*, user_id: Any, path: str, model: str, usage: Any) -> None:
    if usage is None:
        return
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    details = getattr(usage, "prompt_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
    doc = {
        "user_id": user_id,
        "at": datetime.now(UTC),
        "model": model or "",
        "path": path,
        "feature": feature_for_path(path),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": int(getattr(usage, "total_tokens", 0) or (prompt + completion)),
        "cached_tokens": cached,
        # Snapshot at call time; the report re-prices from tokens with current prices.
        "cost_usd": estimate_cost_usd(model, prompt, completion, cached),
    }
    try:
        from app.database import get_db

        await get_db().ai_usage.insert_one(doc)
    except Exception:  # never let bookkeeping break the actual request
        logger.exception("Could not record OpenAI usage")


class _TrackedStream:
    """Wraps an AsyncStream: passes chunks through, records usage from the final one."""

    def __init__(self, stream: Any, *, user_id: Any, path: str, model: str):
        self._stream = stream
        self._ctx = {"user_id": user_id, "path": path, "model": model}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        usage = None
        try:
            async for chunk in self._stream:
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                yield chunk
        finally:
            if usage is not None:
                await record_usage(usage=usage, **self._ctx)


_installed = False


def install_openai_usage_tracking() -> None:
    """Wrap AsyncCompletions.create once so every chat completion is recorded."""
    global _installed
    if _installed:
        return
    from openai.resources.chat.completions import AsyncCompletions

    original = AsyncCompletions.create

    async def tracked_create(self, *args: Any, **kwargs: Any) -> Any:
        user_id = _current_user.get()
        path = _current_path.get()
        model = str(kwargs.get("model") or "")
        if kwargs.get("stream"):
            # Ask for a final usage chunk (it has no choices; callers already skip those).
            kwargs.setdefault("stream_options", {"include_usage": True})
            stream = await original(self, *args, **kwargs)
            return _TrackedStream(stream, user_id=user_id, path=path, model=model)
        response = await original(self, *args, **kwargs)
        await record_usage(
            user_id=user_id, path=path, model=getattr(response, "model", None) or model, usage=response.usage
        )
        return response

    AsyncCompletions.create = tracked_create  # type: ignore[method-assign]
    _installed = True


class UsageContextMiddleware:
    """Pure ASGI middleware: remembers the request path for usage attribution."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            _current_path.set(scope.get("path") or "")
            _current_user.set(None)
        await self.app(scope, receive, send)
