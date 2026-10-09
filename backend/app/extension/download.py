"""Public download of the packaged browser extension (see extension/scripts/package.mjs).

The zip is built during deployment (Dockerfile → /app/downloads) or locally with
``npm run ext:package`` (→ extension/release). It holds no secrets — only the
server URL — and is useless without a JobBot account, so it's served without
auth, which lets the /download page be shared as a plain link.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/extension/download", tags=["extension"])

_BASENAME = "jobbot-copilot"
_REPO_RELEASE_DIR = Path(__file__).resolve().parents[3] / "extension" / "release"


class ExtensionDownloadInfo(BaseModel):
    available: bool
    name: str = "JobBot Copilot"
    version: str = ""
    filename: str = ""
    size: int = 0
    sha256: str = ""
    built_at: str = ""


def _download_dir() -> Path:
    override = os.getenv("EXTENSION_DOWNLOAD_DIR", "").strip()
    return Path(override) if override else _REPO_RELEASE_DIR


def _paths() -> tuple[Path, Path]:
    d = _download_dir()
    return d / f"{_BASENAME}.zip", d / f"{_BASENAME}.json"


def _read_info() -> dict | None:
    zip_path, info_path = _paths()
    if not zip_path.is_file():
        return None
    try:
        return json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"size": zip_path.stat().st_size}


@router.get("/info", response_model=ExtensionDownloadInfo)
async def extension_download_info() -> ExtensionDownloadInfo:
    info = _read_info()
    if info is None:
        return ExtensionDownloadInfo(available=False)
    return ExtensionDownloadInfo(
        available=True,
        name=info.get("name") or "JobBot Copilot",
        version=info.get("version") or "",
        filename=info.get("filename") or f"{_BASENAME}.zip",
        size=int(info.get("size") or 0),
        sha256=info.get("sha256") or "",
        built_at=info.get("built_at") or "",
    )


@router.get("")
async def download_extension() -> FileResponse:
    info = _read_info()
    if info is None:
        raise HTTPException(
            status_code=404,
            detail="The extension package isn't available on this server yet (run `npm run ext:package`).",
        )
    zip_path, _ = _paths()
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=info.get("filename") or f"{_BASENAME}.zip",
        # Always fetch the newest build — members must stay on the latest version.
        headers={"Cache-Control": "no-cache"},
    )
