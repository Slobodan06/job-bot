from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

from app.services.pdf_fonts import pymupdf_fira_buffer, pymupdf_fira_fontname
from app.services.pdf_text_util import sanitize_for_pdf
from app.services.sectionize import ParsedResume

# Phrases to locate section headers (first match per section in reading order wins).
HEADER_QUERIES: dict[str, list[str]] = {
    "summary": [
        "PROFESSIONAL SUMMARY",
        "Professional Summary",
        "SUMMARY",
        "Summary",
        "PROFILE",
        "Profile",
        "OBJECTIVE",
        "Objective",
    ],
    "experience": [
        "PROFESSIONAL WORK EXPERIENCE",
        "Professional Work Experience",
        "PROFESSIONAL EXPERIENCE",
        "Professional Experience",
        "WORK EXPERIENCE",
        "Work Experience",
        "EMPLOYMENT HISTORY",
        "Employment History",
        "EXPERIENCE",
        "Experience",
        "CAREER HISTORY",
        "Career History",
    ],
    "skills": [
        "TECHNICAL SKILLS",
        "Technical Skills",
        "CORE COMPETENCIES",
        "Core Competencies",
        "KEY SKILLS",
        "Key Skills",
        "SKILLS",
        "Skills",
        "EXPERTISE",
        "Expertise",
    ],
}

_MARGIN = 40


def _safe_output_pdf_name(original_filename: str) -> str:
    name = Path(original_filename).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    if not name or name in (".", ".."):
        return "resume.pdf"
    stem = Path(name).stem or "resume"
    return f"{stem}.pdf"


def _rects_for_queries(page: fitz.Page, queries: list[str]) -> list[fitz.Rect]:
    found: list[fitz.Rect] = []
    for q in queries:
        try:
            hits = page.search_for(q, quads=False)
        except (RuntimeError, ValueError):
            continue
        for h in hits:
            r = fitz.Rect(h) if not isinstance(h, fitz.Rect) else h
            if r.is_empty:
                continue
            found.append(r)
    return found


def _collect_header_hits(doc: fitz.Document) -> list[tuple[int, fitz.Rect, str]]:
    raw: list[tuple[int, fitz.Rect, str]] = []
    for page_index in range(len(doc)):
        page = doc[page_index]
        for sec, queries in HEADER_QUERIES.items():
            for r in _rects_for_queries(page, queries):
                raw.append((page_index, fitz.Rect(r), sec))
    # One hit per (page, section): keep topmost (smallest y0).
    best: dict[tuple[int, str], tuple[int, fitz.Rect, str]] = {}
    for page_index, r, sec in raw:
        key = (page_index, sec)
        if key not in best or r.y0 < best[key][1].y0:
            best[key] = (page_index, r, sec)
    hits = list(best.values())
    hits.sort(key=lambda t: (t[0], t[1].y0, t[1].x0))
    return hits


def _pick_ordered_headers(hits: list[tuple[int, fitz.Rect, str]]) -> dict[str, tuple[int, fitz.Rect]] | None:
    """Pick first summary, then first experience after it in reading order, then first skills after that."""
    if not hits:
        return None
    try:
        idx_s = next(i for i, h in enumerate(hits) if h[2] == "summary")
    except StopIteration:
        return None
    try:
        idx_e = next(i for i, h in enumerate(hits) if i > idx_s and h[2] == "experience")
    except StopIteration:
        return None
    try:
        idx_k = next(i for i, h in enumerate(hits) if i > idx_e and h[2] == "skills")
    except StopIteration:
        return None
    sp, sr, _ = hits[idx_s]
    ep, er, _ = hits[idx_e]
    kp, kr, _ = hits[idx_k]
    return {
        "summary": (sp, fitz.Rect(sr)),
        "experience": (ep, fitz.Rect(er)),
        "skills": (kp, fitz.Rect(kr)),
    }


def _body_rect_for_gap(
    doc: fitz.Document,
    page_index: int,
    top_y: float,
    end_page_index: int | None,
    end_y: float | None,
) -> fitz.Rect:
    """Body runs from top_y to end_y on the same page, or to page bottom if end is on a later page."""
    page = doc[page_index]
    pr = page.rect
    x0, x1 = _MARGIN, pr.width - _MARGIN
    bottom = pr.height - _MARGIN
    if end_page_index is not None and end_page_index == page_index and end_y is not None:
        bottom = min(bottom, max(top_y + 8, end_y - 4))
    return fitz.Rect(x0, top_y, x1, bottom)


def _guess_fontsize(page: fitz.Page, y_ref: float) -> float:
    sizes: list[float] = []
    try:
        d = page.get_text("dict")
    except (RuntimeError, ValueError):
        return 10.0
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                bbox = span.get("bbox")
                if not bbox:
                    continue
                cy = (bbox[1] + bbox[3]) / 2
                if abs(cy - y_ref) < 100:
                    sz = float(span.get("size") or 10)
                    if 5 <= sz <= 24:
                        sizes.append(sz)
    if sizes:
        return max(7.0, min(12.0, sum(sizes) / len(sizes)))
    return 10.0


def _redact_white(page: fitz.Page, rect: fitz.Rect) -> None:
    page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions()


def _ensure_fira_font(page: fitz.Page, embedded_pages: set[int], page_index: int) -> str:
    """Embed FiraGO once per page (wide Unicode coverage; avoids '?' from Helvetica)."""
    fn = pymupdf_fira_fontname()
    if page_index not in embedded_pages:
        page.insert_font(fn, fontbuffer=pymupdf_fira_buffer())
        embedded_pages.add(page_index)
    return fn


def _insert_fitted(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    fontsize: float,
    *,
    fontname: str,
) -> bool:
    t = sanitize_for_pdf((text or "").replace("\r\n", "\n").strip())
    if not t:
        t = " "
    fs = fontsize
    while fs >= 6:
        rc = page.insert_textbox(
            rect,
            t,
            fontsize=fs,
            fontname=fontname,
            color=(0, 0, 0),
            align=fitz.TEXT_ALIGN_LEFT,
        )
        if rc >= 0:
            return True
        fs -= 0.75
    return False


def apply_tailored_sections_to_pdf(
    pdf_bytes: bytes,
    *,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    parsed: ParsedResume,
    original_filename: str,
) -> tuple[bytes, str] | None:
    """
    Returns (new_pdf_bytes, download_filename) or None if headers could not be resolved.
    """
    _ = parsed  # reserved for future layout hints
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        hits = _collect_header_hits(doc)
        ordered = _pick_ordered_headers(hits)
        if ordered is None:
            return None

        s_page, s_rect = ordered["summary"]
        e_page, e_rect = ordered["experience"]
        k_page, k_rect = ordered["skills"]

        # Body rectangles (same-page slices only to avoid wiping unrelated pages).
        r_summary = _body_rect_for_gap(doc, s_page, s_rect.y1 + 2, e_page, e_rect.y0)
        r_exp = _body_rect_for_gap(doc, e_page, e_rect.y1 + 2, k_page, k_rect.y0)
        r_skills = _body_rect_for_gap(doc, k_page, k_rect.y1 + 2, None, None)

        ops: list[tuple[int, fitz.Rect, str, float]] = []
        ops.append((s_page, r_summary, professional_summary, _guess_fontsize(doc[s_page], s_rect.y1 + 40)))
        ops.append((e_page, r_exp, professional_experience, _guess_fontsize(doc[e_page], e_rect.y1 + 40)))
        ops.append((k_page, r_skills, skills, _guess_fontsize(doc[k_page], k_rect.y1 + 40)))

        # Bottom-most regions first so earlier geometry stays valid longer.
        ops.sort(key=lambda o: (o[0], o[1].y0), reverse=True)

        embedded: set[int] = set()
        for pno, rect, new_text, fs in ops:
            page = doc[pno]
            if rect.height < 12 or rect.width < 40:
                continue
            _redact_white(page, rect)
            fn = _ensure_fira_font(page, embedded, pno)
            ok = _insert_fitted(page, rect, new_text, fs, fontname=fn)
            if not ok:
                return None

        out = doc.tobytes(deflate=True, garbage=4, clean=True)
        return out, _safe_output_pdf_name(original_filename)
    finally:
        doc.close()


def output_pdf_filename(original_filename: str) -> str:
    return _safe_output_pdf_name(original_filename)
