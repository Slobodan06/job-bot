"""Deterministic form-field classification and value resolution for the extension.

Pure functions (no DB, no network) so they can be unit-tested. The route layer
adds the OpenAI call for genuine free-text screener questions.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.resume_model import ResumeModel, split_date_range

# Keys the autofill profile may carry. EEO / demographic keys are opt-in and only
# emitted when the user explicitly set a value.
PROFILE_TEXT_FIELDS: tuple[str, ...] = (
    "first_name", "last_name", "phone", "phone_country_code", "phone_device_type",
    "address", "address_line2", "city", "state", "postal_code",
    "country", "linkedin", "github", "portfolio", "website", "pronouns",
    "desired_salary", "notice_period_days", "start_date",
    "years_of_experience", "highest_education", "how_heard_about_us",
    "gender", "race_ethnicity", "veteran_status", "disability_status",
    "application_password",
)
PROFILE_BOOL_FIELDS: tuple[str, ...] = (
    "work_authorized", "requires_sponsorship", "currently_employed",
    "willing_to_relocate", "over_18", "worked_here_before", "has_drivers_license",
)

_MAX_TEXT = 400
_YES = "yes"
_NO = "no"

# (canonical_key, pattern tested against "label name placeholder autocomplete")
_FIELD_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\be-?mail\b", re.I)),
    ("first_name", re.compile(r"\bfirst[\s_-]*name\b|\bgiven[\s_-]*name\b|\bfname\b", re.I)),
    ("last_name", re.compile(r"\blast[\s_-]*name\b|\bfamily[\s_-]*name\b|\bsurname\b|\blname\b", re.I)),
    ("full_name", re.compile(r"\b(full[\s_-]*name|your[\s_-]*name|candidate[\s_-]*name)\b|^name$", re.I)),
    ("password", re.compile(r"\bpassword\b|\bpasscode\b", re.I)),
    ("phone_country_code", re.compile(r"(country|calling)\s*code|phone\s*country", re.I)),
    ("phone_device_type", re.compile(r"phone\s*(device\s*)?type|device\s*type", re.I)),
    ("phone", re.compile(r"\bphone\b|\bmobile\b|\btelephone\b|\bcell\b", re.I)),
    ("linkedin", re.compile(r"linkedin", re.I)),
    ("github", re.compile(r"github", re.I)),
    ("portfolio", re.compile(r"portfolio|personal\s*(web)?site|\bwebsite\b|\bblog\b", re.I)),
    ("city", re.compile(r"\bcity\b|\btown\b", re.I)),
    ("state", re.compile(r"\bstate\b|\bprovince\b|\bregion\b", re.I)),
    ("postal_code", re.compile(r"\b(zip|postal)\s*code\b|\bpostcode\b", re.I)),
    ("country", re.compile(r"\bcountry\b", re.I)),
    ("address_line2", re.compile(
        r"address\s*(line\s*)?2|apt(?:artment)?\.?\s*(#|number)?|\bsuite\b|\bunit\s*(#|number)?\b", re.I)),
    ("address", re.compile(r"\b(street\s*)?address\b|\baddress\s*line\s*1\b", re.I)),
    ("current_company", re.compile(r"current\s*(employer|company)|present\s*employer", re.I)),
    ("current_title", re.compile(r"current\s*(title|role|position)|job\s*title", re.I)),
    ("currently_employed", re.compile(r"currently\s+employed|are\s+you\s+(currently\s+)?employed", re.I)),
    ("desired_salary", re.compile(r"salary|compensation|desired\s*pay|expected\s*(ctc|salary)", re.I)),
    ("notice_period_days", re.compile(r"notice\s*period", re.I)),
    ("start_date", re.compile(r"start\s*date|available(\s*to\s*start)?|availability", re.I)),
    ("years_of_experience", re.compile(r"years?\s+of\s+experience|how\s+many\s+years", re.I)),
    ("highest_education", re.compile(
        r"highest\s+(level\s+of\s+)?education|education\s+level|highest\s+degree", re.I)),
    ("how_heard_about_us", re.compile(
        r"how\s+did\s+you\s+(hear|learn)|referral\s*source|hear\s+about\s+(us|this)", re.I)),
    ("willing_to_relocate", re.compile(r"willing\s+to\s+relocate|open\s+to\s+relocat", re.I)),
    ("over_18", re.compile(r"(at\s+least\s+)?18\s+years|age\s+of\s+majority", re.I)),
    ("worked_here_before", re.compile(
        r"(previously|before)\s+work(ed)?\s+(for|at)|worked\s+(for|at)\s+.{0,20}\s+before|"
        r"former\s+employee", re.I)),
    ("has_drivers_license", re.compile(r"driver'?s?\s+licen[cs]e", re.I)),
    ("work_authorized", re.compile(
        r"legally\s*(authoriz|entitl)|authoriz(ed|ation)\s*to\s*work|right\s*to\s*work|"
        r"work\s*authoriz", re.I)),
    ("requires_sponsorship", re.compile(
        r"sponsor|visa\s*(status|sponsor)|require\s*sponsorship|need\s*sponsorship", re.I)),
    ("pronouns", re.compile(r"pronoun", re.I)),
    ("gender", re.compile(r"\bgender\b", re.I)),
    ("race_ethnicity", re.compile(r"race|ethnicit|hispanic|latino", re.I)),
    ("veteran_status", re.compile(r"veteran|protected\s*veteran|military\s*service", re.I)),
    ("disability_status", re.compile(r"disabilit|form\s*cc-?305", re.I)),
    ("linkedin_headline", re.compile(r"headline", re.I)),
    ("cover_letter", re.compile(r"cover\s*letter", re.I)),
    ("resume", re.compile(r"\b(resume|cv|upload)\b", re.I)),
)

# Free-text prompts we hand to the LLM rather than the profile.
_FREE_TEXT_RE = re.compile(
    r"why\s+(do\s+you|are\s+you|would\s+you)|what\s+(interests|excites|draws)|"
    r"tell\s+us|describe|explain|in\s+your\s+own\s+words|motivat|"
    r"what\s+makes\s+you|greatest\s+(strength|accomplishment)|proud",
    re.I,
)


def normalize_autofill_profile(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in PROFILE_TEXT_FIELDS:
        value = raw.get(key)
        if isinstance(value, (int, float)):
            value = str(value)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()[:_MAX_TEXT]
    for key in PROFILE_BOOL_FIELDS:
        if key in raw and raw[key] is not None:
            out[key] = bool(raw[key])
    answers = raw.get("custom_answers")
    if isinstance(answers, list):
        clean: list[dict[str, str]] = []
        for item in answers[:50]:
            if not isinstance(item, dict):
                continue
            q = str(item.get("q") or "").strip()[:300]
            a = str(item.get("a") or "").strip()[:2000]
            if q and a:
                clean.append({"q": q, "a": a})
        if clean:
            out["custom_answers"] = clean
    return out


def _haystack(field: dict[str, Any]) -> str:
    return " ".join(
        str(field.get(k) or "")
        for k in ("label", "name", "placeholder", "autocomplete", "aria_label", "id")
    ).lower()


def _classify_experience_group_field(field: dict[str, Any]) -> str:
    """Bare Company/Job Title/Location/From/To/Description fields inside a
    numbered 'Work Experience N' block — map each occurrence to that specific
    resume entry, not a single flat 'current employer'."""
    label = str(field.get("label") or "").strip().lower()
    text = _haystack(field)
    if label in ("from", "start date") or re.search(r"\bstart\s*date\b", text):
        return "exp_start"
    if label in ("to", "end date") or re.search(r"\bend\s*date\b", text):
        return "exp_end"
    if re.search(r"currently\s+work|i\s+currently|present(?:ly)?\s+work\s+here", text):
        return "exp_current"
    if re.search(r"\bjob\s*title\b|\btitle\b|\bposition\b", text):
        return "exp_title"
    if re.search(r"\bcompany\b|\bemployer\b|\borganization\b", text):
        return "exp_company"
    if re.search(r"\blocation\b|\bcity\b", text):
        return "exp_location"
    if re.search(r"description|responsibilit|role\s*summary|\bduties\b", text):
        return "exp_description"
    return ""


def _classify_education_group_field(field: dict[str, Any]) -> str:
    """Bare School/Degree/Field of Study/From/To fields inside a numbered
    'Education N' block — map each occurrence to that specific resume entry."""
    label = str(field.get("label") or "").strip().lower()
    text = _haystack(field)
    if label in ("from", "start date") or re.search(r"\bstart\s*date\b", text):
        return "edu_start"
    if label in ("to", "end date", "graduation date") or re.search(r"\bend\s*date\b|\bgraduation\b", text):
        return "edu_end"
    if re.search(r"\bschool\b|\binstitution\b|\buniversity\b|\bcollege\b", text):
        return "edu_school"
    if re.search(r"\bdegree\b", text):
        return "edu_degree"
    if re.search(r"field\s*of\s*study|\bmajor\b|area\s*of\s*study", text):
        return "edu_field"
    return ""


def classify_field(field: dict[str, Any]) -> str:
    group_kind = str(field.get("group_kind") or "")
    if group_kind == "experience":
        grouped = _classify_experience_group_field(field)
        if grouped:
            return grouped
    elif group_kind == "education":
        grouped = _classify_education_group_field(field)
        if grouped:
            return grouped

    text = _haystack(field)
    if not text.strip():
        return ""
    for key, pattern in _FIELD_RULES:
        if pattern.search(text):
            return key
    if len(str(field.get("label") or "")) > 12 and _FREE_TEXT_RE.search(str(field.get("label") or "")):
        return "free_text"
    if (field.get("type") or "").lower() == "textarea":
        return "free_text"
    return ""


def _split_name(full: str) -> tuple[str, str]:
    parts = re.sub(r"\s+", " ", (full or "").strip()).split(" ")
    if len(parts) < 2:
        return (parts[0] if parts else ""), ""
    return parts[0], parts[-1]


def _pick_option(value: str, options: list[str]) -> str:
    """Map a canonical value onto one of a select's real option strings."""
    if not options:
        return value
    v = value.strip().lower()
    for opt in options:
        if opt.strip().lower() == v:
            return opt
    if v in (_YES, _NO):
        for opt in options:
            o = opt.strip().lower()
            if v == _YES and o in ("yes", "y", "true"):
                return opt
            if v == _NO and o in ("no", "n", "false"):
                return opt
    for opt in options:
        o = opt.strip().lower()
        if v and (v in o or o in v):
            return opt
    if v == _NO:
        for opt in options:
            if re.search(r"decline|prefer not|do not wish|i don'?t wish", opt, re.I):
                return opt
    return ""


def _group_field_value(
    model: ResumeModel | None, canonical: str, group_index: int | None
) -> tuple[str, str]:
    """Resolve exp_*/edu_* canonical keys against the Nth resume entry."""
    if model is None or group_index is None or group_index < 0:
        return "", ""
    if canonical.startswith("exp_"):
        items = model.professional_experience
        if group_index >= len(items):
            return "", ""
        exp = items[group_index]
        start, end = split_date_range(exp.dates)
        is_current = end.strip().lower() == "present"
        mapping = {
            "exp_company": exp.company,
            "exp_title": exp.title,
            "exp_location": exp.location,
            "exp_start": start,
            "exp_end": "" if is_current else end,
            "exp_current": _YES if is_current else _NO,
            "exp_description": "\n".join(b for b in exp.responsibilities if b),
        }
        return mapping.get(canonical, ""), "resume"
    if canonical.startswith("edu_"):
        edu_items = model.education
        if group_index >= len(edu_items):
            return "", ""
        edu = edu_items[group_index]
        start, end = split_date_range(edu.duration)
        edu_mapping = {
            "edu_school": edu.school,
            "edu_degree": edu.degree,
            "edu_field": edu.field,
            "edu_start": start,
            "edu_end": end,
        }
        return edu_mapping.get(canonical, ""), "resume"
    return "", ""


def resolve_deterministic_values(
    *,
    fields: list[dict[str, Any]],
    profile: dict[str, Any],
    model: ResumeModel | None,
    email: str,
) -> dict[str, dict[str, Any]]:
    """Return {field_key: {value, source, confidence}} for every field we can fill
    from the profile or resume alone. Free-text / unknown fields are left out."""
    first = profile.get("first_name") or ""
    last = profile.get("last_name") or ""
    if (not first or not last) and model and model.name:
        f2, l2 = _split_name(model.name)
        first = first or f2
        last = last or l2
    full_name = (f"{first} {last}".strip()) or (model.name if model else "")
    contact = model.contact if model else None
    exp0 = model.professional_experience[0] if model and model.professional_experience else None

    base: dict[str, tuple[str, str]] = {}  # canonical_key -> (value, source)

    def put(key: str, value: Any, source: str) -> None:
        text = str(value).strip() if value is not None else ""
        if text:
            base.setdefault(key, (text, source))

    put("email", email, "account")
    put("first_name", first, "profile" if profile.get("first_name") else "resume")
    put("last_name", last, "profile" if profile.get("last_name") else "resume")
    put("full_name", full_name, "resume")
    put("phone", profile.get("phone"), "profile")
    put("password", profile.get("application_password"), "profile")
    for k in ("phone_country_code", "phone_device_type",
              "address", "address_line2", "city", "state", "postal_code", "country", "pronouns",
              "desired_salary", "notice_period_days", "start_date",
              "years_of_experience", "highest_education", "how_heard_about_us",
              "gender", "race_ethnicity", "veteran_status", "disability_status"):
        put(k, profile.get(k), "profile")
    put("linkedin", profile.get("linkedin") or (contact.linkedin if contact else ""), "profile")
    put("github", profile.get("github") or (contact.github if contact else ""), "profile")
    put("portfolio",
        profile.get("portfolio") or profile.get("website") or (contact.website if contact else ""),
        "profile")
    if model and model.title:
        put("current_title", model.title, "resume")
        put("linkedin_headline", model.title, "resume")
    if exp0:
        put("current_company", exp0.company, "resume")
        if not base.get("current_title"):
            put("current_title", exp0.title, "resume")
    for bool_key in (
        "work_authorized", "requires_sponsorship", "currently_employed",
        "willing_to_relocate", "over_18", "worked_here_before", "has_drivers_license",
    ):
        if bool_key in profile:
            put(bool_key, _YES if profile[bool_key] else _NO, "profile")

    out: dict[str, dict[str, Any]] = {}
    for field in fields:
        canonical = classify_field(field)
        if not canonical or canonical in ("free_text", "resume", "cover_letter"):
            continue
        if canonical.startswith("exp_") or canonical.startswith("edu_"):
            value, source = _group_field_value(model, canonical, field.get("group_index"))
        else:
            entry = base.get(canonical)
            if not entry:
                continue
            value, source = entry
        if not value:
            continue
        options = [str(o) for o in (field.get("options") or []) if str(o).strip()]
        if options:
            value = _pick_option(value, options)
            if not value:
                continue
        out[str(field.get("key"))] = {
            "canonical": canonical,
            "value": value[:_MAX_TEXT],
            "source": source,
            "confidence": 0.95 if source in ("account", "profile") else 0.8,
        }
    return out


def unresolved_free_text_fields(
    fields: list[dict[str, Any]], resolved: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fields that need an AI-drafted answer: textareas and long question labels."""
    out: list[dict[str, Any]] = []
    for field in fields:
        key = str(field.get("key"))
        if key in resolved:
            continue
        canonical = classify_field(field)
        label = str(field.get("label") or "")
        if canonical == "free_text" or (
            (field.get("type") or "").lower() in ("textarea", "text")
            and len(label) > 25
            and label.rstrip().endswith("?")
        ):
            out.append(field)
    return out


def custom_answer_for(label: str, profile: dict[str, Any]) -> str | None:
    for item in profile.get("custom_answers") or []:
        q = item.get("q", "")
        if q and (q.lower() in label.lower() or label.lower() in q.lower()):
            return item.get("a")
    return None
