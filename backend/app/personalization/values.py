"""Typed values for personal facts: normalisation, validation and display.

Every fact value in the private user graph has a `ValueKind`. Values arrive from people
(JSON from the API) or from documents (strings read by OCR/VLM); both pass through
`normalize`, which returns the canonical stored form or raises `ValueIssue` with a
user-facing reason. Canonical forms: dates are ISO `YYYY-MM-DD`, countries ISO 3166-1
alpha-3, languages ISO 639-1, money `{"amount": 25000.0, "currency": "AED"}`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from app.personalization.reference import (
    CURRENCIES,
    CURRENCY_ALIASES,
    country_code,
    country_name,
    language_code,
    language_name,
)


class ValueKind(StrEnum):
    TEXT = "text"
    DATE = "date"
    DATETIME = "datetime"
    COUNTRY = "country"
    LANGUAGE = "language"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    MONEY = "money"
    CHOICE = "choice"


class ValueIssue(ValueError):
    """The value cannot be stored as this kind. The message is safe to show the user
    (it never echoes the value itself)."""


@dataclass(frozen=True, slots=True)
class Normalized:
    value: Any
    # True when the raw text allowed more than one reading (e.g. 03/04/2020), so a
    # document-extracted value should be reviewed even if the reader was confident.
    ambiguous: bool = False


MAX_TEXT = 200
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_TRUE = {"true", "yes", "y", "1", "present", "attested", "provided", "on"}
_FALSE = {"false", "no", "n", "0", "absent", "none", "not attested", "not provided", "off"}


def _text(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueIssue("Expected text")
    text = re.sub(r"\s+", " ", _CONTROL.sub("", raw)).strip()
    if not text:
        raise ValueIssue("The value is empty")
    if len(text) > MAX_TEXT:
        raise ValueIssue(f"Keep it under {MAX_TEXT} characters")
    return text


def _date(raw: Any) -> Normalized:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return Normalized(raw.isoformat())
    text = _text(raw).lower().replace(",", " ")
    # Bilingual passports print e.g. "12 APR /AVR 1990": keep the first month token.
    text = re.sub(r"\s*/\s*[a-z]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text):
        return Normalized(_build_date(int(m[1]), int(m[2]), int(m[3])))
    if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", text):
        first, second, year = int(m[1]), int(m[2]), int(m[3])
        # Day-first, as printed in the UAE, India and most of the world.
        ambiguous = first <= 12 and second <= 12 and first != second
        return Normalized(_build_date(year, second, first), ambiguous=ambiguous)
    if m := re.fullmatch(r"(\d{1,2}) ([a-z]+)\.? (\d{4})", text):
        month = _MONTHS.get(m[2])
        if month:
            return Normalized(_build_date(int(m[3]), month, int(m[1])))
    if m := re.fullmatch(r"([a-z]+)\.? (\d{1,2}) (\d{4})", text):
        month = _MONTHS.get(m[1])
        if month:
            return Normalized(_build_date(int(m[3]), month, int(m[2])))
    raise ValueIssue("Use a full date, e.g. 2026-11-01")


def _build_date(year: int, month: int, day: int) -> str:
    try:
        value = date(year, month, day)
    except ValueError as exc:
        raise ValueIssue("That date does not exist") from exc
    if not 1900 <= value.year <= 2100:
        raise ValueIssue("That date is out of range")
    return value.isoformat()


def _datetime(raw: Any) -> str:
    text = _text(raw)
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _date(text).value  # a date alone is acceptable for an appointment
    if value.tzinfo is None:
        return value.isoformat(timespec="minutes")
    return value.astimezone(UTC).isoformat(timespec="minutes")


def _money(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        amount, currency = raw.get("amount"), raw.get("currency")
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            raise ValueIssue("The amount must be a number")
        if not isinstance(currency, str):
            raise ValueIssue("Add the currency, e.g. AED")
        text = f"{amount} {currency}"
    else:
        text = _text(raw)
    tokens = re.findall(r"[A-Za-z$€£₹.؀-ۿ]+|\d[\d,]*(?:\.\d+)?", text)
    amount_value: float | None = None
    currency_value: str | None = None
    for token in tokens:
        if token[0].isdigit():
            if amount_value is None:
                amount_value = float(token.replace(",", ""))
            continue
        upper = token.upper()
        code = CURRENCY_ALIASES.get(upper, upper)
        if code in CURRENCIES and currency_value is None:
            currency_value = code
    if amount_value is None:
        raise ValueIssue("No amount found")
    if currency_value is None:
        raise ValueIssue("Add the currency, e.g. AED")
    if amount_value < 0 or amount_value > 1e12:
        raise ValueIssue("The amount is out of range")
    return {"amount": round(amount_value, 2), "currency": currency_value}


def normalize(kind: ValueKind, raw: Any, *, choices: tuple[str, ...] = ()) -> Normalized:
    """Canonical form of `raw` for `kind`, or `ValueIssue`."""
    if raw is None:
        raise ValueIssue("The value is missing")
    match kind:
        case ValueKind.TEXT:
            return Normalized(_text(raw))
        case ValueKind.DATE:
            return _date(raw)
        case ValueKind.DATETIME:
            return Normalized(_datetime(raw))
        case ValueKind.COUNTRY:
            code = country_code(_text(raw))
            if code is None:
                raise ValueIssue("Not a country we recognise")
            return Normalized(code)
        case ValueKind.LANGUAGE:
            code = language_code(_text(raw))
            if code is None:
                raise ValueIssue("Not a language we recognise")
            return Normalized(code)
        case ValueKind.BOOLEAN:
            if isinstance(raw, bool):
                return Normalized(raw)
            text = _text(raw).lower().rstrip(".")
            if text in _TRUE:
                return Normalized(True)
            if text in _FALSE:
                return Normalized(False)
            raise ValueIssue("It doesn't clearly say yes or no")
        case ValueKind.INTEGER:
            if isinstance(raw, bool):
                raise ValueIssue("Expected a whole number")
            if isinstance(raw, str) and re.fullmatch(r"\s*\d{1,7}\s*", raw):
                raw = int(raw)
            if not isinstance(raw, int) or not 0 <= raw <= 1_000_000:
                raise ValueIssue("Expected a whole number")
            return Normalized(raw)
        case ValueKind.MONEY:
            return Normalized(_money(raw))
        case ValueKind.CHOICE:
            text = _text(raw).lower().replace(" ", "_").replace("-", "_")
            if text not in choices:
                raise ValueIssue("Choose one of the listed options")
            return Normalized(text)
    raise ValueIssue(f"Unsupported value kind {kind}")  # pragma: no cover


def display(kind: ValueKind, value: Any, *, choice_labels: dict[str, str] | None = None) -> str:
    """Short human-readable form, used in labels and explanations."""
    if value is None:
        return ""
    match kind:
        case ValueKind.COUNTRY:
            return country_name(str(value))
        case ValueKind.LANGUAGE:
            return language_name(str(value))
        case ValueKind.BOOLEAN:
            return "Yes" if value else "No"
        case ValueKind.MONEY if isinstance(value, dict):
            amount = value.get("amount", 0)
            shown = f"{amount:,.0f}" if float(amount).is_integer() else f"{amount:,.2f}"
            return f"{value.get('currency', '')} {shown}".strip()
        case ValueKind.DATE:
            try:
                parsed = date.fromisoformat(str(value))
            except ValueError:
                return str(value)
            return f"{parsed.day} {parsed.strftime('%B %Y')}"  # %-d is not portable
        case ValueKind.CHOICE:
            return (choice_labels or {}).get(str(value), str(value).replace("_", " ").capitalize())
    return str(value)
