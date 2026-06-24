import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_root / "backend" / ".env")
load_dotenv(_root / "atlas-credentials.env")
load_dotenv()

from app.auth.admin import router as admin_router
from app.auth.routes import router as auth_router
from app.auth.dependencies import get_builder_user
from app.cv_templates.routes import router as cv_templates_router
from app.database import close_db, connect_db, ensure_indexes
from app.schemas import TailorResponse
from app.services.extract_text import extract_text_from_bytes
from app.services.tailor import tailor_resume


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    await ensure_indexes()
    yield
    await close_db()


def _cors_allow_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def _frontend_dist() -> Path | None:
    override = os.getenv("FRONTEND_DIST", "").strip()
    default = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    for candidate in (Path(override) if override else None, default):
        if candidate is None:
            continue
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
    return None


app = FastAPI(title="Resume Tailor API", version="1.0.0", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(cv_templates_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/tailor", response_model=TailorResponse)
async def tailor(
    resume: UploadFile = File(...),
    job_description: str = Form(...),
    _user: dict = Depends(get_builder_user),
) -> TailorResponse:
    if not job_description or not job_description.strip():
        raise HTTPException(status_code=400, detail="Job description is required.")
    raw = await resume.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    try:
        resume_text = extract_text_from_bytes(resume.filename or "resume.pdf", raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not resume_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not extract text from the resume. Try TXT or a different PDF/DOCX export.",
        )
    name = resume.filename or "resume.pdf"
    pdf_bytes = raw if name.lower().endswith(".pdf") else None
    template_key = (_user.get("cv_template_key") or "").strip()
    if not template_key:
        raise HTTPException(
            status_code=403,
            detail="Select a CV template before generating resumes.",
        )
    return await tailor_resume(
        resume_text,
        job_description,
        source_pdf_bytes=pdf_bytes,
        original_filename=name,
        template_key=template_key,
    )


_dist = _frontend_dist()
if _dist is not None:
    assets_dir = _dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    async def spa_index() -> FileResponse:
        return FileResponse(_dist / "index.html")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(_dist / "index.html")

    @app.on_event("startup")
    async def _browser_url_hint() -> None:
        logging.getLogger("uvicorn.error").info(
            "SPA from %s — open http://127.0.0.1:<PORT>/ or http://localhost:<PORT>/ "
            "(not http://0.0.0.0:<PORT>/; browsers often block script loads there).",
            _dist,
        )
