/**
 * Pure reducer that folds a run's events into a view model for live agent UIs (execution
 * console, building state, approvals). Idempotent: replayed events (seq <= lastSeq) are
 * ignored, so reconnects with `Last-Event-ID` are safe.
 */
import type { EvidenceKind } from "@/domain/common";
import type { QuestionOption, RunEvent, RunStatus } from "@/domain/runs";

/** Display status of a stage in the execution console. */
export type StageStatus = "queued" | "running" | "complete" | "blocked" | "awaiting" | "failed";

export interface ToolCallView {
  callId: string;
  tool: string;
  label: string;
  args: Record<string, unknown> | null;
  status: "running" | "done" | "failed";
  summary: string | null;
  startedAt: string;
}

export interface StageView {
  id: string;
  label: string;
  status: StageStatus;
  progress: number | null;
  message: string | null;
  summary: string | null;
  durationMs: number | null;
  attempt: number;
  startedAt: string | null;
  updatedAt: string;
  tools: ToolCallView[];
}

export interface EvidenceView {
  node: string | null;
  title: string;
  url: string | null;
  authority: string | null;
  kind: EvidenceKind;
}

export interface RunView {
  runId: string | null;
  status: RunStatus | "unknown";
  lastSeq: number;
  /** Stage ids in first-seen order. */
  order: string[];
  stages: Record<string, StageView>;
  evidence: EvidenceView[];
  documents: { id: string; title: string }[];
  actions: { id: string; title: string; kind: string }[];
  artifacts: { type: string; id: string; title: string | null }[];
  pendingApprovals: { approvalId: string; title: string; summary: string; node: string | null }[];
  pendingQuestions: { questionId: string; prompt: string; options: QuestionOption[] | null; reason: string | null }[];
  research: { jobId: string; state: "running" | "completed" | "failed"; sections: string[]; completed: string[]; results: number } | null;
  journeyId: string | null;
  summary: string | null;
  error: { code: string; message: string } | null;
  startedAt: string | null;
  finishedAt: string | null;
  /** Recent events, newest last (bounded). */
  log: RunEvent[];
}

export const LOG_LIMIT = 300;

export function initialRunView(runId: string | null = null): RunView {
  return {
    runId,
    status: "unknown",
    lastSeq: 0,
    order: [],
    stages: {},
    evidence: [],
    documents: [],
    actions: [],
    artifacts: [],
    pendingApprovals: [],
    pendingQuestions: [],
    research: null,
    journeyId: null,
    summary: null,
    error: null,
    startedAt: null,
    finishedAt: null,
    log: [],
  };
}

function upsertStage(state: RunView, id: string, ts: string, patch: (stage: StageView) => Partial<StageView>): RunView {
  const existing: StageView = state.stages[id] ?? {
    id,
    label: id,
    status: "queued",
    progress: null,
    message: null,
    summary: null,
    durationMs: null,
    attempt: 1,
    startedAt: null,
    updatedAt: ts,
    tools: [],
  };
  const stage = { ...existing, ...patch(existing), updatedAt: ts };
  return {
    ...state,
    order: state.stages[id] ? state.order : [...state.order, id],
    stages: { ...state.stages, [id]: stage },
  };
}

export function reduceRunEvent(state: RunView, event: RunEvent): RunView {
  if (event.seq <= state.lastSeq) return state;
  const next: RunView = { ...state, runId: event.runId, lastSeq: event.seq, log: [...state.log, event].slice(-LOG_LIMIT) };
  const node = event.node;

  switch (event.event) {
    case "run_started":
      return { ...next, status: "running", startedAt: event.ts };
    case "run_status": {
      const resumed = event.status === "running";
      let view: RunView = { ...next, status: event.status };
      if (resumed) {
        view = { ...view, pendingQuestions: [] };
        for (const id of view.order) {
          if (view.stages[id]!.status === "awaiting") view = upsertStage(view, id, event.ts, () => ({ status: "running" }));
        }
      }
      return view;
    }
    case "run_completed":
      return { ...next, status: "succeeded", summary: event.summary, journeyId: event.journeyId ?? next.journeyId, finishedAt: event.ts, pendingApprovals: [], pendingQuestions: [] };
    case "run_failed":
      return { ...next, status: "failed", error: { code: event.code, message: event.message }, finishedAt: event.ts };
    case "run_cancelled":
      return { ...next, status: "cancelled", finishedAt: event.ts };
    case "node_started":
      return node
        ? upsertStage(next, node, event.ts, () => ({ label: event.label, status: "running", attempt: event.attempt, progress: null, message: null, startedAt: event.ts }))
        : next;
    case "node_progress":
      return node ? upsertStage(next, node, event.ts, () => ({ status: "running", message: event.message, progress: event.progress })) : next;
    case "node_completed":
      return node ? upsertStage(next, node, event.ts, () => ({ status: "complete", progress: 1, summary: event.summary, durationMs: event.durationMs })) : next;
    case "node_failed":
      return node ? upsertStage(next, node, event.ts, () => ({ status: "failed", message: event.message })) : next;
    case "error":
      return node ? upsertStage(next, node, event.ts, () => ({ status: "failed", message: event.message })) : { ...next, error: { code: event.code, message: event.message } };
    case "tool_called":
      return node
        ? upsertStage(next, node, event.ts, (stage) => ({
            tools: [...stage.tools, { callId: event.callId, tool: event.tool, label: event.label, args: event.args, status: "running", summary: null, startedAt: event.ts }],
          }))
        : next;
    case "tool_result":
      return node
        ? upsertStage(next, node, event.ts, (stage) => ({
            tools: stage.tools.map((t) => (t.callId === event.callId ? { ...t, status: event.ok ? "done" : "failed", summary: event.summary } : t)),
          }))
        : next;
    case "evidence_found":
      return { ...next, evidence: [...next.evidence, { node, title: event.title, url: event.url, authority: event.authority, kind: event.kind }] };
    case "document_generated":
      return next.documents.some((d) => d.id === event.documentId) ? next : { ...next, documents: [...next.documents, { id: event.documentId, title: event.title }] };
    case "action_prepared":
      return next.actions.some((a) => a.id === event.actionId) ? next : { ...next, actions: [...next.actions, { id: event.actionId, title: event.title, kind: event.kind }] };
    case "artifact_created": {
      const others = next.artifacts.filter((a) => a.id !== event.artifactId);
      return {
        ...next,
        artifacts: [...others, { type: event.artifactType, id: event.artifactId, title: event.title }],
        journeyId: event.artifactType === "journey" ? event.artifactId : next.journeyId,
      };
    }
    case "approval_required": {
      const view = { ...next, pendingApprovals: [...next.pendingApprovals.filter((a) => a.approvalId !== event.approvalId), { approvalId: event.approvalId, title: event.title, summary: event.summary, node }] };
      return node ? upsertStage(view, node, event.ts, () => ({ status: "awaiting" })) : view;
    }
    case "approval_resolved":
      return { ...next, pendingApprovals: next.pendingApprovals.filter((a) => a.approvalId !== event.approvalId) };
    case "question_asked": {
      const view = { ...next, pendingQuestions: [...next.pendingQuestions, { questionId: event.questionId, prompt: event.prompt, options: event.options, reason: event.reason }] };
      return node ? upsertStage(view, node, event.ts, () => ({ status: "awaiting" })) : view;
    }
    case "research_started":
      return { ...next, research: { jobId: event.jobId, state: "running", sections: event.sections, completed: [], results: 0 } };
    case "research_category_completed":
      return next.research
        ? { ...next, research: { ...next.research, completed: [...next.research.completed, event.section], results: next.research.results + event.resultCount } }
        : next;
    case "research_completed":
      return next.research ? { ...next, research: { ...next.research, state: "completed", results: event.resultCount } } : next;
    case "research_failed":
      return next.research ? { ...next, research: { ...next.research, state: "failed" } } : next;
    case "research_source_found":
    case "message_delta":
      return next;
    default: {
      // Exhaustiveness guard: a new event type must be handled here.
      const unhandled: never = event;
      void unhandled;
      return next;
    }
  }
}

export function reduceRunEvents(events: RunEvent[], initial = initialRunView()): RunView {
  return events.reduce(reduceRunEvent, initial);
}

/**
 * Status of every stage in a workflow, including ones the run hasn't reached: `queued`
 * normally, `blocked` when the run failed or was cancelled before reaching them.
 */
export function stageStatuses(view: RunView, stageIds: string[]): Record<string, StageStatus> {
  const halted = view.status === "failed" || view.status === "cancelled";
  const result: Record<string, StageStatus> = {};
  for (const id of stageIds) {
    const stage = view.stages[id];
    // A stage interrupted by a failure failed; one interrupted by a cancel simply stopped.
    const interrupted = view.status === "failed" ? "failed" : "blocked";
    result[id] = stage ? (halted && (stage.status === "running" || stage.status === "awaiting") ? interrupted : stage.status) : halted ? "blocked" : "queued";
  }
  return result;
}
