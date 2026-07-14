"""Build a fresh tailored PDF from extracted resume data + user's smart CV template."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.schemas import TailorResponse
from app.services.docx_resume import output_docx_filename, parse_resume_from_docx
from app.services.docx_convert import pdf_download_filename
from app.services.pdf_resume import parse_contact, sanitize_for_pdf
from app.services.resume_sections import (
    WorkExperienceRole,
    resolve_docx_sections,
)
from app.services.resume_analysis_ai import repair_resume_metadata_with_ai
from app.services.resume_evidence import (
    SourceFact,
    analyze_job_description,
    assert_render_provenance,
    audit_bullets,
    build_gap_report,
    build_candidate_knowledge_base,
    build_canonical_skills_section,
    bullet_text,
    build_verified_candidate_facts,
    create_evidence_map,
    evaluate_eligibility,
    filter_supported_bullets,
    generate_clarifying_questions,
    is_experience_section_placeholder,
    normalize_generated_skills,
    parse_verified_answer_facts,
    rank_source_bullets_for_job,
    score_resume_match,
    select_nonduplicative_bullets,
    unsupported_terms_for_claim,
    validate_tailored_resume,
)
from app.services.rendercv_resume import (
    build_rendercv_resume_pdf,
    pick_random_rendercv_theme,
    rendercv_template_key,
    rendercv_template_label,
    rendercv_theme_from_template_key,
)
from app.services.render_docx_resume import build_docx_resume
from app.services.template_catalog import build_template_pdf, get_template_meta
from app.services.sectionize import ParsedResume
from app.services.tailor import (
    TailoredSections,
    _openai_client,
    _parse_json_object,
    _sanitize_llm_error,
    build_tailoring_strategy,
    build_candidate_evidence_map,
    extract_keywords,
    extract_jd_target_role_title,
    is_aws_infrastructure_jd,
    _is_applied_ai_consulting_jd,
)
from app.services.resume_prompts import CANONICAL_TAILORING_POLICY, PROMPT_VERSION
from app.services.openai_compat import chat_completion_controls
from app.services.qualification_questions import default_professional_role_index

logger = logging.getLogger(__name__)

DEFAULT_SMART_TEMPLATE_KEY = "clean-classic"


@dataclass
class ContactFields:
    name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    headline: str = ""
    links: list[str] | None = None

    def format_block(self) -> str:
        lines = [self.name] if self.name else []
        if self.headline:
            lines.append(self.headline)
        details: list[str] = []
        if self.email:
            details.append(self.email)
        if self.location:
            details.append(self.location)
        if self.phone:
            details.append(format_phone_with_plus(self.phone))
        for link in self.links or []:
            if link.strip():
                details.append(link.strip())
        if details:
            lines.append(" | ".join(details))
        return "\n".join(lines).strip()


def progressive_bullet_targets(role_count: int) -> list[int]:
    """Oldest role = fewer bullets; newest = most (for fresh PDF generation)."""
    if role_count <= 0:
        return []
    if role_count == 1:
        return [5]
    oldest = 3
    newest = min(8, 4 + role_count // 2)
    if role_count == 2:
        return [oldest, newest]
    counts: list[int] = []
    for i in range(role_count):
        t = i / (role_count - 1)
        counts.append(max(3, round(oldest + (newest - oldest) * (t**1.15))))
    for i in range(1, len(counts)):
        if counts[i] <= counts[i - 1] and counts[i] < newest:
            counts[i] = counts[i - 1] + 1
        elif counts[i] < counts[i - 1]:
            counts[i] = counts[i - 1]
    return counts


def smart_bullet_targets(
    roles: list[WorkExperienceRole],
    *,
    job_description: str,
    target_role: str,
) -> list[int]:
    """Bullet depth by career recency plus JD relevance, not a regular +1 ladder."""
    role_count = len(roles)
    if role_count <= 0:
        return []
    if role_count == 1:
        return [8]

    jd_terms = [term.lower() for term in extract_keywords(job_description, top_k=24)]
    target_terms = [part.lower() for part in re.split(r"[\s,/|+-]+", target_role or "") if len(part) > 2]
    all_terms = list(dict.fromkeys(jd_terms + target_terms))
    max_count = 10 if role_count >= 3 else 9
    counts: list[int] = []
    for i, role in enumerate(roles):
        role_text = " ".join(
            [
                role.title,
                role.company,
                role.header,
                " ".join(role.bullets),
            ]
        ).lower()
        recency = i / (role_count - 1)
        matches = sum(1 for term in all_terms if term and term in role_text)
        relevance_bonus = 0
        if matches >= 8:
            relevance_bonus = 2
        elif matches >= 3:
            relevance_bonus = 1
        if i == 0:
            count = 3 + min(relevance_bonus, 1)
        elif i == role_count - 1:
            count = max_count
        else:
            count = 3 + round((recency**1.7) * (max_count - 3)) + relevance_bonus
        counts.append(max(3, min(max_count, count)))

    counts[-1] = max(counts[-1], max(counts), max_count - 1)
    if role_count >= 3 and counts[-2] == counts[-1]:
        counts[-2] = max(3, counts[-1] - 2)
    return counts


def expand_bullet_targets_for_confirmed_evidence(
    targets: list[int], facts: list[SourceFact]
) -> list[int]:
    """Give any role richer space when the candidate supplied detailed omitted work."""
    expanded = list(targets)
    for role_index in range(len(expanded)):
        experience_id = f"exp_{role_index + 1:03d}"
        detailed = [
            fact
            for fact in facts
            if fact.source == "candidate_verified_answer"
            and fact.experience_id == experience_id
            and not fact.text.lower().startswith("candidate confirms")
            and not fact.text.lower().startswith("which missing skills can you personally confirm")
        ]
        if not detailed:
            continue
        dimension_count = sum(
            max(1, len(re.findall(r"[.;]|\b(?:built|designed|integrated|validated|tested|deployed|monitored|documented|optimized|maintained)\b", fact.text, re.I)))
            for fact in detailed
        )
        expanded[role_index] = max(expanded[role_index], min(10, 4 + dimension_count))
    return expanded


def _role_start_sort_key(role: WorkExperienceRole, fallback_index: int) -> tuple[int, int, int]:
    text = " ".join(
        part
        for part in (
            role.period,
            role.header,
        )
        if part
    )
    patterns = (
        r"\b(?P<month>\d{1,2})\s*/\s*(?P<year>\d{4})\b",
        r"\b(?P<year>\d{4})\s*[-/]\s*(?P<month>\d{1,2})\b",
        r"\b(?P<year>\d{4})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        year = int(match.group("year"))
        month = int(match.groupdict().get("month") or 1)
        if 1 <= month <= 12:
            return (year, month, fallback_index)
    return (9999, 12, fallback_index)


def sort_roles_by_start_date(roles: list[WorkExperienceRole]) -> list[WorkExperienceRole]:
    return [
        role
        for _key, role in sorted(
            ((_role_start_sort_key(role, i), role) for i, role in enumerate(roles)),
            key=lambda item: item[0],
        )
    ]


def format_phone_with_plus(phone: str) -> str:
    raw = sanitize_for_pdf(phone or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        return raw
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw
    if len(digits) == 10:
        return "+1" + digits
    return "+" + digits


def contact_fields_from_block(contact_block: str) -> ContactFields:
    parsed = parse_contact(contact_block or "")
    def _phone_detail(value: str) -> bool:
        digits = re.sub(r"\D", "", value or "")
        return "@" not in value and 10 <= len(digits) <= 15

    phone = next((d for d in parsed.details if _phone_detail(d)), "")
    links = [url for _, url in parsed.links]
    if parsed.linkedin_url and parsed.linkedin_url not in links:
        links.insert(0, parsed.linkedin_url)
    return ContactFields(
        name=sanitize_for_pdf(parsed.name),
        email=next((d for d in parsed.details if "@" in d), ""),
        phone=format_phone_with_plus(phone),
        location=next(
            (d for d in parsed.details if "@" not in d and not _phone_detail(d)),
            "",
        ),
        headline=sanitize_for_pdf(parsed.headline or ""),
        links=links[:4],
    )


def _looks_like_long_profile_line(line: str) -> bool:
    text = sanitize_for_pdf(line or "").strip()
    if not text:
        return False
    if len(text) > 110:
        return True
    return len(text.split()) >= 16 and not re.search(r"@|https?://|linkedin\.com|github\.com|\+?\d[\d\s().-]{7,}", text, re.I)


def _line_has_contact_fact(line: str) -> bool:
    text = sanitize_for_pdf(line or "").strip()
    if not text:
        return False
    if re.search(r"[\w.+-]+@[\w.-]+\.\w+", text):
        return True
    if re.search(r"https?://|linkedin\.com|github\.com|(?:www\.)?[a-z0-9][a-z0-9.-]*\.(?:com|net|org|io|dev|me|app)", text, re.I):
        return True
    if re.search(r"\+?\d[\d\s().-]{7,}\d", text):
        return True
    if re.search(r",\s*[A-Za-zÀ-ÿ]", text) and len(text) < 80:
        return True
    return False


def split_smart_contact_and_summary(contact_block: str) -> tuple[str, str]:
    lines = [sanitize_for_pdf(line).strip() for line in (contact_block or "").splitlines() if sanitize_for_pdf(line).strip()]
    if not lines:
        return "", ""
    name = lines[0]
    contact_lines = [name]
    summary_lines: list[str] = []
    short_headline = ""

    for line in lines[1:]:
        if _looks_like_long_profile_line(line):
            summary_lines.append(line)
            continue
        if _line_has_contact_fact(line):
            contact_lines.append(line)
            continue
        if not short_headline and len(line) <= 90:
            short_headline = line
        else:
            summary_lines.append(line)

    if short_headline and any(_line_has_contact_fact(line) for line in contact_lines[1:]):
        contact_lines.insert(1, short_headline)
    elif short_headline:
        summary_lines.insert(0, short_headline)

    return "\n".join(dict.fromkeys(contact_lines)).strip(), "\n".join(summary_lines).strip()


def merge_contact_profile_into_summary(contact_block: str, summary: str) -> tuple[str, str]:
    smart_contact, profile_summary = split_smart_contact_and_summary(contact_block)
    parts = [part.strip() for part in (profile_summary, summary) if part and part.strip()]
    merged_summary = "\n\n".join(dict.fromkeys(parts)).strip()
    return smart_contact or contact_block, merged_summary


def format_experience_section(roles: list[WorkExperienceRole], bullets_by_role: list[list[object]]) -> str:
    """Scott-style pipe header: Company | Title | Location | Period."""
    blocks: list[str] = []
    for role, bullets in zip(roles, bullets_by_role):
        header_bits: list[str] = []
        if role.company:
            header_bits.append(role.company.strip())
        if role.title:
            header_bits.append(role.title.strip())
        if role.location:
            header_bits.append(role.location.strip())
        if role.period:
            header_bits.append(role.period.strip())
        lines: list[str] = []
        if header_bits:
            lines.append(" | ".join(header_bits))
        for bullet in bullets:
            body = bullet.strip().lstrip("-•* ").strip()
            if body:
                lines.append(f"- {body}")
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks).strip()


def _clean_bullet(text: str) -> str:
    return sanitize_for_pdf(text or "").strip().lstrip("-â€¢* ").strip()


def format_experience_section(roles: list[WorkExperienceRole], bullets_by_role: list[list[object]]) -> str:
    """Scott-style pipe header: Company | Title | Location | Period."""
    blocks: list[str] = []
    for role, bullets in zip(roles, bullets_by_role):
        header_bits: list[str] = []
        if role.company:
            header_bits.append(role.company.strip())
        if role.title:
            header_bits.append(role.title.strip())
        if role.location:
            header_bits.append(role.location.strip())
        if role.period:
            header_bits.append(role.period.strip())
        lines: list[str] = []
        if header_bits:
            lines.append(" | ".join(header_bits))
        for bullet in bullets:
            body = bullet_text(bullet).lstrip("-* ").strip()
            if body:
                lines.append(f"- {body}")
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks).strip()


def _clean_bullet(text: object) -> str:
    value = bullet_text(text) if isinstance(text, dict) else str(text or "")
    return sanitize_for_pdf(value).strip().lstrip("-* ").strip()


def _fallback_role_bullets(
    role: WorkExperienceRole,
    *,
    want: int,
    job_description: str,
    target_role: str,
    role_index: int,
    role_count: int,
) -> list[str]:
    cleaned = [_clean_bullet(b) for b in role.bullets if _clean_bullet(b)]
    out: list[str] = []
    seen: set[str] = set()
    for bullet in cleaned:
        key = bullet.lower()
        if key not in seen:
            seen.add(key)
            out.append(bullet)
        if len(out) >= want:
            return out[:want]
    return out[:want]


def _ensure_progressive_bullets(
    roles: list[WorkExperienceRole],
    bullets_by_role: list[list[object]],
    bullets_per_role: list[int],
    *,
    job_description: str,
    target_role: str,
) -> list[list[object]]:
    role_count = len(roles)
    out: list[list[object]] = []
    for i, role in enumerate(roles):
        want = max(3, bullets_per_role[i] if i < len(bullets_per_role) else 3)
        existing = bullets_by_role[i] if i < len(bullets_by_role) else []
        merged: list[object] = [b for b in existing if _clean_bullet(b)]
        if len(merged) < want:
            fallback = _fallback_role_bullets(
                role,
                want=want,
                job_description=job_description,
                target_role=target_role,
                role_index=i,
                role_count=role_count,
            )
            for bullet in fallback:
                if len(merged) >= want:
                    break
                if bullet.lower() not in {_clean_bullet(b).lower() for b in merged}:
                    merged.append(bullet)
        out.append(merged[:want])
    return out


def _parse_skill_tokens(skills_text: str) -> list[str]:
    tokens: list[str] = []
    for line in sanitize_for_pdf(skills_text or "").splitlines():
        clean = line.strip().lstrip("-â€¢* ").strip()
        if not clean:
            continue
        if ":" in clean:
            clean = clean.split(":", 1)[1]
        for token in re.split(r"[,;|/]", clean):
            token = token.strip()
            if token and len(token) > 1:
                tokens.append(token)
    return list(dict.fromkeys(tokens))


def build_fresh_skills_section(
    *,
    source_skills: str,
    tailored_skills: str,
    job_description: str,
    target_role: str,
    summary: str,
    experience: str,
) -> str:
    jd_terms = extract_keywords(job_description, top_k=18)
    source_tokens = _parse_skill_tokens(source_skills)
    tailored_tokens = _parse_skill_tokens(tailored_skills)
    evidence_text = " ".join([source_skills, summary, experience]).lower()
    combined: list[str] = []
    for token in tailored_tokens + source_tokens + jd_terms:
        clean = token.strip()
        key = clean.lower()
        if not clean or key in {t.lower() for t in combined}:
            continue
        if key in evidence_text or any(part in evidence_text for part in key.split() if len(part) > 3):
            combined.append(clean)
    if not combined:
        combined = source_tokens[:20]

    role_lower = (target_role + " " + job_description).lower()
    if re.search(r"\b(ai|ml|llm|machine learning|rag|agentic|data science)\b", role_lower):
        labels = ["AI & LLM", "Backend & APIs", "Data & Retrieval", "Cloud & DevOps", "Engineering Practices"]
    elif re.search(r"\b(devops|sre|platform|cloud|infrastructure|kubernetes|terraform)\b", role_lower):
        labels = ["Cloud Platforms", "Infrastructure", "Containers & CI/CD", "Monitoring & Security", "Engineering Practices"]
    elif re.search(r"\b(frontend|react|ui|ux)\b", role_lower):
        labels = ["Frontend", "Backend & APIs", "Data", "Cloud & DevOps", "Engineering Practices"]
    else:
        labels = ["Core Technologies", "Backend & APIs", "Cloud & DevOps", "Data & Storage", "Engineering Practices"]

    rules = {
        "AI & LLM": r"ai|llm|openai|rag|retrieval|prompt|agent|langchain|model|ml",
        "Backend & APIs": r"api|backend|python|java|node|fastapi|django|spring|rest|graphql",
        "Data & Retrieval": r"data|sql|postgres|mongo|redis|vector|retrieval|etl|pipeline",
        "Cloud & DevOps": r"aws|azure|gcp|docker|kubernetes|terraform|ci/cd|github actions",
        "Engineering Practices": r"testing|debug|observability|leadership|agile|security|monitoring|documentation",
        "Cloud Platforms": r"aws|azure|gcp|cloud|iam|vpc|rds|lambda",
        "Infrastructure": r"terraform|iac|network|linux|helm|gitops|infrastructure",
        "Containers & CI/CD": r"docker|kubernetes|aks|eks|ci/cd|jenkins|github actions",
        "Monitoring & Security": r"monitor|grafana|datadog|splunk|security|rbac|key vault",
        "Frontend": r"react|angular|vue|typescript|javascript|css|html|ui|frontend",
        "Data": r"sql|database|analytics|pandas|spark|etl|data",
        "Data & Storage": r"sql|postgres|mysql|mongo|redis|storage|database",
        "Core Technologies": r"python|java|javascript|typescript|c#|go|react|node",
    }

    buckets: dict[str, list[str]] = {label: [] for label in labels}
    for token in combined:
        best = max(
            labels,
            key=lambda label: (2 if re.search(rules.get(label, ""), f"{token} {label}".lower()) else 0, -len(buckets[label])),
        )
        buckets[best].append(token)

    lines: list[str] = []
    for label in labels:
        tokens = buckets[label]
        if len(tokens) < 4:
            for token in combined:
                if token not in tokens:
                    tokens.append(token)
                if len(tokens) >= 4:
                    break
        if tokens:
            lines.append(f"{label}: {', '.join(tokens[:8])}")
    return "\n".join(lines).strip()


def build_supported_summary(*, skills: str, experience_block: str, target_role: str = "") -> str:
    skill_terms: list[str] = []
    for line in (skills or "").splitlines():
        if ":" in line:
            skill_terms.extend([part.strip() for part in line.split(":", 1)[1].split(",") if part.strip()])
    bullets = [
        line.strip().lstrip("-*• ").strip()
        for line in (experience_block or "").splitlines()
        if line.strip().startswith("-")
    ]
    lead = "Software engineer"
    sentences = [
        f"{lead} specializing in {', '.join(skill_terms[:3])}." if skill_terms
        else f"{lead} with a record of delivering practical software solutions.",
    ]
    if bullets:
        first = bullets[0].rstrip(".")
        sentences.append(first[:1].upper() + first[1:] + ".")
    if len(bullets) > 1:
        second = bullets[1].rstrip(".")
        sentences.append(second[:1].upper() + second[1:] + ".")
    if len(sentences) < 3 and len(skill_terms) > 3:
        sentences.append(f"Technical strengths also include {', '.join(skill_terms[3:7])}.")
    summary = " ".join(sentences).strip()
    words = summary.split()
    return " ".join(words[:80]).rstrip(" ,;") + "."


FRESH_RESUME_SYSTEM = """You are an expert resume writer. Tailor a candidate resume for ONE target job.
Return ONLY valid JSON with these keys:
- professional_summary (string, 4-5 information-dense sentences, engineering voice, no first person)
- skills (string, 6-10 labeled categories with colon format; include the broadest nonredundant set of JD-relevant, source-supported or candidate-confirmed tools/skills)
- roles (array of objects, one per employer in order, each with:
    - bullets (array of strings WITHOUT leading dashes — accomplishment lines only))

Rules:
- Ground every bullet in the candidate's source bullets — do not invent employers or tools.
- Optimize for the TARGET JOB, not the candidate's unrelated strengths.
- Career arc: oldest company has fewer, concise bullets; newest company has the richest, most detailed bullets.
- Fill the requested bullet_count whenever distinct verified evidence supports it; never pad with repetition.
- Never generate bullets from scratch. Select from ranked_source_bullets, then rewrite without changing meaning.
- Bullet rewrite rules: do not add technologies, metrics, projects, industries, or responsibilities absent from the source bullet/facts.
- Bullets should be specific and detailed (18-28 words), with technologies, scope, ownership, or impact where supported.
- Skills must mirror the job description priorities, ordered from most relevant to least relevant, using only defensible source-supported skills.
- Vary bullet structure; max 40% bullets ending with metrics.
- Use verbs: Built, Designed, Owned, Led, Debugged — not Spearheaded/Engineered/Leveraged."""

EVIDENCE_RESUME_SYSTEM = """You are an evidence-based resume tailoring engine.
Your goal is to create the strongest truthful resume for a target job while preserving factual accuracy.

Return ONLY valid JSON with these keys:
- professional_summary (string, 4-5 information-dense sentences, derived from final verified bullets, no first person)
- skills (string, 6-10 labeled categories with colon format; include the broadest nonredundant set of JD-relevant, source-supported or candidate-confirmed tools/skills)
- roles (array of objects, one per employer in order, each with:
    - experienceId (must match the input role)
    - bullets (array of objects with generated_text, experienceId, source_fact_ids, sourceBulletIds, evidence_strength, unsupported_terms))

NON-NEGOTIABLE ACCURACY RULES:
- Never invent or assume experience.
- Never create a project, technology, achievement, metric, responsibility, industry, certification, or duration absent from VERIFIED_CANDIDATE_DATA.
- Do not copy requirements from the job description into the resume unless supported by candidate evidence.
- Do not change official job titles solely to match the target role.
- Do not calculate years of experience unless dates and relevant experience support the calculation.
- Do not describe tool usage as production experience without evidence of production deployment.
- Do not convert exposure, familiarity, or AI-assisted development into expert-level experience.
- When evidence is insufficient, mark the requirement as a gap instead of fabricating content.

TAILORING RULES:
- First build an internal coverage plan: mandatory requirements, core responsibilities, preferred qualifications, then the verified evidence that supports each one. Do not output the plan.
- Give the most resume space to high-weight supported requirements. Omit unsupported requirements rather than disguising them as transferable experience.
- Summary must be comprehensive but concise: sentence 1 establishes supported professional identity and specialization; sentence 2 covers the strongest job-aligned technical scope; sentence 3 covers supported ownership, delivery, domain, or impact; sentence 4 is optional.
- Experience bullets must prove the summary. Prefer concrete problem, action, technology, scope, and outcome details already present in the source over generic duty statements.
- Within each role, order bullets by target-job relevance: core responsibility evidence first, enabling technology next, then supporting collaboration or operations.
- Prioritize facts most relevant to the target role.
- Rewrite bullets using action + task + technology + outcome.
- Include metrics only when present in verified data.
- Use terminology from the job description only when it accurately describes existing experience.
- Remove irrelevant detail when space is limited.
- Avoid keyword stuffing and repeated skills.
- Keep the professional summary consistent with the work history; generate it last.
- Skills listed in skills must be demonstrated by work, projects, education, or certifications.
- Use concise, natural, recruiter-readable language and ATS-friendly standard headings.
- Optimize for the TARGET JOB, not unrelated strengths.
- Career arc: oldest company has fewer, concise bullets; newest company has the richest, most detailed bullets.
- Fill the requested bullet_count whenever distinct verified evidence supports it; never pad with repetition.
- Bullets should be specific and detailed (20-34 words), with technologies, system purpose, scope, ownership, reliability, or impact where supported.
- Exhaust the useful dimensions of each detailed candidate-confirmed fact. Separate architecture, service development, integrations, data flow, validation, failure handling, testing, deployment, monitoring, documentation, and supported outcomes into distinct bullets when the evidence states them.
- Skills must mirror the job description priorities, ordered from most relevant to least relevant, using only defensible source-supported skills.
- Do not repeat a skill. Do not place soft skills inside technical categories. Prefer specific technologies over vague phrases.
- Vary bullet structure; max 40% bullets ending with metrics.
- Use verbs: Built, Designed, Owned, Led, Debugged - not Spearheaded/Engineered/Leveraged.

EVIDENCE RULE:
For every generated bullet, return source_fact_ids from VERIFIED_CANDIDATE_DATA.
Every generated bullet must keep the same experienceId as its input role and use source_fact_ids from that same role.
If unsupported_terms is not empty, the application will remove that bullet from the final resume.""" + "\n\n" + CANONICAL_TAILORING_POLICY


SAMPLE_RESUME_SYSTEM = """You generate an idealized SAMPLE resume for software developers testing a resume-building application.
The content is fictional sample data, not factual employment verification.

Return ONLY valid JSON with these keys:
- professional_summary: 4-5 dense, ATS-friendly sentences targeted to the job
- skills: one newline-delimited STRING containing 10-12 labeled technical categories using `Category: skill, skill`; never return skills as an array or object
- roles: one object per supplied role, in the same order, with experienceId and bullets

FIXED SOURCE FIELDS:
- Preserve the supplied candidate name and contact details.
- Preserve every employer, official title, location, and employment date exactly.
- Preserve education exactly.
- Never invent a new employer, role, date, degree, certification, or school.

SAMPLE CONTENT AUTHORIZATION:
- Create the strongest plausible fictional summary, technical skills, responsibilities, systems, accomplishments, and metrics for a perfect match to the target job.
- Put all invented technical work inside the existing professional roles. Never create a Selected Technical Projects section.
- Make the newest role the strongest match with 10-12 rich bullets; use 8-10 for the next role and 5-7 for older roles.
- Return exactly the `bullet_count` requested for every role. Do not stop early when more distinct job-relevant dimensions can be written.
- Cover every essential job requirement in context, including production ownership, architecture, implementation, data movement, integrations, validation, testing, deployment, monitoring, documentation, communication, and business results.
- Use varied action verbs and concise 20-34 word bullets. Avoid repetition, filler, placeholders, and copied job-description sentences.
- Invent realistic sample metrics where useful and keep each metric attached to the accomplishment it measures.
- Generate a comprehensive 45-60 item technical-skills inventory ordered by target-job priority. Cover programming, AI/LLMs, document processing, backend/APIs, data engineering, databases, cloud/DevOps, testing/quality, security/compliance, observability, architecture, and relevant domain knowledge.
- Do not include disclaimers or editorial notes inside the resume content."""


async def _llm_generate_fresh_content(
    *,
    client: AsyncOpenAI,
    job_description: str,
    target_role: str,
    contact: ContactFields,
    roles: list[WorkExperienceRole],
    source_summary: str,
    source_skills: str,
    bullets_per_role: list[int],
    strategy_prompt: str,
    candidate_knowledge_base: dict[str, object],
    verified_facts: list[SourceFact],
    job_analysis: dict[str, object],
    requirement_evidence_map: list[dict[str, object]],
    sample_mode: bool = False,
) -> tuple[str, str, list[list[str]]]:
    roles_payload = []
    for i, role in enumerate(roles):
        experience_id = f"exp_{i + 1:03d}"
        confirmed_role_evidence = [
            {"fact_id": fact.fact_id, "text": fact.text}
            for fact in verified_facts
            if fact.source == "candidate_verified_answer" and fact.experience_id == experience_id
        ]
        roles_payload.append(
            {
                "index": i,
                "experienceId": experience_id,
                "title": role.title,
                "company": role.company,
                "period": role.period,
                "location": role.location,
                "bullet_count": bullets_per_role[i] if i < len(bullets_per_role) else 3,
                "source_bullets": list(role.bullets)[:20],
                "candidate_confirmed_role_evidence": confirmed_role_evidence,
                "ranked_source_bullets": rank_source_bullets_for_job(
                    list(role.bullets),
                    job_analysis,  # type: ignore[arg-type]
                    limit=20,
                    experience_id=experience_id,
                ),
            }
        )
    coverage_instructions = (
        "SAMPLE COVERAGE INSTRUCTIONS:\n"
        "1. Treat every required and preferred job qualification as available for fictional sample generation.\n"
        "2. Demonstrate essential requirements repeatedly but nonredundantly across Summary, Skills, and Work Experience.\n"
        "3. Invent realistic production systems, implementation details, operational ownership, outcomes, and metrics under the existing roles.\n"
        "4. Preserve all fixed source fields and create no new employer, title, date, school, degree, or certification.\n"
        "5. Make the newest role read as an exceptional direct match and maintain a plausible career progression.\n"
        if sample_mode
        else
        "REQUIREMENT COVERAGE INSTRUCTIONS:\n"
        "1. Cover every high-weight supported requirement at least once across summary, skills, or experience.\n"
        "2. Prove core responsibilities in experience bullets; do not merely list them in skills.\n"
        "3. Use every relevant candidate_confirmed_role_evidence item and expand its explicitly stated dimensions into distinct, defensible bullets.\n"
        "4. Use partial/transferable evidence only with the candidate's actual technology and scope.\n"
        "5. Never mention missing requirements in generated resume content.\n"
        "6. Avoid duplicating the same claim across summary and multiple roles.\n"
    )
    user = (
        f"TARGET ROLE: {target_role}\n\n"
        f"{strategy_prompt}\n\n"
        "INPUTS\n"
        f"CANDIDATE_KNOWLEDGE_BASE:\n{json.dumps(candidate_knowledge_base, ensure_ascii=False)[:12000]}\n\n"
        f"VERIFIED_CANDIDATE_DATA:\n{json.dumps([fact.__dict__ for fact in verified_facts], ensure_ascii=False)[:12000]}\n\n"
        f"JOB_ANALYSIS:\n{json.dumps(job_analysis, ensure_ascii=False)[:9000]}\n\n"
        f"EVIDENCE_MAP:\n{json.dumps(requirement_evidence_map, ensure_ascii=False)[:12000]}\n\n"
        f"{coverage_instructions}\n"
        f"CANDIDATE: {contact.name}\n"
        f"SOURCE SUMMARY:\n{(source_summary or '')[:1500]}\n\n"
        f"SOURCE SKILLS:\n{(source_skills or '')[:1500]}\n\n"
        f"EMPLOYERS (oldest first — match bullet_count per role):\n"
        f"{json.dumps(roles_payload, ensure_ascii=False)}\n\n"
        f"JOB DESCRIPTION:\n{job_description.strip()[:8000]}"
    )
    writer_model = os.getenv("OPENAI_MODEL_WRITE", os.getenv("OPENAI_MODEL", "chat-latest"))
    completion = await client.chat.completions.create(
        model=writer_model,
        **chat_completion_controls(writer_model, max_output_tokens=12000, temperature=0.55),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SAMPLE_RESUME_SYSTEM if sample_mode else EVIDENCE_RESUME_SYSTEM},
            {"role": "user", "content": user},
        ],
    )
    data = _parse_json_object(completion.choices[0].message.content or "{}")
    summary = str(data.get("professional_summary", "")).strip()
    skills = normalize_generated_skills(data.get("skills", ""))
    raw_roles = data.get("roles")
    bullets_out: list[list[str]] = []
    if isinstance(raw_roles, list):
        for i, _role in enumerate(roles):
            entry = raw_roles[i] if i < len(raw_roles) else {}
            bl = entry.get("bullets") if isinstance(entry, dict) else []
            if not isinstance(bl, list):
                bl = []
            if sample_mode:
                cleaned = [
                    str(item.get("generated_text") or item.get("text") or "").strip().lstrip("-• ").strip()
                    if isinstance(item, dict)
                    else str(item).strip().lstrip("-• ").strip()
                    for item in bl
                ]
                bullets_out.append([item for item in cleaned if item][: bullets_per_role[i]])
                continue
            if any(isinstance(item, dict) for item in bl):
                want = bullets_per_role[i] if i < len(bullets_per_role) else 3
                bullets_out.append(
                    filter_supported_bullets(
                        bl,
                        list(roles[i].bullets),
                        verified_facts,
                        role_index=i,
                        wanted=want,
                    )
                )
                continue
            cleaned = [str(b).strip().lstrip("-• ").strip() for b in bl if str(b).strip()]
            want = bullets_per_role[i] if i < len(bullets_per_role) else 3
            if len(cleaned) < want and roles[i].bullets:
                for src in roles[i].bullets:
                    if len(cleaned) >= want:
                        break
                    if src.lower() not in {b.lower() for b in cleaned}:
                        cleaned.append(src)
            bullets_out.append(cleaned[:want])
    else:
        bullets_out = [list(r.bullets)[: bullets_per_role[i]] for i, r in enumerate(roles)]
    return summary, skills, bullets_out


def _bind_verified_answers_to_roles(
    answer_facts: list[SourceFact], roles: list[WorkExperienceRole]
) -> list[SourceFact]:
    """Attach confirmed experience by explicit employer or unique strong role context."""
    bound: list[SourceFact] = []
    for fact in answer_facts:
        if fact.text.lower().startswith("which missing skills can you personally confirm"):
            bound.append(fact)
            continue
        matches = [
            (i, role)
            for i, role in enumerate(roles)
            if role.company and role.company.lower() in fact.text.lower()
        ]
        if len(matches) == 1:
            i, role = matches[0]
            bound.append(SourceFact(
                fact.fact_id,
                fact.text,
                fact.source,
                role.company,
                fact.verified,
                experience_id=f"exp_{i + 1:03d}",
                title=role.title,
            ))
        elif not matches:
            fact_terms = set(re.findall(r"[a-z0-9+#.]{3,}", fact.text.lower()))
            generic = {
                "with", "that", "this", "from", "using", "used", "built", "work",
                "what", "omitted", "experience", "personally", "confirm",
            }
            fact_terms -= generic
            scored: list[tuple[int, int, WorkExperienceRole]] = []
            for i, role in enumerate(roles):
                role_blob = " ".join([role.title, role.company, role.header, *role.bullets]).lower()
                role_terms = set(re.findall(r"[a-z0-9+#.]{3,}", role_blob)) - generic
                scored.append((len(fact_terms & role_terms), i, role))
            scored.sort(reverse=True, key=lambda item: item[0])
            best = scored[0] if scored else None
            second_score = scored[1][0] if len(scored) > 1 else 0
            if best and best[0] >= 3 and best[0] - second_score >= 2:
                _, i, role = best
                bound.append(SourceFact(
                    fact.fact_id,
                    fact.text,
                    fact.source,
                    role.company,
                    fact.verified,
                    experience_id=f"exp_{i + 1:03d}",
                    title=role.title,
                ))
            else:
                fallback_i = default_professional_role_index(fact.text, roles)
                if fallback_i is None:
                    bound.append(fact)
                else:
                    role = roles[fallback_i]
                    bound.append(SourceFact(
                        fact.fact_id,
                        fact.text,
                        fact.source,
                        role.company,
                        fact.verified,
                        experience_id=f"exp_{fallback_i + 1:03d}",
                        title=role.title,
                    ))
        else:
            bound.append(fact)
    return bound


def _candidate_confirmation_report(facts: list[SourceFact]) -> tuple[list[str], list[str]]:
    report: list[str] = []
    unplaced_projects: list[str] = []
    for fact in facts:
        if fact.source != "candidate_verified_answer":
            continue
        lower = fact.text.lower()
        if lower.startswith("which missing skills can you personally confirm"):
            report.append("Additional skills integrated as candidate-confirmed technical evidence.")
        elif lower.startswith("candidate confirms"):
            report.append(
                "A Yes-only qualification was integrated conservatively into positioning and skills; no employer, project, metric, or accomplishment was invented."
            )
        elif fact.experience_id:
            report.append(f"Additional experience integrated under {fact.company or fact.title or fact.experience_id}.")
        else:
            answer = re.sub(
                r"^what omitted experience can you personally confirm\??\s*",
                "",
                fact.text,
                flags=re.I,
            ).strip()
            if (
                re.search(r"\bai\b|ai tool", answer, re.I)
                and re.search(r"unstructured document", answer, re.I)
                and re.search(r"structured document|structured output", answer, re.I)
            ):
                answer = "Applied AI tools to convert multiple unstructured documents into structured outputs."
            report.append(
                "Unscoped confirmation was retained only for conservative summary and skills positioning."
            )
    return list(dict.fromkeys(report)), unplaced_projects


def _confirmed_fallback_bullets(facts: list[SourceFact], role_index: int) -> list[dict[str, object]]:
    """Preserve detailed candidate-confirmed work if a model rewrite fails validation."""
    experience_id = f"exp_{role_index + 1:03d}"
    out: list[dict[str, object]] = []
    for fact in facts:
        if (
            fact.source != "candidate_verified_answer"
            or fact.experience_id != experience_id
            or fact.text.lower().startswith("candidate confirms")
            or fact.text.lower().startswith("which missing skills can you personally confirm")
        ):
            continue
        chunks = [
            re.sub(r"^I\s+", "", chunk.strip(), flags=re.I)
            for chunk in re.split(r"(?<=[.!?])\s+|;\s+", fact.text)
            if len(chunk.strip().split()) >= 6
        ]
        for chunk in chunks:
            polished = chunk[:1].upper() + chunk[1:]
            out.append(
                {
                    "generated_text": polished.rstrip(".") + ".",
                    "source_fact_ids": [fact.fact_id],
                    "unsupported_terms": [],
                }
            )
    return out


def _ensure_confirmed_evidence_coverage(
    generated: list[object], facts: list[SourceFact], role_index: int
) -> list[object]:
    """Prepend exact confirmed facts only when the model omitted their source IDs."""
    fact_lookup = {fact.fact_id: fact for fact in facts}
    represented: set[str] = set()
    for bullet in generated:
        if not isinstance(bullet, dict):
            continue
        raw_ids = bullet.get("source_fact_ids") or bullet.get("sourceIds") or bullet.get("sourceFactIds") or []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        bullet_text_value = _clean_bullet(bullet).lower()
        bullet_terms = set(re.findall(r"[a-z0-9+#.-]{3,}", bullet_text_value))
        for source_id in raw_ids:
            source_key = str(source_id)
            fact = fact_lookup.get(source_key)
            if not fact:
                continue
            fact_terms = set(re.findall(r"[a-z0-9+#.-]{3,}", fact.text.lower()))
            if len(bullet_terms & fact_terms) >= 3:
                represented.add(source_key)
    fallbacks = _confirmed_fallback_bullets(facts, role_index)
    missing_ids = {
        str(source_id)
        for fallback in fallbacks
        for source_id in fallback.get("source_fact_ids", [])
        if str(source_id) not in represented
    }
    guaranteed = [
        fallback
        for fallback in fallbacks
        if any(str(source_id) in missing_ids for source_id in fallback.get("source_fact_ids", []))
    ]
    return [*guaranteed, *generated]


def _sample_provenance_bullets(
    roles: list[WorkExperienceRole], generated: list[list[object]], targets: list[int]
) -> list[list[dict[str, object]]]:
    """Wrap intentionally fictional sample bullets without candidate-evidence validation."""
    output: list[list[dict[str, object]]] = []
    for role_index, role in enumerate(roles):
        wanted = targets[role_index] if role_index < len(targets) else 3
        source = generated[role_index] if role_index < len(generated) else []
        texts: list[str] = []
        for item in source:
            text = _clean_bullet(item)
            if text and text.lower() not in {existing.lower() for existing in texts}:
                texts.append(text)
            if len(texts) >= wanted:
                break
        if len(texts) < wanted:
            for item in role.bullets:
                text = _clean_bullet(item)
                if text and text.lower() not in {existing.lower() for existing in texts}:
                    texts.append(text)
                if len(texts) >= wanted:
                    break
        experience_id = f"exp_{role_index + 1:03d}"
        output.append([
            {
                "text": text,
                "finalText": text,
                "experienceId": experience_id,
                "company": role.company,
                "title": role.title,
                "sourceIds": [f"sample_{experience_id}_{bullet_index:03d}"],
                "sourceFactIds": [f"sample_{experience_id}_{bullet_index:03d}"],
                "sourceBulletIds": [],
                "metricIds": [],
                "transformationType": "fictional_sample",
                "validationStatus": "sample_mode",
            }
            for bullet_index, text in enumerate(texts, start=1)
        ])
    return output


def _has_practical_ai_evidence(facts: list[SourceFact]) -> bool:
    ai_pattern = re.compile(r"\b(openai|claude|gemini|bedrock|llm|large language model|ai tool)\b", re.I)
    for fact in facts:
        if not ai_pattern.search(fact.text):
            continue
        if fact.fact_id.startswith("exp_") or fact.source == "project":
            return True
        if (
            fact.source == "candidate_verified_answer"
            and not fact.text.lower().startswith("which missing skills can you personally confirm")
        ):
            return True
    return False


async def build_fresh_tailored_resume(
    *,
    source_docx_bytes: bytes,
    original_filename: str,
    job_description: str,
    target_job_role: str = "",
    cv_template_key: str | None = None,
    candidate_answers: str = "",
    sample_mode: bool = True,
) -> TailorResponse:
    """Extract structured data → AI tailor → user's smart CV template PDF."""
    docx_doc = parse_resume_from_docx(source_docx_bytes)
    resolved = resolve_docx_sections(source_docx_bytes, doc=docx_doc)

    repaired_contact, repaired_roles = await repair_resume_metadata_with_ai(
        contact=resolved.contact,
        roles=resolved.work_experience_roles,
        source_text=docx_doc.plain_text,
    )

    roles = [
        role
        for role in repaired_roles
        if not is_experience_section_placeholder(role)
    ]
    if not roles:
        raise ValueError("No work experience roles detected in the uploaded resume.")
    roles = sort_roles_by_start_date(roles)

    smart_contact_block, source_summary = merge_contact_profile_into_summary(
        repaired_contact,
        resolved.professional_summary,
    )
    contact = contact_fields_from_block(smart_contact_block)
    education = resolved.education
    other = resolved.other
    source_skills = resolved.skills
    source_experience = resolved.professional_experience

    target_role = (target_job_role or extract_jd_target_role_title(job_description) or "").strip()
    candidate_knowledge_base = build_candidate_knowledge_base(
        contact=smart_contact_block,
        summary=source_summary,
        skills=source_skills,
        roles=roles,
        education=education,
        other=other,
    )
    verified_facts = build_verified_candidate_facts(
        contact=smart_contact_block,
        summary=source_summary,
        skills=source_skills,
        roles=roles,
        education=education,
        other=other,
    )
    verified_facts.extend(
        _bind_verified_answers_to_roles(parse_verified_answer_facts(candidate_answers), roles)
    )
    integration_report, _unplaced_projects = _candidate_confirmation_report(verified_facts)
    job_analysis = analyze_job_description(job_description)
    requirement_evidence_map = create_evidence_map(job_analysis, verified_facts)
    eligibility = evaluate_eligibility(job_analysis, verified_facts)
    gap_report = build_gap_report(requirement_evidence_map)
    clarifying_questions = generate_clarifying_questions(gap_report) if gap_report else []
    if sample_mode:
        gap_report = []
        clarifying_questions = []
    bullets_per_role = smart_bullet_targets(
        roles,
        job_description=job_description,
        target_role=target_role,
    )
    bullets_per_role = expand_bullet_targets_for_confirmed_evidence(bullets_per_role, verified_facts)
    if sample_mode:
        role_count = len(roles)
        bullets_per_role = [
            12 if index == role_count - 1 else 10 if index == role_count - 2 else 6
            for index in range(role_count)
        ]

    key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_configured = bool(key)
    if sample_mode and not key:
        raise ValueError("OPENAI_API_KEY is required to generate an ideal fictional sample resume.")
    used_llm = False
    llm_error = ""
    summary = source_summary
    skills = source_skills
    bullets_by_role: list[list[str]] = [list(r.bullets) for r in roles]

    if key:
        try:
            evidence_map = build_candidate_evidence_map(
                source_skills,
                source_summary,
                source_experience,
            )
            strategy = build_tailoring_strategy(
                ParsedResume(
                    contact=smart_contact_block,
                    professional_summary=source_summary,
                    professional_experience=source_experience,
                    skills=source_skills,
                    education=education,
                    other=other,
                ),
                job_description,
                evidence_map,
                target_job_role=target_role,
                is_consulting_ai=_is_applied_ai_consulting_jd(target_role, job_description),
                is_aws_infrastructure=is_aws_infrastructure_jd(target_role, job_description),
            )
            from app.services.tailor import build_tailoring_strategy_prompt

            strategy_prompt = build_tailoring_strategy_prompt(strategy)
            if sample_mode:
                strategy_prompt = (
                    "SAMPLE MODE: infer the ideal target-role profile from the job description. "
                    "Preserve fixed source fields, but synthesize perfect-match summary, skills, and role bullets."
                )
            client = _openai_client(key)
            summary, skills, bullets_by_role = await _llm_generate_fresh_content(
                client=client,
                job_description=job_description,
                target_role=target_role,
                contact=contact,
                roles=roles,
                source_summary=source_summary,
                source_skills=source_skills,
                bullets_per_role=bullets_per_role,
                strategy_prompt=strategy_prompt,
                candidate_knowledge_base=candidate_knowledge_base,
                verified_facts=verified_facts,
                job_analysis=job_analysis,
                requirement_evidence_map=requirement_evidence_map,
                sample_mode=sample_mode,
            )
            used_llm = True
        except Exception as exc:
            logger.exception("Fresh resume LLM generation failed")
            llm_error = _sanitize_llm_error(exc)
            bullets_by_role = []
            for i, role in enumerate(roles):
                want = max(3, bullets_per_role[i] if i < len(bullets_per_role) else 3)
                bullets_by_role.append(list(role.bullets)[:want])

    contact_block = smart_contact_block or contact.format_block()
    if sample_mode:
        bullets_by_role = _sample_provenance_bullets(roles, bullets_by_role, bullets_per_role)
        skill_audit = [
            {
                "claimId": "sample_skills",
                "finalText": skills,
                "sourceType": "fictional_sample",
                "transformationType": "fictional_sample",
                "include": True,
            }
        ]
        if not summary:
            summary = f"Sample {target_role or 'software engineering'} professional aligned to the target job."
    else:
        bullets_by_role = [
            filter_supported_bullets(
                _ensure_confirmed_evidence_coverage(
                    list(bullets_by_role[i]) if i < len(bullets_by_role) else [],
                    verified_facts,
                    i,
                ),
                list(role.bullets),
                verified_facts,
                role_index=i,
                wanted=max(3, bullets_per_role[i] if i < len(bullets_per_role) else 3),
            )
            for i, role in enumerate(roles)
        ]
        bullets_by_role = _ensure_progressive_bullets(
            roles,
            bullets_by_role,
            bullets_per_role,
            job_description=job_description,
            target_role=target_role,
        )
        bullets_by_role = [
            filter_supported_bullets(
                list(bullets_by_role[i]) if i < len(bullets_by_role) else [],
                list(role.bullets),
                verified_facts,
                role_index=i,
                wanted=max(1, bullets_per_role[i] if i < len(bullets_per_role) else 1),
            )
            for i, role in enumerate(roles)
        ]
        bullets_by_role = select_nonduplicative_bullets(
            roles,
            bullets_by_role,
            verified_facts,
            max_total=int(os.getenv("RESUME_MAX_EXPERIENCE_BULLETS", "32") or "32"),
        )
    assert_render_provenance(roles, bullets_by_role)
    display_roles = list(reversed(roles))
    display_bullets_by_role = list(reversed(bullets_by_role))
    experience_block = format_experience_section(display_roles, display_bullets_by_role)
    if not sample_mode:
        skills, skill_audit = build_canonical_skills_section(
            source_skills=source_skills,
            job_description=job_description,
            facts=verified_facts,
            final_experience=experience_block,
        )
        invalid_skills = [
            skill
            for skill in skill_audit
            if skill.get("sourceType") not in {"candidate_resume", "candidate_verified_answer"}
            or not skill.get("sourceIds")
        ]
        if invalid_skills:
            raise ValueError("Critical unsupported resume claim blocked: skill sourced outside verified candidate evidence.")
        if summary and re.search(r"\b(ai|llm|openai|claude|gemini|bedrock)\b", summary, re.I) and not _has_practical_ai_evidence(verified_facts):
            summary = build_supported_summary(skills=skills, experience_block=experience_block, target_role="")
        elif summary and unsupported_terms_for_claim(summary, verified_facts):
            summary = build_supported_summary(skills=skills, experience_block=experience_block, target_role=target_role)
        elif not summary:
            summary = build_supported_summary(skills=skills, experience_block=experience_block, target_role=target_role)

    plain = "\n\n".join(
        filter(
            None,
            [
                contact_block,
                f"PROFESSIONAL SUMMARY\n{summary}" if summary else "",
                f"SKILLS\n{skills}" if skills else "",
                f"PROFESSIONAL EXPERIENCE\n{experience_block}" if experience_block else "",
                f"EDUCATION\n{education}" if education else "",
                f"ADDITIONAL\n{other}" if other else "",
            ],
        )
    )

    match_scores = score_resume_match(
        job_analysis=job_analysis,
        evidence_map=requirement_evidence_map,
        final_resume_text=plain,
        eligibility=eligibility,
    )
    if sample_mode:
        match_scores.update({
            "keyword_match": 100,
            "experience_match": 100,
            "evidence_match": 100,
            "minimum_qualification_match": 100,
            "mandatoryQualificationMatch": 100,
            "preferredQualificationMatch": 100,
            "ats_score": 100,
            "atsFormattingScore": 100,
            "credibility_score": 100,
            "credibilityScore": 100,
            "overall_match": 100,
            "overallMatch": 100,
            "criticalGaps": [],
        })
    numeric_match_scores = {key: value for key, value in match_scores.items() if isinstance(value, int)}
    bullet_audit = audit_bullets(
        roles=roles,
        bullets_by_role=bullets_by_role,
        facts=verified_facts,
        job_analysis=job_analysis,
    )
    validation = (
        {"status": "SAMPLE_MODE", "issues": []}
        if sample_mode
        else validate_tailored_resume(
            summary=summary,
            skills=skills,
            bullets_by_role=bullets_by_role,
            facts=verified_facts,
        )
    )
    critical_issues = [issue for issue in validation.get("issues", []) if issue.get("severity") in {"critical", "high"}]
    if critical_issues and not sample_mode:
        logger.warning("Generated claims failed validation; repairing only invalid claims from verified facts: %s", critical_issues[:3])
        # Keep every valid generated bullet. Replace only rejected claims, and
        # prioritize exact candidate-confirmed work before original resume filler.
        invalid_claims = {
            _clean_bullet(str(issue.get("claim", ""))).lower()
            for issue in critical_issues
            if str(issue.get("claim", "")).lower() not in {"summary", "skills"}
        }
        bullets_by_role = [
            filter_supported_bullets(
                [
                    *[
                        bullet
                        for bullet in (bullets_by_role[i] if i < len(bullets_by_role) else [])
                        if _clean_bullet(bullet).lower() not in invalid_claims
                    ],
                    *_confirmed_fallback_bullets(verified_facts, i),
                ],
                list(role.bullets),
                verified_facts,
                role_index=i,
                wanted=max(1, bullets_per_role[i] if i < len(bullets_per_role) else 1),
            )
            for i, role in enumerate(roles)
        ]
        bullets_by_role = select_nonduplicative_bullets(
            roles,
            bullets_by_role,
            verified_facts,
            max_total=int(os.getenv("RESUME_MAX_EXPERIENCE_BULLETS", "32") or "32"),
        )
        display_roles = list(reversed(roles))
        display_bullets_by_role = list(reversed(bullets_by_role))
        experience_block = format_experience_section(display_roles, display_bullets_by_role)
        summary = build_supported_summary(skills=skills, experience_block=experience_block, target_role="")
        plain = "\n\n".join(
            filter(
                None,
                [
                    contact_block,
                    f"PROFESSIONAL SUMMARY\n{summary}" if summary else "",
                    f"SKILLS\n{skills}" if skills else "",
                    f"PROFESSIONAL EXPERIENCE\n{experience_block}" if experience_block else "",
                    f"EDUCATION\n{education}" if education else "",
                    f"ADDITIONAL\n{other}" if other else "",
                ],
            )
        )
        validation = validate_tailored_resume(
            summary=summary,
            skills=skills,
            bullets_by_role=bullets_by_role,
            facts=verified_facts,
        )
        remaining_critical = [
            issue
            for issue in validation.get("issues", [])
            if issue.get("severity") in {"critical", "high"}
        ]
        if remaining_critical:
            logger.error("Source-backed recovery still reported validation issues: %s", remaining_critical[:3])

    requested_template_key = (cv_template_key or "").strip()
    rendercv_error = ""
    used_rendercv = False

    theme = (
        rendercv_theme_from_template_key(requested_template_key)
        if requested_template_key.startswith("rendercv-")
        else pick_random_rendercv_theme()
    )
    template_key = rendercv_template_key(theme)
    template_label = rendercv_template_label(theme)
    try:
        pdf_bytes = build_rendercv_resume_pdf(
            theme=theme,
            contact=contact_block,
            professional_summary=summary,
            roles=display_roles,
            bullets_by_role=[[bullet_text(bullet) for bullet in role_bullets] for role_bullets in display_bullets_by_role],
            skills=skills,
            education=education,
            other=other,
        )
        used_rendercv = True
    except Exception as exc:
        logger.exception("RenderCV PDF generation failed")
        rendercv_error = _sanitize_llm_error(exc)
        template_key = requested_template_key or DEFAULT_SMART_TEMPLATE_KEY

    if not used_rendercv:
        try:
            pdf_bytes, template_key, template_label = build_template_pdf(
                template_key,
                contact=contact_block,
                professional_summary=summary,
                professional_experience=experience_block,
                skills=skills,
                education=education,
                other=other,
            )
        except KeyError:
            template_key = DEFAULT_SMART_TEMPLATE_KEY
            pdf_bytes, template_key, template_label = build_template_pdf(
                template_key,
                contact=contact_block,
                professional_summary=summary,
                professional_experience=experience_block,
                skills=skills,
                education=education,
                other=other,
            )
            template_label = get_template_meta(template_key)["label"]

    import base64

    pdf_name = pdf_download_filename(original_filename.replace(".docx", "-tailored.pdf"))
    if not pdf_name.endswith(".pdf"):
        pdf_name = "resume-tailored.pdf"
    docx_bytes = build_docx_resume(
        contact=contact_block,
        professional_summary=summary,
        roles=display_roles,
        bullets_by_role=[
            [bullet_text(bullet) for bullet in role_bullets]
            for role_bullets in display_bullets_by_role
        ],
        skills=skills,
        education=education,
        other=other,
    )
    docx_name = output_docx_filename(original_filename)

    tailored = TailoredSections(
        contact=contact_block,
        professional_summary=summary,
        professional_experience=experience_block,
        skills=skills,
        education=education,
        other=other,
        experience_bullets_per_role=bullets_per_role,
    )
    missing_requirements = [
        str(item.get("requirement"))
        for item in requirement_evidence_map
        if item.get("status") in {"missing", "unknown", "contradicted"} and item.get("requirement")
    ][:12]
    if sample_mode:
        missing_requirements = []
    audit_report = {
        "sample_mode": sample_mode,
        "prompt_version": PROMPT_VERSION,
        "model_metadata": {
            "writer_model": os.getenv("OPENAI_MODEL_WRITE", os.getenv("OPENAI_MODEL", "chat-latest")),
            "used_llm": used_llm,
        },
        "pipeline": [
            "extract_resume_facts",
            "analyze_job_description",
            "create_evidence_map",
            "generate_clarifying_questions",
            "rank_existing_bullets",
            "rewrite_selected_bullets",
            "ats_optimize_supported_terms",
            "validate_claims",
            "score_match",
        ],
        "candidate_knowledge_base": candidate_knowledge_base,
        "job_analysis": job_analysis,
        "evidence_map": requirement_evidence_map,
        "eligibility": eligibility,
        "bullet_audit": bullet_audit,
        "skill_audit": skill_audit,
        "validation": validation,
        "scoring": {**match_scores, "missing_requirements": missing_requirements},
    }

    tips = [
        f"Fresh PDF and Word files built with your smart CV template: {template_label} ({template_key}).",
        "Contact, summary, skills, experience, and education were mapped to the correct template sections.",
        f"Detected {len(roles)} work roles; display is newest first, while bullet depth is assigned from career start to latest role using JD relevance ({' → '.join(str(n) for n in bullets_per_role[:6])}{'…' if len(bullets_per_role) > 6 else ''}).",
    ]
    if used_rendercv:
        tips.append("RenderCV generated the PDF from structured YAML using one of its built-in themes.")
    elif rendercv_error:
        tips.append(f"RenderCV export failed ({rendercv_error}); used the existing smart PDF renderer instead.")
    if not requested_template_key:
        tips.append(
            f"No CV template selected — used a random RenderCV theme: {template_label}."
        )
    elif used_rendercv and not requested_template_key.startswith("rendercv-"):
        tips.append(
            f"Your saved legacy smart template was ignored for this export — used RenderCV theme: {template_label}."
        )
    if used_llm:
        tips.append("AI rewrote summary, skills, and accomplishment bullets for the target job.")
    else:
        tips.append("Set OPENAI_API_KEY for AI-generated bullets and summary.")
    if gap_report:
        tips.append(
            f"Evidence guardrails found {len(gap_report)} unsupported JD requirement(s); those claims were kept out of the resume."
        )

    return TailorResponse(
        tailored_resume=plain,
        tailored_contact=contact_block,
        tailored_summary=summary,
        tailored_experience=experience_block,
        tailored_skills=skills,
        tailored_education=education,
        tailored_other=other,
        docx_base64=base64.b64encode(docx_bytes).decode("ascii"),
        download_filename=docx_name,
        pdf_base64=base64.b64encode(pdf_bytes).decode("ascii"),
        pdf_download_filename=pdf_name,
        keywords_highlighted=[],
        experience_keywords_highlighted=[],
        skills_keywords_highlighted=[],
        ats_tips=tips,
        used_llm=used_llm,
        openai_configured=openai_configured,
        llm_error=llm_error,
        enable_bold_applied=False,
        export_mode="fresh_pdf",
        template_key=template_key,
        template_label=template_label,
        match_scores=numeric_match_scores,
        gap_report=gap_report,
        clarifying_questions=clarifying_questions,
        integration_report=integration_report,
        audit_report=audit_report,
    )
