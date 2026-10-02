import { tr } from "@/i18n";
/**
 * Pure formatting of run events into the console's human-readable activity log, plus
 * per-stage activity (sources, drafts, actions) pulled from the event history.
 */
import type { EvidenceKind } from "@/domain/common";
import { ACTION_KIND_LABEL, type ActionKind } from "@/domain/common";
import type { RunEvent } from "@/domain/runs";
import type { RunView } from "@/lib/events/runEvents";

export type LogCategory = "run" | "stage" | "tool" | "evidence" | "approval" | "output";
export type LogTone = "neutral" | "success" | "attention" | "danger";
export type LogFilter = "all" | "tools" | "evidence" | "approvals";

export interface LogEntry {
  seq: number;
  ts: string;
  stage: string | null;
  stageLabel: string | null;
  category: LogCategory;
  tone: LogTone;
  text: string;
  detail: string | null;
}

export const LOG_FILTERS: { id: LogFilter; label: string }[] = [
  { id: "all", label: tr("copy.all_6a72085", { lng: "en" }) },
  { id: "tools", label: tr("copy.tools_4fa8cc8", { lng: "en" }) },
  { id: "evidence", label: tr("copy.evidence_7ea014d", { lng: "en" }) },
  { id: "approvals", label: tr("copy.approvals_deb9d03", { lng: "en" }) },
];

const FILTER_CATEGORY: Record<Exclude<LogFilter, "all">, LogCategory> = {
  tools: "tool",
  evidence: "evidence",
  approvals: "approval",
};

const RUN_STATUS_TEXT: Record<string, string> = {
  queued: tr("copy.queued_6a59987", { lng: "en" }),
  running: tr("copy.running_again_00a1753", { lng: "en" }),
  awaiting_input: tr("copy.paused_for_your_review_295fb52", { lng: "en" }),
  succeeded: tr("copy.finished_355bcc5", { lng: "en" }),
  failed: tr("copy.stopped_51e9111", { lng: "en" }),
  cancelled: tr("copy.cancelled_a1bf92e", { lng: "en" }),
};

/** "scope: governance, channel: text". Long values are shortened; nested values summarised. */
export function formatArgs(args: Record<string, unknown> | null, max = 80): string | null {
  if (!args) return null;
  const parts = Object.entries(args).map(([key, value]) => {
    let text: string;
    if (value === null || value === undefined) text = "none";
    else if (typeof value === "string") text = value;
    else if (typeof value === "number" || typeof value === "boolean") text = String(value);
    else if (Array.isArray(value)) text = `${value.length} ${value.length === 1 ? "item" : "items"}`;
    else text = "details";
    return `${key.replace(/_/g, " ")}: ${text}`;
  });
  if (!parts.length) return null;
  const joined = parts.join(", ");
  return joined.length > max ? `${joined.slice(0, max - 1).trimEnd()}…` : joined;
}

function percent(progress: number | null): string | null {
  return progress === null ? null : `${Math.round(Math.max(0, Math.min(1, progress)) * 100)}%`;
}

function seconds(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/**
 * One event as one readable line. Returns null for events that would only add noise
 * (streamed message fragments).
 */
export function describeEvent(event: RunEvent, labelOf: (stageId: string) => string): LogEntry | null {
  const stage = event.node;
  const base = { seq: event.seq, ts: event.ts, stage, stageLabel: stage ? labelOf(stage) : null };
  const entry = (category: LogCategory, text: string, detail: string | null = null, tone: LogTone = "neutral"): LogEntry => ({
    ...base,
    category,
    tone,
    text,
    detail,
  });
  const name = stage ? labelOf(stage) : tr("copy.step_dc416e1");

  switch (event.event) {
    case "run_started":
      return entry("run", tr("copy.run_started_7d78258"));
    case "run_status":
      return entry(
        event.status === "awaiting_input" ? "approval" : "run",
        RUN_STATUS_TEXT[event.status] ?? event.status,
        event.reason,
        event.status === "awaiting_input" ? "attention" : "neutral",
      );
    case "run_completed":
      return entry("run", tr("copy.run_finished_94ae431"), event.summary, "success");
    case "run_failed":
      return entry("run", tr("copy.run_stopped_02f68b6"), event.message, "danger");
    case "run_cancelled":
      return entry("run", tr("copy.run_cancelled_d35c8b3"), event.reason);
    case "node_started":
      return entry("stage", event.attempt > 1 ? `Started ${event.label} (attempt ${event.attempt})` : `Started ${event.label}`);
    case "node_progress":
      return entry("stage", event.message, percent(event.progress));
    case "node_completed":
      return entry("stage", `Finished ${name} in ${seconds(event.durationMs)}`, event.summary, "success");
    case "node_failed":
      return entry("stage", `${name} failed`, event.message, "danger");
    case "tool_called":
      return entry("tool", event.label, formatArgs(event.args) ? `${event.tool} (${formatArgs(event.args)})` : event.tool);
    case "tool_result":
      return entry("tool", event.ok ? event.summary : `${event.tool} failed`, event.ok ? event.tool : event.summary, event.ok ? "neutral" : "danger");
    case "evidence_found":
      return entry("evidence", `Found source: ${event.title}`, event.authority);
    case "document_generated":
      return entry("output", `Drafted ${event.title}`, tr("copy.ready_for_your_review_034acd7"));
    case "approval_required":
      return entry("approval", `Needs your approval: ${event.title}`, event.summary, "attention");
    case "approval_resolved":
      return entry(
        "approval",
        event.decision === "approved" ? tr("copy.you_approved_it_3fec467") : event.decision === "rejected" ? tr("copy.you_declined_it_58d3899") : tr("copy.the_approval_expired_65c5422"),
        null,
        event.decision === "approved" ? "success" : "neutral",
      );
    case "action_prepared":
      return entry("output", `Prepared ${event.title}`, ACTION_KIND_LABEL[event.kind as ActionKind] ?? null);
    case "research_started":
      return entry("stage", tr("copy.started_community_research_bc24a8c"), `${event.sections.length} topics, in the background`);
    case "research_source_found":
      return entry("evidence", `Found: ${event.title}`, event.section);
    case "research_category_completed":
      return (event.status ?? "completed") === "completed"
        ? entry("stage", `Researched ${event.section.replace(/_/g, " ")}`, `${event.resultCount} results`)
        : entry("stage", `${event.status === "failed" ? tr("copy.couldn_t_research_babef1f") : tr("copy.skipped_5a000ad")} ${event.section.replace(/_/g, " ")}`, event.reason ?? null, event.status === "failed" ? "danger" : undefined);
    case "research_completed":
      return entry("stage", tr("copy.community_research_finished_139daf8"), `${event.resultCount} results`, "success");
    case "research_failed":
      return entry("stage", tr("copy.community_research_stopped_d61f2b3"), event.message, "danger");
    case "question_asked":
      return entry("approval", `Question for you: ${event.prompt}`, event.reason, "attention");
    case "artifact_created":
      return entry("output", `Created ${event.title ?? event.artifactType.replace(/_/g, " ")}`);
    case "error":
      return entry(stage ? "stage" : "run", tr("copy.something_went_wrong_8d886c0"), event.message, "danger");
    case "message_delta":
      return null;
  }
}

export function buildLog(events: RunEvent[], labelOf: (stageId: string) => string): LogEntry[] {
  return events.flatMap((e) => {
    const entry = describeEvent(e, labelOf);
    return entry ? [entry] : [];
  });
}

export function filterLog(entries: LogEntry[], filter: LogFilter): LogEntry[] {
  if (filter === "all") return entries;
  const category = FILTER_CATEGORY[filter];
  return entries.filter((e) => e.category === category);
}

export function countByFilter(entries: LogEntry[]): Record<LogFilter, number> {
  return {
    all: entries.length,
    tools: entries.filter((e) => e.category === "tool").length,
    evidence: entries.filter((e) => e.category === "evidence").length,
    approvals: entries.filter((e) => e.category === "approval").length,
  };
}

// --- evidence and outputs ----------------------------------------------------------------------

export interface SourceItem {
  key: string;
  stage: string | null;
  title: string;
  url: string | null;
  authority: string | null;
  kind: EvidenceKind;
  /** When the agent retrieved it; null if the event has scrolled out of the history. */
  checkedAt: string | null;
}

/** Sources the run found, newest last, with the time each was retrieved. Duplicates collapse. */
export function runSources(view: RunView): SourceItem[] {
  const fromLog = view.log.flatMap((e) => (e.event === "evidence_found" ? [e] : []));
  const items: SourceItem[] =
    fromLog.length >= view.evidence.length
      ? fromLog.map((e) => ({ key: `${e.seq}`, stage: e.node, title: e.title, url: e.url, authority: e.authority, kind: e.kind, checkedAt: e.ts }))
      : view.evidence.map((e, i) => ({ key: `ev${i}`, stage: e.node, title: e.title, url: e.url, authority: e.authority, kind: e.kind, checkedAt: null }));
  const seen = new Set<string>();
  return items.filter((item) => {
    const id = `${item.stage}|${item.url ?? item.title}`;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

export interface StageActivity {
  sources: SourceItem[];
  documents: { id: string; title: string }[];
  actions: { id: string; title: string; kind: string }[];
  artifacts: { id: string; type: string; title: string | null }[];
}

/** What one stage produced, from the run's event history. */
export function stageActivity(view: RunView, stageId: string): StageActivity {
  const documents: StageActivity["documents"] = [];
  const actions: StageActivity["actions"] = [];
  const artifacts: StageActivity["artifacts"] = [];
  for (const e of view.log) {
    if (e.node !== stageId) continue;
    if (e.event === "document_generated" && !documents.some((d) => d.id === e.documentId)) documents.push({ id: e.documentId, title: e.title });
    if (e.event === "action_prepared" && !actions.some((a) => a.id === e.actionId)) actions.push({ id: e.actionId, title: e.title, kind: e.kind });
    if (e.event === "artifact_created" && !artifacts.some((a) => a.id === e.artifactId))
      artifacts.push({ id: e.artifactId, type: e.artifactType, title: e.title });
  }
  return { sources: runSources(view).filter((s) => s.stage === stageId), documents, actions, artifacts };
}

/** Where an artifact lives in the app, if anywhere. */
export function artifactLink(type: string): { to: string; label: string } | null {
  switch (type) {
    case "journey":
      return { to: "/journey", label: tr("copy.open_your_journey_a0951bc") };
    case "twin":
    case "twin_node":
      return { to: "/knowledge/me", label: tr("copy.open_your_digital_twin_d9034f8") };
    case "document_extraction":
      return { to: "/documents", label: tr("copy.open_your_documents_770890a") };
    default:
      return null;
  }
}
