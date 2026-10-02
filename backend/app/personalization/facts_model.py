"""Closed vocabularies for facts and review tasks (stored as CHECK-constrained VARCHAR)."""

from __future__ import annotations

from enum import StrEnum


class FactStatus(StrEnum):
    ACCEPTED = "accepted"  # part of the user graph; plans may rely on it
    NEEDS_REVIEW = "needs_review"  # proposed; waits for the person, never used for planning


class ReviewTaskKind(StrEnum):
    LOW_CONFIDENCE = "low_confidence"  # read, but not confidently or not validly
    CONFLICT = "conflict"  # differs from a value already in the twin
    EXTRACTION_FAILED = "extraction_failed"  # nothing could be read automatically
    KIND_MISMATCH = "kind_mismatch"  # it doesn't look like the document the person chose


class ReviewTaskStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReviewResolution(StrEnum):
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"  # a newer extraction replaced it
