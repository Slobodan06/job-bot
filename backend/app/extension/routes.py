import base64
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.applications.logic import job_hash
from app.auth.dependencies import get_builder_user
from app.auth.resume_access import (
    base_resume_for,
    profile_owner,
    works_from_team_member,
)
from app.auth.roles import user_can_use_autofill
from app.database import get_db
from app.extension.answers import draft_free_text_answers
from app.extension.autofill import (
    normalize_autofill_profile,
    resume_file_stem,
    resolve_deterministic_values,
    unresolved_free_text_fields,
)
from app.extension.crypto import decrypt_secret, encrypt_secret
from app.extension.schemas import (
    ApplicationQuestion,
    AnalyzeJobResponse,
    AutofillRequest,
    AutofillResponse,
    AutofillValue,
    AutofillProfile,
    DetectedJob,
    ExtensionProfileResponse,
    ResumeAttachment,
    TailorForJobRequest,
    TailorForJobResponse,
)
from app.resume.store import (
    find_resume_variant,
    get_base_resume_model,
    read_resume_variant,
    read_variant_tailored_text,
    rename_resume_variant,
    store_resume_variant,
)
from app.services.fresh_resume_builder import build_fresh_tailored_resume
from app.services.pdf_resume import extract_jd_target_role_title
from app.services.resume_evidence import analyze_job_description
from app.services.tailor import extract_keywords

router = APIRouter(prefix="/api/extension", tags=["extension"])


def _require_autofill_allowed(user: dict) -> None:
    """Auto-fill spends AI credits, so the owner grants it per member (Members page).
    A bidder needs their own grant, not their team member's. Job detection and
    application tracking don't use AI and keep working either way."""
    if not user_can_use_autofill(user):
        raise HTTPException(
            status_code=403,
            detail="Auto-fill isn't turned on for your account. Ask the site owner to enable it on the Members page.",
        )


def _job_text(job: DetectedJob) -> str:
    return (job.text or "").strip() or (job.page_title or "").strip()


def _profile_for_display(stored: dict) -> dict:
    """Never return the encrypted application password over HTTP — only whether one is set."""
    display = {k: v for k, v in stored.items() if k != "application_password_enc"}
    display["has_application_password"] = bool(stored.get("application_password_enc"))
    return display


@router.get("/profile", response_model=ExtensionProfileResponse)
async def get_extension_profile(user: dict = Depends(get_builder_user)) -> ExtensionProfileResponse:
    owner = await profile_owner(user)
    return ExtensionProfileResponse(
        name=user.get("name") or "",
        email=user.get("email") or "",
        has_base_resume=isinstance(owner.get("base_resume_model"), dict),
        autofill_profile=_profile_for_display(owner.get("autofill_profile") or {}),
        read_only=owner is not user,
        profile_owner_name=(owner.get("name") or owner.get("email") or "") if owner is not user else "",
    )


@router.put("/profile", response_model=ExtensionProfileResponse)
async def put_extension_profile(
    body: AutofillProfile,
    user: dict = Depends(get_builder_user),
) -> ExtensionProfileResponse:
    if works_from_team_member(user):
        raise HTTPException(
            status_code=403,
            detail="Bidders use their team member's autofill profile — only the team member can change it.",
        )
    clean = normalize_autofill_profile(body.model_dump())
    stored = user.get("autofill_profile") or {}
    new_password = clean.pop("application_password", "")
    if new_password:
        clean["application_password_enc"] = encrypt_secret(new_password)
    elif stored.get("application_password_enc"):
        # Blank submission means "unchanged" — never silently wipe a saved secret.
        clean["application_password_enc"] = stored["application_password_enc"]

    db = get_db()
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"autofill_profile": clean, "updated_at": datetime.now(UTC)}},
    )
    return ExtensionProfileResponse(
        name=user.get("name") or "",
        email=user.get("email") or "",
        has_base_resume=isinstance(user.get("base_resume_model"), dict),
        autofill_profile=_profile_for_display(clean),
    )


@router.post("/analyze-job", response_model=AnalyzeJobResponse)
async def analyze_job(
    body: DetectedJob,
    _user: dict = Depends(get_builder_user),
) -> AnalyzeJobResponse:
    text = _job_text(body)
    if not text:
        raise HTTPException(status_code=400, detail="No job text detected on the page.")
    analysis = analyze_job_description(text)

    def _skills(bucket: str) -> list[str]:
        return [
            str(item.get("skill", "")).strip()
            for item in analysis.get(bucket, [])
            if str(item.get("skill", "")).strip()
        ][:20]

    return AnalyzeJobResponse(
        company=body.company,
        job_title=body.job_title or (extract_jd_target_role_title(text) or ""),
        location=body.location,
        seniority=str(analysis.get("seniority") or ""),
        keywords=[k for k in extract_keywords(text, top_k=20)],
        required=_skills("required"),
        preferred=_skills("preferred"),
    )


@router.post("/autofill", response_model=AutofillResponse)
async def autofill(
    body: AutofillRequest,
    user: dict = Depends(get_builder_user),
) -> AutofillResponse:
    _require_autofill_allowed(user)
    # Bidders fill applications as their team member: that member's resume + profile.
    owner = await profile_owner(user)
    model = get_base_resume_model(owner)
    stored_profile = owner.get("autofill_profile") or {}
    profile = normalize_autofill_profile(stored_profile)
    if stored_profile.get("application_password_enc"):
        # Decrypted only transiently, in memory, to fill an actual form field —
        # never persisted or returned over HTTP in plaintext.
        profile["application_password"] = decrypt_secret(stored_profile["application_password_enc"])
    fields = [f.model_dump() for f in body.fields]

    resolved = resolve_deterministic_values(
        fields=fields,
        profile=profile,
        model=model,
        email=owner.get("email") or "",
    )
    free_text = unresolved_free_text_fields(fields, resolved)

    # Attach a resume: an explicit variant, else one already tailored for THIS job,
    # else nothing. Never another job's resume: it would go out to the wrong employer.
    attachment: ResumeAttachment | None = None
    variant_id = body.resume_variant_id
    if not variant_id:
        existing = await find_resume_variant(user_id=user["_id"], job_hash=job_hash(body.job.url))
        variant_id = existing[0] if existing else None
    if variant_id:
        found = await read_resume_variant(user_id=user["_id"], variant_id=variant_id)
        if found:
            _data, filename, _ct = found
            attachment = ResumeAttachment(
                variant_id=variant_id,
                filename=filename,
                download_path=f"/api/extension/resume/{variant_id}",
            )

    answers, drafts = await draft_free_text_answers(
        fields=free_text,
        model=model,
        profile=profile,
        job_text=_job_text(body.job),
        job_title=body.job.job_title,
        company=body.job.company,
        tailored_text=(
            await read_variant_tailored_text(user_id=user["_id"], variant_id=variant_id)
            if free_text and attachment
            else ""
        ),
    )
    questions = [
        ApplicationQuestion(
            key=str(f.get("key")),
            label=str(f.get("label") or f.get("name") or "Application question"),
            answer=drafts.get(str(f.get("key")), ""),
        )
        for f in free_text
        if str(f.get("key")) not in answers
    ]

    values = {
        key: AutofillValue(**payload) for key, payload in resolved.items()
    }
    unfilled = [
        str(f["key"])
        for f in fields
        if str(f["key"]) not in values and str(f["key"]) not in answers and f.get("required")
    ]
    return AutofillResponse(
        values=values,
        answers=answers,
        questions=questions,
        resume=attachment,
        application_id=None,
        unfilled=unfilled,
    )


@router.post("/tailor", response_model=TailorForJobResponse)
async def tailor_for_job(
    body: TailorForJobRequest,
    user: dict = Depends(get_builder_user),
) -> TailorForJobResponse:
    _require_autofill_allowed(user)
    # Own base resume, or (bidders) the assigned team member's — lock-checked.
    model = await base_resume_for(user)
    jh = job_hash(body.job.url)
    # Multi-step forms and repeat clicks reach here again: don't pay to re-tailor
    # the same job unless the base resume has changed since.
    owner = await profile_owner(user)
    file_stem = resume_file_stem(owner.get("autofill_profile") or {}, model)
    existing = await find_resume_variant(
        user_id=user["_id"],
        job_hash=jh,
        not_before=owner.get("base_resume_updated_at"),
        with_text=True,
    )
    if existing:
        variant_id, filename = existing
        # Stored under an older name, or the profile name has changed since.
        if filename != f"{file_stem}.pdf":
            filename = f"{file_stem}.pdf"
            await rename_resume_variant(variant_id, filename)
        docx = await find_resume_variant(user_id=user["_id"], job_hash=jh + ":docx")
        if docx and docx[1] != f"{file_stem}.docx":
            await rename_resume_variant(docx[0], f"{file_stem}.docx")
        return TailorForJobResponse(
            resume=ResumeAttachment(
                variant_id=variant_id,
                filename=filename,
                download_path=f"/api/extension/resume/{variant_id}",
            ),
            docx_variant_id=docx[0] if docx else "",
            match_scores={},
            application_id=None,
        )

    text = _job_text(body.job)
    if len(text) < 40:
        raise HTTPException(status_code=400, detail="Not enough job text to tailor against.")

    try:
        result = await build_fresh_tailored_resume(
            resume_model=model,
            original_filename=f"{(model.name or 'resume').split(' ')[0]}-resume.docx",
            job_description=text,
            target_job_role=body.target_job_role.strip(),
            sample_mode=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pdf_filename = f"{file_stem}.pdf"
    pdf_id = await store_resume_variant(
        user_id=user["_id"],
        job_hash=jh,
        filename=pdf_filename,
        content_type="application/pdf",
        data=base64.b64decode(result.pdf_base64),
        meta={"kind": "pdf", "job_url": body.job.url, "tailored_text": result.tailored_resume},
    )
    docx_id = await store_resume_variant(
        user_id=user["_id"],
        job_hash=jh + ":docx",
        filename=f"{file_stem}.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data=base64.b64decode(result.docx_base64),
        meta={"kind": "docx", "job_url": body.job.url},
    )

    # No application record is created here — the tracker only records a job
    # once the user actually submits it (see the background service worker's
    # "frame:submitted" handling). If an application for this job already
    # exists (the user submitted, then came back to re-tailor), attach this
    # fresh resume + score to it.
    await get_db().applications.update_one(
        {"user_id": user["_id"], "job_hash": jh},
        {"$set": {"resume_variant_id": pdf_id, "scores": result.match_scores}},
    )

    return TailorForJobResponse(
        resume=ResumeAttachment(
            variant_id=pdf_id,
            filename=pdf_filename,
            download_path=f"/api/extension/resume/{pdf_id}",
        ),
        docx_variant_id=docx_id,
        match_scores=result.match_scores,
        application_id=None,
    )


@router.get("/resume/{variant_id}")
async def download_resume_variant(
    variant_id: str,
    user: dict = Depends(get_builder_user),
) -> Response:
    found = await read_resume_variant(user_id=user["_id"], variant_id=variant_id)
    if not found:
        raise HTTPException(status_code=404, detail="Resume file not found.")
    data, filename, content_type = found
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
