"""Embedded Unicode fonts for PDF generation (ReportLab + PyMuPDF)."""
from __future__ import annotations

from io import BytesIO

import pymupdf_fonts
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_RL_REGISTERED = False


def register_reportlab_fira_fonts() -> tuple[str, str]:
    """Register FiraGO (from pymupdf-fonts) with ReportLab. Returns (regular_name, bold_name)."""
    global _RL_REGISTERED
    reg_name, bold_name = "FiraGO", "FiraGOBold"
    if not _RL_REGISTERED:
        pdfmetrics.registerFont(TTFont(reg_name, BytesIO(pymupdf_fonts._figo())))
        pdfmetrics.registerFont(TTFont(bold_name, BytesIO(pymupdf_fonts._figbo())))
        _RL_REGISTERED = True
    return reg_name, bold_name


def pymupdf_fira_buffer() -> bytes:
    return pymupdf_fonts._figo()


def pymupdf_fira_fontname() -> str:
    """Stable internal name for Page.insert_font + insert_textbox."""
    return "ResFiraGO"
