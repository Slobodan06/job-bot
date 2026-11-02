"""Demographic questions reach the right answer, and a wrong answer is never guessed."""
import unittest

from app.extension.autofill import classify_field, resolve_deterministic_values, resume_file_stem
from app.services.resume_model import ResumeModel

GREENHOUSE_VETERAN = [
    "I am not a protected veteran",
    "I identify as one or more of the classifications of a protected veteran",
    "I don't wish to answer",
]


def _value(profile: dict, label: str, options: list[str] | None = None) -> str | None:
    field = {"key": "k", "label": label, "options": options or []}
    out = resolve_deterministic_values(fields=[field], profile=profile, model=None, email="")
    return out["k"]["value"] if "k" in out else None


class ClassifyTests(unittest.TestCase):
    def test_each_question_gets_its_own_answer(self) -> None:
        for label, key in (
            ("Gender", "gender"),
            ("Are you Hispanic / Latino?", "hispanic_latino"),
            ("Please identify your race", "race_ethnicity"),
            ("Race / Hispanic or Latino", "race_ethnicity"),
            ("Veteran Status", "veteran_status"),
            ("Disability Status", "disability_status"),
        ):
            self.assertEqual(key, classify_field({"label": label}), label)

    def test_greenhouse_hispanic_field_id_is_not_read_as_race(self) -> None:
        field = {"label": "Are you Hispanic/Latino?", "id": "hispanic_ethnicity"}
        self.assertEqual("hispanic_latino", classify_field(field))

    def test_words_containing_race_are_not_the_race_question(self) -> None:
        self.assertNotEqual("race_ethnicity", classify_field({"label": "Traceability experience"}))

    def test_long_veteran_wording_is_not_read_as_a_location(self) -> None:
        label = "Are you a protected veteran in your state or country?"
        self.assertEqual("veteran_status", classify_field({"label": label}))


class AnswerTests(unittest.TestCase):
    def test_male_never_answers_female(self) -> None:
        self.assertEqual("Male", _value({"gender": "Male"}, "Gender", ["Female", "Male"]))
        self.assertIsNone(_value({"gender": "Male"}, "Gender", ["Female", "Non-binary"]))

    def test_blank_stays_blank(self) -> None:
        self.assertIsNone(_value({}, "Gender", ["Male", "Female"]))

    def test_veteran_matches_by_meaning_across_wordings(self) -> None:
        profile = {"veteran_status": "I am not a protected veteran"}
        self.assertEqual("I am not a protected veteran", _value(profile, "Veteran Status", GREENHOUSE_VETERAN))
        self.assertEqual("No, not a veteran", _value(profile, "Veteran Status", ["Yes, a veteran", "No, not a veteran"]))

    def test_decline_maps_to_the_forms_own_wording(self) -> None:
        profile = {"gender": "Decline to self-identify"}
        self.assertEqual("I don't wish to answer", _value(profile, "Gender", ["Male", "Female", "I don't wish to answer"]))

    def test_race_keeps_longer_option_wording(self) -> None:
        options = ["White (Not Hispanic or Latino)", "Asian (Not Hispanic or Latino)"]
        self.assertEqual(options[1], _value({"race_ethnicity": "Asian"}, "Race", options))


class FileStemTests(unittest.TestCase):
    def test_profile_name_wins_then_resume_name(self) -> None:
        self.assertEqual("cory-stagg", resume_file_stem({"first_name": "Cory", "last_name": "Stagg"}, None))
        self.assertEqual("cory-stagg", resume_file_stem({}, ResumeModel(name="Cory Stagg")))

    def test_header_safe_names(self) -> None:
        self.assertEqual("jose-nunez", resume_file_stem({"first_name": "Jos\u00e9", "last_name": "N\u00fa\u00f1ez"}, None))
        self.assertEqual("resume", resume_file_stem({}, None))


if __name__ == "__main__":
    unittest.main()
