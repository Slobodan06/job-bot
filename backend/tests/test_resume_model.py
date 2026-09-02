import unittest

from app.services.resume_model import (
    ResumeContact,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeModel,
    normalize_date_token,
    skills_dict_from_text,
    skills_dict_to_text,
    split_date_range,
)


class ResumeModelAdapterTests(unittest.TestCase):
    def _model(self) -> ResumeModel:
        return ResumeModel(
            name="Jane Smith",
            title="Backend Engineer",
            location="Austin, TX, United States",
            contact=ResumeContact(
                email="jane@example.com",
                phone="+1 415 555 0100",
                linkedin="https://linkedin.com/in/jane",
                github="https://github.com/jane",
            ),
            professional_summary="Backend engineer.",
            professional_experience=[
                ResumeExperienceEntry(
                    company="Acme",
                    title="Senior Engineer",
                    location="Brea, CA",
                    dates="01/2020 - Present",
                    responsibilities=["Built payments service.", "Led migration."],
                )
            ],
            education=[ResumeEducationEntry(school="UT Austin", field="Computer Science", degree="BS", duration="2016")],
            certifications=["AWS SA"],
            technical_skills={"Languages": ["Python", "Go"]},
        )

    def test_contact_block_roundtrips_through_identity(self) -> None:
        block = self._model().contact_block()
        self.assertIn("Jane Smith", block)
        self.assertIn("jane@example.com", block)
        self.assertIn("Austin, TX, United States", block)
        self.assertIn("https://linkedin.com/in/jane", block)

    def test_work_experience_roles_adapter(self) -> None:
        roles = self._model().work_experience_roles()
        self.assertEqual(1, len(roles))
        self.assertEqual("Acme", roles[0].company)
        self.assertEqual("Brea, CA", roles[0].location)
        self.assertEqual("01/2020 - Present", roles[0].period)
        self.assertEqual(("Built payments service.", "Led migration."), roles[0].bullets)

    def test_text_adapters(self) -> None:
        model = self._model()
        self.assertEqual("Languages: Python, Go", model.skills_text())
        self.assertIn("Acme | Senior Engineer | Brea, CA | 01/2020 - Present", model.experience_text())
        self.assertIn("- Built payments service.", model.experience_text())
        self.assertIn("CERTIFICATIONS", model.extras_text())
        self.assertEqual([("Certifications", ["AWS SA"])], model.extra_sections())

    def test_skills_dict_roundtrip(self) -> None:
        skills = {"Languages": ["Python", "Go"], "Cloud": ["AWS", "Docker"]}
        parsed = skills_dict_from_text(skills_dict_to_text(skills))
        self.assertEqual(skills, parsed)

    def test_skills_dict_from_uncategorized_line(self) -> None:
        parsed = skills_dict_from_text("Python, Go, SQL")
        self.assertEqual({"Skills": ["Python", "Go", "SQL"]}, parsed)


class DateNormalizationTests(unittest.TestCase):
    def test_normalize_tokens(self) -> None:
        self.assertEqual("01/2020", normalize_date_token("Jan 2020"))
        self.assertEqual("03/2019", normalize_date_token("03/2019"))
        self.assertEqual("2016", normalize_date_token("2016"))
        self.assertEqual("Present", normalize_date_token("present"))
        self.assertEqual("", normalize_date_token("n/a"))

    def test_split_range(self) -> None:
        self.assertEqual(("01/2020", "Present"), split_date_range("Jan 2020 - Present"))
        self.assertEqual(("06/2016", "12/2019"), split_date_range("06/2016 - 12/2019"))
        self.assertEqual(("2012", "2016"), split_date_range("2012 - 2016"))


if __name__ == "__main__":
    unittest.main()
