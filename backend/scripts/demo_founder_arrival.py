"""Rehearse the "Founder Arrival" demo against a running ADAPT stack, headlessly.

    uv run python scripts/demo_founder_arrival.py                    # Docker (http://127.0.0.1:8080/api)
    uv run python scripts/demo_founder_arrival.py --base http://127.0.0.1:8100/api
    uv run python scripts/demo_founder_arrival.py --twice            # two fresh runs must match

It runs the same script as the presenter page (`/demo/founder-arrival`), read from
`GET /api/demo/scenarios/founder-arrival`, through the public API on a fresh private account:
profile, three synthetic documents (each awaited and confirmed), the deterministic journey,
research on the curated snapshot, the "Move alone first" what-if and the action cards. Each
act prints PASS or FAIL, then a fingerprint of everything the audience sees. With `--twice`
the fingerprints of two fresh runs are compared. Needs no OpenAI key. See
docs/demo-founder-arrival.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

ACT_TIMEOUT = 180.0
EXTRACTION_STAGES = ["classify", "extract", "validate", "structure", "update_twin"]


def action_labels(action: dict[str, Any]) -> list[str]:
    """The card vocabulary the presenter page uses. There is no 'submitted' label: an
    action only gets past a handoff with the person's confirmation or a real reference."""
    labels = []
    if action["status"] == "prepared":
        labels.append("Prepared")
    approval = (action.get("approval") or {}).get("status")
    if action["requires_human_approval"] and (
        action["status"] == "awaiting_approval" or approval == "pending"
    ):
        labels.append("Approval required")
    if action["type"] == "official_handoff" or action["status"] == "handoff_required":
        labels.append("Official handoff")
    if action["is_simulated"]:
        labels.append("Demo adapter")
    return labels


class Rehearsal:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        origin = urlsplit(self.base)
        self.origin = f"{origin.scheme}://{origin.netloc}"
        self.api = httpx.Client(base_url=self.base, timeout=30)
        self.failures = 0
        self.print = True
        self.fingerprint: dict[str, Any] = {}

    def act(self, title: str, run: Callable[[], str]) -> None:
        try:
            detail = run()
            print(f"PASS  {title}: {detail}")
        except Exception as exc:
            self.failures += 1
            print(f"FAIL  {title}: {type(exc).__name__}: {exc}")
            raise

    def ok(self, response: httpx.Response, *codes: int) -> Any:
        if response.status_code not in (codes or (200,)):
            raise AssertionError(
                f"{response.request.method} {response.url.path} -> "
                f"{response.status_code} {response.text[:300]}"
            )
        return response.json() if response.content else None

    def wait(self, what: str, probe: Callable[[], Any], timeout: float = ACT_TIMEOUT) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (result := probe()) is not None:
                return result
            time.sleep(0.75)
        raise TimeoutError(f"waited {timeout:.0f} s for {what}")

    # ------------------------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        api, ok, fp = self.api, self.ok, self.fingerprint
        ctx: dict[str, Any] = {}

        def fresh() -> str:
            user = ok(api.post("/auth/demo-session", json={}), 200, 201)["user"]
            ctx["scenario"] = ok(api.get("/demo/scenarios/founder-arrival"))
            return f"new private account {user['id'][:8]}…, scenario '{ctx['scenario']['title']}'"

        def profile() -> str:
            ok(api.post("/onboarding/profile", json=ctx["scenario"]["onboarding"]), 200, 201)
            me = ok(api.get("/me"))
            prefs = me["preferences"]
            assert prefs["faith_personalization"] == "granted", prefs
            assert prefs["community_personalization"] == "granted", prefs
            return "goals, spouse, languages en+hi, Indian and Muslim community opt-ins"

        def documents() -> str:
            ctx["document_ids"] = []
            lines = []
            graph_before = len(ok(api.get("/graph/user"))["nodes"])
            for doc in ctx["scenario"]["documents"]:
                pdf = httpx.get(self.origin + doc["url"], timeout=30)
                assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF"), doc["url"]
                uploaded = ok(
                    api.post(
                        "/documents/upload",
                        files={"file": (doc["filename"], pdf.content, "application/pdf")},
                        data={"kind": doc["kind"]},
                    ),
                    202,
                )
                ctx["document_ids"].append(uploaded["id"])
                settled = self.wait(
                    f"{doc['key']} to be read",
                    lambda u=uploaded: (
                        d
                        if (d := ok(api.get(f"/documents/{u['id']}")))["status"]
                        not in ("uploaded", "processing")
                        else None
                    ),
                )
                assert settled["status"] == "extracted", (doc["key"], settled["status"])
                events = ok(api.get(f"/agents/{uploaded['extraction_run_id']}/events"))["events"]
                done = [e["node"] for e in events if e["event"] == "node_completed"]
                assert done == EXTRACTION_STAGES, (doc["key"], done)
                fields = {f["name"]: f for f in settled.get("fields", [])}
                assert all(f["value"] is not None for f in fields.values()), (doc["key"], fields)
                if doc["key"] == "business_profile":
                    assert len(fields["activities"]["value"]) == 2, fields["activities"]
                if doc["key"] == "marriage_certificate":
                    assert fields["country_of_marriage"]["value"] == "IND", fields
                    assert fields["home_attested"]["value"] is True, fields
                    assert fields["attested"]["value"] is False, fields
                review = ok(api.post(f"/documents/{uploaded['id']}/review", json={"confirm": True}))
                assert review["status"] == "confirmed", review["status"]
                fp.setdefault("documents", {})[doc["key"]] = {
                    "method": settled.get("extraction_method"),
                    "mrz_verified": settled.get("mrz_verified"),
                    "fields": sorted(fields),
                }
                lines.append(f"{doc['key']} {len(fields)} fields ({settled['extraction_method']})")
            graph = ok(api.get("/graph/user"))
            fp["user_graph_types"] = sorted({n["type"] for n in graph["nodes"]})
            return "; ".join(lines) + f"; twin {graph_before} -> {len(graph['nodes'])} nodes"

        def plan() -> str:
            body = {**ctx["scenario"]["journey"], "document_ids": ctx["document_ids"]}
            started = ok(api.post("/journey", json=body), 202)
            ctx["journey"], run_id = started["journey_id"], started["run"]["id"]
            run = self.wait(
                "the plan",
                lambda: (
                    r
                    if (r := ok(api.get(f"/agents/{run_id}")))["status"]
                    in ("awaiting_input", "succeeded", "failed")
                    else None
                ),
            )
            assert run["status"] != "failed", run
            if run["status"] == "awaiting_input":
                gate = ok(api.get(f"/agents/{run_id}/review"))["gate"]
                assert gate == "action_approval", f"unexpected gate {gate}"
            detail = ok(api.get(f"/journey/{ctx['journey']}"))
            ctx["detail"] = detail
            nodes = {n["key"]: n for n in detail["nodes"]}
            for role in ctx["scenario"]["roles"]:
                assert role["task_key"] in nodes, role
            family = nodes["service.family_residence_visa@spouse"]
            missing = [b for b in family["blockers"] if b["kind"] == "missing_info"]
            assert missing, family["blockers"]
            cited = [k for k in nodes if nodes[k]["provenance"].get("citations")]
            key_of = {n["id"]: n["key"] for n in detail["nodes"]}
            fp["plan"] = {
                "nodes": sorted(nodes),
                "edges": sorted(
                    f"{key_of[e['source_node_id']]}<-{key_of[e['target_node_id']]}"
                    for e in detail["edges"]
                ),
                "blockers": {
                    k: sorted({b["kind"] for b in n["blockers"]})
                    for k, n in sorted(nodes.items())
                    if n["blockers"]
                },
                "status": {k: n["status"] for k, n in sorted(nodes.items())},
            }
            return (
                f"{len(nodes)} steps, {len(detail['edges'])} dependencies, "
                f"{len(cited)} with official citations; missing information: "
                f"{missing[0]['message']}"
            )

        def considerations() -> str:
            found = ctx["detail"]["considerations"]
            assert len(found) == 2, [c["id"] for c in found]
            assert all(c["evidence_ids"] for c in found)
            fp["considerations"] = [c["id"] for c in found]
            return " | ".join(c["title"] for c in found)

        def research() -> str:
            body = {**ctx["scenario"]["research"], "journey_id": ctx["journey"]}
            job = ok(api.post("/research", json=body), 202)["job"]
            assert job["mode"] == "snapshot", job["mode"]
            done = self.wait(
                "research",
                lambda: (
                    d
                    if (d := ok(api.get(f"/research/{job['id']}")))["job"]["status"]
                    in ("succeeded", "failed")
                    else None
                ),
            )
            assert done["job"]["status"] == "succeeded", done["job"]
            by_category: dict[str, list[dict[str, Any]]] = {}
            for result in done["results"]:
                by_category.setdefault(result["category"], []).append(result)
            groups = {}
            for group in ctx["scenario"]["research_groups"]:
                results = [r for c in group["categories"] for r in by_category.get(c, [])]
                assert results, f"no results for {group['title']}"
                for r in results:
                    assert r["source_url"].startswith("https://"), r
                    assert r["retrieval"]["method"] == "curated_snapshot", r["retrieval"]
                groups[group["key"]] = [r["source_url"] for r in results]
            fp["research"] = groups
            return ", ".join(f"{k} {len(v)}" for k, v in groups.items())

        def what_if() -> str:
            changes = ctx["scenario"]["what_if"]["changes"]
            started = ok(
                api.post(f"/journey/{ctx['journey']}/simulate", json={"changes": changes}), 202
            )
            scenario = self.wait(
                "the what-if",
                lambda: (
                    j
                    if (j := ok(api.get(f"/journey/{started['scenario_journey_id']}"))).get(
                        "simulation_result"
                    )
                    else None
                ),
            )
            result = scenario["simulation_result"]
            base = ok(api.get(f"/journey/{ctx['journey']}"))
            assert len(base["nodes"]) == len(ctx["detail"]["nodes"]), "the base plan changed"
            assert result["removed_tasks"] and result["changed_dependencies"], result
            fp["what_if"] = {
                "removed": sorted(t["key"] for t in result["removed_tasks"]),
                "added": sorted(t["key"] for t in result["added_tasks"]),
                "dependencies": sorted(
                    f"{d['change']}:{d['source']}<-{d['target']}"
                    for d in result["changed_dependencies"]
                ),
                "considerations": [c["id"] for c in scenario["considerations"]],
            }
            return result["summary"][:140]

        def actions() -> str:
            items = ok(api.get("/actions"))
            assert items, "no actions"
            assert not any(a["status"] in ("submitted", "completed") for a in items)
            labels = {label for a in items for label in action_labels(a)}
            wanted = {"Prepared", "Approval required", "Official handoff", "Demo adapter"}
            assert wanted <= labels, f"missing labels: {wanted - labels}"
            fp["actions"] = sorted(
                f"{a['task_key']}:{a['type']}:{a['status']}:{'+'.join(action_labels(a))}"
                for a in items
            )
            return "; ".join(f"{a['title']} [{', '.join(action_labels(a))}]" for a in items)

        for title, step in (
            ("0. Fresh start", fresh),
            ("1. Meet the founder", profile),
            ("2. Documents: uploaded > analyzed > facts > twin, confirmed", documents),
            ("3. Settlement graph", plan),
            ("4. Things you may not have considered", considerations),
            ("5. Background research", research),
            ("6. What if: move alone first", what_if),
            ("7. Action cards", actions),
        ):
            self.act(title, step)
        return fp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8080/api")
    parser.add_argument("--twice", action="store_true", help="run twice and compare")
    parser.add_argument("--json", help="write the fingerprint to this file")
    args = parser.parse_args()

    runs = 2 if args.twice else 1
    prints = []
    for index in range(runs):
        print(f"\n=== Founder Arrival rehearsal {index + 1}/{runs} ===")
        rehearsal = Rehearsal(args.base)
        try:
            prints.append(rehearsal.run())
        except Exception:
            print("\nSTOPPED: fix the failing act, then rehearse again.")
            return 1
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(prints[-1], fh, indent=2, sort_keys=True)
    if runs == 2:
        same = json.dumps(prints[0], sort_keys=True) == json.dumps(prints[1], sort_keys=True)
        if not same:
            for key in sorted(set(prints[0]) | set(prints[1])):
                if prints[0].get(key) != prints[1].get(key):
                    print(f"DIFFERS  {key}")
            print("\nNOT DETERMINISTIC: the two runs differ (see above).")
            return 1
        print("\nDETERMINISTIC: both fresh runs produced the same fingerprint.")
    print("\nREADY FOR THE STAGE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
