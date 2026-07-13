"""Deep-dive Ciro docx experience paragraph layout."""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from docx import Document

from app.services.docx_resume import (
    _all_document_paragraphs,
    _group_experience_paragraph_indices,
    _is_bullet_paragraph,
    _is_experience_role_start,
    _paragraph_text,
    parse_resume_from_docx,
)

DOCX = Path(r"C:\Users\Jelix\Downloads\cv_ciro-fullstack (3).docx")


def main() -> None:
    docx_bytes = DOCX.read_bytes()
    parsed_doc = parse_resume_from_docx(docx_bytes)
    d = Document(BytesIO(docx_bytes))
    paras = _all_document_paragraphs(d)
    exp_idx = parsed_doc.section_body_indices.get("professional_experience", [])

    print("experience indices count:", len(exp_idx))
    blocks = _group_experience_paragraph_indices(d, exp_idx)
    print("grouped role blocks:", len(blocks))

    for bi, block in enumerate(blocks):
        headers = []
        bullets = []
        empties = []
        for idx in block:
            p = paras[idx]
            t = _paragraph_text(p).strip()
            if not t:
                empties.append(idx)
            elif _is_bullet_paragraph(p):
                bullets.append(t[:50])
            else:
                headers.append(t[:60])
        print(f"\n--- Role block {bi + 1} ({len(block)} paras: {len(headers)} hdr, {len(bullets)} bullets, {len(empties)} empty) ---")
        for h in headers:
            print(f"  HDR: {h!r}")
        for e in empties:
            xml = paras[e]._element.xml
            b = re.search(r'w:before="(\d+)"', xml)
            a = re.search(r'w:after="(\d+)"', xml)
            print(f"  EMPTY para[{e}] spc={b.group(1) if b else 0}/{a.group(1) if a else 0}")
        print(f"  bullets: {len(bullets)}")
        if bullets:
            print(f"    first: {bullets[0]!r}")

    # All experience-region paragraphs including empties between blocks
    print("\n--- Full experience index walk (with gaps between blocks) ---")
    if exp_idx:
        lo, hi = min(exp_idx), max(exp_idx)
        # include a few paragraphs before/after section
        for idx in range(lo, min(hi + 5, len(paras))):
            if idx not in exp_idx and idx <= hi:
                # might be spacer between section header and body
                pass
        prev_block_end = None
        for idx in sorted(set(range(lo, hi + 1))):
            if idx >= len(paras):
                continue
            p = paras[idx]
            t = _paragraph_text(p).strip()
            in_exp = idx in exp_idx
            marker = ""
            if not t:
                marker = "EMPTY"
            elif _is_bullet_paragraph(p):
                marker = "BULLET"
            elif _is_experience_role_start(p, t):
                marker = "ROLE"
            else:
                marker = "META"
            gap = ""
            if prev_block_end is not None and idx - prev_block_end > 1:
                gap = f"  <<<< GAP: {idx - prev_block_end - 1} paras skipped >>>>"
            print(f"  [{idx:3d}] {marker:6s} in_exp={in_exp} | {t[:65]!r}{gap}")
            prev_block_end = idx


if __name__ == "__main__":
    main()
