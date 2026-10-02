import { describe, expect, it } from "vitest";
import type { RunEvent } from "@/domain/runs";
import { reduceRunEvents } from "@/lib/events/runEvents";
import { artifactLink, buildLog, countByFilter, describeEvent, filterLog, formatArgs, runSources, stageActivity } from "./log";

let seq = 0;
type Payload = RunEvent extends infer E ? (E extends RunEvent ? Omit<E, "runId" | "seq" | "ts"> : never) : never;
function ev(payload: Payload): RunEvent {
  seq += 1;
  return { ...payload, runId: "r1", seq, ts: `2026-09-29T10:00:${String(seq).padStart(2, "0")}Z` } as RunEvent;
}
const labelOf = (id: string) => ({ intake: "Understand your move", requirement_planner: "Find official requirements" })[id] ?? id;

describe("describeEvent", () => {
  it("writes stage lifecycle lines in plain words", () => {
    seq = 0;
    expect(describeEvent(ev({ event: "node_started", node: "intake", label: "Understand your move", attempt: 1 }), labelOf)).toMatchObject({
      text: "Started Understand your move",
      category: "stage",
      stageLabel: "Understand your move",
    });
    expect(describeEvent(ev({ event: "node_completed", node: "intake", summary: "Arriving soon", durationMs: 1240 }), labelOf)).toMatchObject({
      text: "Finished Understand your move in 1.2 s",
      detail: "Arriving soon",
      tone: "success",
    });
    expect(describeEvent(ev({ event: "node_started", node: "intake", label: "Understand your move", attempt: 2 }), labelOf)?.text).toBe(
      "Started Understand your move (attempt 2)",
    );
  });

  it("describes tool calls with their arguments", () => {
    seq = 0;
    const call = describeEvent(
      ev({ event: "tool_called", node: "intake", callId: "c", tool: "parse_request", label: "Understanding your move", args: { channel: "text" } }),
      labelOf,
    );
    expect(call).toMatchObject({ category: "tool", text: "Understanding your move", detail: "parse_request (channel: text)" });
    const failed = describeEvent(ev({ event: "tool_result", node: "intake", callId: "c", tool: "parse_request", summary: "Timed out", ok: false }), labelOf);
    expect(failed).toMatchObject({ text: "parse_request failed", detail: "Timed out", tone: "danger" });
  });

  it("flags approvals and pauses for attention", () => {
    seq = 0;
    expect(
      describeEvent(ev({ event: "approval_required", node: "human_approval", approvalId: "a", title: "Send quotes", summary: "To 3 insurers" }), labelOf),
    ).toMatchObject({
      category: "approval",
      tone: "attention",
      text: "Needs your approval: Send quotes",
    });
    expect(describeEvent(ev({ event: "run_status", node: null, status: "awaiting_input", reason: "Waiting" }), labelOf)).toMatchObject({
      category: "approval",
      text: "Paused for your review",
    });
    expect(describeEvent(ev({ event: "approval_resolved", node: "human_approval", approvalId: "a", decision: "rejected" }), labelOf)?.text).toBe(
      "You declined it",
    );
  });

  it("drops streamed message fragments", () => {
    expect(describeEvent(ev({ event: "message_delta", node: null, messageId: "m", text: "Hel" }), labelOf)).toBeNull();
  });
});

describe("formatArgs", () => {
  it("summarises values and truncates", () => {
    expect(formatArgs({ document_id: "doc_1", pages: [1, 2], nested: { a: 1 }, flag: true })).toBe(
      "document id: doc_1, pages: 2 items, nested: details, flag: true",
    );
    expect(formatArgs({ q: "x".repeat(200) }, 20)).toHaveLength(20);
    expect(formatArgs(null)).toBeNull();
    expect(formatArgs({})).toBeNull();
  });
});

describe("log filters", () => {
  it("filters by category and counts", () => {
    seq = 0;
    const log = buildLog(
      [
        ev({ event: "run_started", node: null, kind: "journey" }),
        ev({ event: "tool_called", node: "intake", callId: "c", tool: "t", label: "Tool", args: null }),
        ev({ event: "tool_result", node: "intake", callId: "c", tool: "t", summary: "ok", ok: true }),
        ev({
          event: "evidence_found",
          node: "requirement_planner",
          title: "Visa rules",
          url: "https://icp.gov.ae",
          authority: "ICP",
          kind: "official_guidance",
        }),
        ev({ event: "message_delta", node: null, messageId: "m", text: "x" }),
        ev({ event: "approval_required", node: "human_approval", approvalId: "a", title: "Send", summary: "" }),
      ],
      labelOf,
    );
    expect(log).toHaveLength(5);
    expect(filterLog(log, "tools")).toHaveLength(2);
    expect(filterLog(log, "evidence")[0]!.text).toBe("Found source: Visa rules");
    expect(countByFilter(log)).toEqual({ all: 5, tools: 2, evidence: 1, approvals: 1 });
  });
});

describe("sources and stage activity", () => {
  it("collects sources with their retrieval time, without duplicates", () => {
    seq = 0;
    const view = reduceRunEvents([
      ev({
        event: "evidence_found",
        node: "requirement_planner",
        title: "Visa rules",
        url: "https://icp.gov.ae/a",
        authority: "ICP",
        kind: "official_guidance",
      }),
      ev({
        event: "evidence_found",
        node: "requirement_planner",
        title: "Visa rules",
        url: "https://icp.gov.ae/a",
        authority: "ICP",
        kind: "official_guidance",
      }),
      ev({ event: "evidence_found", node: "eligibility_analysis", title: "Sponsor income", url: null, authority: null, kind: "authoritative_requirement" }),
    ]);
    const sources = runSources(view);
    expect(sources).toHaveLength(2);
    expect(sources[0]).toMatchObject({ title: "Visa rules", checkedAt: "2026-09-29T10:00:01Z", stage: "requirement_planner" });
  });

  it("gathers what a stage produced", () => {
    seq = 0;
    const view = reduceRunEvents([
      ev({ event: "document_generated", node: "document_preparation", documentId: "d1", title: "Cover letter" }),
      ev({ event: "action_prepared", node: "action_preparation", actionId: "a1", title: "Open TAMM", kind: "official_handoff" }),
      ev({ event: "artifact_created", node: "document_preparation", artifactType: "journey", artifactId: "j1", title: "Plan" }),
    ]);
    const docs = stageActivity(view, "document_preparation");
    expect(docs.documents).toEqual([{ id: "d1", title: "Cover letter" }]);
    expect(docs.actions).toEqual([]);
    expect(docs.artifacts).toHaveLength(1);
    expect(stageActivity(view, "action_preparation").actions[0]!.title).toBe("Open TAMM");
  });

  it("links known artifacts", () => {
    expect(artifactLink("journey")?.to).toBe("/journey");
    expect(artifactLink("twin")?.to).toBe("/knowledge/me");
    expect(artifactLink("other")).toBeNull();
  });
});
