"""Clearly-marked SPECIMEN documents for the demo persona and for tests.

These are real PDF files with a text layer, so the local reader extracts their contents
from the uploaded bytes. Nothing is looked up or pre-filled: upload a different file and
you get a different result. Every page carries a "SPECIMEN - NOT A REAL DOCUMENT" banner.

    uv run python -m app.documents.specimens ./specimens   # writes the demo set
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.documents.mrz import build_td3

BANNER = "SPECIMEN - NOT A REAL DOCUMENT"


@dataclass(frozen=True, slots=True)
class Line:
    text: str
    size: int = 11
    mono: bool = False
    gap: int = 8  # extra space above the line


def _escape(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def build_pdf(lines: list[Line], *, banner: bool = True) -> bytes:
    """A one-page A4 PDF with a real text layer (Helvetica / Courier, WinAnsi)."""
    content = [b"0.6 w 36 36 523 770 re S", b"0.75 0 0 rg"]
    y = 790
    if banner:
        content.append(b"BT /F1 12 Tf 60 %d Td (%s) Tj ET" % (y, _escape(BANNER)))
    content.append(b"0 0 0 rg")
    y -= 36
    for line in lines:
        y -= line.size + line.gap
        font = b"F2" if line.mono else b"F1"
        content.append(
            b"BT /%s %d Tf 60 %d Td (%s) Tj ET" % (font, line.size, y, _escape(line.text))
        )
    stream = b"\n".join(content)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def passport(
    *,
    surname: str = "MEHTA",
    given_names: str = "ARJUN",
    nationality: str = "IND",
    date_of_birth: date = date(1990, 4, 12),
    expiry: date = date(2032, 1, 9),
    number: str = "Z0000000",
    sex: str = "M",
    visual_date_of_birth: str | None = None,
) -> bytes:
    line1, line2 = build_td3(
        issuing_country=nationality,
        surname=surname,
        given_names=given_names,
        document_number=number,
        nationality=nationality,
        date_of_birth=date_of_birth,
        sex=sex,
        expiry_date=expiry,
    )
    return build_pdf(
        [
            Line("REPUBLIC OF INDIA", 16, gap=4),
            Line("PASSPORT", 14),
            Line(f"Surname: {surname}"),
            Line(f"Given names: {given_names}"),
            Line("Nationality: INDIAN"),
            Line(f"Date of birth: {visual_date_of_birth or date_of_birth.strftime('%d/%m/%Y')}"),
            Line(f"Date of expiry: {expiry.strftime('%d/%m/%Y')}"),
            Line(f"Country code: {nationality}"),
            Line(line1, 10, mono=True, gap=40),
            Line(line2, 10, mono=True, gap=4),
        ]
    )


def marriage_certificate(*, attestation: str = "Pending") -> bytes:
    return build_pdf(
        [
            Line("GOVERNMENT OF MAHARASHTRA", 14, gap=4),
            Line("MARRIAGE CERTIFICATE", 14),
            Line("Husband: Arjun Mehta"),
            Line("Wife: Priya Mehta"),
            Line("Date of marriage: 23 November 2019"),
            Line("Place of marriage: India"),
            Line("Registrar: Registrar of Marriages, Pune"),
            Line(f"Attestation: {attestation}"),
        ]
    )


def business_document() -> bytes:
    return build_pdf(
        [
            Line("ABU DHABI GLOBAL MARKET", 14, gap=4),
            Line("COMMERCIAL LICENCE", 14),
            Line("Document: Commercial Licence"),
            Line("Company name: Mehta Analytics Ltd"),
            Line("Legal form: Private company limited by shares"),
            Line("Registration authority: ADGM Registration Authority"),
            Line("Licensed activities: Software development; IT consultancy"),
            Line("Expiry date: 14/03/2027"),
        ]
    )


def employment_letter() -> bytes:
    return build_pdf(
        [
            Line("SALARY CERTIFICATE", 14),
            Line("To whom it may concern"),
            Line("Employee name: Arjun Mehta"),
            Line("Employer: Mehta Analytics Ltd"),
            Line("Designation: Managing Director"),
            Line("Monthly salary: AED 32,000"),
            Line("Date of joining: 01/06/2026"),
            Line("Accommodation provided: No"),
        ]
    )


def tenancy_document() -> bytes:
    return build_pdf(
        [
            Line("TENANCY CONTRACT", 14),
            Line("Tenant name: Arjun Mehta"),
            Line("Community: Al Reem Island"),
            Line("City: Abu Dhabi"),
            Line("Contract start: 01/12/2026"),
            Line("Contract end: 30/11/2027"),
            Line("Annual rent: AED 120,000"),
            Line("Tawtheeq registered: Yes"),
        ]
    )


DEMO_SET: dict[str, Callable[[], bytes]] = {
    "passport-arjun-mehta.pdf": passport,
    "marriage-certificate.pdf": marriage_certificate,
    "adgm-commercial-licence.pdf": business_document,
    "salary-certificate.pdf": employment_letter,
    "tenancy-contract.pdf": tenancy_document,
}


def main(argv: list[str]) -> int:
    target = Path(argv[1] if len(argv) > 1 else "specimens")
    target.mkdir(parents=True, exist_ok=True)
    for name, make in DEMO_SET.items():
        (target / name).write_bytes(make())
        print(target / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
