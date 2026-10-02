import { describe, expect, it } from "vitest";
import type { DiscoverItem, ResearchStatus } from "@/domain/discover";
import { cardSlots, categoryStatusText, countBySection, faithNeedsOptIn, groupBySection, isStale, leadFirst, researchProgress, sectionState } from "./discover";

const item = (id: string, over: Partial<DiscoverItem> = {}): DiscoverItem => ({
  id,
  section: "your_communities",
  title: id,
  summary: "",
  relevance: null,
  factIds: [],
  source: { title: "S", url: "https://example.org", domain: "example.org", label: "organization" },
  moreSources: [],
  lastCheckedAt: new Date().toISOString(),
  needsRecheck: false,
  evidenceKind: "community_web",
  when: null,
  where: null,
  contacts: [],
  saved: false,
  journeyNodeId: null,
  isSample: false,
  ...over,
});

const status = (over: Partial<ResearchStatus> = {}): ResearchStatus => ({
  state: "ready",
  jobId: "j",
  runId: null,
  mode: "snapshot",
  itemCount: 0,
  lastCheckedAt: null,
  briefReady: true,
  seen: false,
  categories: [],
  personalisedWith: [],
  ...over,
});

describe("groupBySection", () => {
  it("returns every section in order and filters saved", () => {
    const items = [item("a", { section: "events" }), item("b", { section: "your_communities", saved: true })];
    const groups = groupBySection(items);
    expect(groups.map((g) => g.id)).toEqual(["your_communities", "faith", "professional", "events", "culture", "surprises", "starter_kit"]);
    expect(groups[0]!.items.map((i) => i.id)).toEqual(["b"]);
    const saved = groupBySection(items, { savedOnly: true });
    expect(saved.find((g) => g.id === "events")!.items).toEqual([]);
  });
});

describe("leadFirst", () => {
  it("leads with an item that explains why it fits and has a page", () => {
    const list = [
      item("a"),
      item("b", { relevance: "why", source: { title: "x", url: null, domain: null, label: "community" } }),
      item("c", { relevance: "why" }),
    ];
    expect(leadFirst(list).map((i) => i.id)).toEqual(["c", "a", "b"]);
  });

  it("keeps order when nothing has a reason", () => {
    expect(leadFirst([item("a"), item("b")]).map((i) => i.id)).toEqual(["a", "b"]);
    expect(leadFirst([])).toEqual([]);
  });
});

describe("cardSlots", () => {
  it("leads with a feature and never leaves a card alone on the last row", () => {
    expect(cardSlots(0)).toEqual([]);
    expect(cardSlots(1)).toEqual(["feature"]);
    expect(cardSlots(2)).toEqual(["lead", "pair"]);
    expect(cardSlots(3)).toEqual(["feature", "half", "half"]);
    expect(cardSlots(4)).toEqual(["feature", "third", "third", "third"]);
    expect(cardSlots(5)).toEqual(["feature", "half", "half", "half", "half"]);
    expect(cardSlots(6)).toEqual(["feature", "third", "third", "third", "half", "half"]);
    expect(cardSlots(8)).toEqual(["feature", "third", "third", "third", "half", "half", "half", "half"]);
  });
});

describe("faithNeedsOptIn", () => {
  it("invites when the category was skipped or consent isn't granted", () => {
    expect(faithNeedsOptIn(status({ categories: [{ section: "faith", status: "skipped", count: 0, reason: "faith_not_opted_in" }] }), "granted")).toBe(true);
    expect(faithNeedsOptIn(status(), "not_asked")).toBe(true);
    expect(faithNeedsOptIn(status(), "granted")).toBe(false);
  });
});

describe("research progress", () => {
  it("counts finished categories", () => {
    const categories = [
      { section: "faith" as const, status: "skipped" as const, count: 0, reason: "faith_not_opted_in" },
      { section: "events" as const, status: "completed" as const, count: 3, reason: null },
      { section: "culture" as const, status: "running" as const, count: 0, reason: null },
      { section: "professional" as const, status: "pending" as const, count: 0, reason: null },
    ];
    expect(researchProgress(categories)).toBe(0.5);
    expect(researchProgress([])).toBe(0);
    expect(categoryStatusText(categories[0]!)).toBe("Only if you opt in");
    expect(categoryStatusText(categories[1]!)).toBe("3 found");
    expect(categoryStatusText({ ...categories[1]!, count: 1 })).toBe("1 found");
  });
});

describe("sectionState", () => {
  const base = { section: "events" as const, items: [], loading: false, faithOptIn: false };
  it("describes each state", () => {
    expect(sectionState({ ...base, loading: true, status: undefined })).toBe("loading");
    expect(sectionState({ ...base, items: [item("a")], status: status() })).toBe("items");
    expect(
      sectionState({ ...base, status: status({ state: "running", categories: [{ section: "events", status: "running", count: 0, reason: null }] }) }),
    ).toBe("searching");
    expect(sectionState({ ...base, status: status({ categories: [{ section: "events", status: "failed", count: 0, reason: null }] }) })).toBe("failed");
    expect(sectionState({ ...base, status: status({ state: "idle" }) })).toBe("not_started");
    expect(sectionState({ ...base, status: status() })).toBe("empty");
    expect(sectionState({ ...base, section: "faith", faithOptIn: true, status: status() })).toBe("faith_invite");
    expect(sectionState({ ...base, savedOnly: true, status: status({ state: "idle" }) })).toBe("empty");
  });
});

describe("isStale and counts", () => {
  it("flags old checks and counts by section", () => {
    const now = new Date("2026-09-29T00:00:00Z");
    expect(isStale(item("a", { lastCheckedAt: "2026-08-01T00:00:00Z" }), now)).toBe(true);
    expect(isStale(item("a", { lastCheckedAt: "2026-09-20T00:00:00Z" }), now)).toBe(false);
    expect(isStale(item("a", { needsRecheck: true }), now)).toBe(true);
    expect(countBySection([item("a"), item("b"), item("c", { section: "events" })]).your_communities).toBe(2);
  });
});
