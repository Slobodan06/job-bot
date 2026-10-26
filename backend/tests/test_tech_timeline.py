"""Tailored bullets never name a technology released after the role ended."""
import unittest
from datetime import date

from app.services.fresh_resume_builder import _rebind_to_timeline, drop_anachronistic_bullets
from app.services.resume_evidence import SourceFact
from app.services.resume_sections import WorkExperienceRole
from app.services.tech_timeline import (
    anachronistic_mentions,
    find_tech_mentions,
    role_year_span,
    strip_impossible_tenure_claims,
    unavailable_technologies,
)

TODAY = date(2026, 10, 26)


def _role(company: str, period: str) -> WorkExperienceRole:
    return WorkExperienceRole(f"Engineer | {company} | {period}", company, "Engineer", "", period, ())


class RoleYearSpanTests(unittest.TestCase):
    def test_closed_open_and_single_year_ranges(self) -> None:
        self.assertEqual((2019, 2021), role_year_span("Jan 2019 - Mar 2021", today=TODAY))
        self.assertEqual((2019, 2021), role_year_span("05/2019 – 11/2021", today=TODAY))
        self.assertEqual((2022, 2026), role_year_span("2022 - Present", today=TODAY))
        self.assertEqual((2023, 2026), role_year_span("2023 –", today=TODAY))
        self.assertEqual((2020, 2020), role_year_span("2020", today=TODAY))
        self.assertEqual((None, None), role_year_span("", today=TODAY))


class TechMentionTests(unittest.TestCase):
    def test_claude_code_in_a_2020_role_is_anachronistic(self) -> None:
        names = {m.name for m in anachronistic_mentions("Automated refactors with Claude Code agents.", 2020)}
        self.assertIn("Claude Code", names)
        self.assertEqual([], anachronistic_mentions("Automated refactors with Claude Code agents.", 2025))

    def test_versioned_technologies(self) -> None:
        names = {m.name for m in anachronistic_mentions("Migrated services to Java 21 and .NET 8.", 2020)}
        self.assertEqual({"Java 21", ".NET 8"}, names)
        # .NET Framework 4.8 and Java 8 existed in 2018.
        self.assertEqual([], anachronistic_mentions("Maintained .NET 4.8 and Java 8 services.", 2018))

    def test_everyday_words_are_not_technologies(self) -> None:
        text = "Took the helm to react quickly to incidents, the bedrock of a swift on-call rotation."
        self.assertEqual([], find_tech_mentions(text))

    def test_unavailable_technologies_prompt_hint(self) -> None:
        candidates = find_tech_mentions("Python, LangChain, Claude Code, Docker")
        self.assertEqual(
            ["LangChain (first released 2022)", "Claude Code (first released 2025)"],
            unavailable_technologies(candidates, 2020),
        )


class TenureClaimTests(unittest.TestCase):
    def test_drops_sentences_claiming_more_years_than_the_tool_existed(self) -> None:
        summary = (
            "Backend engineer with 10+ years building distributed systems in Python. "
            "Brings 8+ years of LangChain and LLM application experience. "
            "Recently shipped Claude Code automation for internal tooling."
        )
        self.assertEqual(
            "Backend engineer with 10+ years building distributed systems in Python. "
            "Recently shipped Claude Code automation for internal tooling.",
            strip_impossible_tenure_claims(summary, today=TODAY),
        )


class BulletFilterTests(unittest.TestCase):
    def test_drops_only_bullets_that_predate_their_tools(self) -> None:
        roles = [_role("OldCo", "2018 - 2020"), _role("NewCo", "2024 - Present")]
        bullets = [
            [
                {"text": "Built Claude Code workflows to automate code review.", "experienceId": "exp_001"},
                {"text": "Built Django REST APIs backed by PostgreSQL.", "experienceId": "exp_001"},
            ],
            ["Built Claude Code workflows to automate code review."],
        ]
        out = drop_anachronistic_bullets(roles, bullets)
        self.assertEqual(["Built Django REST APIs backed by PostgreSQL."], [b["text"] for b in out[0]])
        self.assertEqual(["Built Claude Code workflows to automate code review."], out[1])

    def test_confirmed_answer_moves_to_a_role_where_the_tool_existed(self) -> None:
        roles = [_role("OldCo", "2018 - 2020"), _role("NewCo", "2024 - Present")]
        fact = SourceFact("ans_1", "I built MCP servers with Claude Code.", "candidate_verified_answer",
                          "OldCo", experience_id="exp_001")
        rebound = _rebind_to_timeline(fact, roles)
        self.assertEqual(("exp_002", "NewCo"), (rebound.experience_id, rebound.company))

    def test_confirmed_answer_unbound_when_no_role_is_recent_enough(self) -> None:
        roles = [_role("OldCo", "2016 - 2018"), _role("MidCo", "2018 - 2021")]
        fact = SourceFact("ans_1", "I built MCP servers with Claude Code.", "candidate_verified_answer",
                          "MidCo", experience_id="exp_002")
        self.assertEqual("", _rebind_to_timeline(fact, roles).experience_id)


if __name__ == "__main__":
    unittest.main()
