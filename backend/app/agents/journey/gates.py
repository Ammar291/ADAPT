"""What happens when the journey graph pauses at a human gate.

`announce_review` is the `on_interrupt` hook for `execute_run`. It runs once per real
pause, never on a node's resumed re-run:

1. persists the gate payload on the run (`agent_runs.pending_review`), which the API
   serves at GET /agents/{run_id}/review and validates answers against;
2. saves the plan so far as a draft, so the Review step can show the tasks and risks
   behind each decision;
3. emits `approval_required`: one event per action for action approvals, one per
   gate otherwise.
"""

from __future__ import annotations

from typing import Any

from app.agents.journey.context import JourneyContext
from app.agents.journey.emit import emit
from app.agents.journey.nodes.human import plan_snapshot
from app.agents.journey.review import PENDING_REVIEW, ActionApprovalReview
from app.agents.runner import InterruptHook

GATE_NODES = {
    "action_approval": "human_approval",
    "document_correction": "document_analysis",
    "submission_confirmation": "execution_or_handoff",
}


def review_announcer(context: JourneyContext) -> InterruptHook:
    async def announce_review(values: dict[str, Any], interrupts: list[Any]) -> None:
        review = PENDING_REVIEW.validate_python(interrupts[0].value)
        store = context.svc.store
        await store.set_pending_review(run_id=review.run_id, review=review.model_dump(mode="json"))
        if values.get("tasks") and not context.simulation:
            await store.save_plan(
                journey_id=review.journey_id,
                plan=plan_snapshot(values, None),
                tasks=values.get("tasks", []),
                dependencies=values.get("dependencies", []),
                status="draft",
                summary=None,
            )
        node = GATE_NODES[review.gate.value]
        if isinstance(review, ActionApprovalReview):
            for item in review.items:
                await emit(
                    context,
                    "approval_required",
                    approval_id=item.approval_id,
                    action_id=item.action_id,
                    title=item.title,
                    summary=item.summary,
                    gate=review.gate.value,
                    item_count=len(review.items),
                    node=node,
                )
        else:
            await emit(
                context,
                "approval_required",
                approval_id=review.review_id,
                title=review.title,
                summary=review.summary,
                gate=review.gate.value,
                item_count=len(review.items),
                node=node,
            )

    return announce_review
