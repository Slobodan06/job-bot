from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth.dependencies import get_builder_user
from app.cv_templates.assignment import assign_cv_template
from app.cv_templates.previews import (
    SAMPLE_CONTACT,
    SAMPLE_EDUCATION,
    SAMPLE_EXPERIENCE,
    SAMPLE_OTHER,
    SAMPLE_SKILLS,
    SAMPLE_SUMMARY,
)
from app.cv_templates.schemas import CvTemplatePublic, SelectTemplateRequest, SelectTemplateResponse
from app.database import get_db
from app.services.template_catalog import build_template_pdf, get_template_meta, list_template_catalog

router = APIRouter(prefix="/api/cv-templates", tags=["cv-templates"])


async def _claimed_keys() -> dict[str, str]:
    db = get_db()
    claimed: dict[str, str] = {}
    async for doc in db.users.find({"cv_template_key": {"$exists": True, "$nin": [None, ""]}}):
        key = doc.get("cv_template_key")
        if key:
            claimed[key] = str(doc["_id"])
    return claimed


@router.get("", response_model=list[CvTemplatePublic])
async def list_cv_templates(user: dict = Depends(get_builder_user)) -> list[CvTemplatePublic]:
    claimed = await _claimed_keys()
    my_key = user.get("cv_template_key") or ""
    my_id = str(user["_id"])
    result: list[CvTemplatePublic] = []
    for item in list_template_catalog():
        key = item["key"]
        if key == my_key:
            status = "yours"
        elif key in claimed and claimed[key] != my_id:
            status = "taken"
        else:
            status = "available"
        result.append(
            CvTemplatePublic(
                key=key,
                label=item["label"],
                description=item["description"],
                status=status,
                accent_color=item["accent_color"],
                layout_family=item["layout_family"],
            )
        )
    return result


@router.get("/{key}/preview.pdf")
async def preview_template_pdf(
    key: str,
    _user: dict = Depends(get_builder_user),
) -> Response:
    try:
        pdf_bytes, _, _ = build_template_pdf(
            key,
            contact=SAMPLE_CONTACT,
            professional_summary=SAMPLE_SUMMARY,
            professional_experience=SAMPLE_EXPERIENCE,
            skills=SAMPLE_SKILLS,
            education=SAMPLE_EDUCATION,
            other=SAMPLE_OTHER,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail="Unknown CV template.") from e
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{key}-preview.pdf"'},
    )


@router.get("/mine", response_model=CvTemplatePublic | None)
async def my_cv_template(user: dict = Depends(get_builder_user)) -> CvTemplatePublic | None:
    key = user.get("cv_template_key")
    if not key:
        return None
    try:
        meta = get_template_meta(key)
    except KeyError as e:
        raise HTTPException(status_code=500, detail="Your saved template is no longer available.") from e
    return CvTemplatePublic(
        key=key,
        label=meta["label"],
        description=meta["description"],
        status="yours",
        accent_color=meta["accent_color"],
        layout_family=meta["layout_family"],
    )


@router.post("/select", response_model=SelectTemplateResponse)
async def select_cv_template(
    body: SelectTemplateRequest,
    user: dict = Depends(get_builder_user),
) -> SelectTemplateResponse:
    key = body.template_key.strip()
    existing = user.get("cv_template_key")
    if existing == key:
        meta = get_template_meta(key)
        return SelectTemplateResponse(
            message="You already use this CV template.",
            template_key=key,
            template_label=meta["label"],
        )

    db = get_db()
    label = await assign_cv_template(db, user["_id"], key)
    if existing:
        message = f"Switched to CV template “{label}”. Your previous template is now available for others."
    else:
        message = f"CV template “{label}” is now yours."
    return SelectTemplateResponse(message=message, template_key=key, template_label=label)
