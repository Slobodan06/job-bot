import unittest

from app.extension.autofill import (
    classify_field,
    normalize_autofill_profile,
    resolve_deterministic_values,
    unresolved_free_text_fields,
)
from app.services.resume_model import (
    ResumeContact,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeModel,
)


def _model() -> ResumeModel:
    return ResumeModel(
        name="Cory Stagg",
        title="Senior AI Engineer",
        location="Duncan, South Carolina, United States",
        contact=ResumeContact(
            email="ignored@x.com",
            linkedin="https://linkedin.com/in/cory",
            github="https://github.com/cory",
        ),
        professional_experience=[
            ResumeExperienceEntry(company="Innolitics", title="Senior software engineer"),
        ],
    )


def _multi_role_model() -> ResumeModel:
    return ResumeModel(
        name="Cory Stagg",
        title="Senior AI Engineer",
        professional_experience=[
            ResumeExperienceEntry(
                company="Innolitics",
                title="Senior Software Engineer",
                location="Brea, CA",
                dates="03/2024 - Present",
                responsibilities=["Built AI platforms.", "Led architecture reviews."],
            ),
            ResumeExperienceEntry(
                company="CVS Health",
                title="Software Engineer",
                dates="10/2020 - 02/2024",
                responsibilities=["Built full-stack apps."],
            ),
        ],
        education=[
            ResumeEducationEntry(school="Winthrop University", degree="BS", field="Software Engineering", duration="2014 - 2016"),
        ],
    )


class ClassifyFieldTests(unittest.TestCase):
    def test_common_fields(self) -> None:
        self.assertEqual("email", classify_field({"label": "Email Address"}))
        self.assertEqual("first_name", classify_field({"name": "first_name"}))
        self.assertEqual("last_name", classify_field({"label": "Last name *"}))
        self.assertEqual("phone", classify_field({"label": "Mobile phone"}))
        self.assertEqual("linkedin", classify_field({"label": "LinkedIn Profile URL"}))
        self.assertEqual("work_authorized", classify_field({"label": "Are you legally authorized to work in the US?"}))
        self.assertEqual("requires_sponsorship", classify_field({"label": "Will you now or in the future require visa sponsorship?"}))
        self.assertEqual("free_text", classify_field({"label": "Why do you want to work here?", "type": "textarea"}))

    def test_new_common_question_fields(self) -> None:
        self.assertEqual("password", classify_field({"label": "Create Password", "type": "password"}))
        self.assertEqual("password", classify_field({"label": "Confirm Password", "type": "password"}))
        self.assertEqual("address_line2", classify_field({"label": "Address Line 2 (Apt, Suite)"}))
        self.assertEqual("address", classify_field({"label": "Address Line 1"}))
        self.assertEqual("phone_country_code", classify_field({"label": "Phone Country Code"}))
        self.assertEqual("phone_device_type", classify_field({"label": "Phone Device Type"}))
        self.assertEqual("currently_employed", classify_field({"label": "Are you currently employed?"}))
        self.assertEqual("willing_to_relocate", classify_field({"label": "Are you willing to relocate?"}))
        self.assertEqual("over_18", classify_field({"label": "Are you at least 18 years of age?"}))
        self.assertEqual("worked_here_before", classify_field({"label": "Have you previously worked for this company?"}))
        self.assertEqual("has_drivers_license", classify_field({"label": "Do you have a valid driver's license?"}))
        self.assertEqual("years_of_experience", classify_field({"label": "How many years of experience do you have?"}))
        self.assertEqual("highest_education", classify_field({"label": "Highest level of education"}))
        self.assertEqual("how_heard_about_us", classify_field({"label": "How did you hear about us?"}))


class ProfileNormalizationTests(unittest.TestCase):
    def test_bools_and_custom_answers(self) -> None:
        clean = normalize_autofill_profile({
            "first_name": "  Cory ",
            "work_authorized": 1,
            "requires_sponsorship": 0,
            "phone": "+1 917 540 1640",
            "unknown_key": "dropped",
            "custom_answers": [{"q": "Notice period?", "a": "2 weeks"}, {"q": "", "a": "x"}],
        })
        self.assertEqual("Cory", clean["first_name"])
        self.assertIs(True, clean["work_authorized"])
        self.assertIs(False, clean["requires_sponsorship"])
        self.assertNotIn("unknown_key", clean)
        self.assertEqual([{"q": "Notice period?", "a": "2 weeks"}], clean["custom_answers"])


class ResolveValuesTests(unittest.TestCase):
    def test_profile_and_resume_sources(self) -> None:
        profile = normalize_autofill_profile({"phone": "917-540-1640", "work_authorized": True})
        fields = [
            {"key": "f1", "label": "First Name", "type": "text"},
            {"key": "f2", "label": "Last Name", "type": "text"},
            {"key": "f3", "label": "Email", "type": "email"},
            {"key": "f4", "label": "Phone", "type": "text"},
            {"key": "f5", "label": "LinkedIn URL", "type": "text"},
            {"key": "f6", "label": "Authorized to work in the United States?", "type": "select",
             "options": ["Yes", "No"]},
            {"key": "f7", "label": "Why are you interested?", "type": "textarea"},
        ]
        out = resolve_deterministic_values(fields=fields, profile=profile, model=_model(), email="cory@real.com")
        self.assertEqual("Cory", out["f1"]["value"])
        self.assertEqual("Stagg", out["f2"]["value"])
        self.assertEqual("cory@real.com", out["f3"]["value"])
        self.assertEqual("account", out["f3"]["source"])
        self.assertEqual("917-540-1640", out["f4"]["value"])
        self.assertEqual("https://linkedin.com/in/cory", out["f5"]["value"])
        self.assertEqual("Yes", out["f6"]["value"])
        self.assertNotIn("f7", out)  # free text -> AI, not deterministic

    def test_password_and_new_profile_fields(self) -> None:
        profile = normalize_autofill_profile({
            "application_password": "Th r0waway!23",
            "address_line2": "Apt 4B",
            "phone_country_code": "+1",
            "willing_to_relocate": True,
            "over_18": False,
        })
        fields = [
            {"key": "p1", "label": "Create Password", "type": "password"},
            {"key": "p2", "label": "Confirm Password", "type": "password"},
            {"key": "a1", "label": "Address Line 2", "type": "text"},
            {"key": "c1", "label": "Phone Country Code", "type": "text"},
            {"key": "r1", "label": "Willing to relocate?", "type": "select", "options": ["Yes", "No"]},
            {"key": "o1", "label": "At least 18 years of age?", "type": "select", "options": ["Yes", "No"]},
        ]
        out = resolve_deterministic_values(fields=fields, profile=profile, model=_model(), email="cory@real.com")
        self.assertEqual("Th r0waway!23", out["p1"]["value"])
        self.assertEqual("Th r0waway!23", out["p2"]["value"])
        self.assertEqual("Apt 4B", out["a1"]["value"])
        self.assertEqual("+1", out["c1"]["value"])
        self.assertEqual("Yes", out["r1"]["value"])
        self.assertEqual("No", out["o1"]["value"])

    def test_workday_style_repeated_work_experience_blocks(self) -> None:
        """Reproduces the Workday 'My Experience' repeater: Company/Job Title/
        Location/From/To/Description repeat once per employer and must map to
        the matching resume entry, not a single flat 'current employer'."""
        model = _multi_role_model()
        fields = [
            {"key": "title1", "label": "Job Title", "type": "text", "group_kind": "experience", "group_index": 0},
            {"key": "company1", "label": "Company", "type": "text", "group_kind": "experience", "group_index": 0},
            {"key": "location1", "label": "Location", "type": "text", "group_kind": "experience", "group_index": 0},
            {"key": "current1", "label": "I currently work here", "type": "checkbox", "group_kind": "experience", "group_index": 0},
            {"key": "from1", "label": "From", "type": "text", "group_kind": "experience", "group_index": 0},
            {"key": "to1", "label": "To", "type": "text", "group_kind": "experience", "group_index": 0},
            {"key": "desc1", "label": "Role Description", "type": "textarea", "group_kind": "experience", "group_index": 0},
            {"key": "title2", "label": "Job Title", "type": "text", "group_kind": "experience", "group_index": 1},
            {"key": "company2", "label": "Company", "type": "text", "group_kind": "experience", "group_index": 1},
            {"key": "to2", "label": "To", "type": "text", "group_kind": "experience", "group_index": 1},
        ]
        out = resolve_deterministic_values(fields=fields, profile={}, model=model, email="cory@real.com")
        self.assertEqual("Senior Software Engineer", out["title1"]["value"])
        self.assertEqual("Innolitics", out["company1"]["value"])
        self.assertEqual("Brea, CA", out["location1"]["value"])
        self.assertEqual("yes", out["current1"]["value"])
        self.assertEqual("03/2024", out["from1"]["value"])
        self.assertNotIn("to1", out)  # current job -> no end date to fill
        self.assertIn("Built AI platforms.", out["desc1"]["value"])
        self.assertEqual("Software Engineer", out["title2"]["value"])
        self.assertEqual("CVS Health", out["company2"]["value"])
        self.assertEqual("02/2024", out["to2"]["value"])

    def test_workday_style_repeated_education_blocks(self) -> None:
        model = _multi_role_model()
        fields = [
            {"key": "school1", "label": "School or University", "type": "text", "group_kind": "education", "group_index": 0},
            {"key": "degree1", "label": "Degree", "type": "text", "group_kind": "education", "group_index": 0},
            {"key": "field1", "label": "Field of Study", "type": "text", "group_kind": "education", "group_index": 0},
        ]
        out = resolve_deterministic_values(fields=fields, profile={}, model=model, email="cory@real.com")
        self.assertEqual("Winthrop University", out["school1"]["value"])
        self.assertEqual("BS", out["degree1"]["value"])
        self.assertEqual("Software Engineering", out["field1"]["value"])

    def test_group_field_without_matching_index_is_skipped(self) -> None:
        model = _multi_role_model()
        fields = [{"key": "title3", "label": "Job Title", "type": "text", "group_kind": "experience", "group_index": 5}]
        out = resolve_deterministic_values(fields=fields, profile={}, model=model, email="x@y.com")
        self.assertNotIn("title3", out)

    def test_free_text_detection(self) -> None:
        fields = [
            {"key": "f7", "label": "Why are you interested in this role?", "type": "textarea"},
            {"key": "f8", "label": "First Name", "type": "text"},
        ]
        resolved = resolve_deterministic_values(fields=fields, profile={}, model=_model(), email="x@y.com")
        free = unresolved_free_text_fields(fields, resolved)
        self.assertEqual(["f7"], [f["key"] for f in free])


if __name__ == "__main__":
    unittest.main()
