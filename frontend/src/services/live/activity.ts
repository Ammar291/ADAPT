/**
 * Live change feed. The backend owns every journey, document, approval, draft and research
 * job; this follows the agent event log (the same durable, gap-free per-run `seq` the SSE
 * console uses) and tells the UI *which* server state changed, as invalidation topics
 * (see `TOPIC_KEYS`). Queries then refetch from the API. Nothing is derived or kept here
 * beyond a cursor per run.
 *
 * It reads `GET /agents/runs` (every run the server holds for this user, including runs
 * the user didn't start here: research the journey agent queued, a plan started by voice
 * or on another device) and replays each run's new events with `?after=<cursor>`, so a
 * slow poll or a sleeping tab never loses an event: it only delivers it later.
 */
import type { RunKind, RunStatus } from "@/domain/runs";
import { api } from "@/lib/api/client";
import { paths } from "./paths";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type Listener = (topics: string[]) => void;

const ACTIVE_MS = 2_000;
const IDLE_MS = 6_000;
const TERMINAL = new Set<RunStatus>(["succeeded", "failed", "cancelled"]);

/** What a finished run of each kind may have changed. */
const SETTLED_TOPICS: Record<RunKind, string[]> = {
  journey: ["journeys", "approvals", "generated", "graph", "discover"],
  what_if: ["journeys"],
  research: ["discover"],
  document_extraction: ["documents", "graph", "journeys"],
  drafting: ["generated"],
  diagnostic: [],
};

/** Topics one event invalidates (events carry pointers, so the data is refetched). */
export function topicsForEvent(event: string, kind: RunKind | undefined): string[] {
  switch (event) {
    case "run_started":
    case "run_status":
      return ["runs", "approvals"];
    case "run_completed":
    case "run_failed":
    case "run_cancelled":
      return ["runs", ...(kind ? SETTLED_TOPICS[kind] : [])];
    case "approval_required":
    case "approval_resolved":
      return ["runs", "approvals", "journeys"];
    case "action_prepared":
      return ["approvals"];
    case "document_generated":
      return ["generated"];
    case "artifact_created":
    case "artifact_updated":
      return kind === "document_extraction" || kind === "journey" ? ["documents", "graph"] : [];
    case "research_started":
    case "research_category_completed":
    case "research_completed":
    case "research_failed":
      return ["discover"];
    default:
      return [];
  }
}

interface Cursor {
  seq: number;
  status: RunStatus;
  kind: RunKind;
}

export function createLiveActivity() {
  const listeners = new Set<Listener>();
  const cursors = new Map<string, Cursor>();
  let primed = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let polling: Promise<void> | null = null;
  let pokedWhilePolling = false;
  let anyActive = false;

  const emit = (topics: Set<string>) => {
    if (!topics.size) return;
    const list = [...topics];
    for (const listener of listeners) listener(list);
  };

  async function drain(id: string, cursor: Cursor, topics: Set<string>): Promise<number> {
    const page = await api.get<Raw>(paths.runEvents(id), { query: { after: cursor.seq } });
    if (typeof page.status === "string") cursor.status = page.status as RunStatus;
    let seq = cursor.seq;
    for (const event of (page.events ?? []) as Raw[]) {
      if (typeof event.seq === "number" && event.seq > seq) seq = event.seq;
      for (const topic of topicsForEvent(String(event.event), cursor.kind)) topics.add(topic);
    }
    return Math.max(seq, typeof page.last_seq === "number" ? page.last_seq : seq);
  }

  async function poll(): Promise<void> {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    // The newest runs, plus every unfinished one however old (a plan paused for approval
    // must stay followed while what-ifs and uploads create newer runs).
    const [recent, active] = await Promise.all([
      api.get<Raw[]>(paths.runs, { query: { limit: 20 } }),
      api.get<Raw[]>(paths.runs, { query: { active: true, limit: 100 } }),
    ]);
    const runs = [...new Map([...active, ...recent].map((run) => [String(run.id), run])).values()];
    const listed = new Set(runs.map((run) => String(run.id)));
    // A followed run that finished and dropped out of both lists: read its last events.
    for (const [id, cursor] of cursors) {
      if (!listed.has(id) && !TERMINAL.has(cursor.status)) {
        runs.push({ id, kind: cursor.kind, status: cursor.status, last_event_seq: Number.MAX_SAFE_INTEGER });
      }
    }
    const topics = new Set<string>();
    anyActive = false;
    for (const run of runs) {
      const id = String(run.id);
      const status = run.status as RunStatus;
      const kind = run.kind as RunKind;
      const lastSeq = Number(run.last_event_seq ?? 0);
      if (!TERMINAL.has(status)) anyActive = true;
      const known = cursors.get(id);
      if (!primed) {
        // History is already reflected by the first fetch of each screen.
        cursors.set(id, { seq: lastSeq, status, kind });
        continue;
      }
      const cursor = known ?? { seq: 0, status, kind };
      if (!known) topics.add("runs");
      const was = cursor.status;
      if (lastSeq > cursor.seq) {
        try {
          cursor.seq = await drain(id, cursor, topics);
        } catch {
          continue; // try again on the next tick; the cursor didn't move
        }
      }
      // A run in neither list (finished and dropped out) reported its status with its events.
      const now = listed.has(id) ? status : cursor.status;
      if (now !== was) topics.add("runs");
      cursor.status = now;
      cursors.set(id, cursor);
    }
    primed = true;
    emit(topics);
  }

  function schedule(delay: number) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(tick, delay);
  }

  function tick() {
    timer = null;
    if (!listeners.size) return;
    polling ??= poll()
      .catch(() => {}) // offline or signed out: the next tick tries again
      .finally(() => {
        polling = null;
        const again = pokedWhilePolling;
        pokedWhilePolling = false;
        if (listeners.size) schedule(again ? 0 : anyActive ? ACTIVE_MS : IDLE_MS);
      });
  }

  const onVisible = () => {
    if (document.visibilityState === "visible" && listeners.size && !polling) schedule(0);
  };

  return {
    subscribe(listener: Listener): () => void {
      listeners.add(listener);
      if (listeners.size === 1) {
        // A new start (e.g. signed in again): take a fresh look rather than replaying
        // whatever happened while nobody was listening.
        cursors.clear();
        primed = false;
        if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisible);
        schedule(0);
      }
      return () => {
        listeners.delete(listener);
        if (listeners.size) return;
        if (timer) clearTimeout(timer);
        timer = null;
        if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisible);
      };
    },
    /** Look now (e.g. right after starting something), instead of at the next tick. */
    poke() {
      if (!listeners.size) return;
      if (polling) pokedWhilePolling = true;
      else schedule(0);
    },
  };
}

export type LiveActivity = ReturnType<typeof createLiveActivity>;
