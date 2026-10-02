"""Build the public, synthetic stage replay using the real LangGraph and local reader.

No credentials, database, external submissions or web requests. The in-memory ports are
the same harness used by the graph regression tests. This is explicitly a replay, not
a claim that the browser executes LangGraph or that source pages were checked today.
Run from backend: .venv/Scripts/python scripts/build_demo_replay.py
"""

# ruff: noqa: E402 -- this executable script adds the repository/test-harness import roots.
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/tests/unit"))

from journey.fakes import approve_all, harness
from journey.test_seed_compat import real_snapshot
from test_demo_founder_arrival import PROFILE, SCENARIO_FACTS, read

from app.agents.journey.considerations import detect_considerations
from app.agents.journey.drafting import draft
from app.agents.journey.facts import fact
from app.agents.journey.simulation import build_simulation_graph, run_simulation
from app.agents.journey.tools import GenerateDocumentInput
from app.demo_scenarios import founder_arrival
from app.demo_scenarios.documents import DOCUMENTS, PERSONA
from app.research.snapshot import load_catalogue, select_entries
from app.research.types import ResearchCategory

PROMPT = (
    "I'm an Indian technology founder moving to Abu Dhabi next month with my wife. "
    "I want to establish my company, find housing and understand the steps for settling my family."
)


async def build() -> None:
    governance = real_snapshot()
    facts = [
        fact(k, v, "document_extracted", fact_ids=[f"specimen:{k}"])
        for k, v in SCENARIO_FACTS.items()
    ]
    facts += [
        fact(
            "profile.full_name",
            PERSONA.full_name,
            "document_extracted",
            source_ref="specimen:passport",
        ),
        fact(
            "spouse.full_name",
            PERSONA.spouse_name,
            "document_extracted",
            source_ref="specimen:marriage_certificate",
        ),
    ]
    h = harness(governance=governance, facts=facts)
    # Research is shown separately, from the dated source catalogue.
    h.research.available = False
    await h.start(text=PROMPT)
    state = await h.state()
    # Keep only one decision on stage: the appointment. Other pending decisions remain
    # explicit in the full replay; no denominator is silently overwritten.
    featured = next(a for a in state["actions"] if a["task_key"] == "appointment.uae_mission_visit")
    await h.resume(approve_all(h))
    if h.store.pending_reviews.get(str(h.run_id)):
        review = h.review
        await h.resume(
            {
                "gate": "submission_confirmation",
                "review_id": review["review_id"],
                "confirmations": [
                    {"action_id": i["action_id"], "outcome": "not_yet", "reference": None}
                    for i in review["items"]
                ],
            }
        )
    final = await h.state()
    brief, provenance = await draft(
        h.services.llm,
        GenerateDocumentInput(
            journey_id=h.journey_id,
            kind="appointment_brief",
            title="UAE mission visit: appointment brief",
            task_key=featured["task_key"],
            context={
                "official_url": featured["official_url"],
                "documents": [
                    "Marriage certificate (synthetic; home-country attested)",
                    "Passport (synthetic)",
                ],
            },
        ),
    )
    await h.store.save_generated_document(
        journey_id=h.journey_id,
        run_id=str(h.run_id),
        kind="appointment_brief",
        title="UAE mission visit: appointment brief",
        body_markdown=brief,
        task_key=featured["task_key"],
        provenance=provenance,
    )
    journey_events = [e.model_dump(mode="json") for e in h.sink.events]
    simulation = await run_simulation(
        journey_graph=h.graph,
        simulation_graph=build_simulation_graph(h.checkpointer),
        context=h.context,
        base_thread_id=h.thread_id,
        base_journey_id=h.journey_id,
        base_run_id=str(h.run_id),
        scenario_journey_id=str(uuid4()),
        thread_id=f"what_if:{uuid4()}",
        changes=[{"key": "household.move_with_spouse", "value": False}],
    )
    assert simulation.status == "completed", simulation
    branch = simulation.values
    docs = []
    public = ROOT / "frontend/public/demo-specimens"
    public.mkdir(exist_ok=True)
    for doc in DOCUMENTS:
        content = doc.build()
        (public / doc.filename).write_bytes(content)
        _, outcome = await read(doc.key)
        docs.append(
            {
                "key": doc.key,
                "title": doc.title,
                "filename": doc.filename,
                "sha256": hashlib.sha256(content).hexdigest(),
                "url": f"/demo-specimens/{doc.filename}",
                "fields": [
                    {
                        "name": name,
                        "value": field.value,
                        "confidence": field.confidence,
                        "method": field.method,
                    }
                    for name, field in outcome.fields.items()
                ],
            }
        )
    groups = []
    for group in founder_arrival.definition().research_groups:
        entries = []
        for category in group.categories:
            for match in select_entries(
                load_catalogue(), ResearchCategory(category), PROFILE, limit=3
            ):
                entry = match.entry
                entries.append(asdict(entry))
        groups.append(
            {
                "key": group.key,
                "title": group.title,
                "description": group.description,
                "entries": entries,
            }
        )
    output = {
        "version": 1,
        "prompt": PROMPT,
        "provenance": (
            "Recorded real LangGraph run; in-memory demo ports; local PDF text + MRZ; "
            "dated curated research. No live external execution."
        ),
        "scenario": founder_arrival.definition().model_dump(mode="json"),
        "documents": docs,
        "tasks": state["tasks"],
        "dependencies": state["dependencies"],
        "requirements": state["requirements"],
        "eligibility": state["eligibility"],
        "risks": state["risks"],
        "evidence": state["evidence"],
        "considerations": detect_considerations(state, governance.nodes),
        "actions": state["actions"],
        "featuredAction": featured,
        "drafts": list(h.store.documents.values()),
        "events": journey_events,
        "finalSummary": final["final_summary"],
        "branch": {"tasks": branch["tasks"], "dependencies": branch["dependencies"]},
        "research": groups,
        "governance": {"nodes": list(governance.nodes.values()), "edges": governance.edges},
    }
    destination = ROOT / "frontend/src/features/demo/replay.json"
    destination.write_text(
        json.dumps(output, default=str, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    actions = sum(bool(t.get("action_type")) for t in state["tasks"])
    approvals = sum(a["requires_human_approval"] for a in state["actions"])
    print(
        f"Saved synthetic replay: {len(state['tasks'])} steps, {actions} adapter actions, "
        f"{len(state['risks'])} risks, {approvals} full-plan approvals"
    )


if __name__ == "__main__":
    asyncio.run(build())
