from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.resume_evidence import (
    SourceFact,
    analyze_job_description,
    assert_render_provenance,
    build_canonical_skills_section,
    build_gap_report,
    build_verified_candidate_facts,
    bullet_experience_id,
    bullet_text,
    create_evidence_map,
    evaluate_eligibility,
    filter_supported_bullets,
    is_experience_section_placeholder,
    normalize_generated_skills,
    parse_verified_answer_facts,
    rank_source_bullets_for_job,
    select_nonduplicative_bullets,
    unsupported_terms_for_claim,
    validate_tailored_resume,
)


class ResumeEvidenceTests(unittest.TestCase):
    def test_professional_experience_heading_is_not_a_job_role(self) -> None:
        placeholder = SimpleNamespace(
            company="Professional Experience",
            title="Professional Experience",
            period="",
            location="",
        )
        self.assertTrue(is_experience_section_placeholder(placeholder))

    def test_real_role_is_not_removed_by_section_heading_filter(self) -> None:
        role = SimpleNamespace(
            company="Fyresite",
            title="Senior Shopify Engineer",
            period="05/2024 - 04/2026",
            location="Remote",
        )
        self.assertFalse(is_experience_section_placeholder(role))

    def test_generated_skill_array_normalizes_to_clean_category_lines(self) -> None:
        value = [
            "AI Engineering: Python, OpenAI API, Structured JSON",
            "Databases: SQL Server, T-SQL",
        ]
        self.assertEqual(
            "AI Engineering: Python, OpenAI API, Structured JSON\nDatabases: SQL Server, T-SQL",
            normalize_generated_skills(value),
        )

    def test_stringified_skill_array_does_not_render_brackets_or_quotes(self) -> None:
        normalized = normalize_generated_skills(
            "['AI Engineering: Python, OpenAI API', 'Databases: SQL Server, T-SQL']"
        )
        self.assertNotIn("[", normalized)
        self.assertNotIn("'", normalized)
        self.assertEqual(2, len(normalized.splitlines()))

    def test_openai_api_not_added_from_chatgpt_usage(self) -> None:
        facts = [SourceFact("skills_001", "Used ChatGPT as a coding assistant for productivity.", "candidate_resume")]
        self.assertIn("production LLM API experience", unsupported_terms_for_claim("Integrated OpenAI API in production.", facts))

    def test_sql_server_requested_postgresql_is_gap(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Built reporting queries with PostgreSQL.", "candidate_resume")]
        job = analyze_job_description("Required: SQL Server and T-SQL experience.")
        evidence = create_evidence_map(job, facts)
        gaps = "\n".join(build_gap_report(evidence))
        self.assertIn("SQL Server", gaps)
        self.assertIn("T-SQL", gaps)
        self.assertIn("SQL Server/T-SQL", unsupported_terms_for_claim("Optimized SQL Server stored procedures.", facts))

    def test_hipaa_not_claimed_from_healthcare_frontend(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Built React frontend screens for a healthcare scheduling product.", "candidate_resume")]
        self.assertEqual([], unsupported_terms_for_claim("Built healthcare frontend screens.", facts))
        self.assertIn("HIPAA/PHI", unsupported_terms_for_claim("Handled HIPAA and PHI requirements.", facts))

    def test_duplicate_bullets_flagged(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Built Python APIs for order processing.", "candidate_resume")]
        result = validate_tailored_resume(
            summary="Python developer.",
            skills="Programming Languages: Python",
            bullets_by_role=[["Built Python APIs for order processing.", "Built Python APIs for order processing."]],
            facts=facts,
        )
        self.assertTrue(any("Duplicate" in issue["reason"] for issue in result["issues"]))

    def test_malformed_text_excluded(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Built Python APIs.", "candidate_resume")]
        bullets = filter_supported_bullets(["ÃÃÃ broken text"], ["ÃÃÃ broken text", "Built Python APIs."], facts, role_index=0, wanted=2)
        self.assertEqual(["Built Python APIs."], [bullet_text(bullet) for bullet in bullets])
        self.assertEqual(["exp_001"], [bullet_experience_id(bullet) for bullet in bullets])

    def test_metric_must_be_preserved_exactly(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Improved checkout speed by 20%.", "candidate_resume")]
        self.assertEqual([], unsupported_terms_for_claim("Improved checkout speed by 20%.", facts))
        self.assertIn("40%", unsupported_terms_for_claim("Improved checkout speed by 40%.", facts))

    def test_verified_clarification_can_support_claim(self) -> None:
        facts = parse_verified_answer_facts([
            {"question": "Did you use Microsoft SQL Server?", "answer": "Yes, I used SQL Server for reporting views."}
        ])
        self.assertTrue(facts[0].fact_id.startswith("user_verified_"))
        self.assertEqual([], unsupported_terms_for_claim("Used SQL Server for reporting views.", facts))

    def test_ai_engineering_summary_downgraded_without_production_ai(self) -> None:
        facts = [SourceFact("skills_001", "Used AI-assisted coding tools for development productivity.", "candidate_resume")]
        self.assertIn("AI engineering title/identity", unsupported_terms_for_claim("AI Engineer building production systems.", facts))

    def test_job_only_skill_omitted_from_canonical_skills(self) -> None:
        facts = [SourceFact("skills_001", "Python, PostgreSQL", "candidate_resume")]
        skills, audit = build_canonical_skills_section(
            source_skills="Python, PostgreSQL",
            job_description="Required: Python, OpenAI API, SQL Server",
            facts=facts,
            final_experience="Built Python services with PostgreSQL.",
        )
        self.assertIn("Python", skills)
        self.assertNotIn("OpenAI API", skills)
        self.assertNotIn("SQL Server", skills)
        self.assertTrue(audit)

    def test_candidate_role_metric_extraction_keeps_exact_metric(self) -> None:
        role = SimpleNamespace(
            company="Acme",
            title="Developer",
            location="",
            period="2020 - 2022",
            header="Developer | Acme | 2020 - 2022",
            bullets=["Reduced checkout latency by 30% using React profiling."],
        )
        facts = build_verified_candidate_facts(contact="", summary="", skills="React", roles=[role], education="", other="")
        self.assertEqual("exp_001_bullet_001", facts[-1].fact_id)
        self.assertEqual([], unsupported_terms_for_claim("Reduced checkout latency by 30% using React profiling.", facts))
        self.assertIn("50%", unsupported_terms_for_claim("Reduced checkout latency by 50% using React profiling.", facts))

    def test_job_description_keyword_cannot_leak_into_bullet(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Built PostgreSQL reporting queries.", "candidate_resume")]
        generated = ["Built SQL Server reporting queries for regulated healthcare data."]
        bullets = filter_supported_bullets(generated, ["Built PostgreSQL reporting queries."], facts, role_index=0, wanted=2)
        self.assertEqual(["Built PostgreSQL reporting queries."], [bullet_text(bullet) for bullet in bullets])

    def test_noncanonical_skill_category_fails_validation(self) -> None:
        facts = [SourceFact("skills_001", "Python", "candidate_resume")]
        result = validate_tailored_resume(
            summary="Python developer.",
            skills="AI & LLM: Python",
            bullets_by_role=[["Built Python APIs."]],
            facts=facts,
        )
        self.assertEqual("FAIL", result["status"])
        self.assertTrue(any("non-canonical" in issue["reason"] for issue in result["issues"]))

    def test_location_eligibility_flagged_separately(self) -> None:
        facts = [SourceFact("contact_001", "Candidate based in Toronto, Canada.", "candidate_resume")]
        job = analyze_job_description("Must be based in Austin, Texas. Work authorization required.")
        eligibility = evaluate_eligibility(job, facts)
        self.assertEqual("possibly_ineligible", eligibility["eligibilityStatus"])

    def test_rag_job_keyword_missing_not_skill(self) -> None:
        facts = [SourceFact("skills_001", "Python, Java, AWS, PostgreSQL", "candidate_resume")]
        skills, _audit = build_canonical_skills_section(
            source_skills="Python, Java, AWS, PostgreSQL",
            job_description="Required: RAG, OpenAI API, Python",
            facts=facts,
            final_experience="Built Python services on AWS with PostgreSQL.",
        )
        self.assertIn("Python", skills)
        self.assertNotIn("RAG", skills)
        self.assertNotIn("OpenAI API", skills)

    def test_azure_job_keyword_missing_but_aws_retained(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Deployed services on AWS with CI/CD.", "candidate_resume")]
        skills, _audit = build_canonical_skills_section(
            source_skills="AWS, CI/CD",
            job_description="Required: Azure cloud deployment and CI/CD.",
            facts=facts,
            final_experience="Deployed services on AWS with CI/CD.",
        )
        self.assertIn("AWS", skills)
        self.assertIn("CI/CD", skills)
        self.assertNotIn("Azure", skills)

    def test_sql_server_missing_but_postgresql_retained_as_transferable(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Built analytics queries with PostgreSQL.", "candidate_resume")]
        skills, _audit = build_canonical_skills_section(
            source_skills="PostgreSQL",
            job_description="Required: SQL Server database development.",
            facts=facts,
            final_experience="Built analytics queries with PostgreSQL.",
        )
        self.assertIn("PostgreSQL", skills)
        self.assertNotIn("SQL Server", skills)

    def test_metric_cannot_be_reassigned_to_postgresql(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Improved frontend responsiveness by 30% using React profiling.", "candidate_resume")]
        result = validate_tailored_resume(
            summary="Frontend developer.",
            skills="Frontend: React",
            bullets_by_role=[["Improved PostgreSQL performance by 30% for reporting queries."]],
            facts=facts,
        )
        self.assertEqual("FAIL", result["status"])
        self.assertTrue(any("database performance" in issue["reason"] for issue in result["issues"]))

    def test_candidate_confirmed_document_metric_remains_attached_to_document_work(self) -> None:
        fact = SourceFact(
            "user_verified_001",
            "Developed a PDF intake pipeline using PyMuPDF and Azure Document Intelligence to extract claim fields into structured JSON and persist verified records to SQL Server. Schema checks and a review queue cut average processing time from 20 minutes to 6 minutes per claim.",
            "candidate_verified_answer",
            experience_id="exp_001",
        )
        bullet = {
            "text": "Developed a PDF intake pipeline using PyMuPDF and Azure Document Intelligence, persisting verified JSON to SQL Server and reducing claim processing from 20 minutes to 6 minutes.",
            "experienceId": "exp_001",
            "sourceIds": [fact.fact_id],
            "sourceFactIds": [fact.fact_id],
            "sourceBulletIds": [],
            "metricIds": [],
        }
        result = validate_tailored_resume(
            summary="Software engineer.",
            skills="Programming Languages: Python",
            bullets_by_role=[[bullet]],
            facts=[fact, SourceFact("skills_001", "Python", "candidate_resume")],
        )
        self.assertEqual("PASS", result["status"], result["issues"])

    def test_original_and_rewritten_equivalent_not_both_selected(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Built Python APIs for order processing.", "candidate_resume")]
        selected = select_nonduplicative_bullets(
            [],
            [["Built Python APIs for order processing.", "Developed Python APIs supporting order processing."]],
            facts,
            max_total=18,
        )
        self.assertEqual(1, len(selected[0]))

    def test_total_bullet_limit_enforced(self) -> None:
        facts = [SourceFact(f"exp_001_bullet_{i:03d}", f"Built Python API endpoint {i}.", "candidate_resume") for i in range(1, 30)]
        selected = select_nonduplicative_bullets(
            [object()],
            [[f"Built Python API endpoint {i}." for i in range(1, 30)]],
            facts,
            max_total=5,
        )
        self.assertLessEqual(sum(len(role) for role in selected), 5)

    def test_spain_candidate_united_states_job_flagged_blocking(self) -> None:
        facts = [SourceFact("contact_001", "Valencia, Spain", "candidate_resume")]
        job = analyze_job_description("Must be based in the United States. Work authorization required.")
        eligibility = evaluate_eligibility(job, facts)
        self.assertEqual("possibly_ineligible", eligibility["eligibilityStatus"])

    def test_bullet_from_role_a_cannot_render_under_role_b(self) -> None:
        roles = [SimpleNamespace(company="A"), SimpleNamespace(company="B")]
        bullet = {
            "text": "Built Python APIs for role A.",
            "experienceId": "exp_001",
            "sourceIds": ["exp_001_bullet_001"],
            "sourceBulletIds": ["exp_001_bullet_001"],
        }
        with self.assertRaises(ValueError):
            assert_render_provenance(roles, [[], [bullet]])

    def test_metric_from_role_a_cannot_render_under_role_b(self) -> None:
        facts = [
            SourceFact("exp_001_bullet_001", "Reduced incidents by 30% with CI/CD.", "candidate_resume", experience_id="exp_001"),
            SourceFact("exp_002_bullet_001", "Built Python APIs.", "candidate_resume", experience_id="exp_002"),
        ]
        result = validate_tailored_resume(
            summary="Software engineer.",
            skills="Programming Languages: Python",
            bullets_by_role=[
                [],
                [{
                    "text": "Reduced incidents by 30% with CI/CD.",
                    "experienceId": "exp_002",
                    "sourceIds": ["exp_002_bullet_001"],
                    "sourceBulletIds": ["exp_002_bullet_001"],
                    "metricIds": ["exp_001_bullet_001_metric_001"],
                }],
            ],
            facts=facts,
        )
        self.assertEqual("FAIL", result["status"])
        self.assertTrue(any("Metric belongs to a different" in issue["reason"] for issue in result["issues"]))

    def test_ranking_preserves_experience_id(self) -> None:
        job = analyze_job_description("Required: Python and PostgreSQL.")
        ranked = rank_source_bullets_for_job(["Built Python APIs with PostgreSQL."], job, experience_id="exp_004")
        self.assertEqual("exp_004", ranked[0]["experienceId"])
        self.assertEqual("exp_004_bullet_001", ranked[0]["sourceBulletId"])

    def test_job_analysis_extracts_experience_education_and_soft_skills(self) -> None:
        job = analyze_job_description(
            "Required: 5+ years of backend software experience. Bachelor's degree in Computer Science. "
            "Must communicate with stakeholders and own delivery. Required: Python and AWS."
        )
        self.assertEqual(5, job["experienceRequirements"][0]["years"])
        self.assertIn("Bachelor", job["educationRequirements"][0]["text"])
        soft = {item["name"].lower() for item in job["softSkills"]}
        self.assertIn("stakeholder management", soft)
        self.assertIn("ownership", soft)

    def test_candidate_owned_document_ai_skills_are_available(self) -> None:
        facts = [
            SourceFact(
                "exp_001_bullet_001",
                "Built PDF parsing with structured JSON output, prompt design, output validation, and guardrails.",
                "candidate_resume",
            ),
            SourceFact("skills_001", "Python, JavaScript", "candidate_resume"),
        ]
        skills, _audit = build_canonical_skills_section(
            source_skills="Python, JavaScript",
            job_description="Build LLM document tooling with PDF inputs, structured JSON, prompt design, and guardrails.",
            facts=facts,
            final_experience=facts[0].text,
        )
        self.assertIn("JavaScript", skills)
        self.assertIn("PDF Parsing", skills)
        self.assertIn("Structured Outputs", skills)
        self.assertIn("LLM Guardrails", skills)

    def test_rewriting_filter_preserves_experience_id(self) -> None:
        facts = [SourceFact("exp_002_bullet_001", "Built Java APIs.", "candidate_resume", experience_id="exp_002")]
        bullets = filter_supported_bullets(
            [{"generated_text": "Built Java APIs.", "source_fact_ids": ["exp_002_bullet_001"], "unsupported_terms": []}],
            ["Built Java APIs."],
            facts,
            role_index=1,
            wanted=1,
        )
        self.assertEqual("exp_002", bullet_experience_id(bullets[0]))

    def test_rendering_groups_only_by_immutable_experience_id(self) -> None:
        roles = [SimpleNamespace(company="A"), SimpleNamespace(company="B")]
        bullets = [
            [{"text": "Built Python APIs.", "experienceId": "exp_001", "sourceIds": ["exp_001_bullet_001"], "sourceBulletIds": ["exp_001_bullet_001"]}],
            [{"text": "Built Java APIs.", "experienceId": "exp_002", "sourceIds": ["exp_002_bullet_001"], "sourceBulletIds": ["exp_002_bullet_001"]}],
        ]
        assert_render_provenance(roles, bullets)

    def test_jd_only_skill_audit_source_is_candidate_only(self) -> None:
        facts = [SourceFact("skills_001", "Python", "candidate_resume")]
        skills, audit = build_canonical_skills_section(
            source_skills="Python",
            job_description="Required: Python and Azure.",
            facts=facts,
            final_experience="Built Python services.",
        )
        self.assertIn("Python", skills)
        self.assertNotIn("Azure", skills)
        self.assertTrue(all(item["sourceType"] in {"candidate_resume", "candidate_verified_answer"} for item in audit))

    def test_ai_assisted_does_not_become_rag_or_llm_api(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Used AI-assisted workflows to review code.", "candidate_resume")]
        self.assertIn("production LLM API experience", unsupported_terms_for_claim("Built production LLM API and RAG workflows.", facts))

    def test_role_compression_keeps_multiple_recent_relevant_bullets(self) -> None:
        roles = [SimpleNamespace(company="Old"), SimpleNamespace(company="Recent")]
        facts = [
            SourceFact(f"exp_002_bullet_{i:03d}", f"Built Python API endpoint {i} with PostgreSQL.", "candidate_resume", experience_id="exp_002")
            for i in range(1, 6)
        ]
        bullets = [
            [{"text": "Maintained legacy UI.", "experienceId": "exp_001", "sourceIds": ["exp_001_bullet_001"], "sourceBulletIds": ["exp_001_bullet_001"]}],
            [
                {
                    "text": f"Built Python API endpoint {i} with PostgreSQL.",
                    "experienceId": "exp_002",
                    "sourceIds": [f"exp_002_bullet_{i:03d}"],
                    "sourceBulletIds": [f"exp_002_bullet_{i:03d}"],
                }
                for i in range(1, 6)
            ],
        ]
        selected = select_nonduplicative_bullets(roles, bullets, facts, max_total=16)
        self.assertGreaterEqual(len(selected[1]), 3)

    def test_balanced_skills_keep_transferable_strengths_without_jd_leakage(self) -> None:
        facts = [
            SourceFact(
                "exp_001_bullet_001",
                "Built Python and Java services with Spring Boot, AWS, PostgreSQL, REST APIs, React, and Git.",
                "candidate_resume",
            )
        ]
        skills, audit = build_canonical_skills_section(
            source_skills="Python, Java, AWS, PostgreSQL, Spring Boot, React, REST APIs, Git",
            job_description="Required: Python, SQL Server, Azure, and production LLM APIs.",
            facts=facts,
            final_experience=facts[0].text,
        )
        names = {item["canonicalSkill"]: item for item in audit}
        self.assertIn("Python", skills)
        self.assertEqual("exact", names["Python"]["matchType"])
        self.assertIn("PostgreSQL", skills)
        self.assertEqual("transferable", names["PostgreSQL"]["matchType"])
        self.assertIn("AWS", skills)
        self.assertEqual("transferable", names["AWS"]["matchType"])
        self.assertIn("Java", skills)
        self.assertIn("Spring Boot", skills)
        self.assertIn("React", skills)
        self.assertNotIn("SQL Server", skills)
        self.assertNotIn("Azure", skills)
        self.assertNotIn("OpenAI API", skills)

    def test_large_verified_skill_inventory_selects_focused_but_broad_set(self) -> None:
        evidence = (
            "Python, Java, JavaScript, TypeScript, Spring Boot, Spring Framework, FastAPI, Django, Flask, Node.js, "
            "REST APIs, GraphQL, PostgreSQL, MySQL, MongoDB, Redis, Kafka, AWS, Docker, Kubernetes, Terraform, "
            "CI/CD, GitHub Actions, Unit Testing, Integration Testing, Automated Testing, Code Review, React, Next.js, Ionic, Git, Jira"
        )
        facts = [SourceFact("exp_004_bullet_001", evidence, "candidate_resume")]
        skills, audit = build_canonical_skills_section(
            source_skills=evidence,
            job_description="Required: Python, REST APIs, SQL, cloud deployment, CI/CD, testing, and backend systems.",
            facts=facts,
            final_experience=evidence,
        )
        self.assertGreaterEqual(len(audit), 15)
        self.assertLessEqual(len(audit), 30)
        self.assertIn("Python", [item["canonicalSkill"] for item in audit[:8]])
        self.assertIn("React", skills)
        self.assertNotIn("Backend Development", skills)

    def test_small_verified_skill_set_does_not_pad_to_minimum(self) -> None:
        evidence = "Python, Java, AWS, PostgreSQL, React, Git"
        facts = [SourceFact("skills_001", evidence, "candidate_resume")]
        skills, audit = build_canonical_skills_section(
            source_skills=evidence,
            job_description="Required: Python, Azure, SQL Server, OpenAI API, RAG, Kubernetes.",
            facts=facts,
            final_experience="",
        )
        self.assertEqual(6, len(audit))
        self.assertIn("Python", skills)
        self.assertNotIn("Azure", skills)
        self.assertNotIn("SQL Server", skills)
        self.assertNotIn("RAG", skills)

    def test_skill_only_in_job_description_is_gap_not_resume_skill(self) -> None:
        facts = [SourceFact("skills_001", "Python", "candidate_resume")]
        skills, _audit = build_canonical_skills_section(
            source_skills="Python",
            job_description="Required: Python and RAG.",
            facts=facts,
            final_experience="",
        )
        gaps = "\n".join(build_gap_report(create_evidence_map(analyze_job_description("Required: Python and RAG."), facts)))
        self.assertNotIn("RAG", skills)
        self.assertIn("RAG", gaps)

    def test_llm_skill_only_is_partial_until_practical_usage_is_confirmed(self) -> None:
        facts = [SourceFact("skills_001", "Python, OpenAI API", "candidate_resume")]
        job = analyze_job_description("Required: hands-on OpenAI API experience with prompt design and structured JSON output.")
        evidence = create_evidence_map(job, facts)
        openai = next(item for item in evidence if item["requirement"].lower() == "openai")
        self.assertEqual("partial", openai["status"])
        self.assertIn("practical project or professional evidence", openai["reason"])
        self.assertTrue(any("OpenAI" in gap for gap in build_gap_report(evidence)))

    def test_confirmed_llm_experience_can_satisfy_practical_requirement(self) -> None:
        facts = [
            SourceFact(
                "user_verified_001",
                "What omitted experience can you personally confirm? Built an OpenAI API document workflow for structured output validation.",
                "candidate_verified_answer",
            )
        ]
        job = analyze_job_description("Required: hands-on OpenAI API experience.")
        evidence = create_evidence_map(job, facts)
        openai = next(item for item in evidence if item["requirement"].lower() == "openai")
        self.assertEqual("exact_match", openai["status"])

    def test_bare_yes_confirmation_supports_conservative_skill_but_not_employer_bullet(self) -> None:
        facts = parse_verified_answer_facts([
            {
                "question": "Candidate confirms hands-on experience building or maintaining an application that used an LLM API or LLM orchestration framework.",
                "answer": "Candidate confirmed this qualification by selecting Yes.",
            }
        ])
        skills, _audit = build_canonical_skills_section(
            source_skills="Python",
            job_description="Required: production LLM API experience and Python.",
            facts=[*facts, SourceFact("skills_001", "Python", "candidate_resume")],
            final_experience="",
        )
        self.assertIn("LLM API Integration", skills)
        generated = [{
            "generated_text": "Built an LLM API application for production workflows.",
            "source_fact_ids": [facts[0].fact_id],
            "unsupported_terms": [],
        }]
        self.assertEqual(
            [],
            filter_supported_bullets(generated, [], facts, role_index=0, wanted=1),
        )

    def test_detailed_confirmation_uses_answer_as_clean_evidence_text(self) -> None:
        facts = parse_verified_answer_facts([
            {
                "question": "Have you built a PDF workflow?",
                "answer": "Built a PyMuPDF pipeline that reduced processing from 20 minutes to 6 minutes.",
            }
        ])
        self.assertEqual(
            "Built a PyMuPDF pipeline that reduced processing from 20 minutes to 6 minutes.",
            facts[0].text,
        )

    def test_confirmed_ai_skill_taxonomy_keeps_detailed_capabilities(self) -> None:
        skill_text = (
            "OpenAI API, prompt engineering, structured JSON, JSON Schema, function calling, PDF parsing, OCR, "
            "document classification, information extraction, guardrails, source grounding, confidence scoring, "
            "human-in-the-loop review, prompt versioning, LLM monitoring, embeddings, vector search, LangChain"
        )
        facts = [SourceFact("user_verified_001", skill_text, "candidate_verified_answer")]
        skills, _audit = build_canonical_skills_section(
            source_skills="",
            job_description="AI Engineer: OpenAI, document processing, structured outputs, validation, monitoring",
            facts=facts,
            final_experience="",
        )
        for expected in ("OpenAI API", "JSON Schema", "Function Calling", "PDF Parsing", "OCR", "Source Grounding", "Prompt Versioning", "Vector Search"):
            self.assertIn(expected, skills)

    def test_postgresql_transferable_does_not_become_sql_server(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Optimized Postgres reporting workflows.", "candidate_resume")]
        skills, audit = build_canonical_skills_section(
            source_skills="Postgres",
            job_description="Required: Microsoft SQL Server.",
            facts=facts,
            final_experience=facts[0].text,
        )
        self.assertIn("PostgreSQL", skills)
        self.assertNotIn("SQL Server", skills)
        self.assertEqual("transferable", next(item for item in audit if item["canonicalSkill"] == "PostgreSQL")["matchType"])

    def test_aws_transferable_does_not_become_azure(self) -> None:
        facts = [SourceFact("exp_001_bullet_001", "Deployed cloud services on Amazon Web Services.", "candidate_resume")]
        skills, audit = build_canonical_skills_section(
            source_skills="Amazon Web Services",
            job_description="Required: Microsoft Azure deployments.",
            facts=facts,
            final_experience=facts[0].text,
        )
        self.assertIn("AWS", skills)
        self.assertNotIn("Azure", skills)
        self.assertEqual("transferable", next(item for item in audit if item["canonicalSkill"] == "AWS")["matchType"])

    def test_ai_assisted_development_does_not_infer_openai_api_or_rag(self) -> None:
        facts = [SourceFact("skills_001", "Used ChatGPT and AI-assisted development for code review.", "candidate_resume")]
        skills, audit = build_canonical_skills_section(
            source_skills="ChatGPT, AI-assisted development",
            job_description="Required: OpenAI API, RAG, and production LLM engineering.",
            facts=facts,
            final_experience="",
        )
        self.assertIn("AI-Assisted Development", skills)
        self.assertNotIn("OpenAI API", skills)
        self.assertNotIn("RAG", skills)
        self.assertEqual("transferable", next(item for item in audit if item["canonicalSkill"] == "AI-Assisted Development")["matchType"])

    def test_backend_job_prioritizes_backend_but_keeps_limited_frontend(self) -> None:
        evidence = "Python, Java, Spring Boot, REST APIs, PostgreSQL, AWS, React, Next.js, TypeScript, Ionic"
        facts = [SourceFact("exp_003_bullet_001", evidence, "candidate_resume")]
        skills, _audit = build_canonical_skills_section(
            source_skills=evidence,
            job_description="Required: backend APIs, Python, SQL, cloud deployment, and production services.",
            facts=facts,
            final_experience=evidence,
        )
        backend_index = skills.index("Backend and APIs")
        frontend_index = skills.index("Frontend")
        self.assertLess(backend_index, frontend_index)
        frontend_line = next(line for line in skills.splitlines() if line.startswith("Frontend:"))
        self.assertLessEqual(len(frontend_line.split(":", 1)[1].split(",")), 3)

    def test_duplicate_aliases_are_deduped(self) -> None:
        facts = [SourceFact("skills_001", "Postgres, PostgreSQL, RESTful API, REST APIs", "candidate_resume")]
        skills, audit = build_canonical_skills_section(
            source_skills=facts[0].text,
            job_description="Required: SQL and REST APIs.",
            facts=facts,
            final_experience="",
        )
        names = [item["canonicalSkill"] for item in audit]
        self.assertEqual(1, names.count("PostgreSQL"))
        self.assertEqual(1, names.count("REST APIs"))
        self.assertEqual(1, skills.count("PostgreSQL"))
        self.assertEqual(1, skills.count("REST APIs"))

    def test_strong_verified_skill_absent_from_jd_may_remain(self) -> None:
        facts = [SourceFact("exp_004_bullet_001", "Built Python services and Kafka event pipelines for production data movement.", "candidate_resume")]
        skills, audit = build_canonical_skills_section(
            source_skills="Python, Kafka",
            job_description="Required: Python backend services.",
            facts=facts,
            final_experience=facts[0].text,
        )
        self.assertIn("Python", skills)
        self.assertIn("Kafka", skills)
        self.assertEqual("supporting", next(item for item in audit if item["canonicalSkill"] == "Kafka")["selectionLayer"])


if __name__ == "__main__":
    unittest.main()
