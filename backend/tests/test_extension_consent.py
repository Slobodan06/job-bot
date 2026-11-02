"""The terms checkbox that gates a form gets ticked; opt-ins don't; the application email is used."""
import unittest

from app.extension.autofill import classify_field, resolve_deterministic_values


def _resolve(fields: list[dict], profile: dict | None = None, email: str = "login@example.com") -> dict:
    out = resolve_deterministic_values(fields=fields, profile=profile or {}, model=None, email=email)
    return {key: value["value"] for key, value in out.items()}


class ConsentTests(unittest.TestCase):
    def test_terms_checkbox_is_ticked(self) -> None:
        for label in ("I agree", "I have read and accept the Privacy Policy", "I acknowledge the terms and conditions"):
            self.assertEqual({"k": "yes"}, _resolve([{"key": "k", "label": label, "type": "checkbox"}]), label)

    def test_opt_ins_stay_unticked(self) -> None:
        for label in (
            "I agree to receive SMS text messages about my application",
            "I agree to join the talent community for future opportunities",
            "Sign me up for job alerts",
        ):
            self.assertNotEqual("consent", classify_field({"label": label, "type": "checkbox"}), label)

    def test_only_checkboxes_are_consent(self) -> None:
        self.assertNotEqual("consent", classify_field({"label": "I agree", "type": "text"}))


class EmailTests(unittest.TestCase):
    def test_application_email_wins_over_the_sign_in_email(self) -> None:
        field = [{"key": "k", "label": "Email", "type": "email"}]
        self.assertEqual({"k": "apply@example.com"}, _resolve(field, {"email": "apply@example.com"}))
        self.assertEqual({"k": "login@example.com"}, _resolve(field))


if __name__ == "__main__":
    unittest.main()
