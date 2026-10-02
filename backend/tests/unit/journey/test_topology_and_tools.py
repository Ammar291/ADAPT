"""Topology matches the compiled graphs; tools, intake and drafting behave as documented."""

from __future__ import annotations

import json
from itertools import pairwise

import pytest

from app.adapters.llm import DemoLLM
from app.agents.journey.demo import register_demo_responders
from app.agents.journey.drafting import checklist
from app.agents.journey.graph import build_journey_graph
from app.agents.journey.intake import facts_from_intake, parse_request
from app.agents.journey.simulation import build_simulation_graph
from app.agents.journey.tools import TOOL_SPECS, GenerateDocumentInput, tool_schemas
from app.agents.journey.topology import JOURNEY_TOPOLOGY, WHAT_IF_TOPOLOGY
from app.contracts.agents import AgentTopology

EXPECTED = [
    "intake",
    "profile_analysis",
    "document_analysis",
    "eligibility_analysis",
    "requirement_planner",
    "dependency_analysis",
    "risk_detection",
    "document_preparation",
    "action_preparation",
    "human_approval",
    "execution_or_handoff",
    "final_plan",
]


class TestTopology:
    def test_journey_topology_is_the_specified_workflow(self) -> None:
        assert [n.id for n in JOURNEY_TOPOLOGY.nodes] == EXPECTED
        chain = ["__start__", *EXPECTED, "__end__"]
        assert [(e.source, e.target) for e in JOURNEY_TOPOLOGY.edges] == list(pairwise(chain))

    def test_topology_matches_the_compiled_graphs(self) -> None:
        for topology, graph in (
            (JOURNEY_TOPOLOGY, build_journey_graph()),
            (WHAT_IF_TOPOLOGY, build_simulation_graph()),
        ):
            drawn = graph.get_graph()
            assert {n.id for n in topology.nodes} | {"__start__", "__end__"} == set(drawn.nodes)
            compiled = {(e.source, e.target) for e in drawn.edges}
            assert {(e.source, e.target) for e in topology.edges} == compiled

    def test_only_human_approval_leads_into_execution(self) -> None:
        into = {e.source for e in JOURNEY_TOPOLOGY.edges if e.target == "execution_or_handoff"}
        assert into == {"human_approval"}
        kinds = {n.id: n.kind for n in JOURNEY_TOPOLOGY.nodes}
        assert kinds["human_approval"] == "human"

    def test_what_if_branch_never_reaches_side_effects(self) -> None:
        ids = {n.id for n in WHAT_IF_TOPOLOGY.nodes}
        assert ids.isdisjoint({"human_approval", "execution_or_handoff", "final_plan", "intake"})
        assert WHAT_IF_TOPOLOGY.nodes[0].id == "apply_scenario"
        assert WHAT_IF_TOPOLOGY.nodes[-1].id == "compare_scenarios"

    def test_topologies_are_valid_contracts(self) -> None:
        for topology in (JOURNEY_TOPOLOGY, WHAT_IF_TOPOLOGY):
            AgentTopology.model_validate(json.loads(topology.model_dump_json()))


class TestTools:
    def test_all_tools_are_declared(self) -> None:
        assert set(TOOL_SPECS) == {
            "get_user_graph",
            "get_governance_graph",
            "retrieve_evidence",
            "analyze_document",
            "generate_document",
            "prepare_action",
            "prepare_appointment",
            "start_research",
            "simulate_journey",
        }

    def test_schemas_for_function_calling(self) -> None:
        for schema in tool_schemas():
            assert schema["description"] and schema["parameters"]["type"] == "object"
            json.dumps(schema)


class TestIntake:
    def test_founder_with_spouse(self) -> None:
        extraction = parse_request(
            "I'm a founder moving next month with my wife. I want to set up my company, "
            "find a home and sponsor her visa."
        )
        assert set(extraction.goals) == {
            "establish_company",
            "residency",
            "sponsor_family",
            "find_housing",
        }
        assert extraction.move_with_spouse is True and extraction.spouse_relocation == "with_user"
        assert extraction.arrival_timing == "next month"
        assert extraction.company_jurisdiction is None  # not said, not guessed

    def test_spouse_joining_later(self) -> None:
        extraction = parse_request("Setting up my startup in ADGM; my husband will join me later.")
        assert extraction.company_jurisdiction == "adgm"
        assert extraction.move_with_spouse is True and extraction.spouse_relocation == "later"

    def test_income_and_children(self) -> None:
        extraction = parse_request("My salary is AED 25,000 per month and we have two children.")
        assert extraction.monthly_income_aed == 25000 and extraction.children_count == 2

    def test_nothing_sensitive_is_ever_extracted(self) -> None:
        extraction = parse_request("I'm Priya from Pune, a practising Hindu, moving to Abu Dhabi.")
        assert set(extraction.model_dump()) == {
            "goals",
            "is_founder",
            "has_spouse",
            "move_with_spouse",
            "spouse_relocation",
            "children_count",
            "company_jurisdiction",
            "monthly_income_aed",
            "accommodation_provided",
            "arrival_timing",
        }
        assert all(
            not k.startswith(("faith", "religion", "nationality"))
            for k in facts_from_intake(extraction)
        )

    def test_facts_are_user_stated(self) -> None:
        facts = facts_from_intake(parse_request("I'm a founder moving with my wife"))
        assert facts and all(
            f["source"] == "user_stated" and f["source_ref"] == "request" for f in facts.values()
        )


class TestDrafting:
    def test_checklist_uses_only_given_requirements(self) -> None:
        body = checklist(
            {
                "title": "Checklist: Residence visa",
                "authority": "ICP",
                "official_url": "https://icp.gov.ae",
                "requirements": [
                    {"label": "Passport", "status": "satisfied"},
                    {
                        "label": "Medical fitness certificate",
                        "status": "produced_by_task",
                        "provided_by": "Medical fitness test",
                    },
                ],
            }
        )
        assert "- [ ] Medical fitness certificate (from: Medical fitness test)" in body
        assert "- [x] Passport" in body and "https://icp.gov.ae" in body
        assert "AED" not in body  # no invented fees

    async def test_demo_letter_uses_placeholders_for_unknowns(self) -> None:
        llm = DemoLLM()
        register_demo_responders(llm)
        text = await llm.text(
            purpose="journey.document.cover_letter",
            instructions="",
            input=json.dumps(
                {
                    "title": "Cover letter",
                    "service": "Family visa",
                    "applicant_name": None,
                    "documents": ["Passport"],
                }
            ),
        )
        assert "[your full name]" in text and "[spouse full name]" in text and "- Passport" in text

    def test_generate_document_input_is_validated(self) -> None:
        with pytest.raises(ValueError):
            GenerateDocumentInput(kind="invoice", title="x", journey_id="j")  # type: ignore[arg-type]
