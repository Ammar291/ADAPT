import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { DEMO_STORAGE_KEY, adapterActions, agentStages, blockers, branchChanges, initialProgress, readProgress, replay, researchProgress, writeProgress } from "./replay";

describe("stage replay integrity and privacy", () => {
  it("derives headline counts from recorded planner output and scopes the approval", () => {
    expect(replay.tasks).toHaveLength(22);
    expect(adapterActions).toHaveLength(17);
    expect(blockers).toHaveLength(2);
    expect(replay.featuredAction.requires_human_approval).toBe(true);
    expect(replay.actions.filter((a) => a.requires_human_approval)).toHaveLength(2);
    expect(replay.featuredAction.external_reference).toBeNull();
    expect(replay.featuredAction.response_metadata.demo_response.booked).toBe(false);
    expect(agentStages.map((e) => e.node)).toContain("final_plan");
  });
  it("bundles exactly the validated specimen bytes; each is visibly synthetic", () => {
    for (const doc of replay.documents) {
      const bytes = readFileSync(new URL(`../../../public/demo-specimens/${doc.filename}`, import.meta.url));
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(doc.sha256);
      expect(bytes.subarray(0, 4).toString()).toBe("%PDF");
      expect(doc.fields.every((field) => field.confidence >= 0.85)).toBe(true);
    }
  });
  it("records sourced considerations and a real branch with fewer dependencies", () => {
    expect(replay.considerations).toHaveLength(2);
    expect(replay.considerations.every((c) => c.evidence_ids.length > 0)).toBe(true);
    const diff = branchChanges();
    expect(diff.removedTasks.length).toBeGreaterThan(0);
    expect(diff.removedDependencies.length).toBeGreaterThan(0);
    expect(diff.removedTasks.some((t) => t.key.endsWith("@spouse"))).toBe(true);
    expect(replay.tasks.some((t) => t.key.endsWith("@spouse"))).toBe(true);
    expect(replay.research).toHaveLength(5);
    for (const group of replay.research) for (const entry of group.entries) {
      expect(entry.url).toMatch(/^https:\/\//); expect(entry.retrieved_at).toBeTruthy();
      expect(entry).not.toHaveProperty("contacts");
    }
  });
  it("restores only allowlisted progress and survives unavailable or corrupt storage", () => {
    const values = new Map<string, string>();
    const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); } };
    const p = { ...initialProgress(), scene: 7, researchStartedAt: 1000, transcript: "PRIVATE TEXT", apiKey: "PRIVATE KEY" };
    writeProgress(storage, p);
    expect(values.get(DEMO_STORAGE_KEY)).not.toContain("PRIVATE");
    expect(readProgress(storage).scene).toBe(7);
    expect(readProgress({ getItem: () => "bad json" })).toEqual(initialProgress());
    expect(readProgress({ getItem: () => { throw new Error("denied"); } })).toEqual(initialProgress());
    expect(readProgress({ getItem: () => '{"version":1,"scene":99,"decision":"submitted"}' })).toEqual(initialProgress());
    expect(() => writeProgress({ setItem: () => { throw new Error("denied"); } }, p)).not.toThrow();
  });
  it("resumes background progress after refresh without another integration call", () => {
    expect(researchProgress(null, 10000)).toBe(0);
    expect(researchProgress(1000, 0)).toBe(0);
    expect(researchProgress(1000, 5500)).toBe(0.5);
    expect(researchProgress(1000, 20000)).toBe(1);
  });
});
