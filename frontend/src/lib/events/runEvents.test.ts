import { describe, expect, it } from "vitest";
import type { RunEvent } from "@/domain/runs";
import { initialRunView, reduceRunEvent, reduceRunEvents, stageStatuses } from "./runEvents";

const RUN = "run_1";
let seq = 0;
type Payload = RunEvent extends infer E ? (E extends RunEvent ? Omit<E, "runId" | "seq" | "ts"> : never) : never;
function ev(payload: Payload): RunEvent {
  seq += 1;
  return { ...payload, runId: RUN, seq, ts: `2026-09-29T10:00:${String(seq).padStart(2, "0")}Z` } as RunEvent;
}

describe("reduceRunEvent", () => {
  it("tracks a stage from start to completion, with its tool calls", () => {
    seq = 0;
    const view = reduceRunEvents([
      ev({ event: "run_started", node: null, kind: "journey" }),
      ev({ event: "node_started", node: "dependency_analysis", label: "Order steps", attempt: 1 }),
      ev({ event: "tool_called", node: "dependency_analysis", callId: "c1", tool: "plan", label: "Planning", args: null }),
      ev({ event: "node_progress", node: "dependency_analysis", message: "Ordering 12 steps", progress: 0.5 }),
      ev({ event: "tool_result", node: "dependency_analysis", callId: "c1", tool: "plan", summary: "12 steps", ok: true }),
      ev({ event: "node_completed", node: "dependency_analysis", summary: "12 steps", durationMs: 840 }),
      ev({ event: "run_completed", node: null, summary: "Plan ready", journeyId: "j1" }),
    ]);
    expect(view.status).toBe("succeeded");
    expect(view.journeyId).toBe("j1");
    expect(view.stages.dependency_analysis).toMatchObject({ status: "complete", summary: "12 steps", durationMs: 840, progress: 1 });
    expect(view.stages.dependency_analysis!.tools).toEqual([expect.objectContaining({ callId: "c1", status: "done", summary: "12 steps" })]);
  });

  it("ignores replayed events after a reconnect", () => {
    seq = 0;
    const started = ev({ event: "run_started", node: null, kind: "diagnostic" });
    const node = ev({ event: "node_started", node: "check", label: "Check", attempt: 1 });
    const once = reduceRunEvents([started, node]);
    expect(reduceRunEvent(reduceRunEvent(once, started), node)).toBe(once);
  });

  it("marks the gate stage as awaiting approval, then resumes", () => {
    seq = 0;
    let view = reduceRunEvents([
      ev({ event: "run_started", node: null, kind: "journey" }),
      ev({ event: "node_started", node: "human_approval", label: "Your approval", attempt: 1 }),
      ev({ event: "approval_required", node: "human_approval", approvalId: "a1", title: "Send", summary: "Send it" }),
      ev({ event: "run_status", node: null, status: "awaiting_input", reason: "waiting" }),
    ]);
    expect(view.status).toBe("awaiting_input");
    expect(view.stages.human_approval!.status).toBe("awaiting");
    expect(view.pendingApprovals).toHaveLength(1);
    view = reduceRunEvent(view, ev({ event: "approval_resolved", node: "human_approval", approvalId: "a1", decision: "approved" }));
    view = reduceRunEvent(view, ev({ event: "run_status", node: null, status: "running", reason: "resumed" }));
    expect(view.pendingApprovals).toHaveLength(0);
    expect(view.stages.human_approval!.status).toBe("running");
  });

  it("reports queued and blocked stages the run hasn't reached", () => {
    seq = 0;
    const view = reduceRunEvents([
      ev({ event: "run_started", node: null, kind: "journey" }),
      ev({ event: "node_started", node: "intake", label: "Intake", attempt: 1 }),
      ev({ event: "node_failed", node: "intake", code: "x", message: "Timed out", retryable: true }),
      ev({ event: "run_failed", node: null, code: "x", message: "Timed out", retryable: true }),
    ]);
    expect(stageStatuses(view, ["intake", "profile_analysis"])).toEqual({ intake: "failed", profile_analysis: "blocked" });
    expect(stageStatuses(initialRunView(), ["intake"])).toEqual({ intake: "queued" });
    expect(view.error).toEqual({ code: "x", message: "Timed out" });
  });

  it("follows background research", () => {
    seq = 0;
    const view = reduceRunEvents([
      ev({ event: "research_started", node: null, jobId: "r1", sections: ["events", "culture"] }),
      ev({ event: "research_category_completed", node: null, jobId: "r1", section: "events", resultCount: 3 }),
      ev({ event: "research_completed", node: null, jobId: "r1", resultCount: 5 }),
    ]);
    expect(view.research).toEqual({ jobId: "r1", state: "completed", sections: ["events", "culture"], completed: ["events"], results: 5 });
  });
});
