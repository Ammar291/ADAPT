"""What ADAPT reads from each kind of document, and how it recognises them.

Data minimisation is a design rule here: each kind lists only the fields a relocation
plan actually needs. Passport numbers, ID numbers, places of birth and similar are never
requested from any reader, so they can never be stored.
"""

from __future__ import annotations

from enum import StrEnum

from app.adapters.ocr.types import DocumentTypeSpec, FieldSpec

REVIEW_THRESHOLD = 0.85  # below this, a person confirms the value before ADAPT relies on it


class DocumentKind(StrEnum):
    PASSPORT = "passport"
    MARRIAGE_CERTIFICATE = "marriage_certificate"
    EMPLOYMENT_LETTER = "employment_letter"
    BUSINESS_DOCUMENT = "business_document"
    TENANCY_DOCUMENT = "tenancy_document"
    IDENTITY_DOCUMENT = "identity_document"
    MISCELLANEOUS = "miscellaneous"


class DocumentStatus(StrEnum):
    """uploaded → processing → extracted | needs_review → confirmed; failed; deleted."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    EXTRACTED = "extracted"  # read; every fact was confident enough to use
    NEEDS_REVIEW = "needs_review"  # something needs the person's check (or nothing was readable)
    CONFIRMED = "confirmed"  # the person reviewed everything read from it
    FAILED = "failed"  # the file itself could not be processed
    DELETED = "deleted"  # bytes destroyed and facts removed; a tombstone row remains


class DocumentSubject(StrEnum):
    """Whose document it is."""

    SELF = "self"
    SPOUSE = "spouse"
    CHILD = "child"


KIND_LABELS: dict[DocumentKind, str] = {
    DocumentKind.PASSPORT: "Passport",
    DocumentKind.MARRIAGE_CERTIFICATE: "Marriage certificate",
    DocumentKind.EMPLOYMENT_LETTER: "Employment letter",
    DocumentKind.BUSINESS_DOCUMENT: "Business document",
    DocumentKind.TENANCY_DOCUMENT: "Tenancy document",
    DocumentKind.IDENTITY_DOCUMENT: "Identity document",
    DocumentKind.MISCELLANEOUS: "Other document",
}

_F = FieldSpec

_TYPES: tuple[DocumentTypeSpec, ...] = (
    DocumentTypeSpec(
        DocumentKind.PASSPORT.value,
        "A national passport (photo page)",
        (
            _F("surname", "Surname / family name", ("Surname", "Family name", "Last name"), "text"),
            _F("given_names", "Given names", ("Given names", "Given name", "First name"), "text"),
            _F("full_name", "Full name when printed as one field", ("Name", "Full name"), "text"),
            _F("nationality", "Nationality", ("Nationality",), "country"),
            _F("date_of_birth", "Date of birth", ("Date of birth", "DOB", "Birth date"), "date"),
            _F(
                "date_of_expiry",
                "Date of expiry",
                ("Date of expiry", "Expiry date", "Valid until", "Expires"),
                "date",
            ),
            _F(
                "issuing_country",
                "Issuing country or country code",
                ("Issuing country", "Issuing state", "Country code", "Code"),
                "country",
            ),
        ),
        ("passport", "passeport", "pasaporte", "p<"),
    ),
    DocumentTypeSpec(
        DocumentKind.MARRIAGE_CERTIFICATE.value,
        "A marriage certificate or marriage registration",
        (
            _F(
                "spouse_1_name",
                "Name of the first party (husband / groom / spouse 1)",
                ("Husband", "Name of husband", "Groom", "Bridegroom", "Spouse 1", "Party 1"),
            ),
            _F(
                "spouse_2_name",
                "Name of the second party (wife / bride / spouse 2)",
                ("Wife", "Name of wife", "Bride", "Spouse 2", "Party 2"),
            ),
            _F(
                "spouse_1_date_of_birth",
                "Date of birth of the first party",
                (
                    "Husband's date of birth",
                    "Date of birth of husband",
                    "Groom's date of birth",
                    "Spouse 1 date of birth",
                ),
                "date",
            ),
            _F(
                "spouse_2_date_of_birth",
                "Date of birth of the second party",
                (
                    "Wife's date of birth",
                    "Date of birth of wife",
                    "Bride's date of birth",
                    "Spouse 2 date of birth",
                ),
                "date",
            ),
            _F(
                "date_of_marriage",
                "Date of marriage",
                ("Date of marriage", "Marriage date", "Date of solemnisation", "Solemnised on"),
                "date",
            ),
            _F(
                "country_of_marriage",
                "Country where the marriage was registered",
                ("Country of marriage", "Country", "Place of marriage"),
                "country",
            ),
            _F(
                "issuing_authority",
                "Registering authority",
                ("Issuing authority", "Registrar", "Issued by", "Registered by"),
            ),
            _F(
                "attested",
                "Whether it carries the UAE attestation (legalisation) stamps",
                ("Attestation", "Attested", "Legalisation", "MOFA attestation", "UAE attestation"),
                "boolean",
            ),
            _F(
                "home_attested",
                "Whether the issuing country's foreign ministry has attested it",
                (
                    "Home country attestation",
                    "Home attestation",
                    "MEA attestation",
                    "Foreign ministry attestation",
                ),
                "boolean",
            ),
        ),
        ("marriage certificate", "certificate of marriage", "marriage registration", "nikah"),
    ),
    DocumentTypeSpec(
        DocumentKind.EMPLOYMENT_LETTER.value,
        "An employment letter, contract or salary certificate",
        (
            _F("employee_name", "Employee's name", ("Employee name", "Employee", "Name")),
            _F("employer", "Employer", ("Employer", "Company", "Organisation", "Organization")),
            _F("job_title", "Job title", ("Job title", "Designation", "Position", "Title")),
            _F(
                "monthly_salary",
                "Monthly salary with currency",
                ("Monthly salary", "Gross monthly salary", "Total monthly salary", "Salary"),
                "money",
            ),
            _F(
                "start_date",
                "Employment start date",
                ("Date of joining", "Joining date", "Start date", "Employed since"),
                "date",
            ),
            _F(
                "accommodation_provided",
                "Whether the employer provides accommodation",
                ("Accommodation provided", "Accommodation", "Housing provided", "Housing"),
                "boolean",
            ),
        ),
        (
            "employment letter",
            "employment certificate",
            "salary certificate",
            "letter of employment",
            "employment contract",
            "offer letter",
        ),
    ),
    DocumentTypeSpec(
        DocumentKind.BUSINESS_DOCUMENT.value,
        "A trade licence, certificate of incorporation, business plan or similar",
        (
            _F("document_title", "Title of the document", ("Document", "Document type")),
            _F(
                "company_name",
                "Company or trade name",
                ("Company name", "Trade name", "Entity name", "Name of company"),
            ),
            _F("legal_form", "Legal form", ("Legal form", "Legal type", "Entity type")),
            _F(
                "registration_authority",
                "Licensing or registration authority",
                (
                    "Registration authority",
                    "Licensing authority",
                    "Issuing authority",
                    "Issued by",
                    "Planned registration authority",
                    "Planned jurisdiction",
                ),
            ),
            _F(
                "activities",
                "Licensed business activities",
                ("Business activities", "Licensed activities", "Activities", "Activity"),
                "list",
            ),
            _F("expiry_date", "Licence expiry date", ("Expiry date", "Valid until"), "date"),
        ),
        (
            "trade licence",
            "trade license",
            "commercial licence",
            "commercial license",
            "certificate of incorporation",
            "memorandum of association",
            "articles of association",
            "business plan",
            "business profile",
            "company profile",
            "commercial registration",
        ),
    ),
    DocumentTypeSpec(
        DocumentKind.TENANCY_DOCUMENT.value,
        "A tenancy contract, lease or Tawtheeq registration",
        (
            _F("tenant_name", "Tenant's name", ("Tenant name", "Tenant", "Lessee")),
            _F(
                "property_area",
                "Area or community of the property",
                ("Property area", "Community", "Area", "Location"),
            ),
            _F("property_city", "City or emirate", ("City", "Emirate")),
            _F(
                "tenancy_start",
                "Contract start date",
                ("Contract start", "Tenancy start", "Start date", "From"),
                "date",
            ),
            _F(
                "tenancy_end",
                "Contract end date",
                ("Contract end", "Tenancy end", "End date", "To"),
                "date",
            ),
            _F(
                "annual_rent",
                "Annual rent with currency",
                ("Annual rent", "Rent amount", "Rent"),
                "money",
            ),
            _F(
                "registered",
                "Whether it is registered (e.g. with Tawtheeq)",
                ("Tawtheeq registered", "Registered", "Registration status"),
                "boolean",
            ),
        ),
        ("tenancy contract", "tenancy agreement", "lease agreement", "tawtheeq", "tenancy"),
    ),
    DocumentTypeSpec(
        DocumentKind.IDENTITY_DOCUMENT.value,
        "An identity card, e.g. an Emirates ID or a national ID card",
        (
            _F("document_title", "Card type", ("Card type", "Document")),
            _F("full_name", "Full name", ("Full name", "Name")),
            _F("nationality", "Nationality", ("Nationality",), "country"),
            _F("date_of_birth", "Date of birth", ("Date of birth", "DOB", "Birth date"), "date"),
            _F(
                "expiry_date",
                "Expiry date",
                ("Expiry date", "Date of expiry", "Valid until"),
                "date",
            ),
            _F(
                "issuing_country",
                "Issuing country",
                ("Issuing country", "Issuing state", "Country"),
                "country",
            ),
        ),
        ("identity card", "emirates id", "national id", "resident identity", "id card"),
    ),
    DocumentTypeSpec(
        DocumentKind.MISCELLANEOUS.value,
        "Any other document",
        (
            _F("document_title", "Title of the document", ("Title", "Document", "Subject")),
            _F("issuer", "Who issued it", ("Issued by", "Issuer", "From")),
            _F("issue_date", "Date of issue", ("Date of issue", "Issue date", "Date"), "date"),
        ),
        (),
    ),
)

TYPE_SPECS: dict[DocumentKind, DocumentTypeSpec] = {
    DocumentKind(spec.name): spec for spec in _TYPES
}
READ_SCHEMA: tuple[DocumentTypeSpec, ...] = _TYPES

FIELD_LABELS: dict[str, str] = {
    "surname": "Surname",
    "given_names": "Given names",
    "full_name": "Full name",
    "nationality": "Nationality",
    "date_of_birth": "Date of birth",
    "date_of_expiry": "Expiry date",
    "issuing_country": "Issuing country",
    "spouse_1_name": "First party",
    "spouse_2_name": "Second party",
    "date_of_marriage": "Date of marriage",
    "country_of_marriage": "Country of marriage",
    "issuing_authority": "Issuing authority",
    "spouse_1_date_of_birth": "First party's date of birth",
    "spouse_2_date_of_birth": "Second party's date of birth",
    "attested": "UAE attestation",
    "home_attested": "Home-country attestation",
    "employee_name": "Employee",
    "employer": "Employer",
    "job_title": "Job title",
    "monthly_salary": "Monthly salary",
    "start_date": "Start date",
    "accommodation_provided": "Accommodation provided",
    "document_title": "Title",
    "company_name": "Company name",
    "legal_form": "Legal form",
    "registration_authority": "Registration authority",
    "activities": "Business activities",
    "expiry_date": "Expiry date",
    "tenant_name": "Tenant",
    "property_area": "Area",
    "property_city": "City",
    "tenancy_start": "Tenancy start",
    "tenancy_end": "Tenancy end",
    "annual_rent": "Annual rent",
    "registered": "Registered",
    "issuer": "Issued by",
    "issue_date": "Issue date",
}


def field_label(name: str) -> str:
    return FIELD_LABELS.get(name, name.replace("_", " ").capitalize())


def field_kind(kind: DocumentKind, name: str) -> str:
    for spec in TYPE_SPECS[kind].fields:
        if spec.name == name:
            return spec.kind
    return "text"
