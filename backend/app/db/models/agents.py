"""Agent runs and their durable, replayable event log (RLS owner-only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Owned, UUIDPrimaryKey
from app.db.types import enum_check, str_enum
from app.domain.enums import RunKind, RunStatus


class AgentRun(Base, UUIDPrimaryKey, Owned):
    __tablename__ = "agent_runs"
    __table_args__ = (
        enum_check("kind", RunKind),
        enum_check("status", RunStatus),
        Index("ix_agent_runs_user_created", "user_id", "created_at"),
    )

    agent: Mapped[str] = mapped_column(
        String(80), nullable=False, doc="Registered agent name, e.g. 'journey', 'diagnostic'"
    )
    kind: Mapped[RunKind] = mapped_column(str_enum(RunKind), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        str_enum(RunStatus), nullable=False, server_default=RunStatus.QUEUED.value
    )
    journey_id: Mapped[UUID | None] = mapped_column(ForeignKey("journeys.id", ondelete="SET NULL"))
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The open human-in-the-loop gate while the run is `awaiting_input` (cleared on answer).
    pending_review: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    event_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    job_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentEvent(Base, Owned):
    """One streamed agent event. `payload` is the exact JSON sent to clients."""

    __tablename__ = "agent_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_agent_events_run_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(String(60), nullable=False)
    node: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
