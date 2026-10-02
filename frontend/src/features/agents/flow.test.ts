import { describe, expect, it } from "vitest";
import type { RunEvent, RunSummary } from "@/domain/runs";
import { reduceRunEvents, stageStatuses } from "@/lib/events/runEvents";
import { JOURNEY_WORKFLOW } from "@/services/mock/workflows";
import {
  conditionLabel,
  edgeState,
  elapsedMs,
  focusStage,
  formatClock,
  pickRunId,
  runHeadline,
  stageLine,
  stageProgress,
  takenBranches,
  trimLead,
} from "./flow";

let seq = 0;
type Payload = RunEvent extends infer E ? (E extends RunEvent ? Omit<E, "runId" | "seq" | "ts"> : never) : never;
function ev(payload: Payload): RunEvent {
  seq += 1;
  return { ...payload, runId: "r1", seq, ts: `2026-09-29T10:00:${String(seq).padStart(2, "0")}Z` } as RunEvent;
}
const ids = JOURNEY_WORKFLOW.stages.map((s) => s.id);

function through(stages: string[]): RunEvent[] {
  return stages.flatMap((id) => [
    ev({ event: "node_started", node: id, label: id, attempt: 1 }),
    ev({ event: "node_completed", node: id, summary: null, durationMs: 100 }),
  ]);
}

describe("pickRunId", () => {
  const recent = [{ id: "new" }, { id: "old" }] as RunSummary[];
  it("prefers the run in the URL", () => expect(pickRunId("old", recent)).toBe("old"));
  it("falls back to the newest run", () => expect(pickRunId(null, recent)).toBe("new"));
  it("is null with no runs", () => expect(pickRunId(null, [])).toBeNull());
});

describe("edges", () => {
  it("fills edges the run has passed and animates the one it is on", () => {
    seq = 0;
    const view = reduceRunEvents([
      ev({ event: "run_started", node: null, kind: "journey" }),
      ...through(["intake", "profile_analysis"]),
      ev({ event: "node_started", node: "document_analysis", label: "Read", attempt: 1 }),
    ]);
    const statuses = stageStatuses(view, ids);
    const taken = takenBranches(JOURNEY_WORKFLOW, view, statuses);
    expect(edgeState({ source: "intake", target: "profile_analysis", condition: null }, statuses, taken)).toBe("done");
    expect(edgeState({ source: "profile_analysis", target: "document_analysis", condition: null }, statuses, taken)).toBe("active");
    expect(edgeState({ source: "document_analysis", target: "eligibility_analysis", condition: null }, statuses, taken)).toBe("idle");
  });

  it("follows the approved branch and marks the other as skipped", () => {
    seq = 0;
    const view = reduceRunEvents([
      ev({ event: "run_started", node: null, kind: "journey" }),
      ev({ event: "node_started", node: "human_approval", label: "Approve", attempt: 1 }),
      ev({ event: "approval_required", node: "human_approval", approvalId: "a1", title: "Send", summary: "" }),
      ev({ event: "approval_resolved", node: "human_approval", approvalId: "a1", decision: "approved" }),
      ev({ event: "node_completed", node: "human_approval", summary: null, durationMs: 10 }),
      ...through(["execution_or_handoff", "final_plan"]),
    ]);
    const statuses = stageStatuses(view, ids);
    const taken = takenBranches(JOURNEY_WORKFLOW, view, statuses);
    expect(taken).toEqual(new Set(["human_approval->execution_or_handoff"]));
    expect(edgeState({ source: "human_approval", target: "execution_or_handoff", condition: "approved" }, statuses, taken)).toBe("done");
    expect(edgeState({ source: "human_approval", target: "final_plan", condition: "rejected" }, statuses, taken)).toBe("skipped");
  });

  it("uses the recorded decision when the user declines", () => {
    seq = 0;
    const view = reduceRunEvents([
      ev({ event: "node_started", node: "human_approval", label: "Approve", attempt: 1 }),
      ev({ event: "approval_resolved", node: "human_approval", approvalId: "a1", decision: "rejected" }),
      ev({ event: "node_completed", node: "human_approval", summary: null, durationMs: 10 }),
      ...through(["final_plan"]),
    ]);
    const statuses = stageStatuses(view, ids);
    expect(takenBranches(JOURNEY_WORKFLOW, view, statuses)).toEqual(new Set(["human_approval->final_plan"]));
  });

  it("infers the branch from what started first when nothing was decided", () => {
    seq = 0;
    const view = reduceRunEvents(through(["human_approval", "execution_or_handoff", "final_plan"]));
    const statuses = stageStatuses(view, ids);
    expect(takenBranches(JOURNEY_WORKFLOW, view, statuses)).toEqual(new Set(["human_approval->execution_or_handoff"]));
  });

  it("labels conditions in plain words", () => {
    expect(conditionLabel("approved")).toBe("If you approve");
    expect(conditionLabel("rejected")).toBe("If you decline");
    expect(conditionLabel("needs_more_info")).toBe("If needs more info");
  });
});

describe("run helpers", () => {
  it("counts finished stages", () => {
    expect(stageProgress({ a: "complete", b: "running", c: "queued", d: "complete" })).toEqual({ complete: 2, total: 4, ratio: 0.5 });
  });

  it("keeps the live stage in focus", () => {
    seq = 0;
    const view = reduceRunEvents([...through(["intake"]), ev({ event: "node_started", node: "profile_analysis", label: "P", attempt: 1 })]);
    expect(focusStage(view, stageStatuses(view, ids))).toBe("profile_analysis");
    const done = reduceRunEvents(through(["intake", "profile_analysis"]));
    expect(focusStage(done, stageStatuses(done, ids))).toBe("profile_analysis");
  });

  it("measures elapsed time until the run finishes", () => {
    expect(elapsedMs("2026-09-29T10:00:00Z", null, Date.parse("2026-09-29T10:01:05Z"))).toBe(65_000);
    expect(elapsedMs("2026-09-29T10:00:00Z", "2026-09-29T10:00:12Z", Date.parse("2026-09-29T11:00:00Z"))).toBe(12_000);
    expect(elapsedMs(null, null, 0)).toBeNull();
  });

  it("formats a clock", () => {
    expect(formatClock(7_400)).toBe("0:07");
    expect(formatClock(125_000)).toBe("2:05");
    expect(formatClock(3_729_000)).toBe("1:02:09");
  });

  it("writes a headline for each state", () => {
    expect(runHeadline("journey", "running")).toBe("ADAPT is building your plan");
    expect(runHeadline("journey", "awaiting_input")).toBe("Waiting for your approval");
    expect(runHeadline("diagnostic", "succeeded")).toBe("Every part of ADAPT responded");
    expect(runHeadline("what_if", "failed")).toBe("This run stopped before it finished");
  });
});

describe("stageLine", () => {
  it("shows the running tool, then the result", () => {
    seq = 0;
    const view = reduceRunEvents([
      ev({ event: "node_started", node: "intake", label: "Intake", attempt: 1 }),
      ev({ event: "node_progress", node: "intake", message: "Reading", progress: 0.3 }),
      ev({ event: "tool_called", node: "intake", callId: "c", tool: "parse", label: "Understanding your move", args: null }),
    ]);
    expect(stageLine("running", view.stages.intake, "desc")).toBe("Understanding your move");
    const after = reduceRunEvents([ev({ event: "tool_result", node: "intake", callId: "c", tool: "parse", summary: "ok", ok: true })], view);
    expect(stageLine("running", after.stages.intake, "desc")).toBe("Reading");
    expect(stageLine("queued", undefined, "Reads what you said")).toBe("Reads what you said");
    expect(stageLine("awaiting", undefined, "")).toBe("Paused until you decide");
    // Running when the run was cancelled: explain, don't repeat the last progress note.
    expect(stageLine("failed", view.stages.intake, "desc", "cancelled")).toBe("Stopped when the run was cancelled");
    expect(stageLine("blocked", undefined, "desc", "cancelled")).toBe("Not reached: the run was cancelled");
    const failed = reduceRunEvents([ev({ event: "node_failed", node: "intake", code: "x", message: "Timed out", retryable: true })], view);
    expect(stageLine("failed", failed.stages.intake, "desc", "failed")).toBe("Timed out");
  });
});

describe("trimLead", () => {
  it("drops words the headline already says", () => {
    expect(trimLead("Your plan is ready: 29 steps, 3 risks to watch.", "Your plan is ready")).toBe("29 steps, 3 risks to watch.");
    expect(trimLead("Scenario compared with your plan.", "Your what-if is ready to compare")).toBe("Scenario compared with your plan.");
    expect(trimLead("Your plan is ready", "Your plan is ready")).toBe("Your plan is ready");
    expect(trimLead(null, "x")).toBeNull();
  });
});
