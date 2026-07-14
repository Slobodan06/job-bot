import unittest
import zipfile
from io import BytesIO
from types import SimpleNamespace

from app.services.rendercv_resume import (
    _contact_cv_fields,
    _education_entries,
    _experience_entries,
    build_rendercv_payload,
)
from app.services.resume_sections import (
    WorkExperienceRole,
    normalize_work_experience_role,
    recover_contact_block_from_docx,
)
from app.services.resume_evidence import SourceFact, select_nonduplicative_bullets


class ResumeOutputRegressionTests(unittest.TestCase):
    def test_docx_hyperlink_target_is_recovered_from_relationships(self) -> None:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<w:document xmlns:w="urn:w"><w:p><w:r><w:t>outlook.com</w:t>'
                "</w:r></w:p></w:document>",
            )
            archive.writestr(
                "word/_rels/document.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="hyperlink" '
                'Target="https://www.linkedin.com/in/het-patel" TargetMode="External"/>'
                "</Relationships>",
            )
        contact = recover_contact_block_from_docx(buffer.getvalue(), "Het Patel")
        self.assertIn("https://www.linkedin.com/in/het-patel", contact)

    def test_email_provider_domain_is_not_rendered_as_website(self) -> None:
        fields = _contact_cv_fields(
            "Het Patel\nhet-patel12@outlook.com\nIllinois, United States\n"
            "+19176282276\noutlook.com\nhttps://www.linkedin.com/in/het-patel"
        )
        self.assertNotIn("website", fields)
        self.assertEqual(
            [{"network": "LinkedIn", "username": "het-patel"}],
            fields["social_networks"],
        )

    def test_composite_role_metadata_is_normalized_and_rendered_once(self) -> None:
        role = normalize_work_experience_role(WorkExperienceRole(
            header="AI Automation Engineer",
            company=(
                "AI Automation Engineer | 05/2023 - 05/2026 | "
                "Chicago, IL, USA, AI Automation Engineer"
            ),
            title="AI Automation Engineer",
            location="",
            period="05/2023 - 05/2026",
            bullets=(),
        ))
        self.assertEqual("", role.company)
        self.assertEqual("Chicago, IL, USA", role.location)
        self.assertEqual("05/2023 - 05/2026", role.period)
        entry = _experience_entries([role], [[]])[0]
        self.assertEqual("AI Automation Engineer", entry["company"])
        self.assertEqual("", entry["position"])
        self.assertEqual("Chicago, IL, USA", entry["location"])
        self.assertEqual("05/2023 - 05/2026", entry["date"])

    def test_three_part_education_location_is_not_a_highlight(self) -> None:
        entries = _education_entries(
            "Illinois Institute of Technology | Bachelor's in degree in computer science | "
            "04/2014 - 03/2018\nChicago, IL, USA\n"
            "Specialized in Software Engineering"
        )
        self.assertEqual("Chicago, IL, USA", entries[0]["location"])
        self.assertNotIn("Chicago, IL, USA", entries[0].get("highlights", []))

    def test_address_is_not_misclassified_as_phone(self) -> None:
        fields = _contact_cv_fields(
            "Daniel Wiseman\n"
            "1865 Bush St #303, San Francisco, CA | (818) 863-6443 | daniel.wiseman.ca@gmail.com"
        )
        self.assertEqual("daniel.wiseman.ca@gmail.com", fields["email"])
        self.assertIn("1865 Bush St #303", fields["location"])
        self.assertIn("+18188636443", fields["location"])
        self.assertNotIn("+1865303", fields["location"])

    def test_month_year_and_degree_are_preserved(self) -> None:
        entries = _education_entries(
            "Cal Poly San Luis Obispo\n"
            "Bachelor’s Degree – Computer Science | 05/2015 | Cumulative GPA: 3.63"
        )
        self.assertEqual("Cal Poly San Luis Obispo", entries[0]["institution"])
        self.assertEqual("Bachelor's Degree", entries[0]["degree"])
        self.assertEqual("Computer Science", entries[0]["area"])
        self.assertEqual("05/2015", entries[0]["date"])

    def test_selected_projects_heading_is_not_rendered_as_a_bullet(self) -> None:
        payload = build_rendercv_payload(
            theme="classic",
            contact="Daniel Wiseman\ndaniel@example.com",
            professional_summary="Summary",
            roles=[],
            bullets_by_role=[],
            skills="Programming Languages: Python",
            education="",
            other="SELECTED TECHNICAL PROJECTS\n- Built a document extraction workflow.",
        )
        sections = payload["cv"]["sections"]
        self.assertNotIn("Additional", sections)
        self.assertEqual(
            [{"bullet": "Built a document extraction workflow."}],
            sections["Selected Technical Projects"],
        )

    def test_newest_role_is_not_capped_at_five_bullets(self) -> None:
        roles = [SimpleNamespace(company="Old"), SimpleNamespace(company="New")]
        facts = []
        bullets = []
        subjects = [
            "eligibility API", "document parser", "audit logger", "retry worker", "SQL pipeline",
            "monitoring dashboard", "identity gateway", "notification service", "release workflow", "validation engine",
        ]
        for role_i, count in enumerate((0, 10), start=1):
            role_bullets = []
            for i in range(1, count + 1):
                fact_id = f"exp_{role_i:03d}_bullet_{i:03d}"
                text = f"Built {subjects[i - 1]} for supported production workflow {role_i}-{i}."
                facts.append(SourceFact(fact_id, text, "candidate_resume", experience_id=f"exp_{role_i:03d}"))
                role_bullets.append({
                    "text": text,
                    "experienceId": f"exp_{role_i:03d}",
                    "source_fact_ids": [fact_id],
                })
            bullets.append(role_bullets)
        selected = select_nonduplicative_bullets(roles, bullets, facts, max_total=24)
        self.assertEqual(10, len(selected[1]))

    def test_detailed_confirmed_fact_can_support_multiple_distinct_bullets(self) -> None:
        roles = [SimpleNamespace(company="CVS Health")]
        fact = SourceFact(
            "user_verified_001",
            "At CVS Health built a Python OpenAI workflow for PDF to structured JSON, source validation, retries, and SQL Server persistence.",
            "candidate_verified_answer",
            company="CVS Health",
            experience_id="exp_001",
        )
        texts = [
            "Built a Python OpenAI workflow that converted PDF inputs into structured JSON.",
            "Validated extracted fields against source documents before downstream use.",
            "Implemented retry handling for failed document-processing responses.",
            "Persisted verified structured output to SQL Server.",
        ]
        bullets = [[
            {"text": text, "experienceId": "exp_001", "source_fact_ids": [fact.fact_id]}
            for text in texts
        ]]
        selected = select_nonduplicative_bullets(roles, bullets, [fact], max_total=10)
        self.assertEqual(4, len(selected[0]))


if __name__ == "__main__":
    unittest.main()
