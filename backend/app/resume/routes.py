from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.auth.dependencies import get_builder_user
from app.resume.store import (
    clear_base_resume_model,
    get_base_resume_model,
    save_base_resume_model,
)
from app.services.resume_ingest import ingest_resume
from app.services.resume_model import ResumeModel

router = APIRouter(prefix="/api/resume", tags=["resume"])

_RESUME_EXTS = (".docx", ".doc", ".pdf")


@router.post("", response_model=ResumeModel)
async def upload_base_resume(
    resume: UploadFile = File(...),
    user: dict = Depends(get_builder_user),
) -> ResumeModel:
    raw = await resume.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    name = resume.filename or "resume.docx"
    if not name.lower().endswith(_RESUME_EXTS):
        raise HTTPException(status_code=400, detail="Upload a Word (.docx) or PDF (.pdf) resume.")
    try:
        model = await ingest_resume(raw, filename=name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await save_base_resume_model(user["_id"], model)
    return model


@router.get("", response_model=ResumeModel)
async def read_base_resume(user: dict = Depends(get_builder_user)) -> ResumeModel:
    model = get_base_resume_model(user)
    if model is None:
        raise HTTPException(status_code=404, detail="No base resume saved yet.")
    return model


@router.delete("", status_code=204)
async def delete_base_resume(user: dict = Depends(get_builder_user)) -> None:
    await clear_base_resume_model(user["_id"])
