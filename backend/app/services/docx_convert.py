"""Convert tailored .docx bytes to PDF while preserving Word layout."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def pdf_download_filename(docx_filename: str) -> str:
    name = Path(docx_filename).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    if not name or name in (".", ".."):
        return "resume-tailored.pdf"
    stem = Path(name).stem or "resume-tailored"
    return f"{stem}.pdf"


def _libreoffice_commands(profile_dir: Path | None = None) -> list[list[str]]:
    env_path = os.getenv("LIBREOFFICE_PATH", "").strip()
    profile_flag: list[str] = []
    if profile_dir is not None:
        profile_flag = [f"-env:UserInstallation={profile_dir.resolve().as_uri()}"]

    base_flags = ["--headless", "--norestore", "--nologo", "--nodefault", *profile_flag, "--convert-to", "pdf"]

    if env_path:
        return [[env_path, *base_flags]]

    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        return [[path, *base_flags] for path in candidates if Path(path).is_file()]

    for cmd in ("libreoffice", "soffice"):
        if shutil.which(cmd):
            return [[cmd, *base_flags]]
    return []


def _convert_with_docx2pdf(docx_path: Path, pdf_path: Path) -> bool:
    try:
        from docx2pdf import convert
    except ImportError:
        return False
    try:
        convert(str(docx_path), str(pdf_path))
    except Exception:
        return False
    return pdf_path.is_file() and pdf_path.stat().st_size > 0


def _convert_with_libreoffice(docx_path: Path, pdf_path: Path) -> bool:
    out_dir = pdf_path.parent
    profile_dir = out_dir / "lo-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    for base_cmd in _libreoffice_commands(profile_dir):
        cmd = [*base_cmd, "--outdir", str(out_dir), str(docx_path)]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(os.getenv("DOCX_PDF_TIMEOUT_SEC", "120")),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        produced = out_dir / f"{docx_path.stem}.pdf"
        if produced.is_file() and produced.stat().st_size > 0:
            if produced.resolve() != pdf_path.resolve():
                produced.replace(pdf_path)
            return True
    return False


def convert_docx_bytes_to_pdf(
    docx_bytes: bytes,
    *,
    original_filename: str = "resume-tailored.docx",
) -> tuple[bytes, str] | None:
    """
    Convert DOCX bytes to PDF. Tries Microsoft Word (docx2pdf) then LibreOffice.
    Returns (pdf_bytes, suggested_filename) or None if no converter is available.
    """
    if not docx_bytes or docx_bytes[:2] != b"PK":
        return None

    mode = os.getenv("DOCX_PDF_CONVERTER", "auto").strip().lower()
    pdf_name = pdf_download_filename(original_filename)

    with tempfile.TemporaryDirectory(prefix="jobbot-docx-pdf-") as tmp:
        tmp_dir = Path(tmp)
        docx_path = tmp_dir / (Path(original_filename).name or "resume-tailored.docx")
        pdf_path = tmp_dir / pdf_name
        docx_path.write_bytes(docx_bytes)

        converted = False
        try_docx2pdf = mode in ("docx2pdf", "word") or (mode == "auto" and sys.platform == "win32")
        if try_docx2pdf:
            converted = _convert_with_docx2pdf(docx_path, pdf_path)
        if not converted and mode in ("auto", "libreoffice", "soffice"):
            converted = _convert_with_libreoffice(docx_path, pdf_path)

        if not converted or not pdf_path.is_file():
            return None

        return pdf_path.read_bytes(), pdf_name
