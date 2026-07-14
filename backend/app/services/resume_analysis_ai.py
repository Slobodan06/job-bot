"""AI-assisted repair for fixed resume metadata extracted from difficult layouts."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Sequence

from openai import AsyncOpenAI

from app.services.openai_compat import chat_completion_controls
from app.services.resume_sections import WorkExperienceRole

logger = logging.getLogger(__name__)


def _json_object(value: str) -> dict[str, object]:
    text = (value or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
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


def _normalized_evidence(value: str) -> str:
    value = (value or "").casefold().replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", value).strip()


def _is_source_backed(value: str, evidence: str, source: str) -> bool:
    candidate = _normalized_evidence(value)
    quoted = _normalized_evidence(evidence)
    corpus = _normalized_evidence(source)
    return bool(candidate and quoted and candidate in quoted and quoted in corpus)


def _is_allowed_link(url: str, source: str) -> bool:
    candidate = (url or "").strip().lower().rstrip("/")
    corpus = (source or "").lower().replace("\\/", "/")
    return bool(candidate and "linkedin.com/" in candidate and candidate in corpus.rstrip("/"))


async def repair_resume_metadata_with_ai(
    *,
    contact: str,
    roles: Sequence[WorkExperienceRole],
    source_text: str,
) -> tuple[str, tuple[WorkExperienceRole, ...]]:
    """Fill missing links/employers from source-backed AI extraction; preserve known fields."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or not roles:
        return contact, tuple(roles)

    needs_company = any(not (role.company or "").strip() for role in roles)
    suspicious_contact = bool(
        re.search(r"(?:^|\n)\s*(?:outlook|gmail|hotmail|yahoo|icloud)\.com\s*(?:$|\n)", contact, re.I)
    )
    source_has_linkedin = "linkedin.com/" in (contact + "\n" + source_text).lower()
    if not needs_company and not suspicious_contact and not source_has_linkedin:
        return contact, tuple(roles)

    roles_payload = [
        {
            "index": index,
            "header": role.header,
            "company": role.company,
            "title": role.title,
            "location": role.location,
            "period": role.period,
            "first_bullets": list(role.bullets[:2]),
        }
        for index, role in enumerate(roles)
    ]
    evidence_source = "\n".join(filter(None, [contact, source_text]))[:40000]
    prompt = f"""SOURCE RESUME TEXT:
{evidence_source}

CURRENT PARSED ROLES:
{json.dumps(roles_payload, ensure_ascii=False)}

Return JSON only:
{{
  "linkedin_url": "exact URL copied from SOURCE RESUME TEXT or empty",
  "roles": [
    {{
      "index": 0,
      "company": "exact employer copied from source or empty",
      "company_evidence": "exact source line containing that employer",
      "title": "exact title copied from source or empty",
      "title_evidence": "exact source line containing that title",
      "location": "exact location copied from source or empty",
      "location_evidence": "exact source line containing that location",
      "period": "exact date range copied from source or empty",
      "period_evidence": "exact source line containing that date range"
    }}
  ]
}}

Rules:
- This is extraction, not resume writing. Never infer or invent an employer, title, date, location, or URL.
- Use surrounding order, dates, titles, bullets, and layout artifacts to associate each employer with the correct role.
- Preserve role indexes and return one object per parsed role.
- company_evidence and other evidence fields must be verbatim source text; leave a value empty when no exact evidence exists.
- A mail provider domain such as outlook.com is never a LinkedIn or portfolio URL.
"""
    model = (
        os.getenv("OPENAI_MODEL_ANALYSIS", "").strip()
        or os.getenv("OPENAI_MODEL_FAST", "").strip()
        or "gpt-4o-mini"
    )
    try:
        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120") or "120")
        client = AsyncOpenAI(api_key=api_key, timeout=max(30.0, min(timeout, 300.0)))
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You repair structured resume metadata from noisy document extraction. "
                        "Copy fixed facts exactly and return strict JSON. Never invent facts."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            **chat_completion_controls(model, max_output_tokens=3000, temperature=0),
        )
        payload = _json_object(completion.choices[0].message.content or "")
    except Exception:
        logger.exception("AI resume metadata repair failed; retaining deterministic analysis")
        return contact, tuple(roles)

    repaired_contact = contact
    linkedin_url = str(payload.get("linkedin_url") or "").strip()
    if linkedin_url and _is_allowed_link(linkedin_url, evidence_source):
        if linkedin_url.lower().rstrip("/") not in repaired_contact.lower().rstrip("/"):
            repaired_contact = "\n".join(filter(None, [repaired_contact.strip(), linkedin_url]))

    repaired_roles = list(roles)
    raw_roles = payload.get("roles")
    if isinstance(raw_roles, list):
        for item in raw_roles:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index", -1))
            except (TypeError, ValueError):
                continue
            if not 0 <= index < len(repaired_roles):
                continue
            role = repaired_roles[index]

            def supported(field: str) -> str:
                value = str(item.get(field) or "").strip()
                evidence = str(item.get(f"{field}_evidence") or "").strip()
                return value if _is_source_backed(value, evidence, evidence_source) else ""

            company = role.company or supported("company")
            title = role.title or supported("title")
            location = role.location or supported("location")
            period = role.period or supported("period")
            repaired_roles[index] = WorkExperienceRole(
                header=" | ".join(part for part in (company, title, location, period) if part) or role.header,
                company=company,
                title=title,
                location=location,
                period=period,
                bullets=role.bullets,
            )

    return repaired_contact, tuple(repaired_roles)
