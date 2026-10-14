"""OpenAI usage tracking — exercised against a fake OpenAI server (no network, no credits)."""
import asyncio
import json
import os
import unittest
from unittest import mock

import httpx
from openai import AsyncOpenAI

from app.services import ai_usage
from app.services.ai_usage import estimate_cost_usd, feature_for_path

ai_usage.install_openai_usage_tracking()


def _completion(model: str) -> dict:
    return {
        "id": "c1", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
    }


def _stream_body(model: str, with_usage: bool) -> bytes:
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": model,
         "choices": [{"index": 0, "delta": {"content": word}, "finish_reason": None}]}
        for word in ("Hello ", "world")
    ]
    if with_usage:
        chunks.append({"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": model, "choices": [],
                       "usage": {"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250}})
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


class FakeOpenAI:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if body.get("stream"):
            include = (body.get("stream_options") or {}).get("include_usage", False)
            return httpx.Response(200, content=_stream_body(body["model"], include),
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=_completion(body["model"]))

    def client(self) -> AsyncOpenAI:
        return AsyncOpenAI(api_key="sk-test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handler)))


class PricingTests(unittest.TestCase):
    def test_known_models_and_dated_snapshots(self) -> None:
        self.assertAlmostEqual(0.00045, estimate_cost_usd("gpt-4o-mini", 1000, 500))
        self.assertEqual(estimate_cost_usd("gpt-4o-mini-2024-07-18", 1000, 500), estimate_cost_usd("gpt-4o-mini", 1000, 500))
        # Longest prefix wins: gpt-4o-mini is not priced as gpt-4o.
        self.assertNotEqual(estimate_cost_usd("gpt-4o-mini", 10**6, 0), estimate_cost_usd("gpt-4o", 10**6, 0))

    def test_unknown_model_is_unpriced_and_override_works(self) -> None:
        self.assertIsNone(estimate_cost_usd("some-new-model", 1000, 1000))
        with mock.patch.dict(os.environ, {"OPENAI_PRICING_JSON": '{"some-new-model": [1, 2]}'}):
            self.assertAlmostEqual(0.003, estimate_cost_usd("some-new-model", 1000, 1000))

    def test_feature_labels(self) -> None:
        self.assertEqual("Tailored resume", feature_for_path("/api/tailor"))
        self.assertEqual("Tailored resume (extension)", feature_for_path("/api/extension/tailor"))
        self.assertEqual("Application questions", feature_for_path("/api/application-answer"))
        self.assertEqual("Background task", feature_for_path(""))


class TrackingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recorded: list[dict] = []

        async def fake_record(**kw):
            self.recorded.append(kw)

        patcher = mock.patch.object(ai_usage, "record_usage", fake_record)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = FakeOpenAI()

    def _run(self, coro):
        async def wrapped():
            ai_usage._current_user.set("user-1")
            ai_usage._current_path.set("/api/cover-letter")
            return await coro()
        return asyncio.run(wrapped())

    def test_plain_completion_is_recorded_for_the_user(self) -> None:
        async def call():
            return await self.fake.client().chat.completions.create(
                model="gpt-4o-mini", messages=[{"role": "user", "content": "x"}])
        resp = self._run(call)
        self.assertEqual("hi", resp.choices[0].message.content)  # caller unaffected
        (rec,) = self.recorded
        self.assertEqual(("user-1", "/api/cover-letter", "gpt-4o-mini"), (rec["user_id"], rec["path"], rec["model"]))
        self.assertEqual(1500, rec["usage"].total_tokens)

    def test_stream_requests_usage_and_records_it_after_the_last_chunk(self) -> None:
        async def call():
            stream = await self.fake.client().chat.completions.create(
                model="gpt-4o-mini", messages=[{"role": "user", "content": "x"}], stream=True)
            text = ""
            async for chunk in stream:
                if chunk.choices:
                    text += chunk.choices[0].delta.content or ""
            return text
        self.assertEqual("Hello world", self._run(call))  # stream content unchanged
        self.assertEqual({"include_usage": True}, self.fake.requests[0]["stream_options"])
        (rec,) = self.recorded
        self.assertEqual(250, rec["usage"].total_tokens)


if __name__ == "__main__":
    unittest.main()
