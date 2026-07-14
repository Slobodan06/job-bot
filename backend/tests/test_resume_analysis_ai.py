import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.resume_analysis_ai import repair_resume_metadata_with_ai
from app.services.resume_sections import WorkExperienceRole


class _FakeCompletions:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def create(self, **_kwargs):
        message = SimpleNamespace(content=json.dumps(self.payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeClient:
    payload: dict[str, object] = {}

    def __init__(self, **_kwargs) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(self.payload))


class ResumeAnalysisAIRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_company_and_linkedin_are_recovered_from_quoted_source(self) -> None:
        role = WorkExperienceRole(
            header="AI Automation Engineer | Chicago, IL, USA | 05/2023 - 05/2026",
            company="",
            title="AI Automation Engineer",
            location="Chicago, IL, USA",
            period="05/2023 - 05/2026",
            bullets=("Led AI discovery workshops.",),
        )
        _FakeClient.payload = {
            "linkedin_url": "https://www.linkedin.com/in/het-patel",
            "roles": [
                {
                    "index": 0,
                    "company": "Experis",
                    "company_evidence": "Experis",
                    "title": "AI Automation Engineer",
                    "title_evidence": "AI Automation Engineer",
                    "location": "Chicago, IL, USA",
                    "location_evidence": "Chicago, IL, USA",
                    "period": "05/2023 - 05/2026",
                    "period_evidence": "05/2023 - 05/2026",
                }
            ],
        }
        source = (
            "Het Patel\nhttps://www.linkedin.com/in/het-patel\n"
            "Experis\nAI Automation Engineer\nChicago, IL, USA\n05/2023 - 05/2026"
        )
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch(
            "app.services.resume_analysis_ai.AsyncOpenAI", _FakeClient
        ):
            contact, roles = await repair_resume_metadata_with_ai(
                contact="Het Patel\nhet-patel12@outlook.com\noutlook.com",
                roles=[role],
                source_text=source,
            )
        self.assertIn("https://www.linkedin.com/in/het-patel", contact)
        self.assertEqual("Experis", roles[0].company)

    async def test_ai_cannot_add_company_without_exact_source_evidence(self) -> None:
        role = WorkExperienceRole("Engineer", "", "Engineer", "", "", ())
        _FakeClient.payload = {
            "linkedin_url": "",
            "roles": [{"index": 0, "company": "Invented Corp", "company_evidence": "Invented Corp"}],
        }
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch(
            "app.services.resume_analysis_ai.AsyncOpenAI", _FakeClient
        ):
            _contact, roles = await repair_resume_metadata_with_ai(
                contact="Candidate",
                roles=[role],
                source_text="Engineer\nReal Company",
            )
        self.assertEqual("", roles[0].company)


if __name__ == "__main__":
    unittest.main()
