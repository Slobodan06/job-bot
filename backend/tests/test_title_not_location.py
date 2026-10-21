from app.services.pdf_resume import parse_contact_identity
from app.services.render_docx_resume import build_docx_resume_from_model
from app.services.rendercv_resume import _contact_cv_fields_from_model
from app.services.resume_model import ResumeContact, ResumeModel

HEADER = (
    "Keith Joyner\n"
    "Senior Full-Stack Software Engineer, AI | Python | React | AWS\n"
    "keithjoyner31@outlook.com | +1 351 355 5057 | https://linkedin.com/in/keith-joyner"
)


def test_title_with_comma_is_not_parsed_as_location():
    identity = parse_contact_identity(HEADER)
    assert identity.location == ""
    assert identity.headline.startswith("Senior Full-Stack Software Engineer, AI")


def test_real_city_region_is_still_a_location():
    identity = parse_contact_identity("Jane Doe\njane@x.com | Austin, TX")
    assert identity.location == "Austin, TX"


def _stale_model() -> ResumeModel:
    # Resumes ingested before the fix stored the title fragment as the location.
    return ResumeModel(
        name="Keith Joyner",
        title="Senior Full-Stack Software Engineer | Python | FastAPI",
        location="Senior Full-Stack Software Engineer, AI",
        contact=ResumeContact(email="keithjoyner31@outlook.com", phone="+1 351 355 5057"),
    )


def test_stale_model_location_not_rendered_in_rendercv_header():
    assert "location" not in _contact_cv_fields_from_model(_stale_model())


def test_stale_model_location_not_rendered_in_docx_header():
    from io import BytesIO

    from docx import Document

    doc = Document(BytesIO(build_docx_resume_from_model(_stale_model())))
    contact_line = doc.paragraphs[2].text
    assert "Engineer, AI" not in contact_line


def test_skills_list_is_not_guessed_as_location():
    from app.services.resume_ingest import guess_candidate_location

    raw = (
        "Keith Joyner\n"
        "Senior Full-Stack Software Engineer, AI | Python | React | AWS\n"
        "keithjoyner31@outlook.com | +1 351 355 5057 | LinkedIn\n"
        "PROFESSIONAL SUMMARY\n"
        "Senior full-stack engineer with 6+ years building systems.\n"
        "SKILLS\n"
        "Programming: Python, TypeScript, JavaScript (ES6+), SQL, Bash\n"
        "AI/LLM: LLM-assisted code review, Claude Code, Cursor, GitHub Copilot\n"
    )
    assert guess_candidate_location(raw) == ""


def test_stale_skills_location_not_rendered():
    model = _stale_model().model_copy(
        update={
            "location": "Claude Code, Cursor, GitHub Copilot",
            "technical_skills": {"AI/LLM": ["Claude Code", "Cursor", "GitHub Copilot"]},
        }
    )
    assert model.display_location() == ""
    assert "location" not in _contact_cv_fields_from_model(model)
    assert "Cursor" not in model.contact_block()
