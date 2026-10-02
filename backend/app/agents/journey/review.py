"""Human-in-the-loop gates: what the graph asks (interrupt payload) and how the user answers.

Three gates pause the run with a LangGraph `interrupt(...)`:

* action_approval         consequential actions (applications, bookings, submissions)
* document_correction     extracted document fields with low confidence
* submission_confirmation the outcome of a step the user completed on an official site

The payload is persisted on the run (`agent_runs.pending_review`) and announced with
`approval_required` events. The answer comes back through the API, which validates it
with `validate_response` and resumes the run with `Command(resume=answer)`. Nodes
re-validate on resume. For action approvals, they also re-read the decisions from the
database: the approval rows, not the resume payload, are authoritative.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.agents.journey.vocab import ReviewGate
from app.domain.actions import UserConfirmation


def review_id_for(run_id: str, gate: ReviewGate) -> str:
    """Deterministic per run and gate, so a node re-run on resume computes the same id."""
    return f"rev_{uuid.uuid5(uuid.NAMESPACE_URL, f'adapt:{run_id}:{gate.value}').hex[:20]}"


# --- what the user is asked -------------------------------------------------------------


class EvidenceBrief(BaseModel):
    title: str
    source_url: str | None = None
    kind: str


class ActionReviewItem(BaseModel):
    action_id: str
    approval_id: str
    action_type: str
    title: str
    summary: str
    consequences: list[str]
    payload_preview: dict[str, Any]
    official_url: str | None
    reversible: bool
    requires_user_authentication: bool
    is_simulated: bool
    simulation_label: str | None
    task_key: str
    evidence: list[EvidenceBrief] = Field(default_factory=list)
    # Filled on read from the approval row (the authority), not stored in the payload: the
    # person decides items one by one while the run stays paused.
    approval_status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    decided_at: datetime | None = None


class FieldReview(BaseModel):
    name: str
    label: str
    value: str | None
    confidence: float
    needs_review: bool


class DocumentReviewItem(BaseModel):
    document_id: str
    kind: str
    holder: str
    review_task_ids: list[str]
    fields: list[FieldReview]


class SubmissionReviewItem(BaseModel):
    action_id: str
    action_type: str
    title: str
    official_url: str | None
    is_simulated: bool
    simulation_label: str | None


class _Review(BaseModel):
    review_id: str
    run_id: str
    journey_id: str
    title: str
    summary: str


class ActionApprovalReview(_Review):
    gate: Literal[ReviewGate.ACTION_APPROVAL] = ReviewGate.ACTION_APPROVAL
    items: list[ActionReviewItem]


class DocumentCorrectionReview(_Review):
    gate: Literal[ReviewGate.DOCUMENT_CORRECTION] = ReviewGate.DOCUMENT_CORRECTION
    items: list[DocumentReviewItem]


class SubmissionConfirmationReview(_Review):
    gate: Literal[ReviewGate.SUBMISSION_CONFIRMATION] = ReviewGate.SUBMISSION_CONFIRMATION
    items: list[SubmissionReviewItem]


PendingReview = Annotated[
    ActionApprovalReview | DocumentCorrectionReview | SubmissionConfirmationReview,
    Field(discriminator="gate"),
]
PENDING_REVIEW: TypeAdapter[
    ActionApprovalReview | DocumentCorrectionReview | SubmissionConfirmationReview
] = TypeAdapter(PendingReview)


# --- how the user answers ----------------------------------------------------------------


class ActionDecision(BaseModel):
    action_id: str
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=1000)


class ActionApprovalResponse(BaseModel):
    gate: Literal[ReviewGate.ACTION_APPROVAL] = ReviewGate.ACTION_APPROVAL
    review_id: str
    decisions: list[ActionDecision] = Field(default_factory=list)


class ReviewFieldCorrection(BaseModel):
    name: str
    value: str | None = Field(max_length=500)


class DocumentCorrection(BaseModel):
    document_id: str
    corrections: list[ReviewFieldCorrection] = Field(default_factory=list)
    confirm: bool = True


class DocumentCorrectionResponse(BaseModel):
    gate: Literal[ReviewGate.DOCUMENT_CORRECTION] = ReviewGate.DOCUMENT_CORRECTION
    review_id: str
    documents: list[DocumentCorrection]


class SubmissionConfirmationAnswer(UserConfirmation):
    action_id: str


class SubmissionConfirmationResponse(BaseModel):
    gate: Literal[ReviewGate.SUBMISSION_CONFIRMATION] = ReviewGate.SUBMISSION_CONFIRMATION
    review_id: str
    confirmations: list[SubmissionConfirmationAnswer]


ReviewResponse = Annotated[
    ActionApprovalResponse | DocumentCorrectionResponse | SubmissionConfirmationResponse,
    Field(discriminator="gate"),
]
REVIEW_RESPONSE: TypeAdapter[
    ActionApprovalResponse | DocumentCorrectionResponse | SubmissionConfirmationResponse
] = TypeAdapter(ReviewResponse)


class ReviewMismatch(ValueError):
    """The answer does not match the gate the run is paused on."""


def validate_response(
    review: ActionApprovalReview | DocumentCorrectionReview | SubmissionConfirmationReview,
    response: ActionApprovalResponse | DocumentCorrectionResponse | SubmissionConfirmationResponse,
) -> None:
    if response.review_id != review.review_id:
        raise ReviewMismatch("this review is no longer pending")
    if response.gate != review.gate:
        raise ReviewMismatch(f"expected an answer for {review.gate.value}")
    match review, response:
        case ActionApprovalReview(), ActionApprovalResponse():
            if len({d.action_id for d in response.decisions}) != len(response.decisions):
                raise ReviewMismatch("answer each action only once")
            known = {i.action_id for i in review.items}
            unknown = {d.action_id for d in response.decisions} - known
            if unknown:
                raise ReviewMismatch(f"unknown actions: {sorted(unknown)}")
        case DocumentCorrectionReview(), DocumentCorrectionResponse():
            if len({d.document_id for d in response.documents}) != len(response.documents):
                raise ReviewMismatch("answer each document only once")
            fields = {i.document_id: {f.name for f in i.fields} for i in review.items}
            for doc in response.documents:
                if len({c.name for c in doc.corrections}) != len(doc.corrections):
                    raise ReviewMismatch("correct each field only once")
                if doc.document_id not in fields:
                    raise ReviewMismatch(f"document {doc.document_id} is not under review")
                extra = {c.name for c in doc.corrections} - fields[doc.document_id]
                if extra:
                    raise ReviewMismatch(f"unknown fields: {sorted(extra)}")
            missing = set(fields) - {d.document_id for d in response.documents}
            if missing:
                raise ReviewMismatch(f"answer every document under review: {sorted(missing)}")
        case SubmissionConfirmationReview(), SubmissionConfirmationResponse():
            known = {i.action_id for i in review.items}
            answered = {c.action_id for c in response.confirmations}
            if len(answered) != len(response.confirmations):
                raise ReviewMismatch("answer each action only once")
            if answered - known:
                raise ReviewMismatch(f"unknown actions: {sorted(answered - known)}")
            if known - answered:
                raise ReviewMismatch(f"answer every handed-off step: {sorted(known - answered)}")
