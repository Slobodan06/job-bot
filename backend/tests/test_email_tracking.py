import unittest
from datetime import UTC, datetime

from app.applications.email_tracking import (
    heuristic_stage,
    looks_job_related,
    match_application,
    normalize_company,
    parse_results,
    received_in_window,
)
from app.applications.logic import advances_status


def _email(**kw):
    return {"key": "k", "from_name": "", "from_email": "", "subject": "", "snippet": "", "body": "", **kw}


class EmailTrackingTests(unittest.TestCase):
    def test_prefilter(self) -> None:
        self.assertTrue(looks_job_related(_email(from_email="no-reply@us.greenhouse-mail.io")))
        self.assertTrue(looks_job_related(_email(subject="Your application to Acme")))
        self.assertFalse(looks_job_related(_email(from_name="Amazon", subject="Your order has shipped")))

    def test_heuristic_stages(self) -> None:
        self.assertEqual(
            "rejection",
            heuristic_stage(_email(body="Thank you for applying. Unfortunately we will not be moving forward.")),
        )
        self.assertEqual("application", heuristic_stage(_email(subject="Thank you for applying to Acme")))
        self.assertEqual("assessment", heuristic_stage(_email(body="Please complete the HackerRank challenge")))
        self.assertEqual("interview", heuristic_stage(_email(subject="Interview invitation - Backend Engineer")))
        self.assertEqual("offer", heuristic_stage(_email(body="We are pleased to offer you the position")))
        self.assertEqual("other", heuristic_stage(_email(subject="Weekly newsletter")))

    def test_normalize_company(self) -> None:
        self.assertEqual("acme", normalize_company("ACME, Inc."))
        self.assertEqual("stripe", normalize_company("Stripe Recruiting"))

    def test_match_by_company_and_title(self) -> None:
        apps = [
            {"_id": 1, "company": "Acme Inc", "job_title": "Frontend Engineer"},
            {"_id": 2, "company": "Acme", "job_title": "Senior Backend Engineer"},
            {"_id": 3, "company": "Globex", "job_title": "Backend Engineer"},
        ]
        found = match_application(apps, _email(), company="ACME Corp", job_title="Backend Engineer")
        self.assertEqual(2, found["_id"])
        found = match_application(apps, _email(subject="Update on your Globex application"))
        self.assertEqual(3, found["_id"])
        self.assertIsNone(match_application(apps, _email(subject="Hello"), company="Initech"))

    def test_old_email_is_not_applied(self) -> None:
        app = {"created_at": datetime(2026, 10, 10)}
        self.assertFalse(received_in_window(app, datetime(2026, 9, 1, tzinfo=UTC)))
        self.assertTrue(received_in_window(app, datetime(2026, 10, 9, tzinfo=UTC)))
        self.assertTrue(received_in_window(app, None))

    def test_parse_results_validates(self) -> None:
        out = parse_results(
            {"results": [{"i": 0, "stage": "Interview", "a": 1}, {"i": 1, "stage": "bogus", "a": 9}, {"i": 7}]},
            n_emails=2,
            n_apps=2,
        )
        self.assertEqual(("interview", 1), (out[0]["stage"], out[0]["a"]))
        self.assertEqual(("other", None), (out[1]["stage"], out[1]["a"]))

    def test_status_only_moves_forward(self) -> None:
        self.assertTrue(advances_status("submitted", "assessment"))
        self.assertTrue(advances_status("assessment", "interviewing"))
        self.assertFalse(advances_status("interviewing", "submitted"))
        self.assertFalse(advances_status("withdrawn", "rejected"))


if __name__ == "__main__":
    unittest.main()
