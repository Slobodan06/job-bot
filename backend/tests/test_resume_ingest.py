import asyncio
import io
import os
import unittest

from docx import Document

from app.services.resume_ingest import (
    _looks_like_bare_location,
    detect_source_format,
    guess_candidate_location,
    ingest_resume,
)
from app.services.resume_ingest_ai import (
    _validated_contact,
    _validated_experience,
    _validated_list,
    _validated_location,
    _validated_skills,
    normalize_resume_model_with_ai,
)
from app.services.resume_model import ResumeContact, ResumeExperienceEntry, ResumeModel


def _sample_docx() -> bytes:
    doc = Document()
    for line in (
        "Cory Stagg",
        "Senior AI || software engineer",
        "coryluistag@gmail.com | +19175401640 | Duncan, South Carolina, United States",
        "https://www.linkedin.com/in/cory-stagg-4751a3422/",
        "PROFESSIONAL SUMMARY",
        "Senior AI & Software Engineer with 10+ years building enterprise platforms.",
        "SKILLS",
        "Frontend: React, Next.js, TypeScript",
        "AI / ML: LLMs, RAG, LangChain",
        "EXPERIENCE",
        "Innolitics | Senior software engineer | Brea, CA | March 2024 - May 2026",
        "Architected enterprise-grade AI platforms leveraging LLMs and RAG.",
        "Built cloud-native infrastructure using AWS, Docker, and Kubernetes.",
        "CVS Health | Senior Software Engineer | October 2020 - February 2024",
        "Architected scalable full-stack applications using React and Node.js.",
        "EDUCATION",
        "Winthrop University | Bachelor's in Software Engineering | Mar 2014 - May 2016",
    ):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class DetectSourceFormatTests(unittest.TestCase):
    def test_pdf_and_zip_magic(self) -> None:
        self.assertEqual("pdf", detect_source_format(b"%PDF-1.7 ...", "resume"))
        self.assertEqual("docx", detect_source_format(b"PK\x03\x04...", "resume.docx"))

    def test_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            detect_source_format(b"random", "resume.rtf")


class CandidateLocationTests(unittest.TestCase):
    def test_recovers_three_part_header_location(self) -> None:
        raw = (
            "Cory Stagg\nSenior AI || software engineer\n"
            "coryluistag@gmail.com | +19175401640 | Duncan, South Carolina, United States\n"
        )
        self.assertEqual("Duncan, South Carolina, United States", guess_candidate_location(raw))

    def test_ignores_job_city(self) -> None:
        raw = "Acme Corp | Senior Engineer | Brea, CA | 01/2020 - Present\n"
        self.assertEqual("", guess_candidate_location(raw))

    def test_recovers_lone_city_token_that_recurs(self) -> None:
        raw = (
            "Darren Byrne\nDublin\n"
            "darrenbyrne.work@hotmail.com | +353 87 123 4567 | Dublin\n"
            "PROFESSIONAL SUMMARY\nSenior Software Engineer.\n"
        )
        self.assertEqual("Dublin", guess_candidate_location(raw))


class BareLocationTitleTests(unittest.TestCase):
    def test_location_headline_is_not_a_title(self) -> None:
        self.assertTrue(_looks_like_bare_location("Dublin - Dublin", "Dublin"))
        self.assertTrue(_looks_like_bare_location("Dublin", "Dublin"))
        self.assertTrue(_looks_like_bare_location("Duncan, South Carolina, United States", ""))

    def test_real_title_is_kept(self) -> None:
        self.assertFalse(_looks_like_bare_location("Senior Software Engineer", "Dublin"))
        self.assertFalse(_looks_like_bare_location("Full-Stack Developer | Cloud Architect", "Dublin"))


class IngestHeuristicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._key = os.environ.pop("OPENAI_API_KEY", None)

    def tearDown(self) -> None:
        if self._key is not None:
            os.environ["OPENAI_API_KEY"] = self._key

    def test_docx_ingest_builds_populated_model(self) -> None:
        model = asyncio.run(ingest_resume(_sample_docx(), filename="cory.docx"))
        self.assertIsInstance(model, ResumeModel)
        self.assertEqual("heuristic", model.meta.normalized_by)
        self.assertEqual("Cory Stagg", model.name)
        self.assertEqual("coryluistag@gmail.com", model.contact.email)
        self.assertIn("linkedin.com/in/cory-stagg", model.contact.linkedin)
        self.assertEqual("Duncan, South Carolina, United States", model.location)
        self.assertGreaterEqual(len(model.professional_experience), 2)
        self.assertEqual("Innolitics", model.professional_experience[0].company)
        self.assertEqual("Brea, CA", model.professional_experience[0].location)
        self.assertTrue(model.education and model.education[0].school.startswith("Winthrop"))

    def test_ai_normalization_noops_without_key(self) -> None:
        model = asyncio.run(ingest_resume(_sample_docx(), filename="cory.docx"))
        out, applied = asyncio.run(normalize_resume_model_with_ai("some text", model))
        self.assertFalse(applied)
        self.assertIs(out, model)


class AiValidationTests(unittest.TestCase):
    source = (
        "cory stagg senior ai software engineer coryluistag@gmail.com "
        "duncan, south carolina, united states "
        "innolitics senior software engineer brea, ca march 2024 - may 2026 "
        "architected enterprise-grade ai platforms leveraging llms and rag "
        "frontend react next.js typescript"
    )

    def test_unsourced_employer_falls_back_to_draft(self) -> None:
        draft = [ResumeExperienceEntry(company="Innolitics", title="Senior Software Engineer", responsibilities=["Architected enterprise-grade AI platforms leveraging LLMs and RAG."])]
        raw = [{"company": "Globex International", "title": "Staff Engineer", "responsibilities": ["Architected enterprise-grade AI platforms leveraging LLMs and RAG."]}]
        out = _validated_experience(raw, draft, self.source)
        self.assertEqual("Innolitics", out[0].company)

    def test_invented_skill_is_dropped(self) -> None:
        out = _validated_skills({"Frontend": ["React", "Rust", "COBOL"]}, {"Frontend": ["React"]}, self.source)
        self.assertEqual(["React"], out["Frontend"])

    def test_candidate_location_kept_when_sourced(self) -> None:
        self.assertEqual(
            "Duncan, South Carolina, United States",
            _validated_location("Duncan, South Carolina, United States", "", self.source),
        )
        self.assertEqual("draft-loc", _validated_location("Mars Base One", "draft-loc", self.source))

    def test_unsourced_email_falls_back(self) -> None:
        draft = ResumeContact(email="coryluistag@gmail.com")
        out = _validated_contact({"email": "attacker@evil.com"}, draft, self.source, self.source)
        self.assertEqual("coryluistag@gmail.com", out.email)

    def test_validated_list_drops_unsourced(self) -> None:
        out = _validated_list(["React and RAG platforms", "Totally invented achievement xyzzy"], ["fallback"], self.source)
        self.assertEqual(["React and RAG platforms"], out)


if __name__ == "__main__":
    unittest.main()
