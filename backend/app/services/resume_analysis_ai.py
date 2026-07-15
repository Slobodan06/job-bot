"""AI-assisted repair for fixed resume metadata extracted from difficult layouts."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Sequence

from openai import AsyncOpenAI

from app.services.openai_compat import chat_completion_controls
from app.services.pdf_resume import ContactIdentity, format_contact_identity_block, parse_contact_identity
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


def _is_allowed_link(url: str, source: str, required_domain: str = "") -> bool:
    candidate = (url or "").strip().lower().rstrip("/")
    corpus = (source or "").lower().replace("\\/", "/")
    return bool(
        candidate
        and candidate.startswith(("http://", "https://"))
        and (not required_domain or required_domain in candidate)
        and candidate in corpus.rstrip("/")
    )


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
    identity = parse_contact_identity(contact)
    suspicious_contact = bool(
        re.search(r"(?:^|\n)\s*(?:outlook|gmail|hotmail|yahoo|icloud)\.com\s*(?:$|\n)", contact, re.I)
    )
    contact_source = contact + "\n" + source_text
    header_source = "\n".join((source_text or "").splitlines()[:25])
    known_profile_urls = {
        url.lower().rstrip("/")
        for url in (
            identity.linkedin_url,
            identity.portfolio_url,
            identity.github_url,
            *(url for _label, url in identity.other_links),
        )
        if url
    }
    header_urls = {
        match.group(0).lower().rstrip("/.,;)")
        for match in re.finditer(r"https?://[^\s<>{}\[\]]+", header_source, re.I)
    }
    missing_detectable_contact = any((
        bool(re.search(r"[\w.+-]+@[\w.-]+\.\w+", contact_source)) and not identity.email,
        bool(re.search(r"\+?\d[\d\s().-]{7,}\d", contact_source)) and not identity.phone,
        "linkedin.com" in contact_source.lower() and not identity.linkedin_url,
        "github.com" in contact_source.lower() and not identity.github_url,
        bool(header_urls - known_profile_urls),
    ))
    if not needs_company and not suspicious_contact and not missing_detectable_contact:
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
  "contact": {{
    "name": "exact candidate name or empty",
    "name_evidence": "exact source line",
    "headline": "exact professional role/headline or empty",
    "headline_evidence": "exact source line",
    "email": "exact email or empty",
    "email_evidence": "exact source line",
    "phone": "exact phone or empty",
    "phone_evidence": "exact source line",
    "location": "exact candidate location or empty",
    "location_evidence": "exact source line",
    "linkedin_url": "exact LinkedIn URL or empty",
    "portfolio_url": "exact personal portfolio URL or empty",
    "github_url": "exact GitHub profile URL or empty"
  }},
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
- Contact fields must come only from the resume header/contact area. Keep email, phone, location, LinkedIn, portfolio, and GitHub separate.
- A portfolio must be the candidate's personal website, not an employer, school, email provider, or unrelated product URL.
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
    raw_contact = payload.get("contact")
    if not isinstance(raw_contact, dict):
        # Backward compatibility with the original metadata-repair response shape.
        raw_contact = {"linkedin_url": payload.get("linkedin_url", "")}

    def supported_contact(field: str) -> str:
        value = str(raw_contact.get(field) or "").strip()
        if field.endswith("_url"):
            required_domain = (
                "linkedin.com" if field == "linkedin_url"
                else "github.com" if field == "github_url"
                else ""
            )
            return value if _is_allowed_link(value, evidence_source, required_domain) else ""
        evidence = str(raw_contact.get(f"{field}_evidence") or "").strip()
        return value if _is_source_backed(value, evidence, evidence_source) else ""

    updated_identity = ContactIdentity(
        name=identity.name or supported_contact("name"),
        headline=identity.headline or supported_contact("headline"),
        email=identity.email or supported_contact("email"),
        phone=identity.phone or supported_contact("phone"),
        location=identity.location or supported_contact("location"),
        linkedin_url=identity.linkedin_url or supported_contact("linkedin_url"),
        portfolio_url=identity.portfolio_url or supported_contact("portfolio_url"),
        github_url=identity.github_url or supported_contact("github_url"),
        other_links=identity.other_links,
    )
    if updated_identity != identity:
        repaired_contact = format_contact_identity_block(updated_identity)

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
