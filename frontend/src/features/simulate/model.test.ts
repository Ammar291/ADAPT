import { describe, expect, it } from "vitest";
import { ASSUMPTION } from "@/domain/journey";
import {
  addMonths,
  assumptionName,
  assumptionValueLabel,
  changedKeys,
  changesBetween,
  draftFromJourney,
  formatBudget,
  PRESETS,
  presetActive,
  presetAvailable,
  sameChanges,
  togglePreset,
  type Draft,
} from "./model";

const journey = {
  assumptions: [
    { key: ASSUMPTION.household, label: "With my spouse", value: "spouse" },
    { key: ASSUMPTION.children, label: "0 children", value: 0 },
    { key: ASSUMPTION.companyTiming, label: "Now", value: "now" },
    { key: ASSUMPTION.arrivalDate, label: "Arriving", value: "2026-11-12" },
    { key: ASSUMPTION.budget, label: "AED 9000", value: 9000 },
    { key: ASSUMPTION.housing, label: "Lease", value: "long_lease" },
  ],
};
const base = draftFromJourney(journey);
const today = new Date("2026-09-29T12:00:00");
const preset = (id: string) => PRESETS.find((p) => p.id === id)!;

describe("draftFromJourney", () => {
  it("reads the current answers", () => {
    expect(base).toEqual({
      household: "spouse",
      childrenCount: 0,
      companyTiming: "now",
      jurisdiction: "undecided",
      arrivalDate: "2026-11-12",
      budget: 9000,
      housing: "long_lease",
    });
  });

  it("falls back safely on missing or odd values", () => {
    expect(draftFromJourney({ assumptions: [{ key: ASSUMPTION.household, label: "", value: "somebody" }] })).toEqual({
      household: "alone",
      childrenCount: 0,
      companyTiming: "none",
      jurisdiction: "undecided",
      arrivalDate: null,
      budget: null,
      housing: "long_lease",
    });
  });
});

describe("changes", () => {
  it("sends only what changed", () => {
    const draft: Draft = { ...base, household: "alone", budget: 12000 };
    expect(changedKeys(base, draft)).toEqual(["household", "budget"]);
    expect(changesBetween(base, draft)).toEqual([
      { key: ASSUMPTION.household, value: "alone" },
      { key: ASSUMPTION.budget, value: 12000 },
    ]);
    expect(changesBetween(base, base)).toEqual([]);
  });

  it("counts at least one child when the household includes children", () => {
    const draft: Draft = { ...base, household: "spouse_children" };
    expect(changesBetween(base, draft)).toEqual([
      { key: ASSUMPTION.household, value: "spouse_children" },
      { key: ASSUMPTION.children, value: 1 },
    ]);
  });

  it("ignores the children count when the new household has none", () => {
    const withKids: Draft = { ...base, household: "spouse_children", childrenCount: 2 };
    expect(changedKeys(withKids, { ...withKids, household: "alone" })).toEqual(["household"]);
  });

  it("can clear the budget", () => {
    expect(changesBetween(base, { ...base, budget: null })).toEqual([{ key: ASSUMPTION.budget, value: null }]);
  });

  it("compares change lists", () => {
    const a = changesBetween(base, { ...base, housing: "short_stay_first" });
    expect(sameChanges(a, [...a])).toBe(true);
    expect(sameChanges(undefined, a)).toBe(false);
    expect(sameChanges(a, [])).toBe(false);
  });
});

describe("presets", () => {
  it("sets its variable from the current plan, and toggles off", () => {
    const later = togglePreset(base, base, preset("arrive_later"), today);
    expect(later.arrivalDate).toBe("2026-12-12");
    expect(presetActive(base, later, preset("arrive_later"), today)).toBe(true);
    // Applying again returns to the current plan rather than adding another month.
    expect(togglePreset(base, later, preset("arrive_later"), today).arrivalDate).toBe("2026-11-12");
  });

  it("combines with other changes", () => {
    const draft = togglePreset(base, togglePreset(base, base, preset("alone_first"), today), preset("short_stay"), today);
    expect(changedKeys(base, draft)).toEqual(["household", "housing"]);
  });

  it("isn't offered when it would change nothing", () => {
    expect(presetAvailable({ ...base, household: "alone" }, preset("alone_first"), today)).toBe(false);
    expect(presetAvailable(base, preset("alone_first"), today)).toBe(true);
  });

  it("picks a date for a flexible arrival", () => {
    const flexible = { ...base, arrivalDate: null };
    expect(togglePreset(flexible, flexible, preset("arrive_later"), today).arrivalDate).toBe("2026-12-28");
  });
});

describe("labels", () => {
  it("adds months, clamping to the month's end", () => {
    expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonths("2026-12-15", 1)).toBe("2027-01-15");
  });

  it("formats budgets", () => {
    expect(formatBudget(12500)).toBe("AED 12,500 a month");
    expect(formatBudget(null)).toBe("Not set");
  });

  it("turns raw simulated values into plain words", () => {
    expect(assumptionValueLabel(ASSUMPTION.household, "spouse")).toBe("With my spouse");
    expect(assumptionValueLabel(ASSUMPTION.companyTiming, "later")).toBe("Setting up a company later");
    expect(assumptionValueLabel(ASSUMPTION.budget, "12000")).toBe("AED 12,000 a month");
    expect(assumptionValueLabel(ASSUMPTION.budget, "not set")).toBe("Not set");
    expect(assumptionValueLabel(ASSUMPTION.arrivalDate, "null")).toBe("Flexible");
    expect(assumptionValueLabel(ASSUMPTION.arrivalDate, "2026-12-12")).toBe("12 Dec 2026");
    expect(assumptionValueLabel(ASSUMPTION.children, "2")).toBe("2 children");
    expect(assumptionName(ASSUMPTION.household, "x")).toBe("Who's moving");
    expect(assumptionName("unknown.key", "Fallback")).toBe("Fallback");
  });
});
