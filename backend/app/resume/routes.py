from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from pydantic import BaseModel

from app.auth.dependencies import get_builder_user
from app.auth.resume_access import profile_owner, reject_bidder_upload, resume_access_for
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
    """Save/replace the user's own base resume. Bidders can't — theirs is the team member's."""
    reject_bidder_upload(user)
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


class ResumeAccessResponse(BaseModel):
    # Bidders work from their team member's base resume and can't upload or edit it.
    uses_team_member_resume: bool = False
    team_member_name: str = ""
    reason: str = ""
    # The base resume this user generates from by default (own, or the team member's).
    has_base_resume: bool = False
    base_resume_name: str = ""
    base_resume_updated_at: datetime | None = None


@router.get("/access", response_model=ResumeAccessResponse)
async def my_resume_access(user: dict = Depends(get_builder_user)) -> ResumeAccessResponse:
    """Whose base resume this user works from (shown in the builder and on the Profile page)."""
    access = await resume_access_for(user)
    extra: dict = {}
    try:
        owner = await profile_owner(user)
    except HTTPException:
        owner = None  # unassigned bidder: `reason` already explains it
    if owner is not None:
        model = get_base_resume_model(owner)
        updated = owner.get("base_resume_updated_at")
        extra.update(
            has_base_resume=model is not None,
            base_resume_name=model.name if model else "",
            base_resume_updated_at=updated.replace(tzinfo=UTC) if updated and updated.tzinfo is None else updated,
        )
    return ResumeAccessResponse(**access.__dict__, **extra)


@router.get("", response_model=ResumeModel)
async def read_base_resume(user: dict = Depends(get_builder_user)) -> ResumeModel:
    """The base resume this user works from (a bidder sees their team member's, read-only)."""
    model = get_base_resume_model(await profile_owner(user))
    if model is None:
        raise HTTPException(status_code=404, detail="No base resume saved yet.")
    return model


@router.delete("", status_code=204)
async def delete_base_resume(user: dict = Depends(get_builder_user)) -> None:
    reject_bidder_upload(user)
    await clear_base_resume_model(user["_id"])
