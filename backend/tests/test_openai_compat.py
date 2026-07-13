import unittest

from app.services.openai_compat import chat_completion_controls, uses_completion_token_limit


class OpenAICompatibilityTests(unittest.TestCase):
    def test_gpt_5_uses_max_completion_tokens_without_temperature(self) -> None:
        self.assertTrue(uses_completion_token_limit("gpt-5.6-terra"))
        self.assertEqual(
            {"max_completion_tokens": 12000},
            chat_completion_controls("gpt-5.6-terra", max_output_tokens=12000, temperature=0.55),
        )

    def test_chat_latest_alias_uses_modern_completion_limit(self) -> None:
        self.assertTrue(uses_completion_token_limit("chat-latest"))
        self.assertEqual(
            {"max_completion_tokens": 12000},
            chat_completion_controls("chat-latest", max_output_tokens=12000, temperature=0.55),
        )

    def test_legacy_model_keeps_max_tokens_and_temperature(self) -> None:
        self.assertFalse(uses_completion_token_limit("gpt-4o-mini"))
        self.assertEqual(
            {"max_tokens": 1200, "temperature": 0.55},
            chat_completion_controls("gpt-4o-mini", max_output_tokens=1200, temperature=0.55),
        )


if __name__ == "__main__":
    unittest.main()
