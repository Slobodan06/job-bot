"""Whose resume a user generates from.

* The owner and **team members** are trusted: they can use any resume — upload one
  in the builder, or use their own **base resume** (managed on their Profile page).
* **Bidders** never upload a resume. The owner assigns each bidder to a team member,
  and everything the bidder generates (tailored resume, cover letter, answers,
  extension autofill) uses that team member's base resume and autofill profile,
  which the bidder can see but not change.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from app.auth.roles import member_type, user_is_owner
from app.database import get_db
from app.services.resume_model import ResumeModel


def works_from_team_member(user: dict) -> bool:
    return not user_is_owner(user) and member_type(user) == "bidder"


@dataclass
class ResumeAccess:
    # True for bidders: no uploads; they use their team member's base resume.
    uses_team_member_resume: bool
    team_member_name: str = ""
    # Why a bidder can't generate yet (e.g. not assigned), shown to them.
    reason: str = ""


async def _assigned_team_member(user: dict) -> dict | None:
    tm_id = user.get("assigned_team_member_id")
    team_member = await get_db().users.find_one({"_id": tm_id}) if tm_id else None
    if not team_member or user_is_owner(team_member) or member_type(team_member) != "team_member":
        return None
    return team_member


async def resume_access_for(user: dict) -> ResumeAccess:
    if not works_from_team_member(user):
        return ResumeAccess(uses_team_member_resume=False)
    team_member = await _assigned_team_member(user)
    if team_member is None:
        return ResumeAccess(
            uses_team_member_resume=True,
            reason="You haven't been assigned to a team member yet — ask the site owner.",
        )
    return ResumeAccess(
        uses_team_member_resume=True,
        team_member_name=team_member.get("name") or team_member.get("email") or "",
    )


async def profile_owner(user: dict) -> dict:
    """The user doc whose base resume and autofill profile apply to `user`."""
    if not works_from_team_member(user):
        return user
    team_member = await _assigned_team_member(user)
    if team_member is None:
        raise HTTPException(
            status_code=403,
            detail="You haven't been assigned to a team member yet — ask the site owner.",
        )
    return team_member


def reject_bidder_upload(user: dict) -> None:
    if works_from_team_member(user):
        raise HTTPException(
            status_code=403,
            detail="Bidders work from their team member's base resume — uploading a resume isn't allowed.",
        )


async def base_resume_for(user: dict) -> ResumeModel:
    """The base resume `user` generates from: their own, or (bidders) their team member's."""
    from app.resume.store import get_base_resume_model

    owner = await profile_owner(user)
    model = get_base_resume_model(owner)
    if model is None:
        if owner is not user:
            label = owner.get("name") or owner.get("email") or "Your team member"
            raise HTTPException(
                status_code=400,
                detail=f"{label} hasn't saved a base resume yet — ask them to upload it on their Profile page.",
            )
        raise HTTPException(
            status_code=400,
            detail="Upload a resume, or save a base resume on your Profile page first.",
        )
    return model
