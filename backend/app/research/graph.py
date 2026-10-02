"""The research LangGraph: prepare -> one node per category (in parallel) -> compile brief.

    START -> prepare_research -> research_<category> x N (parallel) -> compile_brief -> END

* A category that fails is reported (`research_category_completed`, status failed) and
  the others carry on. The run only fails when every attempted category failed.
* `research_failed` is always emitted before the run's terminal `run_failed`, so the
  browser sees why before the stream closes.
* Each kept source is announced once per job (`research_source_found`), even when several
  categories cite it.

Graph state is JSON-only; results live in Postgres and state holds only counts.
"""

from __future__ import annotations

import asyncio
import logging
import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.agents.instrumentation import instrumented, report
from app.core.errors import AppError, UpstreamError
from app.research import repository
from app.research.contracts import BRIEF_READY_MESSAGE
from app.research.engines import ResearchEngine
from app.research.processing import SourceProcessor
from app.research.profile import ResearchProfile
from app.research.types import ALL_CATEGORIES, CategoryStatus, ResearchCategory

logger = logging.getLogger(__name__)

CATEGORY_TIMEOUT_SECONDS = 240.0

NODE_LABELS: dict[ResearchCategory, str] = {
    ResearchCategory.COMMUNITY: "Find your communities",
    ResearchCategory.FAITH_AND_WORSHIP: "Find faith communities and places",
    ResearchCategory.PROFESSIONAL_NETWORK: "Find professional networks",
    ResearchCategory.EVENTS: "Find local events",
    ResearchCategory.CULTURE: "Build your cultural guide",
    ResearchCategory.LIFESTYLE: "Find what may surprise you",
    ResearchCategory.STARTER_KIT: "Put together your starter kit",
}


def node_id(category: ResearchCategory) -> str:
    return f"research_{category.value}"


@dataclass(frozen=True, slots=True)
class ResearchContext(AgentContext):
    """Run context plus research-only live objects (never checkpointed)."""

    job_id: UUID
    engine: ResearchEngine
    processor: SourceProcessor
    profile: ResearchProfile
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    category_timeout: float = CATEGORY_TIMEOUT_SECONDS
    announced: set[str] = field(default_factory=set)
    announce_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ResearchState(TypedDict, total=False):
    job_id: str
    active: list[str]
    skipped: list[dict[str, str]]
    outcomes: Annotated[list[dict[str, Any]], operator.add]
    summary: str


def _ctx(runtime: Runtime[AgentContext]) -> ResearchContext:
    ctx = runtime.context
    assert isinstance(ctx, ResearchContext)
    return ctx


async def _fail(ctx: ResearchContext, code: str, message: str, retryable: bool) -> None:
    await ctx.events.emit(
        "research_failed",
        {"job_id": str(ctx.job_id), "code": code, "message": message, "retryable": retryable},
    )


@instrumented("prepare_research", "Plan the research")
async def prepare_research(state: ResearchState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = _ctx(runtime)
    try:
        active = [ResearchCategory(c) for c in state.get("active", [])]
        skipped = state.get("skipped", [])
        await ctx.events.emit(
            "research_started",
            {
                "job_id": str(ctx.job_id),
                "categories": [c.value for c in active] + [s["category"] for s in skipped],
                "mode": ctx.engine.mode.value,
            },
        )
        for item in skipped:
            await ctx.events.emit(
                "research_category_completed",
                {
                    "job_id": str(ctx.job_id),
                    "category": item["category"],
                    "status": CategoryStatus.SKIPPED.value,
                    "result_count": 0,
                    "reason": item.get("reason"),
                },
            )
        basis = ctx.profile.basis()
        await report(
            runtime,
            f"Researching {len(active)} topics"
            + (f", personalised with {len(basis)} things you told us" if basis else ""),
            1.0,
        )
    except Exception as exc:
        await _fail(ctx, "research_error", "Research couldn't start", True)
        raise UpstreamError("Research couldn't start") from exc
    return {"_summary": f"{len(active)} topics", "active": [c.value for c in active]}


def _category_node(category: ResearchCategory) -> Callable[..., Any]:
    @instrumented(node_id(category), NODE_LABELS[category])
    async def research_category(
        state: ResearchState, runtime: Runtime[AgentContext]
    ) -> dict[str, Any]:
        ctx = _ctx(runtime)
        job = str(ctx.job_id)
        async with ctx.db.user_session(ctx.principal) as session:
            await repository.set_category_status(
                session, ctx.job_id, category, CategoryStatus.RUNNING
            )
            await session.commit()

        async def progress(message: str, fraction: float | None) -> None:
            await report(runtime, message, fraction)

        try:
            async with asyncio.timeout(ctx.category_timeout):
                findings = await ctx.engine.research(
                    category, ctx.profile, today=ctx.clock().date(), progress=progress
                )
                processed = await ctx.processor.process(findings, ctx.profile, ctx.clock())
            async with ctx.db.user_session(ctx.principal) as session:
                saved = await repository.save_results(session, ctx.principal, ctx.job_id, processed)
                await repository.set_category_status(
                    session,
                    ctx.job_id,
                    category,
                    CategoryStatus.COMPLETED,
                    result_count=len(saved),
                )
                await session.commit()
        except Exception as exc:
            code = (
                exc.code
                if isinstance(exc, AppError)
                else ("research_timeout" if isinstance(exc, TimeoutError) else "research_error")
            )
            logger.warning(
                "research_category_failed",
                extra={"category": category.value, "code": code, "error": type(exc).__name__},
            )
            async with ctx.db.user_session(ctx.principal) as session:
                await repository.set_category_status(
                    session, ctx.job_id, category, CategoryStatus.FAILED, reason=code
                )
                await session.commit()
            await ctx.events.emit(
                "research_category_completed",
                {
                    "job_id": job,
                    "category": category.value,
                    "status": CategoryStatus.FAILED.value,
                    "result_count": 0,
                    "reason": code,
                },
                node=node_id(category),
            )
            return {
                "outcomes": [{"category": category.value, "status": "failed", "count": 0}],
                "_summary": "Couldn't complete this topic",
            }

        for result, citations in saved:
            for citation in citations:
                async with ctx.announce_lock:
                    if citation.canonical_url in ctx.announced:
                        continue
                    ctx.announced.add(citation.canonical_url)
                await ctx.events.emit(
                    "research_source_found",
                    {
                        "job_id": job,
                        "category": category.value,
                        "result_id": str(result.id),
                        "citation_id": str(citation.id),
                        "title": citation.title,
                        "url": citation.url,
                        "source_domain": citation.source_domain,
                        "source_label": citation.source_label.value,
                    },
                    node=node_id(category),
                )
        await ctx.events.emit(
            "research_category_completed",
            {
                "job_id": job,
                "category": category.value,
                "status": CategoryStatus.COMPLETED.value,
                "result_count": len(saved),
                "reason": None,
            },
            node=node_id(category),
        )
        return {
            "outcomes": [{"category": category.value, "status": "completed", "count": len(saved)}],
            "_summary": f"{len(saved)} found",
        }

    research_category.__name__ = node_id(category)
    return research_category


@instrumented("compile_brief", "Put together your Life Brief")
async def compile_brief(state: ResearchState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    ctx = _ctx(runtime)
    outcomes = state.get("outcomes", [])
    completed = [o for o in outcomes if o["status"] == "completed"]
    failed = [o for o in outcomes if o["status"] == "failed"]
    if failed and not completed:
        await _fail(ctx, "research_unavailable", "Research couldn't be completed right now", True)
        raise UpstreamError("Research couldn't be completed right now", code="research_unavailable")
    total = sum(o["count"] for o in completed)
    async with ctx.db.user_session(ctx.principal) as session:
        await repository.mark_completed(session, ctx.job_id)
        await session.commit()
    await ctx.events.emit(
        "research_completed",
        {
            "job_id": str(ctx.job_id),
            "result_count": total,
            "categories_completed": [o["category"] for o in completed],
            "categories_failed": [o["category"] for o in failed],
            "message": BRIEF_READY_MESSAGE,
        },
    )
    return {"summary": BRIEF_READY_MESSAGE, "_summary": f"{total} results"}


def _route(state: ResearchState) -> list[str]:
    active = [node_id(ResearchCategory(c)) for c in state.get("active", [])]
    return active or ["compile_brief"]


def build_research_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph[ResearchState, AgentContext, ResearchState, ResearchState]:
    graph = StateGraph(ResearchState, context_schema=AgentContext)
    # `instrumented` returns a plain callable; LangGraph injects `runtime` by signature.
    graph.add_node("prepare_research", prepare_research)  # type: ignore[call-overload]
    graph.add_node("compile_brief", compile_brief)  # type: ignore[call-overload]
    for category in ALL_CATEGORIES:
        graph.add_node(node_id(category), _category_node(category))
        graph.add_edge(node_id(category), "compile_brief")
    graph.add_edge(START, "prepare_research")
    graph.add_conditional_edges(
        "prepare_research",
        _route,
        [*(node_id(c) for c in ALL_CATEGORIES), "compile_brief"],
    )
    graph.add_edge("compile_brief", END)
    return graph.compile(checkpointer=checkpointer)
