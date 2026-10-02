"""Shape API results for a language model: small, relevant, and privacy-preserving.

Tool outputs go back into the model's context and may be spoken aloud, so they are:

* trimmed: long lists and strings are cut, empty values and internal plumbing dropped;
* masked: identifier-like values (passport, Emirates ID, document, card and account
  numbers) keep only their last three characters, because a spoken number can be
  overheard. The full values stay visible to the user in the app.

Shaping is schema-agnostic on purpose. It works on whatever JSON the feature routes return,
so it keeps working while those contracts evolve.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

# Never useful to the model, and some are internal identifiers of other systems.
_DROP_KEYS = frozenset(
    {
        "embedding",
        "embeddings",
        "tenant_id",
        "user_id",
        "storage_key",
        "sha256",
        "content_hash",
        "thread_id",
        "bbox",
        "events_url",
        # Signed, short-lived links to private files: never into a model's context.
        "content_url",
        "download_url",
        "signed_url",
    }
)
_IDENTIFIER_KEY = re.compile(
    r"(^|[_.])(number|no|num|iban|mrz|emirates_id|eid|passport|id_card)$", re.IGNORECASE
)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def mask(value: str) -> str:
    return f"•••{value[-3:]}" if len(value) > 3 else "•••"


def _should_mask(key: str | None, value: Any) -> bool:
    return (
        key is not None
        and isinstance(value, str)
        and len(value) >= 4
        and bool(_IDENTIFIER_KEY.search(key))
        and not _is_uuid(value)
    )


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _compact(value: Any, *, key: str | None, items: int, chars: int, depth: int) -> Any:
    if depth <= 0:
        return "…"
    if isinstance(value, dict):
        # Extracted fields and facts look like {name|attribute: "passport_number", value: "…"}.
        named = value.get("name") or value.get("attribute")
        field_name = named if isinstance(named, str) else None
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in _DROP_KEYS or _empty(v):
                continue
            effective_key = field_name if k in ("value", "value_display") and field_name else k
            out[k] = _compact(v, key=effective_key, items=items, chars=chars, depth=depth - 1)
        return out
    if isinstance(value, list):
        kept = [
            _compact(v, key=key, items=items, chars=chars, depth=depth - 1)
            for v in value[:items]
            if not _empty(v)
        ]
        if len(value) > items:
            kept.append(f"(+{len(value) - items} more in the app)")
        return kept
    if _should_mask(key, value):
        return mask(value)
    if isinstance(value, str) and len(value) > chars:
        return value[: chars - 1].rstrip() + "…"
    return value


def shape(value: Any, *, budget: int = 12_000) -> Any:
    """Compact `value` until its JSON fits in `budget` characters."""
    for items, chars, depth in ((12, 600, 7), (8, 300, 6), (4, 200, 5), (2, 120, 4)):
        shaped = _compact(value, key=None, items=items, chars=chars, depth=depth)
        if len(json.dumps(shaped, ensure_ascii=False, default=str)) <= budget:
            return shaped
    return shaped
