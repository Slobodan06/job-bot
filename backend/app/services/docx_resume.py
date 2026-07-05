"""Structured resume parsing and in-place tailoring for Word (.docx) uploads."""
from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from app.services.pdf_resume import (
    line_is_factual_contact,
)
from app.services.sectionize import (
    ParsedResume,
    _partition_education_and_other,
    _separate_misplaced_jobs_from_education,
    match_section_header,
    parse_resume_sections,
)

_TAILOR_HEADER_SECTIONS = (
    "professional_summary",
    "professional_experience",
    "skills",
    "education",
    "other",
)
_FROZEN_DOCX_SECTIONS = frozenset({"education", "other"})
_EDITABLE_DOCX_SECTIONS = frozenset({"professional_summary", "professional_experience", "skills"})
_BULLET_CHAR_RE = re.compile(r"^[\-•*–—\u2022]\s*")
_SKILL_CATEGORY_RE = re.compile(
    r"^[\-•*–—\u2022]?\s*(language|frontend|backend|ai/?ml|database|testing|devops|cloud|practices|tools|"
    r"frameworks?|platforms?|methodolog\w*)\s*:",
    re.I,
)
_TABLE_SUMMARY_RE = re.compile(r"^(professional\s+)?summary$|^profile$", re.I)
_TABLE_SKILLS_RE = re.compile(r"^skills$|^technical\s+skills$", re.I)
_TABLE_WORK_EXP_RE = re.compile(r"work\s+experience|^experience$", re.I)
_TABLE_EDUCATION_RE = re.compile(r"^education$", re.I)


@dataclass(frozen=True)
class ExperienceRowRef:
    """One job row inside a Word table (company/title/date cells stay frozen)."""

    table_idx: int
    row_idx: int
    content_cols: tuple[int, ...] = (0, 1)


@dataclass
class DocxResumeDocument:
    """Parsed resume content plus paragraph indices for in-place Word edits."""

    parsed: ParsedResume
    plain_text: str
    section_header_indices: dict[str, int] = field(default_factory=dict)
    section_body_indices: dict[str, list[int]] = field(default_factory=dict)
    contact_paragraph_indices: list[int] = field(default_factory=list)
    experience_table_rows: list[ExperienceRowRef] = field(default_factory=list)


_BULLET_PREFIX_RE = re.compile(r"^[\-•*–—]\s+")
_ROLE_START_RE = re.compile(
    r"\b\d{1,2}/\d{4}\s*[–\-—]\s*(\d{1,2}/\d{4}|present|current)\b",
    re.I,
)


def _looks_like_docx(data: bytes) -> bool:
    return data[:2] == b"PK"


def _paragraph_text(paragraph: Paragraph) -> str:
    parts: list[str] = []
    for run in paragraph.runs:
        parts.append(run.text or "")
    if parts:
        return "".join(parts)
    return (paragraph.text or "").strip()


def _is_list_paragraph(paragraph: Paragraph) -> bool:
    p_pr = paragraph._element.find(qn("w:pPr"))
    if p_pr is None:
        return False
    return p_pr.find(qn("w:numPr")) is not None


def _is_bullet_paragraph(paragraph: Paragraph) -> bool:
    text = _paragraph_text(paragraph).strip()
    if not text:
        return _is_list_paragraph(paragraph)
    return _is_list_paragraph(paragraph) or bool(_BULLET_PREFIX_RE.match(text))


def _line_from_paragraph(paragraph: Paragraph) -> str | None:
    text = _paragraph_text(paragraph).strip()
    if not text:
        return None
    style_name = paragraph.style.name if paragraph.style and paragraph.style.name else ""
    if _is_list_paragraph(paragraph) or re.search(r"list|bullet", style_name, re.I):
        if not _BULLET_PREFIX_RE.match(text):
            return f"- {text}"
    return text


def _table_lines(doc: Document) -> list[str]:
    lines: list[str] = []
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
        if lines and lines[-1]:
            lines.append("")
    return lines


def _display_line_for_paragraph(line: str, paragraph: Paragraph) -> str:
    if _is_bullet_paragraph(paragraph):
        # Skill/category lines (e.g. "• Frontend: React") keep the leading marker.
        if _looks_like_skill_category_line(line) or (
            _looks_like_skill_category_line(_paragraph_text(paragraph))
        ):
            return line.strip()
        return _BULLET_PREFIX_RE.sub("", line).strip()
    return line


def _replace_paragraph_text_inplace(paragraph: Paragraph, text: str) -> None:
    """Replace paragraph text while keeping existing runs/styles (first run keeps formatting)."""
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


_HIGHLIGHT_METRIC_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|percent\b)|"
    r"\b\d+\+\b|"
    r"\b\d{1,3}(?:,\d{3})+\+?\b|"
    r"\b(?:reduced|increased|improved|cut|decreased|accelerated|boosted|lowered|grew|saved|"
    r"delivered|processed|scaled|optimized)\b[^.!?\n]{0,40}\bby\s+\d+(?:\.\d+)?\s*(?:%|x\b|X\b)?",
    re.I,
)
_HIGHLIGHT_TECH_RE = re.compile(
    r"\b(?:React(?:\.js)?|Angular|Vue(?:\.js)?|Node(?:\.js)?|TypeScript|JavaScript|Python|"
    r"Java|Kotlin|Go\b|Golang|C#|\.NET|AWS|Azure|GCP|Docker|Kubernetes|Terraform|CI/CD|"
    r"PostgreSQL|MongoDB|Redis|GraphQL|REST(?:ful)?|APIs?|FastAPI|Django|Flask|Rails|"
    r"Next(?:\.js)?|Express(?:\.js)?|Kubernetes|Lambda|OpenAI|TensorFlow|PyTorch)\b",
    re.I,
)


def _copy_run_font(source_run, target_run) -> None:
    if source_run.font.name:
        target_run.font.name = source_run.font.name
    if source_run.font.size:
        target_run.font.size = source_run.font.size
    if source_run.font.color and source_run.font.color.rgb:
        target_run.font.color.rgb = source_run.font.color.rgb


def _bold_spans_for_text(text: str, highlight_terms: list[str] | None) -> list[tuple[int, int]]:
    if not text:
        return []
    spans: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in spans)

    for match in _HIGHLIGHT_METRIC_RE.finditer(text):
        if not _overlaps(match.start(), match.end()):
            spans.append((match.start(), match.end()))

    for match in _HIGHLIGHT_TECH_RE.finditer(text):
        if len(match.group(0)) >= 3 and not _overlaps(match.start(), match.end()):
            spans.append((match.start(), match.end()))

    terms = sorted({t.strip() for t in (highlight_terms or []) if t and len(t.strip()) >= 3}, key=len, reverse=True)
    for term in terms:
        if len(term) > 80:
            continue
        if re.match(r"^[\w\-./+#]+$", term):
            pattern = re.compile(r"(?<![\w\-./+#])" + re.escape(term) + r"(?![\w\-./+#])", re.I)
        else:
            pattern = re.compile(re.escape(term), re.I)
        for match in pattern.finditer(text):
            if not _overlaps(match.start(), match.end()):
                spans.append((match.start(), match.end()))

    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _replace_paragraph_text_with_highlights(
    paragraph: Paragraph,
    text: str,
    highlight_terms: list[str] | None = None,
) -> None:
    """Replace paragraph text, bolding JD keywords, tech terms, and metrics in-place."""
    spans = _bold_spans_for_text(text, highlight_terms)
    if not spans:
        _replace_paragraph_text_inplace(paragraph, text)
        return

    template_run = paragraph.runs[0] if paragraph.runs else None
    p_element = paragraph._element
    for child in list(p_element):
        if child.tag == qn("w:r"):
            p_element.remove(child)

    pos = 0
    for start, end in spans:
        if start > pos:
            run = paragraph.add_run(text[pos:start])
            if template_run:
                _copy_run_font(template_run, run)
        bold_run = paragraph.add_run(text[start:end])
        bold_run.bold = True
        if template_run:
            _copy_run_font(template_run, bold_run)
        pos = end
    if pos < len(text):
        run = paragraph.add_run(text[pos:])
        if template_run:
            _copy_run_font(template_run, run)


def _sync_paragraph_runs(dup_para: Paragraph, src_para: Paragraph) -> None:
    if dup_para._element is src_para._element:
        return
    dup_el = dup_para._element
    for child in list(dup_el):
        if child.tag == qn("w:r"):
            dup_el.remove(child)
    for child in src_para._element:
        if child.tag == qn("w:r"):
            dup_el.append(deepcopy(child))


def _clone_and_insert_after(
    anchor: Paragraph,
    template: Paragraph,
    text: str,
    highlight_terms: list[str] | None = None,
) -> Paragraph:
    display = _display_line_for_paragraph(text, template)
    new_p = deepcopy(template._element)
    anchor._p.addnext(new_p)
    new_para = Paragraph(new_p, anchor._parent)
    _replace_paragraph_text_with_highlights(new_para, display, highlight_terms)
    return new_para


def _delete_paragraph(paragraph: Paragraph) -> None:
    element = paragraph._element
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _delete_paragraphs_at_indices(doc: Document, indices: list[int]) -> None:
    for idx in sorted(set(indices), reverse=True):
        if 0 <= idx < len(doc.paragraphs):
            _delete_paragraph(doc.paragraphs[idx])


def _split_tailored_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        if stripped:
            lines.append(stripped)
    return lines


def _partition_header_and_bullet_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    headers: list[str] = []
    bullets: list[str] = []
    for line in lines:
        if _BULLET_PREFIX_RE.match(line):
            bullets.append(line)
        else:
            headers.append(line)
    return headers, bullets


def _is_experience_role_start(paragraph: Paragraph, text: str) -> bool:
    if _is_bullet_paragraph(paragraph):
        return False
    # In-role sub-headings (e.g. "DevOps & Cloud Engineering:") are not new employers.
    if text.rstrip().endswith(":") and "|" not in text and not _ROLE_START_RE.search(text):
        return False
    if _ROLE_START_RE.search(text):
        return True
    if "|" in text and len(text) < 120:
        return True
    if re.search(
        r"\b(engineer|developer|manager|architect|analyst|consultant|specialist|director|lead|principal)\b",
        text,
        re.I,
    ):
        return len(text) < 100 and "|" in text
    return False


def _group_experience_paragraph_indices(doc: Document, indices: list[int]) -> list[list[int]]:
    if not indices:
        return []
    blocks: list[list[int]] = []
    current: list[int] = []
    for idx in indices:
        para = doc.paragraphs[idx]
        text = _paragraph_text(para).strip()
        if current and text and _is_experience_role_start(para, text):
            blocks.append(current)
            current = [idx]
        else:
            current.append(idx)
    if current:
        blocks.append(current)
    return blocks if len(blocks) > 1 else [indices]


def _bullet_lines(text: str) -> list[str]:
    return [line for line in _split_tailored_lines(text) if _BULLET_PREFIX_RE.match(line)]


def _partition_bullets_by_block_counts(bullets: list[str], counts: list[int]) -> list[list[str]]:
    """Split flat bullet list into per-role groups matching source paragraph counts."""
    if not counts:
        return [bullets] if bullets else []
    out: list[list[str]] = []
    pos = 0
    for count in counts:
        chunk = bullets[pos : pos + count] if count > 0 else []
        out.append(chunk)
        pos += max(count, 0)
    if pos < len(bullets) and out:
        extras = bullets[pos:]
        for i, bullet in enumerate(extras):
            out[i % len(out)].append(bullet)
    return out


def _update_experience_bullets_only(
    doc: Document,
    indices: list[int],
    new_text: str,
    highlight_terms: list[str] | None = None,
) -> None:
    """
    Update ONLY list/bullet paragraphs in each role block.
    Company name, title, location, dates, and other non-bullet lines are never modified.
    """
    if not indices or not new_text.strip():
        return

    para_blocks = _group_experience_paragraph_indices(doc, indices)
    bullet_counts = [
        sum(1 for idx in block if _is_bullet_paragraph(doc.paragraphs[idx]))
        for block in para_blocks
    ]
    llm_bullets = _bullet_lines(new_text)
    bullets_per_block = _partition_bullets_by_block_counts(llm_bullets, bullet_counts)

    for block_i, para_block in enumerate(para_blocks):
        bullet_indices = [idx for idx in para_block if _is_bullet_paragraph(doc.paragraphs[idx])]
        if not bullet_indices:
            continue
        new_bullets = bullets_per_block[block_i] if block_i < len(bullets_per_block) else []

        for bi, idx in enumerate(bullet_indices):
            if bi >= len(new_bullets):
                break
            para = doc.paragraphs[idx]
            display = _display_line_for_paragraph(new_bullets[bi], para)
            _replace_paragraph_text_with_highlights(para, display, highlight_terms)

        if len(new_bullets) > len(bullet_indices):
            anchor = doc.paragraphs[bullet_indices[-1]]
            template = doc.paragraphs[bullet_indices[0]]
            for line in new_bullets[len(bullet_indices) :]:
                anchor = _clone_and_insert_after(anchor, template, line, highlight_terms)


def _update_lines_index_preserving(
    doc: Document,
    indices: list[int],
    new_text: str,
) -> None:
    """
    Update paragraph i with line i only — preserves structure, styles, and extra paragraphs.
    Paragraphs beyond len(new_lines) are left unchanged (no deletes, no clearing).
    """
    lines = _split_tailored_lines(new_text)
    if not lines or not indices:
        return
    if len(indices) == 1 and len(lines) > 1:
        _replace_paragraph_text_inplace(doc.paragraphs[indices[0]], " ".join(lines))
        return
    for i, idx in enumerate(indices):
        if i >= len(lines) or idx >= len(doc.paragraphs):
            break
        para = doc.paragraphs[idx]
        line = lines[i]
        existing = _paragraph_text(para).strip()
        if existing and _BULLET_CHAR_RE.match(existing) and not _BULLET_CHAR_RE.match(line):
            line = _format_bullet_line(_BULLET_CHAR_RE.match(existing).group(0), line)
        display = _display_line_for_paragraph(line, para)
        _replace_paragraph_text_inplace(para, display)


def _reassign_trailing_education_indices(
    body_indices: dict[str, list[int]],
    parsed: ParsedResume,
) -> None:
    if body_indices.get("education"):
        return
    edu_count = len(_split_tailored_lines(parsed.education))
    if edu_count <= 0:
        return
    skill_idx = body_indices.get("skills", [])
    if len(skill_idx) < edu_count:
        return
    body_indices["education"] = skill_idx[-edu_count:]
    body_indices["skills"] = skill_idx[:-edu_count]


def _normalize_table_label(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _table_row_label(table, row_idx: int = 0) -> str:
    if row_idx >= len(table.rows):
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    for cell in table.rows[row_idx].cells:
        label = _normalize_table_label(cell.text)
        if label and label not in seen:
            seen.add(label)
            parts.append(label)
    return " | ".join(parts)


def _is_bulletish_text(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    return bool(_BULLET_CHAR_RE.match(stripped))


def _looks_like_skill_category_line(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _SKILL_CATEGORY_RE.match(stripped):
        return True
    return _is_bulletish_text(stripped) and ":" in stripped.split("\n", 1)[0][:60]


def _cell_bullet_paragraph_indices(cell) -> list[int]:
    indices: list[int] = []
    for idx, para in enumerate(cell.paragraphs):
        if _is_bulletish_text(_paragraph_text(para)):
            indices.append(idx)
    return indices


def _detect_bullet_prefix(cell) -> str:
    for para in cell.paragraphs:
        text = _paragraph_text(para).strip()
        if not text:
            continue
        match = _BULLET_CHAR_RE.match(text)
        if match:
            return match.group(0).rstrip()
    return "•"


def _format_bullet_line(prefix: str, line: str) -> str:
    body = _BULLET_PREFIX_RE.sub("", line).strip()
    body = re.sub(r"^[\-•*–—\u2022]\s*", "", body).strip()
    sep = "" if prefix.endswith(" ") else " "
    return f"{prefix}{sep}{body}".strip()


def _find_work_experience_table(doc: Document) -> tuple[int, int | None] | None:
    for ti, table in enumerate(doc.tables):
        label = _table_row_label(table, 0)
        if not _TABLE_WORK_EXP_RE.search(label):
            continue
        edu_row: int | None = None
        for ri in range(1, len(table.rows)):
            row_label = _table_row_label(table, ri)
            first = row_label.split("|", 1)[0].strip()
            if _TABLE_EDUCATION_RE.match(first):
                edu_row = ri
                break
        return ti, edu_row
    return None


def _detect_table_layout(doc: Document) -> tuple[list[int], list[int], list[ExperienceRowRef]] | None:
    """Detect summary/skills paragraphs and experience table rows (table-based templates)."""
    work = _find_work_experience_table(doc)
    if work is None:
        return None
    table_idx, edu_row = work

    summary_indices: list[int] = []
    skills_indices: list[int] = []
    skill_start: int | None = None

    for idx, para in enumerate(doc.paragraphs):
        text = _paragraph_text(para).strip()
        if not text:
            continue
        if _looks_like_skill_category_line(text):
            if skill_start is None:
                skill_start = idx
            skills_indices.append(idx)
        elif skill_start is None and len(text) > 60 and not _is_bulletish_text(text):
            summary_indices.append(idx)

    if not summary_indices:
        for idx, para in enumerate(doc.paragraphs):
            if _paragraph_text(para).strip():
                summary_indices = [idx]
                break

    exp_table = doc.tables[table_idx]
    end_row = edu_row if edu_row is not None else len(exp_table.rows)
    exp_rows: list[ExperienceRowRef] = []
    for ri in range(1, end_row):
        row_label = _table_row_label(exp_table, ri)
        first = row_label.split("|", 1)[0].strip()
        if _TABLE_EDUCATION_RE.match(first):
            break
        row = exp_table.rows[ri]
        content_cols = _unique_content_col_indices(row)
        content_cell = row.cells[content_cols[0]]
        if not content_cell.text.strip():
            continue
        exp_rows.append(ExperienceRowRef(table_idx=table_idx, row_idx=ri, content_cols=content_cols))

    if not exp_rows and not summary_indices and not skills_indices:
        return None
    return summary_indices, skills_indices, exp_rows


def _experience_text_from_table_row(doc: Document, ref: ExperienceRowRef) -> list[str]:
    cell = doc.tables[ref.table_idx].rows[ref.row_idx].cells[ref.content_cols[0]]
    lines: list[str] = []
    header_done = False
    for para in cell.paragraphs:
        text = _paragraph_text(para).strip()
        if not text:
            continue
        if _is_bulletish_text(text):
            header_done = True
            lines.append(_format_bullet_line("- ", text))
        elif not header_done:
            lines.append(text)
    date_cell = doc.tables[ref.table_idx].rows[ref.row_idx].cells[-1].text.strip()
    if date_cell:
        lines.append(date_cell)
    return lines


def _parsed_from_table_layout(
    doc: Document,
    summary_indices: list[int],
    skills_indices: list[int],
    exp_rows: list[ExperienceRowRef],
) -> ParsedResume:
    contact_lines: list[str] = []
    if doc.tables:
        for row in doc.tables[0].rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                contact_lines.append(" | ".join(dict.fromkeys(cells)))

    summary = "\n".join(_paragraph_text(doc.paragraphs[i]) for i in summary_indices).strip()
    skills = "\n".join(_paragraph_text(doc.paragraphs[i]) for i in skills_indices).strip()

    exp_blocks: list[str] = []
    for ref in exp_rows:
        block_lines = _experience_text_from_table_row(doc, ref)
        if block_lines:
            exp_blocks.append("\n".join(block_lines))
    experience = "\n\n".join(exp_blocks).strip()

    education_lines: list[str] = []
    other_lines: list[str] = []
    work = _find_work_experience_table(doc)
    if work:
        table_idx, edu_row = work
        if edu_row is not None:
            exp_table = doc.tables[table_idx]
            for ri in range(edu_row + 1, len(exp_table.rows)):
                row_text = " | ".join(
                    c.text.strip() for c in exp_table.rows[ri].cells if c.text.strip()
                )
                if row_text:
                    education_lines.append(row_text)

    for idx, para in enumerate(doc.paragraphs):
        text = _paragraph_text(para).strip()
        if not text or idx in summary_indices or idx in skills_indices:
            continue
        if _looks_like_skill_category_line(text):
            continue
        if idx in summary_indices:
            continue
        other_lines.append(text)

    return ParsedResume(
        contact="\n".join(contact_lines).strip(),
        professional_summary=summary,
        professional_experience=experience,
        skills=skills,
        education="\n".join(education_lines).strip(),
        other="\n".join(other_lines).strip(),
    )


def _apply_table_layout_to_parse(
    doc: Document,
    body_indices: dict[str, list[int]],
    section_header_indices: dict[str, int],
) -> tuple[ParsedResume, list[ExperienceRowRef], str]:
    layout = _detect_table_layout(doc)
    if layout is None:
        raise ValueError("no table layout")
    summary_indices, skills_indices, exp_rows = layout

    body_indices["professional_summary"] = summary_indices
    body_indices["skills"] = skills_indices
    body_indices["professional_experience"] = []
    body_indices["education"] = []
    body_indices["other"] = []

    for ti, table in enumerate(doc.tables):
        label = _table_row_label(table, 0)
        if _TABLE_SUMMARY_RE.match(label.split("|", 1)[0].strip()):
            section_header_indices.setdefault("professional_summary", -ti - 1)
        elif _TABLE_SKILLS_RE.match(label.split("|", 1)[0].strip()):
            section_header_indices.setdefault("skills", -ti - 1)
        elif _TABLE_WORK_EXP_RE.search(label):
            section_header_indices.setdefault("professional_experience", -ti - 1)

    parsed = _parsed_from_table_layout(doc, summary_indices, skills_indices, exp_rows)
    plain_parts = [parsed.contact, parsed.professional_summary, parsed.skills, parsed.professional_experience]
    plain_text = "\n\n".join(p for p in plain_parts if p).strip()
    return parsed, exp_rows, plain_text


def _update_experience_table_rows(
    doc: Document,
    rows: list[ExperienceRowRef],
    new_text: str,
    highlight_terms: list[str] | None = None,
) -> None:
    """Update bullet paragraphs inside experience table rows; title/company/date cells stay frozen."""
    if not rows or not new_text.strip():
        return

    bullet_counts = []
    for ref in rows:
        cell = doc.tables[ref.table_idx].rows[ref.row_idx].cells[ref.content_cols[0]]
        bullet_counts.append(len(_cell_bullet_paragraph_indices(cell)))

    llm_bullets = _bullet_lines(new_text)
    bullets_per_row = _partition_bullets_by_block_counts(llm_bullets, bullet_counts)

    for row_i, ref in enumerate(rows):
        cell = doc.tables[ref.table_idx].rows[ref.row_idx].cells[ref.content_cols[0]]
        bullet_indices = _cell_bullet_paragraph_indices(cell)
        if not bullet_indices:
            continue
        new_bullets = bullets_per_row[row_i] if row_i < len(bullets_per_row) else []
        prefix = _detect_bullet_prefix(cell)

        for bi, para_idx in enumerate(bullet_indices):
            if bi >= len(new_bullets):
                break
            formatted = _format_bullet_line(prefix, new_bullets[bi])
            _replace_paragraph_text_with_highlights(
                cell.paragraphs[para_idx],
                formatted,
                highlight_terms,
            )

        if len(new_bullets) > len(bullet_indices):
            anchor = cell.paragraphs[bullet_indices[-1]]
            template = cell.paragraphs[bullet_indices[0]]
            for line in new_bullets[len(bullet_indices) :]:
                anchor = _clone_and_insert_after(
                    anchor,
                    template,
                    _format_bullet_line(prefix, line),
                    highlight_terms,
                )

        for col in ref.content_cols[1:]:
            row_cells = doc.tables[ref.table_idx].rows[ref.row_idx].cells
            if col < len(row_cells):
                _sync_cell_paragraphs(row_cells[col], cell)


def _unique_content_col_indices(row) -> tuple[int, ...]:
    """Column indices for editable content, deduped when Word merges cells (same tc repeated)."""
    cols: list[int] = []
    seen_tc: set[int] = set()
    for ci, cell in enumerate(row.cells):
        tc_id = id(cell._tc)
        if tc_id in seen_tc:
            continue
        seen_tc.add(tc_id)
        cols.append(ci)
    return tuple(cols[:1] if cols else (0,))


def _sync_cell_paragraphs(dup_cell, source_cell) -> None:
    """Mirror paragraph runs (including bold highlights) into duplicate merged cells."""
    if dup_cell._tc is source_cell._tc:
        return
    src_paras = source_cell.paragraphs
    dup_paras = dup_cell.paragraphs
    for i, src_para in enumerate(src_paras):
        if i < len(dup_paras):
            _sync_paragraph_runs(dup_paras[i], src_para)


def _has_editable_docx_targets(
    section_body_indices: dict[str, list[int]],
    experience_table_rows: list[ExperienceRowRef],
) -> bool:
    if experience_table_rows:
        return True
    return any(section_body_indices.get(section) for section in _EDITABLE_DOCX_SECTIONS)


def extract_http_links_from_docx(docx_bytes: bytes) -> list[tuple[str, str]]:
    if not docx_bytes:
        return []
    doc = Document(BytesIO(docx_bytes))
    labeled: list[tuple[str, str]] = []
    seen: set[str] = set()
    for paragraph in doc.paragraphs:
        for hyperlink in paragraph._element.xpath(".//w:hyperlink"):
            r_id = hyperlink.get(qn("r:id"))
            if not r_id:
                continue
            try:
                url = paragraph.part.rels[r_id].target_ref.strip()
            except KeyError:
                continue
            if not url.lower().startswith(("http://", "https://")):
                continue
            key = url.lower().rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            label = "LinkedIn" if "linkedin.com" in key else "GitHub" if "github.com" in key else "Link"
            labeled.append((label, url))
    return labeled


def parse_resume_from_docx(data: bytes) -> DocxResumeDocument:
    if not _looks_like_docx(data):
        raise ValueError("Not a valid .docx file (expected a ZIP-based Word document).")

    doc = Document(BytesIO(data))
    buckets: dict[str, list[str]] = {
        "contact": [],
        "professional_summary": [],
        "professional_experience": [],
        "skills": [],
        "education": [],
        "other": [],
    }
    body_indices: dict[str, list[int]] = {key: [] for key in buckets}
    section_header_indices: dict[str, int] = {}
    contact_paragraph_indices: list[int] = []
    current = "contact"
    plain_lines: list[str] = []

    for idx, paragraph in enumerate(doc.paragraphs):
        line = _line_from_paragraph(paragraph)
        if line:
            stripped = line.strip()
            sec = match_section_header(stripped, in_contact=(current == "contact"))
            if sec:
                current = sec
                section_header_indices[sec] = idx
                if sec == "other":
                    buckets[current].append(line)
                    body_indices[current].append(idx)
                    plain_lines.append(line)
                continue
            buckets[current].append(line)
            body_indices[current].append(idx)
            plain_lines.append(line)
            if current == "contact":
                contact_paragraph_indices.append(idx)

    for line in _table_lines(doc):
        buckets[current].append(line)
        plain_lines.append(line)

    def join_bucket(key: str) -> str:
        return "\n".join(buckets[key]).strip()

    contact = join_bucket("contact")
    summary = join_bucket("professional_summary")
    experience = join_bucket("professional_experience")
    skills = join_bucket("skills")
    education = join_bucket("education")
    other = join_bucket("other")

    if not any([summary, experience, skills, education, other]) and contact:
        experience = contact
        contact = ""
        body_indices["professional_experience"] = list(body_indices["contact"])
        body_indices["contact"] = []
        contact_paragraph_indices = []

    education, other = _partition_education_and_other(education, other)
    education, experience = _separate_misplaced_jobs_from_education(education, experience)

    parsed = ParsedResume(
        contact=contact,
        professional_summary=summary,
        professional_experience=experience,
        skills=skills,
        education=education,
        other=other,
    )
    plain_text = "\n".join(plain_lines).strip()

    if not plain_text.strip():
        raise ValueError("Could not read any text from this Word document.")

    if not any([summary, experience, skills]) and plain_text:
        parsed = parse_resume_sections(plain_text)

    section_body_indices = {key: list(body_indices[key]) for key in _TAILOR_HEADER_SECTIONS}
    _reassign_trailing_education_indices(section_body_indices, parsed)

    experience_table_rows: list[ExperienceRowRef] = []
    table_layout = _detect_table_layout(doc)
    if table_layout is not None:
        try:
            parsed, experience_table_rows, plain_text = _apply_table_layout_to_parse(
                doc,
                section_body_indices,
                section_header_indices,
            )
        except ValueError:
            experience_table_rows = []

    return DocxResumeDocument(
        parsed=parsed,
        plain_text=plain_text,
        section_header_indices=section_header_indices,
        section_body_indices=section_body_indices,
        contact_paragraph_indices=contact_paragraph_indices,
        experience_table_rows=experience_table_rows,
    )


def _update_contact_inplace(
    doc: Document,
    contact_indices: list[int],
    new_text: str,
) -> None:
    valid_indices = [i for i in contact_indices if i < len(doc.paragraphs)]
    if not valid_indices:
        return

    new_lines = [line for line in _split_tailored_lines(new_text) if not line_is_factual_contact(line)]
    header_indices = [
        i for i in valid_indices if not line_is_factual_contact(_paragraph_text(doc.paragraphs[i]))
    ]
    new_i = 0
    for idx in header_indices:
        if new_i >= len(new_lines):
            break
        para = doc.paragraphs[idx]
        _replace_paragraph_text_inplace(
            para,
            _display_line_for_paragraph(new_lines[new_i], para),
        )
        new_i += 1


def _update_section_inplace(
    doc: Document,
    section_name: str,
    indices: list[int],
    new_text: str,
    source_text: str,
    highlight_terms: list[str] | None = None,
) -> None:
    if section_name in _FROZEN_DOCX_SECTIONS:
        return
    if section_name not in _EDITABLE_DOCX_SECTIONS:
        return
    if section_name == "professional_experience":
        _update_experience_bullets_only(doc, indices, new_text, highlight_terms)
    else:
        _update_lines_index_preserving(doc, indices, new_text)


def _first_table_xml(document_xml: str) -> str | None:
    body_match = re.search(r"<w:body>(.*)</w:body>", document_xml, re.S)
    if not body_match:
        return None
    inner = body_match.group(1)
    pos = inner.find("<w:tbl")
    if pos < 0:
        return None
    end = _find_w_element_end(inner, pos, "tbl")
    return inner[pos:end] if end > pos else None


def _replace_first_table_xml(document_xml: str, header_table_xml: str) -> str:
    body_match = re.search(r"(<w:body>)(.*?)(</w:body>)", document_xml, re.S)
    if not body_match:
        return document_xml
    inner = body_match.group(2)
    pos = inner.find("<w:tbl")
    if pos < 0:
        return document_xml
    end = _find_w_element_end(inner, pos, "tbl")
    if end < 0:
        return document_xml
    new_inner = inner[:pos] + header_table_xml + inner[end:]
    return (
        document_xml[: body_match.start()]
        + body_match.group(1)
        + new_inner
        + body_match.group(3)
        + document_xml[body_match.end() :]
    )


def _find_w_element_end(xml: str, start: int, local_name: str) -> int:
    """Return the end index of a <w:local_name ...>...</w:local_name> element."""
    open_prefix = f"<w:{local_name}"
    close_tag = f"</w:{local_name}>"
    if not xml.startswith(open_prefix, start):
        return -1
    after = start + len(open_prefix)
    if after >= len(xml) or xml[after] not in (">", " ", "/"):
        return -1

    pos = after
    depth = 1
    while pos < len(xml) and depth > 0:
        next_open = _find_next_w_open(xml, pos, local_name)
        next_close = xml.find(close_tag, pos)
        if next_close < 0:
            return -1
        if next_open >= 0 and next_open < next_close:
            depth += 1
            pos = next_open + len(open_prefix)
            continue
        depth -= 1
        pos = next_close + len(close_tag)
    return pos


def _find_next_w_open(xml: str, pos: int, local_name: str) -> int:
    open_prefix = f"<w:{local_name}"
    idx = pos
    while True:
        idx = xml.find(open_prefix, idx)
        if idx < 0:
            return -1
        after = idx + len(open_prefix)
        if after < len(xml) and xml[after] in (">", " ", "/"):
            return idx
        idx = after


def _split_document_body_children(document_xml: str) -> list[str] | None:
    body_match = re.search(r"<w:body>(.*)</w:body>", document_xml, re.S)
    if not body_match:
        return None

    inner = body_match.group(1)
    children: list[str] = []
    pos = 0
    length = len(inner)
    while pos < length:
        while pos < length and inner[pos].isspace():
            pos += 1
        if pos >= length:
            break

        if inner.startswith("<w:p", pos):
            end = _find_w_element_end(inner, pos, "p")
        elif inner.startswith("<w:tbl", pos):
            end = _find_w_element_end(inner, pos, "tbl")
        elif inner.startswith("<w:sectPr", pos):
            end = _find_w_element_end(inner, pos, "sectPr")
        else:
            return None

        if end < 0:
            return None
        children.append(inner[pos:end])
        pos = end

    return children or None


def _merge_document_xml_preserving_layout(
    original_xml: str,
    modified_xml: str,
    *,
    editable_paragraph_indices: set[int],
    editable_table_index: int | None,
) -> str | None:
    """
    Keep original page/body XML byte-for-byte for every frozen region; only swap in
    modified summary/skills paragraphs and the work-experience table.
    """
    orig_children = _split_document_body_children(original_xml)
    mod_children = _split_document_body_children(modified_xml)
    if not orig_children or len(orig_children) != len(mod_children):
        return None

    para_idx = 0
    tbl_idx = 0
    merged_parts: list[str] = []
    for o_child, m_child in zip(orig_children, mod_children):
        if o_child.startswith("<w:sectPr"):
            merged_parts.append(o_child)
            continue
        if o_child.startswith("<w:tbl"):
            use_modified = editable_table_index is not None and tbl_idx == editable_table_index
            merged_parts.append(m_child if use_modified else o_child)
            tbl_idx += 1
            continue
        if o_child.startswith("<w:p"):
            use_modified = para_idx in editable_paragraph_indices
            merged_parts.append(m_child if use_modified else o_child)
            para_idx += 1
            continue
        merged_parts.append(o_child)

    body_match = re.search(r"(<w:body>).*?(</w:body>)", original_xml, re.S)
    if not body_match:
        return None
    merged_body = body_match.group(1) + "".join(merged_parts) + body_match.group(2)
    return original_xml[: body_match.start()] + merged_body + original_xml[body_match.end() :]


def _restore_frozen_docx_parts(
    original_bytes: bytes,
    modified_bytes: bytes,
    *,
    editable_paragraph_indices: set[int] | None = None,
    editable_table_index: int | None = None,
) -> bytes:
    """
    python-docx save can strip package metadata and subtly alter header drawings.
    Restore header table + media/package parts from the upload so profile photos,
    round crops, fonts, and contact layout stay exactly as uploaded.
    """
    editable_paragraph_indices = editable_paragraph_indices or set()
    with ZipFile(BytesIO(original_bytes)) as orig_zip:
        orig_names = set(orig_zip.namelist())
        orig_document = orig_zip.read("word/document.xml").decode("utf-8")
        header_table = _first_table_xml(orig_document)

        preserve_whole = [
            "[Content_Types].xml",
            "_rels/.rels",
            "docProps/core.xml",
            "docProps/app.xml",
            "word/_rels/document.xml.rels",
            "word/styles.xml",
            "word/stylesWithEffects.xml",
            "word/theme/theme1.xml",
            "word/fontTable.xml",
            "word/webSettings.xml",
            "word/settings.xml",
            "word/numbering.xml",
        ]
        preserved: dict[str, bytes] = {}
        for name in preserve_whole:
            if name in orig_names:
                preserved[name] = orig_zip.read(name)
        for name in orig_names:
            if name.startswith("word/media/"):
                preserved[name] = orig_zip.read(name)

    in_buf = BytesIO(modified_bytes)
    out_buf = BytesIO()
    with ZipFile(in_buf, "r") as mod_zip, ZipFile(out_buf, "w") as out_zip:
        for item in mod_zip.infolist():
            data = mod_zip.read(item.filename)
            if item.filename in preserved:
                data = preserved[item.filename]
            elif item.filename == "word/document.xml":
                mod_document = data.decode("utf-8")
                merged_document = _merge_document_xml_preserving_layout(
                    orig_document,
                    mod_document,
                    editable_paragraph_indices=editable_paragraph_indices,
                    editable_table_index=editable_table_index,
                )
                if merged_document is not None:
                    data = merged_document.encode("utf-8")
                elif header_table:
                    data = _replace_first_table_xml(mod_document, header_table).encode("utf-8")
            out_zip.writestr(item, data)

        for name, data in preserved.items():
            if name not in mod_zip.namelist():
                out_zip.writestr(name, data)

    return out_buf.getvalue()


def apply_tailored_sections_to_docx(
    docx_bytes: bytes,
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
    section_header_indices: dict[str, int],
    section_body_indices: dict[str, list[int]],
    contact_paragraph_indices: list[int],
    source_sections: ParsedResume,
    original_filename: str,
    experience_table_rows: list[ExperienceRowRef] | None = None,
    highlight_keywords: list[str] | None = None,
) -> tuple[bytes, str] | None:
    exp_rows = experience_table_rows or []
    highlights = [k.strip() for k in (highlight_keywords or []) if k and k.strip()]
    if not _has_editable_docx_targets(section_body_indices, exp_rows):
        return None

    doc = Document(BytesIO(docx_bytes))
    fallbacks = {
        "contact": source_sections.contact,
        "professional_summary": source_sections.professional_summary,
        "professional_experience": source_sections.professional_experience,
        "skills": source_sections.skills,
        "education": source_sections.education,
        "other": source_sections.other,
    }
    tailored_by_section = {
        "contact": contact,
        "professional_summary": professional_summary,
        "professional_experience": professional_experience,
        "skills": skills,
        "education": education,
        "other": other,
    }

    for section_name in reversed(_TAILOR_HEADER_SECTIONS):
        if section_name in _FROZEN_DOCX_SECTIONS:
            continue
        elif section_name == "professional_experience":
            exp_indices = section_body_indices.get(section_name, [])
            text = (professional_experience or "").strip() or (fallbacks["professional_experience"] or "").strip()
            if not text:
                continue
            if exp_rows:
                _update_experience_table_rows(doc, exp_rows, text, highlights)
            elif exp_indices:
                _update_experience_bullets_only(doc, exp_indices, text, highlights)
            continue
        indices = section_body_indices.get(section_name, [])
        if not indices:
            continue
        text = (tailored_by_section[section_name] or "").strip() or (fallbacks[section_name] or "").strip()
        if not text:
            continue
        _update_section_inplace(
            doc,
            section_name,
            indices,
            text,
            fallbacks[section_name],
            None,
        )

    # Contact/header block is never modified — name, title, email, phone, links stay as uploaded.

    out = BytesIO()
    doc.save(out)

    editable_paragraph_indices: set[int] = set(section_body_indices.get("professional_summary", []))
    editable_paragraph_indices.update(section_body_indices.get("skills", []))
    editable_table_index: int | None = None
    if exp_rows:
        editable_table_index = exp_rows[0].table_idx
    else:
        editable_paragraph_indices.update(section_body_indices.get("professional_experience", []))

    merged = _restore_frozen_docx_parts(
        docx_bytes,
        out.getvalue(),
        editable_paragraph_indices=editable_paragraph_indices,
        editable_table_index=editable_table_index,
    )
    return merged, output_docx_filename(original_filename)


def output_docx_filename(original_filename: str) -> str:
    name = Path(original_filename).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    if not name or name in (".", ".."):
        return "resume-tailored.docx"
    stem = Path(name).stem or "resume"
    return f"{stem}-tailored.docx"
