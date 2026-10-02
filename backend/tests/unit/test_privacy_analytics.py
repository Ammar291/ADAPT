"""Analytics never carry raw personal data."""

from __future__ import annotations

from typing import Any

import pytest

from app.personalization import analytics


@pytest.fixture
def recorded() -> Any:
    events: list[dict[str, Any]] = []
    analytics.sinks.append(events.append)
    yield events
    analytics.sinks.remove(events.append)


def test_only_allow_listed_vocabulary_passes(recorded: list[dict[str, Any]]) -> None:
    record = analytics.track(
        "document_processed",
        kind="passport",
        method="local:pdf-text+mrz",
        field_count=5,
        kind_mismatch=False,
        duration_ms=120,
    )
    assert record == {
        "event": "document_processed",
        "kind": "passport",
        "method": "local:pdf-text+mrz",
        "field_count": 5,
        "kind_mismatch": False,
        "duration_ms": 120,
    }
    assert recorded == [record]


@pytest.mark.parametrize(
    "props",
    [
        {"name": "priya"},  # token-shaped, but not an allow-listed key
        {"user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"},
        {"kind": "Arjun Mehta"},  # allow-listed key, but free text
        {"value": "1990-04-12"},
        {"filename": "arjun-passport.pdf"},
        {"source": {"nested": "dict"}},
    ],
)
def test_personal_data_is_dropped(props: dict[str, Any], recorded: list[dict[str, Any]]) -> None:
    record = analytics.track("fact_added", **props)
    assert record == {"event": "fact_added", "dropped_properties": 1}


def test_event_names_are_tokens() -> None:
    with pytest.raises(ValueError):
        analytics.track("Uploaded passport of Arjun")
