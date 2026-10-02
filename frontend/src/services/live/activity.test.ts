import { afterEach, describe, expect, it, vi } from "vitest";
import { createLiveActivity, topicsForEvent } from "./activity";

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}

/** A fake API: the runs list and each run's event log, as the backend serves them. */
function backend() {
  const runs: Record<string, unknown>[] = [];
  const events: Record<string, Record<string, unknown>[]> = {};
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://test");
    if (url.pathname === "/api/agents/runs") {
      const active = url.searchParams.get("active") === "true";
      const limit = Number(url.searchParams.get("limit") ?? 20);
      const finished = new Set(["succeeded", "failed", "cancelled"]);
      return json(runs.filter((r) => !active || !finished.has(String(r.status))).slice(0, limit));
    }
    const match = /^\/api\/agents\/([^/]+)\/events$/.exec(url.pathname);
    if (match) {
      const after = Number(url.searchParams.get("after") ?? 0);
      const log = (events[match[1]!] ?? []).filter((e) => Number(e.seq) > after);
      const run = runs.find((r) => r.id === match[1]);
      return json({ run_id: match[1], status: run?.status ?? "running", last_seq: log.at(-1)?.seq ?? after, events: log });
    }
    return new Response(null, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { runs, events, fetchMock };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("topicsForEvent", () => {
  it("refreshes what a run's events point at", () => {
    expect(topicsForEvent("approval_required", "journey")).toEqual(expect.arrayContaining(["approvals", "runs"]));
    expect(topicsForEvent("document_generated", "journey")).toEqual(["generated"]);
    expect(topicsForEvent("research_completed", "research")).toEqual(["discover"]);
    expect(topicsForEvent("run_completed", "journey")).toEqual(expect.arrayContaining(["journeys", "discover"]));
    expect(topicsForEvent("run_completed", "document_extraction")).toEqual(expect.arrayContaining(["documents", "graph"]));
    expect(topicsForEvent("node_progress", "journey")).toEqual([]);
  });
});

describe("createLiveActivity", () => {
  it("reports changes after the first look, from each run's new events only", async () => {
    vi.useFakeTimers();
    const api = backend();
    api.runs.push({ id: "old", kind: "journey", status: "succeeded", last_event_seq: 40 });
    const seen: string[][] = [];
    const activity = createLiveActivity();
    const stop = activity.subscribe((topics) => seen.push(topics));

    await vi.advanceTimersByTimeAsync(0);
    expect(seen).toEqual([]); // history is already on screen

    // The journey agent queues research; the research run then finishes.
    api.runs.unshift({ id: "r1", kind: "research", status: "succeeded", last_event_seq: 2 });
    api.events.r1 = [
      { event: "research_started", seq: 1 },
      { event: "run_completed", seq: 2 },
    ];
    await vi.advanceTimersByTimeAsync(10_000);
    expect(new Set(seen.flat())).toEqual(new Set(["runs", "discover"]));

    // Nothing new: nothing reported, and events are never fetched twice.
    seen.length = 0;
    const calls = api.fetchMock.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(seen).toEqual([]);
    expect(api.fetchMock.mock.calls.slice(calls).every(([url]) => String(url).includes("/agents/runs"))).toBe(true);
    stop();
  });

  it("stops looking when nobody listens", async () => {
    vi.useFakeTimers();
    const api = backend();
    const stop = createLiveActivity().subscribe(() => {});
    await vi.advanceTimersByTimeAsync(0);
    stop();
    const calls = api.fetchMock.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(api.fetchMock.mock.calls.length).toBe(calls);
  });

  it("keeps following a paused plan however many newer runs there are", async () => {
    vi.useFakeTimers();
    const api = backend();
    api.runs.push({ id: "plan", kind: "journey", status: "awaiting_input", last_event_seq: 5 });
    for (let i = 0; i < 25; i++) api.runs.unshift({ id: `upload${i}`, kind: "document_extraction", status: "succeeded", last_event_seq: 3 });
    const seen: string[][] = [];
    const stop = createLiveActivity().subscribe((topics) => seen.push(topics));
    await vi.advanceTimersByTimeAsync(0);

    // The person approves elsewhere; the plan resumes and later finishes.
    const plan = api.runs.find((r) => r.id === "plan")!;
    Object.assign(plan, { status: "running", last_event_seq: 6 });
    api.events.plan = [{ event: "approval_resolved", seq: 6 }];
    await vi.advanceTimersByTimeAsync(10_000);
    expect(new Set(seen.flat())).toEqual(new Set(["runs", "approvals", "journeys"]));

    // Finished, it drops out of both lists: its last events are still read once.
    seen.length = 0;
    Object.assign(plan, { status: "succeeded", last_event_seq: 7 });
    api.events.plan = [...api.events.plan, { event: "run_completed", seq: 7 }];
    await vi.advanceTimersByTimeAsync(10_000);
    expect(seen.flat()).toEqual(expect.arrayContaining(["runs", "journeys", "generated", "discover"]));
    seen.length = 0;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(seen).toEqual([]);
    stop();
  });
});
