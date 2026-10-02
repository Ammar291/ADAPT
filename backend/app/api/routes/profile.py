"""Onboarding and profile."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import PrincipalDep, UserSession
from app.contracts.profile import FullProfileOut, OnboardingProfileRequest, ProfileUpdate
from app.services import profile as profile_service
from app.services.presenters import full_profile_out

router = APIRouter(tags=["profile"])


@router.post(
    "/onboarding/profile",
    response_model=FullProfileOut,
    summary="Complete onboarding",
    description="Saves the profile, household, goals and preferences in one transaction "
    "and rebuilds the private user graph from them. Household, goals and preferences "
    "replace any earlier answers.",
)
async def onboarding_profile(
    body: OnboardingProfileRequest, principal: PrincipalDep, session: UserSession
) -> FullProfileOut:
    bundle = await profile_service.onboard(session, principal, body)
    await session.commit()
    return full_profile_out(bundle, profile_service.missing_for_planning(bundle))


@router.get("/profile", response_model=FullProfileOut, summary="Your profile")
async def read_profile(principal: PrincipalDep, session: UserSession) -> FullProfileOut:
    bundle = await profile_service.load(session, principal)
    return full_profile_out(bundle, profile_service.missing_for_planning(bundle))


@router.patch(
    "/profile",
    response_model=FullProfileOut,
    summary="Update your profile",
    description="Partial update: omitted fields are unchanged; a provided list "
    "(household, goals, preferences) replaces the whole set.",
)
async def update_profile(
    body: ProfileUpdate, principal: PrincipalDep, session: UserSession
) -> FullProfileOut:
    bundle = await profile_service.update(session, principal, body)
    await session.commit()
    return full_profile_out(bundle, profile_service.missing_for_planning(bundle))
