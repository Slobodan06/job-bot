"""The line under the name follows the job description (never claims untailored skills)."""
import unittest

from app.services.fresh_resume_builder import _replace_title_line, build_tailored_headline

SKILLS = (
    "Programming Languages: Python, SQL, TypeScript\n"
    "LLM Engineering: OpenAI API, Prompt Engineering, Structured Outputs\n"
    "Evaluation: Shadow Deployment, Drift Monitoring"
)
JD = (
    "Senior Applied AI Engineer. You will build LLM systems in Python with the OpenAI API, "
    "own evaluation, shadow deployment and drift monitoring. Python and SQL at scale. Python."
)
SOURCE_TITLE = "Senior Fullstack Engineer | .NET / C# | Azure Architect"


class TailoredHeadlineTests(unittest.TestCase):
    def test_ai_headline_kept_but_only_with_skills_in_the_resume(self) -> None:
        out = build_tailored_headline(
            ai_headline="Senior Applied AI Engineer | Python | Kubernetes | OpenAI API | 10+ years",
            target_role="Senior Applied AI Engineer", skills=SKILLS, job_description=JD, source_title=SOURCE_TITLE)
        # Kubernetes isn't in the tailored skills; "10+ years" is a claim, not a skill.
        self.assertEqual("Senior Applied AI Engineer | Python | OpenAI API", out)

    def test_fallback_uses_job_title_and_skills_the_job_mentions_most(self) -> None:
        out = build_tailored_headline(ai_headline="", target_role="Senior Applied AI Engineer",
                                      skills=SKILLS, job_description=JD, source_title=SOURCE_TITLE)
        # Python is mentioned most; ties go to whatever the job mentions first.
        self.assertEqual("Senior Applied AI Engineer | Python | OpenAI API | Shadow Deployment", out)

    def test_keeps_original_title_when_no_role_is_known(self) -> None:
        out = build_tailored_headline(ai_headline="", target_role="", skills=SKILLS, job_description="",
                                      source_title=SOURCE_TITLE)
        self.assertEqual(SOURCE_TITLE, out)

    def test_length_is_capped_without_cutting_a_segment(self) -> None:
        many = " | ".join(["Senior Applied AI Engineer"] + ["Python", "SQL", "TypeScript", "OpenAI API",
                                                              "Prompt Engineering", "Structured Outputs"])
        out = build_tailored_headline(ai_headline=many, target_role="x", skills=SKILLS, job_description=JD,
                                      source_title="")
        self.assertLessEqual(len(out), 110)
        self.assertTrue(out.startswith("Senior Applied AI Engineer | Python"))
        self.assertFalse(out.endswith("|"))

    def test_contact_block_title_line_is_swapped(self) -> None:
        block = f"Tetiana Pustovoitova\n{SOURCE_TITLE}\nt@x.com | Frankfurt"
        out = _replace_title_line(block, SOURCE_TITLE, "Senior Applied AI Engineer | Python")
        self.assertEqual("Tetiana Pustovoitova\nSenior Applied AI Engineer | Python\nt@x.com | Frankfurt", out)
        # No title in the source header: inserted under the name.
        out = _replace_title_line("Jane Doe\nj@x.com", "", "Data Engineer")
        self.assertEqual("Jane Doe\nData Engineer\nj@x.com", out)


if __name__ == "__main__":
    unittest.main()
