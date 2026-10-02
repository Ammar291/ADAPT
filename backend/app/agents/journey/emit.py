"""Typed event emission for journey nodes and tools.

Calls the platform `EventSink` helpers (tool_called, tool_result, evidence_found,
document_generated, approval_required, approval_resolved, action_prepared) with the
current node filled in. A helper a sink doesn't provide is skipped, never faked, so the
agent keeps working against a minimal sink (e.g. in tests).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.context import AgentContext
from app.agents.instrumentation import current_node

logger = logging.getLogger(__name__)


async def emit(context: AgentContext, helper: str, *args: Any, **kwargs: Any) -> None:
    fn = getattr(context.events, helper, None)
    if fn is None:
        logger.debug("event_helper_missing", extra={"helper": helper})
        return
    kwargs.setdefault("node", current_node())
    await fn(*args, **kwargs)
