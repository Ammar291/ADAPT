import { tr, localize, useLocale } from "@/i18n";
import { CircleAlert, CircleCheck, CircleSlash, ListTree, Network, Stethoscope, Workflow } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/Controls";
import { EmptyState, ErrorState, Skeleton, SkeletonText } from "@/components/ui/States";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Controls";
import { toast } from "@/components/ui/Toast";
import type { AgentWorkflow, RunKind, RunStatus, RunSummary } from "@/domain/runs";
import { describeError } from "@/lib/api/errors";
import { useActiveJourney, useCancelRun, useRecentRuns, useRun, useStartDiagnosticRun, useWorkflow } from "@/lib/api/hooks";
import { stageStatuses, type RunView } from "@/lib/events/runEvents";
import { useRunEvents } from "@/lib/events/useRunEvents";
import { useIsDesktop } from "@/lib/hooks/useMediaQuery";
import { useWidth } from "./useWidth";
import { cn } from "@/lib/cn";
import { focusStage, isActiveStatus, pickRunId, RUN_KIND_LABEL, runHeadline, stageLine, stageProgress, trimLead } from "./flow";
import { buildLog, runSources, stageActivity } from "./log";
import { ReviewPanel } from "./ReviewPanel";
import { ActivityLog, OutputsList, PlanLinks, RunHeader, RunPicker, SourcesList } from "./RunConsole";
import { StageDetail } from "./StageDetail";
import { KindIcon } from "./StageStatus";
import { StageTimeline } from "./StageTimeline";
import { WorkflowGraph } from "./WorkflowGraph";

/** False for a moment after a run opens, while its history replays, so it doesn't all animate at once. */
function useSettled(key: string, ms = 700): boolean {
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    setSettled(false);
    const timer = setTimeout(() => setSettled(true), ms);
    return () => clearTimeout(timer);
  }, [key, ms]);
  return settled;
}

// --- outcome ----------------------------------------------------------------------------------------------

function RunOutcome({
  kind,
  status,
  view,
  headline,
  onSystemCheck,
  checking,
}: {
  kind: RunKind;
  status: RunStatus;
  view: RunView;
  headline: string;
  onSystemCheck: () => void;
  checking: boolean;
}) {
  useLocale();
  if (status === "succeeded") {
    return (
      <Card tone="raised" className="flex flex-col gap-3 p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <CircleCheck className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <h2 className="text-base font-medium">{localize(trimLead(view.summary, headline) ?? tr("copy.finished_355bcc5"))}</h2>
            {kind === "journey" && <p className="mt-0.5 text-sm text-muted">{tr("copy.every_step_cites_its_source_nothing_was_sent_or__833dcd9")}</p>}
            {kind === "what_if" && <p className="mt-0.5 text-sm text-muted">{tr("copy.your_real_plan_hasn_t_changed_compare_the_two_pa_206baae")}</p>}
            {kind === "diagnostic" && <p className="mt-0.5 text-sm text-muted">{tr("copy.the_database_live_updates_and_the_agent_runtime__33ba2e9")}</p>}
          </div>
        </div>
        {kind === "journey" && <PlanLinks />}
        {kind === "what_if" && (
          <Link to="/simulate" className={buttonClass("secondary", "md", "self-start")}>
            {tr("copy.open_what_if_9627a97")}</Link>
        )}
        {kind === "research" && (
          <Link to="/discover" className={buttonClass("secondary", "md", "self-start")}>
            {tr("copy.open_discover_5525c87")}</Link>
        )}
        {kind === "diagnostic" && (
          <Button variant="secondary" className="self-start" loading={checking} onClick={onSystemCheck}>
            {tr("copy.run_the_check_again_c54f607")}</Button>
        )}
      </Card>
    );
  }
  if (status === "failed") {
    return (
      <div role="alert" className="flex flex-col gap-3 rounded-xl border border-danger/30 bg-danger-tint p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
          <div className="min-w-0">
            <h2 className="text-base font-medium">{localize(view.error?.message ?? tr("copy.the_run_stopped_unexpectedly_db14bcf"))}</h2>
            <p className="mt-1 text-sm text-muted">
              {tr("copy.check_your_plan_for_each_action_s_status_run_a_s_d3111a3")}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" loading={checking} onClick={onSystemCheck} icon={<Stethoscope className="size-4" aria-hidden />}>
            {tr("copy.run_a_system_check_7295feb")}</Button>
          {kind === "journey" && (
            <Link to="/onboarding" className={buttonClass("ghost", "md")}>
              {tr("copy.start_your_plan_again_bc3edce")}</Link>
          )}
          {kind === "what_if" && (
            <Link to="/simulate" className={buttonClass("ghost", "md")}>
              {tr("copy.try_the_what_if_again_439344b")}</Link>
          )}
        </div>
      </div>
    );
  }
  if (status === "cancelled") {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-line bg-surface p-4 sm:p-5">
        <CircleSlash className="mt-0.5 size-5 shrink-0 text-subtle" aria-hidden />
        <div className="min-w-0">
          <h2 className="text-base font-medium">{tr("copy.this_run_was_cancelled_22e0ed6")}</h2>
          <p className="mt-0.5 text-sm text-muted">{tr("copy.it_stopped_where_it_was_your_plan_shows_the_stat_7546bfa")}</p>
        </div>
      </div>
    );
  }
  return null;
}

// --- console tabs ----------------------------------------------------------------------------------------

function ConsoleTabs({ view, live, labelOf, className }: { view: RunView; live: boolean; labelOf: (id: string) => string; className?: string }) {
  const uiLocale = useLocale();
  const entries = useMemo(() => buildLog(view.log, labelOf), [view.log, labelOf, uiLocale]);
  const sources = useMemo(() => runSources(view), [view, uiLocale]);
  const outputs = view.documents.length + view.actions.length + view.artifacts.length + (view.research ? 1 : 0);
  return (
    <Tabs defaultValue="activity" className={cn("flex min-h-0 flex-col", className)}>
      <TabsList label={tr("copy.run_details_e6487ca")} className="shrink-0 px-2 sm:px-3">
        <TabsTrigger value="activity">{tr("copy.activity_81c0d91")}</TabsTrigger>
        <TabsTrigger value="sources">
          {tr("copy.sources_2eb56be")}<span className="tabular rounded-full bg-sunken px-1.5 text-2xs text-muted">{localize(sources.length)}</span>
        </TabsTrigger>
        <TabsTrigger value="outputs">
          {tr("copy.outputs_7835db4")}<span className="tabular rounded-full bg-sunken px-1.5 text-2xs text-muted">{localize(outputs)}</span>
        </TabsTrigger>
      </TabsList>
      <TabsContent value="activity" className="flex min-h-0 flex-1 flex-col focus-visible:outline-none">
        <ActivityLog entries={entries} live={live} className="flex-1" />
      </TabsContent>
      <TabsContent value="sources" className="min-h-0 flex-1 overflow-y-auto">
        <SourcesList sources={sources} labelOf={labelOf} />
      </TabsContent>
      <TabsContent value="outputs" className="min-h-0 flex-1 overflow-y-auto">
        <OutputsList view={view} />
      </TabsContent>
    </Tabs>
  );
}

// --- run screen ----------------------------------------------------------------------------------------------

/** Graph beside the console needs room for both; below this the console stacks under a step list. */
const SIDE_BY_SIDE_MIN = 1000;

function RunScreen({ runId, recent, onPick, width }: { runId: string; recent: RunSummary[]; onPick: (id: string) => void; width: number }) {
  const uiLocale = useLocale();
  const run = useRun(runId);
  const { view, stream } = useRunEvents(runId);
  const listed = recent.find((r) => r.id === runId);
  const startedKind = view.log.find((e) => e.event === "run_started");
  const kind: RunKind | null = run.data?.kind ?? listed?.kind ?? (startedKind?.event === "run_started" ? startedKind.kind : null);
  const workflow = useWorkflow(kind ?? "journey");
  const isDesktop = useIsDesktop();
  const sideBySide = isDesktop && width >= SIDE_BY_SIDE_MIN;
  const reduce = useReducedMotion();
  const settled = useSettled(runId);
  const cancel = useCancelRun();
  const check = useStartDiagnosticRun();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<"graph" | "list">("graph");
  const reviewRef = useRef<HTMLElement>(null);

  // Agents without a published topology (e.g. the system check): draw the stages the run reports.
  const resolved = useMemo((): AgentWorkflow | undefined => {
    const published = workflow.data;
    if (!published || published.stages.length > 0 || view.order.length === 0) return published;
    const ids = view.order;
    return {
      id: published.id,
      version: "from-events",
      stages: ids.map((id) => ({ id, label: view.stages[id]?.label ?? id, description: "", kind: "tool", lane: 0 })),
      edges: ids.slice(1).map((id, i) => ({ source: ids[i]!, target: id, condition: null })),
    };
  }, [workflow.data, view.order, view.stages, uiLocale]);
  const stages = resolved?.stages;
  const stageIds = useMemo(() => stages?.map((s) => s.id) ?? [], [stages, uiLocale]);
  const statuses = useMemo(() => stageStatuses(view, stageIds), [view, stageIds, uiLocale]);
  const status: RunStatus = view.status !== "unknown" ? view.status : (run.data?.status ?? listed?.status ?? "queued");
  const active = isActiveStatus(status);
  const needsReview = active && (status === "awaiting_input" || view.pendingApprovals.length > 0);
  const focusId = focusStage(view, statuses);
  const labelOf = useCallback((id: string) => stages?.find((s) => s.id === id)?.label ?? view.stages[id]?.label ?? id, [stages, view.stages, uiLocale]);

  const select = useCallback((id: string) => setSelectedId((current) => (current === id ? null : id)), [uiLocale]);
  const close = useCallback(() => {
    setSelectedId((current) => {
      if (current) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-stage="${current}"]`)?.focus());
      return null;
    });
  }, [uiLocale]);

  useEffect(() => {
    if (!selectedId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if ((event.target as HTMLElement | null)?.closest("dialog, [role='menu']")) return;
      close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [selectedId, close]);

  // When the run pauses for the person, bring the review into view in the console.
  const revealReview = () => {
    if (!sideBySide) return;
    requestAnimationFrame(() => reviewRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }));
  };

  const goToReview = () => {
    const el = reviewRef.current;
    if (!el) return;
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    el.focus({ preventScroll: true });
  };

  const runCheck = () =>
    check.mutate(undefined, {
      onSuccess: (ref) => onPick(ref.runId),
      onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail ?? undefined, tone: "error" }),
    });

  const doCancel = () =>
    cancel.mutate(runId, {
      onSuccess: () => toast({ title: tr("copy.run_cancelled_d35c8b3"), description: tr("copy.your_plan_shows_the_status_of_each_action_116e52b") }),
      onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail ?? undefined, tone: "error" }),
    });

  if (run.isError && !listed && view.status === "unknown") {
    return (
      <div className="flex flex-col gap-4 px-4 py-6 sm:px-6 lg:px-8">
        <EmptyState
          icon={<Workflow className="size-5" aria-hidden />}
          title={tr("copy.adapt_can_t_find_this_run_d3a5ca5")}
          description={tr("copy.it_may_belong_to_another_account_or_it_was_remov_e24ebcb")}
          action={
            <div className="flex flex-wrap gap-2">
              {recent[0] && (
                <Button onClick={() => onPick(recent[0]!.id)} variant="primary">
                  {tr("copy.open_the_latest_run_7e871bf")}</Button>
              )}
              <Button variant={recent[0] ? "secondary" : "primary"} loading={check.isPending} onClick={runCheck}>
                {tr("copy.run_a_system_check_7295feb")}</Button>
            </div>
          }
        />
      </div>
    );
  }
  if (!kind || workflow.isPending) return <AgentsSkeleton />;
  if (workflow.isError) {
    return (
      <div className="px-4 py-6 sm:px-6 lg:px-8">
        <ErrorState error={workflow.error} onRetry={() => void workflow.refetch()} />
      </div>
    );
  }

  const wf: AgentWorkflow = resolved ?? workflow.data;
  const progress = stageProgress(statuses);
  const headline = runHeadline(kind, status);
  const selected = selectedId ? wf.stages.find((s) => s.id === selectedId) : undefined;
  const runs = listed ? recent : run.data ? [run.data, ...recent] : recent;

  const header = (
    <RunHeader
      kind={kind}
      status={status}
      view={view}
      stream={stream}
      progress={progress}
      headline={headline}
      current={
        active && focusId && statuses[focusId] !== "complete"
          ? { label: labelOf(focusId), line: stageLine(statuses[focusId]!, view.stages[focusId], "") }
          : null
      }
      picker={<RunPicker runs={runs} currentId={runId} onPick={onPick} />}
      actions={
        // A run can be stopped while it waits for the person (nothing is executing then).
        status === "awaiting_input" ? (
          <Button variant="ghost" size="sm" loading={cancel.isPending} onClick={doCancel}>
            {tr("copy.cancel_run_83dc24e")}</Button>
        ) : undefined
      }
    />
  );

  const review = (
    <AnimatePresence initial={false}>
      {needsReview && (
        <motion.div
          key="review"
          initial={reduce ? false : { opacity: 0, y: -8, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={reduce ? { opacity: 0 } : { opacity: 0, height: 0 }}
          transition={{ duration: 0.3, ease: [0.2, 0, 0, 1] }}
        >
          <ReviewPanel ref={reviewRef} runId={runId} view={view} onLoaded={revealReview} />
        </motion.div>
      )}
    </AnimatePresence>
  );

  const outcome = <RunOutcome kind={kind} status={status} view={view} headline={headline} onSystemCheck={runCheck} checking={check.isPending} />;

  const detailFor = (id: string, onClose?: () => void) => {
    const stage = wf.stages.find((s) => s.id === id)!;
    return (
      <StageDetail
        stage={stage}
        view={view.stages[id]}
        status={statuses[id] ?? "queued"}
        activity={stageActivity(view, id)}
        onClose={onClose}
        onGoToReview={needsReview ? goToReview : undefined}
        headingLevel={onClose ? "h2" : "h3"}
      />
    );
  };

  if (!sideBySide) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 pt-5 pb-10 sm:px-6">
        {localize(header)}
        {localize(review)}
        {localize(outcome)}
        <section aria-labelledby="steps-title">
          <div className="mb-2 flex items-baseline justify-between gap-3">
            <h2 id="steps-title" className="text-lg">
              {tr("copy.steps_cdde4f2")}</h2>
            <span className="text-xs text-muted">{tr("copy.select_a_step_for_details_4511b8a")}</span>
          </div>
          <StageTimeline
            workflow={wf}
            view={view}
            statuses={statuses}
            selectedId={selectedId}
            onSelect={select}
            renderDetail={(id) => detailFor(id)}
            animate={settled}
          />
        </section>
        <section aria-label={tr("copy.run_activity_58f23b6")} className="overflow-hidden rounded-xl border border-line bg-surface">
          <ConsoleTabs view={view} live={settled && active} labelOf={labelOf} className="h-[30rem]" />
        </section>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1">
      <section aria-labelledby="workflow-title" className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-5 py-2.5">
          <div className="min-w-0">
            <h2 id="workflow-title" className="truncate font-sans text-sm font-medium">
              {localize(RUN_KIND_LABEL[kind])} {tr("copy.workflow_899531e")}</h2>
            <p className="text-2xs text-muted">{tr("copy.select_a_step_to_see_its_tool_calls_sources_and__33e3726")}</p>
          </div>
          <Segmented
            label={tr("copy.show_the_workflow_as_18f9fe1")}
            size="sm"
            value={mode}
            onChange={setMode}
            options={[
              { value: "graph", label: "Graph", icon: <Network className="size-3.5" aria-hidden /> },
              { value: "list", label: "Steps", icon: <ListTree className="size-3.5" aria-hidden /> },
            ]}
          />
        </div>
        {mode === "graph" ? (
          <WorkflowGraph workflow={wf} view={view} statuses={statuses} selectedId={selectedId} focusId={focusId} onSelect={select} animate={settled} />
        ) : (
          <div className="canvas-dots min-h-0 flex-1 overflow-y-auto px-6 pt-8 pb-24">
            <StageTimeline
              workflow={wf}
              view={view}
              statuses={statuses}
              selectedId={selectedId}
              onSelect={select}
              animate={settled}
              className="mx-auto max-w-xl"
            />
          </div>
        )}
      </section>

      <aside aria-label={tr("copy.run_console_21e002d")} className="flex min-h-0 w-[26rem] shrink-0 flex-col border-s border-line bg-surface xl:w-[28rem]">
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div className="shrink-0 border-b border-line px-5 pt-5 pb-4">{localize(header)}</div>
          {(needsReview || status === "succeeded" || status === "failed" || status === "cancelled") && (
            <div className="flex shrink-0 flex-col gap-3 border-b border-line bg-muted-surface p-4">
              {localize(review)}
              {localize(outcome)}
            </div>
          )}
          <AnimatePresence mode="wait" initial={false}>
            {selected ? (
              <motion.div
                key={`detail-${selected.id}`}
                initial={reduce ? false : { opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                exit={reduce ? { opacity: 0 } : { opacity: 0, x: 12 }}
                transition={{ duration: 0.18, ease: [0.2, 0, 0, 1] }}
                className="shrink-0 p-5 pb-24"
                aria-live="polite"
              >
                {localize(detailFor(selected.id, close))}
              </motion.div>
            ) : (
              <motion.div
                key="tabs"
                initial={reduce ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="flex min-h-[24rem] flex-1 flex-col"
              >
                <ConsoleTabs view={view} live={settled && active} labelOf={labelOf} className="flex-1" />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </aside>
    </div>
  );
}

// --- no runs and loading ------------------------------------------------------------------------------------

function AgentsSkeleton() {
  useLocale();
  return (
    <div role="status" aria-label={tr("copy.loading_the_run_2c52d6d")} className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <div className="hidden min-h-0 flex-1 flex-col items-center gap-5 p-16 lg:flex">
        {localize(Array.from({ length: 7 }, (_, i) => (
          <Skeleton key={i} className="h-[60px] w-80 rounded-xl" />
        )))}
      </div>
      <div className="flex flex-col gap-4 border-line px-4 pt-5 sm:px-6 lg:w-[26rem] lg:border-s lg:bg-surface lg:p-5">
        <Skeleton className="h-9 w-52" />
        <Skeleton className="h-8 w-3/4" />
        <Skeleton className="h-2 w-full" />
        <SkeletonText lines={6} className="mt-4" />
      </div>
    </div>
  );
}

function NoRuns({ onPick }: { onPick: (id: string) => void }) {
  useLocale();
  const check = useStartDiagnosticRun();
  const journey = useActiveJourney();
  const workflow = useWorkflow("journey");
  const runCheck = () =>
    check.mutate(undefined, {
      onSuccess: (ref) => onPick(ref.runId),
      onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail ?? undefined, tone: "error" }),
    });

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
      <header>
        <h1 className="text-3xl">{tr("copy.agents_64acf7e")}</h1>
        <p className="mt-2 max-w-2xl text-muted">{tr("copy.watch_adapt_s_agents_work_on_your_move_step_by_s_5afe065")}</p>
      </header>
      <EmptyState
        icon={<Workflow className="size-5" aria-hidden />}
        title={tr("copy.no_agent_runs_yet_72b7404")}
        description={tr("copy.when_adapt_plans_your_move_or_tests_a_what_if_it_e9ca15c")}
        action={
          <div className="flex flex-wrap gap-2">
            {journey.data ? (
              <Link to="/simulate" className={buttonClass("primary", "md")}>
                {tr("copy.try_a_what_if_dcc20fe")}</Link>
            ) : (
              <Link to="/onboarding" className={buttonClass("primary", "md")}>
                {tr("copy.plan_my_move_7da4bc0")}</Link>
            )}
            <Button variant="secondary" loading={check.isPending} onClick={runCheck} icon={<Stethoscope className="size-4" aria-hidden />}>
              {tr("copy.run_a_system_check_7295feb")}</Button>
          </div>
        }
      />
      {workflow.data && (
        <section aria-labelledby="how-title" className="max-w-3xl">
          <h2 id="how-title" className="text-lg">
            {tr("copy.how_adapt_builds_your_plan_8256b63")}</h2>
          <ol className="mt-3 grid gap-x-8 sm:grid-cols-2">
            {workflow.data.stages.map((stage) => (
              <li key={stage.id} className="flex items-start gap-3 border-b border-line py-3">
                <KindIcon kind={stage.kind} />
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{localize(stage.label)}</span>
                  <span className="block text-sm text-muted">{localize(stage.description)}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

function AgentsContent({ width }: { width: number }) {
  const uiLocale = useLocale();
  const [params, setParams] = useSearchParams();
  const requested = params.get("run");
  const recent = useRecentRuns();
  const runId = pickRunId(requested, recent.data);
  const pick = useCallback((id: string) => setParams({ run: id }), [setParams, uiLocale]);

  if (!runId) {
    if (recent.isPending) return <AgentsSkeleton />;
    if (recent.isError) {
      return (
        <div className="px-4 py-6 sm:px-6 lg:px-8">
          <ErrorState error={recent.error} onRetry={() => void recent.refetch()} />
        </div>
      );
    }
    return <NoRuns onPick={pick} />;
  }
  return <RunScreen key={runId} runId={runId} recent={recent.data ?? []} onPick={pick} width={width} />;
}

export default function AgentsPage() {
  useLocale();
  const [ref, width] = useWidth<HTMLDivElement>();
  return (
    // On desktop the page fills the viewport; when it's too narrow for the graph (e.g. the
    // assistant is docked) the stacked layout scrolls inside it.
    <div ref={ref} className="flex min-h-0 flex-1 flex-col lg:overflow-y-auto">
      {width > 0 && <AgentsContent width={width} />}
    </div>
  );
}
