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
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.pdf_fonts import register_reportlab_fira_fonts
from app.services.pdf_resume import (
    MODERN_CONTENT_WIDTH,
    MODERN_MARGIN_BOTTOM,
    MODERN_MARGIN_LR,
    MODERN_MARGIN_TOP,
    build_scott_ats_professional_pdf,
    build_tailored_resume_pdf,
    format_contact_details_markup,
    format_contact_header_markup,
    format_contact_name_markup,
    parse_contact,
    parse_contact_header,
    _section_body_markup,
)
from app.services.pdf_text_util import sanitize_for_pdf


def _splittable_table(
    data,
    colWidths,
    style: TableStyle | None = None,
    **kwargs,
) -> Table:
    table = Table(data, colWidths=colWidths, splitInRow=1, **kwargs)
    if style is not None:
        table.setStyle(style)
    return table


def _build_framed_two_column_pdf(
    *,
    left_flowables: list,
    right_flowables: list,
    sidebar_bg: colors.Color | None = None,
    border_after_left: colors.Color | None = None,
    left_w: float = 2.15 * inch,
    gap: float = 0.05 * inch,
) -> bytes:
    """Side-by-side columns that can span multiple pages (right column continues on page 2+)."""
    buf = BytesIO()
    right_w = MODERN_CONTENT_WIDTH - left_w - gap
    frame_h = letter[1] - MODERN_MARGIN_TOP - MODERN_MARGIN_BOTTOM
    frame_y = MODERN_MARGIN_BOTTOM
    left_x = MODERN_MARGIN_LR
    right_x = MODERN_MARGIN_LR + left_w + gap

    def _on_page(canvas, doc) -> None:
        if sidebar_bg is None and border_after_left is None:
            return
        canvas.saveState()
        if sidebar_bg is not None:
            canvas.setFillColor(sidebar_bg)
            canvas.rect(
                left_x,
                MODERN_MARGIN_BOTTOM,
                left_w,
                frame_h,
                fill=1,
                stroke=0,
            )
        if border_after_left is not None:
            canvas.setStrokeColor(border_after_left)
            canvas.setLineWidth(1)
            canvas.line(
                left_x + left_w,
                MODERN_MARGIN_BOTTOM,
                left_x + left_w,
                MODERN_MARGIN_BOTTOM + frame_h,
            )
        canvas.restoreState()

    class TwoColDoc(BaseDocTemplate):
        def __init__(self) -> None:
            BaseDocTemplate.__init__(
                self,
                buf,
                pagesize=letter,
                leftMargin=MODERN_MARGIN_LR,
                rightMargin=MODERN_MARGIN_LR,
                topMargin=MODERN_MARGIN_TOP,
                bottomMargin=MODERN_MARGIN_BOTTOM,
            )
            left_frame = Frame(
                left_x,
                frame_y,
                left_w,
                frame_h,
                id="left",
                leftPadding=10,
                rightPadding=8,
                topPadding=10,
                bottomPadding=10,
            )
            right_frame = Frame(
                right_x,
                frame_y,
                right_w,
                frame_h,
                id="right",
                leftPadding=10,
                rightPadding=10,
                topPadding=10,
                bottomPadding=10,
            )
            self.addPageTemplates(
                [
                    PageTemplate(
                        id="TwoCol",
                        frames=[left_frame, right_frame],
                        onPage=_on_page,
                    )
                ]
            )

    doc = TwoColDoc()
    story = list(left_flowables) + [FrameBreak("right")] + list(right_flowables)
    doc.build(story)
    return buf.getvalue()


def _para_markup(text: str) -> str:
    t = sanitize_for_pdf(text or "")
    t = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", t)
    t = escape(t)
    return re.sub(r"\r\n|\r|\n", "<br/>", t)


def _contact_styles(
    body_f: str,
    head_f: str,
    *,
    name_size: int = 16,
    name_color: colors.Color | None = None,
    detail_color: colors.Color | None = None,
    headline_color: colors.Color | None = None,
    alignment: int = TA_LEFT,
) -> tuple[ParagraphStyle, ParagraphStyle, ParagraphStyle]:
    ink = name_color or colors.HexColor("#0f172a")
    muted = detail_color or colors.HexColor("#64748b")
    headline = headline_color or colors.HexColor("#475569")
    name_st = ParagraphStyle(
        "ContactName",
        fontName=head_f,
        fontSize=name_size,
        leading=name_size + 3,
        textColor=ink,
        alignment=alignment,
        spaceAfter=2,
    )
    headline_st = ParagraphStyle(
        "ContactHeadline",
        fontName=body_f,
        fontSize=10,
        leading=13,
        textColor=headline,
        alignment=alignment,
        spaceAfter=2,
    )
    detail_st = ParagraphStyle(
        "ContactDetail",
        fontName=body_f,
        fontSize=9,
        leading=12,
        textColor=muted,
        alignment=alignment,
        spaceAfter=4,
    )
    return name_st, headline_st, detail_st


def _append_contact_block(
    story: list,
    contact: str,
    *,
    body_f: str,
    head_f: str,
    name_size: int = 16,
    name_color: colors.Color | None = None,
    detail_color: colors.Color | None = None,
    headline_color: colors.Color | None = None,
    link_color: str = "#0d9488",
    alignment: int = TA_LEFT,
    trailing_spacer: float = 10,
) -> None:
    if not sanitize_for_pdf(contact or "").strip():
        return
    name_st, headline_st, detail_st = _contact_styles(
        body_f,
        head_f,
        name_size=name_size,
        name_color=name_color,
        detail_color=detail_color,
        headline_color=headline_color,
        alignment=alignment,
    )
    parsed = parse_contact(contact)
    name_link_color = link_color
    if name_color is not None:
        name_link_color = (
            f"#{int(name_color.red * 255):02x}"
            f"{int(name_color.green * 255):02x}"
            f"{int(name_color.blue * 255):02x}"
        )
    name_html = format_contact_name_markup(parsed, link_color=name_link_color)
    if name_html:
        story.append(Paragraph(name_html, name_st))
    if parsed.headline:
        story.append(Paragraph(escape(parsed.headline), headline_st))
    details_html = format_contact_details_markup(parsed, link_color=link_color)
    if details_html:
        story.append(Paragraph(details_html, detail_st))
    if trailing_spacer:
        story.append(Spacer(1, trailing_spacer))


def _contact_markup_for_table(
    contact: str,
    *,
    name_size: int = 12,
    name_color: str | None = None,
    headline_color: str = "#475569",
    detail_color: str = "#64748b",
) -> str:
    return format_contact_header_markup(
        contact,
        name_size=name_size,
        name_color=name_color,
        headline_color=headline_color,
        detail_color=detail_color,
    )


def _contact_centered_markup(contact: str, *, link_color: str = "#0d9488") -> str:
    parsed = parse_contact(contact)
    parts: list[str] = []
    if parsed.name:
        parts.append(format_contact_name_markup(parsed, link_color=link_color))
    if parsed.headline:
        parts.append(escape(parsed.headline))
    details_html = format_contact_details_markup(parsed, link_color=link_color)
    if details_html:
        parts.append(details_html)
    return "<br/>".join(parts)


def _section_content_markup(title: str, content: str) -> str:
    return _section_body_markup(title, content)


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
    return [
        Paragraph(_para_markup(title.upper()), heading),
        Paragraph(_section_content_markup(title, c), body),
        Spacer(1, 6),
    ]


def build_scott_ats_professional(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    return build_scott_ats_professional_pdf(
        contact=contact,
        professional_summary=professional_summary,
        professional_experience=professional_experience,
        skills=skills,
        education=education,
        other=other,
    )


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
    )
    header_html = format_contact_header_markup(
        contact,
        name_size=17,
        name_color="#ffffff",
        headline_color="#c5dae6",
        detail_color="#c5dae6",
        link_color="#93c5fd",
    )
    hdr = Table(
        [[Paragraph(header_html or "&nbsp;", name_st)]],
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
    body_f, head_f, body, body_sm, heading = _styles()
    left_flowables: list = [
        Paragraph("<b><font color='#0f172a'>PROFILE &amp; SKILLS</font></b>", body_sm),
        Spacer(1, 6),
    ]
    _append_contact_block(
        left_flowables,
        contact,
        body_f=body_f,
        head_f=head_f,
        name_size=10,
        trailing_spacer=10,
    )
    left_flowables.append(
        Paragraph(
            f"<b><font color='#0f172a'>SKILLS</font></b><br/>{_para_markup(skills) if skills.strip() else '—'}",
            body_sm,
        )
    )
    if education.strip():
        left_flowables.append(Spacer(1, 10))
        left_flowables.append(
            Paragraph(
                f"<b><font color='#0f172a'>EDUCATION</font></b><br/>{_para_markup(education)}",
                body_sm,
            )
        )

    right_flowables: list = []
    for block in (
        _section_block("PROFESSIONAL SUMMARY", professional_summary, heading, body),
        _section_block("PROFESSIONAL EXPERIENCE", professional_experience, heading, body),
        _section_block("ADDITIONAL", other, heading, body_sm),
    ):
        right_flowables.extend(block)
    if not right_flowables:
        right_flowables = [Paragraph(_para_markup("(No main content)"), body)]

    return _build_framed_two_column_pdf(
        left_flowables=left_flowables,
        right_flowables=right_flowables,
        sidebar_bg=colors.HexColor("#eef4f8"),
        border_after_left=colors.HexColor("#cbd5e1"),
        left_w=2.15 * inch,
    )


def build_navy_sidebar(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    return _build_navy_colored_impl(
        sidebar_hex="#1e3a5f",
        contact=contact,
        professional_summary=professional_summary,
        professional_experience=professional_experience,
        skills=skills,
        education=education,
        other=other,
    )


def build_bordered_cards(
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
    story: list = []
    if contact.strip():
        story.append(
            Table(
                [[Paragraph(
                    _contact_centered_markup(contact),
                    ParagraphStyle("c", parent=body, alignment=TA_CENTER, fontName=body_f, fontSize=12, leading=15),
                )]],
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
            [Paragraph(_section_content_markup(title, content), body)],
        ]
        t = _splittable_table(inner, colWidths=[6.5 * inch])
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
    accent = colors.HexColor("#0d9488")
    story: list = []
    _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=13, trailing_spacer=8)
    if sanitize_for_pdf(contact or "").strip():
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
        row = _splittable_table([[combined]], colWidths=[6.5 * inch])
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
    h2 = ParagraphStyle("d2", parent=heading, fontSize=9, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#64748b"), fontName=head_f)
    b2 = ParagraphStyle("db2", parent=body_sm, fontSize=9, leading=12.5, alignment=TA_JUSTIFY)
    story: list = []
    _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=11, trailing_spacer=6)
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
            _splittable_table(
                [[Paragraph(_section_content_markup(title, content), b2)]],
                colWidths=[6.7 * inch],
                style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0"))]),
            )
        )
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
    story: list = []
    _append_contact_block(
        story,
        contact,
        body_f=body_f,
        head_f=head_f,
        name_size=16,
        alignment=TA_CENTER,
        trailing_spacer=6,
    )
    if sanitize_for_pdf(contact or "").strip():
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
    blue = colors.HexColor("#1d4ed8")
    story: list = []
    _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=13, trailing_spacer=8)
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
    accent = colors.HexColor("#c2410c")
    story: list = []
    _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=12, trailing_spacer=12)
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
        row = _splittable_table(
            [
                [
                    Paragraph(f"<b>{escape(title)}</b>", wa_h),
                    Paragraph(_section_content_markup(title, content), body_sm),
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
    body_f, head_f, body, body_sm, heading = _styles()
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
    _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=12, trailing_spacer=14)
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
    parsed_contact = parse_contact(contact)
    name_html = format_contact_name_markup(parsed_contact, link_color="#c5dae6")
    sub_parts: list[str] = []
    if parsed_contact.headline:
        sub_parts.append(escape(parsed_contact.headline))
    details_html = format_contact_details_markup(parsed_contact, link_color="#93c5fd")
    if details_html:
        sub_parts.append(details_html)
    sub = "<br/>".join(sub_parts) if sub_parts else "&nbsp;"
    hdr = Table(
        [[Paragraph(name_html or "&nbsp;", name_st)], [Paragraph(sub, sub_st)]],
        colWidths=[6.6 * inch],
    )
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
    return _build_navy_colored_impl(
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
    body_f, head_f, body, body_sm, heading = _styles()
    navy = colors.HexColor(sidebar_hex)
    side_body = ParagraphStyle(
        "SideB", parent=body_sm, fontName=head_f, textColor=colors.white, fontSize=9, leading=13
    )
    left_flowables: list = [
        Paragraph("<b><font size='12'>CONTACT</font></b>", side_body),
        Spacer(1, 6),
    ]
    _append_contact_block(
        left_flowables,
        contact,
        body_f=body_f,
        head_f=head_f,
        name_size=10,
        name_color=colors.white,
        detail_color=colors.HexColor("#e2e8f0"),
        headline_color=colors.HexColor("#cbd5e1"),
        link_color="#93c5fd",
        trailing_spacer=10,
    )
    left_flowables.append(
        Paragraph(
            f"<b><font size='12'>SKILLS</font></b><br/><br/>{_para_markup(skills) if skills.strip() else '—'}",
            side_body,
        )
    )
    if education.strip():
        left_flowables.extend(
            [
                Spacer(1, 10),
                Paragraph(
                    f"<b><font size='12'>EDUCATION</font></b><br/><br/>{_section_content_markup('Education', education)}",
                    side_body,
                ),
            ]
        )
    rh = ParagraphStyle("RightH", parent=heading, textColor=navy, fontSize=12)
    rb = ParagraphStyle("RightB", parent=body, alignment=TA_JUSTIFY)
    right_flowables: list = []
    for block in (
        _section_block("PROFILE / SUMMARY", professional_summary, rh, rb),
        _section_block("EXPERIENCE", professional_experience, rh, rb),
        _section_block("OTHER", other, rh, rb),
    ):
        right_flowables.extend(block)
    if not right_flowables:
        right_flowables = [Paragraph(_para_markup("(No content)"), rb)]
    return _build_framed_two_column_pdf(
        left_flowables=left_flowables,
        right_flowables=right_flowables,
        sidebar_bg=navy,
        left_w=2.05 * inch,
    )


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
    body_f, head_f, body, body_sm, heading = _styles()
    left_flowables: list = [
        Paragraph("<b><font color='#0f172a'>PROFILE &amp; SKILLS</font></b>", body_sm),
        Spacer(1, 6),
    ]
    _append_contact_block(
        left_flowables,
        contact,
        body_f=body_f,
        head_f=head_f,
        name_size=10,
        trailing_spacer=10,
    )
    left_flowables.append(
        Paragraph(
            f"<b><font color='#0f172a'>SKILLS</font></b><br/>{_para_markup(skills) if skills.strip() else '—'}",
            body_sm,
        )
    )
    if education.strip():
        left_flowables.extend(
            [
                Spacer(1, 10),
                Paragraph(
                    f"<b><font color='#0f172a'>EDUCATION</font></b><br/>{_para_markup(education)}",
                    body_sm,
                ),
            ]
        )
    right_flowables: list = []
    for block in (
        _section_block("PROFESSIONAL SUMMARY", professional_summary, heading, body),
        _section_block("PROFESSIONAL EXPERIENCE", professional_experience, heading, body),
        _section_block("ADDITIONAL", other, heading, body_sm),
    ):
        right_flowables.extend(block)
    if not right_flowables:
        right_flowables = [Paragraph(_para_markup("(No main content)"), body)]
    return _build_framed_two_column_pdf(
        left_flowables=left_flowables,
        right_flowables=right_flowables,
        sidebar_bg=colors.HexColor(sidebar_hex),
        border_after_left=colors.HexColor(border_hex),
        left_w=2.15 * inch,
    )


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
    accent = colors.HexColor(accent_hex)
    story: list = []
    _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=13, trailing_spacer=8)
    if sanitize_for_pdf(contact or "").strip():
        story.append(Table([[""]], colWidths=[6.2 * inch], rowHeights=[2]))
        story[-1].setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 3, accent)]))
        story.append(Spacer(1, 16))

    def sec(title: str, content: str) -> None:
        if not (content or "").strip():
            return
        combined = Paragraph(f"<b><font color='{accent_hex}'>{escape(title)}</font></b><br/>{_para_markup(content)}", body)
        row = _splittable_table([[combined]], colWidths=[6.5 * inch])
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
    body_f, head_f, body, body_sm, heading = _styles()
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
        story.append(
            Table(
                [[Paragraph(
                    _contact_centered_markup(contact),
                    ParagraphStyle("c", parent=body, alignment=TA_CENTER, fontName=body_f, fontSize=12, leading=15),
                )]],
                colWidths=[6.5 * inch],
            )
        )
        story[-1].setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, accent), ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
        story.append(Spacer(1, 14))

    def card(title: str, content: str) -> None:
        if not (content or "").strip():
            return
        inner = [
            [Paragraph(_para_markup(f"<b>{escape(title)}</b>"), heading)],
            [Paragraph(_section_content_markup(title, content), body)],
        ]
        t = _splittable_table(
            inner,
            colWidths=[6.5 * inch],
            style=TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, accent),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ]
            ),
        )
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
    h2 = ParagraphStyle("d2", parent=heading, fontSize=9, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor(accent_hex), fontName=head_f)
    b2 = ParagraphStyle("db2", parent=body_sm, fontSize=9, leading=12.5, alignment=TA_JUSTIFY)
    story: list = []
    _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=11, trailing_spacer=6)
    for title, content in (("SUMMARY", professional_summary), ("EXPERIENCE", professional_experience), ("SKILLS", skills), ("EDUCATION", education), ("OTHER", other)):
        if not (content or "").strip():
            continue
        story.append(Paragraph(escape(title), h2))
        story.append(
            _splittable_table(
                [[Paragraph(_section_content_markup(title, content), b2)]],
                colWidths=[6.7 * inch],
                style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0"))]),
            )
        )
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
    story: list = []
    _append_contact_block(
        story,
        contact,
        body_f=body_f,
        head_f=head_f,
        name_size=16,
        alignment=TA_CENTER,
        trailing_spacer=6,
    )
    if sanitize_for_pdf(contact or "").strip():
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
    body_f, head_f, body, body_sm, heading = _styles()
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
    _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=13, trailing_spacer=8)
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
    accent = colors.HexColor(accent_hex)
    story: list = []
    _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=12, trailing_spacer=12)
    wa_h = ParagraphStyle("waH", parent=heading, textColor=accent, fontSize=10, fontName=head_f)
    border = colors.HexColor("#fed7aa") if accent_hex.startswith("#c") or accent_hex.startswith("#d") else colors.HexColor("#fecaca")
    for title, content in (("PROFILE", professional_summary), ("EXPERIENCE", professional_experience), ("SKILLS", skills), ("EDUCATION", education), ("OTHER", other)):
        if not (content or "").strip():
            continue
        row = _splittable_table(
            [[Paragraph(f"<b>{escape(title)}</b>", wa_h), Paragraph(_section_content_markup(title, content), body_sm)]],
            colWidths=[1.35 * inch, 5.15 * inch],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, border),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            ),
        )
        story.append(row)
    if not story:
        story.append(Paragraph(_para_markup("(No content)"), body))
    doc.build(story)
    return buf.getvalue()


def _contact_header(contact: str, body_f: str, head_f: str, accent_hex: str) -> list:
    story: list = []
    _append_contact_block(
        story,
        contact,
        body_f=body_f,
        head_f=head_f,
        name_size=16,
        trailing_spacer=6,
    )
    if not story:
        return story
    accent = colors.HexColor(accent_hex)
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
        row = _splittable_table(
            [
                [
                    Paragraph(f"<b><font color='{accent_hex}'>{escape(title.upper())}</font></b>", heading),
                ],
                [Paragraph(_section_content_markup(title, c), b)],
            ],
            colWidths=[MODERN_CONTENT_WIDTH],
            style=TableStyle(
                [
                    ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            ),
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
    body_f, head_f, body, body_sm, heading = _styles(accent_hex)
    left_w = 2.25 * inch
    left_flowables: list = [
        Paragraph(f"<b><font color='{accent_hex}'>CONTACT</font></b>", body_sm),
        Spacer(1, 6),
    ]
    _append_contact_block(
        left_flowables,
        contact,
        body_f=body_f,
        head_f=head_f,
        name_size=10,
        trailing_spacer=10,
    )
    left_flowables.append(
        Paragraph(
            f"<b><font color='{accent_hex}'>SKILLS</font></b><br/><br/>{_para_markup(skills) if skills.strip() else '—'}",
            body_sm,
        )
    )
    if education.strip():
        left_flowables.extend(
            [
                Spacer(1, 10),
                Paragraph(
                    f"<b><font color='{accent_hex}'>EDUCATION</font></b><br/><br/>{_para_markup(education)}",
                    body_sm,
                ),
            ]
        )
    right_flowables: list = []
    for block in (
        _section_block("Summary", professional_summary, heading, body),
        _section_block("Experience", professional_experience, heading, body),
        _section_block("Additional", other, heading, body_sm),
    ):
        right_flowables.extend(block)
    if not right_flowables:
        right_flowables = [Paragraph(_para_markup("(No content)"), body)]
    return _build_framed_two_column_pdf(
        left_flowables=left_flowables,
        right_flowables=right_flowables,
        sidebar_bg=colors.HexColor(sidebar_hex),
        border_after_left=colors.HexColor(accent_hex),
        left_w=left_w,
    )


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
    header_html = format_contact_header_markup(
        contact,
        name_size=17,
        name_color="#ffffff",
        headline_color="#e2e8f0",
        detail_color="#e2e8f0",
        link_color="#93c5fd",
    )
    name_st = ParagraphStyle(
        "HeroName",
        fontName=head_f,
        fontSize=17,
        leading=20,
        textColor=colors.white,
        spaceAfter=3,
    )
    hdr = Table(
        [[Paragraph(header_html or "&nbsp;", name_st)]],
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
        story.append(Paragraph(_section_content_markup(title, c), b))
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
        _append_contact_block(story, contact, body_f=body_f, head_f=head_f, name_size=15, trailing_spacer=8)
    if sanitize_for_pdf(contact or "").strip():
        story.append(Table([[""]], colWidths=[MODERN_CONTENT_WIDTH], rowHeights=[0.5]))
        story[-1].setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, muted)]))
        story.append(Spacer(1, 10))

    title_st = ParagraphStyle("LineH", fontName=head_f, fontSize=7.5, leading=10, textColor=accent, spaceBefore=8, spaceAfter=3)

    def line_section(title: str, content: str, b: ParagraphStyle) -> None:
        c = (content or "").strip()
        if not c:
            return
        story.append(Paragraph(escape(title.upper()), title_st))
        story.append(Paragraph(_section_content_markup(title, c), b))
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


# Fresh PDF export: Scott-like ATS single-column layouts only (no sidebars, bands, or cards).
_SCOTT_LIKE_FRESH_KEYS = (
    "scott-ats-professional",
    "clean-classic",
    "dense-modern",
    "smart-line-minimal",
)

_SCOTT_LIKE_FRESH_BUILDERS: dict[str, tuple[str, _Builder]] = {
    "scott-ats-professional": (
        "ATS professional (pipe header)",
        build_scott_ats_professional,
    ),
}


def pick_random_blank_template() -> tuple[str, str, _Builder]:
    """Random ATS-style template similar to Scott resume (single column, pipe headers)."""
    from app.services.template_catalog import _CATALOG

    by_key = {entry[0]: entry for entry in _CATALOG}
    pool: list[tuple[str, str, _Builder]] = []
    for key in _SCOTT_LIKE_FRESH_KEYS:
        if key in _SCOTT_LIKE_FRESH_BUILDERS:
            label, fn = _SCOTT_LIKE_FRESH_BUILDERS[key]
            pool.append((key, label, fn))
        elif key in by_key:
            entry = by_key[key]
            pool.append((entry[0], entry[1], entry[3]))
    if not pool:
        entry = _CATALOG[0]
        pool.append((entry[0], entry[1], entry[3]))
    i = randbelow(len(pool))
    return pool[i]


def build_random_blank_template_pdf(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> tuple[bytes, str, str]:
    """Returns (pdf_bytes, template_key, template_label) using a random blank single-column layout."""
    key, label, fn = pick_random_blank_template()
    pdf = fn(
        contact=contact,
        professional_summary=professional_summary,
        professional_experience=professional_experience,
        skills=skills,
        education=education,
        other=other,
    )
    return pdf, key, label


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
