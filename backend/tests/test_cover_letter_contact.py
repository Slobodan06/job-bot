"""Cover letters must not contain the candidate's email address or phone number."""
import asyncio
import base64
import os
import re
import unittest
from unittest import mock

import fitz  # pymupdf

from app.services.cover_letter import generate_cover_letter, strip_contact_details
from app.services.resume_model import ResumeContact, ResumeExperienceEntry, ResumeModel

EMAIL = "tetianapustovoitova7@gmail.com"
PHONE = "+49 151 2345 6789"
CONTACT_RE = re.compile(r"[\w.+-]+@[\w-]+\.\w+|\d[\d\s().-]{6,}\d")


class StripContactDetailsTests(unittest.TestCase):
    def test_signature_block_lines_are_dropped(self) -> None:
        letter = (
            "Dear Hiring Manager,\n\nI am excited to apply.\n\nSincerely,\nTetiana Pustovoitova\n"
            f"{EMAIL}\n{PHONE}\nEmail: {EMAIL} | Phone: {PHONE}"
        )
        out = strip_contact_details(letter)
        self.assertNotIn(EMAIL, out)
        self.assertNotIn("151", out)
        self.assertTrue(out.endswith("Sincerely,\nTetiana Pustovoitova"), out)

    def test_inline_mentions_are_removed_and_sentence_tidied(self) -> None:
        out = strip_contact_details(f"Please reach me at {EMAIL} or {PHONE}. I look forward to speaking with you.")
        self.assertEqual("Please reach me. I look forward to speaking with you.", out)

    def test_text_without_contact_details_is_unchanged(self) -> None:
        text = "Dear Acme Team,\n\nI improved latency by 38% across 2,000 requests.\n\nBest regards,\nJane Doe"
        self.assertEqual(text, strip_contact_details(text))


class GenerateCoverLetterTests(unittest.TestCase):
    def test_pdf_and_text_have_name_but_no_email_or_phone(self) -> None:
        model = ResumeModel(
            name="Tetiana Pustovoitova",
            contact=ResumeContact(email=EMAIL, phone=PHONE),
            professional_summary="Senior Fullstack Engineer with 10 years of SaaS experience.",
            professional_experience=[
                ResumeExperienceEntry(company="Patients Know Best", title="Senior Fullstack Engineer",
                                      responsibilities=["Led backend services in C# and SQL Server."])
            ],
            technical_skills={"Backend": ["C#", ".NET"]},
        )
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):  # offline template, no OpenAI call
            result = asyncio.run(generate_cover_letter(
                resume_model=model, job_description="Senior .NET engineer for a SaaS platform. " * 5,
                target_job_role="Senior Fullstack Engineer", company_name="WeTransact"))
        pdf = fitz.open(stream=base64.b64decode(result["pdf_base64"]), filetype="pdf")
        pdf_text = "\n".join(page.get_text() for page in pdf)
        for text in (result["cover_letter"], pdf_text):
            self.assertIsNone(CONTACT_RE.search(text), text)
        self.assertIn("Tetiana Pustovoitova", pdf_text)


if __name__ == "__main__":
    unittest.main()
