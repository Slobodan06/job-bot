import asyncio
import base64
import json
import os
import re
from collections import Counter
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.schemas import TailorResponse
from app.services.docx_convert import convert_docx_bytes_to_pdf, pdf_download_filename
from app.services.docx_resume import (
    apply_tailored_sections_to_docx,
    output_docx_filename,
    parse_resume_from_docx,
)
from app.services.pdf_resume import (
    build_experience_role_titles_from_target,
    merge_experience_headers_with_bullets,
    merge_profile_links_into_contact,
    merge_skills_preserving_labels,
    sanitize_target_job_role,
    split_experience_line_blocks,
)
from app.services.sectionize import ParsedResume

_BULLET_CHARS = r"\-•*–—\u2022\u25cf\u25cb\u25aa\u25e6\u00b7\u2219"
_BULLET_LINE_RE = re.compile(rf"^[{_BULLET_CHARS}]\s+")
_YEARS_OF_EXPERIENCE_RE = re.compile(
    r"\b(\d+\+\s*(?:years?|yrs?)(?:\s+of\s+(?:professional\s+)?experience)?|"
    r"\d+\s+years?(?:\s+of\s+(?:professional\s+)?experience)?)\b",
    re.I,
)
_METRIC_SNIPPET_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|percent|x\b|X\b|k\+|K\+|m\+|M\+)|"
    r"(?:reduced|increased|improved|cut|decreased|accelerated|grew|lowered|boosted|saved|"
    r"delivered|processed|scaled)[^.!?\n]{0,70}\d+",
    re.I,
)

def _tailor_max_tokens() -> int:
    raw = os.getenv("OPENAI_TAILOR_MAX_TOKENS", "16384").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 8192
    return max(2048, min(n, 32000))


def _tailor_temperature() -> float:
    raw = os.getenv("OPENAI_TAILOR_TEMPERATURE", "0.62").strip()
    try:
        t = float(raw)
    except ValueError:
        t = 0.62
    return max(0.0, min(t, 1.5))


STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "as", "by",
    "with", "from", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "shall",
    "can", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
    "what", "which", "who", "whom", "whose", "where", "when", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "just", "also", "into", "through",
    "during", "before", "after", "above", "below", "between", "under", "again", "further",
    "then", "once", "here", "there", "any", "if", "about", "our", "your", "their", "my",
    "me", "us", "them", "his", "her", "its", "myself", "yourself", "himself", "herself",
    "itself", "ourselves", "themselves", "within", "across", "including", "etc", "eg",
    "e.g", "i.e", "years", "year", "experience", "work", "team", "role", "job", "position",
    "company", "opportunity", "looking", "seeking", "candidate", "responsibilities",
    "requirements", "skills", "ability", "able", "strong", "excellent", "good", "great",
    "build", "building", "using", "use", "used", "including", "based", "related",
}


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^\w\s+#./-]", " ", text, flags=re.UNICODE)
    return [w for w in text.split() if len(w) > 2]


def extract_keywords(job_description: str, top_k: int = 28) -> list[str]:
    tokens = _tokenize(job_description)
    scored: Counter[str] = Counter()
    for raw in tokens:
        w = raw.strip(".-/")
        if not w or w in STOPWORDS:
            continue
        if w.isdigit():
            continue
        scored[w] += 2 if any(c.isdigit() for c in raw) else 1
    phrases = re.findall(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b",
        job_description,
    )
    for p in phrases:
        key = p.strip().lower()
        if len(key) < 4:
            continue
        parts = key.split()
        if all(len(x) > 2 for x in parts):
            scored[key] += 3
    out: list[str] = []
    seen: set[str] = set()
    for term, _ in scored.most_common(top_k * 2):
        if term in seen:
            continue
        seen.add(term)
        out.append(term)
        if len(out) >= top_k:
            break
    return out


@dataclass
class TailoredSections:
    contact: str
    professional_summary: str
    professional_experience: str
    skills: str
    education: str
    other: str
    experience_role_titles: str = ""


def _source_section_stats(parsed: ParsedResume) -> dict[str, int | list[int]]:
    exp = (parsed.professional_experience or "").strip()
    skills = (parsed.skills or "").strip()
    bullets = len(re.findall(rf"^[{_BULLET_CHARS}]\s", exp, re.M))
    roles = len(re.findall(r"\n\s*\n", exp)) + (1 if exp else 0)
    skill_lines = len([line for line in skills.splitlines() if line.strip()])
    per_role = _experience_bullets_per_role(exp)
    return {
        "experience_chars": len(exp),
        "experience_bullets": bullets,
        "experience_roles_est": roles,
        "experience_bullets_per_role": per_role,
        "skills_chars": len(skills),
        "skills_lines": skill_lines,
    }


def _experience_bullets_per_role(experience: str) -> list[int]:
    blocks = split_experience_line_blocks(experience or "")
    if not blocks:
        return []
    return [
        sum(1 for line in block if _BULLET_LINE_RE.match(line.strip()))
        for block in blocks
    ]


def _partition_flat_bullets(bullets: list[str], counts: list[int]) -> list[list[str]]:
    if not counts:
        return [bullets] if bullets else []
    out: list[list[str]] = []
    pos = 0
    for count in counts:
        chunk = bullets[pos : pos + count] if count > 0 else []
        out.append(chunk)
        pos += max(count, 0)
    if pos < len(bullets) and out:
        for i, bullet in enumerate(bullets[pos:]):
            out[i % len(out)].append(bullet)
    return out


def _tailored_bullets_per_role(tailored_experience: str, role_counts: list[int]) -> list[int]:
    bullets = [
        line.strip()
        for line in (tailored_experience or "").splitlines()
        if line.strip() and _BULLET_LINE_RE.match(line.strip())
    ]
    return [len(part) for part in _partition_flat_bullets(bullets, role_counts)]


def extract_years_of_experience(*texts: str) -> str | None:
    """Find a years-of-experience phrase from profile, summary, or contact."""
    for text in texts:
        if not text:
            continue
        match = _YEARS_OF_EXPERIENCE_RE.search(text)
        if match:
            return match.group(1).strip()
    return None


def extract_source_metrics(*texts: str, limit: int = 12) -> list[str]:
    """Collect quantified results from the source resume to reuse in tailored bullets."""
    seen: set[str] = set()
    metrics: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in _METRIC_SNIPPET_RE.finditer(text):
            snippet = re.sub(r"\s+", " ", match.group(0)).strip(" ,;.")
            key = snippet.lower()
            if len(snippet) < 4 or key in seen:
                continue
            seen.add(key)
            metrics.append(snippet)
            if len(metrics) >= limit:
                return metrics
    return metrics


def ensure_years_in_summary(summary: str, source_summary: str, contact: str = "") -> str:
    """Keep the profile's years-of-experience phrase in the tailored summary."""
    summary = (summary or "").strip()
    if not summary:
        return summary
    years = extract_years_of_experience(source_summary, contact)
    if not years:
        return summary
    if extract_years_of_experience(summary):
        return summary
    years_phrase = years if re.search(r"experience|exp", years, re.I) else f"{years} of experience"
    parts = re.split(r"(?<=[.!?])\s+", summary, maxsplit=1)
    first = parts[0].rstrip(".")
    rest = parts[1].strip() if len(parts) > 1 else ""
    if re.search(r"\b(with|bringing)\b", first, re.I):
        first = f"{first}, {years_phrase}"
    else:
        first = f"{first} with {years_phrase}"
    return f"{first}. {rest}".strip() if rest else f"{first}."


def _tailor_volume_ok(parsed: ParsedResume, tailored: TailoredSections) -> bool:
    stats = _source_section_stats(parsed)
    out_exp = len(tailored.professional_experience.strip())
    out_sk = len(tailored.skills.strip())
    out_sum = len(tailored.professional_summary.strip())
    if stats["experience_chars"] > 600 and out_exp < stats["experience_chars"] * 0.35:
        return False
    if stats["experience_bullets"] >= 4:
        out_bullets = len(re.findall(rf"^[{_BULLET_CHARS}]\s", tailored.professional_experience, re.M))
        if out_bullets < max(4, int(stats["experience_bullets"] * 0.65)):
            return False
    if stats["skills_chars"] > 80 and out_sk < stats["skills_chars"] * 0.55:
        return False
    if (parsed.professional_summary or "").strip() and out_sum < max(200, len(parsed.professional_summary.strip()) * 0.55):
        return False
    return True


def _meaningful_lines(text: str, *, min_len: int = 24) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        if len(stripped) >= min_len:
            lines.append(stripped)
    if lines:
        return lines
    for sentence in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        s = sentence.strip()
        if len(s) >= min_len:
            lines.append(s)
    return lines


def _verbatim_line_overlap(source: str, tailored: str) -> float:
    src_lines = [line.lower() for line in _meaningful_lines(source)]
    if not src_lines:
        return 0.0
    tailored_lower = (tailored or "").lower()
    hits = sum(1 for line in src_lines if line in tailored_lower)
    return hits / len(src_lines)


def _bullet_bodies(text: str) -> list[str]:
    bodies: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        if not stripped:
            continue
        if re.match(rf"^[{_BULLET_CHARS}]\s+", stripped):
            body = re.sub(rf"^[{_BULLET_CHARS}]\s+", "", stripped).strip().lower()
            if len(body) >= 20:
                bodies.append(body)
    return bodies


def _bullet_verbatim_overlap(source: str, tailored: str) -> float:
    src = _bullet_bodies(source)
    if not src:
        return 0.0
    tail = set(_bullet_bodies(tailored))
    if not tail:
        return 1.0
    hits = sum(1 for body in src if body in tail)
    return hits / len(src)


def _bullets_with_metrics(text: str) -> int:
    count = 0
    for body in _bullet_bodies(text):
        if _METRIC_SNIPPET_RE.search(body):
            count += 1
    return count


def _tailor_metrics_ok(parsed: ParsedResume, tailored: TailoredSections) -> bool:
    src_metrics = len(extract_source_metrics(parsed.professional_experience, parsed.professional_summary))
    if src_metrics == 0:
        return _bullets_with_metrics(tailored.professional_experience) >= 2
    src_bullets = max(1, len(_bullet_bodies(parsed.professional_experience)))
    out_metrics = _bullets_with_metrics(tailored.professional_experience)
    min_required = max(2, min(src_metrics, int(src_bullets * 0.35)))
    return out_metrics >= min_required


def _tailor_rewrite_aggressive_enough(parsed: ParsedResume, tailored: TailoredSections) -> bool:
    """Reject light edits — editable sections must be substantially rewritten for the JD."""
    if _verbatim_line_overlap(parsed.professional_summary, tailored.professional_summary) > 0.15:
        return False
    if _bullet_verbatim_overlap(parsed.professional_experience, tailored.professional_experience) > 0.12:
        return False
    if _verbatim_line_overlap(parsed.skills, tailored.skills) > 0.25:
        return False
    return True


def _tailor_quality_ok(parsed: ParsedResume, tailored: TailoredSections) -> bool:
    return (
        _tailor_volume_ok(parsed, tailored)
        and _tailor_rewrite_aggressive_enough(parsed, tailored)
        and _tailor_metrics_ok(parsed, tailored)
    )


def build_docx_highlight_keywords(
    job_description: str,
    parsed: ParsedResume,
    tailored: TailoredSections,
) -> list[str]:
    """Terms to bold in profile and experience only: JD keywords, tech, and source metrics."""
    terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        cleaned = re.sub(r"\s+", " ", (term or "").strip(" ,;."))
        if len(cleaned) < 3:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        terms.append(cleaned)

    for kw in extract_keywords(job_description, top_k=36):
        _add(kw)

    for metric in extract_source_metrics(parsed.professional_experience, parsed.professional_summary, limit=16):
        _add(metric)

    for body in _bullet_bodies(tailored.professional_experience or parsed.professional_experience):
        for match in re.finditer(
            r"\b(?:React(?:\.js)?|Angular|Vue(?:\.js)?|Node(?:\.js)?|TypeScript|JavaScript|Python|"
            r"Java|AWS|Azure|GCP|Docker|Kubernetes|Terraform|CI/CD|PostgreSQL|MongoDB|Redis|"
            r"GraphQL|REST(?:ful)?|FastAPI|Django|Flask|\.NET|Next(?:\.js)?|OpenAI)\b",
            body,
            re.I,
        ):
            _add(match.group(0))

    summary_text = tailored.professional_summary or parsed.professional_summary or ""
    for match in re.finditer(
        r"\b(?:React(?:\.js)?|Angular|Vue(?:\.js)?|Node(?:\.js)?|TypeScript|JavaScript|Python|"
        r"Java|AWS|Azure|GCP|Docker|Kubernetes|Terraform|CI/CD|PostgreSQL|MongoDB|Redis|"
        r"GraphQL|REST(?:ful)?|FastAPI|Django|Flask|\.NET|Next(?:\.js)?|OpenAI|Shopify)\b",
        summary_text,
        re.I,
    ):
        _add(match.group(0))

    return sorted(terms, key=len, reverse=True)


def _skills_highlight_max() -> int:
    raw = os.getenv("OPENAI_SKILLS_HIGHLIGHT_MAX", "10").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 10
    return max(3, min(n, 16))


def _extract_jd_priority_text(job_description: str) -> str:
    """Requirements / qualifications / responsibilities — weighted higher for skill highlights."""
    jd = (job_description or "").strip()
    if not jd:
        return ""
    chunks: list[str] = []
    section_starts = re.compile(
        r"(?:^|\n)\s*(?:requirements|qualifications|what you(?:'ll| will) do|"
        r"core focus|must have|required skills|key skills|you have|who you are)\b",
        re.I | re.M,
    )
    matches = list(section_starts.finditer(jd))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(jd)
        chunk = jd[start:end].strip()
        if len(chunk) > 40:
            chunks.append(chunk[:3000])
    return "\n\n".join(chunks)


def _parse_skill_tokens(skills_text: str) -> list[str]:
    tokens: list[str] = []
    for raw_line in (skills_text or "").replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" in line[:60]:
            line = line.split(":", 1)[1]
        for part in re.split(r"[,;|/•·]", line):
            token = part.strip()
            if token and len(token) >= 2 and token.lower() not in STOPWORDS:
                tokens.append(token)
    return tokens


def _term_appears_in_skills(term: str, skills_text: str) -> bool:
    term = (term or "").strip()
    if len(term) < 2 or not skills_text:
        return False
    if re.match(r"^[\w\-./+#]+$", term):
        return bool(
            re.search(
                r"(?<![\w\-./+#])" + re.escape(term) + r"(?![\w\-./+#])",
                skills_text,
                re.I,
            )
        )
    return term.lower() in skills_text.lower()


_SKILL_HIGHLIGHT_STOPWORDS = frozenset(
    {
        "management", "customer", "order", "flow", "operations", "experience",
        "relationship", "tools", "frontend", "backend", "database", "practices",
        "communication", "leadership", "development", "platform", "integration",
        "process", "performance", "reporting", "compliance", "automation",
        "technical", "professional", "excellent", "strong", "skills",
    }
)


def _score_skill_token_against_jd(token: str, priority_text: str, full_jd: str) -> int:
    token_lower = token.lower()
    score = 0
    for kw in extract_keywords(priority_text, top_k=40):
        kw_lower = kw.lower()
        if kw_lower == token_lower:
            score += 6
        elif len(kw_lower) >= 4 and (kw_lower in token_lower or token_lower in kw_lower):
            score += 4
    for kw in extract_keywords(full_jd, top_k=24):
        kw_lower = kw.lower()
        if kw_lower == token_lower:
            score += 2
        elif len(kw_lower) >= 5 and kw_lower in token_lower:
            score += 1
    if _term_appears_in_skills(token, priority_text):
        score += 3
    return score


def _prune_substring_highlights(terms: list[str]) -> list[str]:
    kept: list[str] = []
    for term in terms:
        lower = term.lower()
        if any(lower != other.lower() and lower in other.lower() for other in terms):
            continue
        kept.append(term)
    return kept


def build_skills_highlight_keywords(job_description: str, skills_text: str) -> list[str]:
    """
    Return only the most job-critical skills to bold in the Skills section (not every keyword).
    Terms must be actual skill entries from the resume and score high against JD requirements.
    """
    skills = (skills_text or "").strip()
    if not skills:
        return []

    max_highlights = _skills_highlight_max()
    priority_text = _extract_jd_priority_text(job_description) or job_description
    tokens = _parse_skill_tokens(skills)

    scored: list[tuple[int, int, str]] = []
    for token in tokens:
        if len(token) < 2:
            continue
        token_lower = token.lower()
        if token_lower in STOPWORDS or token_lower in _SKILL_HIGHLIGHT_STOPWORDS:
            continue
        score = _score_skill_token_against_jd(token, priority_text, job_description)
        if score < 4:
            continue
        scored.append((score, len(token), token))

    scored.sort(key=lambda item: (-item[0], -item[1]))
    out: list[str] = []
    seen: set[str] = set()
    for _score, _length, token in scored:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= max_highlights:
            break
    return _prune_substring_highlights(out)


def _skills_as_categorized_lines(text: str) -> str:
    """Normalize skills to one category per line: Frontend: a, b, c — keeps newlines."""
    raw = (text or "").strip()
    if not raw:
        return ""
    out: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        s = re.sub(r"^[•\-\*\u2022]+\s*", "", s)
        s = re.sub(r"\s+", " ", s)
        out.append(s)
    return "\n".join(out)


def _offline_tailor_structured(parsed: ParsedResume, jd: str) -> TailoredSections:
    keywords = extract_keywords(jd, top_k=26)
    kline = ", ".join(keywords[:20])

    summ = (parsed.professional_summary or "").strip()
    if summ:
        professional_summary = (
            summ + "\n\n[Role alignment — weave these keywords where truthful: " + kline + "]"
        )
    else:
        professional_summary = (
            "Professional summary oriented to role themes: "
            + kline
            + ". Lead with outcomes and tools already evidenced in your experience."
        )

    exp = (parsed.professional_experience or "").strip()
    if not exp:
        exp = "[Paste your roles and bullets under Professional Experience in the source resume.]"

    sk = (parsed.skills or "").strip()
    if sk:
        skills_raw = (
            sk
            + "\n\nPosting-aligned terms to weave in when accurate: "
            + kline
            + "."
        )
    else:
        skills_raw = (
            "Frontend: add comma-separated UI frameworks and libraries from your experience.\n"
            "Backend: add languages, runtimes, and API styles you have used.\n"
            "Database: add databases and data tools you have used.\n"
            "DevOps & cloud: add CI/CD, containers, and hosting where applicable.\n"
            "Other: "
            + kline
        )

    return TailoredSections(
        contact=(parsed.contact or "").strip(),
        professional_summary=professional_summary.strip(),
        professional_experience=exp,
        skills=_skills_as_categorized_lines(skills_raw),
        education=(parsed.education or "").strip(),
        other=(parsed.other or "").strip(),
    )


STRUCTURED_SYSTEM = """You are an expert ATS resume strategist. Maximize this candidate's score for the job posting.
The candidate uploaded a Word resume; you receive source sections as JSON. Facts must stay truthful; wording must be NEW.

Return ONLY a JSON object with exactly these keys (all strings, use \\n for line breaks inside values):
"contact", "professional_summary", "professional_experience", "skills", "education", "other"

Editable sections — FULL REWRITE for this job (not light edits):
- professional_summary (profile)
- professional_experience (bullet lines only)
- skills (skill lists only; keep category labels)

Frozen sections — copy verbatim from SOURCE_SECTIONS_JSON:
- contact, education, other

Note: Job titles in work experience are set from TARGET_JOB_ROLE (user input) — do not invent role headers.

ATS optimization (primary goal):
- Write completely fresh summary sentences and bullets optimized for THIS job description.
- FORBIDDEN: tweaking a few words, synonym swaps, or keeping source phrasing/sentence structure.
- REQUIRED: mirror the job description's role title, responsibilities, qualifications, tools, and domain language.
- Front-load keywords recruiters and ATS systems scan for; use exact JD phrases when the candidate's background supports them.
- Every bullet: strong action verb + scope + methods/stack + measurable outcome (%, time saved, volume, scale, speed).
- Reuse quantified results from the source resume when rewriting bullets; do not drop real numbers/percentages.
- Reorder skills within each category so JD-matched tools appear first; add truthful JD-aligned terms from the candidate's experience.

Experience volume (ATS):
- Use BULLETS_PER_ROLE in the user message as a baseline per job, not a maximum.
- Add 2–4 extra "- " bullets per role when the job description supports truthful, metric-rich achievements.
- Prefer more JD-aligned bullets over keeping the original count; never pad with generic filler.

Truth boundaries:
- NEVER invent employers, schools, degrees, dates, certifications, or tools not evidenced in the source.
- You MAY fully rewrite sentences, merge/split bullets, reframe achievements, and emphasize JD-relevant work.

contact:
- Return source contact EXACTLY unchanged.

professional_summary:
- Write 5–8 NEW sentences from scratch for this posting (not a edit of the source summary).
- Open with fit for THIS role: target title phrasing from the JD, seniority, core stack, domain, and outcomes.
- If the source profile states years of experience (e.g. "10+ years"), keep that exact figure in the summary opening.

professional_experience:
- Output ONLY accomplishment bullets starting with "- " (one bullet per line).
- Do NOT include company names, titles, locations, or dates — those stay in the Word file.
- Cover EVERY role from the source in order; blank line between roles is optional.
- Rewrite EVERY bullet from scratch for the JD; include metrics (%, counts, latency, throughput) in most bullets.
- Reuse source metrics when present; only use numbers evidenced in the source — never invent statistics.

skills:
- Same number of lines and SAME category labels as source (e.g. "Frontend:", "DevOps & Cloud:").
- Fully rewrite the comma-separated lists after each label for the JD; reorder to prioritize posting keywords.

education / other:
- Return source text EXACTLY unchanged.

No markdown fences, no commentary outside JSON."""


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


async def _llm_tailor_structured(
    parsed: ParsedResume,
    jd: str,
    api_key: str,
    *,
    target_job_role: str = "",
) -> TailoredSections:
    client = AsyncOpenAI(api_key=api_key)
    stats = _source_section_stats(parsed)
    keywords = extract_keywords(jd, top_k=32)
    keyword_line = ", ".join(keywords[:24])
    years = extract_years_of_experience(parsed.professional_summary, parsed.contact)
    source_metrics = extract_source_metrics(
        parsed.professional_experience,
        parsed.professional_summary,
    )
    per_role = stats.get("experience_bullets_per_role") or []
    per_role_text = ", ".join(str(n) for n in per_role) if per_role else str(stats["experience_bullets"])
    target_role = sanitize_target_job_role(target_job_role)
    preserve_lines: list[str] = []
    if years:
        preserve_lines.append(f'- Years of experience (keep in summary): "{years}"')
    if source_metrics:
        preserve_lines.append(
            "- Source metrics to reuse in rewritten bullets when relevant:\n  "
            + "\n  ".join(f"• {m}" for m in source_metrics[:10])
        )
    preserve_block = "\n".join(preserve_lines) + "\n\n" if preserve_lines else ""
    payload = {
        "contact": parsed.contact,
        "professional_summary": parsed.professional_summary,
        "professional_experience": parsed.professional_experience,
        "skills": parsed.skills,
        "education": parsed.education,
        "other": parsed.other,
    }
    user_intro = (
        "TARGET JOB — fully rewrite profile/summary, every experience bullet, and all skill lists for ATS match.\n"
        "- Do NOT lightly edit source sentences. Write new content aligned to the job description.\n"
        "- Do NOT change contact, education, or other — return those verbatim from source.\n"
        "- Experience: output ONLY \"- \" bullet lines (no company/title/location/date headers).\n"
        "- Include measurable results in most bullets (%, speed, scale, cost, time saved) using SOURCE metrics when available.\n"
        "- Skills: same line count and category labels as source; fully rewrite list text for the JD.\n"
        f"- BULLETS_PER_ROLE (baseline per job, in order — add more when the JD supports it): {per_role_text}\n"
        f"- TARGET_JOB_ROLE (use this exact phrasing in summary/skills; experience headers are set separately): {target_role}\n"
        f"- Add extra JD-focused bullets with metrics; exceeding the baseline improves ATS match.\n"
        f"- Source stats: ~{stats['experience_roles_est']} roles, ~{stats['experience_bullets']} bullets, "
        f"{stats['skills_lines']} skills lines.\n"
        f"- ATS keywords to weave naturally (when truthful): {keyword_line}\n\n"
        + preserve_block
        + "JOB DESCRIPTION:\n"
        + jd.strip()
        + "\n\nSOURCE_SECTIONS_JSON:\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    async def _call(user_content: str, temp_boost: float = 0.0) -> TailoredSections:
        completion = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=min(_tailor_temperature() + temp_boost, 0.72),
            max_tokens=_tailor_max_tokens(),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": STRUCTURED_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        )
        raw = completion.choices[0].message.content or "{}"
        data = _parse_json_object(raw)
        return TailoredSections(
            contact=str(data.get("contact", "")).strip(),
            professional_summary=str(data.get("professional_summary", "")).strip(),
            professional_experience=str(data.get("professional_experience", "")).strip(),
            skills=_skills_as_categorized_lines(str(data.get("skills", ""))),
            education=str(data.get("education", "")).strip(),
            other=str(data.get("other", "")).strip(),
            experience_role_titles="",
        )

    tailored = await _call(user_intro)
    if _tailor_quality_ok(parsed, tailored):
        return _ensure_source_sections(parsed, tailored)

    retry_msg = (
        user_intro
        + "\n\nYour previous JSON was too short, too similar to source, lacked metrics, or changed frozen sections. "
        "FULLY REWRITE summary, skills, and experience bullets in new sentences for this job — "
        "do not reuse source phrasing. Return contact, education, and other verbatim. "
        f"Include at least {max(4, stats['experience_bullets'])} total \"- \" bullets; "
        f"exceed baseline BULLETS_PER_ROLE ({per_role_text}) where the JD supports extra achievements; "
        f"most bullets need % or numeric results. JD keywords: {keyword_line}."
    )
    tailored = await _call(retry_msg, temp_boost=0.08)
    if _tailor_quality_ok(parsed, tailored):
        return _ensure_source_sections(parsed, tailored)

    retry_msg2 = (
        retry_msg
        + "\n\nStill too close to the source resume. Replace every summary sentence and every bullet with "
        "completely different wording while keeping the same facts, employers, and tools."
    )
    tailored = await _call(retry_msg2, temp_boost=0.12)
    return _ensure_source_sections(parsed, tailored)


def _ensure_source_sections(parsed: ParsedResume, tailored: TailoredSections) -> TailoredSections:
    """Never drop editable sections the model omitted; keep frozen sections from source."""
    return TailoredSections(
        contact=(parsed.contact or "").strip(),
        professional_summary=tailored.professional_summary.strip() or parsed.professional_summary.strip(),
        professional_experience=tailored.professional_experience.strip() or parsed.professional_experience.strip(),
        skills=_skills_as_categorized_lines(tailored.skills or parsed.skills),
        education=(parsed.education or "").strip(),
        other=(parsed.other or "").strip(),
    )


def _assemble_plain(t: TailoredSections) -> str:
    parts: list[str] = []
    if t.contact.strip():
        parts.append(t.contact.strip())
    if t.professional_summary.strip():
        parts.append("PROFESSIONAL SUMMARY\n" + t.professional_summary.strip())
    if t.professional_experience.strip():
        parts.append("PROFESSIONAL EXPERIENCE\n" + t.professional_experience.strip())
    if t.skills.strip():
        parts.append("SKILLS\n" + t.skills.strip())
    if t.education.strip():
        parts.append("EDUCATION\n" + t.education.strip())
    if t.other.strip():
        parts.append("ADDITIONAL\n" + t.other.strip())
    return "\n\n".join(parts)


def _parse_role_titles_list(text: str) -> list[str]:
    return [line.strip() for line in (text or "").replace("\r\n", "\n").splitlines() if line.strip()]


def _finalize_tailored(
    parsed: ParsedResume,
    tailored: TailoredSections,
    job_description: str = "",
    *,
    target_job_role: str,
    role_count: int | None = None,
) -> TailoredSections:
    """Merge AI rewrites into experience/skills layout; freeze contact, education, other."""
    role_titles = build_experience_role_titles_from_target(
        target_job_role,
        parsed.professional_experience,
        expected_count=role_count,
    )
    exp_merged = merge_experience_headers_with_bullets(
        parsed.professional_experience,
        tailored.professional_experience,
        tailored_role_titles=role_titles or None,
    )
    skills_merged = merge_skills_preserving_labels(parsed.skills, tailored.skills)
    summary = ensure_years_in_summary(
        tailored.professional_summary.strip() or parsed.professional_summary.strip(),
        parsed.professional_summary,
        parsed.contact,
    )
    return TailoredSections(
        contact=(parsed.contact or "").strip(),
        professional_summary=summary,
        professional_experience=exp_merged.strip() or parsed.professional_experience.strip(),
        skills=_skills_as_categorized_lines(skills_merged or tailored.skills or parsed.skills),
        education=(parsed.education or "").strip(),
        other=(parsed.other or "").strip(),
        experience_role_titles="\n".join(role_titles),
    )


def _default_tips_llm() -> list[str]:
    return [
        "Summary and experience bold JD keywords and metrics; Skills bold only the top job-critical tools (not every skill).",
        "Verify employers, schools, dates, and contact details before submitting; AI must not invent credentials.",
        "If wording still feels too close to your original, retry or raise OPENAI_TAILOR_MAX_TOKENS.",
    ]


def _default_tips_offline() -> list[str]:
    return [
        "Set OPENAI_API_KEY for full AI resume rewrites; offline mode adds keyword alignment notes only.",
        "Use clear section headers in your .docx (Summary, Experience, Skills, Education) for best results.",
        "Review headline, education, and contact lines before sending applications.",
    ]


def _build_docx_sync(
    *,
    source_docx_bytes: bytes,
    section_header_indices: dict[str, int],
    section_body_indices: dict[str, list[int]],
    contact_paragraph_indices: list[int],
    experience_table_rows: list,
    source_sections: ParsedResume,
    original_filename: str,
    tailored: TailoredSections,
    highlight_keywords: list[str] | None = None,
    skills_highlight_keywords: list[str] | None = None,
    enable_bold: bool = True,
) -> tuple[str, str, bool]:
    """Returns (base64_docx, download_filename, used_inplace_on_upload)."""
    download_name = output_docx_filename(original_filename)
    inplace = apply_tailored_sections_to_docx(
        source_docx_bytes,
        contact=tailored.contact,
        professional_summary=tailored.professional_summary,
        professional_experience=tailored.professional_experience,
        skills=tailored.skills,
        education=tailored.education,
        other=tailored.other,
        section_header_indices=section_header_indices,
        section_body_indices=section_body_indices,
        contact_paragraph_indices=contact_paragraph_indices,
        experience_table_rows=experience_table_rows,
        highlight_keywords=highlight_keywords,
        skills_highlight_keywords=skills_highlight_keywords,
        experience_role_titles=_parse_role_titles_list(tailored.experience_role_titles),
        enable_bold=enable_bold,
        source_sections=source_sections,
        original_filename=original_filename,
    )
    if inplace is not None:
        data, name = inplace
        return base64.b64encode(data).decode("ascii"), name, True
    return "", download_name, False


async def tailor_resume(
    resume_text: str,
    job_description: str,
    *,
    source_docx_bytes: bytes,
    original_filename: str = "resume.docx",
    target_job_role: str,
    enable_bold: bool = True,
) -> TailorResponse:
    docx_doc = parse_resume_from_docx(source_docx_bytes)
    parsed = docx_doc.parsed
    resume_text = docx_doc.plain_text
    docx_section_header_indices = docx_doc.section_header_indices
    docx_section_body_indices = docx_doc.section_body_indices
    contact_paragraph_indices = docx_doc.contact_paragraph_indices
    experience_table_rows = docx_doc.experience_table_rows
    role_count = len(experience_table_rows) if experience_table_rows else None

    enriched_contact = merge_profile_links_into_contact(
        parsed.contact,
        resume_text,
        docx_bytes=source_docx_bytes,
    )
    parsed = ParsedResume(
        contact=enriched_contact,
        professional_summary=parsed.professional_summary,
        professional_experience=parsed.professional_experience,
        skills=parsed.skills,
        education=parsed.education,
        other=parsed.other,
    )
    keywords = extract_keywords(job_description, top_k=22)
    key = os.getenv("OPENAI_API_KEY", "").strip()
    used_llm = False
    tailored: TailoredSections

    if key:
        try:
            tailored = await _llm_tailor_structured(
                parsed, job_description, key, target_job_role=target_job_role
            )
            if not (
                tailored.professional_summary.strip()
                or tailored.professional_experience.strip()
                or tailored.skills.strip()
                or tailored.contact.strip()
            ):
                raise ValueError("empty structured sections")
            used_llm = True
            tips = _default_tips_llm()
        except Exception:
            tailored = _offline_tailor_structured(parsed, job_description)
            used_llm = False
            tips = _default_tips_offline() + ["AI pass failed or returned invalid JSON; used offline section edits."]
    else:
        tailored = _offline_tailor_structured(parsed, job_description)
        tips = _default_tips_offline()

    tailored = _finalize_tailored(
        parsed,
        tailored,
        job_description,
        target_job_role=target_job_role,
        role_count=role_count,
    )
    highlight_keywords = build_docx_highlight_keywords(job_description, parsed, tailored) if enable_bold else []
    skills_highlight_keywords = (
        build_skills_highlight_keywords(job_description, tailored.skills) if enable_bold else []
    )
    full_text = _assemble_plain(tailored)

    docx_b64 = ""
    docx_download_name = output_docx_filename(original_filename)
    pdf_b64 = ""
    pdf_download_name = pdf_download_filename(docx_download_name)
    used_docx_inplace = False

    if docx_section_header_indices or contact_paragraph_indices or experience_table_rows:
        try:
            docx_b64, docx_download_name, used_docx_inplace = await asyncio.to_thread(
                _build_docx_sync,
                source_docx_bytes=source_docx_bytes,
                section_header_indices=docx_section_header_indices,
                section_body_indices=docx_section_body_indices,
                contact_paragraph_indices=contact_paragraph_indices,
                experience_table_rows=experience_table_rows,
                source_sections=parsed,
                original_filename=original_filename,
                tailored=tailored,
                highlight_keywords=highlight_keywords,
                skills_highlight_keywords=skills_highlight_keywords,
                enable_bold=enable_bold,
            )
            if used_docx_inplace and docx_b64:
                pdf_result = await asyncio.to_thread(
                    convert_docx_bytes_to_pdf,
                    base64.b64decode(docx_b64),
                    original_filename=docx_download_name,
                )
                if pdf_result is not None:
                    pdf_bytes, pdf_download_name = pdf_result
                    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
                    tips = [
                        *tips,
                        "A PDF version of your tailored resume is ready to download.",
                    ]
            if used_docx_inplace:
                tips = [
                    *tips,
                    "Your Word file keeps original formatting; Profile/Experience use broader keyword bolding; Skills bold only top JD-critical tools.",
                ]
            else:
                tips = [
                    *tips,
                    "Could not map every section in your .docx. Use clear headers (Summary, Experience, Skills, Education) or copy sections below.",
                ]
        except Exception:
            tips = [*tips, "Word export failed; tailored text sections are still available below."]
        if docx_b64 and not pdf_b64:
            tips = [
                *tips,
                "PDF export needs Microsoft Word (docx2pdf) or LibreOffice installed on the server.",
            ]

    return TailorResponse(
        tailored_resume=full_text,
        tailored_contact=tailored.contact,
        tailored_summary=tailored.professional_summary,
        tailored_experience=tailored.professional_experience,
        tailored_skills=tailored.skills,
        tailored_education=tailored.education,
        tailored_other=tailored.other,
        docx_base64=docx_b64,
        download_filename=docx_download_name,
        pdf_base64=pdf_b64,
        pdf_download_filename=pdf_download_name,
        keywords_highlighted=keywords,
        ats_tips=tips,
        used_llm=used_llm,
        enable_bold_applied=enable_bold,
    )
