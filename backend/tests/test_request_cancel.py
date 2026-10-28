"""Clicking Stop (client disconnect) cancels the remaining AI work."""
import asyncio
import unittest

from fastapi import HTTPException

from app.services import request_cancel
from app.services.request_cancel import CLIENT_CLOSED_REQUEST, run_until_disconnect


class _FakeRequest:
    class url:
        path = "/api/tailor"

    def __init__(self, disconnect_after_checks: int | None) -> None:
        self.checks = 0
        self.disconnect_after_checks = disconnect_after_checks

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.disconnect_after_checks is not None and self.checks >= self.disconnect_after_checks


class RunUntilDisconnectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._poll = request_cancel._POLL_SECONDS
        request_cancel._POLL_SECONDS = 0.01

    def tearDown(self) -> None:
        request_cancel._POLL_SECONDS = self._poll

    async def test_returns_result_when_client_stays(self) -> None:
        async def work() -> str:
            await asyncio.sleep(0.03)
            return "resume"

        self.assertEqual("resume", await run_until_disconnect(_FakeRequest(None), work()))

    async def test_disconnect_cancels_work_before_later_ai_calls(self) -> None:
        calls: list[str] = []
        cancelled = asyncio.Event()

        async def work() -> str:
            try:
                calls.append("ingest")
                await asyncio.sleep(10)  # in-flight LLM call
                calls.append("writer")  # never reached
                return "resume"
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with self.assertRaises(HTTPException) as ctx:
            await run_until_disconnect(_FakeRequest(disconnect_after_checks=2), work())
        self.assertEqual(CLIENT_CLOSED_REQUEST, ctx.exception.status_code)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(["ingest"], calls)

    async def test_work_errors_propagate(self) -> None:
        async def work() -> str:
            raise ValueError("No work experience roles detected")

        with self.assertRaises(ValueError):
            await run_until_disconnect(_FakeRequest(None), work())


if __name__ == "__main__":
    unittest.main()
