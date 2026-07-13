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
from app.schemas import (
    CoverLetterResponse,
    ParseSectionsResponse,
    QualificationAnalysisResponse,
    TailorResponse,
    WorkExperienceRoleResponse,
)
from app.services.cover_letter import generate_cover_letter
from app.services.extract_text import extract_text_from_bytes
from app.services.email import log_email_config
from app.services.resume_sections import analyze_resume_file
from app.services.fresh_resume_builder import build_fresh_tailored_resume
from app.services.qualification_questions import analyze_resume_qualification_gaps
from app.services.tailor import tailor_resume


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_email_config()
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
async def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "openai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
    }


@app.post("/api/parse-sections", response_model=ParseSectionsResponse)
async def parse_sections(
    resume: UploadFile = File(...),
    _user: dict = Depends(get_builder_user),
) -> ParseSectionsResponse:
    """Detect resume sections and individual work-experience roles (local parsing, no external API)."""
    raw = await resume.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    name = resume.filename or "resume.docx"
    lower = name.lower()
    if not (lower.endswith(".docx") or lower.endswith(".doc") or lower.endswith(".pdf")):
        raise HTTPException(
            status_code=400,
            detail="Upload a Word resume (.docx) or PDF (.pdf).",
        )
    try:
        analysis = analyze_resume_file(raw, filename=name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    total_bullets = sum(len(role.bullets) for role in analysis.work_experience_roles)

    return ParseSectionsResponse(
        contact=analysis.contact,
        professional_summary=analysis.professional_summary,
        professional_experience=analysis.professional_experience,
        skills=analysis.skills,
        education=analysis.education,
        other=analysis.other,
        work_experience_roles=[
            WorkExperienceRoleResponse(
                header=role.header,
                company=role.company,
                title=role.title,
                location=role.location,
                period=role.period,
                bullets=list(role.bullets),
                bullet_count=len(role.bullets),
            )
            for role in analysis.work_experience_roles
        ],
        role_count=analysis.role_count,
        experience_layout=analysis.experience_layout,
        sections_detected=list(analysis.sections_detected),
        source_format=analysis.source_format,
        total_experience_bullets=total_bullets,
    )


@app.post("/api/tailor", response_model=TailorResponse)
async def tailor(
    resume: UploadFile = File(...),
    job_description: str = Form(...),
    target_job_role: str = Form(""),
    candidate_answers: str = Form(""),
    sample_mode: str = Form("true"),
    enable_bold: str = Form("true"),
    export_mode: str = Form("fresh_pdf"),
    _user: dict = Depends(get_builder_user),
) -> TailorResponse:
    if not job_description or not job_description.strip():
        raise HTTPException(status_code=400, detail="Job description is required.")
    raw = await resume.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    name = resume.filename or "resume.docx"
    lower_name = name.lower()
    if not lower_name.endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Upload a Word resume (.docx).",
        )
    mode = (export_mode or "fresh_pdf").strip().lower()
    if mode == "fresh_pdf":
        try:
            return await build_fresh_tailored_resume(
                source_docx_bytes=raw,
                original_filename=name,
                job_description=job_description,
                target_job_role=target_job_role.strip(),
                cv_template_key=None,
                candidate_answers=candidate_answers,
                sample_mode=sample_mode.strip().lower() in ("1", "true", "yes", "on"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        resume_text = extract_text_from_bytes(name, raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not resume_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not extract text from the resume. Use a .docx with clear sections.",
        )
    result = await tailor_resume(
        resume_text,
        job_description,
        source_docx_bytes=raw,
        original_filename=name,
        target_job_role=target_job_role.strip(),
        enable_bold=enable_bold.strip().lower() in ("1", "true", "yes", "on"),
    )
    return result.model_copy(update={"export_mode": "inplace_docx"})


@app.post("/api/qualification-analysis", response_model=QualificationAnalysisResponse)
async def qualification_analysis(
    resume: UploadFile = File(...),
    job_description: str = Form(...),
    _user: dict = Depends(get_builder_user),
) -> QualificationAnalysisResponse:
    """Compare the JD with source evidence before any resume is generated."""
    if not job_description or not job_description.strip():
        raise HTTPException(status_code=400, detail="Job description is required.")
    raw = await resume.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    name = resume.filename or "resume.docx"
    if not name.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Upload a Word resume (.docx).")
    try:
        result = analyze_resume_qualification_gaps(
            source_docx_bytes=raw,
            job_description=job_description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return QualificationAnalysisResponse(**result)


@app.post("/api/cover-letter", response_model=CoverLetterResponse)
async def cover_letter(
    resume: UploadFile = File(...),
    job_description: str = Form(...),
    target_job_role: str = Form(""),
    company_name: str = Form(""),
    _user: dict = Depends(get_builder_user),
) -> CoverLetterResponse:
    if not job_description or not job_description.strip():
        raise HTTPException(status_code=400, detail="Job description is required.")
    raw = await resume.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    name = resume.filename or "resume.docx"
    if not name.lower().endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Upload a Word resume (.docx) to generate a cover letter.",
        )
    try:
        resume_text = extract_text_from_bytes(name, raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not resume_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not extract text from the resume.",
        )
    result = await generate_cover_letter(
        raw,
        job_description,
        original_filename=name,
        target_job_role=target_job_role.strip(),
        company_name=company_name.strip(),
    )
    return CoverLetterResponse(**result)


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
