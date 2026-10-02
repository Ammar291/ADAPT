"""Tool outcomes: what a tool returns, and how API failures map to something the
assistant can explain honestly."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.contracts.voice import ApprovalRequest, ConsentRequest, ToolCitation, ToolStatus
from app.voice.gateway import ApiResponse
from app.voice.shaping import shape


@dataclass
class ToolOutcome:
    status: ToolStatus
    data: Any = None
    summary: str | None = None
    guidance: str | None = None
    approval: ApprovalRequest | None = None
    consent: ConsentRequest | None = None
    ui_hint: str | None = None
    citations: list[ToolCitation] = field(default_factory=list)

    def model_output(self) -> dict[str, Any]:
        output: dict[str, Any] = {"status": self.status}
        if self.summary:
            output["summary"] = self.summary
        if self.data is not None:
            output["data"] = self.data
        if self.guidance:
            output["guidance"] = self.guidance
        return output


def rate_limited() -> ToolOutcome:
    return ToolOutcome(
        "unavailable",
        summary="Too many requests just now",
        guidance="ADAPT is limiting requests for a moment. Tell the person briefly and offer "
        "to try again in a minute.",
    )


def unavailable(what: str) -> ToolOutcome:
    return ToolOutcome(
        "unavailable",
        summary=f"{what} isn't available yet",
        guidance=f"{what} isn't available in ADAPT right now. Say so briefly and offer what "
        "you can do instead. Don't imply it happened.",
    )


_CONSENT_COPY: dict[str, tuple[str, str]] = {
    "faith_personalization": (
        "Include faith in your suggestions?",
        "ADAPT would include places of worship and faith communities. It stays off unless "
        "you allow it, and you can turn it off any time in Settings.",
    ),
    "community_personalization": (
        "Personalise community suggestions?",
        "ADAPT would use the background and interests you've shared to suggest communities "
        "and events. It stays off unless you allow it, and you can change it in Settings.",
    ),
}


def consent_outcome(preference: str) -> ToolOutcome:
    if preference not in _CONSENT_COPY:
        preference = "community_personalization"
    title, detail = _CONSENT_COPY[preference]
    return ToolOutcome(
        "needs_consent",
        summary="Needs your permission",
        guidance="This needs the person's explicit opt-in. Explain in one sentence what it "
        "would change and that they can allow it with the button on screen, or carry on "
        "without it. Don't ask about their faith or background yourself.",
        consent=ConsentRequest(preference=preference, title=title, detail=detail),  # type: ignore[arg-type]
    )


def failure(response: ApiResponse, *, what: str) -> ToolOutcome:
    """Map a non-2xx API response to an outcome the assistant can explain."""
    status, code = response.status, response.code
    if status == 401:
        return ToolOutcome(
            "error",
            summary="Session expired",
            guidance="The person's session has expired. Ask them to reload the app.",
        )
    if status == 404:
        reason = f" The service said: {response.detail}." if response.detail else ""
        return ToolOutcome(
            "not_found",
            summary=response.detail or "Not found",
            guidance=f"{what}: nothing matching was found.{reason} Say so in your own words, "
            "and offer an alternative.",
        )
    if status == 409 and code == "consent_required":
        extra = response.body.get("extra") if isinstance(response.body, dict) else None
        preference = extra.get("consent") if isinstance(extra, dict) else None
        return consent_outcome(str(preference or "community_personalization"))
    if status == 422:
        errors = response.body.get("errors") if isinstance(response.body, dict) else None
        return ToolOutcome(
            "invalid_arguments",
            data=shape(errors) if errors else None,
            summary="Needs different details",
            guidance="The request was rejected as invalid. Fix the arguments and try again, "
            "or ask the person for the missing detail.",
        )
    if status in (429, 502, 503, 504):
        return ToolOutcome(
            "unavailable",
            summary=f"{what} is temporarily unavailable",
            guidance=f"{what} is temporarily unavailable. Offer to try again shortly.",
        )
    if status >= 500:
        return ToolOutcome(
            "error",
            summary=f"{what} ran into a problem",
            guidance=f"{what} failed because of a problem on ADAPT's side. Apologise briefly "
            "and offer to try again; don't guess the answer.",
        )
    reason = f" The service said: {response.detail}." if response.detail else ""
    return ToolOutcome(
        "error",
        summary=f"{what} didn't work",
        guidance=f"{what} was refused.{reason} Explain briefly in your own words and suggest "
        "what the person can do instead.",
    )
