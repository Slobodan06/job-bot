"""
Professional resume PDF layouts (ReportLab + embedded FiraGO).
Members choose one exclusive template via /api/cv-templates; PDF export uses that layout.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from io import BytesIO
from secrets import randbelow
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.pdf_fonts import register_reportlab_fira_fonts
from app.services.pdf_resume import (
    MODERN_CONTENT_WIDTH,
    MODERN_MARGIN_BOTTOM,
    MODERN_MARGIN_LR,
    MODERN_MARGIN_TOP,
    build_tailored_resume_pdf,
)
from app.services.pdf_text_util import sanitize_for_pdf


def _para_markup(text: str) -> str:
    t = sanitize_for_pdf(text or "")
    t = escape(t)
    return re.sub(r"\r\n|\r|\n", "<br/>", t)


def _styles(accent_hex: str = "#0f7669") -> tuple[str, str, ParagraphStyle, ParagraphStyle, ParagraphStyle]:
    body_f, head_f = register_reportlab_fira_fonts()
    base = getSampleStyleSheet()
    ink = colors.HexColor("#0f172a")
    muted = colors.HexColor("#64748b")
    accent = colors.HexColor(accent_hex)
    body = ParagraphStyle(
        "TBody",
        parent=base["Normal"],
        fontName=body_f,
        fontSize=9.5,
        leading=13,
        textColor=ink,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )
    body_sm = ParagraphStyle(
        "TBodySm",
        parent=body,
        fontSize=8.5,
        leading=12,
    )
    heading = ParagraphStyle(
        "THead",
        parent=base["Heading2"],
        fontName=head_f,
        fontSize=8,
        leading=11,
        textColor=accent,
        spaceBefore=10,
        spaceAfter=4,
        alignment=TA_LEFT,
    )
    return body_f, head_f, body, body_sm, heading


def _section_block(title: str, content: str, heading: ParagraphStyle, body: ParagraphStyle) -> list:
    c = (content or "").strip()
    if not c:
        return []
    return [Paragraph(_para_markup(title.upper()), heading), Paragraph(_para_markup(c), body), Spacer(1, 6)]


def build_clean_classic(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    return build_tailored_resume_pdf(
        contact=contact,
        professional_summary=professional_summary,
        professional_experience=professional_experience,
        skills=skills,
        education=education,
        other=other,
    )


def build_executive_band(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    body_f, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    band = colors.HexColor("#15232f")
    white = colors.white
    name_st = ParagraphStyle(
        "ExecName",
        fontName=head_f,
        fontSize=17,
        leading=20,
        textColor=white,
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    sub_st = ParagraphStyle(
        "ExecSub",
        fontName=body_f,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#c5dae6"),
        alignment=TA_CENTER,
    )
    raw = sanitize_for_pdf(contact).strip().split("\n")
    name = raw[0] if raw else " "
    sub = "<br/>".join(escape(x) for x in raw[1:]) if len(raw) > 1 else "&nbsp;"
    hdr = Table(
        [[Paragraph(escape(name), name_st)], [Paragraph(sub, sub_st)]],
        colWidths=[6.6 * inch],
    )
    hdr.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), band),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story: list = [hdr, Spacer(1, 10)]
    for block in (
        _section_block("PROFESSIONAL SUMMARY", professional_summary, heading, body),
        _section_block("PROFESSIONAL EXPERIENCE", professional_experience, heading, body),
        _section_block("SKILLS", skills, heading, body_sm),
        _section_block("EDUCATION", education, heading, body_sm),
        _section_block("ADDITIONAL", other, heading, body_sm),
    ):
        story.extend(block)
    if len(story) <= 2:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_two_column(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    left_bits = ["<b><font color='#0f172a'>PROFILE &amp; SKILLS</font></b>", "<br/>"]
    if contact.strip():
        left_bits.append(_para_markup(contact))
        left_bits.append("<br/><br/>")
    left_bits.append(f"<b><font color='#0f172a'>SKILLS</font></b><br/>{_para_markup(skills) if skills.strip() else '—'}")
    if education.strip():
        left_bits.append("<br/><br/><b><font color='#0f172a'>EDUCATION</font></b><br/>")
        left_bits.append(_para_markup(education))
    left_cell = Paragraph("".join(left_bits), body_sm)

    right_story: list = []
    for block in (
        _section_block("PROFESSIONAL SUMMARY", professional_summary, heading, body),
        _section_block("PROFESSIONAL EXPERIENCE", professional_experience, heading, body),
        _section_block("ADDITIONAL", other, heading, body_sm),
    ):
        right_story.extend(block)
    if not right_story:
        right_story = [Paragraph(_para_markup("(No main content)"), body)]
    right_inner = Table([[x] for x in right_story], colWidths=[4.55 * inch])
    right_inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    outer = Table([[left_cell, right_inner]], colWidths=[2.15 * inch, 4.85 * inch])
    outer.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef4f8")),
                ("BACKGROUND", (1, 0), (1, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 14),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
                ("LINEAFTER", (0, 0), (0, -1), 1, colors.HexColor("#cbd5e1")),
            ]
        )
    )
    story = [outer]
    doc.build(story)
    return buf.getvalue()


def build_navy_sidebar(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    navy = colors.HexColor("#1e3a5f")
    w = colors.white
    side_body = ParagraphStyle("SideB", parent=body_sm, fontName=head_f, textColor=w, fontSize=9, leading=13)
    left_parts: list[str] = ["<b><font size='12'>CONTACT</font></b><br/><br/>"]
    left_parts.append(_para_markup(contact) if contact.strip() else "—")
    left_parts.append("<br/><br/><b><font size='12'>SKILLS</font></b><br/><br/>")
    left_parts.append(_para_markup(skills) if skills.strip() else "—")
    if education.strip():
        left_parts.append("<br/><br/><b><font size='12'>EDUCATION</font></b><br/><br/>")
        left_parts.append(_para_markup(education))
    left = Paragraph("".join(left_parts), side_body)

    rh = ParagraphStyle("RightH", parent=heading, textColor=colors.HexColor("#1e3a5f"), fontSize=12)
    rb = ParagraphStyle("RightB", parent=body, alignment=TA_JUSTIFY)
    right: list = []
    for block in (
        _section_block("PROFILE / SUMMARY", professional_summary, rh, rb),
        _section_block("EXPERIENCE", professional_experience, rh, rb),
        _section_block("OTHER", other, rh, rb),
    ):
        right.extend(block)
    if not right:
        right = [Paragraph(_para_markup("(No content)"), rb)]
    right_inner = Table([[x] for x in right], colWidths=[4.95 * inch])
    right_inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    outer = Table([[left, right_inner]], colWidths=[2.05 * inch, 4.95 * inch])
    outer.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), navy),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, -1), 14),
                ("RIGHTPADDING", (0, 0), (0, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    story = [outer]
    doc.build(story)
    return buf.getvalue()


def build_bordered_cards(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    story: list = []
    if contact.strip():
        story.append(
            Table(
                [[Paragraph(_para_markup(contact), ParagraphStyle("c", parent=body, alignment=TA_CENTER, fontName=head_f, fontSize=12))]],
                colWidths=[6.5 * inch],
            )
        )
        story[-1].setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#334155")),
                    ("TOPPADDING", (0, 0), (-1, -1), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ]
            )
        )
        story.append(Spacer(1, 14))

    def card(title: str, content: str) -> None:
        if not (content or "").strip():
            return
        inner = [
            [Paragraph(_para_markup(f"<b>{escape(title)}</b>"), heading)],
            [Paragraph(_para_markup(content), body)],
        ]
        t = Table(inner, colWidths=[6.5 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#94a3b8")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 12))

    card("PROFESSIONAL SUMMARY", professional_summary)
    card("PROFESSIONAL EXPERIENCE", professional_experience)
    card("SKILLS", skills)
    card("EDUCATION", education)
    card("ADDITIONAL", other)
    if len(story) == 0:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_timeline_accent(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    accent = colors.HexColor("#0d9488")
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("topc", parent=body, fontName=head_f, fontSize=13, leading=18)))
        story.append(Spacer(1, 8))
        story.append(Table([[""]], colWidths=[6.2 * inch], rowHeights=[2]))
        story[-1].setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 3, accent)]))
        story.append(Spacer(1, 16))

    def sec(title: str, content: str) -> None:
        if not (content or "").strip():
            return
        combined = Paragraph(
            f"<b><font color='#0f7669'>{escape(title)}</font></b><br/>{_para_markup(content)}",
            body,
        )
        # Single-column + LINEBEFORE avoids ReportLab two-column height bugs with tiny accent cells.
        row = Table([[combined]], colWidths=[6.5 * inch])
        row.setStyle(
            TableStyle(
                [
                    ("LINEBEFORE", (0, 0), (0, 0), 4, accent),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ]
            )
        )
        story.append(row)
        story.append(Spacer(1, 6))

    sec("SUMMARY", professional_summary)
    sec("EXPERIENCE", professional_experience)
    sec("SKILLS", skills)
    sec("EDUCATION", education)
    sec("OTHER", other)
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_dense_modern(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    h2 = ParagraphStyle("d2", parent=heading, fontSize=9, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#64748b"), fontName=head_f)
    b2 = ParagraphStyle("db2", parent=body_sm, fontSize=9, leading=12.5, alignment=TA_JUSTIFY)
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("dn", parent=body, fontName=head_f, fontSize=11, leading=15)))
        story.append(Spacer(1, 6))
    for title, content in (
        ("SUMMARY", professional_summary),
        ("EXPERIENCE", professional_experience),
        ("SKILLS", skills),
        ("EDUCATION", education),
        ("OTHER", other),
    ):
        if not (content or "").strip():
            continue
        story.append(Paragraph(escape(title), h2))
        story.append(
            Table(
                [[Paragraph(_para_markup(content), b2)]],
                colWidths=[6.7 * inch],
            )
        )
        story[-1].setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0"))]))
        story.append(Spacer(1, 8))
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_minimal_serif(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    story: list = []
    if contact.strip():
        story.append(
            Paragraph(
                _para_markup(contact),
                ParagraphStyle("msName", parent=body, fontName=head_f, fontSize=16, leading=20, alignment=TA_CENTER),
            )
        )
        story.append(Spacer(1, 6))
        story.append(Table([[""]], colWidths=[5.8 * inch], rowHeights=[1]))
        story[-1].setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1"))]))
        story.append(Spacer(1, 18))
    h = ParagraphStyle("msH", parent=heading, fontSize=10, textColor=colors.HexColor("#475569"), spaceBefore=10)
    for title, content in (
        ("SUMMARY", professional_summary),
        ("EXPERIENCE", professional_experience),
        ("SKILLS", skills),
        ("EDUCATION", education),
        ("OTHER", other),
    ):
        story.extend(_section_block(title, content, h, body_sm))
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_corporate_blue(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    blue = colors.HexColor("#1d4ed8")
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("cbC", parent=body, fontName=head_f, fontSize=13)))
        story.append(Spacer(1, 8))
    story.append(Table([[""]], colWidths=[6.5 * inch], rowHeights=[3]))
    story[-1].setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), blue)]))
    story.append(Spacer(1, 14))
    cb_h = ParagraphStyle("cbH", parent=heading, textColor=blue, fontSize=11, fontName=head_f)
    for title, content in (
        ("PROFESSIONAL SUMMARY", professional_summary),
        ("EXPERIENCE", professional_experience),
        ("SKILLS", skills),
        ("EDUCATION", education),
        ("ADDITIONAL", other),
    ):
        story.extend(_section_block(title, content, cb_h, body))
    if len(story) <= 2:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_warm_accent(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    accent = colors.HexColor("#c2410c")
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("waC", parent=body, fontName=head_f, fontSize=12)))
        story.append(Spacer(1, 12))
    wa_h = ParagraphStyle("waH", parent=heading, textColor=accent, fontSize=10, fontName=head_f)
    for title, content in (
        ("PROFILE", professional_summary),
        ("EXPERIENCE", professional_experience),
        ("SKILLS", skills),
        ("EDUCATION", education),
        ("OTHER", other),
    ):
        if not (content or "").strip():
            continue
        row = Table(
            [
                [
                    Paragraph(f"<b>{escape(title)}</b>", wa_h),
                    Paragraph(_para_markup(content), body_sm),
                ]
            ],
            colWidths=[1.35 * inch, 5.15 * inch],
        )
        row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#fed7aa")),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(row)
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_classic_tinted(
    *,
    accent_hex: str = "#0d9488",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    accent = colors.HexColor(accent_hex)
    h = ParagraphStyle("clH", parent=heading, textColor=accent, fontSize=11, fontName=head_f)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("clC", parent=body, fontName=head_f, fontSize=12)))
        story.append(Spacer(1, 14))
    for title, content in (
        ("PROFESSIONAL SUMMARY", professional_summary),
        ("PROFESSIONAL EXPERIENCE", professional_experience),
        ("SKILLS", skills),
        ("EDUCATION", education),
        ("ADDITIONAL", other),
    ):
        story.extend(_section_block(title, content, h, body_sm if title in ("SKILLS", "EDUCATION", "ADDITIONAL") else body))
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_executive_colored(
    *,
    band_hex: str = "#15232f",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    body_f, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    band = colors.HexColor(band_hex)
    name_st = ParagraphStyle("ExecName", fontName=head_f, fontSize=17, leading=20, textColor=colors.white, alignment=TA_CENTER, spaceAfter=4)
    sub_st = ParagraphStyle("ExecSub", fontName=body_f, fontSize=9, leading=12, textColor=colors.HexColor("#c5dae6"), alignment=TA_CENTER)
    raw = sanitize_for_pdf(contact).strip().split("\n")
    name = raw[0] if raw else " "
    sub = "<br/>".join(escape(x) for x in raw[1:]) if len(raw) > 1 else "&nbsp;"
    hdr = Table([[Paragraph(escape(name), name_st)], [Paragraph(sub, sub_st)]], colWidths=[6.6 * inch])
    hdr.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), band), ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 14), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story: list = [hdr, Spacer(1, 10)]
    for block in (
        _section_block("PROFESSIONAL SUMMARY", professional_summary, heading, body),
        _section_block("PROFESSIONAL EXPERIENCE", professional_experience, heading, body),
        _section_block("SKILLS", skills, heading, body_sm),
        _section_block("EDUCATION", education, heading, body_sm),
        _section_block("ADDITIONAL", other, heading, body_sm),
    ):
        story.extend(block)
    if len(story) <= 2:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_navy_colored(
    *,
    sidebar_hex: str = "#1e3a5f",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    return build_navy_sidebar(
        contact=contact,
        professional_summary=professional_summary,
        professional_experience=professional_experience,
        skills=skills,
        education=education,
        other=other,
    ) if sidebar_hex == "#1e3a5f" else _build_navy_colored_impl(
        sidebar_hex=sidebar_hex,
        contact=contact,
        professional_summary=professional_summary,
        professional_experience=professional_experience,
        skills=skills,
        education=education,
        other=other,
    )


def _build_navy_colored_impl(
    *,
    sidebar_hex: str,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    navy = colors.HexColor(sidebar_hex)
    side_body = ParagraphStyle("SideB", parent=body_sm, fontName=head_f, textColor=colors.white, fontSize=9, leading=13)
    left_parts = ["<b><font size='12'>CONTACT</font></b><br/><br/>", _para_markup(contact) if contact.strip() else "—", "<br/><br/><b><font size='12'>SKILLS</font></b><br/><br/>", _para_markup(skills) if skills.strip() else "—"]
    if education.strip():
        left_parts.extend(["<br/><br/><b><font size='12'>EDUCATION</font></b><br/><br/>", _para_markup(education)])
    left = Paragraph("".join(left_parts), side_body)
    rh = ParagraphStyle("RightH", parent=heading, textColor=navy, fontSize=12)
    rb = ParagraphStyle("RightB", parent=body, alignment=TA_JUSTIFY)
    right: list = []
    for block in (_section_block("PROFILE / SUMMARY", professional_summary, rh, rb), _section_block("EXPERIENCE", professional_experience, rh, rb), _section_block("OTHER", other, rh, rb)):
        right.extend(block)
    if not right:
        right = [Paragraph(_para_markup("(No content)"), rb)]
    right_inner = Table([[x] for x in right], colWidths=[4.95 * inch])
    right_inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    outer = Table([[left, right_inner]], colWidths=[2.05 * inch, 4.95 * inch])
    outer.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), navy), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, -1), 14), ("RIGHTPADDING", (0, 0), (0, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
    doc.build([outer])
    return buf.getvalue()


def build_two_column_tinted(
    *,
    sidebar_hex: str = "#eef4f8",
    border_hex: str = "#cbd5e1",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    left_bits = ["<b><font color='#0f172a'>PROFILE &amp; SKILLS</font></b>", "<br/>"]
    if contact.strip():
        left_bits.extend([_para_markup(contact), "<br/><br/>"])
    left_bits.append(f"<b><font color='#0f172a'>SKILLS</font></b><br/>{_para_markup(skills) if skills.strip() else '—'}")
    if education.strip():
        left_bits.extend(["<br/><br/><b><font color='#0f172a'>EDUCATION</font></b><br/>", _para_markup(education)])
    left_cell = Paragraph("".join(left_bits), body_sm)
    right_story: list = []
    for block in (_section_block("PROFESSIONAL SUMMARY", professional_summary, heading, body), _section_block("PROFESSIONAL EXPERIENCE", professional_experience, heading, body), _section_block("ADDITIONAL", other, heading, body_sm)):
        right_story.extend(block)
    if not right_story:
        right_story = [Paragraph(_para_markup("(No main content)"), body)]
    right_inner = Table([[x] for x in right_story], colWidths=[4.55 * inch])
    right_inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    outer = Table([[left_cell, right_inner]], colWidths=[2.15 * inch, 4.85 * inch])
    outer.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor(sidebar_hex)), ("BACKGROUND", (1, 0), (1, -1), colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14), ("TOPPADDING", (0, 0), (-1, -1), 14), ("BOTTOMPADDING", (0, 0), (-1, -1), 14), ("LINEAFTER", (0, 0), (0, -1), 1, colors.HexColor(border_hex))]))
    doc.build([outer])
    return buf.getvalue()


def build_timeline_colored(
    *,
    accent_hex: str = "#0d9488",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    accent = colors.HexColor(accent_hex)
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("topc", parent=body, fontName=head_f, fontSize=13, leading=18)))
        story.append(Spacer(1, 8))
        story.append(Table([[""]], colWidths=[6.2 * inch], rowHeights=[2]))
        story[-1].setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 3, accent)]))
        story.append(Spacer(1, 16))

    def sec(title: str, content: str) -> None:
        if not (content or "").strip():
            return
        combined = Paragraph(f"<b><font color='{accent_hex}'>{escape(title)}</font></b><br/>{_para_markup(content)}", body)
        row = Table([[combined]], colWidths=[6.5 * inch])
        row.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, 0), 4, accent), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 12)]))
        story.append(row)
        story.append(Spacer(1, 6))

    sec("SUMMARY", professional_summary)
    sec("EXPERIENCE", professional_experience)
    sec("SKILLS", skills)
    sec("EDUCATION", education)
    sec("OTHER", other)
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_bordered_tinted(
    *,
    accent_hex: str = "#334155",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    accent = colors.HexColor(accent_hex)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    story: list = []
    if contact.strip():
        story.append(Table([[Paragraph(_para_markup(contact), ParagraphStyle("c", parent=body, alignment=TA_CENTER, fontName=head_f, fontSize=12))]], colWidths=[6.5 * inch]))
        story[-1].setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, accent), ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
        story.append(Spacer(1, 14))

    def card(title: str, content: str) -> None:
        if not (content or "").strip():
            return
        inner = [[Paragraph(_para_markup(f"<b>{escape(title)}</b>"), heading)], [Paragraph(_para_markup(content), body)]]
        t = Table(inner, colWidths=[6.5 * inch])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, accent), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")), ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12)]))
        story.append(t)
        story.append(Spacer(1, 12))

    card("PROFESSIONAL SUMMARY", professional_summary)
    card("PROFESSIONAL EXPERIENCE", professional_experience)
    card("SKILLS", skills)
    card("EDUCATION", education)
    card("ADDITIONAL", other)
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_dense_tinted(
    *,
    accent_hex: str = "#64748b",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    h2 = ParagraphStyle("d2", parent=heading, fontSize=9, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor(accent_hex), fontName=head_f)
    b2 = ParagraphStyle("db2", parent=body_sm, fontSize=9, leading=12.5, alignment=TA_JUSTIFY)
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("dn", parent=body, fontName=head_f, fontSize=11, leading=15)))
        story.append(Spacer(1, 6))
    for title, content in (("SUMMARY", professional_summary), ("EXPERIENCE", professional_experience), ("SKILLS", skills), ("EDUCATION", education), ("OTHER", other)):
        if not (content or "").strip():
            continue
        story.append(Paragraph(escape(title), h2))
        story.append(Table([[Paragraph(_para_markup(content), b2)]], colWidths=[6.7 * inch]))
        story[-1].setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0"))]))
        story.append(Spacer(1, 8))
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_minimal_tinted(
    *,
    accent_hex: str = "#475569",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("msName", parent=body, fontName=head_f, fontSize=16, leading=20, alignment=TA_CENTER)))
        story.append(Spacer(1, 6))
        story.append(Table([[""]], colWidths=[5.8 * inch], rowHeights=[1]))
        story[-1].setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor(accent_hex))]))
        story.append(Spacer(1, 18))
    h = ParagraphStyle("msH", parent=heading, fontSize=10, textColor=colors.HexColor(accent_hex), spaceBefore=10)
    for title, content in (("SUMMARY", professional_summary), ("EXPERIENCE", professional_experience), ("SKILLS", skills), ("EDUCATION", education), ("OTHER", other)):
        story.extend(_section_block(title, content, h, body_sm))
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_corporate_colored(
    *,
    rule_hex: str = "#1d4ed8",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    blue = colors.HexColor(rule_hex)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("cbC", parent=body, fontName=head_f, fontSize=13)))
        story.append(Spacer(1, 8))
    story.append(Table([[""]], colWidths=[6.5 * inch], rowHeights=[3]))
    story[-1].setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), blue)]))
    story.append(Spacer(1, 14))
    cb_h = ParagraphStyle("cbH", parent=heading, textColor=blue, fontSize=11, fontName=head_f)
    for title, content in (("PROFESSIONAL SUMMARY", professional_summary), ("EXPERIENCE", professional_experience), ("SKILLS", skills), ("EDUCATION", education), ("ADDITIONAL", other)):
        story.extend(_section_block(title, content, cb_h, body))
    if len(story) <= 2:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_warm_colored(
    *,
    accent_hex: str = "#c2410c",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    accent = colors.HexColor(accent_hex)
    story: list = []
    if contact.strip():
        story.append(Paragraph(_para_markup(contact), ParagraphStyle("waC", parent=body, fontName=head_f, fontSize=12)))
        story.append(Spacer(1, 12))
    wa_h = ParagraphStyle("waH", parent=heading, textColor=accent, fontSize=10, fontName=head_f)
    border = colors.HexColor("#fed7aa") if accent_hex.startswith("#c") or accent_hex.startswith("#d") else colors.HexColor("#fecaca")
    for title, content in (("PROFILE", professional_summary), ("EXPERIENCE", professional_experience), ("SKILLS", skills), ("EDUCATION", education), ("OTHER", other)):
        if not (content or "").strip():
            continue
        row = Table([[Paragraph(f"<b>{escape(title)}</b>", wa_h), Paragraph(_para_markup(content), body_sm)]], colWidths=[1.35 * inch, 5.15 * inch])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.5, border), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        story.append(row)
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def _contact_header(contact: str, body_f: str, head_f: str, accent_hex: str) -> list:
    story: list = []
    raw = sanitize_for_pdf(contact or "").strip()
    if not raw:
        return story
    lines = raw.split("\n")
    name_st = ParagraphStyle(
        "ModName",
        fontName=head_f,
        fontSize=16,
        leading=19,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=2,
    )
    sub_st = ParagraphStyle(
        "ModSub",
        fontName=body_f,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748b"),
    )
    story.append(Paragraph(_para_markup(lines[0]), name_st))
    if len(lines) > 1:
        story.append(Paragraph(_para_markup("\n".join(lines[1:])), sub_st))
    accent = colors.HexColor(accent_hex)
    story.append(Spacer(1, 6))
    story.append(Table([[""]], colWidths=[MODERN_CONTENT_WIDTH], rowHeights=[2]))
    story[-1].setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), accent)]))
    story.append(Spacer(1, 10))
    return story


def build_modern_stack(
    *,
    accent_hex: str = "#0d9488",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    body_f, head_f, body, body_sm, heading = _styles(accent_hex)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    accent = colors.HexColor(accent_hex)
    story = _contact_header(contact, body_f, head_f, accent_hex)
    for title, content, b in (
        ("Summary", professional_summary, body),
        ("Experience", professional_experience, body),
        ("Skills", skills, body_sm),
        ("Education", education, body_sm),
        ("Additional", other, body_sm),
    ):
        c = (content or "").strip()
        if not c:
            continue
        row = Table(
            [
                [
                    Paragraph(f"<b><font color='{accent_hex}'>{escape(title.upper())}</font></b>", heading),
                ],
                [Paragraph(_para_markup(c), b)],
            ],
            colWidths=[MODERN_CONTENT_WIDTH],
        )
        row.setStyle(
            TableStyle(
                [
                    ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(row)
        story.append(Spacer(1, 4))
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_modern_split(
    *,
    accent_hex: str = "#334155",
    sidebar_hex: str = "#f8fafc",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    _, head_f, body, body_sm, heading = _styles(accent_hex)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    accent = colors.HexColor(accent_hex)
    left_w = 2.25 * inch
    right_w = MODERN_CONTENT_WIDTH - left_w
    left_bits = [f"<b><font color='{accent_hex}'>CONTACT</font></b><br/><br/>"]
    left_bits.append(_para_markup(contact) if contact.strip() else "—")
    left_bits.append(f"<br/><br/><b><font color='{accent_hex}'>SKILLS</font></b><br/><br/>")
    left_bits.append(_para_markup(skills) if skills.strip() else "—")
    if education.strip():
        left_bits.append(f"<br/><br/><b><font color='{accent_hex}'>EDUCATION</font></b><br/><br/>")
        left_bits.append(_para_markup(education))
    left_cell = Paragraph("".join(left_bits), body_sm)

    right: list = []
    for block in (
        _section_block("Summary", professional_summary, heading, body),
        _section_block("Experience", professional_experience, heading, body),
        _section_block("Additional", other, heading, body_sm),
    ):
        right.extend(block)
    if not right:
        right = [Paragraph(_para_markup("(No content)"), body)]
    right_inner = Table([[x] for x in right], colWidths=[right_w])
    right_inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    outer = Table([[left_cell, right_inner]], colWidths=[left_w, right_w])
    outer.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor(sidebar_hex)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LINEAFTER", (0, 0), (0, -1), 1.5, accent),
            ]
        )
    )
    doc.build([outer])
    return buf.getvalue()


def build_modern_hero(
    *,
    accent_hex: str = "#1e293b",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    body_f, head_f, body, body_sm, heading = _styles(accent_hex)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    band = colors.HexColor(accent_hex)
    raw = sanitize_for_pdf(contact or "").strip().split("\n")
    name = raw[0] if raw else " "
    sub = "<br/>".join(escape(x) for x in raw[1:]) if len(raw) > 1 else "&nbsp;"
    name_st = ParagraphStyle("HeroName", fontName=head_f, fontSize=17, leading=20, textColor=colors.white, spaceAfter=3)
    sub_st = ParagraphStyle("HeroSub", fontName=body_f, fontSize=9, leading=12, textColor=colors.HexColor("#e2e8f0"))
    hdr = Table(
        [[Paragraph(escape(name), name_st)], [Paragraph(sub, sub_st)]],
        colWidths=[MODERN_CONTENT_WIDTH],
    )
    hdr.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), band),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )
    story: list = [hdr, Spacer(1, 10)]
    h = ParagraphStyle("HeroH", parent=heading, textColor=band, fontSize=8)
    for block in (
        _section_block("Summary", professional_summary, h, body),
        _section_block("Experience", professional_experience, h, body),
        _section_block("Skills", skills, h, body_sm),
        _section_block("Education", education, h, body_sm),
        _section_block("Additional", other, h, body_sm),
    ):
        story.extend(block)
    if len(story) <= 2:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_modern_pill(
    *,
    accent_hex: str = "#059669",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    body_f, head_f, body, body_sm, heading = _styles(accent_hex)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    accent = colors.HexColor(accent_hex)
    story = _contact_header(contact, body_f, head_f, accent_hex)

    def pill_section(title: str, content: str, b: ParagraphStyle) -> None:
        c = (content or "").strip()
        if not c:
            return
        label = Table(
            [[Paragraph(f"<b><font color='{accent_hex}'>{escape(title.upper())}</font></b>", heading)]],
            colWidths=[MODERN_CONTENT_WIDTH],
        )
        label.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
                ]
            )
        )
        story.append(label)
        story.append(Paragraph(_para_markup(c), b))
        story.append(Spacer(1, 6))

    pill_section("Summary", professional_summary, body)
    pill_section("Experience", professional_experience, body)
    pill_section("Skills", skills, body_sm)
    pill_section("Education", education, body_sm)
    pill_section("Additional", other, body_sm)
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def build_modern_line(
    *,
    accent_hex: str = "#6366f1",
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    body_f, head_f, body, body_sm, _heading = _styles(accent_hex)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
    )
    accent = colors.HexColor(accent_hex)
    muted = colors.HexColor("#94a3b8")
    story: list = []
    raw = sanitize_for_pdf(contact or "").strip()
    if raw:
        lines = raw.split("\n")
        story.append(
            Paragraph(
                _para_markup(lines[0]),
                ParagraphStyle("LineName", fontName=head_f, fontSize=15, leading=18, textColor=colors.HexColor("#0f172a")),
            )
        )
        if len(lines) > 1:
            story.append(Paragraph(_para_markup("\n".join(lines[1:])), ParagraphStyle("LineSub", parent=body_sm, textColor=colors.HexColor("#64748b"))))
        story.append(Spacer(1, 8))
        story.append(Table([[""]], colWidths=[MODERN_CONTENT_WIDTH], rowHeights=[0.5]))
        story[-1].setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, muted)]))
        story.append(Spacer(1, 10))

    title_st = ParagraphStyle("LineH", fontName=head_f, fontSize=7.5, leading=10, textColor=accent, spaceBefore=8, spaceAfter=3)

    def line_section(title: str, content: str, b: ParagraphStyle) -> None:
        c = (content or "").strip()
        if not c:
            return
        story.append(Paragraph(escape(title.upper()), title_st))
        story.append(Paragraph(_para_markup(c), b))
        story.append(Table([[""]], colWidths=[MODERN_CONTENT_WIDTH], rowHeights=[0.5]))
        story[-1].setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0"))]))
        story.append(Spacer(1, 4))

    line_section("Summary", professional_summary, body)
    line_section("Experience", professional_experience, body)
    line_section("Skills", skills, body_sm)
    line_section("Education", education, body_sm)
    line_section("Additional", other, body_sm)
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


_Builder = Callable[..., bytes]

# Legacy registry kept for imports; canonical catalog is template_catalog.py (40 templates).
TEMPLATE_REGISTRY: list[tuple[str, str, str, _Builder]] = []


def list_template_catalog() -> list[dict[str, str]]:
    from app.services.template_catalog import list_template_catalog as _list

    return _list()


def get_template_builder(key: str) -> tuple[str, str, _Builder]:
    from app.services.template_catalog import get_template_builder as _get

    return _get(key)


def build_template_pdf(
    template_key: str,
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> tuple[bytes, str, str]:
    from app.services.template_catalog import build_template_pdf as _build

    return _build(
        template_key,
        contact=contact,
        professional_summary=professional_summary,
        professional_experience=professional_experience,
        skills=skills,
        education=education,
        other=other,
    )


def pick_random_template() -> tuple[str, str, _Builder]:
    from app.services.template_catalog import _CATALOG

    i = randbelow(len(_CATALOG))
    key, label, _desc, fn, _accent, _layout = _CATALOG[i]
    return key, label, fn


def build_random_template_pdf(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> tuple[bytes, str, str]:
    """Returns (pdf_bytes, template_key, template_label)."""
    key, label, fn = pick_random_template()
    pdf = fn(
        contact=contact,
        professional_summary=professional_summary,
        professional_experience=professional_experience,
        skills=skills,
        education=education,
        other=other,
    )
    return pdf, key, label
