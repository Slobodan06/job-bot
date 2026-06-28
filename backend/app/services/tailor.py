import asyncio
import base64
import json
import os
import re
from collections import Counter
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.schemas import TailorResponse
from app.services.pdf_inplace import apply_tailored_sections_to_pdf, output_pdf_filename
from app.services.template_catalog import build_template_pdf, get_template_meta
from app.services.pdf_text_util import sanitize_for_pdf
from app.services.sectionize import ParsedResume, parse_resume_sections

def _tailor_max_tokens() -> int:
    raw = os.getenv("OPENAI_TAILOR_MAX_TOKENS", "16384").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 8192
    return max(2048, min(n, 32000))


def _tailor_temperature() -> float:
    raw = os.getenv("OPENAI_TAILOR_TEMPERATURE", "0.52").strip()
    try:
        t = float(raw)
    except ValueError:
        t = 0.52
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
    professional_summary: str
    professional_experience: str
    skills: str


def _source_section_stats(parsed: ParsedResume) -> dict[str, int]:
    exp = (parsed.professional_experience or "").strip()
    skills = (parsed.skills or "").strip()
    bullets = len(re.findall(r"^[\-•*–—]\s", exp, re.M))
    roles = len(re.findall(r"\n\s*\n", exp)) + (1 if exp else 0)
    skill_lines = len([line for line in skills.splitlines() if line.strip()])
    return {
        "experience_chars": len(exp),
        "experience_bullets": bullets,
        "experience_roles_est": roles,
        "skills_chars": len(skills),
        "skills_lines": skill_lines,
    }


def _tailor_volume_ok(parsed: ParsedResume, tailored: TailoredSections) -> bool:
    stats = _source_section_stats(parsed)
    out_exp = len(tailored.professional_experience.strip())
    out_sk = len(tailored.skills.strip())
    if stats["experience_chars"] > 600 and out_exp < stats["experience_chars"] * 0.45:
        return False
    if stats["experience_bullets"] >= 6:
        out_bullets = len(re.findall(r"^[\-•*–—]\s", tailored.professional_experience, re.M))
        if out_bullets < max(4, int(stats["experience_bullets"] * 0.55)):
            return False
    if stats["skills_chars"] > 80 and out_sk < stats["skills_chars"] * 0.4:
        return False
    return True


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
    professional_experience = (
        exp
        + "\n\n[Expand each role with additional truthful bullets inferred only from lines above; "
        "mirror posting phrasing where it matches real work — "
        + kline
        + "]"
    )

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
        professional_summary=professional_summary.strip(),
        professional_experience=professional_experience.strip(),
        skills=_skills_as_categorized_lines(skills_raw),
    )


STRUCTURED_SYSTEM = """You are an ATS-aware resume editor optimizing for ONE target job posting.
You receive that job description and JSON with resume sections from the candidate's uploaded CV:
professional_summary, professional_experience, skills (rewrite these three), plus reference_education
and reference_other (context only — do not output separate keys for those).

Return ONLY a JSON object with exactly these keys (all strings, use \\n for line breaks inside values):
"professional_summary", "professional_experience", "skills"

Truth and ethics:
- Preserve factual truth from the candidate's source only: employers, tenure, titles, stacks they actually used. Do NOT invent employers, titles, dates, certifications, metrics, products, or tools never evidenced or strongly implied by the source.
- If a section is empty, infer concise content consistent with other sections (still no fabrication).

Coverage (critical — do not under-generate):
- **Include EVERY role** listed in source professional_experience. Never drop, merge away, or skip a position.
- For each role, preserve job title, employer, dates, and location lines from the source (you may rephrase titles slightly but not change facts).
- **Bullet volume**: when the source role has N bullets, output at least max(4, N) rewritten bullets for that role. When source experience is rich (many bullets), aim for 6–12 bullets per role.
- **Skills completeness**: every tool, language, framework, and platform explicitly named in source skills MUST appear somewhere in your rebuilt skills lines (reordered and grouped for the job). Add JD-aligned terms only when truthful. Do not shrink a rich skills section.

Job-first targeting (critical):
- Read the job description before writing. Prioritize vocabulary, domains, outcomes, scale, compliance, stack, user types, and success criteria that the posting emphasizes.
- **Do NOT copy source bullet wording.** Each "- " bullet must be **fresh sentences** optimized for THIS role while reflecting the same underlying responsibilities and tech.
- **Forbidden pattern**: reproducing ~70%+ of an original bullet with only a short suffix about the industry or employer. Rewrite the whole bullet so leadership, scope, and impact read differently while staying honest.
- Vary openings (verbs and structure) across bullets and across roles so positions do not read like copy-paste with employer names swapped.

professional_summary:
- 5–8 substantive sentences when the résumé is rich. Tie background explicitly to what the posting asks for (domain, seniority, stack, outcomes).

professional_experience:
- Use "- " bullets only (plain text).
- For EACH role from the source: job title line, employer line, then dates and location when present (separate lines), then bullets—preserve structure but **rewrite all bullet content for the job**.
- Each bullet should answer how that work maps to the posting's problems (platform, reliability, UX, APIs, commerce, data, collaboration as relevant)—using **new phrasing**, not appended clichés.

skills:
- **Fully rebuild for the target job** while retaining all verified tools from the source.
- MUST be categorized lines only (no bullets, no markdown). One category per line:
  Frontend: …
  Backend: …
  Database: …
  DevOps & cloud: … (when relevant)
  AI & data: … (when relevant)
  E-commerce / CMS: … (when relevant)
  Plus other categories as needed (Mobile, Security, Monitoring, Testing/QA).
- **Reorder categories** so the **most JD-relevant category appears first** (when sensible). Within each line, list **job-aligned tools and phrases first** when truthful, then other verified skills from the résumé.
- Aim for **6–14 distinct items per line** where supported; weave JD terminology where accurate.

No markdown fences, no commentary outside JSON."""


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


async def _llm_tailor_structured(parsed: ParsedResume, jd: str, api_key: str) -> TailoredSections:
    client = AsyncOpenAI(api_key=api_key)
    stats = _source_section_stats(parsed)
    payload = {
        "professional_summary": parsed.professional_summary,
        "professional_experience": parsed.professional_experience,
        "skills": parsed.skills,
        "reference_education": parsed.education,
        "reference_other": parsed.other,
    }
    user_intro = (
        "TARGET JOB — rewrite aggressively for THIS posting only.\n"
        "- Experience: include EVERY role from source; rewrite every bullet in new words (same facts/tech).\n"
        "- Skills: keep ALL source tools/skills, reordered for this JD; add JD terms only when truthful.\n"
        f"- Source stats: ~{stats['experience_roles_est']} roles, ~{stats['experience_bullets']} bullets, "
        f"{stats['skills_lines']} skills lines — output must not be shorter than a thorough rewrite of that material.\n\n"
        "JOB DESCRIPTION:\n"
        + jd.strip()
        + "\n\nSOURCE_SECTIONS_JSON:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    completion = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=_tailor_temperature(),
        max_tokens=_tailor_max_tokens(),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": STRUCTURED_SYSTEM},
            {"role": "user", "content": user_intro},
        ],
    )
    raw = completion.choices[0].message.content or "{}"
    data = _parse_json_object(raw)
    tailored = TailoredSections(
        professional_summary=str(data.get("professional_summary", "")).strip(),
        professional_experience=str(data.get("professional_experience", "")).strip(),
        skills=_skills_as_categorized_lines(str(data.get("skills", ""))),
    )
    if _tailor_volume_ok(parsed, tailored):
        return tailored

    retry_msg = (
        user_intro
        + "\n\nYour previous JSON was too short or omitted source material. "
        "Return a FULL rewrite: every employer/role from professional_experience, "
        f"at least {max(4, stats['experience_bullets'])} total bullets when the source supports it, "
        "and every skill/tool from source skills reorganized for the job."
    )
    completion = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=min(_tailor_temperature() + 0.05, 0.65),
        max_tokens=_tailor_max_tokens(),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": STRUCTURED_SYSTEM},
            {"role": "user", "content": retry_msg},
        ],
    )
    raw = completion.choices[0].message.content or "{}"
    data = _parse_json_object(raw)
    return TailoredSections(
        professional_summary=str(data.get("professional_summary", "")).strip(),
        professional_experience=str(data.get("professional_experience", "")).strip(),
        skills=_skills_as_categorized_lines(str(data.get("skills", ""))),
    )


def _assemble_plain(parsed: ParsedResume, t: TailoredSections) -> str:
    parts: list[str] = []
    if parsed.contact.strip():
        parts.append(parsed.contact.strip())
    parts.append("PROFESSIONAL SUMMARY\n" + t.professional_summary.strip())
    parts.append("PROFESSIONAL EXPERIENCE\n" + t.professional_experience.strip())
    parts.append("SKILLS\n" + t.skills.strip())
    if parsed.education.strip():
        parts.append("EDUCATION\n" + parsed.education.strip())
    if parsed.other.strip():
        parts.append("ADDITIONAL\n" + parsed.other.strip())
    return "\n\n".join(parts)


def _default_tips_llm() -> list[str]:
    return [
        "Editable resumes work best when they use clear section headings (Summary, Experience, Skills).",
        "The AI must rewrite bullets in new words for the posting—verify facts and tweak phrasing before you submit.",
        "Skills lines are prioritized for this job—add or trim tools so every claim is truthful.",
        "If wording still resembles your upload too closely, shorten the pasted JD to the must-haves or set OPENAI_TAILOR_TEMPERATURE slightly higher (e.g. 0.55).",
        "Raise OPENAI_TAILOR_MAX_TOKENS if responses truncate.",
    ]


def _default_tips_offline() -> list[str]:
    return [
        "Set OPENAI_API_KEY for AI-rewritten sections; offline mode adds keyword alignment notes.",
        "Use clear section headers (Profile/Summary, Experience, Skills) in your source file for best text splitting.",
        "Skills use category lines (Frontend:, Backend:, …); review each line before sending applications.",
    ]


def _build_pdf_sync(
    *,
    source_pdf_bytes: bytes | None,
    original_filename: str,
    parsed: ParsedResume,
    tailored: TailoredSections,
    template_key: str,
) -> tuple[str, str, bool, str, str]:
    """
    Returns (base64_pdf, download_filename, used_inplace_on_upload, template_key, template_label).

    In-place PDF edits are opt-in (USE_PDF_INPLACE=1): Helvetica-based viewers often
    showed '?' for bullets/dashes; FiraGO is used when enabled, but the default is a
    fresh Unicode-safe PDF (ReportLab + FiraGO) using the member's chosen layout.
    """
    download_name = output_pdf_filename(original_filename)
    pdf_tailored = TailoredSections(
        sanitize_for_pdf(tailored.professional_summary),
        sanitize_for_pdf(tailored.professional_experience),
        sanitize_for_pdf(tailored.skills),
    )
    use_inplace = os.getenv("USE_PDF_INPLACE", "").strip().lower() in ("1", "true", "yes")
    if use_inplace and source_pdf_bytes:
        inplace = apply_tailored_sections_to_pdf(
            source_pdf_bytes,
            professional_summary=pdf_tailored.professional_summary,
            professional_experience=pdf_tailored.professional_experience,
            skills=pdf_tailored.skills,
            parsed=parsed,
            original_filename=original_filename,
        )
        if inplace is not None:
            data, name = inplace
            return (
                base64.b64encode(data).decode("ascii"),
                name,
                True,
                "inplace",
                "Original PDF (in-place edits)",
            )
    pdf_bytes, tmpl_key, tmpl_label = build_template_pdf(
        template_key,
        contact=sanitize_for_pdf(parsed.contact),
        professional_summary=pdf_tailored.professional_summary,
        professional_experience=pdf_tailored.professional_experience,
        skills=pdf_tailored.skills,
        education=sanitize_for_pdf(parsed.education),
        other=sanitize_for_pdf(parsed.other),
    )
    return base64.b64encode(pdf_bytes).decode("ascii"), download_name, False, tmpl_key, tmpl_label


async def tailor_resume(
    resume_text: str,
    job_description: str,
    *,
    source_pdf_bytes: bytes | None = None,
    original_filename: str = "resume.pdf",
    template_key: str = "",
) -> TailorResponse:
    parsed = parse_resume_sections(resume_text)
    keywords = extract_keywords(job_description, top_k=22)
    key = os.getenv("OPENAI_API_KEY", "").strip()
    used_llm = False
    tailored: TailoredSections

    if key:
        try:
            tailored = await _llm_tailor_structured(parsed, job_description, key)
            if not (
                tailored.professional_summary.strip()
                or tailored.professional_experience.strip()
                or tailored.skills.strip()
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

    tailored = TailoredSections(
        professional_summary=tailored.professional_summary,
        professional_experience=tailored.professional_experience,
        skills=_skills_as_categorized_lines(tailored.skills),
    )
    full_text = _assemble_plain(parsed, tailored)

    pdf_b64 = ""
    download_name = output_pdf_filename(original_filename)
    pdf_template_key = template_key
    pdf_template_label = ""
    if template_key:
        try:
            pdf_template_label = get_template_meta(template_key)["label"]
        except KeyError:
            pdf_template_label = template_key

    if template_key:
        try:
            pdf_b64, download_name, used_inplace, pdf_template_key, pdf_template_label = await asyncio.to_thread(
                _build_pdf_sync,
                source_pdf_bytes=source_pdf_bytes,
                original_filename=original_filename,
                parsed=parsed,
                tailored=tailored,
                template_key=template_key,
            )
            if not used_inplace and source_pdf_bytes:
                tips = [
                    *tips,
                    "Your tailored CV was exported using your chosen template layout.",
                ]
        except Exception:
            tips = [*tips, "PDF export failed; tailored text sections are still available below. Retry or contact support."]

    return TailorResponse(
        tailored_resume=full_text,
        tailored_summary=tailored.professional_summary,
        tailored_experience=tailored.professional_experience,
        tailored_skills=tailored.skills,
        pdf_base64=pdf_b64,
        download_filename=download_name,
        keywords_highlighted=keywords,
        ats_tips=tips,
        used_llm=used_llm,
        pdf_template_key=pdf_template_key,
        pdf_template_label=pdf_template_label,
    )
