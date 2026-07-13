"""Quick OpenAI connectivity check — does not print the API key."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def main() -> None:
    backend = Path(__file__).resolve().parents[1]
    load_dotenv(backend / ".env")
    key = os.getenv("OPENAI_API_KEY", "").strip()
    print("key_present:", bool(key))
    write_model = (
        os.getenv("OPENAI_MODEL_WRITE", "").strip()
        or os.getenv("OPENAI_MODEL", "").strip()
        or "chat-latest"
    )
    fast_model = os.getenv("OPENAI_MODEL_FAST", "").strip() or "gpt-4o-mini"
    strategy_model = os.getenv("OPENAI_MODEL_STRATEGY", "").strip() or write_model
    review_model = os.getenv("OPENAI_MODEL_REVIEW", "").strip() or write_model
    print("writer_model:", write_model)
    print("strategy_model:", strategy_model)
    print("review_model:", review_model)
    print("fast_model:", fast_model)
    print("timeout_seconds:", os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    if not key:
        print("api_status: failed (no OPENAI_API_KEY)")
        return
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key, timeout=90.0)
        t0 = time.time()
        normalized_model = write_model.strip().lower()
        modern_model = bool(
            re.match(r"^(?:gpt-5(?:\.|-|$)|o[134](?:-|$))", normalized_model)
            or normalized_model == "chat-latest"
        )
        token_controls = (
            {"max_completion_tokens": 32}
            if modern_model
            else {"max_tokens": 32}
        )
        resp = client.chat.completions.create(
            model=write_model,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            **token_controls,
        )
        elapsed = time.time() - t0
        print("api_status: ok")
        print("reply:", (resp.choices[0].message.content or "").strip())
        print("seconds:", round(elapsed, 1))
    except Exception as exc:
        print("api_status: failed")
        print("error_type:", type(exc).__name__)
        msg = str(exc).replace("\n", " ")
        if len(msg) > 320:
            msg = msg[:317] + "..."
        print("error:", msg)


if __name__ == "__main__":
    main()
