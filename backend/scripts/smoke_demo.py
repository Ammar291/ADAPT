"""End-to-end smoke test of the demo journey against a running ADAPT stack.

    uv run python scripts/smoke_demo.py                       # Docker stack (http://127.0.0.1:8080/api)
    uv run python scripts/smoke_demo.py --base http://127.0.0.1:8100/api

It signs in as a fresh private demo user and drives the API the way the app does: an Indian
founder moving to Abu Dhabi with his wife to start a company uploads a passport and a
marriage certificate, the journey agent plans (pausing at its human gates), research runs in
the background, and the assistant triggers the same workflows. Each demo step prints PASS or
FAIL; the exit code is the number of failures. Needs no OpenAI key (demo adapters).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

DOCUMENTS = Path(__file__).resolve().parents[2] / "demo-documents"
PROMPT = (
    "I'm an Indian founder moving to Abu Dhabi to start a tech startup. "
    "My wife is relocating with me."
)


class Smoke:
    def __init__(self, base: str) -> None:
        self.api = httpx.Client(base_url=base, timeout=30)
        self.failures = 0
        self.ctx: dict[str, Any] = {}

    def step(self, number: int, title: str, check: Callable[[], str]) -> None:
        try:
            detail = check()
            print(f"PASS {number:>2}. {title}: {detail}")
        except Exception as exc:  # report and carry on with the remaining steps
            self.failures += 1
            print(f"FAIL {number:>2}. {title}: {type(exc).__name__}: {exc}")

    def ok(self, response: httpx.Response, *codes: int) -> Any:
        if response.status_code not in (codes or (200,)):
            raise AssertionError(
                f"{response.request.method} {response.url.path} -> "
                f"{response.status_code} {response.text[:300]}"
            )
        return response.json() if response.content else None

    def wait(self, what: str, probe: Callable[[], Any], timeout: float = 120) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (result := probe()) is not None:
                return result
            time.sleep(1)
        raise TimeoutError(f"waited {timeout:.0f} s for {what}")

    def run_events(self, run_id: str) -> list[dict[str, Any]]:
        return self.ok(self.api.get(f"/agents/{run_id}/events"))["events"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8080/api")
    s = Smoke(parser.parse_args().base)
    api, ok, ctx = s.api, s.ok, s.ctx

    def onboarding() -> str:
        user = ok(api.post("/auth/demo-session", json={}))["user"]
        ok(
            api.patch(
                "/me/preferences",
                json={
                    "community_personalization": "granted",
                    "faith_personalization": "declined",
                },
            )
        )
        ok(
            api.post(
                "/onboarding/profile",
                json={
                    "profile": {
                        "persona": "founder",
                        "languages": ["en", "hi"],
                        "target_city": "Abu Dhabi",
                    },
                    "household": [
                        {
                            "relationship": "spouse",
                            "name": "My wife",
                            "relocation_plan": "with_user",
                            "needs_sponsorship": True,
                        }
                    ],
                    "goals": [
                        {"goal_type": "establish_company", "priority": "high"},
                        {"goal_type": "residency"},
                        {"goal_type": "find_housing"},
                        {"goal_type": "sponsor_family", "priority": "high"},
                    ],
                },
            )
        )
        return f"demo user {user['id'][:8]}, profile saved"

    def upload() -> str:
        ids = []
        for name, kind in (
            ("passport-arjun-mehta.pdf", "passport"),
            ("marriage-certificate.pdf", "marriage_certificate"),
        ):
            data = (DOCUMENTS / name).read_bytes()
            doc = ok(
                api.post(
                    "/documents/upload",
                    files={"file": (name, data, "application/pdf")},
                    data={"kind": kind},
                ),
                202,
            )
            ids.append(doc["id"])
        ctx["documents"] = ids
        return f"{len(ids)} documents uploaded"

    def intelligence() -> str:
        def settled() -> list[dict[str, Any]] | None:
            docs = ok(api.get("/documents"))
            busy = [d for d in docs if d["status"] in ("uploaded", "processing")]
            return None if busy else docs

        docs = s.wait("documents to be read", settled)
        passport = ok(api.get(f"/documents/{ctx['documents'][0]}"))
        assert passport["mrz_verified"] is True, "passport MRZ not verified"
        return ", ".join(f"{d['kind']}={d['status']}" for d in docs)

    def user_graph() -> str:
        graph = ok(api.get("/graph/user"))
        types = {n.get("type") for n in graph["nodes"]}
        assert {"person", "passport"} <= types, f"twin is missing nodes: {sorted(map(str, types))}"
        return f"{len(graph['nodes'])} private nodes ({', '.join(sorted(map(str, types)))[:80]})"

    def governance() -> str:
        graph = ok(api.get("/graph/governance", params={"q": "family residence visa"}))
        assert graph["nodes"], "no governance nodes"
        return f"{len(graph['nodes'])} nodes for 'family residence visa'"

    def rag() -> str:
        hits = ok(
            api.get("/knowledge/search", params={"q": "sponsor spouse residence visa", "k": 3})
        )
        first = hits["results"][0]
        assert first["source_url"].startswith("https://"), "evidence without an official URL"
        ctx["evidence_url"] = first["source_url"]
        return f"{len(hits['results'])} passages, first from {first['source_url'][:60]}"

    def start() -> str:
        started = ok(
            api.post(
                "/journey",
                json={"prompt": PROMPT, "language": "en", "document_ids": ctx["documents"]},
            ),
            202,
        )
        ctx["journey"], ctx["run"] = started["journey_id"], started["run"]["id"]
        listed = ok(api.get("/agents/runs", params={"active": "true"}))
        assert ctx["run"] in {r["id"] for r in listed}, "the run isn't listed by the server"
        return f"run {ctx['run'][:8]} queued and listed server-side"

    def progress() -> str:
        def paused() -> str | None:
            run = ok(api.get(f"/agents/{ctx['run']}"))
            assert run["status"] not in ("failed", "cancelled"), run.get("error")
            return run["status"] if run["status"] == "awaiting_input" else None

        s.wait("the first human gate", paused)
        names = {e["event"] for e in s.run_events(ctx["run"])}
        assert {"run_started", "node_started", "node_completed", "tool_called"} <= names
        return f"{len(s.run_events(ctx['run']))} events streamed before the first gate"

    def gates() -> str:
        answered = []
        for _ in range(6):
            run = s.wait(
                "the run to pause or finish",
                lambda: (
                    r
                    if (r := ok(api.get(f"/agents/{ctx['run']}")))["status"]
                    in ("awaiting_input", "succeeded", "failed")
                    else None
                ),
            )
            if run["status"] != "awaiting_input":
                break
            review = ok(api.get(f"/agents/{ctx['run']}/review"))
            gate = review["gate"]
            if gate == "document_correction":
                ok(
                    api.post(
                        f"/agents/{ctx['run']}/resume",
                        json={
                            "gate": gate,
                            "review_id": review["review_id"],
                            "documents": [
                                {
                                    "document_id": i["document_id"],
                                    "corrections": [],
                                    "confirm": True,
                                }
                                for i in review["items"]
                            ],
                        },
                    ),
                    202,
                )
            elif gate == "action_approval":
                ctx["approval_titles"] = [i["title"] for i in review["items"]]
                for item in review["items"]:
                    assert item["approval_status"] == "pending"
                    ok(api.post(f"/actions/{item['action_id']}/approve", json={}))
                again = ok(api.get(f"/agents/{ctx['run']}/review"), 200, 404)
                assert (
                    not again
                    or again.get("gate") != "action_approval"
                    or all(i["approval_status"] != "pending" for i in again["items"])
                )
            else:
                ok(
                    api.post(
                        f"/agents/{ctx['run']}/resume",
                        json={
                            "gate": gate,
                            "review_id": review["review_id"],
                            "confirmations": [
                                {"action_id": i["action_id"], "outcome": "not_yet"}
                                for i in review["items"]
                            ],
                        },
                    ),
                    202,
                )
            answered.append(gate)
            time.sleep(1)
        run = s.wait(
            "the plan to finish",
            lambda: (
                r
                if (r := ok(api.get(f"/agents/{ctx['run']}")))["status"] in ("succeeded", "failed")
                else None
            ),
        )
        assert run["status"] == "succeeded", run.get("error")
        events = s.run_events(ctx["run"])
        opened = {e["approval_id"] for e in events if e["event"] == "approval_required"}
        closed = {e["approval_id"] for e in events if e["event"] == "approval_resolved"}
        assert opened <= closed, "a gate opened on the stream was never closed"
        assert "action_approval" in answered, "no approval gate"
        return " -> ".join(answered) + " -> succeeded"

    def journey() -> str:
        j = ok(api.get(f"/journey/{ctx['journey']}"))
        ctx["detail"] = j
        assert j["status"] == "active" and j["nodes"] and j["edges"]
        return f"{len(j['nodes'])} steps, {len(j['edges'])} dependencies"

    def risks() -> str:
        risks = ctx["detail"]["risks"]
        assert risks, "no risks"
        return f"{len(risks)} risks, e.g. '{risks[0]['title'][:60]}'"

    def generated() -> str:
        docs = ok(api.get("/documents/generated"))
        assert docs, "no generated documents"
        return ", ".join(d["title"] for d in docs)[:100]

    def actions() -> str:
        acts = ctx["detail"]["actions"]
        assert acts, "no actions prepared"
        return f"{len(acts)} actions ({', '.join(sorted({a['status'] for a in acts}))})"

    def approval_gate() -> str:
        titles = ctx.get("approval_titles")
        assert titles, "no approval gate was raised"
        return f"approved by tap: {', '.join(titles)}"

    def research_started() -> str:
        jobs = ok(api.get("/research", params={"limit": 1}))
        assert jobs, "the journey didn't start research"
        ctx["research"] = jobs[0]["id"]
        return f"job {jobs[0]['id'][:8]} ({jobs[0]['mode']})"

    def discover() -> str:
        s.wait(
            "research to finish",
            lambda: (
                True
                if ok(api.get(f"/research/{ctx['research']}"))["job"]["status"]
                in ("succeeded", "failed")
                else None
            ),
        )
        sections = ok(api.get("/discover"))["sections"]
        counts = {
            sec.get("key") or sec.get("category"): len(sec.get("results") or sec.get("items") or [])
            for sec in sections
        }
        assert sum(counts.values()) > 0, "Discover is empty"
        return ", ".join(f"{k}={v}" for k, v in counts.items())

    def evidence() -> str:
        node = next(n for n in ctx["detail"]["nodes"] if n.get("official_url"))
        assert ctx["detail"]["evidence"], "no evidence on the journey"
        return f"'{node['title']}' -> {node['official_url'][:70]}"

    def what_if() -> str:
        started = ok(
            api.post(
                f"/journey/{ctx['journey']}/simulate",
                json={"changes": [{"key": "company.jurisdiction", "value": "adgm"}]},
            ),
            202,
        )
        scenario = s.wait(
            "the what-if",
            lambda: (
                j
                if (j := ok(api.get(f"/journey/{started['scenario_journey_id']}"))).get(
                    "simulation_result"
                )
                else None
            ),
        )
        base = ok(api.get(f"/journey/{ctx['journey']}"))
        assert len(base["nodes"]) == len(ctx["detail"]["nodes"]), "the base plan changed"
        return scenario["simulation_result"]["summary"][:110]

    def voice() -> str:
        replies = []
        for text in (
            "What's next in my plan?",
            "What if my wife joins later?",
            "Is my research ready?",
        ):
            out = ok(
                api.post("/voice/assistant", json={"messages": [{"role": "user", "text": text}]})
            )
            tools = [r["name"] for r in out["tool_results"]]
            assert tools, f"no tool for {text!r}"
            replies.append(f"{tools[0]}")
        return " | ".join(replies)

    s.step(1, "New user lands on onboarding (demo session, profile)", onboarding)
    s.step(
        2,
        "Indian founder, Abu Dhabi, wife relocating, startup",
        lambda: "in the profile and prompt",
    )
    s.step(3, "Upload passport and marriage certificate", upload)
    s.step(4, "Document intelligence processes them", intelligence)
    s.step(5, "Private user graph updates", user_graph)
    s.step(6, "Governance graph is queried", governance)
    s.step(7, "RAG returns evidence", rag)
    s.step(8, "LangGraph journey starts", start)
    s.step(9, "Agent progress streams", progress)
    s.step(14, "Human gates (documents, approval, confirmation)", gates)
    s.step(10, "Journey graph is created", journey)
    s.step(11, "Risks and blockers", risks)
    s.step(12, "Generated documents", generated)
    s.step(13, "Action preparation", actions)
    s.step(14, "Human approval gate", approval_gate)
    s.step(15, "Async research starts", research_started)
    s.step(16, "Discover results when research completes", discover)
    s.step(17, "Evidence opens to an official source", evidence)
    s.step(18, "What-if simulation (ADGM instead)", what_if)
    s.step(19, "Assistant triggers the same workflows", voice)
    print(f"\n{'ALL PASSED' if not s.failures else f'{s.failures} FAILED'}")
    return s.failures


if __name__ == "__main__":
    sys.exit(main())
