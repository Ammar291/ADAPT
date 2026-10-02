"""Closed vocabularies of the journey agent (stage ids, gates, risks, task kinds).

Stage ids are shared verbatim with the frontend's agent console and the topology
endpoint, so renaming one is a breaking change.
"""

from __future__ import annotations

from enum import StrEnum


class NodeId(StrEnum):
    # --- core journey workflow (in execution order) --------------------------------
    INTAKE = "intake"
    PROFILE_ANALYSIS = "profile_analysis"
    DOCUMENT_ANALYSIS = "document_analysis"
    ELIGIBILITY_ANALYSIS = "eligibility_analysis"
    REQUIREMENT_PLANNER = "requirement_planner"
    DEPENDENCY_ANALYSIS = "dependency_analysis"
    RISK_DETECTION = "risk_detection"
    DOCUMENT_PREPARATION = "document_preparation"
    ACTION_PREPARATION = "action_preparation"
    HUMAN_APPROVAL = "human_approval"
    EXECUTION_OR_HANDOFF = "execution_or_handoff"
    FINAL_PLAN = "final_plan"
    # --- what-if branch ----------------------------------------------------------------
    APPLY_SCENARIO = "apply_scenario"
    COMPARE_SCENARIOS = "compare_scenarios"


class ReviewGate(StrEnum):
    """Human-in-the-loop gates. Each pauses the run with a LangGraph interrupt."""

    ACTION_APPROVAL = "action_approval"  # consequential actions need the user's approval
    DOCUMENT_CORRECTION = "document_correction"  # low-confidence extracted fields
    SUBMISSION_CONFIRMATION = "submission_confirmation"  # outcome of an external step


class RiskKind(StrEnum):
    MISSING_USER_DOCUMENT = "missing_user_document"
    MISSING_INFORMATION = "missing_information"
    MISSING_SOURCE_EVIDENCE = "missing_source_evidence"
    TIMELINE_DEPENDENCY = "timeline_dependency"
    INCOMPATIBLE_TASK_ORDERING = "incompatible_task_ordering"
    EXTERNAL_LOGIN_REQUIRED = "external_login_required"
    ELIGIBILITY_GAP = "eligibility_gap"


class RiskSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class TaskKind(StrEnum):
    """What a planned task is, mirrored from the governance node it comes from."""

    SERVICE = "service"  # apply for a government service
    REQUIREMENT = "requirement"  # meet a precondition off-platform (e.g. home attestation)
    APPOINTMENT = "appointment"  # an in-person step (screening, biometrics)


class TaskStatus(StrEnum):
    READY = "ready"  # every prerequisite task is done
    BLOCKED = "blocked"  # waiting for a prerequisite task
    DONE = "done"  # the user reported it done, or holds what it produces
    NOT_APPLICABLE = "not_applicable"


class DependencyKind(StrEnum):
    SERVICE = "service"  # governance depends_on between services
    ALTERNATIVE = "alternative"  # one option of an OR-group (dependency node)
    DOCUMENT = "document"  # needs a document another task produces
    REQUIREMENT = "requirement"  # needs an off-platform requirement task first
    APPOINTMENT = "appointment"  # includes an in-person appointment


class Subject(StrEnum):
    """Whose task it is. Facts about household members use the subject as a key prefix."""

    SELF = "self"
    SPOUSE = "spouse"


SIMULATION_LABEL = "DEMO / SIMULATED"
