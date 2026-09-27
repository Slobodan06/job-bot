from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import BulkWriteError

from app.auth.dependencies import get_builder_user, get_owner_user
from app.database import get_db
from app.extension.crypto import decrypt_secret, encrypt_secret
from app.job_boards.logic import (
    ApiKeyRequiredError,
    KEYED_PLATFORMS,
    UnsupportedBoardError,
    board_doc_to_public,
    board_url_for,
    build_board_doc,
    build_job_docs,
    job_doc_to_listing,
    keyed_platform_label,
    keyed_platform_signup_note,
    keyed_platform_signup_url,
    keyed_platform_url,
    parse_board_url,
)
from app.job_boards.schemas import (
    AddJobBoardRequest,
    AddJobBoardResponse,
    JobBoardListResponse,
    JobBoardPublic,
    PlatformCredentialListResponse,
    PlatformCredentialPublic,
    SetPlatformCredentialRequest,
)
from app.jobs.schemas import JobListing, JobSearchResponse
from app.services.job_boards import fetch_board_jobs, fetch_keyed_platform_jobs

router = APIRouter(prefix="/api/job-boards", tags=["job-boards"])


@router.post("", response_model=AddJobBoardResponse)
async def add_job_board(
    body: AddJobBoardRequest,
    owner: dict = Depends(get_owner_user),
) -> AddJobBoardResponse:
    """Admin-only: track a new source and pull its current matches. Board sources and
    the jobs they produce are shared app-wide — every team member sees the results
    via the GET endpoints below, but only an owner can add or remove a source.
    """
    db = get_db()
    api_key: str | None = None
    try:
        platform, token = parse_board_url(body.url)
    except ApiKeyRequiredError as e:
        cred = await db.platform_credentials.find_one({"_id": e.platform})
        if not cred or not cred.get("api_key_enc"):
            raise HTTPException(
                status_code=428,
                detail={
                    "platform": e.platform,
                    "label": e.label,
                    "message": str(e),
                    "signup_url": e.signup_url,
                    "signup_note": e.signup_note,
                },
            ) from e
        platform, token = e.platform, e.platform
        api_key = decrypt_secret(cred["api_key_enc"])
    except UnsupportedBoardError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        if api_key is not None:
            raw_jobs, company = await fetch_keyed_platform_jobs(platform, api_key)
            board_url = keyed_platform_url(platform)
        else:
            raw_jobs, company = await fetch_board_jobs(platform, token)
            board_url = board_url_for(platform, token)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    now = datetime.now(UTC)
    existing_board = await db.job_boards.find_one({"platform": platform, "token": token})
    if existing_board:
        board_id = existing_board["_id"]
    else:
        doc = build_board_doc(
            added_by=owner["_id"],
            platform=platform,
            token=token,
            board_url=board_url,
            company=company,
            now=now,
            job_count=0,
        )
        result = await db.job_boards.insert_one(doc)
        board_id = result.inserted_id

    job_docs, filtered_out = build_job_docs(
        board_id=board_id,
        platform=platform,
        raw_jobs=raw_jobs,
        now=now,
    )

    inserted = 0
    skipped_duplicate = 0
    if job_docs:
        try:
            result = await db.sourced_jobs.insert_many(job_docs, ordered=False)
            inserted = len(result.inserted_ids)
        except BulkWriteError as bwe:
            write_errors = (bwe.details or {}).get("writeErrors", [])
            other_errors = [e for e in write_errors if e.get("code") != 11000]
            if other_errors:
                raise HTTPException(status_code=500, detail="Failed to save some jobs.") from bwe
            skipped_duplicate = len(write_errors)
            inserted = len(job_docs) - skipped_duplicate

    company_name = company or (existing_board.get("company") if existing_board else "") or token
    await db.job_boards.update_one(
        {"_id": board_id},
        {
            "$set": {"last_synced_at": now, "company": company_name},
            "$inc": {"job_count": inserted},
        },
    )
    board_doc = await db.job_boards.find_one({"_id": board_id})

    return AddJobBoardResponse(
        board=JobBoardPublic(**board_doc_to_public(board_doc)),
        added_count=inserted,
        skipped_duplicate_count=skipped_duplicate,
        filtered_out_count=filtered_out,
    )


@router.get("", response_model=JobBoardListResponse)
async def list_job_boards(_user: dict = Depends(get_builder_user)) -> JobBoardListResponse:
    db = get_db()
    docs = await db.job_boards.find({}).sort("added_at", -1).to_list(200)
    return JobBoardListResponse(items=[JobBoardPublic(**board_doc_to_public(d)) for d in docs])


@router.get("/jobs", response_model=JobSearchResponse)
async def list_sourced_jobs(
    platform: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _user: dict = Depends(get_builder_user),
) -> JobSearchResponse:
    db = get_db()
    query: dict = {}
    if platform:
        query["platform"] = platform
    docs = await db.sourced_jobs.find(query).sort("posted_at", -1).limit(limit).to_list(limit)
    items = [JobListing(**job_doc_to_listing(d)) for d in docs]
    return JobSearchResponse(items=items, count=len(items))


@router.get("/platform-credentials", response_model=PlatformCredentialListResponse)
async def list_platform_credentials(
    _owner: dict = Depends(get_owner_user),
) -> PlatformCredentialListResponse:
    db = get_db()
    docs = {d["_id"]: d async for d in db.platform_credentials.find({})}
    items = [
        PlatformCredentialPublic(
            platform=platform,
            label=meta["label"],
            has_key=bool(docs.get(platform, {}).get("api_key_enc")),
            updated_at=docs.get(platform, {}).get("updated_at"),
            signup_url=meta.get("signup_url", ""),
            signup_note=meta.get("signup_note", ""),
        )
        for platform, meta in KEYED_PLATFORMS.items()
    ]
    return PlatformCredentialListResponse(items=items)


@router.put("/platform-credentials/{platform}", response_model=PlatformCredentialPublic)
async def set_platform_credential(
    platform: str,
    body: SetPlatformCredentialRequest,
    owner: dict = Depends(get_owner_user),
) -> PlatformCredentialPublic:
    if platform not in KEYED_PLATFORMS:
        raise HTTPException(status_code=404, detail="Unknown platform.")
    db = get_db()
    now = datetime.now(UTC)
    await db.platform_credentials.update_one(
        {"_id": platform},
        {
            "$set": {
                "api_key_enc": encrypt_secret(body.api_key.strip()),
                "updated_at": now,
                "added_by": owner["_id"],
            },
            "$setOnInsert": {"added_at": now},
        },
        upsert=True,
    )
    return PlatformCredentialPublic(
        platform=platform,
        label=keyed_platform_label(platform),
        has_key=True,
        updated_at=now,
        signup_url=keyed_platform_signup_url(platform),
        signup_note=keyed_platform_signup_note(platform),
    )


@router.delete("/platform-credentials/{platform}", status_code=204)
async def remove_platform_credential(
    platform: str, _owner: dict = Depends(get_owner_user)
) -> None:
    db = get_db()
    await db.platform_credentials.delete_one({"_id": platform})


@router.delete("/{board_id}", status_code=204)
async def remove_job_board(board_id: str, _owner: dict = Depends(get_owner_user)) -> None:
    if not ObjectId.is_valid(board_id):
        raise HTTPException(status_code=404, detail="Job board not found.")
    db = get_db()
    doc = await db.job_boards.find_one({"_id": ObjectId(board_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Job board not found.")
    await db.job_boards.delete_one({"_id": doc["_id"]})
    await db.sourced_jobs.delete_many({"board_id": doc["_id"]})
