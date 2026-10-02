"""From validated document fields to proposed facts in the private user graph.

Each document kind maps its fields onto entities and attributes of the user-graph
vocabulary. A passport, for example, yields the holder's name and date of birth, a
nationality, and a passport entity with only the issuing country and expiry date. Every
proposed fact keeps its provenance: which field it came from, how it was read, and how
confident the pipeline is after validation.

Only personal information goes in. Public governance knowledge (what a service requires,
what a document is for) is never copied into facts. Documents link to governance nodes
by reference (`instance_of`), see `governance_document_key`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any
from uuid import UUID

from app.documents.catalogue import REVIEW_THRESHOLD, DocumentKind
from app.documents.validation import CheckedField, ValidationOutcome, names_match
from app.personalization.vocabulary import (
    ENTITY_SPECS,
    UserEntityType,
    identity_token,
)

E = UserEntityType


@dataclass(frozen=True, slots=True)
class EntityRef:
    """Addresses a user-graph entity before it necessarily exists."""

    type: UserEntityType
    parent: EntityRef | None = None
    instance: str | None = None  # identity value (or document id) telling siblings apart
    node_id: UUID | None = None  # an existing entity, e.g. a child the user picked


SELF = EntityRef(E.PERSON)
SPOUSE = EntityRef(E.SPOUSE, SELF)


@dataclass(slots=True)
class ProposedFact:
    entity: EntityRef
    attribute: str
    value: Any | None
    confidence: float
    method: str
    field: str | None  # the document field it came from (None for derived facts)
    issues: list[str] = dc_field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.value is None or self.confidence < REVIEW_THRESHOLD or bool(self.issues)


@dataclass(slots=True)
class StructuringContext:
    document_id: UUID
    subject: EntityRef  # whose document it is: SELF, SPOUSE, or a child
    kind_confidence: float  # confidence in the document kind itself
    method: str  # extraction method of the reading
    self_name: str | None = None  # the user's accepted full name, if known
    subject_name: str | None = None  # the subject's accepted full name, if known


@dataclass(slots=True)
class Structured:
    facts: list[ProposedFact]
    document_entity: EntityRef  # the entity representing this document in the graph
    warnings: list[str] = dc_field(default_factory=list)


class _Builder:
    def __init__(self, outcome: ValidationOutcome, ctx: StructuringContext) -> None:
        self.outcome = outcome
        self.ctx = ctx
        self.facts: list[ProposedFact] = []
        self.warnings: list[str] = []

    def put(
        self,
        entity: EntityRef,
        attribute: str,
        source: str | CheckedField | None,
        *,
        value: Any = None,
        confidence: float | None = None,
        issues: list[str] | None = None,
    ) -> ProposedFact | None:
        """Add a fact from a field (by name or CheckedField) or an explicit value."""
        if attribute not in ENTITY_SPECS[entity.type].attributes:
            return None  # e.g. an employer is not recorded for a spouse
        checked = self.outcome.fields.get(source) if isinstance(source, str) else source
        if checked is None and value is None:
            return None
        fact = ProposedFact(
            entity=entity,
            attribute=attribute,
            value=value if value is not None else checked.value if checked else None,
            confidence=confidence
            if confidence is not None
            else checked.confidence
            if checked
            else 1.0,
            method=checked.method if checked else self.ctx.method,
            field=checked.name if checked else None,
            issues=list(checked.issues if checked else []) + list(issues or []),
        )
        self.facts.append(fact)
        return fact

    def instance(self, name: str) -> str:
        """Identity token from a field value, or the document id when unreadable."""
        value = self.outcome.value(name)
        return identity_token(value) if value not in (None, "") else f"doc:{self.ctx.document_id}"

    def document(self, kind: DocumentKind, parent: EntityRef | None = None) -> EntityRef:
        ref = EntityRef(E.DOCUMENT, parent or self.ctx.subject, instance=str(self.ctx.document_id))
        self.put(ref, "document_kind", None, value=kind.value, confidence=self.ctx.kind_confidence)
        return ref

    def flag_all(self, issue: str) -> None:
        for fact in self.facts:
            fact.issues.append(issue)


def _join_name(outcome: ValidationOutcome) -> CheckedField | None:
    """Full name from given names + surname (or a single name field)."""
    given, surname = outcome.fields.get("given_names"), outcome.fields.get("surname")
    if given and surname and given.value and surname.value:
        return CheckedField(
            "full_name",
            f"{given.value} {surname.value}",
            min(given.confidence, surname.confidence),
            given.method if given.confidence <= surname.confidence else surname.method,
            given.issues + surname.issues,
        )
    return outcome.fields.get("full_name")


def _check_holder(b: _Builder, name: str | None, label: str) -> None:
    if name and b.ctx.subject_name and not names_match(name, b.ctx.subject_name):
        b.flag_all(f"The {label} on this document doesn't match the name in your twin")


def _passport(b: _Builder) -> EntityRef:
    subject = b.ctx.subject
    full_name = _join_name(b.outcome)
    b.put(subject, "full_name", full_name)
    b.put(subject, "date_of_birth", "date_of_birth")
    if (nat := b.outcome.fields.get("nationality")) is not None:
        b.put(EntityRef(E.NATIONALITY, subject, b.instance("nationality")), "country", nat)
    passport = EntityRef(E.PASSPORT, subject, b.instance("issuing_country"))
    b.put(passport, "issuing_country", "issuing_country")
    b.put(passport, "expiry_date", "date_of_expiry")
    _check_holder(b, full_name.value if full_name else None, "name")
    return passport


def _identity(b: _Builder) -> EntityRef:
    subject = b.ctx.subject
    b.put(subject, "full_name", "full_name")
    b.put(subject, "date_of_birth", "date_of_birth")
    if (nat := b.outcome.fields.get("nationality")) is not None:
        b.put(EntityRef(E.NATIONALITY, subject, b.instance("nationality")), "country", nat)
    doc = b.document(DocumentKind.IDENTITY_DOCUMENT)
    b.put(doc, "title", "document_title")
    b.put(doc, "issuing_country", "issuing_country")
    b.put(doc, "expiry_date", "expiry_date")
    _check_holder(b, b.outcome.value("full_name"), "name")
    return doc


def _marriage(b: _Builder) -> EntityRef:
    doc = b.document(DocumentKind.MARRIAGE_CERTIFICATE, SELF)
    b.put(doc, "issuer", "issuing_authority")
    b.put(doc, "issuing_country", "country_of_marriage")
    b.put(doc, "attested", "attested")
    b.put(doc, "home_attested", "home_attested")

    p1, p2 = b.outcome.fields.get("spouse_1_name"), b.outcome.fields.get("spouse_2_name")
    n1, n2 = (p.value if p else None for p in (p1, p2))
    self_name = b.ctx.self_name
    spouse_field: CheckedField | None
    issue: str | None = None
    if self_name and names_match(n1, self_name):
        spouse_field = p2
    elif self_name and names_match(n2, self_name):
        spouse_field = p1
    else:
        spouse_field = p2 or p1
        if self_name:
            issue = "Neither name matches the name in your twin, so check who your spouse is"
        else:
            issue = "Check this is your spouse's name (we couldn't tell which name is yours)"
            if p1 is not None and spouse_field is not p1:
                b.put(SELF, "full_name", p1, issues=[
                    "Check this is your name (we couldn't tell which name is yours)"
                ])  # fmt: skip
    b.put(SPOUSE, "full_name", spouse_field, issues=[issue] if issue else None)
    # The spouse's date of birth, when printed next to their name (Indian registrations
    # list both parties' dates of birth). It decides age-based requirements for them.
    if spouse_field is not None:
        dob_field = "spouse_1_date_of_birth" if spouse_field is p1 else "spouse_2_date_of_birth"
        b.put(SPOUSE, "date_of_birth", dob_field, issues=[issue] if issue else None)
    b.put(SPOUSE, "married_on", "date_of_marriage")
    b.put(SPOUSE, "marriage_country", "country_of_marriage")
    return doc


def _employment(b: _Builder) -> EntityRef:
    subject = b.ctx.subject
    doc = b.document(DocumentKind.EMPLOYMENT_LETTER)
    b.put(doc, "issuer", "employer")
    b.put(subject, "employer", "employer")
    b.put(subject, "job_title", "job_title")
    if b.ctx.subject.type is not E.PERSON:
        b.put(subject, "occupation", "job_title")
    b.put(subject, "monthly_income", "monthly_salary")
    b.put(subject, "employment_start_date", "start_date")
    b.put(subject, "employer_provides_accommodation", "accommodation_provided")
    _check_holder(b, b.outcome.value("employee_name"), "employee's name")
    return doc


_ADGM = re.compile(r"\badgm\b|abu dhabi global market", re.IGNORECASE)
_MAINLAND = re.compile(
    r"department of economic development|\bded\b|\badded\b|economic development", re.IGNORECASE
)
_LICENCE = re.compile(r"licen[cs]e|incorporation|registration certificate", re.IGNORECASE)
# A plan or profile the founder wrote: it names where the company will register, but no
# authority issued it and the company doesn't exist yet.
_PLAN = re.compile(r"business plan|business profile|company profile", re.IGNORECASE)


def _business(b: _Builder) -> EntityRef:
    doc = b.document(DocumentKind.BUSINESS_DOCUMENT, SELF)
    title = b.outcome.value("document_title")
    planned = isinstance(title, str) and bool(_PLAN.search(title))
    b.put(doc, "title", "document_title")
    if not planned:
        b.put(doc, "issuer", "registration_authority")
    b.put(doc, "expiry_date", "expiry_date")

    company = EntityRef(E.COMPANY, SELF, b.instance("company_name"))
    b.put(company, "name", "company_name")
    b.put(company, "legal_form", "legal_form")
    authority = b.outcome.fields.get("registration_authority")
    b.put(company, "registration_authority", authority)
    if authority is not None and isinstance(authority.value, str):
        jurisdiction = (
            "adgm" if _ADGM.search(authority.value)
            else "mainland" if _MAINLAND.search(authority.value) else None
        )  # fmt: skip
        if jurisdiction:
            b.put(company, "jurisdiction", None, value=jurisdiction,
                  confidence=round(authority.confidence * 0.95, 3))  # fmt: skip
    if planned:
        b.put(company, "stage", None, value="idea", confidence=0.9)
    elif isinstance(title, str) and _LICENCE.search(title):
        b.put(company, "stage", None, value="registered", confidence=0.9)

    activities = b.outcome.fields.get("activities")
    if activities is not None and isinstance(activities.value, list):
        for description in activities.value:
            activity = EntityRef(E.BUSINESS_ACTIVITY, company, identity_token(description))
            b.put(activity, "description", activities, value=description)
    return doc


def _tenancy(b: _Builder) -> EntityRef:
    doc = b.document(DocumentKind.TENANCY_DOCUMENT)
    for attribute in ("property_area", "property_city", "tenancy_start", "tenancy_end",
                      "annual_rent", "registered"):  # fmt: skip
        b.put(doc, attribute, attribute)
    _check_holder(b, b.outcome.value("tenant_name"), "tenant's name")
    return doc


def _miscellaneous(b: _Builder) -> EntityRef:
    doc = b.document(DocumentKind.MISCELLANEOUS)
    b.put(doc, "title", "document_title")
    b.put(doc, "issuer", "issuer")
    b.put(doc, "issue_date", "issue_date")
    return doc


_STRUCTURERS = {
    DocumentKind.PASSPORT: _passport,
    DocumentKind.IDENTITY_DOCUMENT: _identity,
    DocumentKind.MARRIAGE_CERTIFICATE: _marriage,
    DocumentKind.EMPLOYMENT_LETTER: _employment,
    DocumentKind.BUSINESS_DOCUMENT: _business,
    DocumentKind.TENANCY_DOCUMENT: _tenancy,
    DocumentKind.MISCELLANEOUS: _miscellaneous,
}


def structure(outcome: ValidationOutcome, ctx: StructuringContext) -> Structured:
    builder = _Builder(outcome, ctx)
    document_entity = _STRUCTURERS[outcome.kind](builder)
    return Structured(builder.facts, document_entity, builder.warnings)


def governance_document_key(entity_type: UserEntityType, facts: dict[str, Any]) -> str | None:
    """Which public governance document node a user's document is an instance of.

    Returns a governance key such as 'document.passport', or None when the document is
    not (yet) the kind a governance requirement names. For example, a marriage certificate
    only counts as 'attested' once it is.
    """
    if entity_type is E.PASSPORT:
        return "document.passport"
    if entity_type is not E.DOCUMENT:
        return None
    kind = facts.get("document_kind")
    if kind == DocumentKind.MARRIAGE_CERTIFICATE and facts.get("attested") is True:
        return "document.marriage_certificate_attested"
    if kind == DocumentKind.TENANCY_DOCUMENT and facts.get("registered") is True:
        return "document.tenancy_contract_registered"
    if kind == DocumentKind.IDENTITY_DOCUMENT and facts.get("issuing_country") == "ARE":
        return "document.emirates_id"
    title = facts.get("title")
    if (
        kind == DocumentKind.BUSINESS_DOCUMENT
        and isinstance(title, str)
        and _LICENCE.search(title)
        and not _PLAN.search(title)
    ):
        return "document.commercial_license"
    return None
