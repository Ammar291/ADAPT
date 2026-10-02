import type { ActionKind, EvidenceKind } from "./common";

/** The backend's `RunKind` (one run per journey plan, what-if, research job, document reading…). */
export type RunKind = "journey" | "what_if" | "research" | "document_extraction" | "drafting" | "diagnostic";
export type RunStatus = "queued" | "running" | "awaiting_input" | "succeeded" | "failed" | "cancelled";

export interface RunSummary {
  id: string;
  kind: RunKind;
  status: RunStatus;
  journeyId: string | null;
  lastSeq: number;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

/** Stage of an agent workflow, as drawn in the execution console. */
export interface AgentStage {
  id: string;
  label: string;
  description: string;
  kind: "agent" | "tool" | "human";
  /** Parallel branch index; stages with the same column but different lanes run side by side. */
  lane: number;
}

export interface AgentWorkflow {
  id: string;
  version: string;
  stages: AgentStage[];
  edges: { source: string; target: string; condition: string | null }[];
}

export interface QuestionOption {
  value: string;
  label: string;
}

interface Envelope {
  runId: string;
  /** Gap-free and strictly increasing per run. */
  seq: number;
  ts: string;
  /** Emitting stage, or null for run-level events. */
  node: string | null;
}

/**
 * Normalised agent progress events. Live adapters translate the backend wire format (SSE)
 * into this union; mock runs emit it directly. Events carry pointers, not private payloads.
 */
export type RunEvent = Envelope &
  (
    | { event: "run_started"; kind: RunKind }
    | { event: "run_status"; status: RunStatus; reason: string | null }
    | { event: "run_completed"; summary: string | null; journeyId: string | null }
    | { event: "run_failed"; code: string; message: string; retryable: boolean }
    | { event: "run_cancelled"; reason: string | null }
    | { event: "node_started"; label: string; attempt: number }
    | { event: "node_progress"; message: string; progress: number | null }
    | { event: "node_completed"; label?: string | null; summary: string | null; durationMs: number }
    | { event: "node_failed"; code: string; message: string; retryable: boolean }
    | { event: "tool_called"; callId: string; tool: string; label: string; args: Record<string, unknown> | null }
    | { event: "tool_result"; callId: string; tool: string; summary: string; ok: boolean }
    | { event: "evidence_found"; title: string; url: string | null; authority: string | null; kind: EvidenceKind }
    | { event: "document_generated"; documentId: string; title: string }
    | { event: "approval_required"; approvalId: string; title: string; summary: string }
    | { event: "approval_resolved"; approvalId: string; decision: "approved" | "rejected" | "expired" }
    | { event: "action_prepared"; actionId: string; title: string; kind: ActionKind }
    | { event: "research_started"; jobId: string; sections: string[] }
    | { event: "research_source_found"; jobId: string; title: string; url: string | null; section: string | null }
    | { event: "research_category_completed"; jobId: string; section: string; resultCount: number; status?: "completed" | "failed" | "skipped"; reason?: string | null }
    | { event: "research_completed"; jobId: string; resultCount: number }
    | { event: "research_failed"; jobId: string; message: string }
    | { event: "question_asked"; questionId: string; prompt: string; options: QuestionOption[] | null; reason: string | null }
    | { event: "message_delta"; messageId: string; text: string }
    | { event: "artifact_created"; artifactType: string; artifactId: string; title: string | null }
    | { event: "error"; code: string; message: string }
  );

export type RunEventType = RunEvent["event"];

export type RunEventOf<T extends RunEventType> = Extract<RunEvent, { event: T }>;

export const TERMINAL_RUN_EVENTS: RunEventType[] = ["run_completed", "run_failed", "run_cancelled"];

export function isTerminalRunEvent(event: RunEvent): boolean {
  return TERMINAL_RUN_EVENTS.includes(event.event);
}

export type StreamState = "idle" | "connecting" | "open" | "reconnecting" | "closed";
