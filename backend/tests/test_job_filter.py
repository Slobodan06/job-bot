import pytest

from app.services.job_filter import check_job_filter


def _categories(jd: str) -> set[str]:
    return {reason.category for reason in check_job_filter(jd).reasons}


@pytest.mark.parametrize(
    "jd, expected",
    [
        ("This is a hybrid role based in Austin, TX.", {"hybrid"}),
        ("Work model: Hybrid (3 days a week in the office).", {"hybrid"}),
        ("You will work 2-3 days per week in our office in Boston.", {"hybrid"}),
        ("Location: New York, NY (On-site)", {"onsite"}),
        ("This position is onsite five days a week.", {"onsite"}),
        ("This is not a remote position.", {"onsite"}),
        ("Candidates must live within commuting distance of our Denver office.", {"onsite"}),
        ("Applicants must have an active Secret security clearance.", {"federal"}),
        ("Ability to obtain and maintain a Public Trust clearance.", {"federal"}),
        ("You will build data platforms for our federal government clients.", {"federal"}),
        ("Supporting the Department of Defense mission.", {"federal"}),
        ("TS/SCI with polygraph required.", {"federal"}),
        ("This is a GS-13 position posted on USAJOBS.", {"federal"}),
        (
            "Hybrid schedule in Arlington, VA. Requires active TS/SCI clearance.",
            {"hybrid", "federal"},
        ),
    ],
)
def test_blocks_non_remote_and_federal(jd, expected):
    result = check_job_filter(jd)
    assert result.blocked
    assert _categories(jd) == expected
    assert all(reason.evidence for reason in result.reasons)


@pytest.mark.parametrize(
    "jd",
    [
        "This is a fully remote role open to candidates anywhere in the US.",
        "Experience with hybrid cloud and multi-cloud deployments on AWS and Azure.",
        "Build hybrid search and hybrid retrieval pipelines for RAG.",
        "Fully remote, with an annual on-site team summit in Denver.",
        "Occasional travel to the office for quarterly planning.",
        "We offer remote or hybrid options for this role.",
        "Final round is an onsite interview.",
        "We are an equal opportunity employer and comply with all federal, state, and local laws.",
        "Discrimination based on any status protected by federal law is prohibited.",
        "Benefits include 11 paid federal holidays.",
        "Proficiency with React, TypeScript, and Python.",
    ],
)
def test_allows_remote_and_ignores_boilerplate(jd):
    result = check_job_filter(jd)
    assert not result.blocked, [r.evidence for r in result.reasons]


def test_message_names_the_categories():
    result = check_job_filter("Hybrid role. Active secret clearance required.")
    message = result.message()
    assert "hybrid role" in message
    assert "federal" in message.lower()


def test_enforce_job_filter_raises_only_when_checked():
    from fastapi import HTTPException

    from app.services.job_filter import enforce_job_filter

    jd = "Hybrid role in Austin, TX, 3 days a week in the office."
    enforce_job_filter("false", jd)  # unchecked: never blocks
    enforce_job_filter("true", "Fully remote role across the US.")  # remote: passes
    with pytest.raises(HTTPException) as excinfo:
        enforce_job_filter("true", jd)
    assert excinfo.value.status_code == 422
    detail = excinfo.value.detail
    assert detail["code"] == "job_filter_blocked"
    assert detail["reasons"][0]["category"] == "hybrid"
    assert "Hybrid role in Austin" in detail["reasons"][0]["evidence"]
