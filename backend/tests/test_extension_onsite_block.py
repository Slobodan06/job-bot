"""Auto-fill refuses hybrid and on-site jobs before spending anything; remote jobs go through."""
import unittest
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException

from app.extension import routes
from app.extension.schemas import AutofillRequest, DetectedJob, TailorForJobRequest

USER = {"_id": ObjectId(), "email": "a@example.com", "can_use_autofill": True}
BODY = "We build payment APIs in Python and Go. You will own services end to end. "


def _job(text: str, location: str = "") -> DetectedJob:
    return DetectedJob(url="https://jobs.example.com/acme/1", text=BODY * 3 + text, job_title="Backend", location=location)


class OnsiteBlockTests(unittest.IsolatedAsyncioTestCase):
    async def _blocked(self, job: DetectedJob) -> HTTPException:
        with patch.object(routes, "base_resume_for", AsyncMock()) as base, \
                patch.object(routes, "build_fresh_tailored_resume", AsyncMock()) as build:
            with self.assertRaises(HTTPException) as ctx:
                await routes.tailor_for_job(TailorForJobRequest(job=job), user=USER)
        base.assert_not_awaited()
        build.assert_not_awaited()
        return ctx.exception

    async def test_hybrid_role_is_blocked_with_the_evidence(self) -> None:
        err = await self._blocked(_job("This is a hybrid role, three days a week in our Austin office."))
        self.assertEqual(422, err.status_code)
        self.assertEqual(routes.ONSITE_BLOCKED, err.detail["code"])
        self.assertIn("hybrid role", err.detail["message"])
        self.assertIn("three days a week", err.detail["message"])

    async def test_onsite_role_is_blocked(self) -> None:
        err = await self._blocked(_job("This position is on-site at our Denver headquarters."))
        self.assertIn("on-site role", err.detail["message"])

    async def test_location_saying_onsite_is_enough(self) -> None:
        await self._blocked(_job("", location="San Francisco (On-site)"))

    async def test_autofill_is_blocked_too(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await routes.autofill(AutofillRequest(job=_job("Hybrid schedule required."), fields=[]), user=USER)
        self.assertEqual(routes.ONSITE_BLOCKED, ctx.exception.detail["code"])

    def test_remote_jobs_pass(self) -> None:
        for text in (
            "This role is fully remote within the US.",
            "Remote or hybrid, your choice.",
            "We meet for an annual on-site team summit.",
            "Experience with hybrid cloud infrastructure is a plus.",
        ):
            routes._require_remote_role(_job(text))  # no exception


if __name__ == "__main__":
    unittest.main()
