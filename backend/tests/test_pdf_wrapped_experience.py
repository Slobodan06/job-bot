"""PDF text extraction hard-wraps lines; the parser must rebuild roles, bullets and header."""
from app.services.pdf_resume import parse_contact_identity
from app.services.rendercv_resume import _education_entries
from app.services.resume_sections import _roles_from_experience_text, reflow_pdf_experience_text
from app.services.sectionize import parse_resume_sections

RAW = (
    "Tetiana Pustovoitova  \n"
    "Senior AI Engineer | Agentic AI | LangGraph | FastAPI | LLM Applications | \n"
    "Python\n"
    "tetianapustovoitova7@gmail.com\n"
    " \n"
    "Frankfurt am Main, Hesse, Germany\n"
    "SUMMARY\n"
    "Senior AI Engineer with 10+ years of software engineering experience.\n"
    "SKILLS\n"
    "Programming:\xa0Python, TypeScript, SQL\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Patients Know Best, Senior AI Engineer\n"
    "London, United\xa0Kingdom  | 11/2022 – 01/2026\n"
    "•Designed and developed production AI backend systems using Python, FastAPI, LLM APIs, retrieval \n"
    "pipelines, and intelligent automation workflows supporting enterprise healthcare applications.\n"
    "•Developed scalable FastAPI services handling approximately 50K+ monthly requests, integrating AI \n"
    "capabilities with backend services, APIs, and enterprise platforms.\n"
    "\n"
    "•Implemented AI workflow orchestration patterns using tool execution, structured outputs, validation \n"
    "logic, and automated decision flows.  \n"
    "BotCore.AI, AI Automation Engineer\n"
    "Slough, United\xa0Kingdom  | 10/2019 – 08/2022\n"
    "•Designed agent-based automation workflows combining LLM reasoning, deterministic business logic, \n"
    "structured outputs, and tool execution.\n"
    "•Worked with engineering and business stakeholders to translate operational challenges into scalable AI \n"
    "solutions and automation architectures.\n"
    "EDUCATION\n"
    "Nanyang Technological University\n"
    "Bachelor of Engineering in Computer Science\n"
    "Singapore  | 08/2010 – 05/2014"
)


def test_headline_stays_in_contact_not_experience():
    parsed = parse_resume_sections(RAW)
    assert "Agentic AI" not in parsed.professional_experience
    identity = parse_contact_identity(parsed.contact)
    assert identity.headline == (
        "Senior AI Engineer | Agentic AI | LangGraph | FastAPI | LLM Applications | Python"
    )
    assert identity.email == "tetianapustovoitova7@gmail.com"


def test_wrapped_bullets_and_two_line_headers_rebuild_roles():
    parsed = parse_resume_sections(RAW)
    roles = _roles_from_experience_text(reflow_pdf_experience_text(parsed.professional_experience))
    assert [(r.company, r.title, r.location) for r in roles] == [
        ("Patients Know Best", "Senior AI Engineer", "London, United Kingdom"),
        ("BotCore.AI", "AI Automation Engineer", "Slough, United Kingdom"),
    ]
    assert roles[0].period.startswith("11/2022")
    assert roles[0].bullets[0].endswith("supporting enterprise healthcare applications.")
    assert len(roles[0].bullets) == 3
    assert roles[1].bullets[1].endswith("solutions and automation architectures.")


def test_institution_above_degree_is_kept():
    parsed = parse_resume_sections(RAW)
    entries = _education_entries(parsed.education)
    assert len(entries) == 1
    assert entries[0]["institution"] == "Nanyang Technological University"
    assert entries[0]["area"] == "Bachelor of Engineering in Computer Science"
    assert entries[0].get("location") == "Singapore"
