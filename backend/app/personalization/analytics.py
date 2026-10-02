"""Privacy-safe product analytics for the document pipeline and the user graph.

Rule: analytics never contain raw personal data. An event is a name plus properties that
are booleans, numbers, or short machine tokens (enum values, field names, provider ids),
never values, names, file names, free text or user identifiers. Anything else is dropped
before it leaves this module, and the count of dropped properties is recorded so the
mistake is visible without the data.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("adapt.analytics")

_TOKEN = re.compile(r"^[a-z0-9_.:+-]{1,64}$")
# Property keys are allow-listed: a token-shaped string can still be personal (a first
# name in lower case), so only keys whose values are known to be vocabulary are accepted.
ALLOWED_KEYS = frozenset(
    {
        "kind", "declared_kind", "subject", "provider", "method", "outcome", "status",
        "stage", "reason", "source", "entity_type", "attribute", "resolution", "change",
        "field_count", "fact_count", "accepted_count", "needs_review_count", "task_count",
        "duration_ms", "size_kb", "kind_mismatch", "mrz_verified",
    }
)  # fmt: skip

AnalyticsEvent = dict[str, Any]
# Test hooks and exporters. Each receives the already-sanitised event.
sinks: list[Callable[[AnalyticsEvent], None]] = []


def _safe(value: Any) -> bool:
    if value is None or isinstance(value, bool | int | float):
        return True
    return isinstance(value, str) and bool(_TOKEN.match(value))


def track(event: str, **properties: Any) -> AnalyticsEvent:
    if not _TOKEN.match(event):
        raise ValueError("analytics event names are lower-case tokens")
    clean: dict[str, Any] = {}
    dropped = 0
    for key, value in properties.items():
        if key not in ALLOWED_KEYS or not _safe(value):
            dropped += 1
            continue
        clean[key] = value
    if dropped:
        clean["dropped_properties"] = dropped
    record: AnalyticsEvent = {"event": event, **clean}
    logger.info("analytics_event", extra={"analytics": record})
    for sink in list(sinks):
        sink(record)
    return record
