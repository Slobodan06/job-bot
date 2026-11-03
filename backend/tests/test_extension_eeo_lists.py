"""EEO lists worded differently per form: Ethnicity as Hispanic / Not Hispanic, Workday suffixes, veterans."""
import unittest

from app.extension.autofill import resolve_deterministic_values

PROFILE = {"gender": "Male", "hispanic_latino": "No", "race_ethnicity": "White",
           "veteran_status": "I am not a protected veteran"}


def _resolve(fields: list[dict], profile: dict | None = None) -> dict:
    return resolve_deterministic_values(fields=fields, profile=PROFILE if profile is None else profile,
                                        model=None, email="a@example.com")


def _field(label: str, options: list[str] | None = None) -> dict:
    return {"key": "k", "label": label, "type": "select" if options else "combobox", "options": options or []}


class EeoListTests(unittest.TestCase):
    def test_ethnicity_asking_only_hispanic_gets_the_hispanic_answer(self) -> None:
        out = _resolve([_field("Ethnicity*", ["Hispanic or Latino", "Not Hispanic or Latino", "Decline to answer"])])
        self.assertEqual("Not Hispanic or Latino", out["k"]["value"])

    def test_ethnicity_listing_races_gets_the_race(self) -> None:
        out = _resolve([_field("Ethnicity*", ["Hispanic or Latino (United States of America)",
                                              "White (Not Hispanic or Latino) (United States of America)",
                                              "I do not wish to answer."])])
        self.assertEqual("White (Not Hispanic or Latino) (United States of America)", out["k"]["value"])

    def test_dropdown_with_unknown_options_carries_the_alternative_wording(self) -> None:
        out = _resolve([_field("Ethnicity*")])
        self.assertEqual(("White", ["Not Hispanic or Latino"]), (out["k"]["value"], out["k"]["alternatives"]))

    def test_ethnicity_without_a_race_in_the_profile(self) -> None:
        out = _resolve([_field("Ethnicity*")], {"hispanic_latino": "No"})
        self.assertEqual("Not Hispanic or Latino", out["k"]["value"])

    def test_veteran_never_picks_the_veteran_but_not_protected_option(self) -> None:
        out = _resolve([_field("Veteran Status*", ["I am a veteran but not a protected veteran", "I am not a veteran",
                                                   "I identify as one or more of the classifications of protected veteran",
                                                   "I do not wish to self-identify"])])
        self.assertEqual("I am not a veteran", out["k"]["value"])


if __name__ == "__main__":
    unittest.main()
