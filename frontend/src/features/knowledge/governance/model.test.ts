import { describe, expect, it } from "vitest";
import type { KnowledgeEdge, KnowledgeNode } from "@/domain/graph";
import { governanceGraph } from "@/services/mock/governance";
import { overlaps } from "../layout/geometry";
import {
  acronymOf,
  buildGovernanceMap,
  describeCondition,
  groupNeighbours,
  propertyFacts,
  relationVariant,
  shortLabel,
  withoutAcronym,
} from "./model";

const graph = governanceGraph();

describe("buildGovernanceMap (real governance snapshot)", () => {
  const started = performance.now();
  const map = buildGovernanceMap(graph, 1.8);
  const took = performance.now() - started;

  it("leaves cited sources and citation edges off the map", () => {
    expect(map.items.some((i) => i.type === "source")).toBe(false);
    expect(map.edges.some((e) => e.relation === "evidenced_by")).toBe(false);
    expect(map.items.length).toBe(graph.nodes.filter((n) => n.type !== "source").length);
  });

  it("lays out every rule without overlaps, quickly", () => {
    const rects = map.items.map((i) => i.rect);
    rects.forEach((r, i) => rects.forEach((o, j) => j > i && expect(overlaps(r, o)).toBe(false)));
    expect(took).toBeLessThan(1500);
  });

  it("orders the columns from requirements to authorities", () => {
    expect(map.headers.map((h) => h.id)).toEqual([
      "header:requirements",
      "header:documents",
      "header:services",
      "header:channels",
      "header:authorities",
    ]);
    const x = (type: string) => Math.min(...map.items.filter((i) => i.type === type).map((i) => i.rect.x));
    expect(x("requirement")).toBeLessThan(x("document"));
    expect(x("document")).toBeLessThan(x("service"));
    expect(x("service")).toBeLessThan(x("portal"));
    expect(x("portal")).toBeLessThan(x("authority"));
    expect(map.items.find((i) => i.type === "appointment")!.group).toBe("services");
    expect(map.items.find((i) => i.type === "legal_instrument")!.group).toBe("authorities");
  });

  it("keeps a roughly viewport-shaped map for wide and tall screens", () => {
    expect(map.bounds.width / map.bounds.height).toBeGreaterThan(1);
    const tall = buildGovernanceMap(graph, 0.6);
    expect(tall.bounds.width / tall.bounds.height).toBeLessThan(map.bounds.width / map.bounds.height);
  });

  it("marks dependencies with arrows", () => {
    const depends = map.edges.filter((e) => e.relation === "depends_on");
    expect(depends.length).toBeGreaterThan(0);
    expect(depends.every((e) => e.marker === "ink" && e.variant === "depends")).toBe(true);
  });
});

describe("relation styles", () => {
  it("gives each relation family its own look", () => {
    expect(relationVariant("requires")).toBe("requires");
    expect(relationVariant("may_require")).toBe("may");
    expect(relationVariant("satisfied_by")).toBe("produces");
    expect(relationVariant("available_at")).toBe("quiet");
    expect(relationVariant("provides")).toBe("quiet");
  });
});

describe("acronyms", () => {
  it("finds the short name authorities are known by", () => {
    expect(acronymOf("Federal Authority for Identity, Citizenship, Customs & Port Security (ICP)")).toBe("ICP");
    expect(acronymOf("UAE Ministry of Foreign Affairs (MoFA)")).toBe("MoFA");
    expect(acronymOf("Abu Dhabi Department of Economic Development (ADDED)")).toBe("ADDED");
    expect(acronymOf("SEHA – Abu Dhabi Health Services Company")).toBe("SEHA");
    expect(acronymOf("Integrated Transport Centre (Abu Dhabi Mobility)")).toBeNull();
    expect(withoutAcronym("Federal Tax Authority (FTA)")).toBe("Federal Tax Authority");
    expect(withoutAcronym("Integrated Transport Centre (Abu Dhabi Mobility)")).toBe("Integrated Transport Centre (Abu Dhabi Mobility)");
  });
});

describe("groupNeighbours", () => {
  const node = (id: string, type = "service", label = id): KnowledgeNode => ({
    id,
    key: `${type}.${id}`,
    scope: "governance",
    type,
    label,
    summary: null,
    properties: {},
    evidence: null,
    officialUrl: null,
    facts: {},
  });
  const edge = (source: string, relation: string, target: string, anyOf: string | null = null): KnowledgeEdge => ({
    id: `${source}-${relation}-${target}`,
    scope: "governance",
    source,
    target,
    relation,
    label: null,
    anyOf,
  });

  it("reads relations from the selected node's point of view, in a sensible order", () => {
    const neighbours = [node("prior"), node("next"), node("passport", "document"), node("icp", "authority"), node("tamm", "portal"), node("src", "source"), node("rule", "eligibility_rule")];
    const edges = [
      edge("me", "depends_on", "prior"),
      edge("next", "depends_on", "me"),
      edge("me", "requires", "passport"),
      edge("icp", "provides", "me"),
      edge("me", "available_at", "tamm"),
      edge("me", "evidenced_by", "src"),
      edge("rule", "applies_to", "me"),
    ];
    const groups = groupNeighbours("me", edges, neighbours);
    expect(groups.map((g) => g.title)).toEqual(["Comes after", "Eligibility rules", "You'll need", "Provided by", "Where to apply", "Unlocks"]);
    expect(groups.flatMap((g) => g.items.map((i) => i.node.id))).not.toContain("src");
  });

  it("flags either-or alternatives", () => {
    const groups = groupNeighbours("me", [edge("me", "depends_on", "a", "licence"), edge("me", "depends_on", "b", "licence")], [node("a"), node("b")]);
    expect(groups[0]!.items.every((i) => i.either)).toBe(true);
  });

  it("works on the real snapshot", () => {
    const family = graph.nodes.find((n) => n.key === "service.family_residence_visa")!;
    const edges = graph.edges.filter((e) => e.source === family.id || e.target === family.id);
    const ids = new Set(edges.flatMap((e) => [e.source, e.target]));
    const groups = groupNeighbours(family.id, edges, graph.nodes.filter((n) => ids.has(n.id)));
    const titles = groups.map((g) => g.title);
    expect(titles).toContain("You'll need");
    expect(titles).toContain("Provided by");
    expect(titles).toContain("Where to apply");
    expect(titles).toContain("Eligibility rules");
  });
});

describe("describeCondition", () => {
  it("turns the sponsor income rule into plain sentences", () => {
    const rule = graph.nodes.find((n) => n.key === "eligibility_rule.family_sponsor_income")!;
    expect(describeCondition(rule.properties.condition)).toEqual({
      kind: "any",
      items: [
        { kind: "leaf", text: "Monthly income: at least AED 4,000" },
        {
          kind: "all",
          items: [
            { kind: "leaf", text: "Monthly income: at least AED 3,000" },
            { kind: "leaf", text: "Accommodation is provided by the employer" },
          ],
        },
      ],
    });
  });

  it("reads every condition in the snapshot without falling back to raw data", () => {
    const flatten = (c: ReturnType<typeof describeCondition>): string[] => (!c ? [] : c.kind === "leaf" ? [c.text] : c.items.flatMap(flatten));
    for (const node of graph.nodes.filter((n) => n.properties.condition)) {
      const lines = flatten(describeCondition(node.properties.condition));
      expect(lines.length).toBeGreaterThan(0);
      lines.forEach((line) => expect(line).not.toMatch(/[{}[\]"]|undefined|object/));
    }
  });

  it("handles single rules, lists and unknown shapes", () => {
    expect(describeCondition({ op: "gte", fact: "person.age", value: 18 })).toEqual({ kind: "leaf", text: "Age: at least 18" });
    expect(describeCondition({ op: "in", fact: "person.relationship_to_sponsor", value: ["son", "daughter"] })).toEqual({
      kind: "leaf",
      text: "Relationship to the sponsor: son or daughter",
    });
    expect(describeCondition({ op: "eq", fact: "company.has_resident_signatory", value: true })).toEqual({
      kind: "leaf",
      text: "The company has a UAE-resident authorised signatory",
    });
    expect(describeCondition({ op: "wobble", fact: "x", value: 1 })).toBeNull();
    expect(describeCondition("nope")).toBeNull();
  });
});

describe("propertyFacts", () => {
  it("shows simple extra properties and skips the ones shown elsewhere", () => {
    const tawtheeq = graph.nodes.find((n) => n.key === "service.tawtheeq")!;
    expect(propertyFacts(tawtheeq)).toEqual([{ label: "Registered by", value: "The landlord" }]);
    const family = graph.nodes.find((n) => n.key === "service.family_residence_visa")!;
    expect(propertyFacts(family)).toEqual([]);
  });
});

describe("shortLabel", () => {
  it("drops the leading verb of services and long asides in brackets", () => {
    expect(shortLabel({ type: "service", label: "Get your residence visa" })).toBe("Residence visa");
    expect(shortLabel({ type: "service", label: "Issue an economic licence (mainland)" })).toBe("Economic licence (mainland)");
    expect(shortLabel({ type: "portal", label: "ICP smart services (website and UAEICP app)" })).toBe("ICP smart services");
    expect(shortLabel({ type: "document", label: "Registered tenancy contract (Tawtheeq)" })).toBe("Registered tenancy contract (Tawtheeq)");
    expect(shortLabel({ type: "document", label: "Get well card" })).toBe("Get well card");
  });
});
