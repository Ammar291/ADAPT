import { describe, expect, it } from "vitest";
import type { KnowledgeGraph, KnowledgeNode, TwinFact } from "@/domain/graph";
import type { MoveProfile } from "@/domain/profile";
import { describeFactSources, moveRows, plural, summariseTwin } from "./summary";

const BASE: MoveProfile = {
  moveType: "business",
  arrivalDate: "2026-11-12",
  household: "spouse",
  childrenCount: 0,
  companyTiming: "now",
  jurisdiction: "undecided",
  languages: ["en", "ar"],
  housing: "long_lease",
  monthlyHousingBudgetAed: null,
  faith: null,
  note: "",
};

const NOW = new Date("2026-09-29T09:00:00");

describe("moveRows", () => {
  it("describes a move in plain words, with language names from the browser", () => {
    const rows = moveRows(BASE, NOW);
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));
    expect(byKey.moveType?.value).toBe("Starting or moving a business");
    expect(byKey.arrival?.value).toBe("12 Nov 2026");
    expect(byKey.arrival?.detail).toBe("In 44 days");
    expect(byKey.household?.detail).toBeNull();
    expect(byKey.company?.detail).toBe("Mainland or ADGM not decided yet");
    expect(byKey.languages?.value).toBe("English, Arabic");
    expect(byKey.housing?.detail).toBeNull();
    expect(rows.some((r) => r.key === "faith")).toBe(false);
  });

  it("covers flexible arrival, children, no company, a budget and a shared faith", () => {
    const rows = moveRows(
      {
        ...BASE,
        arrivalDate: null,
        household: "spouse_children",
        childrenCount: 2,
        companyTiming: "none",
        languages: [],
        monthlyHousingBudgetAed: 12000,
        faith: "all",
      },
      NOW,
    );
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));
    expect(byKey.arrival?.value).toBe("Flexible");
    expect(byKey.household?.detail).toBe("2 children");
    expect(byKey.company?.value).toBe("No company");
    expect(byKey.company?.detail).toBeNull();
    expect(byKey.languages?.value).toBe("Not shared");
    expect(byKey.housing?.detail).toBe("Up to AED 12,000 a month");
    expect(byKey.faith?.value).toBe("All faiths");
  });

  it("names one child in the singular and keeps region tags readable", () => {
    const rows = moveRows({ ...BASE, household: "children", childrenCount: 1, languages: ["pt-BR"] }, NOW);
    expect(rows.find((r) => r.key === "household")?.detail).toBe("1 child");
    expect(rows.find((r) => r.key === "languages")?.value).toBe("Portuguese");
  });
});

describe("summariseTwin", () => {
  const fact = (source: TwinFact["source"]): TwinFact => ({ value: "x", source, sourceRef: null, confidence: 1, confirmedByUser: true, observedAt: null });
  const node = (key: string, facts: Record<string, TwinFact>): KnowledgeNode => ({
    id: key,
    key,
    scope: "user",
    type: "person",
    label: key,
    summary: null,
    properties: {},
    evidence: null,
    officialUrl: null,
    facts,
  });

  it("counts items and facts by where they came from", () => {
    const graph: KnowledgeGraph = {
      nodes: [
        node("you", { a: fact("user_stated"), b: fact("user_stated") }),
        node("passport", { n: fact("document_extracted") }),
        node("company", { s: fact("system") }),
        node("goal", {}),
      ],
      edges: [],
      linkedNodes: [],
      generatedAt: "2026-09-29T00:00:00Z",
    };
    const summary = summariseTwin(graph);
    expect(summary.items).toBe(4);
    expect(summary.facts).toBe(4);
    expect(summary.bySource).toEqual({ user_stated: 2, document_extracted: 1, inferred: 0, system: 1 });
    expect(describeFactSources(summary)).toBe("2 you told ADAPT, 1 read from your documents, 1 set by ADAPT");
  });

  it("handles an empty twin", () => {
    const summary = summariseTwin({ nodes: [], edges: [], linkedNodes: [], generatedAt: "" });
    expect(summary).toEqual({ items: 0, facts: 0, bySource: { user_stated: 0, document_extracted: 0, inferred: 0, system: 0 } });
    expect(describeFactSources(summary)).toBe("");
  });
});

describe("plural", () => {
  it("picks the right form", () => {
    expect(plural(1, "document", "documents")).toBe("1 document");
    expect(plural(0, "document", "documents")).toBe("0 documents");
  });
});
