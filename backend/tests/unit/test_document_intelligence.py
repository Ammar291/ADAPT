"""Document pipeline logic: MRZ, validation/confidence calibration, structuring into facts."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.adapters.ocr import LocalTextReader, ReadField, ReadRequest, ReadResult
from app.documents import specimens
from app.documents.catalogue import READ_SCHEMA, REVIEW_THRESHOLD, DocumentKind
from app.documents.mrz import build_td3, check_digit, parse_mrz
from app.documents.structuring import (
    SELF,
    SPOUSE,
    StructuringContext,
    governance_document_key,
    structure,
)
from app.documents.validation import names_match, validate_reading
from app.personalization.vocabulary import UserEntityType

E = UserEntityType

TODAY = date(2026, 9, 29)
ICAO_TD3 = [
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
]


async def read(pdf: bytes, hint: str | None = None) -> ReadResult:
    return await LocalTextReader().read(ReadRequest(pdf, "application/pdf", READ_SCHEMA, hint))


def ctx(subject=SELF, **kw) -> StructuringContext:  # type: ignore[no-untyped-def]
    return StructuringContext(uuid4(), subject, 1.0, "local:pdf-text", **kw)


class TestMrz:
    def test_icao_specimen_check_digits(self) -> None:
        assert check_digit("L898902C3") == 6
        mrz = parse_mrz(ICAO_TD3, today=TODAY)
        assert mrz is not None and mrz.valid
        assert (mrz.surname, mrz.given_names) == ("ERIKSSON", "ANNA MARIA")
        assert mrz.date_of_birth == "1974-08-12"
        assert not hasattr(mrz, "document_number")  # verified, never returned

    def test_tampering_is_detected(self) -> None:
        tampered = [ICAO_TD3[0], ICAO_TD3[1].replace("7408122", "7508122")]
        mrz = parse_mrz(tampered, today=TODAY)
        assert mrz is not None and "date_of_birth" in mrz.failed_checks

    def test_built_specimen_mrz_verifies(self) -> None:
        lines = build_td3(
            issuing_country="IND", surname="Mehta", given_names="Priya", document_number="X1",
            nationality="IND", date_of_birth=date(1992, 2, 3), sex="F",
            expiry_date=date(2030, 5, 6),
        )  # fmt: skip
        mrz = parse_mrz(list(lines), today=TODAY)
        assert mrz is not None and mrz.valid and mrz.expiry_date == "2030-05-06"


class TestValidation:
    async def test_mrz_confirms_the_visual_zone(self) -> None:
        outcome = validate_reading(
            DocumentKind.PASSPORT, await read(specimens.passport()), today=TODAY
        )
        dob = outcome.fields["date_of_birth"]
        # 12/04/1990 is ambiguous on its own; the verified MRZ settles it.
        assert dob.value == "1990-04-12" and dob.confidence >= 0.98 and not dob.issues
        assert outcome.fields["nationality"].value == "IND"
        assert not any(f.needs_review for f in outcome.fields.values())

    async def test_conflict_with_mrz_forces_review(self) -> None:
        pdf = specimens.passport(visual_date_of_birth="13/04/1990")
        outcome = validate_reading(DocumentKind.PASSPORT, await read(pdf), today=TODAY)
        dob = outcome.fields["date_of_birth"]
        assert dob.confidence <= 0.5 and dob.needs_review
        assert "machine-readable" in dob.issues[0]

    def test_ambiguous_and_invalid_values_need_review(self) -> None:
        reading = ReadResult(
            "openai:test",
            "marriage_certificate",
            0.9,
            [
                ReadField("date_of_marriage", "03/04/2020", 0.99),
                ReadField("attested", "see reverse", 0.95),
                ReadField("spouse_2_name", "Pr1ya", 0.95),
                ReadField("spouse_1_name", None, 0.1),
            ],
        )
        fields = validate_reading(DocumentKind.MARRIAGE_CERTIFICATE, reading, today=TODAY).fields
        assert fields["date_of_marriage"].confidence == 0.7
        assert fields["attested"].value is None and fields["attested"].needs_review
        assert fields["spouse_2_name"].needs_review
        assert fields["spouse_1_name"].issues == ["We couldn't read this"]

    def test_implausible_dates(self) -> None:
        reading = ReadResult("t", "passport", 0.9, [ReadField("date_of_birth", "2030-01-01", 0.99)])
        checked = validate_reading(DocumentKind.PASSPORT, reading, today=TODAY).fields[
            "date_of_birth"
        ]
        assert checked.needs_review and "plausible" in checked.issues[0]

    def test_name_matching(self) -> None:
        assert names_match("ARJUN MEHTA", "Arjun Mehta")
        assert names_match("Mehta Arjun Kumar", "Arjun Mehta")
        assert not names_match("Priya Mehta", "Arjun Mehta")


def _by(facts, entity: UserEntityType):  # type: ignore[no-untyped-def]
    return {f.attribute: f for f in facts if f.entity.type is entity}


class TestStructuring:
    async def test_passport_yields_minimum_fields_only(self) -> None:
        outcome = validate_reading(
            DocumentKind.PASSPORT, await read(specimens.passport()), today=TODAY
        )
        result = structure(outcome, ctx())
        person, passport = (
            _by(result.facts, UserEntityType.PERSON),
            _by(result.facts, UserEntityType.PASSPORT),
        )
        assert person["full_name"].value == "Arjun Mehta"
        assert set(passport) == {"issuing_country", "expiry_date"}
        assert _by(result.facts, UserEntityType.NATIONALITY)["country"].value == "IND"
        assert all(f.confidence >= REVIEW_THRESHOLD for f in result.facts)
        assert result.document_entity.type is UserEntityType.PASSPORT

    async def test_marriage_certificate_finds_the_spouse(self) -> None:
        outcome = validate_reading(
            DocumentKind.MARRIAGE_CERTIFICATE,
            await read(specimens.marriage_certificate()),
            today=TODAY,
        )
        result = structure(outcome, ctx(self_name="ARJUN MEHTA"))
        spouse = _by(result.facts, UserEntityType.SPOUSE)
        assert spouse["full_name"].value == "Priya Mehta" and not spouse["full_name"].needs_review
        assert spouse["married_on"].value == "2019-11-23"
        doc = _by(result.facts, UserEntityType.DOCUMENT)
        assert doc["document_kind"].value == "marriage_certificate"
        # "Attestation: Pending" is neither yes nor no, so it is left for the person to answer.
        assert doc["attested"].value is None and doc["attested"].needs_review

    async def test_marriage_certificate_without_known_name_asks(self) -> None:
        outcome = validate_reading(
            DocumentKind.MARRIAGE_CERTIFICATE,
            await read(specimens.marriage_certificate()),
            today=TODAY,
        )
        result = structure(outcome, ctx())
        assert _by(result.facts, UserEntityType.SPOUSE)["full_name"].needs_review
        assert _by(result.facts, UserEntityType.PERSON)["full_name"].needs_review

    async def test_business_document_builds_company_context(self) -> None:
        outcome = validate_reading(
            DocumentKind.BUSINESS_DOCUMENT, await read(specimens.business_document()), today=TODAY
        )
        result = structure(outcome, ctx())
        company = _by(result.facts, UserEntityType.COMPANY)
        assert company["name"].value == "Mehta Analytics Ltd"
        assert company["jurisdiction"].value == "adgm"
        activities = [
            f.value for f in result.facts if f.entity.type is UserEntityType.BUSINESS_ACTIVITY
        ]
        assert activities == ["Software development", "IT consultancy"]
        assert {
            f.entity.parent
            for f in result.facts
            if f.entity.type is UserEntityType.BUSINESS_ACTIVITY
        } == {next(f.entity for f in result.facts if f.entity.type is UserEntityType.COMPANY)}

    async def test_employment_letter_for_a_spouse_keeps_only_spouse_attributes(self) -> None:
        outcome = validate_reading(
            DocumentKind.EMPLOYMENT_LETTER, await read(specimens.employment_letter()), today=TODAY
        )
        result = structure(outcome, ctx(SPOUSE, subject_name="Priya Mehta"))
        spouse = _by(result.facts, UserEntityType.SPOUSE)
        assert set(spouse) == {"occupation"}
        # The letter is in Arjun's name, not Priya's: everything goes to review.
        assert all("doesn't match" in " ".join(f.issues) for f in result.facts)

    async def test_employment_letter_for_the_user(self) -> None:
        outcome = validate_reading(
            DocumentKind.EMPLOYMENT_LETTER, await read(specimens.employment_letter()), today=TODAY
        )
        person = _by(
            structure(outcome, ctx(subject_name="Arjun Mehta")).facts, UserEntityType.PERSON
        )
        assert person["monthly_income"].value == {"amount": 32000.0, "currency": "AED"}
        assert person["employer_provides_accommodation"].value is False

    @pytest.mark.parametrize(
        ("entity", "facts", "key"),
        [
            (E.PASSPORT, {}, "document.passport"),
            (E.DOCUMENT, {"document_kind": "marriage_certificate", "attested": True},
             "document.marriage_certificate_attested"),
            (E.DOCUMENT, {"document_kind": "marriage_certificate", "attested": False}, None),
            (E.DOCUMENT, {"document_kind": "tenancy_document", "registered": True},
             "document.tenancy_contract_registered"),
            (E.DOCUMENT, {"document_kind": "identity_document", "issuing_country": "ARE"},
             "document.emirates_id"),
            (E.DOCUMENT, {"document_kind": "business_document", "title": "Commercial Licence"},
             "document.commercial_license"),
            (E.SPOUSE, {}, None),
        ],
    )  # fmt: skip
    def test_governance_document_links(self, entity, facts, key) -> None:  # type: ignore[no-untyped-def]
        assert governance_document_key(entity, facts) == key
