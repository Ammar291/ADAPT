import { tr } from "@/i18n";
/**
 * Pure run-state helpers for the execution console: which run to show, how far execution
 * has travelled along each edge, and run-level labels.
 */
import type { AgentWorkflow, RunKind, RunStatus, RunSummary, StreamState } from "@/domain/runs";
import type { RunView, StageStatus, StageView } from "@/lib/events/runEvents";

// --- which run --------------------------------------------------------------------------------

/** The run named in the URL, else the newest one. */
export function pickRunId(requested: string | null, recent: RunSummary[] | undefined): string | null {
  if (requested) return requested;
  return recent?.[0]?.id ?? null;
}

export const ACTIVE_RUN_STATUSES: RunStatus[] = ["queued", "running", "awaiting_input"];

export function isActiveStatus(status: RunStatus | "unknown"): boolean {
  return status !== "unknown" && ACTIVE_RUN_STATUSES.includes(status);
}

// --- labels -----------------------------------------------------------------------------------

export const RUN_KIND_LABEL: Record<RunKind, string> = {
  journey: tr("copy.journey_plan_4d7b762", { lng: "en" }),
  what_if: tr("copy.what_if_simulation_8f75344", { lng: "en" }),
  research: tr("copy.community_research_0911f6e", { lng: "en" }),
  document_extraction: tr("copy.document_reading_f4dfed4", { lng: "en" }),
  drafting: tr("copy.drafting_48180fd", { lng: "en" }),
  diagnostic: tr("copy.system_check_b46eb13", { lng: "en" }),
};

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  queued: tr("copy.queued_6a59987", { lng: "en" }),
  running: tr("copy.running_73989d9", { lng: "en" }),
  awaiting_input: tr("copy.needs_you_0d9d0df", { lng: "en" }),
  succeeded: tr("copy.finished_355bcc5", { lng: "en" }),
  failed: tr("copy.failed_09fef5d", { lng: "en" }),
  cancelled: tr("copy.cancelled_a1bf92e", { lng: "en" }),
};

/** The console's headline for a run: what is happening, in plain words. */
export function runHeadline(kind: RunKind, status: RunStatus | "unknown"): string {
  if (status === "awaiting_input") return tr("copy.waiting_for_your_approval_5095847");
  if (status === "failed") return tr("copy.this_run_stopped_before_it_finished_b9c404f");
  if (status === "cancelled") return tr("copy.you_stopped_this_run_d2afaf4");
  const done = status === "succeeded";
  switch (kind) {
    case "journey":
      return done ? tr("copy.your_plan_is_ready_3028217") : tr("copy.adapt_is_building_your_plan_ff4e27f");
    case "what_if":
      return done ? tr("copy.your_what_if_is_ready_to_compare_9bfbbdd") : tr("copy.adapt_is_testing_your_what_if_86cd344");
    case "diagnostic":
      return done ? tr("copy.every_part_of_adapt_responded_ee81e3f") : tr("copy.checking_every_part_of_adapt_c29218b");
    case "research":
      return done ? tr("copy.community_research_is_done_b8e83d9") : tr("copy.researching_life_in_abu_dhabi_90cedaf");
    case "document_extraction":
      return done ? tr("copy.your_document_is_read_e1c76fc") : tr("copy.reading_your_document_b5f3b17");
    case "drafting":
      return done ? tr("copy.your_draft_is_ready_96df6f0") : tr("copy.drafting_for_you_193159d");
  }
}

/**
 * A summary without the words the headline already says: "Your plan is ready: 29 steps"
 * under "Your plan is ready" becomes "29 steps".
 */
export function trimLead(summary: string | null, headline: string): string | null {
  if (!summary) return null;
  const lead = headline.replace(/[.!]$/, "");
  if (!summary.toLowerCase().startsWith(lead.toLowerCase())) return summary;
  const rest = summary.slice(lead.length).replace(/^[\s:,.;-]+/, "");
  return rest ? rest.charAt(0).toUpperCase() + rest.slice(1) : summary;
}

export const STREAM_LABEL: Record<StreamState, string> = {
  idle: tr("copy.not_connected_8b02f3d", { lng: "en" }),
  connecting: tr("copy.connecting_c1f3b71", { lng: "en" }),
  open: tr("copy.live_65c821a", { lng: "en" }),
  reconnecting: tr("copy.reconnecting_9d80f91", { lng: "en" }),
  closed: tr("copy.closed_88d86b7", { lng: "en" }),
};

// --- time -------------------------------------------------------------------------------------

export function elapsedMs(startedAt: string | null, finishedAt: string | null, now: number): number | null {
  if (!startedAt) return null;
  const start = Date.parse(startedAt);
  const end = finishedAt ? Date.parse(finishedAt) : now;
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.max(0, end - start);
}

/** "0:07", "2:05", "1:02:09". */
export function formatClock(ms: number): string {
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

// --- progress ------------------------------------------------------------------------------------

export function stageProgress(statuses: Record<string, StageStatus>): { complete: number; total: number; ratio: number } {
  const values = Object.values(statuses);
  const complete = values.filter((s) => s === "complete").length;
  return { complete, total: values.length, ratio: values.length ? complete / values.length : 0 };
}

/** The stage to keep in view: the latest running or waiting one, else the last one touched. */
export function focusStage(view: RunView, statuses: Record<string, StageStatus>): string | null {
  const touched = view.order.filter((id) => id in statuses);
  const live = [...touched].reverse().find((id) => statuses[id] === "awaiting" || statuses[id] === "running");
  return live ?? touched[touched.length - 1] ?? null;
}

// --- edges ----------------------------------------------------------------------------------------

export type EdgeState = "idle" | "active" | "done" | "skipped";

const STARTED: StageStatus[] = ["running", "awaiting", "complete", "failed"];

/**
 * For conditional edges (e.g. "approved" / "rejected" after the approval gate), the branch
 * the run took: from the recorded decision when there is one, else the branch whose target
 * started first.
 */
export function takenBranches(workflow: AgentWorkflow, view: RunView, statuses: Record<string, StageStatus>): Set<string> {
  const taken = new Set<string>();
  const bySource = new Map<string, AgentWorkflow["edges"]>();
  for (const edge of workflow.edges) {
    if (!edge.condition) continue;
    bySource.set(edge.source, [...(bySource.get(edge.source) ?? []), edge]);
  }
  for (const [source, edges] of bySource) {
    const decisions = view.log.flatMap((e) => (e.event === "approval_resolved" && e.node === source ? [e.decision] : []));
    let branch: string | null = null;
    if (decisions.length) branch = decisions.includes("approved") ? "approved" : "rejected";
    let edge = branch ? edges.find((e) => e.condition === branch) : undefined;
    if (!edge) {
      const started = edges
        .filter((e) => STARTED.includes(statuses[e.target] ?? "queued"))
        .sort((a, b) => (view.stages[a.target]?.startedAt ?? "").localeCompare(view.stages[b.target]?.startedAt ?? ""));
      // Without a recorded decision, the branch that runs straight on is the one taken.
      edge = statuses[source] === "complete" ? started[0] : undefined;
    }
    if (edge) taken.add(`${edge.source}->${edge.target}`);
  }
  return taken;
}

export function edgeState(
  edge: { source: string; target: string; condition: string | null },
  statuses: Record<string, StageStatus>,
  taken: Set<string>,
): EdgeState {
  const source = statuses[edge.source] ?? "queued";
  const target = statuses[edge.target] ?? "queued";
  if (source !== "complete") return "idle";
  if (edge.condition && !taken.has(`${edge.source}->${edge.target}`)) {
    const siblingTaken = [...taken].some((id) => id.startsWith(`${edge.source}->`));
    return siblingTaken ? "skipped" : "idle";
  }
  if (target === "complete" || target === "failed") return "done";
  if (target === "running" || target === "awaiting") return "active";
  if (target === "blocked") return "idle";
  return "active"; // the source just finished; the next stage is about to start
}

/** Plain label for a conditional edge. */
export function conditionLabel(condition: string): string {
  switch (condition) {
    case "approved":
      return tr("copy.if_you_approve_d16f339");
    case "rejected":
      return tr("copy.if_you_decline_ccaf6f8");
    default:
      return tr("copy.if_v0_034bdc2", { v0: condition.replace(/_/g, " ") });
  }
}

// --- stage text ---------------------------------------------------------------------------------

/**
 * The one line under a stage's name: what it is doing right now while it runs, its result
 * once complete, and what the user should know otherwise.
 */
export function stageLine(status: StageStatus, stage: StageView | undefined, description: string, runStatus?: RunStatus | "unknown"): string {
  switch (status) {
    case "running": {
      const tool = stage ? [...stage.tools].reverse().find((t) => t.status === "running") : undefined;
      return tool?.label ?? stage?.message ?? tr("copy.working_on_it_9f56551");
    }
    case "awaiting":
      return tr("copy.paused_until_you_decide_c03247f");
    case "complete":
      return stage?.summary ?? tr("copy.done_e9b450d");
    case "failed":
      // A stage still running when the run halted shows as failed; say why rather than its last progress note.
      if (stage?.status !== "failed") return runStatus === "cancelled" ? tr("copy.stopped_when_the_run_was_cancelled_74a898f") : tr("copy.stopped_when_the_run_failed_ff82425");
      return stage.message ?? tr("copy.stopped_with_an_error_31219bf");
    case "blocked":
      return runStatus === "cancelled" ? tr("copy.not_reached_the_run_was_cancelled_b9c8cfe") : tr("copy.not_reached_the_run_stopped_earlier_cd74ca8");
    case "queued":
      return description;
  }
}
