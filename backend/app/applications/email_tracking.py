"""Gmail-driven status tracking for the application tracker.

The extension reads job emails in the member's open Gmail tab (inbox rows and
opened messages) and posts them here. Each email is classified into a stage —
application received, assessment, interview, offer, rejection, or other — and
matched to one of the member's tracked applications, whose status is then moved
*forward* (never back: an old "we received your application" never undoes
"interviewing").

Each email is handled once per member (``email_signals``, keyed by the
extension's message key). Only metadata is stored there, never the body.

Classification uses the configured AI provider; without one, a keyword
heuristic and a company-name match are used instead.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.applications.logic import advances_status, as_utc
from app.database import get_db
from app.services.llm_config import llm_configured, llm_model, make_llm_client
from app.services.openai_compat import chat_completion_controls

logger = logging.getLogger(__name__)

STAGES = ("application", "assessment", "interview", "offer", "rejection", "other")
STAGE_TO_STATUS = {
    "application": "submitted",
    "assessment": "assessment",
    "interview": "interviewing",
    "offer": "offer",
    "rejection": "rejected",
}

# Per member, per rolling 24h: emails that may reach the AI classifier.
MAX_CLASSIFIED_PER_DAY = 400
AI_BATCH_SIZE = 15
CANDIDATE_APPLICATIONS = 150
# An email older than the application (minus this slack) is about an earlier attempt.
RECEIVED_SLACK = timedelta(days=2)

_ATS_SENDER_RE = re.compile(
    r"greenhouse|lever\.co|hire\.lever|workday|myworkday|ashbyhq|smartrecruiters|workable|icims|"
    r"jobvite|bamboohr|breezy|recruitee|teamtailor|jazzhr|applytojob|successfactors|taleo|"
    r"rippling|gem\.com|dover|wellfound|hackerrank|codility|codesignal|testgorilla|hirevue",
    re.I,
)
_JOB_TEXT_RE = re.compile(
    r"\b(?:appl(?:y|ied|ying|ication)s?|candidacy|candidate|interview\w*|assessment|"
    r"coding (?:challenge|test|exercise)|take[- ]home|online test|offer|unfortunately|regret|"
    r"moving forward|move forward|next steps?|recruit\w*|hiring|talent (?:acquisition|team)|"
    r"position|opportunity|role)\b",
    re.I,
)

_HEURISTIC_STAGES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "rejection",
        re.compile(
            r"unfortunately|regret to inform|not (?:to )?(?:be )?mov(?:e|ing) forward|"
            r"decided to (?:pursue|proceed|move forward) with other|other candidates|"
            r"no longer (?:being )?considered|position has been filled|will not be (?:proceeding|moving)",
            re.I,
        ),
    ),
    ("offer", re.compile(r"offer letter|pleased to (?:offer|extend)|job offer|extend (?:you )?an offer", re.I)),
    (
        "assessment",
        re.compile(
            r"\bassessment\b|coding (?:challenge|test|exercise)|take[- ]home|hackerrank|codility|"
            r"codesignal|testgorilla|online test",
            re.I,
        ),
    ),
    (
        "interview",
        re.compile(
            r"\binterview|phone screen|schedule (?:a )?(?:call|time|chat|meeting)|calendly|your availability",
            re.I,
        ),
    ),
    (
        "application",
        re.compile(
            r"(?:thank you|thanks) for (?:applying|your application|your interest)|"
            r"application (?:has been |was )?(?:received|submitted)|we(?:'ve| have)? received your application",
            re.I,
        ),
    ),
)

_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:inc|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|ag|sa|bv|pty|group|holdings|"
    r"technologies|technology|labs|careers|jobs|recruiting|talent|team|hiring)\b\.?",
    re.I,
)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------


def email_text(email: dict[str, Any], body_chars: int = 4000) -> str:
    parts = [email.get("from_name"), email.get("subject"), email.get("snippet"), (email.get("body") or "")[:body_chars]]
    return "\n".join(str(p) for p in parts if p)


def looks_job_related(email: dict[str, Any]) -> bool:
    """Cheap filter in front of the AI: ATS senders, or job words in sender/subject/snippet."""
    if _ATS_SENDER_RE.search(email.get("from_email") or ""):
        return True
    head = " ".join(str(email.get(k) or "") for k in ("from_name", "subject", "snippet"))
    return bool(_JOB_TEXT_RE.search(head))


def heuristic_stage(email: dict[str, Any]) -> str:
    text = email_text(email)
    for stage, pattern in _HEURISTIC_STAGES:
        if pattern.search(text):
            return stage
    return "other"


def normalize_company(name: str) -> str:
    text = (name or "").lower().replace("&", " and ")
    text = _COMPANY_SUFFIX_RE.sub(" ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#]+", (text or "").lower()) if len(t) > 2}


def _title_overlap(a: str, b: str) -> int:
    return len(_tokens(a) & _tokens(b))


def match_application(
    apps: list[dict[str, Any]], email: dict[str, Any], *, company: str = "", job_title: str = ""
) -> dict[str, Any] | None:
    """Deterministic fallback: an application whose company the email names.

    ``company`` (when the classifier extracted one) must equal the tracked company
    after normalizing; otherwise the tracked company must appear as whole words in
    the email. Several jobs at one company are told apart by job-title overlap,
    then the most recently updated wins.
    """
    wanted = normalize_company(company)
    haystack = f" {normalize_company(email_text(email, 1500))} "
    found: list[dict[str, Any]] = []
    for app in apps:
        norm = normalize_company(app.get("company") or "")
        if len(norm) < 3:
            continue
        if wanted:
            short, long_ = sorted((norm, wanted), key=len)
            if len(short) >= 4 and f" {short} " in f" {long_} ":
                found.append(app)
        elif f" {norm} " in haystack:
            found.append(app)
    if not found:
        return None
    title = job_title or (email.get("subject") or "")
    # Stable sort: apps arrive most-recently-updated first, so ties keep that order.
    found.sort(key=lambda a: _title_overlap(a.get("job_title") or "", title), reverse=True)
    return found[0]


def received_in_window(app: dict[str, Any], received_at: datetime | None) -> bool:
    """False for an email that predates this application (an earlier attempt at the same company)."""
    if received_at is None:
        return True
    starts = [as_utc(d) for d in (app.get("created_at"), app.get("submitted_at")) if isinstance(d, datetime)]
    if not starts:
        return True
    return as_utc(received_at) >= min(starts) - RECEIVED_SLACK


def _json_object(value: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (value or "").strip(), flags=re.I)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def build_prompt(emails: list[dict[str, Any]], apps: list[dict[str, Any]]) -> str:
    tracked = [
        {"a": i, "company": a.get("company") or "", "job_title": a.get("job_title") or "", "status": a.get("status")}
        for i, a in enumerate(apps)
    ]
    items = [
        {
            "i": i,
            "from": f"{e.get('from_name') or ''} <{e.get('from_email') or ''}>",
            "subject": e.get("subject") or "",
            "text": ((e.get("body") or "") or (e.get("snippet") or ""))[:3000],
        }
        for i, e in enumerate(emails)
    ]
    return f"""TRACKED APPLICATIONS (the candidate's own job applications):
{json.dumps(tracked, ensure_ascii=False)}

EMAILS:
{json.dumps(items, ensure_ascii=False)}

For every email return one result. Return JSON only:
{{"results": [{{"i": 0, "stage": "application|assessment|interview|offer|rejection|other", "company": "", "job_title": "", "a": null}}]}}

Stages:
- application: confirms the candidate's application was received/submitted.
- assessment: invites the candidate to an online assessment, coding challenge, test or take-home assignment.
- interview: invites the candidate to interview / phone screen, asks for availability, or confirms an interview time.
- offer: makes or discusses a job offer.
- rejection: the company is not moving forward with the candidate.
- other: anything else — job alerts, newsletters, recommendations, marketing, cold recruiter outreach about new roles, account or password emails.

Rules:
- company / job_title: the hiring company and role the email is about, copied from the email; empty if not stated. The ATS vendor (Greenhouse, Lever, Workday...) is never the company.
- a: index of the tracked application this email is about, or null. Only match when the company clearly is the same; when several applications share that company, use the job title to choose, and use null if you cannot tell.
- When unsure about the stage, use "other".
"""


def parse_results(payload: dict[str, Any], n_emails: int, n_apps: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"stage": "other", "company": "", "job_title": "", "a": None} for _ in range(n_emails)]
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        i = row.get("i")
        if not isinstance(i, int) or not 0 <= i < n_emails:
            continue
        stage = str(row.get("stage") or "other").strip().lower()
        a = row.get("a")
        out[i] = {
            "stage": stage if stage in STAGES else "other",
            "company": str(row.get("company") or "").strip()[:200],
            "job_title": str(row.get("job_title") or "").strip()[:300],
            "a": a if isinstance(a, int) and not isinstance(a, bool) and 0 <= a < n_apps else None,
        }
    return out


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


async def _classify_with_ai(emails: list[dict[str, Any]], apps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    model = llm_model("OPENAI_MODEL_EMAIL", "OPENAI_MODEL_FAST", openai_default="gpt-4o-mini", role="fast")
    client = make_llm_client(max_timeout=90)
    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You triage a job seeker's emails: classify each one's hiring stage and match it "
                    "to their tracked applications. Return strict JSON. Never guess a match."
                ),
            },
            {"role": "user", "content": build_prompt(emails, apps)},
        ],
        response_format={"type": "json_object"},
        **chat_completion_controls(model, max_output_tokens=200 + 120 * len(emails), temperature=0),
    )
    return parse_results(_json_object(completion.choices[0].message.content or ""), len(emails), len(apps))


async def classify(emails: list[dict[str, Any]], apps: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """One result per email, or None if the AI call failed (retry later)."""
    if not llm_configured():
        return [{"stage": heuristic_stage(e), "company": "", "job_title": "", "a": None} for e in emails]
    results: list[dict[str, Any]] = []
    for start in range(0, len(emails), AI_BATCH_SIZE):
        try:
            results += await _classify_with_ai(emails[start : start + AI_BATCH_SIZE], apps)
        except Exception:
            logger.exception("Email classification failed; the extension will resend these emails later")
            return None
    return results


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------


async def _classified_today(user_id: Any, now: datetime) -> int:
    return await get_db().email_signals.count_documents(
        {"user_id": user_id, "classified": True, "at": {"$gte": now - timedelta(days=1)}}
    )


async def _remember(user_id: Any, email: dict[str, Any], now: datetime, **fields: Any) -> None:
    try:
        await get_db().email_signals.insert_one(
            {
                "user_id": user_id,
                "key": email["key"],
                "at": now,
                "received_at": email.get("received_at"),
                "from_email": (email.get("from_email") or "")[:200],
                "subject": (email.get("subject") or "")[:300],
                **fields,
            }
        )
    except DuplicateKeyError:
        pass  # a concurrent request (another Gmail tab) handled it first


async def process_email_signals(user_id: Any, emails: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Classify new emails, move matched applications forward. Returns what changed.

    ``processed_keys`` lists every email that is now handled (the extension stops
    sending those); emails left out — AI failure or the daily limit — come back later.
    """
    db = get_db()
    unique: dict[str, dict[str, Any]] = {}
    for e in emails:
        unique.setdefault(e["key"], e)
    known = {
        d["key"]
        async for d in db.email_signals.find({"user_id": user_id, "key": {"$in": list(unique)}}, {"key": 1})
    }
    processed: list[str] = list(known)
    fresh = [e for k, e in unique.items() if k not in known]

    candidates: list[dict[str, Any]] = []
    for e in fresh:
        if looks_job_related(e):
            candidates.append(e)
        else:
            await _remember(user_id, e, now, stage="ignored", classified=False)
            processed.append(e["key"])

    room = max(0, MAX_CLASSIFIED_PER_DAY - await _classified_today(user_id, now))
    candidates = candidates[:room]
    updates: list[dict[str, Any]] = []
    if not candidates:
        return {"processed_keys": processed, "updated": updates}

    apps = (
        await db.applications.find({"user_id": user_id, "status": {"$ne": "withdrawn"}})
        .sort("updated_at", -1)
        .limit(CANDIDATE_APPLICATIONS)
        .to_list(CANDIDATE_APPLICATIONS)
    )
    if not apps:
        for e in candidates:
            await _remember(user_id, e, now, stage="skipped", classified=False)
            processed.append(e["key"])
        return {"processed_keys": processed, "updated": updates}

    # Oldest first, so a later rejection lands after an earlier interview invite.
    candidates.sort(key=lambda e: as_utc(e.get("received_at")) or now)
    results = await classify(candidates, apps)
    if results is None:
        return {"processed_keys": processed, "updated": updates}

    for email, result in zip(candidates, results):
        stage = result["stage"]
        status = STAGE_TO_STATUS.get(stage)
        app = None
        if status:
            app = apps[result["a"]] if result["a"] is not None else match_application(
                apps, email, company=result["company"], job_title=result["job_title"]
            )
        applied = None
        if app and status and received_in_window(app, email.get("received_at")):
            previous = app.get("status") or "detected"
            if advances_status(previous, status):
                changes: dict[str, Any] = {
                    "status": status,
                    "updated_at": now,
                    "last_email_update": {
                        "stage": stage,
                        "subject": (email.get("subject") or "")[:300],
                        "from_email": (email.get("from_email") or "")[:200],
                        "received_at": email.get("received_at"),
                        "at": now,
                    },
                }
                if not app.get("submitted_at"):
                    changes["submitted_at"] = email.get("received_at") or now
                await db.applications.update_one({"_id": app["_id"]}, {"$set": changes})
                app.update(changes)
                applied = status
                updates.append(
                    {
                        "application_id": str(app["_id"]),
                        "company": app.get("company") or "",
                        "job_title": app.get("job_title") or "",
                        "previous_status": previous,
                        "status": status,
                        "subject": email.get("subject") or "",
                    }
                )
        await _remember(
            user_id,
            email,
            now,
            stage=stage,
            classified=True,
            company=result["company"],
            job_title=result["job_title"],
            application_id=app["_id"] if app else None,
            applied_status=applied,
        )
        processed.append(email["key"])
    return {"processed_keys": processed, "updated": updates}
