from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.qualification_questions import (
    build_qualification_questions,
    default_professional_role_index,
)
from app.services.resume_evidence import (
    SourceFact,
    analyze_job_description,
    build_canonical_skills_section,
    create_evidence_map,
)


HRA_JD = """
AI Engineer
Build and maintain production AI tooling that turns unstructured documents into structured, verifiable data.
Write production Python that moves data between source systems and SQL Server.
Build LLM-powered document generation from structured inputs.
Required: 3+ years production Python and 2+ years SQL.
Required: hands-on Claude or OpenAI API experience with prompt design, structured JSON, PDF inputs,
multi-block responses, validation, guardrails, and monitoring.
Preferred: T-SQL, stored procedures, schema design, query tuning, agentic workflows, state management,
healthcare, HIPAA, PHI, Azure, Git, and CI/CD.
"""


class QualificationQuestionTests(unittest.TestCase):
    def _questions(self, facts: list[SourceFact]) -> list[dict]:
        analysis = analyze_job_description(HRA_JD)
        evidence = create_evidence_map(analysis, facts)
        return build_qualification_questions(
            job_description=HRA_JD,
            facts=facts,
            evidence_map=evidence,
        )

    def test_hra_skill_only_resume_gets_targeted_skill_and_experience_topics(self) -> None:
        facts = [
            SourceFact(
                "skills_001",
                "Python, FastAPI, OpenAI API, SQL Server, Azure, healthcare, HIPAA, PHI",
                "candidate_resume",
            ),
            SourceFact(
                "exp_001_bullet_001",
                "Built Node.js services for healthcare workflows and tuned SQL Server queries.",
                "candidate_resume",
                experience_id="exp_001",
            ),
        ]
        questions = self._questions(facts)
        ids = [question["id"] for question in questions]
        self.assertEqual(
            [
                "llm_production",
                "document_processing",
                "production_python",
                "sql_server_depth",
                "llm_failure_guardrail",
                "regulated_data",
                "cloud_release",
            ],
            ids,
        )
        self.assertTrue(all(not question["details_required_when_yes"] for question in questions))
        self.assertTrue(all(question["confirmation_claim"].startswith("Candidate confirms") for question in questions))
        self.assertTrue(all(question["example_answer"].startswith("FICTIONAL EXAMPLE") for question in questions))
        self.assertTrue(all(question["example_skills"].startswith("FICTIONAL SKILLS EXAMPLE") for question in questions))
        self.assertTrue(all(question["skills_prompt"] for question in questions))

    def test_practical_evidence_suppresses_questions_already_answered_by_resume(self) -> None:
        facts = [
            SourceFact(
                "exp_001_bullet_001",
                "Built production Python services using OpenAI API prompt design to parse PDFs into structured JSON.",
                "candidate_resume",
                experience_id="exp_001",
            ),
            SourceFact(
                "exp_001_bullet_002",
                "Validated output against source documents, monitored failures, and used human review guardrails.",
                "candidate_resume",
                experience_id="exp_001",
            ),
            SourceFact(
                "exp_001_bullet_003",
                "Implemented T-SQL stored procedures, schema design, indexing, and query tuning in SQL Server.",
                "candidate_resume",
                experience_id="exp_001",
            ),
            SourceFact(
                "exp_001_bullet_004",
                "Built agentic workflows with orchestration and state management on Azure using Git and CI/CD.",
                "candidate_resume",
                experience_id="exp_001",
            ),
        ]
        ids = {question["id"] for question in self._questions(facts)}
        self.assertNotIn("llm_production", ids)
        self.assertNotIn("document_processing", ids)
        self.assertNotIn("production_python", ids)
        self.assertNotIn("sql_server_depth", ids)

    def test_confirmed_modern_ai_and_document_tools_reach_rich_skills_section(self) -> None:
        confirmed = (
            "At CVS Health I used Azure OpenAI, LangGraph, Model Context Protocol, Pinecone, PyMuPDF, "
            "Azure Document Intelligence, multi-block responses, stored procedures, schema design, and query tuning."
        )
        fact = SourceFact("user_verified_001", confirmed, "candidate_verified_answer")
        skills, _audit = build_canonical_skills_section(
            source_skills="Python, SQL Server",
            job_description=HRA_JD,
            facts=[fact, SourceFact("skills_001", "Python, SQL Server", "candidate_resume")],
            final_experience=confirmed,
        )
        for expected in (
            "Azure OpenAI",
            "LangGraph",
            "Model Context Protocol (MCP)",
            "Pinecone",
            "PyMuPDF",
            "Azure Document Intelligence",
            "Multi-Block Response Handling",
            "Stored Procedures",
            "Database Schema Design",
            "Query Tuning",
        ):
            self.assertIn(expected, skills)

    def test_detailed_unscoped_answer_defaults_to_newest_existing_role(self) -> None:
        roles = [SimpleNamespace(company="Older"), SimpleNamespace(company="Newest")]
        self.assertEqual(
            1,
            default_professional_role_index("I built a production Python document workflow.", roles),
        )
        self.assertIsNone(
            default_professional_role_index("Candidate confirms production Python experience.", roles)
        )


if __name__ == "__main__":
    unittest.main()
