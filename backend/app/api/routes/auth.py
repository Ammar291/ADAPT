from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import ContainerDep, PrincipalDep, UserSession, get_optional_principal
from app.contracts.auth import DemoSessionRequest, SessionOut, UserOut, UserPreferencesUpdate
from app.core.auth import DemoIdentityProvider, sign_in
from app.core.config import Settings
from app.core.errors import Forbidden, Unauthorized
from app.core.security import issue_session_token
from app.db.models import User
from app.domain.principal import Principal
from app.repositories import accounts
from app.services.presenters import user_out

router = APIRouter(tags=["auth"])

# The cookie is scoped to the API; it is httpOnly so JavaScript can never read it.
COOKIE_PATH = "/api"
_demo_provider = DemoIdentityProvider()


def _set_session_cookie(response: Response, settings: Settings, principal: Principal) -> datetime:
    issued = issue_session_token(
        principal,
        secret=settings.session_secret.get_secret_value(),
        ttl_hours=settings.session_ttl_hours,
    )
    response.set_cookie(
        settings.session_cookie_name,
        issued.token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )
    return issued.expires_at


async def _require_user(session: UserSession, principal: Principal) -> User:
    user = await accounts.get_user(session, principal.user_id, principal.tenant_id)
    if user is None:
        raise Unauthorized("Your account no longer exists", code="account_missing")
    return user


@router.post(
    "/auth/demo-session",
    response_model=SessionOut,
    summary="Start (or resume) a demo session",
    description="Creates a private demo account and sets an httpOnly session cookie. "
    "A caller that already holds a valid session gets it refreshed instead.",
)
async def demo_session(
    body: DemoSessionRequest,
    response: Response,
    container: ContainerDep,
    principal: Annotated[Principal | None, Depends(get_optional_principal)],
) -> SessionOut:
    settings = container.settings
    if not settings.demo_auth_enabled:
        raise Forbidden("Demo sign-in is disabled", code="demo_auth_disabled")

    if principal is not None and not body.sample_household:
        async with container.db.user_session(principal) as session:
            existing = await accounts.get_user(session, principal.user_id, principal.tenant_id)
        if existing is not None:
            expires_at = _set_session_cookie(response, settings, principal)
            return SessionOut(user=user_out(existing), expires_at=expires_at)

    identity = await _demo_provider.identify(display_name=body.display_name, locale=body.ui_locale)
    new_principal = await sign_in(container.db, identity)
    if body.sample_household:
        # Copy synthetic fixtures into a fresh account. Never issue a session for the
        # shared seed account: another visitor could have changed its private data.
        from app.seed.demo import seed_demo_household

        await seed_demo_household(container.db, principal=new_principal)
    async with container.db.user_session(new_principal) as session:
        user = await accounts.get_user(session, new_principal.user_id, new_principal.tenant_id)
    assert user is not None
    expires_at = _set_session_cookie(response, settings, new_principal)
    return SessionOut(user=user_out(user), expires_at=expires_at)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the session")
async def logout(container: ContainerDep) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(container.settings.session_cookie_name, path=COOKIE_PATH)
    return response


@router.get("/me", response_model=UserOut, tags=["me"], summary="The signed-in user")
async def me(principal: PrincipalDep, session: UserSession) -> UserOut:
    return user_out(await _require_user(session, principal))


@router.patch(
    "/me/preferences",
    response_model=UserOut,
    tags=["me"],
    summary="Update language and personalisation consents",
)
async def update_preferences(
    body: UserPreferencesUpdate, principal: PrincipalDep, session: UserSession
) -> UserOut:
    user = await accounts.update_preferences(session, await _require_user(session, principal), body)
    await session.commit()
    return user_out(user)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["me"],
    summary="Delete your account and every private record",
    description="Deletes the account; database cascades remove all private rows "
    "(profile, graph, journeys, runs, documents metadata, actions).",
)
async def delete_me(
    principal: PrincipalDep, session: UserSession, container: ContainerDep
) -> Response:
    await _require_user(session, principal)
    await accounts.delete_account(session, principal)
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(container.settings.session_cookie_name, path=COOKIE_PATH)
    return response
