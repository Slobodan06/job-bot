"""Auto-fill never attaches another job's resume and never pays twice for the same job."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException

from app.applications.logic import job_hash
from app.extension import routes
from app.extension.schemas import AutofillRequest, DetectedJob, TailorForJobRequest

USER = {
    "_id": ObjectId(),
    "email": "a@example.com",
    "base_resume_updated_at": "resume-saved-at",
    "can_use_autofill": True,
    "autofill_profile": {"first_name": "Cory", "last_name": "Stagg"},
}
JOB = DetectedJob(url="https://jobs.example.com/acme/123", text="Backend engineer. " * 10, job_title="Backend")


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_member_without_the_grant_is_refused_before_any_ai_call(self) -> None:
        member = {"_id": ObjectId(), "email": "b@example.com"}
        with patch.object(routes, "build_fresh_tailored_resume", AsyncMock()) as build:
            for call in (
                routes.tailor_for_job(TailorForJobRequest(job=JOB), user=member),
                routes.autofill(AutofillRequest(job=JOB, fields=[]), user=member),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await call
                self.assertEqual(403, ctx.exception.status_code)
        build.assert_not_awaited()


class TailorReuseTests(unittest.IsolatedAsyncioTestCase):
    def _patches(self, found):
        return (
            patch.object(routes, "base_resume_for", AsyncMock(return_value=SimpleNamespace(name="Cory Stagg"))),
            patch.object(routes, "profile_owner", AsyncMock(return_value=USER)),
            patch.object(routes, "find_resume_variant", AsyncMock(side_effect=found)),
            patch.object(routes, "build_fresh_tailored_resume", AsyncMock()),
        )

    async def test_same_job_reuses_the_resume_without_an_ai_call(self) -> None:
        a, b, find, build = self._patches([("pdf1", "cory-stagg.pdf"), ("docx1", "cory-stagg.docx")])
        with a, b, find as find_mock, build as build_mock:
            out = await routes.tailor_for_job(TailorForJobRequest(job=JOB), user=USER)
        build_mock.assert_not_awaited()
        self.assertEqual(("pdf1", "docx1"), (out.resume.variant_id, out.docx_variant_id))
        # Only a variant built since the base resume last changed counts.
        self.assertEqual("resume-saved-at", find_mock.await_args_list[0].kwargs["not_before"])

    async def test_reused_resume_is_renamed_to_the_profile_name(self) -> None:
        a, b, find, build = self._patches([("pdf1", "Cory-resume-tailored.pdf"), ("docx1", "cory-stagg.docx")])
        rename = AsyncMock()
        with a, b, find, build, patch.object(routes, "rename_resume_variant", rename):
            out = await routes.tailor_for_job(TailorForJobRequest(job=JOB), user=USER)
        self.assertEqual("cory-stagg.pdf", out.resume.filename)
        rename.assert_awaited_once_with("pdf1", "cory-stagg.pdf")

    async def test_reuse_works_on_a_form_page_with_no_job_text(self) -> None:
        a, b, find, build = self._patches([("pdf1", "cory-stagg.pdf"), None])
        job = DetectedJob(url=JOB.url, text="")
        with a, b, find, build:
            out = await routes.tailor_for_job(TailorForJobRequest(job=job), user=USER)
        self.assertEqual(("pdf1", ""), (out.resume.variant_id, out.docx_variant_id))


class AutofillAttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_a_variant_only_this_jobs_resume_is_looked_up(self) -> None:
        find = AsyncMock(return_value=None)
        with patch.object(routes, "profile_owner", AsyncMock(return_value=USER)), \
                patch.object(routes, "get_base_resume_model", return_value=None), \
                patch.object(routes, "draft_free_text_answers", AsyncMock(return_value=({}, {}))), \
                patch.object(routes, "find_resume_variant", find):
            out = await routes.autofill(AutofillRequest(job=JOB, fields=[]), user=USER)
        self.assertIsNone(out.resume)
        self.assertEqual(job_hash(JOB.url), find.await_args.kwargs["job_hash"])


if __name__ == "__main__":
    unittest.main()
