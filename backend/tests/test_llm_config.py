"""Provider switch: OpenAI (default) vs DeepSeek — no network, no credits."""
import asyncio
import json
import os
import unittest
from unittest import mock

import httpx
from openai import AsyncOpenAI

from app.services import ai_usage
from app.services.ai_usage import estimate_cost_usd
from app.services.llm_config import (
    adapt_request_for_provider,
    llm_api_key,
    llm_model,
    llm_provider,
    make_llm_client,
)
from app.services.openai_compat import chat_completion_controls

ai_usage.install_openai_usage_tracking()

DEEPSEEK = {"AI_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "ds-key", "OPENAI_API_KEY": "sk-openai",
            "OPENAI_MODEL_WRITE": "chat-latest", "DEEPSEEK_MODEL": "", "DEEPSEEK_BASE_URL": ""}
OPENAI = {"AI_PROVIDER": "", "DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": "sk-openai",
          "OPENAI_MODEL_WRITE": "", "OPENAI_MODEL": ""}


class ProviderSelectionTests(unittest.TestCase):
    def test_openai_is_the_default_and_unchanged(self) -> None:
        with mock.patch.dict(os.environ, OPENAI):
            self.assertEqual("openai", llm_provider())
            self.assertEqual("sk-openai", llm_api_key())
            self.assertEqual("chat-latest", llm_model("OPENAI_MODEL_WRITE", "OPENAI_MODEL", openai_default="chat-latest"))
            self.assertEqual("https://api.openai.com/v1/", str(make_llm_client().base_url))

    def test_deepseek_key_url_and_model_ignore_openai_settings(self) -> None:
        with mock.patch.dict(os.environ, DEEPSEEK):
            self.assertEqual("deepseek", llm_provider())
            self.assertEqual("ds-key", llm_api_key())
            # OPENAI_MODEL_WRITE=chat-latest must not leak into DeepSeek requests.
            self.assertEqual("deepseek-chat", llm_model("OPENAI_MODEL_WRITE", openai_default="chat-latest"))
            client = make_llm_client()
            self.assertEqual("https://api.deepseek.com", str(client.base_url).rstrip("/"))
            self.assertEqual("ds-key", client.api_key)

    def test_deepseek_auto_selected_when_only_its_key_is_set(self) -> None:
        with mock.patch.dict(os.environ, {"AI_PROVIDER": "", "OPENAI_API_KEY": "", "DEEPSEEK_API_KEY": "ds"}):
            self.assertEqual("deepseek", llm_provider())

    def test_per_role_override(self) -> None:
        with mock.patch.dict(os.environ, {**DEEPSEEK, "DEEPSEEK_MODEL_FAST": "deepseek-reasoner"}):
            self.assertEqual("deepseek-reasoner", llm_model(openai_default="gpt-4o-mini", role="fast"))
            self.assertEqual("deepseek-chat", llm_model(openai_default="chat-latest", role="write"))

    def test_deepseek_chat_output_cap(self) -> None:
        self.assertEqual({"max_tokens": 8192, "temperature": 0.5}, chat_completion_controls("deepseek-chat", max_output_tokens=12000, temperature=0.5))
        self.assertEqual({"max_tokens": 12000}, chat_completion_controls("gpt-4o-mini", max_output_tokens=12000))

    def test_json_hint_only_when_needed_and_only_for_deepseek(self) -> None:
        bare = {"response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": "Rewrite this."}]}
        with mock.patch.dict(os.environ, DEEPSEEK):
            out = adapt_request_for_provider(dict(bare))
            self.assertIn("json", out["messages"][0]["content"].lower())
            already = {"response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": "Return JSON."}]}
            self.assertEqual(1, len(adapt_request_for_provider(dict(already))["messages"]))
        with mock.patch.dict(os.environ, OPENAI):
            self.assertEqual(1, len(adapt_request_for_provider(dict(bare))["messages"]))


class ServedModelPricingTests(unittest.TestCase):
    def test_unknown_served_name_falls_back_to_requested_model_price(self) -> None:
        # DeepSeek answers "deepseek-chat" requests as "deepseek-flash" (seen live 2026-10-14).
        from app.services.ai_usage import estimate_call_cost

        self.assertIsNone(estimate_cost_usd("deepseek-flash", 1000, 500))
        self.assertEqual(estimate_cost_usd("deepseek-chat", 1000, 500),
                         estimate_call_cost("deepseek-flash", "deepseek-chat", 1000, 500))
        # A known served name keeps its own price.
        self.assertEqual(estimate_cost_usd("gpt-4o-mini", 1000, 500),
                         estimate_call_cost("gpt-4o-mini-2024-07-18", "chat-latest", 1000, 500))


class DeepSeekRoundTripTests(unittest.TestCase):
    def test_request_shape_and_usage_tracking_against_fake_deepseek(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            body = json.loads(request.content)
            return httpx.Response(200, json={
                "id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500,
                          "prompt_cache_hit_tokens": 400, "prompt_cache_miss_tokens": 600},
            })

        recorded: list[dict] = []

        async def fake_record(**kw):
            recorded.append(kw)

        async def call():
            client = AsyncOpenAI(api_key=llm_api_key(), base_url="https://api.deepseek.com",
                                 http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
            return await client.chat.completions.create(
                model=llm_model("OPENAI_MODEL_WRITE", openai_default="chat-latest"),
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": "Tailor this resume."}],
                **chat_completion_controls("deepseek-chat", max_output_tokens=12000, temperature=0.55),
            )

        with mock.patch.dict(os.environ, DEEPSEEK), mock.patch.object(ai_usage, "record_usage", fake_record):
            asyncio.run(call())
        (req,) = seen
        body = json.loads(req.content)
        self.assertEqual("https://api.deepseek.com/chat/completions", str(req.url))
        self.assertEqual("Bearer ds-key", req.headers["authorization"])
        self.assertEqual("deepseek-chat", body["model"])
        self.assertEqual(8192, body["max_tokens"])
        self.assertIn("json", json.dumps(body["messages"]).lower())  # hint added for DeepSeek JSON mode
        (rec,) = recorded
        self.assertEqual(400, rec["usage"].prompt_cache_hit_tokens)
        # Priced as DeepSeek (cheap), with the cache-hit discount.
        self.assertAlmostEqual(600 * 0.28e-6 + 400 * 0.028e-6 + 500 * 0.42e-6, estimate_cost_usd("deepseek-chat", 1000, 500, 400), places=6)


if __name__ == "__main__":
    unittest.main()
