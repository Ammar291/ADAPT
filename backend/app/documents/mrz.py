"""Machine-readable zone (ICAO 9303) parsing with check-digit verification.

Passports (TD3: 2 lines x 44) and ID cards such as the Emirates ID (TD1: 3 lines x 30)
carry check digits over the document number, birth date and expiry date, plus a
composite check. When they verify, the MRZ is an independent, deterministic reading
that confirms or contradicts what OCR/VLM read from the visual zone.

The document number is used only to verify its check digit. It is not returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

_WEIGHTS = (7, 3, 1)


def check_digit(data: str) -> int:
    total = 0
    for i, ch in enumerate(data):
        if ch.isdigit():
            value = int(ch)
        elif "A" <= ch <= "Z":
            value = ord(ch) - 55
        else:  # '<' filler
            value = 0
        total += value * _WEIGHTS[i % 3]
    return total % 10


def _verify(data: str, digit: str) -> bool:
    return digit.isdigit() and check_digit(data) == int(digit)


def _mrz_date(yymmdd: str, *, birth: bool, today: date) -> str | None:
    if not re.fullmatch(r"\d{6}", yymmdd):
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    # Birth dates may be last century; expiry dates of current documents never are.
    year = 2000 + yy if not birth or 2000 + yy <= today.year else 1900 + yy
    try:
        return date(year, mm, dd).isoformat()
    except ValueError:
        return None


def _names(raw: str) -> tuple[str | None, str | None]:
    surname, _, given = raw.strip("<").partition("<<")
    clean = lambda s: " ".join(p for p in s.split("<") if p) or None  # noqa: E731
    return clean(surname), clean(given)


@dataclass(slots=True)
class MrzData:
    format: str  # "TD3" | "TD1"
    document_code: str
    issuing_country: str
    surname: str | None
    given_names: str | None
    nationality: str
    date_of_birth: str | None
    expiry_date: str | None
    failed_checks: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.failed_checks

    @property
    def full_name(self) -> str | None:
        parts = [p for p in (self.given_names, self.surname) if p]
        return " ".join(parts) or None


def _clean_lines(lines: list[str]) -> list[str]:
    return [re.sub(r"\s+", "", line).upper() for line in lines if line.strip()]


def parse_mrz(lines: list[str], *, today: date | None = None) -> MrzData | None:
    """Parse TD3 or TD1 lines; None when no complete MRZ is present."""
    today = today or date.today()
    rows = _clean_lines(lines)
    td3 = [r for r in rows if len(r) == 44]
    if len(td3) >= 2 and td3[0].startswith("P"):
        return _parse_td3(td3[0], td3[1], today)
    td1 = [r for r in rows if len(r) == 30]
    if len(td1) >= 3:
        return _parse_td1(td1[0], td1[1], td1[2], today)
    return None


def _parse_td3(l1: str, l2: str, today: date) -> MrzData:
    surname, given = _names(l1[5:44])
    failed = []
    if not _verify(l2[0:9], l2[9]):
        failed.append("document_number")
    if not _verify(l2[13:19], l2[19]):
        failed.append("date_of_birth")
    if not _verify(l2[21:27], l2[27]):
        failed.append("expiry_date")
    optional = l2[28:42]
    if optional.strip("<") and not _verify(optional, l2[42]):
        failed.append("optional_data")
    if not _verify(l2[0:10] + l2[13:20] + l2[21:43], l2[43]):
        failed.append("composite")
    return MrzData(
        format="TD3",
        document_code=l1[0:2].rstrip("<"),
        issuing_country=l1[2:5].replace("<", ""),
        surname=surname,
        given_names=given,
        nationality=l2[10:13].replace("<", ""),
        date_of_birth=_mrz_date(l2[13:19], birth=True, today=today),
        expiry_date=_mrz_date(l2[21:27], birth=False, today=today),
        failed_checks=failed,
    )


def _parse_td1(l1: str, l2: str, l3: str, today: date) -> MrzData:
    surname, given = _names(l3)
    failed = []
    if not _verify(l1[5:14], l1[14]):
        failed.append("document_number")
    if not _verify(l2[0:6], l2[6]):
        failed.append("date_of_birth")
    if not _verify(l2[8:14], l2[14]):
        failed.append("expiry_date")
    if not _verify(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29], l2[29]):
        failed.append("composite")
    return MrzData(
        format="TD1",
        document_code=l1[0:2].rstrip("<"),
        issuing_country=l1[2:5].replace("<", ""),
        surname=surname,
        given_names=given,
        nationality=l2[15:18].replace("<", ""),
        date_of_birth=_mrz_date(l2[0:6], birth=True, today=today),
        expiry_date=_mrz_date(l2[8:14], birth=False, today=today),
        failed_checks=failed,
    )


def build_td3(
    *,
    issuing_country: str,
    surname: str,
    given_names: str,
    document_number: str,
    nationality: str,
    date_of_birth: date,
    sex: str,
    expiry_date: date,
) -> tuple[str, str]:
    """Compose a valid TD3 MRZ. Used to generate clearly-marked specimen documents."""

    def field_(text: str, width: int) -> str:
        cleaned = re.sub(r"[^A-Z0-9]+", "<", text.upper())
        return cleaned[:width].ljust(width, "<")

    def name_(text: str) -> str:
        return re.sub(r"[^A-Z]+", "<", text.upper()).strip("<")

    names = f"{name_(surname)}<<{name_(given_names)}"[:39].ljust(39, "<")
    line1 = f"P<{field_(issuing_country, 3)}{names}"
    number = field_(document_number, 9)
    dob = date_of_birth.strftime("%y%m%d")
    exp = expiry_date.strftime("%y%m%d")
    optional = "<" * 14
    body = (
        f"{number}{check_digit(number)}{field_(nationality, 3)}{dob}{check_digit(dob)}"
        f"{sex.upper()[:1] or '<'}{exp}{check_digit(exp)}{optional}"
    )
    optional_check = "<" if not optional.strip("<") else str(check_digit(optional))
    composite_data = body[0:10] + body[13:20] + body[21:28] + optional + optional_check
    line2 = f"{body}{optional_check}{check_digit(composite_data)}"
    return line1, line2
