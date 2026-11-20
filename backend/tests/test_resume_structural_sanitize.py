"""Regression: garbled education field and bullet fragments in the job location slot."""
from app.services.rendercv_resume import _education_entries_from_model, _experience_entries_from_model, _split_degree_area
from app.services.resume_model import (
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeModel,
    plausible_job_location,
    sanitize_education_entry,
    sanitize_resume_model,
)


def test_split_degree_area_bachelors_degree_in():
    assert _split_degree_area("Bachelor's Degree in Computer Science") == ("Bachelor's Degree", "Computer Science")
    assert _split_degree_area("Master Degree of Engineering") == ("Master's Degree", "Engineering")
    assert _split_degree_area("Bachelor's Degree, Sunway University") == ("Bachelor's Degree", "Sunway University")
    assert _split_degree_area("Bachelor of Science in Physics") == (None, "Bachelor of Science in Physics")


def test_education_no_duplicated_degree_or_school():
    entry = sanitize_education_entry(
        ResumeEducationEntry(
            degree="Bachelor's Degree",
            field="Bachelor's in Degree, Sunway University",
            school="Sunway University",
            duration="01/2017 - 02/2020",
        )
    )
    assert entry.degree == "Bachelor's Degree"
    assert entry.field == ""
    rendered = _education_entries_from_model([entry])[0]
    assert rendered["institution"] == "Sunway University"
    assert rendered["area"] == "Bachelor's Degree"
    assert "degree" not in rendered


def test_education_recovers_field_of_study():
    entry = sanitize_education_entry(
        ResumeEducationEntry(degree="", field="Bachelor's in Degree in Computer Science", school="MIT")
    )
    assert (entry.degree, entry.field) == ("Bachelor's Degree", "Computer Science")


def test_education_legit_fields_untouched():
    for field in ("Computer Science", "Bachelor of Science in Physics", "Information Technology"):
        entry = sanitize_education_entry(ResumeEducationEntry(degree="BSc", field=field, school="Uni"))
        assert entry.field == field


def test_job_location_rejects_sentence_fragment():
    assert not plausible_job_location("Drizzle ORM for reliable, high-performance data processing.")
    assert not plausible_job_location("cutting production incidents by 35%")
    for ok in ("Brea, CA", "Remote", "Kuala Lumpur, Malaysia", "Rio de Janeiro, Brazil", "New York, NY (Hybrid)"):
        assert plausible_job_location(ok), ok


def test_sanitize_model_clears_bad_job_location():
    model = ResumeModel(
        professional_experience=[
            ResumeExperienceEntry(
                title="Fullstack Developer",
                company="Fossasia",
                location="Drizzle ORM for reliable, high-performance data processing.",
                dates="12/2018 - 12/2019",
            ),
            ResumeExperienceEntry(title="Engineer", company="Acme", location="Brea, CA"),
        ]
    )
    clean = sanitize_resume_model(model)
    entries = _experience_entries_from_model(clean.professional_experience)
    assert "location" not in entries[0]
    assert entries[0]["company"] == "Fossasia"
    assert entries[1]["location"] == "Brea, CA"
