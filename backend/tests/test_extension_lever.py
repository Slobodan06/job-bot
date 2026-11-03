"""Lever forms: signature Name/Date under the disability survey, Yes/No radios, follow-ups."""
import unittest
from datetime import date

from app.extension.autofill import classify_field, resolve_deterministic_values, unresolved_free_text_fields

PROFILE = {"first_name": "Cory", "last_name": "Stagg", "country": "United States",
           "work_authorized": True, "requires_sponsorship": False,
           "disability_status": "No, I do not have a disability and have not had one in the past"}


def _resolve(fields: list[dict], profile: dict | None = None) -> dict:
    out = resolve_deterministic_values(fields=fields, profile=PROFILE if profile is None else profile,
                                       model=None, email="a@example.com", today=date(2026, 11, 2))
    return {key: value["value"] for key, value in out.items()}


YES_NO = ["Yes", "No"]


class LeverTests(unittest.TestCase):
    def test_disability_signature_gets_name_and_date_not_the_answer(self) -> None:
        fields = [
            {"key": "n", "label": "Name", "name": "eeo[disabilitySignature]", "type": "text"},
            {"key": "d", "label": "Date", "name": "eeo[disabilitySignatureDate]", "type": "text"},
        ]
        self.assertEqual({"n": "Cory Stagg", "d": "11/02/2026"}, _resolve(fields))

    def test_disability_question_still_answered(self) -> None:
        field = {"key": "k", "label": "Disability status", "name": "eeo[disability]", "type": "select",
                 "options": ["Yes, I have a disability", "No, I do not have a disability and have not had one in the past",
                             "I do not want to answer"]}
        self.assertEqual({"k": "No, I do not have a disability and have not had one in the past"}, _resolve([field]))

    def test_yes_no_radio_questions(self) -> None:
        fields = [
            {"key": "a", "label": "Are you legally authorized to work in the United States for any employer? *",
             "type": "radio", "options": YES_NO},
            {"key": "s", "label": "Will you now or in the future, require sponsorship for employment VISA status (e.g., H-1B)? *",
             "type": "radio", "options": YES_NO},
            {"key": "l", "label": "Do you currently live in the contiguous United States? *",
             "type": "radio", "options": YES_NO},
        ]
        self.assertEqual({"a": "Yes", "s": "No", "l": "Yes"}, _resolve(fields))

    def test_living_outside_the_us_answers_no(self) -> None:
        field = {"key": "l", "label": "Do you currently live in the United States?", "type": "radio", "options": YES_NO}
        self.assertEqual({"l": "No"}, _resolve([field], {"country": "Canada"}))

    def test_follow_up_question_is_left_alone(self) -> None:
        field = {"key": "y", "label": "If yes, how many years of experience do you have?", "type": "text"}
        self.assertEqual("", classify_field(field))
        self.assertEqual({}, _resolve([field], {**PROFILE, "years_of_experience": "8"}))

    def test_blank_profile_questions_are_not_sent_to_the_ai(self) -> None:
        field = {"key": "p", "label": "What is your desired salary?", "type": "text"}
        self.assertEqual([], unresolved_free_text_fields([field], {}))


if __name__ == "__main__":
    unittest.main()
