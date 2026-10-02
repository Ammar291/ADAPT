"""Accounts. `tenants` and `users` are protected by RLS too: an account is only visible
inside a transaction scoped to it, so a new account is created by first claiming its
(random) ids as the transaction's principal."""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.auth import UserPreferences, UserPreferencesUpdate
from app.db.models import Tenant, User
from app.db.session import Database
from app.domain.principal import Principal


def new_account_principal(*, is_demo: bool) -> Principal:
    return Principal(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), is_demo=is_demo)


async def create_account(
    db: Database,
    *,
    display_name: str | None,
    ui_locale: str | None = None,
    is_demo: bool,
    auth_provider: str = "demo",
    auth_subject: str | None = None,
    principal: Principal | None = None,
) -> User:
    """One tenant per personal account: accounts never share a tenant."""
    principal = principal or new_account_principal(is_demo=is_demo)
    async with db.user_session(principal) as session:
        session.add(Tenant(id=principal.tenant_id, name="Personal", is_demo=is_demo))
        await session.flush()
        preferences = UserPreferences(ui_locale=ui_locale or "en")
        user = User(
            id=principal.user_id,
            tenant_id=principal.tenant_id,
            display_name=display_name,
            is_demo=is_demo,
            preferences=preferences.model_dump(mode="json"),
            auth_provider=auth_provider,
            auth_subject=auth_subject,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        await session.commit()
        return user


async def resolve_identity(session: AsyncSession, provider: str, subject: str) -> Principal | None:
    """Find the account linked to an identity-provider subject (SECURITY DEFINER lookup:
    the runtime role cannot otherwise see accounts outside its own transaction scope)."""
    row = (
        await session.execute(
            text("SELECT user_id, tenant_id FROM app_resolve_identity(:provider, :subject)"),
            {"provider": provider, "subject": subject},
        )
    ).first()
    if row is None:
        return None
    return Principal(user_id=row.user_id, tenant_id=row.tenant_id)


async def get_user(session: AsyncSession, user_id: UUID, tenant_id: UUID) -> User | None:
    return (
        await session.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    ).scalar_one_or_none()


def read_preferences(user: User) -> UserPreferences:
    return UserPreferences.model_validate(user.preferences or {})


async def update_preferences(
    session: AsyncSession, user: User, update: UserPreferencesUpdate
) -> User:
    # Every stored preference has a value, so an explicit null in the update means "leave
    # it as it is" (clients echo full objects back), never "erase it".
    changes = update.model_dump(exclude_unset=True, exclude_none=True)
    merged = read_preferences(user).model_copy(update=changes)
    user.preferences = UserPreferences.model_validate(merged.model_dump()).model_dump(mode="json")
    await session.flush()
    await session.refresh(user)
    return user


async def delete_account(session: AsyncSession, principal: Principal) -> None:
    """Delete the caller's account; foreign keys cascade every private row."""
    await session.execute(
        text("DELETE FROM tenants WHERE id = :tenant_id"), {"tenant_id": principal.tenant_id}
    )
