/**
 * In-memory agent runs. A run is a script that emits `RunEvent`s over time; subscribers get
 * the full history replayed, then live events, exactly like the backend's SSE stream with
 * `Last-Event-ID` replay. Human gates pause the script until the user decides.
 */
import type { Review } from "@/domain/documents";
import type { RunEvent, RunKind, RunStatus, RunSummary } from "@/domain/runs";
import { isTerminalRunEvent } from "@/domain/runs";
import type { RunSubscription } from "../types";
import { delay, uid } from "./util";

type Payload = RunEvent extends infer E ? (E extends RunEvent ? Omit<E, "runId" | "seq" | "ts"> : never) : never;

interface MockRun {
  summary: RunSummary;
  events: RunEvent[];
  subscribers: Set<RunSubscription>;
  review: Review | null;
  resume: (() => void) | null;
}

export interface RunContext {
  runId: string;
  emit(payload: Payload): void;
  /** Runs one stage: started → body → completed (with duration). */
  stage(id: string, label: string, body: () => Promise<string | null>): Promise<void>;
  wait(ms: number): Promise<void>;
  /** Pauses at a human gate until `resume` is called for this run. */
  pause(review: Review): Promise<void>;
  setJourney(journeyId: string): void;
}

const runs = new Map<string, MockRun>();
const order: string[] = [];

function publish(run: MockRun, event: RunEvent) {
  run.events.push(event);
  run.summary.lastSeq = event.seq;
  for (const sub of run.subscribers) {
    sub.onEvent(event);
    if (isTerminalRunEvent(event)) sub.onState("closed");
  }
}

function setStatus(run: MockRun, status: RunStatus) {
  run.summary.status = status;
  if (status === "running" && !run.summary.startedAt) run.summary.startedAt = new Date().toISOString();
  if (status === "succeeded" || status === "failed" || status === "cancelled") run.summary.finishedAt = new Date().toISOString();
}

/** Starts a scripted run. The script's return value becomes the run summary. */
export function startRun(
  kind: RunKind,
  script: (ctx: RunContext) => Promise<{ summary: string | null } | void>,
  options: { journeyId?: string | null; instant?: boolean } = {},
): string {
  const runId = uid("run");
  const run: MockRun = {
    summary: {
      id: runId,
      kind,
      status: "queued",
      journeyId: options.journeyId ?? null,
      lastSeq: 0,
      createdAt: new Date().toISOString(),
      startedAt: null,
      finishedAt: null,
    },
    events: [],
    subscribers: new Set(),
    review: null,
    resume: null,
  };
  runs.set(runId, run);
  order.unshift(runId);
  let seq = 0;
  const instant = options.instant ?? false;

  const ctx: RunContext = {
    runId,
    emit(payload) {
      // A cancelled run stops at its next emit.
      if (run.summary.status === "cancelled") throw new Error("Run cancelled");
      seq = run.summary.lastSeq + 1;
      const event = { ...payload, runId, seq, ts: new Date().toISOString() } as RunEvent;
      if (event.event === "run_started" || (event.event === "run_status" && event.status === "running")) setStatus(run, "running");
      if (event.event === "run_status") setStatus(run, event.status);
      if (event.event === "run_completed") setStatus(run, "succeeded");
      if (event.event === "run_failed") setStatus(run, "failed");
      if (event.event === "run_cancelled") setStatus(run, "cancelled");
      publish(run, event);
    },
    async stage(id, label, body) {
      const started = performance.now();
      ctx.emit({ event: "node_started", node: id, label, attempt: 1 });
      const summary = await body();
      ctx.emit({
        event: "node_completed",
        node: id,
        summary,
        durationMs: Math.round(performance.now() - started),
      });
    },
    wait: (ms) => (instant ? Promise.resolve() : delay(ms)),
    pause(review) {
      run.review = review;
      ctx.emit({ event: "run_status", node: null, status: "awaiting_input", reason: "Waiting for your review" });
      return new Promise<void>((resolve) => {
        run.resume = () => {
          run.review = null;
          run.resume = null;
          ctx.emit({ event: "run_status", node: null, status: "running", reason: "Resumed after your review" });
          resolve();
        };
      });
    },
    setJourney(journeyId) {
      run.summary.journeyId = journeyId;
    },
  };

  void (async () => {
    await Promise.resolve();
    ctx.emit({ event: "run_started", node: null, kind });
    try {
      const result = await script(ctx);
      ctx.emit({ event: "run_completed", node: null, summary: result?.summary ?? null, journeyId: run.summary.journeyId });
    } catch (error) {
      if (run.summary.status === "cancelled") return;
      ctx.emit({
        event: "run_failed",
        node: null,
        code: "mock_failure",
        message: error instanceof Error ? error.message : "The run stopped unexpectedly.",
        retryable: true,
      });
    }
  })();

  return runId;
}

export function getRun(runId: string): RunSummary | null {
  const run = runs.get(runId);
  return run ? { ...run.summary } : null;
}

export function recentRuns(): RunSummary[] {
  return order.map((id) => ({ ...runs.get(id)!.summary }));
}

export function subscribeRun(runId: string, subscription: RunSubscription): () => void {
  const run = runs.get(runId);
  if (!run) {
    queueMicrotask(() => subscription.onState("closed"));
    return () => undefined;
  }
  subscription.onState("connecting");
  let active = true;
  queueMicrotask(() => {
    if (!active) return;
    subscription.onState("open");
    for (const event of run.events) subscription.onEvent(event);
    if (run.events.some(isTerminalRunEvent)) {
      subscription.onState("closed");
      return;
    }
    run.subscribers.add(subscription);
  });
  return () => {
    active = false;
    run.subscribers.delete(subscription);
  };
}

export function reviewOf(runId: string): Review | null {
  return runs.get(runId)?.review ?? null;
}

export function resumeRun(runId: string): boolean {
  const run = runs.get(runId);
  if (!run?.resume) return false;
  run.resume();
  return true;
}

export function cancelRun(runId: string): RunSummary | null {
  const run = runs.get(runId);
  if (!run) return null;
  if (run.summary.status === "succeeded" || run.summary.status === "failed" || run.summary.status === "cancelled") {
    return { ...run.summary };
  }
  setStatus(run, "cancelled");
  const seq = run.summary.lastSeq + 1;
  publish(run, { event: "run_cancelled", node: null, reason: "Cancelled by you", runId, seq, ts: new Date().toISOString() });
  run.resume = null;
  return { ...run.summary };
}

export function isRunActive(runId: string): boolean {
  const status = runs.get(runId)?.summary.status;
  return status === "queued" || status === "running" || status === "awaiting_input";
}

/** Test helper: forget all runs. */
export function resetRuns(): void {
  runs.clear();
  order.length = 0;
}
