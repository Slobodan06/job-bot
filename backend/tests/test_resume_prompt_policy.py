import unittest
from pathlib import Path

from app.services.resume_prompts import CANONICAL_TAILORING_POLICY, PROMPT_VERSION


class ResumePromptPolicyTests(unittest.TestCase):
    def test_policy_is_versioned_and_wired_into_both_writers(self) -> None:
        self.assertEqual("resume_pipeline_v5_2026_07_13", PROMPT_VERSION)
        self.assertIn("EVIDENCE CLASSIFICATIONS", CANONICAL_TAILORING_POLICY)
        services = Path(__file__).resolve().parents[1] / "app" / "services"
        fresh_source = (services / "fresh_resume_builder.py").read_text(encoding="utf-8")
        inplace_source = (services / "tailor.py").read_text(encoding="utf-8")
        self.assertIn("EVIDENCE_RESUME_SYSTEM", fresh_source)
        self.assertIn("SAMPLE_RESUME_SYSTEM", fresh_source)
        self.assertIn("Create the strongest plausible fictional summary", fresh_source)
        self.assertIn("Never invent a new employer, role, date, degree, certification, or school", fresh_source)
        self.assertIn("sample_mode: bool = True", fresh_source)
        self.assertIn("+ CANONICAL_TAILORING_POLICY", fresh_source)
        self.assertIn("STRUCTURED_SYSTEM", inplace_source)
        self.assertIn("+ CANONICAL_TAILORING_POLICY", inplace_source)
        self.assertIn('or "chat-latest"', inplace_source)
        self.assertIn('os.getenv("OPENAI_MODEL", "chat-latest")', fresh_source)

    def test_policy_preserves_truth_and_transferable_boundaries(self) -> None:
        self.assertIn("never fabricate", CANONICAL_TAILORING_POLICY.lower())
        self.assertIn("CANDIDATE-CONFIRMED", CANONICAL_TAILORING_POLICY)
        self.assertIn("UNVERIFIED", CANONICAL_TAILORING_POLICY)
        self.assertIn("never as direct use", CANONICAL_TAILORING_POLICY)
        self.assertIn("never create or extrapolate a number", CANONICAL_TAILORING_POLICY)
        self.assertIn("skill-only AI or LLM mention", CANONICAL_TAILORING_POLICY)
        self.assertIn("bare Yes response", CANONICAL_TAILORING_POLICY)
        self.assertIn("Employer bullets", CANONICAL_TAILORING_POLICY)
        self.assertIn("Do not create a Selected Technical Projects section", CANONICAL_TAILORING_POLICY)


if __name__ == "__main__":
    unittest.main()
