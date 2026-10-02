import { tr, localize, useLocale } from "@/i18n";
import { CircleCheck, CircleDashed, FlaskConical, Route } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { JourneyLines, JourneyLinesLegend } from "@/components/journey/JourneyLines";
import { buttonClass, Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { ProgressBar } from "@/components/ui/Progress";
import { EmptyState, ErrorState, Skeleton, SkeletonText } from "@/components/ui/States";
import type { Journey } from "@/domain/journey";
import type { SimulationProgress } from "@/domain/simulate";
import { useActiveJourney, useRecentRuns, useSimulation, useSimulationVariables, useWorkflow } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { completion, criticalPathDays } from "@/lib/journey/analysis";
import { changesBetween, draftFromJourney, sameChanges, variablesFor, type Draft } from "./model";
import { Results } from "./Results";
import { VariablesPanel } from "./VariablesPanel";

const ACTIVE = new Set(["queued", "running", "awaiting_input"]);

function LiveDot() {
  useLocale();
  const reduce = useReducedMotion();
  return (
    <span className="relative inline-flex size-4 items-center justify-center text-primary" aria-hidden>
      {!reduce && (
        <motion.span
          className="absolute inset-0.5 rounded-full bg-current"
          animate={{ scale: [1, 1.9], opacity: [0.4, 0] }}
          transition={{ duration: 1.8, repeat: Infinity, ease: "easeOut" }}
        />
      )}
      <span className="relative size-2 rounded-full bg-current" />
    </span>
  );
}

/** Before the first run: the plan as it is today, and an invitation to change one thing. */
function Idle({ journey }: { journey: Journey }) {
  useLocale();
  const { total, percent } = completion(journey);
  return (
    <div className="flex flex-col gap-6">
      <Card tone="flat" className="p-5 sm:p-6">
        <div className="flex items-start gap-4">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-tint text-primary-strong">
            <FlaskConical className="size-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 className="text-xl">{tr("copy.try_a_change_before_you_commit_to_it_d77b569")}</h2>
            <p className="mt-1 max-w-prose text-muted">
              {tr("copy.pick_a_quick_start_or_set_your_own_answers_then__cc52f1e")}</p>
          </div>
        </div>
      </Card>
      <section aria-labelledby="today-title">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="today-title" className="text-lg">
              {tr("copy.your_plan_today_ff56900")}</h2>
            <p className="tabular mt-0.5 text-sm text-muted">
              {localize(total)} {tr("copy.steps_6578912")}{criticalPathDays(journey) > 0 ? tr("copy.longest_chain_about_v0_days_adapt_estimate_07310b3", { v0: criticalPathDays(journey) }) : ""}{tr("copy.text_d3bc9a3")}{localize(percent)}{tr("copy.done_ef97506")}</p>
          </div>
          <Link to="/journey" className="text-sm font-medium text-primary-strong underline-offset-4 hover:underline">
            {tr("copy.open_journey_map_9908827")}</Link>
        </div>
        <Card tone="raised" className="p-5">
          <JourneyLines journey={journey} />
          <div className="mt-4 flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-start sm:justify-between">
            <JourneyLinesLegend />
            <p className="shrink-0 text-2xs text-subtle">{tr("copy.further_right_means_later_in_your_plan_05c3971")}</p>
          </div>
        </Card>
      </section>
    </div>
  );
}

/** While the simulation runs: which what-if stage it is on, with a way to watch or stop it. */
function Running({ progress, runId, onCancel }: { progress: SimulationProgress | null; runId: string | null; onCancel: () => void }) {
  useLocale();
  const workflow = useWorkflow("what_if");
  const stages = workflow.data?.stages ?? [];
  const current = stages.findIndex((s) => s.id === progress?.stage);
  return (
    <Card tone="raised" className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl">{tr("copy.testing_your_what_if_962e891")}</h2>
          <p className="mt-1 text-sm text-muted" aria-live="polite">
            {localize(progress?.label ?? tr("copy.starting_7725e05"))}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {runId && (
            <Link to={`/agents?run=${runId}`} className={buttonClass("secondary", "sm")}>
              {tr("copy.watch_it_run_feb8105")}</Link>
          )}
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {tr("copy.cancel_77dfd21")}</Button>
        </div>
      </div>
      <ProgressBar value={progress?.progress ?? 0} label={tr("copy.simulation_progress_25cef5a")} className="mt-4" />
      {stages.length > 0 && (
        <ol className="mt-5 grid gap-2 sm:grid-cols-2">
          {stages.map((stage, i) => {
            const state = current < 0 ? "queued" : i < current ? "done" : i === current ? "running" : "queued";
            return (
              <li key={stage.id} className="flex items-center gap-2.5 text-sm">
                {state === "done" ? (
                  <CircleCheck className="size-4 shrink-0 text-primary" aria-hidden />
                ) : state === "running" ? (
                  <LiveDot />
                ) : (
                  <CircleDashed className="size-4 shrink-0 text-subtle" aria-hidden />
                )}
                <span className={cn(state === "queued" ? "text-muted" : "text-ink", state === "running" && "font-medium")}>{localize(stage.label)}</span>
                <span className="sr-only">{state === "done" ? tr("copy.complete_ea62ae5") : state === "running" ? tr("copy.running_3ec734d") : tr("copy.queued_d656209")}</span>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

function SimulateSkeleton() {
  useLocale();
  return (
    <div role="status" aria-label={tr("copy.loading_your_plan_856478b")} className="grid items-start gap-6 @4xl/main:grid-cols-[22rem_minmax(0,1fr)]">
      <div className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-5">
        <Skeleton className="h-5 w-40" />
        <div className="grid grid-cols-2 gap-2">
          {localize(Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-12" />
          )))}
        </div>
        {localize(Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-16" />
        )))}
      </div>
      <div className="flex flex-col gap-4">
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-5 w-48" />
        <SkeletonText lines={5} />
      </div>
    </div>
  );
}

function Simulator({ journey }: { journey: Journey }) {
  const uiLocale = useLocale();
  const base = useMemo(() => draftFromJourney(journey), [journey, uiLocale]);
  const [draft, setDraft] = useState<Draft>(base);
  const sim = useSimulation();
  const variables = useSimulationVariables(journey.id);
  const supported = useMemo(() => variablesFor(variables.data ?? []), [variables.data, uiLocale]);
  const runs = useRecentRuns();
  const whatIf = useWorkflow("what_if");
  const stageLabel = useCallback(
    (id: string) => whatIf.data?.stages.find((s) => s.id === id)?.label ?? id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()),
    [whatIf.data, uiLocale],
  );
  const reduce = useReducedMotion();
  const resultsRef = useRef<HTMLDivElement>(null);
  const baseKey = JSON.stringify(base);

  // A changed plan (e.g. the person finished a step elsewhere) resets the variables to it.
  useEffect(() => {
    setDraft(JSON.parse(baseKey) as Draft);
  }, [baseKey]);

  const changes = changesBetween(base, draft);
  const running = sim.isPending;
  const whatIfRun = running ? (runs.data?.find((r) => r.kind === "what_if" && ACTIVE.has(r.status))?.id ?? null) : null;
  const stale = Boolean(sim.data) && !sameChanges(sim.variables?.changes, changes);

  // Bring progress and results into view when they would start off screen (below the
  // variables on phones, or above when reading earlier results further down).
  const reveal = useCallback(() => {
    requestAnimationFrame(() => {
      const el = resultsRef.current;
      if (!el) return;
      const { top } = el.getBoundingClientRect();
      if (top < 0 || top > window.innerHeight * 0.35) el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    });
  }, [reduce, uiLocale]);

  const run = useCallback(() => {
    if (!changes.length) return;
    sim.mutate({ journeyId: journey.id, changes }, { onSuccess: reveal });
    reveal();
  }, [changes, journey.id, reveal, sim, uiLocale]);

  if (variables.isPending) return <SimulateSkeleton />;
  if (variables.isError) return <ErrorState error={variables.error} onRetry={() => void variables.refetch()} />;

  return (
    <div className="grid items-start gap-6 @4xl/main:grid-cols-[22rem_minmax(0,1fr)] @6xl/main:grid-cols-[24rem_minmax(0,1fr)] @6xl/main:gap-8">
      <VariablesPanel
        base={base}
        draft={draft}
        onChange={setDraft}
        onRun={run}
        onCancel={sim.cancel}
        running={running}
        progress={sim.progress}
        supported={supported}
        className="self-start"
      />
      <div ref={resultsRef} className="min-w-0 scroll-mt-20" aria-busy={running || undefined}>
        {running ? (
          <Running progress={sim.progress} runId={whatIfRun} onCancel={sim.cancel} />
        ) : sim.isError ? (
          <ErrorState error={sim.error} onRetry={run} />
        ) : sim.data ? (
          <Results outcome={sim.data} stale={stale} running={running} onRerun={run} stageLabel={stageLabel} />
        ) : (
          <Idle journey={journey} />
        )}
      </div>
    </div>
  );
}

export default function SimulatePage() {
  useLocale();
  const journey = useActiveJourney();
  return (
    <div className="flex flex-col">
      <PageHeader
        title={tr("copy.what_if_fd0b7c0")}
        description={tr("copy.see_how_a_different_choice_would_change_your_pla_016bffa")}
      />
      {journey.isPending ? (
        <SimulateSkeleton />
      ) : journey.isError ? (
        <ErrorState error={journey.error} onRetry={() => void journey.refetch()} />
      ) : !journey.data ? (
        <EmptyState
          icon={<Route className="size-5" aria-hidden />}
          title={tr("copy.you_need_a_plan_to_compare_against_b1d43de")}
          description={tr("copy.what_if_tests_changes_against_your_plan_moving_a_b83c94d")}
          action={
            <Link to="/onboarding" className={buttonClass("primary", "lg")}>
              {tr("copy.plan_my_move_7da4bc0")}</Link>
          }
        />
      ) : (
        <Simulator journey={journey.data} />
      )}
    </div>
  );
}
