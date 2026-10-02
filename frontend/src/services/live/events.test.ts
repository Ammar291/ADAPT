import { describe, expect, it } from "vitest";
import { normaliseRunEvent } from "./events";

describe("normaliseRunEvent", () => {
  it("reads the flat wire format", () => {
    expect(
      normaliseRunEvent({ event: "tool_called", run_id: "r", seq: 3, ts: "t", node: "eligibility_analysis", tool: "query_governance", call_id: "c1", summary: "Matching services" }),
    ).toEqual({ event: "tool_called", runId: "r", seq: 3, ts: "t", node: "eligibility_analysis", callId: "c1", tool: "query_governance", label: "Matching services", args: null });
    expect(
      normaliseRunEvent({ event: "evidence_found", run_id: "r", seq: 4, ts: "t", node: null, title: "ICP", source_url: "https://icp.gov.ae", authority: "ICP", evidence_kind: "official_guidance" }),
    ).toMatchObject({ url: "https://icp.gov.ae", kind: "official_guidance" });
    expect(normaliseRunEvent({ event: "node_completed", run_id: "r", seq: 5, ts: "t", node: "x", summary: null, duration_ms: 12 })).toMatchObject({ durationMs: 12 });
  });

  it("reads the original type/data envelope", () => {
    expect(
      normaliseRunEvent({ type: "approval.requested", run_id: "r", seq: 1, ts: "t", node: "approval_gate", data: { approval_id: "a", title: "T", summary: "S" } }),
    ).toEqual({ event: "approval_required", runId: "r", seq: 1, ts: "t", node: "approval_gate", approvalId: "a", title: "T", summary: "S" });
  });

  it("drops keep-alives and unknown events", () => {
    expect(normaliseRunEvent({ event: "ping" })).toBeNull();
    expect(normaliseRunEvent("nope")).toBeNull();
  });
});
