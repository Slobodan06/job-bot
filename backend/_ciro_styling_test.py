"""Test whether docx export preserves Ciro template spacing."""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from docx import Document

from app.services.docx_resume import (
    _all_document_paragraphs,
    _paragraph_text,
    apply_tailored_sections_to_docx,
    parse_resume_from_docx,
)

DOCX = Path(r"C:\Users\Jelix\Downloads\cv_ciro-fullstack (3).docx")
SPACERS = [29, 36, 43, 49, 55, 60, 65, 71, 75]


def spacing(xml: str) -> tuple[str, str]:
    b = re.search(r'w:before="(\d+)"', xml)
    a = re.search(r'w:after="(\d+)"', xml)
    return (b.group(1) if b else "0", a.group(1) if a else "0")


def main() -> None:
    raw = DOCX.read_bytes()
    doc = parse_resume_from_docx(raw)
    p = doc.parsed

    result = apply_tailored_sections_to_docx(
        raw,
        contact=p.contact,
        professional_summary=p.professional_summary,
        professional_experience=p.professional_experience,
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

    out_bytes, _name = result
    out_path = Path(__file__).with_name("_ciro_styling_test.docx")
    out_path.write_bytes(out_bytes)

    orig = Document(BytesIO(raw))
    new = Document(BytesIO(out_bytes))
    op = _all_document_paragraphs(orig)
    np = _all_document_paragraphs(new)
    print("paragraph count orig/new:", len(op), len(np))

    print("\n--- Job spacer paragraphs (between roles) ---")
    ok = True
    for idx in SPACERS:
        if idx >= len(op) or idx >= len(np):
            continue
        ot = _paragraph_text(op[idx]).strip()
        nt = _paragraph_text(np[idx]).strip()
        ob, oa = spacing(op[idx]._element.xml)
        nb, na = spacing(np[idx]._element.xml)
        match = (not ot and not nt and ob == nb and oa == na)
        if not match:
            ok = False
        print(
            f"  [{idx}] empty {not ot}->{not nt} spc {ob}/{oa}->{nb}/{na} preserved={match}"
        )

    print("\n--- Skills paragraphs 9-18 spacing ---")
    for idx in range(9, 19):
        if idx >= len(op) or idx >= len(np):
            continue
        ob, oa = spacing(op[idx]._element.xml)
        nb, na = spacing(np[idx]._element.xml)
        match = ob == nb and oa == na
        if not match:
            ok = False
        print(f"  [{idx}] spc {ob}/{oa}->{nb}/{na} preserved={match}")

    print("\nOVERALL spacing preserved:", ok)
    print("Wrote:", out_path)


if __name__ == "__main__":
    main()
