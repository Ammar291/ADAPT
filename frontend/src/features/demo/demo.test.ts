import { describe, expect, it } from "vitest";
import type { Journey, JourneyNode } from "@/domain/journey";
import type { RunEvent } from "@/domain/runs";
import type { ScenarioRoleRef } from "@/domain/scenario";
import { actionCardLabels } from "@/lib/actionCard";
import { toJourney } from "@/services/live/journeys";
import { toDiscoverItem } from "@/services/live/research";
import { toScenario } from "@/services/live/scenarios";
import { chainOf, depths, layoutChain, removedBy, SIZE } from "./chain";
import { describeMethod, doneCount, pipelineFromEvents } from "./pipeline";

function node(key: string, area: JourneyNode["area"], extra: Partial<JourneyNode> = {}): JourneyNode {
  return {
    id: key,
    key,
    kind: "task",
    title: key,
    summary: "",
    whyItMatters: null,
    area,
    status: "todo",
    authority: null,
    officialUrl: null,
    estimatedDays: null,
    dueBy: null,
    completedAt: null,
    evidence: { kind: "official_guidance", citations: [], confidence: null, note: null },
    blockers: [],
    action: null,
    governanceKey: key,
    factIds: [],
    ...extra,
  };
}

// residence <- permit <- insurance; family <- residence, family <- attest <- mission
const plan: Pick<Journey, "nodes" | "edges"> = {
  nodes: [
    node("insurance", "health"),
    node("permit", "residency"),
    node("residence", "residency"),
    node("mission", "family"),
    node("attest", "family"),
    node("family", "family", { blockers: [{ kind: "missing_info", message: "Missing information: income", resolution: null, relatedNodeKey: null }] }),
    node("company", "business"),
  ],
  edges: [
    { id: "1", source: "permit", target: "insurance", relation: "depends_on", anyOf: null },
    { id: "2", source: "residence", target: "permit", relation: "depends_on", anyOf: null },
    { id: "3", source: "family", target: "residence", relation: "depends_on", anyOf: null },
    { id: "4", source: "attest", target: "mission", relation: "depends_on", anyOf: null },
    { id: "5", source: "family", target: "attest", relation: "depends_on", anyOf: null },
  ],
};

const roles: ScenarioRoleRef[] = [
  { role: "family", label: "Family", nodeKey: "family", note: "" },
  { role: "missing_information", label: "Missing information", nodeKey: "family", note: "" },
  { role: "company", label: "Company", nodeKey: "company", note: "" },
];

describe("dependency chain layout", () => {
  it("places steps by longest prerequisite path", () => {
    const d = depths(plan);
    expect(d.get("insurance")).toBe(0);
    expect(d.get("residence")).toBe(2);
    expect(d.get("family")).toBe(3);
    expect(d.get("company")).toBe(0);
  });

  it("puts each area in its own band and draws edges left to right", () => {
    const layout = layoutChain(plan, roles);
    expect(layout.lanes.map((l) => l.area)).toEqual(["business", "residency", "health", "family"]);
    const family = layout.nodes.find((n) => n.key === "family")!;
    expect(family.x).toBe(SIZE.label + 3 * (SIZE.column + SIZE.gap));
    expect(family.h).toBe(SIZE.featured);
    // The blocker is a role on the node, not a tag of its own.
    expect(family.roles.map((r) => r.role)).toEqual(["family"]);
    expect(layout.edges.find((e) => e.id === "family<-residence")?.path.startsWith("M ")).toBe(true);
    for (const edge of layout.edges) {
      const from = layout.nodes.find((n) => n.key === edge.from)!;
      const to = layout.nodes.find((n) => n.key === edge.to)!;
      expect(from.x).toBeLessThan(to.x);
    }
  });

  it("highlights a step's whole chain and the what-if removals", () => {
    expect([...chainOf(plan, "attest")].sort()).toEqual(["attest", "family", "mission"]);
    const alone: Pick<Journey, "nodes" | "edges"> = {
      nodes: plan.nodes.filter((n) => !["family", "attest", "mission"].includes(n.key)),
      edges: plan.edges.filter((e) => !["family", "attest"].includes(e.source)),
    };
    const removed = removedBy(plan, alone);
    expect([...removed.nodes].sort()).toEqual(["attest", "family", "mission"]);
    expect([...removed.edges].sort()).toEqual(["attest<-mission", "family<-attest", "family<-residence"]);
  });
});

const envelope = (seq: number, node: string | null) => ({ runId: "r", seq, ts: "2026-10-02T00:00:00Z", node });

describe("document reading stages", () => {
  const events: RunEvent[] = [
    { ...envelope(1, null), event: "run_started", kind: "document_extraction" },
    { ...envelope(2, "classify"), event: "node_completed", summary: "Passport", durationMs: 4 },
    { ...envelope(3, "extract"), event: "node_completed", summary: "6 fields read", durationMs: 30 },
    { ...envelope(4, "validate"), event: "node_completed", summary: "All checks passed", durationMs: 2 },
  ];

  it("lights stages only from real events, in order", () => {
    const state = pipelineFromEvents(events, { uploaded: true, detail: "passport.pdf received" });
    expect(state.stages.map((s) => [s.stage, s.done])).toEqual([
      ["uploaded", true],
      ["analyzed", true],
      ["facts", false],
      ["twin", false],
    ]);
    expect(state.stages[1]!.detail).toBe("Passport. 6 fields read");
    expect(state.stages[1]!.durationMs).toBe(34);
    expect(doneCount(state)).toBe(2);
    expect(pipelineFromEvents([], { uploaded: false }).stages.every((s) => !s.done)).toBe(true);
  });

  it("finishes with the twin update", () => {
    const state = pipelineFromEvents(
      [
        ...events,
        { ...envelope(5, "structure"), event: "node_completed", summary: "5 details", durationMs: 3 },
        { ...envelope(6, "update_twin"), event: "node_completed", summary: "Everything added to your twin", durationMs: 120 },
        { ...envelope(7, null), event: "run_completed", summary: null, journeyId: null },
      ],
      { uploaded: true },
    );
    expect(doneCount(state)).toBe(4);
    expect(state.finished).toBe(true);
    expect(state.stages[2]!.detail).toBe("All checks passed. 5 details");
  });

  it("says how a document was read", () => {
    expect(describeMethod("local:pdf-text+mrz", true)).toMatch(/text layer.*check digits/);
    expect(describeMethod("openai:gpt-5.4-mini")).toMatch(/vision model/);
  });
});

describe("action card vocabulary", () => {
  it("never says submitted and labels demo adapters", () => {
    expect(actionCardLabels({ status: "awaiting_approval", kind: "appointment", isSimulated: true, approvalStatus: "pending" })).toEqual([
      "Approval required",
      "Demo adapter",
    ]);
    expect(actionCardLabels({ status: "prepared", kind: "official_handoff", isSimulated: false })).toEqual(["Prepared", "Official handoff"]);
    expect(actionCardLabels({ status: "handoff_required", kind: "government_portal", isSimulated: false, approvalStatus: "approved" })).toEqual([
      "Official handoff",
    ]);
  });
});

describe("scenario kit mapping", () => {
  it("maps research categories to Discover sections and keeps fact sources", () => {
    const scenario = toScenario({
      key: "founder-arrival",
      title: "Founder Arrival",
      tagline: "t",
      synthetic_notice: "n",
      persona: {
        name: "Kabir Rahman",
        headline: "h",
        summary: "s",
        facts: [
          { label: "Nationality", value: "From his passport", source: "document" },
          { label: "Monthly income", value: "Not given anywhere", source: "missing" },
        ],
      },
      documents: [{ key: "passport", kind: "passport", title: "Passport", filename: "p.pdf", url: "/api/x", reads: [], changes: "", confirm: true }],
      research_groups: [{ key: "muslim_faith", title: "Muslim community and faith", categories: ["faith_and_worship"], description: "d" }],
      roles: [{ role: "family", label: "Family", task_key: "service.family_residence_visa@spouse", note: "" }],
      what_if: { key: "move_alone_first", title: "Move alone first", description: "d", changes: [] },
      acts: [],
    });
    expect(scenario.researchGroups[0]!.sections).toEqual(["faith"]);
    expect(scenario.roles[0]!.nodeKey).toBe("service.family_residence_visa@spouse");
    expect(scenario.persona.facts.map((f) => f.source)).toEqual(["document", "missing"]);
  });
});

describe("live mappings used by the demo", () => {
  it("keeps how a research result was retrieved", () => {
    const item = toDiscoverItem({
      id: "r1",
      category: "community",
      title: "India Social and Cultural Centre",
      summary: "s",
      relevance: "A community for people from India.",
      fact_ids: ["f1"],
      evidence_kind: "community_web",
      source_label: "organization",
      source_url: "https://iscabudhabi.com/about",
      source_title: "ISC",
      source_domain: "iscabudhabi.com",
      retrieved_at: "2026-09-29T00:00:00Z",
      needs_recheck: false,
      retrieval: { method: "curated_snapshot", label: "ADAPT reviewed source list", note: "Curated snapshot", retrieved_at: "2026-09-29T00:00:00Z" },
      citations: [],
      contacts: [],
      saved: false,
    });
    expect(item.retrieval).toEqual({ method: "curated_snapshot", label: "ADAPT reviewed source list", note: "Curated snapshot", retrievedAt: "2026-09-29T00:00:00Z" });
  });

  it("maps a journey's considerations with their cited evidence", () => {
    const journey = toJourney({
      id: "j1",
      title: "t",
      status: "draft",
      goals: [],
      assumptions: {},
      nodes: [],
      edges: [],
      considerations: [{ id: "consideration:lease_before_family_visa", title: "Lease first", detail: "d", area: "housing", evidence_ids: ["ref:service.tawtheeq"] }],
      evidence: [{ id: "ref:service.tawtheeq", kind: "official_reference", trust: "official_guidance", title: "Tawtheeq", source_url: "https://www.tamm.abudhabi/" }],
      created_at: "2026-10-02T00:00:00Z",
      updated_at: "2026-10-02T00:00:00Z",
    });
    expect(journey.considerations).toHaveLength(1);
    expect(journey.considerations[0]!.area).toBe("housing");
    expect(journey.considerations[0]!.evidence.citations[0]!.url).toBe("https://www.tamm.abudhabi/");
  });
});
