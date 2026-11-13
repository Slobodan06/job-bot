"""Tracker search: find the application an employer email / interview invite is about.

Pure (no DB) so it is unit-testable. The member typically pastes whatever the
invitation gives them — a subject line ("Interview invitation: Senior Backend
Engineer at Acme"), the recruiter's address (``jane@talent.acme.com``), a job link,
a req id, or a phrase from the posting — and we have to find the job they applied
to, its link, the description and the exact resume that went out.

How a query is read:
  * URLs        → exact job match by ``job_hash`` (same rules as the tracker), plus a
                  looser host+path match for apply-flow variants of the link.
  * emails      → the sender's company from the domain (``talent.acme-corp.co.uk`` →
                  "acme corp"); free-mail and ATS/scheduler domains are ignored.
  * "quoted"    → kept as one phrase.
  * other words → terms, minus filler ("interview", "invitation", "at", "role"…).

Every term is looked up in company, title, link, location, notes, resume filename
and the full job description. A job is kept when at least half of the terms hit
somewhere; results are ranked by how many terms hit and where (company/title hits
weigh far more than a hit buried in the description).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.applications.logic import job_hash, normalize_job_url

MAX_TERMS = 12
SNIPPET_RADIUS = 90

# Words that appear in invitations/subjects but say nothing about which job it is.
_STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "to", "in", "on", "at", "by", "with", "from", "re", "fw", "fwd",
    "your", "you", "our", "we", "us", "is", "are", "be", "as", "or", "about", "regarding", "next", "step", "steps",
    "interview", "interviews", "interviewing", "invitation", "invite", "invited", "inviting", "schedule",
    "scheduling", "scheduled", "call", "phone", "screen", "screening", "meeting", "chat", "conversation",
    "application", "applied", "applying", "apply", "candidate", "candidacy", "position", "role", "job",
    "opportunity", "opening", "update", "status", "thank", "thanks", "hi", "hello", "dear", "team",
    "recruiter", "recruiting", "talent", "acquisition", "hiring", "hr", "mail", "email", "no", "reply", "noreply",
    "inc", "llc", "ltd", "corp", "corporation", "company", "co", "gmbh", "plc",
    "com", "www", "http", "https",
}

# Sender domains that never identify the employer.
_IGNORED_MAIL_DOMAINS = {
    "gmail", "googlemail", "outlook", "hotmail", "live", "msn", "yahoo", "ymail", "icloud", "me", "mac", "aol",
    "proton", "protonmail", "gmx", "zoho", "yandex", "mail",
    "greenhouse", "greenhouse-mail", "lever", "hire", "workday", "myworkday", "myworkdayjobs", "ashbyhq", "ashby",
    "icims", "smartrecruiters", "workable", "workablemail", "bamboohr", "jobvite", "breezy", "breezyhr",
    "linkedin", "indeed", "indeedemail", "ziprecruiter", "glassdoor", "successfactors", "sapsf", "taleo",
    "oracle", "oraclecloud", "jazzhr", "applytojob", "recruitee", "teamtailor", "paylocity", "ultipro", "ukg",
    "adp", "dayforce", "ceridian", "rippling", "gem", "calendly", "goodtime", "modernloop", "zoom", "google",
    "microsoft", "sendgrid", "mailgun", "amazonses", "hirevue", "codility", "hackerrank", "codesignal",
    "phenom", "phenompeople", "eightfold", "avature", "beamery", "dover", "wellfound", "angellist", "dice",
}
# Sub-domain / second-level labels to skip when picking the company label.
_DOMAIN_FILLER = {
    "mail", "email", "e", "em", "talent", "careers", "career", "jobs", "job", "hr", "recruiting", "recruitment",
    "notifications", "notification", "notify", "noreply", "no-reply", "us", "eu", "uk", "www", "people", "team",
    "hire", "hiring", "apply", "news", "info", "corp", "co", "com", "org", "net", "ac", "gov", "edu",
}

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+|\b[a-z0-9.-]+\.[a-z]{2,}/[^\s<>\"')\]]*", re.I)
_EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@([a-z0-9.-]+\.[a-z]{2,})", re.I)
_PHRASE_RE = re.compile(r"[\"“”]([^\"“”]{2,80})[\"“”]")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#]*(?:\.[a-z0-9+#]+)*", re.I)
_APPLY_TAIL_RE = re.compile(r"/(?:apply|application|applications)(?:/.*)?$", re.I)

# (doc key, label shown to the user, weight). Order = display order of "matched in".
FIELDS: tuple[tuple[str, str, float], ...] = (
    ("company", "company", 6.0),
    ("job_title", "title", 5.0),
    ("job_url", "job link", 3.0),
    ("location", "location", 2.0),
    ("resume_filename", "resume file", 2.0),
    ("notes", "notes", 2.0),
    ("jd_text", "job description", 1.0),
)
# Fields fetched from Mongo for searching (applied_resume.filename is nested).
MONGO_FIELDS = ("company", "job_title", "job_url", "location", "notes", "jd_text", "applied_resume.filename")


@dataclass
class ParsedQuery:
    terms: list[str] = field(default_factory=list)  # words + phrases + sender companies, lowercase
    url_hashes: list[str] = field(default_factory=list)
    url_needles: list[str] = field(default_factory=list)  # "host/path" of pasted links

    @property
    def empty(self) -> bool:
        return not (self.terms or self.url_hashes)


@dataclass
class SearchMatch:
    score: float
    matched_terms: list[str]
    fields: list[str]
    snippet: str
    exact_link: bool = False


def _url_needle(url: str) -> str:
    norm = normalize_job_url(url)
    parsed = urlparse(norm)
    host = (parsed.hostname or "").removeprefix("www.")
    path = _APPLY_TAIL_RE.sub("", parsed.path).rstrip("/")
    return f"{host}{path}".lower() if path else ""


def company_from_email_domain(domain: str) -> str:
    """``talent.acme-corp.co.uk`` → ``acme corp``; free-mail / ATS domains → ``""``."""
    labels = [l for l in domain.lower().strip(".").split(".") if l]
    if len(labels) < 2:
        return ""
    labels = labels[:-1]  # drop the TLD
    if any(l in _IGNORED_MAIL_DOMAINS for l in labels):
        return ""
    candidates = [l for l in labels if l not in _DOMAIN_FILLER and len(l) >= 2]
    if not candidates:
        return ""
    # The registrable label is the last meaningful one (``careers.acme`` → ``acme``).
    return re.sub(r"[-_]+", " ", candidates[-1]).strip()


def parse_query(raw: str) -> ParsedQuery:
    text = (raw or "").strip()
    out = ParsedQuery()
    if not text:
        return out
    seen: set[str] = set()

    def add(term: str) -> None:
        term = re.sub(r"\s+", " ", term.strip().lower()).strip(".")
        if term and term not in seen and len(out.terms) < MAX_TERMS:
            seen.add(term)
            out.terms.append(term)

    # Emails first — otherwise their domain would be read as a URL.
    for m in _EMAIL_RE.finditer(text):
        company = company_from_email_domain(m.group(1))
        if company:
            add(company)
    text = _EMAIL_RE.sub(" ", text)

    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:")
        h = job_hash(url)
        if h not in out.url_hashes:
            out.url_hashes.append(h)
        needle = _url_needle(url)
        if needle and needle not in out.url_needles:
            out.url_needles.append(needle)
    text = _URL_RE.sub(" ", text)

    for m in _PHRASE_RE.finditer(text):
        add(m.group(1))
    text = _PHRASE_RE.sub(" ", text)

    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0).lower()
        if tok in _STOPWORDS:
            continue
        if len(tok) < 2 and not tok.isdigit():
            continue
        add(tok)
    return out


def _term_pattern(term: str) -> str:
    """Regex for a term; spaces/hyphens inside it match any separator ("acme corp" ~ "Acme-Corp")."""
    parts = [re.escape(p) for p in re.split(r"[\s\-_]+", term) if p]
    return r"[\s\-_.&]*".join(parts)


def mongo_filter(parsed: ParsedQuery) -> dict[str, Any]:
    """Cheap candidate prefilter: ANY term in ANY field, or the pasted link. Ranking happens in Python."""
    ors: list[dict[str, Any]] = []
    for term in parsed.terms:
        rx = {"$regex": _term_pattern(term), "$options": "i"}
        ors.extend({f: rx} for f in MONGO_FIELDS)
    if parsed.url_hashes:
        ors.append({"job_hash": {"$in": parsed.url_hashes}})
    for needle in parsed.url_needles:
        ors.append({"job_url": {"$regex": re.escape(needle), "$options": "i"}})
    return {"$or": ors} if ors else {}


def _field_values(doc: dict[str, Any]) -> dict[str, str]:
    values = {k: str(doc.get(k) or "") for k, _, _ in FIELDS if k != "resume_filename"}
    values["resume_filename"] = str((doc.get("applied_resume") or {}).get("filename") or "")
    return values


def _snippet(text: str, pattern: re.Pattern[str]) -> str:
    m = pattern.search(text)
    if not m:
        return ""
    start = max(0, m.start() - SNIPPET_RADIUS)
    end = min(len(text), m.end() + SNIPPET_RADIUS)
    # Don't cut words in half.
    if start > 0:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < m.start() else start
    if end < len(text):
        space = text.rfind(" ", m.end(), end)
        end = space if space > m.end() else end
    body = re.sub(r"\s+", " ", text[start:end]).strip()
    return f"{'…' if start > 0 else ''}{body}{'…' if end < len(text) else ''}"


def score_application(doc: dict[str, Any], parsed: ParsedQuery) -> SearchMatch | None:
    """How well one application matches; None when it doesn't match enough to show."""
    values = _field_values(doc)
    exact_link = bool(parsed.url_hashes) and doc.get("job_hash") in parsed.url_hashes
    if not exact_link and parsed.url_needles:
        url_norm = _url_needle(values["job_url"])
        exact_link = any(n and url_norm and (n in url_norm or url_norm in n) for n in parsed.url_needles)

    score = 100.0 if exact_link else 0.0
    matched_terms: list[str] = []
    fields_hit: set[str] = {"job link"} if exact_link else set()
    jd_pattern: re.Pattern[str] | None = None

    for term in parsed.terms:
        body = _term_pattern(term)
        word = re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.I)
        loose = re.compile(body, re.I)
        best = 0.0
        for key, label, weight in FIELDS:
            value = values[key]
            if not value:
                continue
            if word.search(value):
                strength = weight
            elif loose.search(value):
                strength = weight * 0.5
            else:
                continue
            fields_hit.add(label)
            best = max(best, strength)
            if key == "jd_text" and jd_pattern is None:
                jd_pattern = word if word.search(value) else loose
        if best:
            matched_terms.append(term)
            score += best

    n = len(parsed.terms)
    if not exact_link:
        if not matched_terms or len(matched_terms) < math.ceil(n / 2):
            return None
    # Whole query as a phrase in the title/company (e.g. "senior backend engineer").
    if n >= 2:
        phrase = re.compile(r"[\s\-_.,&/]+".join(_term_pattern(t) for t in parsed.terms), re.I)
        if phrase.search(values["job_title"]) or phrase.search(values["company"]):
            score += 5.0
    if n:
        score *= 0.5 + 0.5 * len(matched_terms) / n  # favour jobs that explain every term

    order = [label for _, label, _ in FIELDS]
    return SearchMatch(
        score=round(score, 2),
        matched_terms=matched_terms,
        fields=sorted(fields_hit, key=order.index),
        snippet=_snippet(values["jd_text"], jd_pattern) if jd_pattern else "",
        exact_link=exact_link,
    )


def rank(docs: list[dict[str, Any]], parsed: ParsedQuery) -> list[tuple[dict[str, Any], SearchMatch]]:
    """Matching docs, best first (ties: most recently applied first)."""
    scored = [(d, m) for d in docs if (m := score_application(d, parsed))]

    def applied(doc: dict[str, Any]) -> float:
        at = doc.get("submitted_at") or doc.get("created_at")
        return at.timestamp() if hasattr(at, "timestamp") else 0.0

    scored.sort(key=lambda dm: (dm[1].exact_link, len(dm[1].matched_terms), dm[1].score, applied(dm[0])), reverse=True)
    return scored
