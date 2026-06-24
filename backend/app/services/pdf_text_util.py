"""Normalize text for reliable PDF rendering (avoids missing-glyph '?' from narrow fonts)."""
from __future__ import annotations

import unicodedata


_REPLACEMENTS: dict[str, str] = {
    "\u2011": "-",  # non-breaking hyphen
    "\u2010": "-",  # hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "--",  # em dash
    "\u2212": "-",  # minus
    "\u00ad": "",  # soft hyphen
    "\u2022": "- ",  # bullet
    "\u2023": "- ",
    "\u2043": "- ",
    "\u25aa": "- ",
    "\u25cf": "- ",
    "\u00b7": "- ",  # middle dot
    "\u2026": "...",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00a0": " ",
    "\u200b": "",
    "\ufeff": "",
}


def sanitize_for_pdf(text: str) -> str:
    if not text:
        return text
    t = unicodedata.normalize("NFKC", text)
    for k, v in _REPLACEMENTS.items():
        t = t.replace(k, v)
    # Keep newlines/tabs; drop other control characters.
    out: list[str] = []
    for ch in t:
        o = ord(ch)
        if ch in "\n\t" or o >= 32:
            out.append(ch)
    return "".join(out)
