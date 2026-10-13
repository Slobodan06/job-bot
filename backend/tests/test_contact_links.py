"""Tech names that look like domains ("ASP.NET", "Judge.me") must never become header links."""
import unittest

from app.services.fresh_resume_builder import drop_tech_lookalike_website
from app.services.pdf_resume import is_plausible_personal_link, parse_contact_identity
from app.services.resume_ingest_ai import _validated_contact, header_region
from app.services.resume_model import ResumeContact, ResumeModel

# Tetiana's real resume: no website in the header; "ASP.NET" only in Skills.
TETIANA = """Tetiana Pustovoitova
Senior Fullstack Engineer | .NET / C# | Azure Architect | SQL Server | AI-Native Developer
tetianapustovoitova7@gmail.com Frankfurt am Main, Hesse, Germany
linkedin.com/in/tetiana-pustovoitova
Summary
Senior Fullstack Engineer with ~10 years of experience building SaaS platforms.
Skills
Backend: .NET Core, C#, ASP.NET Core MVC, REST APIs, Entity Framework
E-commerce: Shopify, Judge.me reviews, Klaviyo
Professional Experience
Patients Know Best, Senior Fullstack Engineer
"""


class PlausibleLinkTests(unittest.TestCase):
    def test_tech_names_are_not_links(self) -> None:
        for url in ("asp.net", "https://asp.net", "ASP.NET", "judge.me", "https://judge.me/", "socket.io", "vb.net"):
            self.assertFalse(is_plausible_personal_link(url), url)

    def test_capitalised_bare_domain_in_source_is_a_technology(self) -> None:
        self.assertFalse(is_plausible_personal_link("https://acmeframework.net", "Skills: AcmeFramework.NET, C#".upper()))

    def test_real_personal_sites_still_work(self) -> None:
        for url, source in (
            ("https://janedoe.dev", "jane@x.com | janedoe.dev"),
            ("https://www.janedoe.com", "www.janedoe.com"),
            ("https://johnsmith.io", "https://johnsmith.io"),
            ("https://medium.com/@jane", "medium.com/@jane"),  # has a path
        ):
            self.assertTrue(is_plausible_personal_link(url, source), url)


class HeaderParsingTests(unittest.TestCase):
    def test_header_region_stops_at_first_section(self) -> None:
        header = header_region(TETIANA)
        self.assertIn("linkedin.com/in/tetiana-pustovoitova", header)
        self.assertNotIn("ASP.NET", header)

    def test_ai_website_from_skills_is_rejected(self) -> None:
        draft = ResumeContact(email="tetianapustovoitova7@gmail.com")
        for bogus in ("asp.net", "https://asp.net", "judge.me"):
            raw = {"email": "tetianapustovoitova7@gmail.com", "website": bogus,
                   "linkedin": "linkedin.com/in/tetiana-pustovoitova"}
            out = _validated_contact(raw, draft, TETIANA.casefold(), TETIANA)
            self.assertEqual("", out.website, bogus)
            self.assertEqual("linkedin.com/in/tetiana-pustovoitova", out.linkedin)

    def test_ai_website_in_header_is_kept(self) -> None:
        src = "Jane Doe\njane@x.com | janedoe.dev\nSkills\nPython\n"
        out = _validated_contact({"website": "janedoe.dev"}, ResumeContact(), src.casefold(), src)
        self.assertEqual("janedoe.dev", out.website)

    def test_headline_framework_is_not_parsed_as_portfolio(self) -> None:
        identity = parse_contact_identity("Sam Lee\nSenior Developer | ASP.NET | Azure\nsam@x.com | samlee.dev")
        self.assertEqual("https://samlee.dev", identity.portfolio_url)
        self.assertNotIn("asp.net", " ".join(u for _, u in identity.other_links).lower())


class SavedResumeGuardTests(unittest.TestCase):
    def test_stale_website_from_skills_is_dropped_before_tailoring(self) -> None:
        model = ResumeModel(
            name="Tetiana Pustovoitova",
            contact=ResumeContact(email="t@x.com", website="asp.net"),
            technical_skills={"Backend": [".NET Core", "ASP.NET Core MVC"]},
        )
        self.assertEqual("", drop_tech_lookalike_website(model).contact.website)

    def test_real_website_survives(self) -> None:
        model = ResumeModel(
            name="Jane Doe",
            contact=ResumeContact(email="j@x.com", website="https://janedoe.dev"),
            technical_skills={"Backend": ["Python", "ASP.NET"]},
        )
        self.assertEqual("https://janedoe.dev", drop_tech_lookalike_website(model).contact.website)


if __name__ == "__main__":
    unittest.main()
