"""Single source of truth for smart CV templates."""
from __future__ import annotations

from collections.abc import Callable
from functools import partial

from app.services import resume_pdf_templates as pdf
from app.services import rendercv_resume as rendercv

_Builder = Callable[..., bytes]

# key, label, description, builder, accent hex, layout family (for UI previews)
_CATALOG: list[tuple[str, str, str, _Builder, str, str]] = [
    ("rendercv-classic", "RenderCV classic", "RenderCV's default clean academic and engineering theme.", partial(rendercv.build_rendercv_template_pdf, theme="classic"), "#004f90", "rendercv"),
    ("rendercv-ember", "RenderCV ember", "RenderCV theme with warm modern defaults.", partial(rendercv.build_rendercv_template_pdf, theme="ember"), "#d97706", "rendercv"),
    ("rendercv-engineeringclassic", "RenderCV engineering classic", "RenderCV engineering-focused classic theme.", partial(rendercv.build_rendercv_template_pdf, theme="engineeringclassic"), "#334155", "rendercv"),
    ("rendercv-engineeringresumes", "RenderCV engineering resumes", "RenderCV theme inspired by engineering resume conventions.", partial(rendercv.build_rendercv_template_pdf, theme="engineeringresumes"), "#0f172a", "rendercv"),
    ("rendercv-harvard", "RenderCV Harvard", "RenderCV theme with compact Harvard-style resume defaults.", partial(rendercv.build_rendercv_template_pdf, theme="harvard"), "#7f1d1d", "rendercv"),
    ("rendercv-ink", "RenderCV ink", "RenderCV minimal ink-forward theme.", partial(rendercv.build_rendercv_template_pdf, theme="ink"), "#111827", "rendercv"),
    ("rendercv-moderncv", "RenderCV ModernCV", "RenderCV theme based on ModernCV styling.", partial(rendercv.build_rendercv_template_pdf, theme="moderncv"), "#2563eb", "rendercv"),
    ("rendercv-opal", "RenderCV opal", "RenderCV theme with polished contemporary defaults.", partial(rendercv.build_rendercv_template_pdf, theme="opal"), "#0d9488", "rendercv"),
    ("rendercv-sb2nov", "RenderCV sb2nov", "RenderCV theme based on the sb2nov resume format.", partial(rendercv.build_rendercv_template_pdf, theme="sb2nov"), "#374151", "rendercv"),
    ("clean-classic", "Smart classic", "Clean single-column layout with tight margins and modern typography.", pdf.build_clean_classic, "#0d9488", "clean-classic"),
    ("clean-forest", "Smart forest", "Classic smart layout with forest-green accents.", partial(pdf.build_classic_tinted, accent_hex="#166534"), "#166534", "clean-classic"),
    ("executive-band", "Smart executive onyx", "Slim header band with bold name and compact body.", partial(pdf.build_executive_colored, band_hex="#15232f"), "#15232f", "executive-band"),
    ("executive-charcoal", "Smart executive charcoal", "Charcoal header strip with crisp white type.", partial(pdf.build_executive_colored, band_hex="#1f2937"), "#1f2937", "executive-band"),
    ("executive-slate", "Smart executive slate", "Slate header band for a refined professional look.", partial(pdf.build_executive_colored, band_hex="#334155"), "#334155", "executive-band"),
    ("executive-wine", "Smart executive wine", "Deep wine header for a distinctive profile.", partial(pdf.build_executive_colored, band_hex="#7f1d1d"), "#7f1d1d", "executive-band"),
    ("two-column", "Smart sidebar", "Light sidebar for skills; experience on the right.", pdf.build_two_column, "#64748b", "two-column"),
    ("two-column-sage", "Smart sage sidebar", "Two-column layout with a soft sage panel.", partial(pdf.build_two_column_tinted, sidebar_hex="#ecfdf5", border_hex="#6ee7b7"), "#059669", "two-column"),
    ("two-column-sand", "Smart sand sidebar", "Two-column layout with a warm sand panel.", partial(pdf.build_two_column_tinted, sidebar_hex="#fffbeb", border_hex="#fcd34d"), "#d97706", "two-column"),
    ("navy-sidebar", "Smart navy sidebar", "Bold navy sidebar for contact and skills.", partial(pdf.build_navy_colored, sidebar_hex="#1e3a5f"), "#1e3a5f", "navy-sidebar"),
    ("navy-indigo", "Smart indigo sidebar", "Indigo sidebar with high-contrast white text.", partial(pdf.build_navy_colored, sidebar_hex="#312e81"), "#312e81", "navy-sidebar"),
    ("navy-forest", "Smart forest sidebar", "Forest-green sidebar for an earthy feel.", partial(pdf.build_navy_colored, sidebar_hex="#14532d"), "#14532d", "navy-sidebar"),
    ("bordered-cards", "Smart cards", "Section cards with subtle borders and compact spacing.", pdf.build_bordered_cards, "#334155", "bordered-cards"),
    ("bordered-graphite", "Smart graphite cards", "Card sections with graphite headers.", partial(pdf.build_bordered_tinted, accent_hex="#334155"), "#334155", "bordered-cards"),
    ("bordered-ocean", "Smart ocean cards", "Card sections with ocean-blue headers.", partial(pdf.build_bordered_tinted, accent_hex="#0369a1"), "#0369a1", "bordered-cards"),
    ("timeline-accent", "Smart teal stripe", "Teal accent stripe beside each section.", partial(pdf.build_timeline_colored, accent_hex="#0d9488"), "#0d9488", "timeline-accent"),
    ("timeline-violet", "Smart violet stripe", "Violet stripe accent beside each section.", partial(pdf.build_timeline_colored, accent_hex="#7c3aed"), "#7c3aed", "timeline-accent"),
    ("timeline-emerald", "Smart emerald stripe", "Emerald stripe accent beside each section.", partial(pdf.build_timeline_colored, accent_hex="#059669"), "#059669", "timeline-accent"),
    ("timeline-rose", "Smart rose stripe", "Rose stripe accent beside each section.", partial(pdf.build_timeline_colored, accent_hex="#e11d48"), "#e11d48", "timeline-accent"),
    ("dense-modern", "Smart compact", "Dense, ATS-friendly layout with minimal whitespace.", pdf.build_dense_modern, "#64748b", "dense-modern"),
    ("dense-ink", "Smart compact ink", "Compact layout with ink-gray dividers.", partial(pdf.build_dense_tinted, accent_hex="#374151"), "#374151", "dense-modern"),
    ("minimal-serif", "Smart centered", "Centered header with hairline dividers.", pdf.build_minimal_serif, "#475569", "minimal-serif"),
    ("minimal-pearl", "Smart pearl", "Centered header with soft pearl accents.", partial(pdf.build_minimal_tinted, accent_hex="#94a3b8"), "#94a3b8", "minimal-serif"),
    ("minimal-ink", "Smart ink", "Centered header with deep ink titles.", partial(pdf.build_minimal_tinted, accent_hex="#1e293b"), "#1e293b", "minimal-serif"),
    ("corporate-blue", "Smart corporate blue", "Blue rule under header; professional and tight.", partial(pdf.build_corporate_colored, rule_hex="#1d4ed8"), "#1d4ed8", "corporate-blue"),
    ("corporate-cobalt", "Smart corporate cobalt", "Cobalt accent rule for corporate roles.", partial(pdf.build_corporate_colored, rule_hex="#2563eb"), "#2563eb", "corporate-blue"),
    ("corporate-azure", "Smart corporate azure", "Bright azure rule for a modern corporate CV.", partial(pdf.build_corporate_colored, rule_hex="#0284c7"), "#0284c7", "corporate-blue"),
    ("warm-accent", "Smart warm grid", "Label grid with warm accent headings.", partial(pdf.build_warm_colored, accent_hex="#c2410c"), "#c2410c", "warm-accent"),
    ("warm-amber", "Smart amber grid", "Label grid with amber section headings.", partial(pdf.build_warm_colored, accent_hex="#d97706"), "#d97706", "warm-accent"),
    ("warm-crimson", "Smart crimson grid", "Label grid with crimson section headings.", partial(pdf.build_warm_colored, accent_hex="#dc2626"), "#dc2626", "warm-accent"),
    ("smart-stack-teal", "Smart stack teal", "Contemporary single column with teal accent bar.", partial(pdf.build_modern_stack, accent_hex="#0d9488"), "#0d9488", "modern-stack"),
    ("smart-stack-graphite", "Smart stack graphite", "Modern stack layout with graphite accents.", partial(pdf.build_modern_stack, accent_hex="#334155"), "#334155", "modern-stack"),
    ("smart-stack-indigo", "Smart stack indigo", "Modern stack layout with indigo accents.", partial(pdf.build_modern_stack, accent_hex="#4f46e5"), "#4f46e5", "modern-stack"),
    ("smart-split-pearl", "Smart split pearl", "Asymmetric split with pearl sidebar panel.", partial(pdf.build_modern_split, accent_hex="#334155", sidebar_hex="#f8fafc"), "#334155", "modern-split"),
    ("smart-split-charcoal", "Smart split charcoal", "Split layout with charcoal accent stripe.", partial(pdf.build_modern_split, accent_hex="#0f172a", sidebar_hex="#f1f5f9"), "#0f172a", "modern-split"),
    ("smart-hero-midnight", "Smart hero midnight", "Slim midnight hero bar with clean body text.", partial(pdf.build_modern_hero, accent_hex="#0f172a"), "#0f172a", "modern-hero"),
    ("smart-hero-ocean", "Smart hero ocean", "Ocean-blue hero strip with modern spacing.", partial(pdf.build_modern_hero, accent_hex="#0284c7"), "#0284c7", "modern-hero"),
    ("smart-pill-emerald", "Smart pill emerald", "Section labels in soft pill-style headers.", partial(pdf.build_modern_pill, accent_hex="#059669"), "#059669", "modern-pill"),
    ("smart-pill-coral", "Smart pill coral", "Coral pill headers with airy section spacing.", partial(pdf.build_modern_pill, accent_hex="#f97316"), "#f97316", "modern-pill"),
    ("smart-line-minimal", "Smart line minimal", "Ultra-clean layout with hairline dividers.", partial(pdf.build_modern_line, accent_hex="#6366f1"), "#6366f1", "modern-line"),
]

assert len(_CATALOG) == 49


def list_template_catalog() -> list[dict[str, str]]:
    return [
        {
            "key": key,
            "label": label,
            "description": desc,
            "accent_color": accent,
            "layout_family": layout,
        }
        for key, label, desc, _fn, accent, layout in _CATALOG
    ]


def get_template_meta(key: str) -> dict[str, str]:
    for entry in _CATALOG:
        if entry[0] == key:
            return {
                "key": entry[0],
                "label": entry[1],
                "description": entry[2],
                "accent_color": entry[4],
                "layout_family": entry[5],
            }
    raise KeyError(key)


def get_template_builder(key: str) -> tuple[str, str, _Builder]:
    for k, label, _desc, fn, _accent, _layout in _CATALOG:
        if k == key:
            return k, label, fn
    raise KeyError(key)


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
    key, label, fn = get_template_builder(template_key)
    pdf_bytes = fn(
        contact=contact,
        professional_summary=professional_summary,
        professional_experience=professional_experience,
        skills=skills,
        education=education,
        other=other,
    )
    return pdf_bytes, key, label
