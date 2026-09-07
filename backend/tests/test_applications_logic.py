import unittest
from datetime import UTC, datetime

from app.applications.logic import (
    APPLICATION_STATUSES,
    application_doc_to_public,
    build_application_doc,
    detect_ats,
    is_valid_status,
    job_hash,
    normalize_job_url,
)


class JobUrlTests(unittest.TestCase):
    def test_normalize_strips_tracking_and_fragment(self) -> None:
        a = normalize_job_url("https://boards.greenhouse.io/acme/jobs/123?utm_source=x&gh_jid=123#app")
        b = normalize_job_url("http://boards.greenhouse.io/acme/jobs/123/?gh_jid=123")
        self.assertEqual(a, b)
        self.assertEqual(job_hash(a), job_hash(b))

    def test_different_postings_differ(self) -> None:
        self.assertNotEqual(
            job_hash("https://jobs.lever.co/acme/aaa"),
            job_hash("https://jobs.lever.co/acme/bbb"),
        )

    def test_detect_ats(self) -> None:
        self.assertEqual("greenhouse", detect_ats("https://boards.greenhouse.io/x/jobs/1"))
        self.assertEqual("lever", detect_ats("https://jobs.lever.co/x/y"))
        self.assertEqual("workday", detect_ats("https://acme.wd5.myworkdayjobs.com/x"))
        self.assertEqual("other", detect_ats("https://careers.acme.com/x"))


class ApplicationDocTests(unittest.TestCase):
    def test_status_validation(self) -> None:
        self.assertTrue(all(is_valid_status(s) for s in APPLICATION_STATUSES))
        self.assertFalse(is_valid_status("bogus"))

    def test_build_doc_defaults_and_clips(self) -> None:
        now = datetime.now(UTC)
        doc = build_application_doc(
            user_id="u1",
            payload={
                "job_url": "https://jobs.lever.co/acme/xyz",
                "company": "  Acme  ",
                "job_title": "Engineer",
                "status": "not-a-status",
                "jd_text": "x" * 50000,
            },
            now=now,
        )
        self.assertEqual("u1", doc["user_id"])
        self.assertEqual("lever", doc["ats"])
        self.assertEqual("Acme", doc["company"])
        self.assertEqual("detected", doc["status"])
        self.assertEqual(40000, len(doc["jd_text"]))
        self.assertIsNone(doc["submitted_at"])

    def test_submitted_sets_timestamp(self) -> None:
        now = datetime.now(UTC)
        doc = build_application_doc(
            user_id="u1",
            payload={"job_url": "https://x.com/j/1", "status": "submitted"},
            now=now,
        )
        self.assertEqual(now, doc["submitted_at"])

    def test_public_shape(self) -> None:
        now = datetime.now(UTC)
        doc = build_application_doc(user_id="u1", payload={"job_url": "https://x.com/j/1"}, now=now)
        doc["_id"] = "abc123"
        pub = application_doc_to_public(doc)
        self.assertEqual({"id", "job_url", "ats", "company", "job_title", "location", "status",
                          "resume_variant_id", "notes", "answers", "scores", "created_at",
                          "updated_at", "submitted_at"}, set(pub))


if __name__ == "__main__":
    unittest.main()
