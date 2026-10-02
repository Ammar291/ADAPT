from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey


class Tenant(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class User(Base, UUIDPrimaryKey, Timestamps):
    """Account record. Holds no identity-document data: that lives in the private twin.

    `auth_provider` / `auth_subject` link the account to an identity provider (see
    `app.core.auth`); demo accounts have provider 'demo' and no subject. `preferences`
    holds account settings and consents (language, faith/community personalisation).
    """

    __tablename__ = "users"
    __table_args__ = (
        Index(
            "uq_users_auth_identity",
            "auth_provider",
            "auth_subject",
            unique=True,
            postgresql_where=text("auth_subject IS NOT NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(120))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    auth_provider: Mapped[str] = mapped_column(String(40), nullable=False, server_default="demo")
    auth_subject: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
