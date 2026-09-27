import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_root / "backend" / ".env")
load_dotenv(_root / "atlas-credentials.env")
load_dotenv()

from app.auth.admin import router as admin_router
from app.auth.routes import router as auth_router
from app.auth.dependencies import get_builder_user
from app.applications.routes import router as applications_router
from app.cv_templates.routes import router as cv_templates_router
from app.extension.routes import router as extension_router
from app.job_boards.routes import router as job_boards_router
from app.jobs.routes import router as jobs_router
from app.resume.routes import router as resume_router
from app.database import close_db, connect_db, ensure_indexes
from app.schemas import (
    CoverLetterResponse,
    ParseSectionsResponse,
    QualificationAnalysisResponse,
    TailorResponse,
    WorkExperienceRoleResponse,
)
from app.services.application_answers import (
    build_messages,
    open_answer_stream,
    openai_configured,
    resume_text_from_model,
)
from app.services.cover_letter import generate_cover_letter
from app.services.extract_text import extract_text_from_bytes
from app.services.email import log_email_config
from app.services.resume_ingest import ingest_resume
from app.resume.store import get_base_resume_model
from app.services.fresh_resume_builder import build_fresh_tailored_resume
from app.services.qualification_questions import analyze_resume_qualification_gaps
from app.services.tailor import tailor_resume

_RESUME_EXTS = (".docx", ".doc", ".pdf")


async def _read_resume_upload(resume: UploadFile) -> tuple[bytes, str]:
    raw = await resume.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    name = resume.filename or "resume.docx"
    if not name.lower().endswith(_RESUME_EXTS):
        raise HTTPException(
            status_code=400,
            detail="Upload a Word resume (.docx) or PDF (.pdf).",
        )
    return raw, name


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
        return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    origins = [
        "http://127.0.0.1:8080",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    # The deployed site (APP_URL) always talks to its own API.
    app_url = os.getenv("APP_URL", "").strip().rstrip("/")
    if app_url and app_url not in origins:
        origins.append(app_url)
    return origins


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
app.include_router(resume_router)
app.include_router(applications_router)
app.include_router(extension_router)
app.include_router(jobs_router)
app.include_router(job_boards_router)

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
        "job_search_configured": bool(os.getenv("RAPIDAPI_KEY", "").strip()),
    }


@app.post("/api/parse-sections", response_model=ParseSectionsResponse)
async def parse_sections(
    resume: UploadFile = File(...),
    _user: dict = Depends(get_builder_user),
) -> ParseSectionsResponse:
    """Convert the upload into the normalized canonical resume model."""
    raw, name = await _read_resume_upload(resume)
    try:
        model = await ingest_resume(raw, filename=name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    roles = model.work_experience_roles()
    total_bullets = sum(len(role.bullets) for role in roles)
    sections_detected = [
        key
        for key, present in (
            ("contact", bool(model.name or model.contact.email)),
            ("professional_summary", bool(model.professional_summary.strip())),
            ("professional_experience", bool(roles)),
            ("skills", bool(model.technical_skills)),
            ("education", bool(model.education)),
            ("other", bool(model.extra_sections())),
        )
        if present
    ]

    return ParseSectionsResponse(
        contact=model.contact_block(),
        professional_summary=model.professional_summary,
        professional_experience=model.experience_text(),
        skills=model.skills_text(),
        education=model.education_text(),
        other=model.extras_text(),
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
            for role in roles
        ],
        role_count=len(roles),
        experience_layout="structured",
        sections_detected=sections_detected,
        source_format=model.meta.source_format,
        total_experience_bullets=total_bullets,
        resume_model=model.model_dump(),
    )


@app.post("/api/tailor", response_model=TailorResponse)
async def tailor(
    resume: UploadFile | None = File(None),
    job_description: str = Form(...),
    target_job_role: str = Form(""),
    candidate_answers: str = Form(""),
    sample_mode: str = Form("true"),
    enable_bold: str = Form("true"),
    export_mode: str = Form("fresh_pdf"),
    user: dict = Depends(get_builder_user),
) -> TailorResponse:
    if not job_description or not job_description.strip():
        raise HTTPException(status_code=400, detail="Job description is required.")
    mode = (export_mode or "fresh_pdf").strip().lower()

    if resume is None or not (resume.filename or "").strip():
        # No file: tailor from the user's saved base resume (used by the extension).
        base_model = get_base_resume_model(user)
        if base_model is None:
            raise HTTPException(
                status_code=400,
                detail="Attach a resume or save a base resume first.",
            )
        try:
            return await build_fresh_tailored_resume(
                resume_model=base_model,
                original_filename=f"{(user.get('name') or 'resume').split(' ')[0]}-resume.docx",
                job_description=job_description,
                target_job_role=target_job_role.strip(),
                cv_template_key=None,
                candidate_answers=candidate_answers,
                sample_mode=sample_mode.strip().lower() in ("1", "true", "yes", "on"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    raw, name = await _read_resume_upload(resume)
    lower_name = name.lower()
    # In-place Word editing needs the original .docx; anything else uses fresh export.
    if mode != "fresh_pdf" and not lower_name.endswith(".docx"):
        mode = "fresh_pdf"
    if mode == "fresh_pdf":
        try:
            model = await ingest_resume(raw, filename=name)
            return await build_fresh_tailored_resume(
                resume_model=model,
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
    raw, name = await _read_resume_upload(resume)
    try:
        model = await ingest_resume(raw, filename=name)
        result = analyze_resume_qualification_gaps(
            resume_model=model,
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
    raw, name = await _read_resume_upload(resume)
    try:
        model = await ingest_resume(raw, filename=name)
        result = await generate_cover_letter(
            resume_model=model,
            job_description=job_description,
            original_filename=name,
            target_job_role=target_job_role.strip(),
            company_name=company_name.strip(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return CoverLetterResponse(**result)


@app.post("/api/application-answer")
async def application_answer(
    question: str = Form(..., max_length=4000),
    job_description: str = Form(""),
    company_name: str = Form(""),
    target_job_role: str = Form(""),
    length: str = Form("standard"),
    history: str = Form("[]", description='Prior turns as JSON: [{"role": "user"|"assistant", "content": "..."}]'),
    resume: UploadFile | None = File(None),
    user: dict = Depends(get_builder_user),
) -> StreamingResponse:
    """Stream a resume-grounded answer to a job-application question (plain text)."""
    if not question.strip():
        raise HTTPException(status_code=400, detail="Type the application question first.")
    if not openai_configured():
        raise HTTPException(
            status_code=503,
            detail="OpenAI is not configured on the server (OPENAI_API_KEY) — answers need it.",
        )

    if resume is not None and (resume.filename or "").strip():
        raw, name = await _read_resume_upload(resume)
        try:
            # Raw text is all the model needs here — skips the (slow) AI normalization
            # that full resume ingestion does, so every question stays fast.
            resume_text = extract_text_from_bytes(name, raw)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
        base_model = get_base_resume_model(user)
        if base_model is None:
            raise HTTPException(
                status_code=400,
                detail="Attach a resume (or save a base resume on the Applications page) first.",
            )
        resume_text = resume_text_from_model(base_model)
    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Could not read any text from the resume.")

    try:
        turns = json.loads(history or "[]")
    except ValueError:
        turns = []
    messages = build_messages(
        resume_text=resume_text,
        job_description=job_description,
        question=question,
        history=turns if isinstance(turns, list) else [],
        company_name=company_name,
        target_role=target_job_role,
        length=length,
    )
    try:
        chunks = await open_answer_stream(messages)
    except Exception as e:
        logging.getLogger("uvicorn.error").exception("Application answer request failed")
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {e}") from e
    return StreamingResponse(
        chunks,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
