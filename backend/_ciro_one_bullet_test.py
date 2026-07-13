"""Simulate tailored export with fewer bullets than template slots."""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from docx import Document

from app.services.docx_resume import (
    _all_document_paragraphs,
    _group_experience_paragraph_indices,
    _is_bullet_paragraph,
    _paragraph_text,
    apply_tailored_sections_to_docx,
    parse_resume_from_docx,
)

DOCX = Path(r"C:\Users\Jelix\Downloads\cv_ciro-fullstack (3).docx")
SPACERS = [29, 36, 43, 49, 55, 60, 65, 71, 75]


def build_one_bullet_per_role(experience: str) -> str:
    blocks = experience.split("\n\n")
    out: list[str] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        headers = [ln for ln in lines if not ln.strip().startswith(("-", "•", "●", "*"))]
        bullets = [ln for ln in lines if ln.strip().startswith(("-", "•", "●", "*"))]
        out.extend(headers)
        if bullets:
            out.append(bullets[0])
        out.append("")
    return "\n".join(out).strip()


def main() -> None:
    raw = DOCX.read_bytes()
    doc = parse_resume_from_docx(raw)
    p = doc.parsed

    slim_exp = build_one_bullet_per_role(p.professional_experience)
    print("original bullet lines:", sum(1 for l in p.professional_experience.splitlines() if l.strip().startswith(("-", "•"))))
    print("simulated bullet lines:", sum(1 for l in slim_exp.splitlines() if l.strip().startswith(("-", "•"))))

    result = apply_tailored_sections_to_docx(
        raw,
        contact=p.contact,
        professional_summary=p.professional_summary,
        professional_experience=slim_exp,
        skills=p.skills,
        education=p.education,
        other=p.other,
        section_header_indices=doc.section_header_indices,
        section_body_indices=doc.section_body_indices,
        contact_paragraph_indices=doc.contact_paragraph_indices,
        source_sections=p,
        original_filename=DOCX.name,
        experience_table_rows=doc.experience_table_rows,
    )
    if not result:
        print("export failed")
        return

    out_bytes, _ = result
    out_path = Path(__file__).with_name("_ciro_one_bullet_test.docx")
    out_path.write_bytes(out_bytes)

    orig = Document(BytesIO(raw))
    new = Document(BytesIO(out_bytes))
    op = _all_document_paragraphs(orig)
    np = _all_document_paragraphs(new)
    exp_idx = doc.section_body_indices.get("professional_experience", [])

    blocks_orig = _group_experience_paragraph_indices(orig, exp_idx)
    blocks_new = _group_experience_paragraph_indices(new, exp_idx)

    print("\n--- Per role: bullet slots vs filled (orig -> new) ---")
    for i, (bo, bn) in enumerate(zip(blocks_orig, blocks_new)):
        def count_bullets(block, paras):
            b = sum(1 for idx in block if _is_bullet_paragraph(paras[idx]))
            visible = sum(1 for idx in block if _is_bullet_paragraph(paras[idx]) and _paragraph_text(paras[idx]).strip())
            hidden = b - visible
            return b, visible, hidden
        ob, ov, oh = count_bullets(bo, op)
        nb, nv, nh = count_bullets(bn, np)
        print(f"  Role {i+1}: slots {ob} -> {nb}, visible bullets {ov} -> {nv}, empty/hidden bullet paras {oh} -> {nh}")

    print("\n--- Spacer paragraphs between jobs ---")
    for idx in SPACERS:
        if idx >= len(np):
            continue
        t = _paragraph_text(np[idx]).strip()
        xml = np[idx]._element.xml
        vanish = "w:vanish" in xml
        line = re.search(r'w:line="(\d+)"', xml)
        print(f"  [{idx}] empty={not t} vanish={vanish} line={line.group(1) if line else 'default'}")

    print("Wrote:", out_path)


if __name__ == "__main__":
    main()
