import { describe, expect, it } from "vitest";
import type { MoveProfile } from "@/domain/profile";
import { buildJourney, type PlannerProgress } from "@/services/mock/planner";
import { blockedNodes, completion, countByFilter, criticalPath, depthOf, nextActions, prerequisites, unlocks } from "./analysis";
import { diffJourneys } from "./diff";

const NOW = new Date("2026-09-29T09:00:00");

const founder: MoveProfile = {
  moveType: "business",
  arrivalDate: "2026-11-12",
  household: "spouse",
  childrenCount: 0,
  companyTiming: "now",
  jurisdiction: "mainland",
  languages: ["en"],
  housing: "long_lease",
  monthlyHousingBudgetAed: 9000,
  faith: null,
  note: "",
};

function progress(patch: Partial<PlannerProgress> = {}): PlannerProgress {
  return { done: new Set(), inProgress: new Set(), answered: new Set(), documents: [], approvals: [], draftsByNode: new Map(), ...patch };
}

const plan = (profile: MoveProfile, p = progress()) => buildJourney(profile, p, { journeyId: "j", status: "active", now: NOW });

describe("mock planner", () => {
  it("builds a dependency graph whose edges all resolve", () => {
    const journey = plan(founder);
    const keys = new Set(journey.nodes.map((n) => n.key));
    expect(journey.nodes.length).toBeGreaterThan(20);
    for (const edge of journey.edges) {
      expect(keys.has(edge.source)).toBe(true);
      expect(keys.has(edge.target)).toBe(true);
    }
    // Every official claim cites an https source.
    for (const node of journey.nodes.filter((n) => n.evidence.kind === "official_guidance")) {
      expect(node.evidence.citations[0]?.url).toMatch(/^https:\/\//);
    }
  });

  it("blocks steps until their prerequisites are done", () => {
    const before = plan(founder);
    expect(before.nodes.find((n) => n.key === "business.licence")?.status).toBe("blocked");
    expect(before.nodes.find((n) => n.key === "business.trade_name")?.status).toBe("prepared");
    const after = plan(founder, progress({ done: new Set(["business.trade_name", "business.initial_approval"]), answered: new Set(["business.premises"]) }));
    expect(after.nodes.find((n) => n.key === "business.licence")?.status).toBe("prepared");
  });

  it("leaves out family steps for someone moving alone", () => {
    const alone = plan({ ...founder, household: "alone" });
    expect(alone.nodes.some((n) => n.area === "family")).toBe(false);
  });
});

describe("journey analysis", () => {
  const journey = plan(founder);

  it("counts completion without approvals or external dependencies", () => {
    const { done, total, percent } = completion(journey);
    expect(total).toBe(journey.nodes.filter((n) => n.kind !== "approval" && n.kind !== "dependency").length);
    expect(percent).toBe(Math.round((done / total) * 100));
  });

  it("orders next actions with things waiting on the user first", () => {
    const next = nextActions(journey, 10);
    const firstNonWaiting = next.findIndex((n) => n.status !== "waiting_for_me");
    expect(next.slice(firstNonWaiting).every((n) => n.status !== "waiting_for_me")).toBe(true);
  });

  it("finds prerequisites, unlocks and depth consistently", () => {
    const depth = depthOf(journey);
    for (const node of journey.nodes) {
      for (const { node: pre } of prerequisites(journey, node.key)) {
        expect(depth.get(pre.key)!).toBeLessThan(depth.get(node.key)!);
        expect(unlocks(journey, pre.key).map((n) => n.key)).toContain(node.key);
      }
    }
    const path = criticalPath(journey);
    expect(path.length).toBeGreaterThan(2);
    expect(blockedNodes(journey).every((n) => n.status === "blocked")).toBe(true);
    const counts = countByFilter(journey);
    expect(counts.todo + counts.blocked + counts.prepared + counts.waiting_for_me + counts.done).toBe(counts.all);
  });
});

describe("diffJourneys", () => {
  it("reports removed family steps and dependencies when moving alone", () => {
    const base = plan(founder);
    const scenario = plan({ ...founder, household: "alone" });
    const diff = diffJourneys(base, scenario);
    expect(diff.removedTasks.map((t) => t.key)).toContain("family.spouse_visa");
    expect(diff.changedDependencies.some((d) => d.source === "family.spouse_visa" && d.change === "removed")).toBe(true);
    expect(diff.summary).toMatch(/no longer needed/);
  });

  it("adds a short stay and a Tawtheeq risk for short stays with a spouse", () => {
    const base = plan(founder);
    const scenario = plan({ ...founder, housing: "short_stay_first" });
    const diff = diffJourneys(base, scenario);
    expect(diff.addedTasks.map((t) => t.key)).toContain("housing.short_stay");
    expect(diff.changedRisks.some((r) => r.id === "r.short_stay_tawtheeq" && r.change === "added")).toBe(true);
    // No unsupported rule: the spouse visa doesn't wait for Tawtheeq.
    expect(scenario.edges.some((e) => e.source === "family.spouse_visa" && e.target === "housing.tawtheeq")).toBe(false);
  });
});
