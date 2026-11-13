from datetime import datetime

from app.applications.logic import job_hash
from app.applications.search import (
    company_from_email_domain,
    mongo_filter,
    parse_query,
    rank,
    score_application,
)


def _app(**kw):
    url = kw.get("job_url", "https://boards.greenhouse.io/acme/jobs/111")
    return {
        "job_url": url,
        "job_hash": job_hash(url),
        "company": "",
        "job_title": "",
        "location": "",
        "notes": "",
        "jd_text": "",
        "applied_resume": None,
        "created_at": datetime(2026, 11, 1),
        **kw,
    }


ACME = _app(
    company="Acme Corp",
    job_title="Senior Backend Engineer",
    location="Austin, TX, USA",
    jd_text="We are hiring a backend engineer to build payment APIs in Python and Go. Req ID R-48213.",
    applied_resume={"filename": "jane-doe.pdf"},
)
GLOBEX = _app(
    job_url="https://jobs.lever.co/globex/abc-123",
    company="Globex",
    job_title="Backend Engineer",
    jd_text="Globex builds logistics software with Kotlin.",
)
INITECH = _app(
    job_url="https://initech.wd5.myworkdayjobs.com/en-US/careers/job/Senior-Data-Analyst_JR991",
    company="Initech",
    job_title="Senior Data Analyst",
    jd_text="SQL, dashboards, stakeholder management.",
)
ALL = [ACME, GLOBEX, INITECH]


def test_parse_drops_filler_words_from_an_invitation_subject():
    p = parse_query("Interview invitation: Senior Backend Engineer role at Acme")
    assert p.terms == ["senior", "backend", "engineer", "acme"]


def test_parse_reads_sender_company_from_email_domain():
    assert company_from_email_domain("talent.acme-corp.co.uk") == "acme corp"
    assert company_from_email_domain("careers.initech.com") == "initech"
    assert company_from_email_domain("gmail.com") == ""
    assert company_from_email_domain("us.greenhouse-mail.io") == ""
    p = parse_query("Mark <mark.smith@globex.com>")
    assert p.terms[0] == "globex"
    # The sender's display name doesn't stop the match (half the terms suffice).
    assert [d["company"] for d, _ in rank(ALL, p)] == ["Globex"]


def test_parse_keeps_quoted_phrases_and_tech_tokens():
    p = parse_query('"payment APIs" node.js c++')
    assert p.terms == ["payment apis", "node.js", "c++"]


def test_pasted_job_link_matches_exactly_even_with_tracking_params():
    p = parse_query("https://boards.greenhouse.io/acme/jobs/111?utm_source=linkedin&gh_src=x")
    assert p.terms == []
    ranked = rank(ALL, p)
    assert [d for d, _ in ranked] == [ACME]
    assert ranked[0][1].exact_link


def test_apply_flow_link_variant_still_finds_the_job():
    p = parse_query("https://initech.wd5.myworkdayjobs.com/en-US/careers/job/Senior-Data-Analyst_JR991/apply")
    assert [d["company"] for d, _ in rank(ALL, p)] == ["Initech"]


def test_company_and_title_hits_outrank_description_only_hits():
    ranked = rank(ALL, parse_query("backend engineer acme"))
    assert [d["company"] for d, _ in ranked] == ["Acme Corp", "Globex"]


def test_search_finds_words_only_in_the_job_description_with_snippet():
    ranked = rank(ALL, parse_query("R-48213"))
    assert [d["company"] for d, _ in ranked] == ["Acme Corp"]
    match = ranked[0][1]
    assert "job description" in match.fields
    assert "48213" in match.snippet


def test_recruiter_email_finds_company_from_job_link_host():
    # Workday postings often have an empty company but the tenant in the host.
    no_company = {**INITECH, "company": ""}
    ranked = rank([ACME, no_company], parse_query("recruiting@careers.initech.com"))
    assert ranked and ranked[0][0] is no_company
    assert "job link" in ranked[0][1].fields


def test_needs_at_least_half_of_the_terms():
    assert score_application(GLOBEX, parse_query("python payment acme austin")) is None
    assert score_application(ACME, parse_query("python payment acme austin")) is not None


def test_separators_are_flexible():
    m = score_application(ACME, parse_query("acme-corp"))
    assert m and "company" in m.fields


def test_resume_filename_is_searchable():
    m = score_application(ACME, parse_query("jane-doe.pdf"))
    assert m and "resume file" in m.fields


def test_mongo_filter_covers_jd_and_link():
    f = mongo_filter(parse_query("acme https://jobs.lever.co/globex/abc-123"))
    fields = {k for clause in f["$or"] for k in clause}
    assert {"company", "jd_text", "applied_resume.filename", "job_hash", "job_url"} <= fields
    assert mongo_filter(parse_query("   ")) == {}
