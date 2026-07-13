"""Compatibility helpers for legacy and modern Chat Completions models."""
from __future__ import annotations

import re
from typing import Any


def uses_completion_token_limit(model: str) -> bool:
    """Modern reasoning/frontier models reject legacy ``max_tokens``."""
    name = (model or "").strip().lower()
    return bool(
        re.match(r"^(?:gpt-5(?:\.|-|$)|o[134](?:-|$))", name)
        or name in {"chat-latest"}
    )


def chat_completion_controls(
    model: str,
    *,
    max_output_tokens: int,
    temperature: float | None = None,
) -> dict[str, Any]:
    if uses_completion_token_limit(model):
        # These models use max_completion_tokens and may reject non-default
        # temperature values, so omit temperature entirely.
        return {"max_completion_tokens": max_output_tokens}
    controls: dict[str, Any] = {"max_tokens": max_output_tokens}
    if temperature is not None:
        controls["temperature"] = temperature
    return controls
