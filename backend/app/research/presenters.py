"""ORM -> research API contracts. The internal quality score is deliberately not mapped."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.db.models import AgentRun
from app.domain.enums import RunStatus
from app.research.contracts import (
    BRIEF_READY_MESSAGE,
    DISCOVER_SECTIONS,
    DiscoverOut,
    DiscoverSectionOut,
    ResearchCategoryState,
    ResearchCitationOut,
    ResearchContactOut,
    ResearchEventInfo,
    ResearchJobOut,
    ResearchProfileOut,
    ResearchResultOut,
    ResearchRetrievalOut,
)
from app.research.models import ResearchCitation, ResearchJob, ResearchResult
from app.research.profile import ResearchProfile
from app.research.sources import needs_recheck
from app.research.types import CategoryStatus, ResearchCategory, ResearchMode


def events_url(api_prefix: str, run_id: object) -> str:
    return f"{api_prefix}/agents/{run_id}/events"


def _category_states(job: ResearchJob) -> list[ResearchCategoryState]:
    states: list[ResearchCategoryState] = []
    for value in job.categories:
        raw = (job.category_status or {}).get(value) or {}
        states.append(
            ResearchCategoryState(
                category=ResearchCategory(value),
                status=CategoryStatus(raw.get("status", CategoryStatus.PENDING.value)),
                result_count=int(raw.get("result_count") or 0),
                reason=raw.get("reason"),
            )
        )
    return states


def job_out(job: ResearchJob, run: AgentRun, *, api_prefix: str) -> ResearchJobOut:
    profile = ResearchProfile.model_validate(job.profile or {})
    states = _category_states(job)
    return ResearchJobOut(
        id=job.id,
        run_id=run.id,
        status=run.status,
        mode=job.mode,
        categories=states,
        personalised_with=profile.basis(),
        profile=ResearchProfileOut(
            relocation_type=profile.relocation_type,
            profession=profile.profession,
            interests=list(profile.interests),
            background=profile.background,
            faith=profile.faith,
            focus=profile.focus,
            faith_opted_in=profile.faith_opted_in,
            community_opted_in=profile.community_opted_in,
        ),
        result_count=sum(s.result_count for s in states),
        brief_ready=run.status is RunStatus.SUCCEEDED and job.completed_at is not None,
        created_at=job.created_at,
        started_at=run.started_at,
        completed_at=job.completed_at,
        seen_at=job.seen_at,
        events_url=events_url(api_prefix, run.id),
    )


def retrieval_out(mode: ResearchMode | str | None, retrieved_at: datetime) -> ResearchRetrievalOut:
    day = f"{retrieved_at.day} {retrieved_at.strftime('%b %Y')}"
    if str(getattr(mode, "value", mode)) == ResearchMode.LIVE.value:
        return ResearchRetrievalOut(
            method="live_web_search",
            label="Live web search",
            retrieved_at=retrieved_at,
            note=f"Found by a web search on {day}. ADAPT kept only pages the search returned.",
        )
    return ResearchRetrievalOut(
        method="curated_snapshot",
        label="ADAPT reviewed source list",
        retrieved_at=retrieved_at,
        note=f"Curated snapshot: a person checked this page on {day}. Not a live web search.",
    )


def result_out(
    result: ResearchResult,
    citations: Sequence[ResearchCitation],
    now: datetime,
    mode: ResearchMode | str | None = None,
) -> ResearchResultOut:
    event = None
    if result.event_starts_on or result.event_ends_on or result.event_timing:
        event = ResearchEventInfo(
            starts_on=result.event_starts_on,
            ends_on=result.event_ends_on,
            timing_note=result.event_timing,
        )
    return ResearchResultOut(
        id=result.id,
        job_id=result.job_id,
        category=result.category,
        title=result.title,
        summary=result.summary,
        relevance=result.relevance,
        fact_ids=list(result.fact_ids or []),
        evidence_kind=result.evidence_kind,
        source_label=result.source_label,
        source_url=result.source_url,
        source_title=result.source_title,
        source_domain=result.source_domain,
        retrieved_at=result.retrieved_at,
        needs_recheck=needs_recheck(result.retrieved_at, now),
        retrieval=retrieval_out(mode, result.retrieved_at),
        citations=[
            ResearchCitationOut(
                id=c.id,
                url=c.url,
                title=c.title,
                source_domain=c.source_domain,
                source_label=c.source_label,
                retrieved_at=c.retrieved_at,
                summary=c.summary,
                category=c.category,
                is_primary=c.is_primary,
            )
            for c in citations
        ],
        contacts=[ResearchContactOut.model_validate(c) for c in result.contacts or []],
        event=event,
        saved=result.saved_at is not None,
        journey_node_id=result.journey_node_id,
        created_at=result.created_at,
    )


def discover_out(
    job: ResearchJobOut | None,
    results: Sequence[ResearchResultOut],
    saved: Sequence[ResearchResultOut],
) -> DiscoverOut:
    states = {s.category: s for s in job.categories} if job else {}
    sections: list[DiscoverSectionOut] = []
    for section, title, category in DISCOVER_SECTIONS:
        state = states.get(category)
        sections.append(
            DiscoverSectionOut(
                section=section,
                title=title,
                category=category,
                status=state.status if state else CategoryStatus.PENDING,
                reason=state.reason if state else None,
                results=[r for r in results if r.category is category],
            )
        )
    ready = bool(job and job.brief_ready and job.seen_at is None)
    return DiscoverOut(
        job=job,
        sections=sections,
        saved=list(saved),
        message=BRIEF_READY_MESSAGE if ready else None,
    )
