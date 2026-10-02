"""Discover catalogue seed (`catalogue.yaml`, curated and URL-verified by the research
workstream). Idempotent upsert by key.

Trust rule applied on the way in: a row may only be stored as `official_guidance` when its
source is an official government domain; anything else is downgraded to `community_web`.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Community, CulturalGuide, Event
from app.domain.enums import EvidenceKind
from app.domain.provenance import is_official_source

logger = logging.getLogger("adapt.seed")
CATALOGUE_FILE = Path(__file__).with_name("catalogue.yaml")
_SKIP = frozenset({"id", "created_at", "updated_at"})


def _columns(model: Any) -> frozenset[str]:
    return frozenset(c.key for c in model.__table__.columns if c.key not in _SKIP)


def load_catalogue(path: Path = CATALOGUE_FILE) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return datetime.fromisoformat(str(value))


def _evidence_kind(raw: dict[str, Any]) -> EvidenceKind:
    kind = EvidenceKind(raw.get("evidence_kind") or EvidenceKind.COMMUNITY_WEB)
    url = raw.get("source_url")
    official = bool(url) and is_official_source(str(url))
    if kind in (EvidenceKind.OFFICIAL_GUIDANCE, EvidenceKind.AUTHORITATIVE_REQUIREMENT):
        if not official:
            logger.warning(
                "catalogue row %s stored as community_web: source not official", raw["key"]
            )
            return EvidenceKind.COMMUNITY_WEB
        return EvidenceKind.OFFICIAL_GUIDANCE  # the catalogue never stores requirements
    return kind


def catalogue_row(model: Any, raw: dict[str, Any], reviewed_on: Any) -> dict[str, Any]:
    columns = _columns(model)
    values = {k: v for k, v in raw.items() if k in columns}
    values["retrieved_at"] = _as_datetime(raw.get("retrieved_at") or reviewed_on)
    for key in ("starts_at", "ends_at"):
        if key in values:
            values[key] = _as_datetime(values[key])
    values["evidence_kind"] = _evidence_kind(raw).value
    values["is_sample"] = bool(raw.get("is_sample", False))
    for key in ("languages", "tags"):
        if key in columns:
            values[key] = list(raw.get(key) or [])
    if model is Event and not values.get("starts_at") and not values.get("timing_note"):
        values["timing_note"] = "Dates vary from year to year; check the official page."
    return values


async def seed_catalogue(session: AsyncSession, data: dict[str, Any]) -> dict[str, int]:
    reviewed_on = data.get("reviewed_on")
    counts: dict[str, int] = {}
    for section, model in (
        ("communities", Community),
        ("events", Event),
        ("cultural_guides", CulturalGuide),
    ):
        rows = data.get(section) or []
        for raw in rows:
            values = catalogue_row(model, raw, reviewed_on)
            stmt = insert(model).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={k: stmt.excluded[k] for k in values if k != "key"},
            )
            await session.execute(stmt)
        counts[section] = len(rows)
    return counts
