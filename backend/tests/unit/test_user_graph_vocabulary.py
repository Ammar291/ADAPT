"""Private user graph vocabulary: value normalisation, entity specs, keys and labels."""

from __future__ import annotations

import re

import pytest

from app.personalization.reference import country_code, language_code
from app.personalization.values import ValueIssue, ValueKind, display, normalize
from app.personalization.vocabulary import (
    ENTITY_SPECS,
    HUB_KEY,
    Cardinality,
    FactRuleError,
    UserEntityType,
    entity_key,
    entity_label,
    spec_for,
)

KEY_FORMAT = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_:-]+)*$")


class TestValues:
    @pytest.mark.parametrize(
        ("raw", "expected", "ambiguous"),
        [
            ("1990-04-12", "1990-04-12", False),
            ("12/04/1990", "1990-04-12", True),  # day-first, but could be 4 December
            ("25/04/1990", "1990-04-25", False),
            ("12 APR 1990", "1990-04-12", False),
            ("12 APR /AVR 1990", "1990-04-12", False),
            ("November 23, 2019", "2019-11-23", False),
        ],
    )
    def test_dates(self, raw: str, expected: str, ambiguous: bool) -> None:
        result = normalize(ValueKind.DATE, raw)
        assert (result.value, result.ambiguous) == (expected, ambiguous)

    @pytest.mark.parametrize("raw", ["31/02/2020", "yesterday", "", "1850-01-01"])
    def test_bad_dates(self, raw: str) -> None:
        with pytest.raises(ValueIssue):
            normalize(ValueKind.DATE, raw)

    @pytest.mark.parametrize(
        ("raw", "code"),
        [("IND", "IND"), ("India", "IND"), ("INDIAN", "IND"), ("uae", "ARE"), ("D", "DEU")],
    )
    def test_countries(self, raw: str, code: str) -> None:
        assert country_code(raw) == code
        assert normalize(ValueKind.COUNTRY, raw).value == code

    def test_unknown_country_is_an_issue(self) -> None:
        with pytest.raises(ValueIssue, match="country"):
            normalize(ValueKind.COUNTRY, "Atlantis")

    def test_languages(self) -> None:
        assert language_code("ar-AE") == "ar"
        assert language_code("Arabic") == "ar"
        assert normalize(ValueKind.LANGUAGE, "Hindi").value == "hi"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("AED 32,000", {"amount": 32000.0, "currency": "AED"}),
            ("25000.50 AED per month", {"amount": 25000.5, "currency": "AED"}),
            ("Dhs 1,200", {"amount": 1200.0, "currency": "AED"}),
            ({"amount": 10, "currency": "usd"}, {"amount": 10.0, "currency": "USD"}),
        ],
    )
    def test_money(self, raw: object, expected: dict[str, object]) -> None:
        assert normalize(ValueKind.MONEY, raw).value == expected

    def test_money_needs_a_currency(self) -> None:
        with pytest.raises(ValueIssue, match="currency"):
            normalize(ValueKind.MONEY, "32000")

    def test_booleans_and_choices(self) -> None:
        assert normalize(ValueKind.BOOLEAN, "Yes").value is True
        assert normalize(ValueKind.BOOLEAN, "not attested").value is False
        with pytest.raises(ValueIssue):
            normalize(ValueKind.BOOLEAN, "Pending")
        assert normalize(ValueKind.CHOICE, "Free Zone", choices=("free_zone",)).value == "free_zone"

    def test_issue_messages_never_echo_the_value(self) -> None:
        with pytest.raises(ValueIssue) as exc:
            normalize(ValueKind.COUNTRY, "Z1234567 secret")
        assert "Z1234567" not in str(exc.value)

    def test_display(self) -> None:
        assert display(ValueKind.COUNTRY, "IND") == "India"
        assert display(ValueKind.DATE, "2019-11-23") == "23 November 2019"
        assert display(ValueKind.MONEY, {"amount": 32000.0, "currency": "AED"}) == "AED 32,000"


class TestVocabulary:
    def test_entity_types_match_the_brief(self) -> None:
        assert {t.value for t in UserEntityType} == {
            "person", "household", "spouse", "child", "passport", "visa", "nationality",
            "company", "business_activity", "goal", "housing_preference", "budget",
            "language", "preference", "document", "appointment", "community_preference",
        }  # fmt: skip
        assert set(ENTITY_SPECS) == set(UserEntityType)

    @pytest.mark.parametrize("spec", list(ENTITY_SPECS.values()), ids=lambda s: s.type.value)
    def test_specs_are_consistent(self, spec) -> None:  # type: ignore[no-untyped-def]
        if spec.cardinality is Cardinality.HUB:
            assert spec.relation is None and not spec.parents
        else:
            assert spec.relation is not None and spec.parents
        if spec.identity:
            assert spec.identity in spec.attributes
        assert all(name in spec.attributes for name in spec.label_from)

    def test_only_faith_is_sensitive(self) -> None:
        sensitive = {
            (spec.type.value, a.name)
            for spec in ENTITY_SPECS.values()
            for a in spec.attributes.values()
            if a.sensitive
        }
        assert sensitive == {("community_preference", "faith_community")}

    def test_passport_is_minimal(self) -> None:
        """Data minimisation: no document number is ever part of the twin."""
        assert set(ENTITY_SPECS[UserEntityType.PASSPORT].attributes) == {
            "issuing_country",
            "expiry_date",
        }
        for spec in ENTITY_SPECS.values():
            assert not any("number" in name for name in spec.attributes)

    def test_keys_are_deterministic_and_pii_free(self) -> None:
        child = entity_key(UserEntityType.CHILD, parent_key=HUB_KEY, instance="aarav mehta")
        assert child == entity_key(UserEntityType.CHILD, parent_key=HUB_KEY, instance="aarav mehta")
        assert child and "aarav" not in child and KEY_FORMAT.match(child)
        assert entity_key(UserEntityType.PERSON, parent_key=None, instance=None) == HUB_KEY
        assert entity_key(UserEntityType.SPOUSE, parent_key=HUB_KEY, instance=None) == "spouse.self"
        spouse_passport = entity_key(
            UserEntityType.PASSPORT, parent_key="spouse.self", instance="ind"
        )
        own_passport = entity_key(UserEntityType.PASSPORT, parent_key=HUB_KEY, instance="ind")
        assert spouse_passport != own_passport
        assert entity_key(UserEntityType.APPOINTMENT, parent_key=HUB_KEY, instance=None) is None

    def test_labels_come_from_facts(self) -> None:
        passport = ENTITY_SPECS[UserEntityType.PASSPORT]
        assert entity_label(passport, {"issuing_country": "IND"}) == "Passport · India"
        assert entity_label(passport, {}) == "Passport"
        goal = ENTITY_SPECS[UserEntityType.GOAL]
        assert entity_label(goal, {"kind": "start_company"}) == "Start a company"

    def test_unknown_attributes_and_types_are_rejected(self) -> None:
        with pytest.raises(FactRuleError, match="not something ADAPT records"):
            ENTITY_SPECS[UserEntityType.SPOUSE].attribute("passport_number")
        with pytest.raises(FactRuleError):
            spec_for("service")  # a governance type is never a user entity
