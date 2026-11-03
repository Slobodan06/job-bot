"""Location questions get the candidate's full place; office preferences don't; Yes/No buttons answer."""
import unittest

from app.extension.autofill import classify_field, resolve_deterministic_values

PROFILE = {"city": "Austin", "state": "Texas", "country": "United States", "work_authorized": True}


def _resolve(fields: list[dict], profile: dict | None = None) -> dict:
    out = resolve_deterministic_values(fields=fields, profile=PROFILE if profile is None else profile,
                                       model=None, email="a@example.com")
    return {key: value["value"] for key, value in out.items()}


class LocationTests(unittest.TestCase):
    def test_location_questions_get_city_state_country(self) -> None:
        for label in ("Location (City)", "Current location", "Where are you currently located?", "Location"):
            self.assertEqual({"k": "Austin, Texas, United States"},
                             _resolve([{"key": "k", "label": label, "type": "text"}]), label)

    def test_office_and_relocation_questions_are_not_home_location(self) -> None:
        for label in ("Which location are you applying for?", "Preferred work location",
                      "Are you willing to relocate to this location?"):
            self.assertNotEqual("location", classify_field({"label": label, "type": "text"}), label)

    def test_city_field_still_gets_only_the_city(self) -> None:
        self.assertEqual({"k": "Austin"}, _resolve([{"key": "k", "label": "City", "type": "text"}]))

    def test_location_dropdown_picks_the_option_naming_the_city(self) -> None:
        field = {"key": "k", "label": "Location", "type": "select", "options": ["Remote", "Dallas, TX", "Austin, TX"]}
        self.assertEqual({"k": "Austin, TX"}, _resolve([field]))

    def test_no_city_means_no_location_answer(self) -> None:
        self.assertEqual({}, _resolve([{"key": "k", "label": "Location", "type": "text"}], {"country": "United States"}))


class YesNoButtonTests(unittest.TestCase):
    def test_button_group_question_is_answered_with_its_option(self) -> None:
        field = {"key": "k", "label": "Are you legally authorized to work in the US and/or Canada?*",
                 "type": "radio", "options": ["Yes", "No"]}
        self.assertEqual({"k": "Yes"}, _resolve([field]))


if __name__ == "__main__":
    unittest.main()
