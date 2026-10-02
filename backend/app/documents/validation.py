"""Validation of a reading before anything becomes a fact.

Reader confidence is a starting point, not the truth: a vision model reports its own
confidence, and a text layer can put the right text under the wrong label. Each field is
normalised to its canonical form and checked for plausibility. Passports and ID cards
are also cross-checked against their machine-readable zone, whose check digits give an
independent, deterministic reading. Confidence goes up when evidence agrees, down when it
conflicts, and every problem is recorded as a user-facing issue that forces a review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.adapters.ocr.types import ReadResult
from app.documents.catalogue import REVIEW_THRESHOLD, TYPE_SPECS, DocumentKind
from app.documents.mrz import MrzData, parse_mrz
from app.personalization.reference import country_code, fold
from app.personalization.values import ValueIssue, ValueKind, normalize

MRZ_AGREES = 0.98
MRZ_FILLS = 0.97
CONFLICT_CAP = 0.5
AMBIGUOUS_CAP = 0.7

_KIND = {
    "text": ValueKind.TEXT,
    "date": ValueKind.DATE,
    "country": ValueKind.COUNTRY,
    "boolean": ValueKind.BOOLEAN,
    "money": ValueKind.MONEY,
}
_NAME_FIELDS = frozenset(
    {"surname", "given_names", "full_name", "spouse_1_name", "spouse_2_name", "employee_name",
     "tenant_name"}
)  # fmt: skip
_NAME_CHARS = re.compile(r"^[^\W\d_]+(?:[ '\-.][^\W\d_]+)*\.?$", re.UNICODE)
_PAST_DATES = frozenset({"date_of_marriage", "start_date", "issue_date"})
_EXPIRY_DATES = frozenset({"date_of_expiry", "expiry_date"})


@dataclass(slots=True)
class CheckedField:
    name: str
    value: Any | None  # canonical value; None when missing or invalid
    confidence: float
    method: str
    issues: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.value is None or self.confidence < REVIEW_THRESHOLD or bool(self.issues)


@dataclass(slots=True)
class ValidationOutcome:
    kind: DocumentKind
    fields: dict[str, CheckedField]
    mrz: MrzData | None = None
    warnings: list[str] = field(default_factory=list)

    def value(self, name: str) -> Any | None:
        checked = self.fields.get(name)
        return checked.value if checked else None


def smart_case(name: str) -> str:
    """'ARJUN MEHTA' -> 'Arjun Mehta'; mixed-case names are kept as printed."""
    if not name.isupper():
        return name
    return re.sub(r"[^\W\d_]+", lambda m: m[0].capitalize(), name.lower(), flags=re.UNICODE)


def names_match(a: str | None, b: str | None) -> bool:
    """Tolerant comparison: order, case and accents don't matter; two shared tokens do."""
    if not a or not b:
        return False
    ta, tb = set(fold(a).replace("-", " ").split()), set(fold(b).replace("-", " ").split())
    if not ta or not tb:
        return False
    return ta == tb or len(ta & tb) >= min(2, len(ta), len(tb))


def _normalise(kind: DocumentKind, name: str, raw: str) -> tuple[Any, bool]:
    """Canonical value and whether it was ambiguous. Raises ValueIssue."""
    spec_kind = next((f.kind for f in TYPE_SPECS[kind].fields if f.name == name), "text")
    if spec_kind == "list":
        items = [i.strip(" .") for i in re.split(r"[;\n]|,\s+|\s+/\s+", raw) if i.strip(" .")]
        if not items:
            raise ValueIssue("Nothing readable")
        return [normalize(ValueKind.TEXT, i).value for i in items[:20]], False
    normalized = normalize(_KIND.get(spec_kind, ValueKind.TEXT), raw)
    value = normalized.value
    if name in _NAME_FIELDS:
        if not _NAME_CHARS.match(value):
            raise ValueIssue("That doesn't look like a name")
        value = smart_case(value)
    return value, normalized.ambiguous


def _plausibility(name: str, value: Any, today: date) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    when = date.fromisoformat(value)
    if name.endswith("date_of_birth") and not (date(today.year - 120, 1, 1) <= when < today):
        return "That date of birth isn't plausible"
    if name in _PAST_DATES and when > today:
        return "That date is in the future"
    if name in _EXPIRY_DATES and when.year < 1990:
        return "That expiry date isn't plausible"
    return None


def _mrz_values(kind: DocumentKind, mrz: MrzData) -> dict[str, Any]:
    values: dict[str, Any] = {
        "nationality": country_code(mrz.nationality),
        "date_of_birth": mrz.date_of_birth,
        "issuing_country": country_code(mrz.issuing_country),
    }
    if kind is DocumentKind.PASSPORT:
        values |= {
            "surname": smart_case(mrz.surname) if mrz.surname else None,
            "given_names": smart_case(mrz.given_names) if mrz.given_names else None,
            "date_of_expiry": mrz.expiry_date,
        }
    else:
        values |= {
            "full_name": smart_case(mrz.full_name) if mrz.full_name else None,
            "expiry_date": mrz.expiry_date,
        }
    return {k: v for k, v in values.items() if v is not None}


def _agrees(name: str, read: Any, from_mrz: Any) -> bool:
    if name in _NAME_FIELDS:
        return names_match(str(read), str(from_mrz))
    return read == from_mrz


def validate_reading(
    kind: DocumentKind, reading: ReadResult, *, today: date | None = None
) -> ValidationOutcome:
    today = today or date.today()
    allowed = {f.name for f in TYPE_SPECS[kind].fields}
    outcome = ValidationOutcome(kind=kind, fields={})

    for read in reading.fields:
        if read.name not in allowed or read.name in outcome.fields:
            continue
        checked = CheckedField(read.name, None, read.confidence, reading.method)
        outcome.fields[read.name] = checked
        if not read.value:
            checked.issues.append("We couldn't read this")
            continue
        try:
            value, ambiguous = _normalise(kind, read.name, read.value)
        except ValueIssue as issue:
            checked.issues.append(str(issue))
            checked.confidence = min(checked.confidence, CONFLICT_CAP)
            continue
        checked.value = value
        if ambiguous:
            checked.confidence = min(checked.confidence, AMBIGUOUS_CAP)
            checked.issues.append("Day and month could be swapped")
        if problem := _plausibility(read.name, value, today):
            checked.issues.append(problem)
            checked.confidence = min(checked.confidence, CONFLICT_CAP)

    if kind in (DocumentKind.PASSPORT, DocumentKind.IDENTITY_DOCUMENT):
        mrz = parse_mrz(reading.machine_readable_zone, today=today)
        if mrz is not None:
            outcome.mrz = mrz
            if not mrz.valid:
                outcome.warnings.append(
                    "The machine-readable lines didn't pass their check digits, "
                    "so they weren't used to confirm the details"
                )
            else:
                _cross_check(outcome, _mrz_values(kind, mrz), reading.method, today)
    return outcome


def _cross_check(
    outcome: ValidationOutcome, from_mrz: dict[str, Any], method: str, today: date
) -> None:
    for name, mrz_value in from_mrz.items():
        checked = outcome.fields.get(name)
        if checked is None or checked.value is None:
            # Missing or unreadable in the visual zone: the verified MRZ supplies it.
            outcome.fields[name] = CheckedField(name, mrz_value, MRZ_FILLS, f"{method}+mrz")
            if problem := _plausibility(name, mrz_value, today):
                outcome.fields[name].issues.append(problem)
            continue
        if _agrees(name, checked.value, mrz_value):
            checked.confidence = max(checked.confidence, MRZ_AGREES)
            checked.method = f"{checked.method}+mrz"
            checked.issues = [i for i in checked.issues if i != "Day and month could be swapped"]
            if name not in _NAME_FIELDS:
                checked.value = mrz_value
        else:
            checked.confidence = min(checked.confidence, CONFLICT_CAP)
            checked.issues.append("This doesn't match the machine-readable lines on the document")
