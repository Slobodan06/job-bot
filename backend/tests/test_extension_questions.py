"""Written questions: right classification, drafted from the tailored resume, shown not typed."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from app.extension import answers as answers_module
from app.extension import routes
from app.extension.answers import draft_free_text_answers
from app.extension.autofill import classify_field, resolve_deterministic_values
from app.extension.schemas import AutofillRequest, DetectedJob, FormField

ACCOMMODATION = "Do you require any special accommodations during the interview process (for example disability related support)?"
USER = {"_id": ObjectId(), "email": "a@example.com", "can_use_autofill": True}
JOB = DetectedJob(url="https://jobs.example.com/acme/123", text="Backend engineer. " * 10, company="Acme")


class ClassificationTests(unittest.TestCase):
    def test_accommodation_question_is_not_the_disability_survey(self) -> None:
        for field_type in ("textarea", "text", "select"):
            self.assertEqual("free_text", classify_field({"label": ACCOMMODATION, "type": field_type}))
        out = resolve_deterministic_values(
            fields=[{"key": "k", "label": ACCOMMODATION, "type": "textarea"}],
            profile={"disability_status": "No, I do not have a disability"},
            model=None,
            email="",
        )
        self.assertEqual({}, out)

    def test_long_written_question_ignores_the_words_it_mentions(self) -> None:
        label = "Describe a time you supported customers across every state and region"
        self.assertEqual("free_text", classify_field({"label": label, "type": "textarea"}))

    def test_the_survey_question_still_is_one(self) -> None:
        self.assertEqual("disability_status", classify_field({"label": "Disability Status", "type": "combobox"}))

    def test_race_option_with_a_slightly_different_spelling(self) -> None:
        out = resolve_deterministic_values(
            fields=[{
                "key": "k",
                "label": "Please identify your race",
                "options": ["American Indian or Alaskan Native", "Asian"],
            }],
            profile={"race_ethnicity": "American Indian or Alaska Native"},
            model=None,
            email="",
        )
        self.assertEqual("American Indian or Alaskan Native", out["k"]["value"])

    def test_similar_race_options_are_never_confused(self) -> None:
        out = resolve_deterministic_values(
            fields=[{"key": "k", "label": "Race", "options": ["American Indian", "Asian"]}],
            profile={"race_ethnicity": "Black or African American"},
            model=None,
            email="",
        )
        self.assertEqual({}, out)


class DraftingTests(unittest.IsolatedAsyncioTestCase):
    async def _draft(self, **kwargs):
        reply = {"answers": [{"key": "q1", "answer": "I shipped it."}]}
        create = AsyncMock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))]
        ))
        client = MagicMock()
        client.chat.completions.create = create
        with patch.object(answers_module, "llm_api_key", return_value="key"), \
                patch.object(answers_module, "make_llm_client", return_value=client):
            result = await draft_free_text_answers(
                fields=[{"key": "q1", "label": "Tell us about a launch"}],
                model=None,
                job_text="Build backend systems.",
                job_title="Engineer",
                company="Acme",
                **kwargs,
            )
        return result, create.await_args.kwargs["messages"][1]["content"]

    async def test_uses_the_tailored_resume_and_returns_a_draft_not_an_answer(self) -> None:
        (presets, drafts), prompt = await self._draft(profile={"city": "Dublin"}, tailored_text="TAILORED RESUME TEXT")
        self.assertEqual(({}, {"q1": "I shipped it."}), (presets, drafts))
        self.assertIn("TAILORED RESUME TEXT", prompt)
        self.assertIn("Build backend systems.", prompt)

    async def test_password_and_demographics_never_reach_the_ai(self) -> None:
        _, prompt = await self._draft(
            profile={
                "city": "Dublin",
                "application_password": "hunter2-secret",
                "gender": "SECRET-GENDER",
                "race_ethnicity": "SECRET-RACE",
            },
            tailored_text="resume",
        )
        self.assertIn("Dublin", prompt)
        for private in ("hunter2-secret", "SECRET-GENDER", "SECRET-RACE"):
            self.assertNotIn(private, prompt)


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_drafts_come_back_as_questions_and_unanswered_ones_are_kept(self) -> None:
        fields = [
            FormField(key="q1", label="Tell us about a launch you are proud of?", type="textarea"),
            FormField(key="q2", label=ACCOMMODATION, type="textarea"),
        ]
        with patch.object(routes, "profile_owner", AsyncMock(return_value=USER)), \
                patch.object(routes, "get_base_resume_model", return_value=None), \
                patch.object(routes, "find_resume_variant", AsyncMock(return_value=None)), \
                patch.object(routes, "draft_free_text_answers", AsyncMock(return_value=({}, {"q1": "I shipped it."}))):
            out = await routes.autofill(AutofillRequest(job=JOB, fields=fields), user=USER)
        self.assertEqual({}, out.answers)
        self.assertEqual(
            [("q1", "I shipped it."), ("q2", "")],
            [(q.key, q.answer) for q in out.questions],
        )


if __name__ == "__main__":
    unittest.main()
