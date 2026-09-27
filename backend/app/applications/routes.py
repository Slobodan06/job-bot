"""The signed-in member's own application tracker."""
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from app.applications import service
from app.applications.schemas import (
    ApplicationListResponse,
    ApplicationPublic,
    ApplicationStatsResponse,
    ApplicationUpdateRequest,
    ApplicationUpsertRequest,
)
from app.auth.dependencies import get_builder_user
from app.resume.store import read_resume_variant

router = APIRouter(prefix="/api/applications", tags=["applications"])


async def _owned(application_id: str, user: dict) -> dict:
    return await service.find_application(application_id, user_id=user["_id"])


# ---------------------------------------------------------------------------
# Create / list / stats
# ---------------------------------------------------------------------------


@router.post("", response_model=ApplicationPublic)
async def upsert_application(
    body: ApplicationUpsertRequest,
    strict: bool = Query(default=False, description="Fail with 409 instead of merging duplicates."),
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    if strict:
        return service.to_public(await service.create_strict(user["_id"], body))
    return service.to_public(await service.upsert(user["_id"], body, datetime.now(UTC)))


@router.post("/submitted", response_model=ApplicationPublic)
async def record_submitted_application(
    payload: str = Form(..., description="ApplicationUpsertRequest as JSON"),
    resume: UploadFile | None = File(default=None),
    resume_variant_id: str = Form(default=""),
    resume_source: str = Form(default=""),
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    """Called by the extension once the site confirms the application was sent.

    Records the job as ``submitted`` together with the resume that went out with
    it — either the file the user picked on the page (uploaded here) or the
    JobBot-generated variant the extension attached (referenced by id) — stored
    in MongoDB alongside the application.
    """
    try:
        body = ApplicationUpsertRequest(**{**json.loads(payload), "status": "submitted"})
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid payload: {exc}") from exc

    file: tuple[bytes, str, str] | None = None
    source = resume_source or "selected_on_page"
    if resume is not None and (resume.filename or "").strip():
        file = await service.read_resume_upload(resume)
    elif resume_variant_id:
        found = await read_resume_variant(user_id=user["_id"], variant_id=resume_variant_id)
        if found:
            file = found
            source = "attached_by_extension"

    doc = await service.upsert(user["_id"], body, datetime.now(UTC))
    if file:
        data, filename, content_type = file
        doc = await service.attach_resume(
            doc, data=data, filename=filename, content_type=content_type, source=source
        )
    return service.to_public(doc)


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    user: dict = Depends(get_builder_user),
) -> ApplicationListResponse:
    query = service.build_list_query({"user_id": user["_id"]}, status=status, q=q, cursor=cursor)
    docs, next_cursor = await service.list_page(query, limit)
    return ApplicationListResponse(items=[service.to_public(d) for d in docs], next_cursor=next_cursor)


@router.get("/stats", response_model=ApplicationStatsResponse)
async def application_stats(user: dict = Depends(get_builder_user)) -> ApplicationStatsResponse:
    total, by_status = await service.status_counts({"user_id": user["_id"]})
    return ApplicationStatsResponse(total=total, by_status=by_status)


# ---------------------------------------------------------------------------
# Read / update / delete one
# ---------------------------------------------------------------------------


@router.get("/{application_id}", response_model=ApplicationPublic)
async def get_application(application_id: str, user: dict = Depends(get_builder_user)) -> ApplicationPublic:
    return service.to_public(await _owned(application_id, user))


@router.patch("/{application_id}", response_model=ApplicationPublic)
async def update_application(
    application_id: str,
    body: ApplicationUpdateRequest,
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    return service.to_public(await service.update(await _owned(application_id, user), body))


@router.delete("/{application_id}", status_code=204)
async def delete_application(application_id: str, user: dict = Depends(get_builder_user)) -> None:
    await service.delete(await _owned(application_id, user))


# ---------------------------------------------------------------------------
# Applied resume
# ---------------------------------------------------------------------------


@router.get("/{application_id}/resume")
async def download_applied_resume(application_id: str, user: dict = Depends(get_builder_user)) -> Response:
    return await service.resume_download(await _owned(application_id, user))


@router.put("/{application_id}/resume", response_model=ApplicationPublic)
async def replace_applied_resume(
    application_id: str,
    resume: UploadFile = File(...),
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    return service.to_public(await service.replace_resume(await _owned(application_id, user), resume))


@router.delete("/{application_id}/resume", response_model=ApplicationPublic)
async def remove_applied_resume(application_id: str, user: dict = Depends(get_builder_user)) -> ApplicationPublic:
    return service.to_public(await service.remove_resume(await _owned(application_id, user)))
