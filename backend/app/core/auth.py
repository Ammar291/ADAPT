"""Authentication abstraction.

Two separate concerns:

* **Sessions** (`app.core.security`): every request is authenticated by a signed session
  token (httpOnly cookie, or `Authorization: Bearer` for tools and tests) that resolves to
  a `Principal`. Nothing downstream knows how the user signed in.
* **Identity providers** (this module): how a person proves who they are *before* a
  session exists. An `IdentityProvider` turns a sign-in attempt into an
  `ExternalIdentity`; `sign_in` maps that identity to an account (creating it on first
  use) and returns the `Principal` to issue a session for.

Only the demo provider ships: it creates a fresh private account per sign-in and has no
subject. A production OIDC provider would return a stable `subject` and plug in here with
no schema change (`users.auth_provider` / `users.auth_subject`). ADAPT never acts as, or
collects credentials for, UAE PASS — government services that need it are handed off.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.db.session import Database
from app.domain.principal import Principal
from app.repositories import accounts


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    provider: str
    subject: str | None  # stable id at the provider; None means "always a new account"
    display_name: str | None = None
    locale: str | None = None
    is_demo: bool = False


class IdentityProvider(Protocol):
    name: str

    async def identify(
        self, *, display_name: str | None = None, locale: str | None = None
    ) -> ExternalIdentity: ...


class DemoIdentityProvider:
    """Private demo accounts: one fresh account per sign-in, no credentials involved."""

    name = "demo"

    async def identify(
        self, *, display_name: str | None = None, locale: str | None = None
    ) -> ExternalIdentity:
        return ExternalIdentity(
            provider=self.name,
            subject=None,
            display_name=display_name,
            locale=locale,
            is_demo=True,
        )


async def sign_in(db: Database, identity: ExternalIdentity) -> Principal:
    """Resolve (or create) the account for `identity`."""
    if identity.subject is not None:
        async with db.public_session() as session:
            existing = await accounts.resolve_identity(session, identity.provider, identity.subject)
        if existing is not None:
            return Principal(
                user_id=existing.user_id, tenant_id=existing.tenant_id, is_demo=identity.is_demo
            )
    user = await accounts.create_account(
        db,
        display_name=identity.display_name,
        ui_locale=identity.locale,
        is_demo=identity.is_demo,
        auth_provider=identity.provider,
        auth_subject=identity.subject,
    )
    return Principal(user_id=user.id, tenant_id=user.tenant_id, is_demo=identity.is_demo)
