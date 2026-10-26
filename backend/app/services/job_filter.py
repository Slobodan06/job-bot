"""Deterministic "fully remote, non-federal only" screen for a job description.

Runs before any AI call, so a blocked job costs nothing. Every reason carries the
sentence from the posting that triggered it, so the user can see why it was blocked.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from fastapi import HTTPException

# "hybrid" followed by one of these is technology, not a work arrangement.
_HYBRID_TECH_NEXT = (
    r"cloud|multi-?cloud|mobile|apps?|applications?|infrastructure|architectures?|"
    r"search|retrieval|rag|deployments?|solutions?|kubernetes|data|systems?|ml|ai|"
    r"approach|models?(?!\s+of\s+work)|vehicles?|integration|environments?(?!\s*[,.;:)]?\s*$)"
)
_HYBRID_RE = re.compile(rf"\bhybrid\b(?![\s-]+(?:{_HYBRID_TECH_NEXT})\b)", re.I)
_OFFICE_DAYS_RE = re.compile(
    r"\b(?:\d|one|two|three|four)\s*(?:(?:-|to|or)\s*(?:\d|two|three|four|five)\s*)?days?\s*"
    r"(?:a|per|each|every)?\s*week\s*(?:in|at|from|on[- ]?site\s+(?:in|at))\s*(?:the|our)?\s*office\b"
    r"|\bin[- ]office\s+(?:\d|one|two|three|four)\s*(?:(?:-|to)\s*\d\s*)?days?\b",
    re.I,
)
_ONSITE_RE = re.compile(
    r"\bon[- ]?site\b"
    r"|\bin[- ](?:office|person)\b"
    r"|\boffice[- ]based\b"
    r"|\b(?:this is )?not (?:a |an )?(?:fully )?remote\b"
    r"|\bno remote\b"
    r"|\bremote (?:work )?(?:is )?not (?:available|possible|offered|an option)\b"
    r"|\bcommut(?:ing|able) distance\b"
    r"|\brelocation (?:is )?required\b"
    r"|\bmust (?:be willing to )?relocate\b"
    r"|\bmust (?:live|reside|be based|be located) (?:in|within|near)\b",
    re.I,
)
# On-site mentions that still fit a fully remote job ("annual on-site team summit").
_ONSITE_EXCEPTION_RE = re.compile(
    r"\boccasional(?:ly)?\b|\bquarterly\b|\bannual(?:ly)?\b|\bonce (?:a|per) (?:year|quarter)\b"
    r"|\bper (?:year|quarter)\b|\boff-?sites?\b|\btravel\b|\bas needed\b|\bmeet-?ups?\b"
    r"|\b(?:team|company) (?:gatherings?|summits?|retreats?|events?)\b|\binterviews?\b|\bonboarding\b",
    re.I,
)
# "remote or hybrid", "hybrid/remote" — remote is still on the table.
_REMOTE_OPTION_RE = re.compile(
    r"\bremote\s*(?:or|/|and|,)\s*(?:hybrid|on[- ]?site|in[- ]office)\b"
    r"|\b(?:hybrid|on[- ]?site|in[- ]office)\s*(?:or|/|,)\s*(?:fully\s+)?remote\b",
    re.I,
)

_FEDERAL_RE = re.compile(
    r"\bfederal (?:government|agency|agencies|clients?|customers?|contracts?|programs?|"
    r"sector|space|civilian|health|missions?|employees?|employment|position|job)\b"
    r"|\bU\.?\s?S\.? (?:federal )?government\b"
    r"|\busa ?jobs\b"
    r"|\bGS-\s?\d{1,2}\b"
    r"|\bsecurity clearance\b"
    r"|\b(?:active|current|existing|secret|top[- ]secret|ts|dod|government|federal)\s+clearance\b"
    r"|\b(?:obtain|maintain|hold|eligib\w*(?: (?:for|to obtain))?)\s+(?:an?\s+)?(?:\w+\s+){0,2}clearance\b"
    r"|\bts/sci\b|\btop[- ]secret\b|\bpublic trust\b|\bpolygraph\b"
    r"|\bdepartment of (?:defense|homeland security|veterans affairs|energy|state|justice|"
    r"health and human services|the (?:army|navy|air force))\b"
    r"|\b(?:DoD|DHS|NSA|FBI|CIA|DISA|USCIS)\b"
    r"|\bintelligence community\b",
    re.I,
)
# EEO / legal boilerplate mentions "federal" in nearly every US posting.
_FEDERAL_BOILERPLATE_RE = re.compile(
    r"\blaws?\b|\blegal(?:ly)?\b|\bregulations?\b|\bequal (?:employment )?opportunity\b|\beeo\b"
    r"|\bdiscriminat\w*|\bprotected\b|\bvevraa\b|\be-verify\b|\bofccp\b|\baffirmative action\b"
    r"|\bholidays?\b|\btax\w*\b|\bminimum wage\b",
    re.I,
)

_CLEARANCE_RE = re.compile(r"clearance|ts/sci|secret|polygraph|public trust", re.I)

_LABELS = {
    "hybrid": "Hybrid role",
    "onsite": "On-site / in-office role",
    "federal": "Federal / government-clearance job",
}


@dataclass
class JobFilterReason:
    category: str  # hybrid | onsite | federal
    label: str
    evidence: str


@dataclass
class JobFilterResult:
    blocked: bool
    reasons: list[JobFilterReason] = field(default_factory=list)

    def message(self) -> str:
        kinds = ", ".join(dict.fromkeys(r.label.lower() for r in self.reasons))
        return (
            f"Resume generation blocked: this posting looks like a {kinds}. "
            "Uncheck \"Only fully remote, non-federal jobs\" to generate it anyway."
        )


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?:\r?\n)+|(?<=[.!?;])\s+|\s+[•·▪●]\s+", text or "")
    return [re.sub(r"\s+", " ", p).strip(" -•*\t") for p in parts if p and p.strip(" -•*\t")]


def _snippet(sentence: str, match: re.Match[str], width: int = 160) -> str:
    if len(sentence) <= width:
        return sentence
    start = max(0, match.start() - width // 2)
    end = min(len(sentence), start + width)
    start = max(0, end - width)
    return ("…" if start else "") + sentence[start:end].strip() + ("…" if end < len(sentence) else "")


def check_job_filter(job_description: str) -> JobFilterResult:
    """Flag postings that are hybrid, on-site, or federal / clearance-bound."""
    found: dict[str, list[str]] = {}

    def add(category: str, sentence: str, match: re.Match[str]) -> None:
        bucket = found.setdefault(category, [])
        if len(bucket) < 2:
            snippet = _snippet(sentence, match)
            if snippet not in bucket:
                bucket.append(snippet)

    for sentence in _sentences(job_description):
        remote_option = bool(_REMOTE_OPTION_RE.search(sentence))
        if not remote_option:
            match = _HYBRID_RE.search(sentence) or _OFFICE_DAYS_RE.search(sentence)
            if match:
                add("hybrid", sentence, match)
            match = _ONSITE_RE.search(sentence)
            if match and not _ONSITE_EXCEPTION_RE.search(sentence):
                add("onsite", sentence, match)
        match = _FEDERAL_RE.search(sentence)
        if match and not (
            _FEDERAL_BOILERPLATE_RE.search(sentence) and not _CLEARANCE_RE.search(match.group(0))
        ):
            add("federal", sentence, match)

    reasons = [
        JobFilterReason(category=category, label=_LABELS[category], evidence=evidence)
        for category in ("hybrid", "onsite", "federal")
        for evidence in found.get(category, [])
    ]
    return JobFilterResult(blocked=bool(reasons), reasons=reasons)


def enforce_job_filter(remote_nonfederal_only: str, job_description: str) -> None:
    """422 with the triggering phrases when the "fully remote, non-federal" box is on and the job fails it."""
    if (remote_nonfederal_only or "").strip().lower() not in ("1", "true", "yes", "on"):
        return
    screen = check_job_filter(job_description)
    if screen.blocked:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "job_filter_blocked",
                "message": screen.message(),
                "reasons": [asdict(reason) for reason in screen.reasons],
            },
        )
