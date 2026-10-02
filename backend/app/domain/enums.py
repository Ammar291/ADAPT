"""Closed vocabularies shared by persistence, services, agents and API contracts.

These enums are exported to the frontend through the generated OpenAPI contract, so
renaming a member is a breaking API change.
"""

from __future__ import annotations

from enum import StrEnum


class GraphType(StrEnum):
    """Which logical knowledge graph a node or edge belongs to (`graph_type` column)."""

    GOVERNANCE = "governance"  # shared, public institutional knowledge
    USER = "user"  # private, per-user graph (the user's digital twin)


class GovernanceNodeType(StrEnum):
    AUTHORITY = "authority"  # e.g. ICP, ADGM Registration Authority, Abu Dhabi DED
    SERVICE = "service"  # a government service a person can apply for
    REQUIREMENT = "requirement"  # a condition a service needs (e.g. registered premises)
    ELIGIBILITY_RULE = "eligibility_rule"  # e.g. minimum salary for family sponsorship
    DOCUMENT = "document"  # a document type, e.g. passport, attested marriage certificate
    DEPENDENCY = "dependency"  # an OR-group precondition, e.g. "a company licence"
    APPOINTMENT = "appointment"  # an in-person step, e.g. medical screening, biometrics
    PORTAL = "portal"  # official channel: portal / app / service centre (TAMM, ICP app)
    LOCATION = "location"  # e.g. free zone, emirate, service centre
    PROCESS_STEP = "process_step"
    FEE = "fee"
    LEGAL_INSTRUMENT = "legal_instrument"  # law, decree, regulation


class TwinNodeType(StrEnum):
    """Entity types of the private user graph (the user's digital twin)."""

    PERSON = "person"  # the user
    HOUSEHOLD = "household"
    SPOUSE = "spouse"
    CHILD = "child"
    PASSPORT = "passport"
    VISA = "visa"
    NATIONALITY = "nationality"
    COMPANY = "company"  # e.g. the company the founder is establishing
    BUSINESS_ACTIVITY = "business_activity"
    GOAL = "goal"
    HOUSING_PREFERENCE = "housing_preference"
    BUDGET = "budget"
    LANGUAGE = "language"
    PREFERENCE = "preference"
    DOCUMENT = "document"  # an uploaded document (metadata only; bytes live in storage)
    APPOINTMENT = "appointment"
    COMMUNITY_PREFERENCE = "community_preference"


class GraphEdgeType(StrEnum):
    """Edge `relation` vocabulary."""

    # governance -> governance
    PROVIDES = "provides"  # authority -> service
    REQUIRES = "requires"  # service -> requirement / document / eligibility_rule
    DEPENDS_ON = "depends_on"  # service -> service | dependency (must be satisfied first)
    SATISFIED_BY = "satisfied_by"  # dependency -> service (any one satisfies the group)
    PRODUCES = "produces"  # service -> document (outcome of the service)
    APPLIES_TO = "applies_to"  # eligibility_rule -> service
    AVAILABLE_AT = "available_at"  # service -> portal
    MAY_REQUIRE = "may_require"  # service -> appointment
    GOVERNED_BY = "governed_by"  # service/rule -> legal_instrument
    LOCATED_IN = "located_in"  # authority/service -> location
    # user -> user
    HAS_HOUSEHOLD_MEMBER = "has_household_member"  # person -> spouse | child
    MEMBER_OF = "member_of"  # person -> household
    HAS_DOCUMENT = "has_document"  # person | spouse | child -> passport | document
    HOLDS_VISA = "holds_visa"  # -> visa
    HAS_NATIONALITY = "has_nationality"  # -> nationality
    HAS_GOAL = "has_goal"  # person -> goal
    PREFERS = "prefers"  # -> housing_preference | preference
    SEEKS = "seeks"  # -> community_preference
    FOUNDER_OF = "founder_of"  # person -> company
    ENGAGES_IN = "engages_in"  # company -> business_activity
    SPEAKS = "speaks"  # -> language
    HAS_BUDGET = "has_budget"  # -> budget
    HAS_APPOINTMENT = "has_appointment"  # -> appointment
    # user -> governance (personalisation links; always private)
    PURSUES = "pursues"  # goal -> governance service
    SATISFIES = "satisfies"  # document -> governance requirement / document_type
    INSTANCE_OF = "instance_of"  # user document -> governance document_type
    ELIGIBLE_FOR = "eligible_for"  # person -> governance service (assessed)
    BLOCKED_BY = "blocked_by"  # goal -> governance requirement not yet met


class EvidenceKind(StrEnum):
    """Trust tier of any claim shown to a user. Rendered distinctly in the UI."""

    AUTHORITATIVE_REQUIREMENT = "authoritative_requirement"  # binding rule from an official source
    OFFICIAL_GUIDANCE = "official_guidance"  # published by an authority, but advisory
    COMMUNITY_WEB = "community_web"  # current web finding; never authoritative
    AI_RECOMMENDATION = "ai_recommendation"  # ADAPT's own reasoning/suggestion


class FactSource(StrEnum):
    USER_STATED = "user_stated"
    DOCUMENT_EXTRACTED = "document_extracted"
    INFERRED = "inferred"
    SYSTEM = "system"


class ConsentStatus(StrEnum):
    NOT_ASKED = "not_asked"
    GRANTED = "granted"
    DECLINED = "declined"


# --- profile & household ---------------------------------------------------------------


class HouseholdRelationship(StrEnum):
    SPOUSE = "spouse"
    CHILD = "child"
    PARENT = "parent"
    SIBLING = "sibling"
    DOMESTIC_WORKER = "domestic_worker"
    OTHER = "other"


class RelocationPlan(StrEnum):
    """When a household member moves relative to the user."""

    WITH_USER = "with_user"
    LATER = "later"
    ALREADY_IN_UAE = "already_in_uae"
    NOT_RELOCATING = "not_relocating"
    UNDECIDED = "undecided"


class GoalType(StrEnum):
    ESTABLISH_COMPANY = "establish_company"
    RESIDENCY = "residency"
    SPONSOR_FAMILY = "sponsor_family"
    FIND_HOUSING = "find_housing"
    SCHOOLING = "schooling"
    HEALTHCARE = "healthcare"
    BANKING = "banking"
    EMPLOYMENT = "employment"
    COMMUNITY = "community"
    DRIVING = "driving"
    OTHER = "other"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ACHIEVED = "achieved"
    DROPPED = "dropped"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PreferenceCategory(StrEnum):
    HOUSING = "housing"
    BUDGET = "budget"
    LANGUAGE = "language"
    COMMUNITY = "community"
    FOOD = "food"
    SCHOOLING = "schooling"
    TRANSPORT = "transport"
    FAITH = "faith"  # only with explicit opt-in, and only ever stated by the user
    OTHER = "other"


# --- agent runs ---------------------------------------------------------------------------


class RunKind(StrEnum):
    JOURNEY = "journey"
    WHAT_IF = "what_if"
    RESEARCH = "research"
    DOCUMENT_EXTRACTION = "document_extraction"
    DRAFTING = "drafting"
    DIAGNOSTIC = "diagnostic"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"  # LangGraph interrupt: approval or clarifying question
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}


# --- actions & approvals ---------------------------------------------------------------------


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ActionKind(StrEnum):
    """`actions.type`. Only real, authenticated integrations may ever submit anything."""

    GOVERNMENT_PORTAL = "government_portal"  # an application on an official portal
    APPOINTMENT = "appointment"  # booking through an explicit adapter
    DOCUMENT_SUBMISSION = "document_submission"  # sending documents through an adapter
    OFFICIAL_HANDOFF = "official_handoff"  # deep link to an official service; user completes it


class ActionStatus(StrEnum):
    DRAFT = "draft"  # being assembled by the agent
    PREPARED = "prepared"  # described; nothing has happened externally
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"  # the user approved; not yet executed
    SUBMITTED = "submitted"  # sent to a real external system; awaiting its confirmation
    COMPLETED = "completed"  # confirmed with the external system's reference
    HANDOFF_REQUIRED = "handoff_required"  # the user completes it on the official channel
    BLOCKED = "blocked"  # a dependency or missing input prevents it
    REJECTED = "rejected"  # the user declined it; nothing happened externally
    CANCELLED = "cancelled"
    FAILED = "failed"


class ConfirmationSource(StrEnum):
    ADAPTER = "adapter"  # the external system returned a reference
    USER_REPORTED = "user_reported"  # the user told ADAPT they completed it themselves


# --- documents -------------------------------------------------------------------------------


class DocumentKind(StrEnum):
    PASSPORT = "passport"
    MARRIAGE_CERTIFICATE = "marriage_certificate"
    BIRTH_CERTIFICATE = "birth_certificate"
    EMIRATES_ID = "emirates_id"
    RESIDENCE_VISA = "residence_visa"
    DEGREE_CERTIFICATE = "degree_certificate"
    TENANCY_CONTRACT = "tenancy_contract"
    TRADE_LICENSE = "trade_license"
    BANK_STATEMENT = "bank_statement"
    SALARY_CERTIFICATE = "salary_certificate"
    PHOTO = "photo"
    OTHER = "other"


class DocumentStatus(StrEnum):
    """Upload lifecycle: uploaded -> processing -> needs_review -> confirmed.

    `failed` when extraction fails (can be reprocessed); `deleted` once the stored bytes
    have been destroyed (the metadata row is kept only as a tombstone).
    """

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    DELETED = "deleted"


class FactStatus(StrEnum):
    PROPOSED = "proposed"  # extracted, not yet reviewed
    CONFIRMED = "confirmed"  # the user confirmed the extracted value
    CORRECTED = "corrected"  # the user replaced the extracted value
    REJECTED = "rejected"  # the user said the value is wrong and gave none


class GeneratedDocumentKind(StrEnum):
    COVER_LETTER = "cover_letter"
    EMAIL = "email"
    CHECKLIST = "checklist"
    FORM_PREFILL = "form_prefill"
    BUSINESS_SUMMARY = "business_summary"
    APPOINTMENT_BRIEF = "appointment_brief"
    PLAN = "plan"


class GeneratedDocumentStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    DISCARDED = "discarded"


# --- journeys ---------------------------------------------------------------------------------


class JourneyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SCENARIO = "scenario"  # a "What if?" simulation branch; never acted upon
    ARCHIVED = "archived"


class StepStatus(StrEnum):
    BLOCKED = "blocked"  # a dependency is not complete
    NEEDS_INFO = "needs_info"  # ADAPT needs a fact or document from the user
    READY = "ready"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    HANDOFF = "handoff"  # the user must complete it on an official channel
    DONE = "done"
    NOT_APPLICABLE = "not_applicable"


class StepCategory(StrEnum):
    BUSINESS = "business"
    RESIDENCY = "residency"
    FAMILY = "family"
    HOUSING = "housing"
    HEALTH = "health"
    FINANCE = "finance"
    DAILY_LIFE = "daily_life"
    COMMUNITY = "community"


class JourneyEdgeType(StrEnum):
    DEPENDS_ON = "depends_on"  # target must be finished before source can start
    ALTERNATIVE_TO = "alternative_to"  # either node satisfies the same need


class BlockerKind(StrEnum):
    MISSING_INFO = "missing_info"
    MISSING_DOCUMENT = "missing_document"
    DEPENDENCY = "dependency"
    ELIGIBILITY = "eligibility"
    ATTESTATION = "attestation"


class ArtifactType(StrEnum):
    JOURNEY = "journey"
    JOURNEY_NODE = "journey_node"
    TWIN_NODE = "twin_node"
    DOCUMENT_EXTRACTION = "document_extraction"
    EVIDENCE = "evidence"
    GENERATED_DOCUMENT = "generated_document"
    ACTION = "action"
    RESEARCH_RESULT = "research_result"
    CONSIDERATION = "consideration"
    PLAN = "plan"


# --- research & discover ------------------------------------------------------------------------


class ResearchCategory(StrEnum):
    COMMUNITY = "community"
    EVENT = "event"
    CULTURE = "culture"
    PRACTICAL = "practical"
    FAITH = "faith"  # only produced after explicit opt-in


class ResearchJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"  # no live web research configured: nothing was invented
    FAILED = "failed"


class CommunityCategory(StrEnum):
    PROFESSIONAL = "professional"
    SOCIAL = "social"
    CULTURAL = "cultural"
    FAMILY = "family"
    SPORTS = "sports"
    LANGUAGE = "language"
    VOLUNTEERING = "volunteering"
    FAITH = "faith"  # hidden unless the user opted in to faith personalisation


class EventCategory(StrEnum):
    NETWORKING = "networking"
    CULTURE = "culture"
    FAMILY = "family"
    SPORTS = "sports"
    EDUCATION = "education"
    COMMUNITY = "community"
    FAITH = "faith"  # hidden unless the user opted in to faith personalisation


class GuideTopic(StrEnum):
    ETIQUETTE = "etiquette"
    RAMADAN = "ramadan"
    PUBLIC_HOLIDAYS = "public_holidays"
    DRESS = "dress"
    WORKPLACE = "workplace"
    FAMILY_LIFE = "family_life"
    LANGUAGE = "language"
    HERITAGE = "heritage"
    ARTS = "arts"
    CLIMATE = "climate"
    GOVERNMENT_SERVICES = "government_services"
    HEALTH = "health"
    TRANSPORT = "transport"
    SAFETY = "safety"
    UTILITIES = "utilities"


# --- appointments --------------------------------------------------------------------------------


class AppointmentStatus(StrEnum):
    PLANNED = "planned"  # ADAPT suggests it; nothing booked
    REQUESTED = "requested"  # the user started booking on the official channel
    CONFIRMED = "confirmed"  # a real external booking reference exists
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Channel(StrEnum):
    TEXT = "text"
    VOICE = "voice"
