import { describe, expect, it } from "vitest";
import type { Journey, JourneyNode } from "@/domain/journey";
import { evidenceOf } from "@/domain/journey";
import { diffJourneys } from "@/lib/journey/diff";
import { alignPaths, daysDelta, describeFieldChange, fieldLabel, focusRows, focusSteps, newActions, pathSummary, splitChangedNodes } from "./paths";

function node(key: string, patch: Partial<JourneyNode> = {}): JourneyNode {
  return {
    id: key,
    key,
    kind: "task",
    title: key,
    summary: "",
    whyItMatters: null,
    area: "residency",
    status: "todo",
    authority: null,
    officialUrl: null,
    estimatedDays: 5,
    dueBy: null,
    completedAt: null,
    evidence: evidenceOf("official_guidance"),
    blockers: [],
    action: null,
    governanceKey: null,
    factIds: [],
    ...patch,
  };
}

function journey(nodes: JourneyNode[], deps: [string, string][]): Journey {
  return {
    id: "j",
    title: "Plan",
    status: "active",
    goals: [],
    assumptions: [],
    nodes,
    edges: deps.map(([source, target], i) => ({ id: `e${i}`, source, target, relation: "depends_on", anyOf: null })),
    considerations: [],
    risks: [],
    parentJourneyId: null,
    createdAt: "2026-09-01T00:00:00Z",
    updatedAt: "2026-09-01T00:00:00Z",
  };
}

const handoff = (label: string, url: string) => ({
  id: label,
  kind: "official_handoff" as const,
  label,
  status: null,
  url,
  approvalId: null,
  draftId: null,
  documentKind: null,
  requiresUserAuthentication: true,
});

// Current: permit -> visa -> spouse visa; scenario: spouse visa removed, short stay added before housing.
const base = journey(
  [
    node("permit", { estimatedDays: 10, action: handoff("Open ICP", "https://icp.gov.ae") }),
    node("visa", { estimatedDays: 7, dueBy: "2026-11-01" }),
    node("spouse", { area: "family", estimatedDays: 20 }),
    node("housing", { area: "housing", estimatedDays: 3 }),
    node("approval.x", { kind: "approval" }),
  ],
  [
    ["visa", "permit"],
    ["spouse", "visa"],
  ],
);
const scenario = journey(
  [
    node("permit", { estimatedDays: 10, action: handoff("Open ICP", "https://icp.gov.ae") }),
    node("visa", { estimatedDays: 7, dueBy: "2026-12-01" }),
    node("stay", { area: "housing", estimatedDays: 2, action: handoff("Book a stay", "https://visitabudhabi.ae") }),
    node("housing", { area: "housing", estimatedDays: 3, action: handoff("Register lease", "https://tamm.abudhabi") }),
  ],
  [
    ["visa", "permit"],
    ["housing", "stay"],
  ],
);
const diff = diffJourneys(base, scenario);

describe("pathSummary", () => {
  it("orders steps by dependency depth and marks the longest chain", () => {
    const current = pathSummary(base, diff, "base");
    expect(current.steps.map((s) => s.key)).toEqual(["permit", "housing", "visa", "spouse"]);
    expect(current.steps.filter((s) => s.critical).map((s) => s.key)).toEqual(["permit", "visa", "spouse"]);
    expect(current.criticalDays).toBe(37);
    expect(current.steps.find((s) => s.key === "spouse")?.change).toBe("removed");
    // Approval checkpoints aren't steps on the path.
    expect(current.steps.some((s) => s.key === "approval.x")).toBe(false);
  });

  it("flags added and changed steps on the alternative path", () => {
    const alt = pathSummary(scenario, diff, "scenario");
    expect(alt.criticalDays).toBe(17);
    expect(alt.steps.find((s) => s.key === "stay")?.change).toBe("added");
    expect(alt.steps.find((s) => s.key === "visa")).toMatchObject({ change: "changed", changedFields: ["dueBy"] });
    expect(alt.completion.total).toBe(4);
  });
});

describe("alignPaths", () => {
  it("puts the same step on the same row, with gaps where a path lacks it", () => {
    const rows = alignPaths(pathSummary(base, diff, "base"), pathSummary(scenario, diff, "scenario"));
    expect(rows.map((r) => r.key)).toEqual(["permit", "stay", "visa", "housing", "spouse"]);
    expect(rows.find((r) => r.key === "stay")).toMatchObject({ base: null });
    expect(rows.find((r) => r.key === "spouse")).toMatchObject({ scenario: null });
  });

  it("focuses on changes and the longest chains", () => {
    const rows = alignPaths(pathSummary(base, diff, "base"), pathSummary(scenario, diff, "scenario"));
    expect(
      focusRows(rows)
        .map((r) => r.key)
        .sort(),
    ).toEqual(["permit", "spouse", "stay", "visa"]);
    expect(focusSteps(pathSummary(scenario, diff, "scenario").steps).map((s) => s.key)).toEqual(["permit", "stay", "visa"]);
  });
});

describe("newActions", () => {
  it("lists actions that are new or different in the scenario", () => {
    const actions = newActions(base, scenario);
    expect(actions.map((a) => [a.key, a.newStep])).toEqual([
      ["stay", true],
      ["housing", false],
    ]);
    expect(actions[0]).toMatchObject({ label: "Book a stay", url: "https://visitabudhabi.ae", requiresUserAuthentication: true });
  });
});

describe("changed steps", () => {
  it("describes a moved date", () => {
    expect(describeFieldChange(base, scenario, "visa", "dueBy")).toEqual({ field: "Target date", from: "1 Nov", to: "1 Dec" });
  });

  it("groups date-only changes", () => {
    const split = splitChangedNodes([
      { key: "a", title: "A", fields: ["dueBy"] },
      { key: "b", title: "B", fields: ["status", "dueBy"] },
    ]);
    expect(split.datesOnly.map((c) => c.key)).toEqual(["a"]);
    expect(split.other.map((c) => c.key)).toEqual(["b"]);
  });

  it("labels fields and day differences", () => {
    expect(fieldLabel("dueBy")).toBe("Target date");
    expect(fieldLabel("estimatedDays")).toBe("Estimated days");
    expect(daysDelta(40, 33)).toEqual({ text: "7 days shorter", direction: "shorter" });
    expect(daysDelta(40, 41).text).toBe("1 day longer");
    expect(daysDelta(40, 40).direction).toBe("same");
  });
});
