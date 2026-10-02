/**
 * Normalises backend agent events into the domain `RunEvent` union. Accepts both wire
 * formats: the original `{type: "node.started", data: {...}}` envelope and the flat
 * `{event: "node_started", ...fields}` format. Unknown event types are dropped.
 */
import type { EvidenceKind } from "@/domain/common";
import type { RunEvent, RunEventType, RunKind, RunStatus } from "@/domain/runs";

type Raw = Record<string, unknown>;

const LEGACY: Record<string, RunEventType> = {
  "run.started": "run_started",
  "run.status": "run_status",
  "run.completed": "run_completed",
  "run.failed": "run_failed",
  "run.cancelled": "run_cancelled",
  "node.started": "node_started",
  "node.progress": "node_progress",
  "node.completed": "node_completed",
  "node.failed": "node_failed",
  "artifact.created": "artifact_created",
  "artifact.updated": "artifact_created",
  "approval.requested": "approval_required",
  "approval.resolved": "approval_resolved",
  "question.asked": "question_asked",
  "message.delta": "message_delta",
};

const KNOWN = new Set<RunEventType>([
  "run_started",
  "run_status",
  "run_completed",
  "run_failed",
  "run_cancelled",
  "node_started",
  "node_progress",
  "node_completed",
  "node_failed",
  "tool_called",
  "tool_result",
  "evidence_found",
  "document_generated",
  "approval_required",
  "approval_resolved",
  "action_prepared",
  "research_started",
  "research_source_found",
  "research_category_completed",
  "research_completed",
  "research_failed",
  "question_asked",
  "message_delta",
  "artifact_created",
  "error",
]);

const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const strOrNull = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown, fallback = 0): number => (typeof v === "number" ? v : fallback);
const numOrNull = (v: unknown): number | null => (typeof v === "number" ? v : null);

export function normaliseRunEvent(input: unknown): RunEvent | null {
  if (typeof input !== "object" || input === null) return null;
  const raw = input as Raw;
  let type: RunEventType | undefined;
  let d: Raw;
  if (typeof raw.event === "string") {
    type = raw.event as RunEventType;
    d = raw;
  } else if (typeof raw.type === "string") {
    type = LEGACY[raw.type];
    d = (raw.data as Raw) ?? {};
  } else {
    return null;
  }
  // An update of an artifact is drawn the same way as its creation.
  if ((type as string) === "artifact_updated") type = "artifact_created";
  if (!type || !KNOWN.has(type)) return null;

  const base = {
    runId: str(raw.run_id),
    seq: num(raw.seq),
    ts: str(raw.ts, new Date().toISOString()),
    node: strOrNull(raw.node),
  };

  switch (type) {
    case "run_started":
      return { ...base, event: type, kind: str(d.kind, "journey") as RunKind };
    case "run_status":
      return { ...base, event: type, status: str(d.status, "running") as RunStatus, reason: strOrNull(d.reason) };
    case "run_completed":
      return { ...base, event: type, summary: strOrNull(d.summary), journeyId: strOrNull(d.journey_id) };
    case "run_failed":
    case "node_failed":
      return { ...base, event: type, code: str(d.code, "error"), message: str(d.message, "Something went wrong."), retryable: d.retryable === true };
    case "run_cancelled":
      return { ...base, event: type, reason: strOrNull(d.reason) };
    case "node_started":
      return { ...base, event: type, label: str(d.label, base.node ?? ""), attempt: num(d.attempt, 1) };
    case "node_progress":
      return { ...base, event: type, message: str(d.message), progress: numOrNull(d.progress) };
    case "node_completed":
      return { ...base, event: type, label: strOrNull(d.label), summary: strOrNull(d.summary), durationMs: num(d.duration_ms) };
    case "tool_called":
      return { ...base, event: type, callId: str(d.call_id), tool: str(d.tool), label: str(d.label, str(d.summary, str(d.tool))), args: (d.args as Record<string, unknown>) ?? null };
    case "tool_result":
      return { ...base, event: type, callId: str(d.call_id), tool: str(d.tool), summary: str(d.summary), ok: d.ok !== false };
    case "evidence_found":
      return {
        ...base,
        event: type,
        title: str(d.title, str(d.source_title)),
        url: strOrNull(d.url) ?? strOrNull(d.source_url),
        authority: strOrNull(d.authority),
        kind: str(d.kind, str(d.evidence_kind, "official_guidance")) as EvidenceKind,
      };
    case "document_generated":
      return { ...base, event: type, documentId: str(d.document_id, str(d.generated_document_id)), title: str(d.title) };
    case "approval_required":
      return { ...base, event: type, approvalId: str(d.approval_id), title: str(d.title), summary: str(d.summary) };
    case "approval_resolved":
      return { ...base, event: type, approvalId: str(d.approval_id), decision: str(d.decision, "approved") as "approved" | "rejected" | "expired" };
    case "action_prepared":
      return { ...base, event: type, actionId: str(d.action_id), title: str(d.title), kind: str(d.kind, str(d.action_type, "official_handoff")) as never };
    case "research_started":
      return {
        ...base,
        event: type,
        jobId: str(d.job_id),
        sections: Array.isArray(d.categories) ? (d.categories as string[]) : Array.isArray(d.sections) ? (d.sections as string[]) : [],
      };
    case "research_source_found":
      return { ...base, event: type, jobId: str(d.job_id), title: str(d.title), url: strOrNull(d.url) ?? strOrNull(d.source_url), section: strOrNull(d.section) ?? strOrNull(d.category) };
    case "research_category_completed":
      return {
        ...base,
        event: type,
        jobId: str(d.job_id),
        section: str(d.section, str(d.category)),
        resultCount: num(d.result_count, num(d.count)),
        status: d.status === "failed" || d.status === "skipped" ? d.status : "completed",
        reason: strOrNull(d.reason),
      };
    case "research_completed":
      return { ...base, event: type, jobId: str(d.job_id), resultCount: num(d.result_count, num(d.count)) };
    case "research_failed":
      return { ...base, event: type, jobId: str(d.job_id), message: str(d.message, "Research stopped.") };
    case "question_asked":
      return {
        ...base,
        event: type,
        questionId: str(d.question_id),
        prompt: str(d.prompt),
        options: Array.isArray(d.options) ? (d.options as { value: string; label: string }[]) : null,
        reason: strOrNull(d.reason),
      };
    case "message_delta":
      return { ...base, event: type, messageId: str(d.message_id), text: str(d.text) };
    case "artifact_created":
      return { ...base, event: type, artifactType: str(d.artifact_type), artifactId: str(d.artifact_id), title: strOrNull(d.title) };
    case "error":
      return { ...base, event: type, code: str(d.code, "error"), message: str(d.message) };
  }
}
