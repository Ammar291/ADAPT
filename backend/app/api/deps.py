"""FastAPI dependencies: container, authenticated principal, RLS-scoped sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Container
from app.core.errors import Unauthorized
from app.core.origins import trusted_origin
from app.core.security import verify_session_token
from app.domain.principal import Principal


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


ContainerDep = Annotated[Container, Depends(get_container)]


def _token_from(request: Request, cookie_name: str) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(cookie_name)


def get_principal(request: Request, container: ContainerDep) -> Principal:
    token = _token_from(request, container.settings.session_cookie_name)
    if not token:
        raise Unauthorized("Sign in to continue", code="session_missing")
    return verify_session_token(token, secret=container.settings.session_secret.get_secret_value())


def get_optional_principal(request: Request, container: ContainerDep) -> Principal | None:
    try:
        return get_principal(request, container)
    except Unauthorized:
        return None


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def get_user_session(
    principal: PrincipalDep, container: ContainerDep
) -> AsyncIterator[AsyncSession]:
    """Session whose every transaction is scoped to the principal by RLS."""
    async with container.db.user_session(principal) as session:
        yield session


async def get_public_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    """Session with no principal: only governance/public data is visible."""
    async with container.db.public_session() as session:
        yield session


UserSession = Annotated[AsyncSession, Depends(get_user_session)]
PublicSession = Annotated[AsyncSession, Depends(get_public_session)]


def websocket_principal(websocket: WebSocket) -> Principal:
    """Principal for a WebSocket handshake (session cookie or `Authorization: Bearer`).

    Browsers send the session cookie with same-origin WebSocket handshakes, so the Origin
    header is checked too: a page on another site must never ride the user's session
    (cross-site WebSocket hijacking).
    """
    container: Container = websocket.app.state.container
    settings = container.settings
    origin = websocket.headers.get("origin")
    if origin is not None and not trusted_origin(
        origin,
        scheme=websocket.scope["scheme"],
        host=websocket.headers.get("host", ""),
        settings=settings,
    ):
        raise Unauthorized("This origin may not open a stream", code="origin_not_allowed")
    header = websocket.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    if origin is None and not token and websocket.cookies.get(settings.session_cookie_name):
        raise Unauthorized("A browser origin is required", code="origin_not_allowed")
    token = token or websocket.cookies.get(settings.session_cookie_name)
    if not token:
        raise Unauthorized("Sign in to continue", code="session_missing")
    return verify_session_token(token, secret=settings.session_secret.get_secret_value())
