"""API contracts (source of truth for `packages/contracts` TypeScript types).

Models used by a registered route appear in OpenAPI automatically. Models listed in
`EXTRA_CONTRACT_MODELS` are contracts for non-HTTP channels (the agent event stream) or
shared read shapes that other workstreams serve; they are injected into the OpenAPI
components so the frontend can build against them.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.contracts.actions import ActionApprovalOut, ActionOut
from app.contracts.agents import AgentTopology
from app.contracts.common import ProblemDetail
from app.contracts.events import AgentEvent
from app.contracts.journey import JourneyOut, JourneySummary
from app.contracts.voice import (
    VoiceSessionOut,
    VoiceSessionRequest,
    VoiceToolCallRequest,
    VoiceToolCallResult,
)

# (model, is_request). Request models use validation-mode schemas (defaults optional);
# response models use serialization-mode schemas (every field present).
EXTRA_CONTRACT_MODELS: list[tuple[type[BaseModel], bool]] = [
    (ProblemDetail, False),
    (AgentEvent, False),
    (AgentTopology, False),
    (JourneyOut, False),
    (JourneySummary, False),
    (ActionOut, False),
    (ActionApprovalOut, False),
    (VoiceSessionRequest, True),
    (VoiceSessionOut, False),
    (VoiceToolCallRequest, True),
    (VoiceToolCallResult, False),
]
