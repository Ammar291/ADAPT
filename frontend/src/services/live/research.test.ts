import { describe, expect, it } from "vitest";
import { describeWhen, itemsFromDiscover, toDiscoverItem, toResearchStatus } from "./research";

const result = {
  id: "r1",
  job_id: "j1",
  category: "lifestyle",
  title: "Summer midday break for outdoor work",
  summary: "Outdoor work is not allowed at midday in summer.",
  relevance: "Many newcomers don't expect this.",
  fact_ids: ["fact-1"],
  evidence_kind: "authoritative_requirement",
  source_label: "official",
  source_url: "https://u.ae/en/midday",
  source_title: "Health and safety at workplace",
  source_domain: "u.ae",
  retrieved_at: "2026-09-29T00:00:00Z",
  needs_recheck: false,
  citations: [
    { id: "c1", url: "https://u.ae/en/midday", title: "u.ae", source_domain: "u.ae", source_label: "official", is_primary: true },
    { id: "c2", url: "https://news.example.com/x", title: "News", source_domain: "news.example.com", source_label: "general_web", is_primary: false },
  ],
  contacts: [{ kind: "email", value: "hi@club.ae", source_url: "https://club.ae", verified_at: "2026-09-29T00:00:00Z" }],
  event: null,
  saved: true,
  journey_node_id: null,
  created_at: "2026-09-29T00:00:00Z",
};

describe("live research mapping", () => {
  it("maps a result into a Discover item", () => {
    const item = toDiscoverItem(result);
    expect(item.section).toBe("surprises");
    expect(item.evidenceKind).toBe("authoritative_requirement");
    expect(item.source).toEqual({
      url: "https://u.ae/en/midday",
      title: "Health and safety at workplace",
      domain: "u.ae",
      label: "official",
    });
    expect(item.moreSources.map((s) => s.label)).toEqual(["general_web"]);
    expect(item.contacts).toEqual([{ kind: "email", value: "hi@club.ae", sourceUrl: "https://club.ae" }]);
    expect(item.isSample).toBe(false);
    expect(item.saved).toBe(true);
    expect(item.factIds).toEqual(["fact-1"]);
    expect(toDiscoverItem({ ...result, fact_ids: undefined }).factIds).toEqual([]);
  });

  it("describes event timing without inventing dates", () => {
    expect(describeWhen(null)).toBeNull();
    expect(describeWhen({ starts_on: null, ends_on: null, timing_note: "Usually held in November" })).toBe(
      "Usually held in November",
    );
    expect(describeWhen({ starts_on: "2026-11-20", ends_on: null, timing_note: null })).toContain("2026");
  });

  it("maps job status, including skipped faith research", () => {
    expect(toResearchStatus(undefined).state).toBe("idle");
    const status = toResearchStatus({
      id: "j1",
      run_id: "run1",
      status: "running",
      mode: "live",
      result_count: 0,
      brief_ready: false,
      seen_at: null,
      completed_at: null,
      personalised_with: ["Work: founder"],
      categories: [{ category: "faith_and_worship", status: "skipped", result_count: 0, reason: "faith_not_opted_in" }],
    });
    expect(status).toMatchObject({ state: "running", runId: "run1", mode: "live", seen: false });
    expect(status.categories).toContainEqual({ section: "faith", status: "skipped", count: 0, reason: "faith_not_opted_in" });
    expect(toResearchStatus({ id: "j", status: "succeeded", brief_ready: true, seen_at: "x" })).toMatchObject({
      state: "ready",
      briefReady: true,
      seen: true,
    });
  });

  it("merges the brief and earlier saves without duplicates", () => {
    const items = itemsFromDiscover({
      sections: [{ results: [result] }, { results: [] }],
      saved: [result, { ...result, id: "r0", category: "community" }],
    });
    expect(items.map((i) => i.id)).toEqual(["r1", "r0"]);
    expect(items.find((i) => i.id === "r0")?.section).toBe("your_communities");
  });
});
