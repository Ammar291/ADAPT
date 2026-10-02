import { tr, localize, useLocale } from "@/i18n";
import { DropdownMenu } from "radix-ui";
import {
  ArrowDown,
  Ban,
  Check,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  FileText,
  Hand,
  History,
  Package,
  Radio,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Unplug,
  Wrench,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/Badge";
import { buttonClass } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Controls";
import { ProgressBar } from "@/components/ui/Progress";
import { SourceLink } from "@/components/ui/SourceLink";
import { TrustBadge } from "@/components/ui/TrustBadge";
import { ACTION_KIND_LABEL, type ActionKind } from "@/domain/common";
import type { RunKind, RunStatus, RunSummary, StreamState } from "@/domain/runs";
import { useRecentRuns, useResearchStatus } from "@/lib/api/hooks";
import type { RunView } from "@/lib/events/runEvents";
import { cn } from "@/lib/cn";
import { formatTime, relativeTime } from "@/lib/format";
import { RUN_KIND_LABEL, RUN_STATUS_LABEL, STREAM_LABEL, elapsedMs, formatClock, isActiveStatus } from "./flow";
import { artifactLink, countByFilter, filterLog, LOG_FILTERS, type LogCategory, type LogEntry, type LogFilter, type SourceItem } from "./log";
import { LiveDot } from "./StageStatus";

// --- time ---------------------------------------------------------------------------------------------

/** The current time, ticking every second while `active`. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

// --- status badges --------------------------------------------------------------------------------------

const RUN_STATUS_STYLE: Record<RunStatus, { tone: "neutral" | "primary" | "danger" | "ink" | "outline"; icon: ReactNode }> = {
  queued: { tone: "outline", icon: <History className="size-3.5" aria-hidden /> },
  running: { tone: "primary", icon: <LiveDot /> },
  awaiting_input: { tone: "ink", icon: <Hand className="size-3.5" aria-hidden /> },
  succeeded: { tone: "primary", icon: <CircleCheck className="size-3.5" aria-hidden /> },
  failed: { tone: "danger", icon: <CircleAlert className="size-3.5" aria-hidden /> },
  cancelled: { tone: "neutral", icon: <Ban className="size-3.5" aria-hidden /> },
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  useLocale();
  const style = RUN_STATUS_STYLE[status];
  return (
    <Badge tone={style.tone} icon={style.icon}>
      {localize(RUN_STATUS_LABEL[status])}
    </Badge>
  );
}

function StreamIndicator({ stream, active }: { stream: StreamState; active: boolean }) {
  useLocale();
  const icon =
    stream === "open" ? (
      active ? (
        <LiveDot className="text-primary" />
      ) : (
        <Radio className="size-3.5 text-primary" aria-hidden />
      )
    ) : stream === "reconnecting" || stream === "connecting" ? (
      <RefreshCw className="size-3.5 text-muted" aria-hidden />
    ) : (
      <Unplug className="size-3.5 text-subtle" aria-hidden />
    );
  return (
    <span className="inline-flex items-center gap-1.5" aria-live="polite">
      {localize(icon)}
      <span className={stream === "open" ? "font-medium text-primary-strong" : ""}>{localize(STREAM_LABEL[stream])}</span>
    </span>
  );
}

// --- run picker -----------------------------------------------------------------------------------------

export function RunPicker({ runs, currentId, onPick }: { runs: RunSummary[]; currentId: string; onPick: (id: string) => void }) {
  useLocale();
  const current = runs.find((r) => r.id === currentId);
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="inline-flex h-9 max-w-full items-center gap-2 rounded-md border border-line-strong bg-surface px-3 text-sm hover:bg-sunken"
        >
          <History className="size-4 shrink-0 text-subtle" aria-hidden />
          <span className="truncate">{current ? `${RUN_KIND_LABEL[current.kind]}, ${relativeTime(current.createdAt)}` : tr("copy.choose_a_run_b359c7e")}</span>
          <span className="sr-only">{tr("copy.choose_another_run_1942864")}{localize(runs.length)} {tr("copy.recent_0d912e8")}</span>
          <ChevronDown className="size-4 shrink-0 text-subtle" aria-hidden />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={6}
          className="z-50 max-h-[min(24rem,var(--radix-dropdown-menu-content-available-height))] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-overlay"
        >
          <DropdownMenu.Label className="px-2.5 pt-1.5 pb-1 text-xs text-muted">{tr("copy.recent_runs_on_this_device_a0e09cd")}</DropdownMenu.Label>
          <DropdownMenu.RadioGroup value={currentId} onValueChange={onPick}>
            {runs.map((run) => (
              <DropdownMenu.RadioItem
                key={run.id}
                value={run.id}
                className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 outline-none data-[highlighted]:bg-sunken"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{localize(RUN_KIND_LABEL[run.kind])}</span>
                  <span className="block text-2xs text-subtle">{tr("copy.started_750fe42")}{localize(relativeTime(run.createdAt))}</span>
                </span>
                <RunStatusBadge status={run.status} />
                <DropdownMenu.ItemIndicator className="w-4">
                  <Check className="size-4 text-primary" aria-hidden />
                </DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

// --- header ---------------------------------------------------------------------------------------------

export function RunHeader({
  kind,
  status,
  view,
  stream,
  progress,
  headline,
  current,
  picker,
  actions,
}: {
  kind: RunKind;
  status: RunStatus;
  view: RunView;
  stream: StreamState;
  progress: { complete: number; total: number; ratio: number };
  headline: string;
  /** The stage working right now, while the run is live. */
  current: { label: string; line: string } | null;
  picker: ReactNode;
  actions?: ReactNode;
}) {
  useLocale();
  const active = isActiveStatus(status);
  const now = useNow(active);
  const elapsed = elapsedMs(view.startedAt, view.finishedAt, now);

  return (
    <header className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        {localize(picker)}
        {localize(actions)}
      </div>
      <div>
        <h1 className="text-2xl leading-tight">{localize(headline)}</h1>
        <p className="sr-only" aria-live="polite">
          {localize(RUN_KIND_LABEL[kind])}{tr("copy.text_ceca32e")}{localize(RUN_STATUS_LABEL[status])}
        </p>
      </div>
      <dl className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted">
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">{tr("copy.status_bae7d5b")}</dt>
          <dd>
            <RunStatusBadge status={status} />
          </dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">{tr("copy.updates_c76d180")}</dt>
          <dd>
            <StreamIndicator stream={stream} active={active} />
          </dd>
        </div>
        {view.startedAt && (
          <div className="flex items-center gap-1">
            <dt>{tr("copy.started_faa9e7e")}</dt>
            <dd className="tabular">{localize(formatTime(view.startedAt))}</dd>
          </div>
        )}
        {elapsed !== null && (
          <div className="flex items-center gap-1">
            <dt>{active ? tr("copy.elapsed_5fc9779") : tr("copy.took_26251f9")}</dt>
            <dd className="tabular">{!active && elapsed < 1000 ? tr("copy.under_a_second_85e0403") : formatClock(elapsed)}</dd>
          </div>
        )}
      </dl>
      {progress.total > 0 && (
        <div className="flex items-center gap-3">
          <ProgressBar value={progress.ratio} label={tr("copy.steps_complete_e8aa9b2")} className="flex-1" tone={status === "failed" ? "ink" : "primary"} />
          <span className="tabular shrink-0 text-xs text-muted">
            {localize(progress.complete)} {tr("copy.of_2449d65")}{localize(progress.total)} {tr("copy.steps_6578912")}</span>
        </div>
      )}
      {active && (
        <p className="min-h-5 text-sm text-muted" aria-live="polite">
          {current && status === "running" && (
            <>
              <span className="font-medium text-ink">{localize(current.label)}</span>
              {current.line ? `: ${current.line}` : ""}
            </>
          )}
          {status === "awaiting_input" && tr("copy.paused_at_your_approval_the_run_carries_on_as_so_2232e0f")}
        </p>
      )}
    </header>
  );
}

// --- activity log ---------------------------------------------------------------------------------------

const CATEGORY_ICON: Record<LogCategory, ReactNode> = {
  run: <Radio className="size-3.5" aria-hidden />,
  stage: <Sparkles className="size-3.5" aria-hidden />,
  tool: <Wrench className="size-3.5" aria-hidden />,
  evidence: <Search className="size-3.5" aria-hidden />,
  approval: <ShieldCheck className="size-3.5" aria-hidden />,
  output: <FileText className="size-3.5" aria-hidden />,
};

function LogLine({ entry }: { entry: LogEntry }) {
  useLocale();
  const stage = entry.stageLabel && !entry.text.includes(entry.stageLabel) && !entry.detail?.includes(entry.stageLabel) ? entry.stageLabel : null;
  return (
    <li className="grid grid-cols-[4.25rem_1rem_minmax(0,1fr)] gap-x-2 px-4 py-2 sm:px-5">
      <time dateTime={entry.ts} className="tabular pt-px text-2xs text-subtle">
        {localize(formatTime(entry.ts))}
      </time>
      <span
        className={cn(
          "pt-0.5",
          entry.tone === "danger" ? "text-danger" : entry.tone === "attention" ? "text-ink" : entry.tone === "success" ? "text-primary" : "text-subtle",
        )}
      >
        {localize(CATEGORY_ICON[entry.category])}
      </span>
      <div className="min-w-0">
        <p className={cn("text-sm break-words", entry.tone === "attention" && "font-medium", entry.tone === "danger" && "text-danger")}>{localize(entry.text)}</p>
        {(entry.detail || stage) && (
          <p className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-2xs text-muted">
            {stage && <span className="rounded bg-sunken px-1.5 py-px text-subtle">{localize(stage)}</span>}
            {entry.detail && <span className="min-w-0 break-words">{localize(entry.detail)}</span>}
          </p>
        )}
      </div>
    </li>
  );
}

/**
 * The run's events as readable lines, newest at the bottom. Follows new lines unless the
 * person has scrolled up to read, then offers a jump back to the latest.
 */
export function ActivityLog({ entries, live, className }: { entries: LogEntry[]; live: boolean; className?: string }) {
  const uiLocale = useLocale();
  const [filter, setFilter] = useState<LogFilter>("all");
  const counts = useMemo(() => countByFilter(entries), [entries, uiLocale]);
  const shown = useMemo(() => filterLog(entries, filter), [entries, filter, uiLocale]);
  const scroller = useRef<HTMLDivElement>(null);
  const [stuck, setStuck] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const lastCount = useRef(shown.length);

  useLayoutEffect(() => {
    const el = scroller.current;
    const added = shown.length - lastCount.current;
    lastCount.current = shown.length;
    if (!el) return;
    if (stuck) el.scrollTop = el.scrollHeight;
    else if (added > 0) setUnseen((n) => n + added);
  }, [shown, stuck]);

  useEffect(() => {
    setStuck(true);
    setUnseen(0);
  }, [filter]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setStuck(atBottom);
    if (atBottom) setUnseen(0);
  };

  const latest = entries[entries.length - 1];

  return (
    <div className={cn("relative flex min-h-0 flex-col", className)}>
      <div className="px-4 pt-3 pb-2 sm:px-5">
        <Segmented
          label={tr("copy.show_activity_a306bf7")}
          size="sm"
          value={filter}
          onChange={setFilter}
          options={LOG_FILTERS.map((f) => ({ value: f.id, label: f.label, count: f.id === "all" ? undefined : counts[f.id] }))}
        />
      </div>
      {/* Announce only the newest line, so screen readers aren't flooded during replay. */}
      <p className="sr-only" aria-live="polite">
        {live && latest ? latest.text : ""}
      </p>
      <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto" tabIndex={0} aria-label={tr("copy.run_activity_58f23b6")}>
        {shown.length === 0 ? (
          <p className="px-4 py-6 text-sm text-subtle sm:px-5">
            {filter === "all"
              ? tr("copy.activity_appears_here_as_soon_as_the_run_starts_92a7efc")
              : tr("copy.no_v0_activity_in_this_run_yet_faa67f8", { v0: LOG_FILTERS.find((f) => f.id === filter)!.label.toLowerCase() })}
          </p>
        ) : (
          <ol className="divide-y divide-line/70 pb-24">
            {shown.map((entry) => (
              <LogLine key={entry.seq} entry={entry} />
            ))}
          </ol>
        )}
      </div>
      {!stuck && unseen > 0 && (
        <button
          type="button"
          onClick={() => {
            const el = scroller.current;
            if (el) el.scrollTop = el.scrollHeight;
            setStuck(true);
            setUnseen(0);
          }}
          className="absolute bottom-3 left-1/2 inline-flex h-9 -translate-x-1/2 items-center gap-1.5 rounded-full bg-ink px-3.5 text-sm font-medium text-canvas shadow-overlay"
        >
          <ArrowDown className="size-4" aria-hidden />
          {localize(unseen)} {tr("copy.new_c2a6b03")}</button>
      )}
    </div>
  );
}

// --- sources and outputs -----------------------------------------------------------------------------------

export function SourcesList({ sources, labelOf }: { sources: SourceItem[]; labelOf: (id: string) => string }) {
  useLocale();
  if (!sources.length)
    return (
      <p className="px-4 py-6 text-sm text-subtle sm:px-5">{tr("copy.official_sources_the_agents_check_appear_here_ea_d8fe183")}</p>
    );
  return (
    <ul className="divide-y divide-line pb-24">
      {sources.map((source) => (
        <li key={source.key} className="flex flex-col gap-1.5 px-4 py-3 sm:px-5">
          <div className="flex flex-wrap items-center gap-2">
            <TrustBadge kind={source.kind} />
            {source.stage && <span className="text-2xs text-subtle">{tr("copy.found_by_3c77f5e")}{localize(labelOf(source.stage))}</span>}
          </div>
          <SourceLink title={localize(source.title)} url={source.url} authority={source.authority} checkedAt={source.checkedAt} />
          {source.authority && source.authority !== source.title && <p className="text-2xs text-muted">{localize(source.title)}</p>}
        </li>
      ))}
    </ul>
  );
}

/**
 * Research a run started in the background. Mock runs stream its events; a live journey
 * only records that it started it (research is its own run), so the server's research
 * status is read instead.
 */
function useRunResearch(view: RunView): RunView["research"] {
  const runs = useRecentRuns();
  // The server's status is the newest research job: it belongs to this run only if this is
  // the newest plan run and its research actually started.
  const newestPlan = runs.data?.find((run) => run.kind === "journey")?.id === view.runId;
  const startedHere =
    !view.research &&
    newestPlan &&
    view.log.some((e) => e.event === "tool_result" && e.tool === "start_research" && e.ok && !e.summary.startsWith(tr("copy.not_started_7e3fe7c")));
  const status = useResearchStatus(startedHere);
  if (view.research) return view.research;
  const data = status.data;
  if (!startedHere || !data || data.state === "idle" || data.state === "unavailable") return null;
  const settled = data.categories.filter((c) => c.status === "completed" || c.status === "failed" || c.status === "skipped");
  return {
    jobId: data.jobId ?? "",
    state: data.state === "running" ? "running" : "completed",
    sections: data.categories.map((c) => c.section),
    completed: settled.map((c) => c.section),
    results: data.itemCount,
  };
}

export function OutputsList({ view }: { view: RunView }) {
  useLocale();
  const research = useRunResearch(view);
  const empty = !view.documents.length && !view.actions.length && !view.artifacts.length && !research;
  if (empty) return <p className="px-4 py-6 text-sm text-subtle sm:px-5">{tr("copy.drafts_prepared_actions_and_plans_the_agents_cre_8cc32d1")}</p>;
  return (
    <div className="flex flex-col divide-y divide-line pb-24">
      {view.artifacts.length > 0 && (
        <section className="px-4 py-3 sm:px-5">
          <h3 className="mb-2 font-sans text-xs font-medium text-muted">{tr("copy.created_accf40c")}</h3>
          <ul className="flex flex-col gap-2">
            {view.artifacts.map((artifact) => {
              const link = artifactLink(artifact.type);
              return (
                <li key={artifact.id} className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate">{localize(artifact.title ?? artifact.type)}</span>
                  {link && (
                    <Link to={link.to} className="shrink-0 text-sm font-medium text-primary-strong underline-offset-4 hover:underline">
                      {tr("copy.open_cf9b770")}</Link>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {view.documents.length > 0 && (
        <section className="px-4 py-3 sm:px-5">
          <h3 className="mb-2 font-sans text-xs font-medium text-muted">{tr("copy.drafts_for_your_review_cc254ef")}</h3>
          <ul className="flex flex-col gap-2">
            {view.documents.map((doc) => (
              <li key={doc.id} className="flex items-center gap-2 text-sm">
                <FileText className="size-4 shrink-0 text-subtle" aria-hidden />
                <span className="min-w-0 truncate">{localize(doc.title)}</span>
              </li>
            ))}
          </ul>
          <Link to="/documents?tab=drafts" className="mt-2 inline-block text-sm font-medium text-primary-strong underline-offset-4 hover:underline">
            {tr("copy.review_drafts_1fcaa37")}</Link>
        </section>
      )}
      {view.actions.length > 0 && (
        <section className="px-4 py-3 sm:px-5">
          <h3 className="mb-2 font-sans text-xs font-medium text-muted">{tr("copy.actions_prepared_94bb7c8")}</h3>
          <ul className="flex flex-col gap-2">
            {view.actions.map((action) => (
              <li key={action.id} className="flex items-start gap-2 text-sm">
                <Package className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
                <span className="min-w-0">
                  {localize(action.title)}
                  <span className="block text-2xs text-subtle">{localize(ACTION_KIND_LABEL[action.kind as ActionKind] ?? action.kind)}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {research && (
        <section className="px-4 py-3 sm:px-5">
          <h3 className="mb-1 font-sans text-xs font-medium text-muted">{tr("copy.community_research_0911f6e")}</h3>
          <p className="text-sm" aria-live="polite">
            {research.state === "running"
              ? tr("copy.running_in_the_background_v0_of_v1_topics_done_c91665b", { v0: research.completed.length, v1: research.sections.length })
              : research.state === "completed"
                ? tr("copy.finished_with_v0_results_d9a5beb", { v0: research.results })
                : tr("copy.stopped_before_it_finished_your_plan_doesn_t_dep_b9ee721")}
          </p>
          <Link to="/discover" className="mt-1 inline-block text-sm font-medium text-primary-strong underline-offset-4 hover:underline">
            {tr("copy.open_discover_5525c87")}</Link>
        </section>
      )}
    </div>
  );
}

// --- small helpers --------------------------------------------------------------------------------------------

export function PlanLinks({ className }: { className?: string }) {
  useLocale();
  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      <Link to="/home" className={buttonClass("primary", "md")}>
        {tr("copy.see_your_plan_3d9d334")}</Link>
      <Link to="/journey" className={buttonClass("secondary", "md")}>
        {tr("copy.open_your_journey_a0951bc")}</Link>
    </div>
  );
}
