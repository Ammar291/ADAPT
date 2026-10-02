"""The journey nodes, in workflow order."""

from __future__ import annotations

from app.agents.journey.nodes.analysis import (
    dependency_analysis,
    eligibility_analysis,
    requirement_planner,
    risk_detection,
)
from app.agents.journey.nodes.human import execution_or_handoff, final_plan, human_approval
from app.agents.journey.nodes.outputs import action_preparation, document_preparation
from app.agents.journey.nodes.understanding import document_analysis, intake, profile_analysis

# START -> ... -> END, exactly as specified.
JOURNEY_SEQUENCE = (
    intake,
    profile_analysis,
    document_analysis,
    eligibility_analysis,
    requirement_planner,
    dependency_analysis,
    risk_detection,
    document_preparation,
    action_preparation,
    human_approval,
    execution_or_handoff,
    final_plan,
)

# Nodes a what-if may re-run: pure analysis plus previews. Understanding nodes read
# inputs a scenario doesn't change (request, saved profile, documents), and the human
# and execution nodes have side effects, so what-ifs never run them.
SIMULATION_SEQUENCE = (
    eligibility_analysis,
    requirement_planner,
    dependency_analysis,
    risk_detection,
    document_preparation,
    action_preparation,
)

__all__ = ["JOURNEY_SEQUENCE", "SIMULATION_SEQUENCE"]
