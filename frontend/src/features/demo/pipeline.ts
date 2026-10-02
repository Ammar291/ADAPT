import { tr } from "@/i18n";
/**
 * A document's reading run, as the four stages the audience follows:
 * uploaded, analyzed, facts extracted, user graph updated. Built only from the run's real
 * events (classify, extract, validate, structure, update_twin), never from a timer.
 */
import type { DocumentStage } from "@/domain/scenario";
import { DOCUMENT_STAGES } from "@/domain/scenario";
import type { RunEvent } from "@/domain/runs";

export interface StageState {
  stage: DocumentStage;
  label: string;
  done: boolean;
  /** What the stage found, in the reader's own words (e.g. "6 fields read"). */
  detail: string | null;
  durationMs: number | null;
}

export interface PipelineState {
  stages: StageState[];
  finished: boolean;
  failed: string | null;
}

function completed(events: RunEvent[], node: string): Extract<RunEvent, { event: "node_completed" }> | undefined {
  return events.find((e): e is Extract<RunEvent, { event: "node_completed" }> => e.event === "node_completed" && e.node === node);
}

function join(...parts: (string | null | undefined)[]): string | null {
  const kept = parts.filter((p): p is string => Boolean(p && p.trim()));
  return kept.length ? kept.join(". ") : null;
}

function sum(...values: (number | null | undefined)[]): number | null {
  const kept = values.filter((v): v is number => typeof v === "number");
  return kept.length ? kept.reduce((a, b) => a + b, 0) : null;
}

export function pipelineFromEvents(events: RunEvent[], upload: { uploaded: boolean; detail?: string | null }): PipelineState {
  const classify = completed(events, "classify");
  const extract = completed(events, "extract");
  const validate = completed(events, "validate");
  const structure = completed(events, "structure");
  const twin = completed(events, "update_twin");
  const byStage: Record<DocumentStage, Omit<StageState, "stage" | "label">> = {
    uploaded: { done: upload.uploaded, detail: upload.detail ?? null, durationMs: null },
    analyzed: {
      done: Boolean(extract),
      detail: join(classify?.summary, extract?.summary),
      durationMs: sum(classify?.durationMs, extract?.durationMs),
    },
    facts: {
      done: Boolean(structure),
      detail: join(validate?.summary, structure?.summary),
      durationMs: sum(validate?.durationMs, structure?.durationMs),
    },
    twin: { done: Boolean(twin), detail: twin?.summary ?? null, durationMs: twin?.durationMs ?? null },
  };
  const failed = events.find((e) => e.event === "run_failed");
  return {
    stages: DOCUMENT_STAGES.map(({ stage, label }) => ({ stage, label, ...byStage[stage] })),
    finished: events.some((e) => e.event === "run_completed"),
    failed: failed && failed.event === "run_failed" ? failed.message : null,
  };
}

/** How many stages to show as done: stages light up in order, never out of sequence. */
export function doneCount(state: PipelineState): number {
  const index = state.stages.findIndex((s) => !s.done);
  return index === -1 ? state.stages.length : index;
}

/** "local:pdf-text" -> words a person understands. */
export function describeMethod(method: string | null | undefined, mrzVerified?: boolean | null): string {
  if (!method) return tr("copy.read_by_adapt_ef260be");
  const base = method.startsWith("local:pdf-text")
    ? tr("copy.read_from_the_pdf_s_text_layer_on_adapt_s_server_be13ef9")
    : method.startsWith("openai:")
      ? `Read by a vision model (${method.slice("openai:".length).split("+")[0]})`
      : `Read with ${method}`;
  return mrzVerified ? `${base}. Machine-readable lines verified by their check digits` : base;
}
