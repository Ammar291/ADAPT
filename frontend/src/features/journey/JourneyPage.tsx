import { tr, localize, useLocale } from "@/i18n";
/**
 * /journey — the plan as a transit map: one line per area of life, stations ordered by what
 * depends on what, with a list alternative, filters and a details panel for every step.
 *
 * URL: `?filter=<JourneyFilter>` preselects a filter, `?node=<key>` opens (and centres) a step.
 */
import { Info, List, Map as MapIcon, Route, X } from "lucide-react";
import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { BuildingPlanCard } from "@/components/journey/BuildingPlanCard";
import { Button, IconButton, buttonClass } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Controls";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { Spinner } from "@/components/ui/Spinner";
import type { Journey } from "@/domain/journey";
import { useActiveJourney, useDemo, useRecentRuns } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { useIsDesktop } from "@/lib/hooks/useMediaQuery";
import { JOURNEY_FILTERS, completion, countByFilter, criticalPathDays, nodeByKey, type JourneyFilter } from "@/lib/journey/analysis";
import { parseFilter, type ListGrouping } from "./graph";
import { JourneyList } from "./JourneyList";
import { buildTransitLayout } from "./layout";
import { Legend } from "./Legend";
import { DesktopNodePanel, MobileNodeSheet } from "./NodePanel";
import { TransitMap } from "./TransitMap";

const ACTIVE_RUN = new Set(["queued", "running", "awaiting_input"]);
const PAD = "px-4 sm:px-6 lg:px-8";

type View = "map" | "list";

function MiniRing({ value }: { value: number }) {
  useLocale();
  const r = 13;
  const c = 2 * Math.PI * r;
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" className="-rotate-90 shrink-0" aria-hidden>
      <circle cx="16" cy="16" r={r} fill="none" stroke="var(--surface-sunken)" strokeWidth="4" />
      <circle
        cx="16"
        cy="16"
        r={r}
        fill="none"
        stroke="var(--teal)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - value)}
        className="transition-[stroke-dashoffset] duration-700 ease-out"
      />
    </svg>
  );
}

function Stats({ journey }: { journey: Journey }) {
  useLocale();
  const { done, total, percent } = completion(journey);
  const days = criticalPathDays(journey);
  return (
    <dl className="grid w-full grid-cols-2 items-center gap-4 sm:flex sm:w-auto sm:gap-5">
      <div className="flex items-center gap-2.5">
        <MiniRing value={percent / 100} />
        <div>
          <dt className="sr-only">{tr("copy.completion_2ff2556")}</dt>
          <dd className="tabular text-sm font-medium whitespace-nowrap">
            {localize(done)} {tr("copy.of_2449d65")}{localize(total)} {tr("copy.done_e5fd9cf")}</dd>
          <dd className="tabular text-2xs text-subtle">{localize(percent)}{tr("copy.of_your_plan_ce661bc")}</dd>
        </div>
      </div>
      {days > 0 && (
        <div className="flex items-center gap-2.5 border-s border-line ps-4 sm:ps-5">
          <span className="h-[3px] w-5 shrink-0 rounded-full bg-primary" aria-hidden />
          <div>
            <dt className="sr-only">{tr("copy.critical_path_c77e227")}</dt>
            <dd className="tabular text-sm font-medium whitespace-nowrap">{tr("copy.about_dae445c")}{localize(days)} {tr("copy.days_5548ae4")}</dd>
            <dd className="text-2xs text-subtle">{tr("copy.estimated_time_remaining_5f2b937")}</dd>
          </div>
        </div>
      )}
    </dl>
  );
}

function BuildingNote({ runId, awaiting }: { runId: string; awaiting: boolean }) {
  useLocale();
  return (
    <div className={cn(PAD, "pb-3")}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-surface px-4 py-2.5 text-sm shadow-card" aria-live="polite">
        {!awaiting && <Spinner className="size-4 text-primary" />}
        <span className="text-ink">
          {awaiting ? tr("copy.your_plan_is_paused_until_you_approve_one_action_d7f1e67") : tr("copy.adapt_is_still_adding_steps_new_ones_appear_here_6f6fe1a")}
        </span>
        <Link to={`/agents?run=${runId}`} className="font-medium text-primary-strong hover:underline hover:underline-offset-4">
          {awaiting ? tr("copy.review_and_approve_365a840") : tr("copy.watch_it_build_6b698f8")}
        </Link>
      </div>
    </div>
  );
}

function JourneySkeleton() {
  useLocale();
  return (
    <div role="status" aria-label={tr("copy.loading_your_journey_f240bab")} className="flex min-h-0 flex-1 flex-col">
      <div className={cn(PAD, "pt-5 pb-4")}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <Skeleton className="h-7 w-40" />
            <Skeleton className="mt-2 h-4 w-60" />
          </div>
          <Skeleton className="h-9 w-44 rounded-lg" />
        </div>
        <Skeleton className="mt-4 h-10 w-full max-w-2xl rounded-lg" />
      </div>
      <div className="h-[68dvh] overflow-hidden border-t border-line lg:h-auto lg:flex-1">
        {[0, 1, 2, 3, 4].map((row) => (
          <div key={row} className={cn("flex items-start gap-12 border-b border-line py-7", PAD, row % 2 === 1 && "bg-muted-surface")}>
            <Skeleton className="h-11 w-28 shrink-0 rounded-lg" />
            {[0, 1, 2, 3].map((col) => (
              <div key={col} className={cn("flex shrink-0 flex-col items-center gap-3", (row + col) % 3 === 2 && "invisible")}>
                <Skeleton className="h-[88px] w-52 rounded-lg" />
                {(row + col) % 2 === 0 && <Skeleton className="h-8 w-44 rounded-full" />}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function Workspace({ journey, buildingRun }: { journey: Journey; buildingRun: { id: string; awaiting: boolean } | null }) {
  const uiLocale = useLocale();
  const isDesktop = useIsDesktop();
  const [params, setParams] = useSearchParams();
  const filter = parseFilter(params.get("filter"));
  const selectedKey = params.get("node");
  const selectedNode = selectedKey ? (nodeByKey(journey, selectedKey) ?? null) : null;
  const [viewChoice, setViewChoice] = useState<View | null>(null);
  const view: View = viewChoice ?? (isDesktop ? "map" : "list");
  const [grouping, setGrouping] = useState<ListGrouping>("area");
  const [legendChoice, setLegendChoice] = useState<boolean | null>(null);
  const legendOpen = legendChoice ?? false;

  const layout = useMemo(() => buildTransitLayout(journey), [journey, uiLocale]);
  const counts = useMemo(() => countByFilter(journey), [journey, uiLocale]);

  const updateParams = useCallback(
    (change: (next: URLSearchParams) => void) =>
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          // The demo seed is consumed on load (outside the router); don't write it back.
          next.delete("seed");
          change(next);
          return next;
        },
        { replace: true },
      ),
    [setParams, uiLocale],
  );

  const select = useCallback((key: string | null) => updateParams((p) => (key ? p.set("node", key) : p.delete("node"))), [updateParams, uiLocale]);
  const setFilter = (value: JourneyFilter) => updateParams((p) => (value === "all" ? p.delete("filter") : p.set("filter", value)));

  const close = useCallback(() => {
    const key = selectedKey;
    select(null);
    if (!key) return;
    // Return focus to the step that was open.
    requestAnimationFrame(() => {
      const escaped = CSS.escape(key);
      document.querySelector<HTMLElement>(`.react-flow__node[data-id="${escaped}"], [data-node-key="${escaped}"]`)?.focus({ preventScroll: true });
    });
  }, [select, selectedKey, uiLocale]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && selectedKey && isDesktop) close();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col" onKeyDown={onKeyDown}>
      <header className={cn(PAD, "relative z-20 shrink-0 pt-5 pb-4")}>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
          <div className="me-auto min-w-0">
            <h1 className="text-2xl">{tr("copy.your_journey_8379d05")}</h1>
            <p className="mt-0.5 truncate text-sm text-muted">{localize(journey.title)}</p>
          </div>
          <Stats journey={journey} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-3">
          <Segmented<JourneyFilter>
            label={tr("copy.show_steps_4d15abc")}
            value={filter}
            onChange={setFilter}
            options={JOURNEY_FILTERS.map((f) => ({ value: f.id, label: f.label, count: counts[f.id] }))}
            className="max-w-full"
          />
          <div className="ms-auto flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              aria-expanded={legendOpen}
              aria-controls="journey-legend"
              icon={<Info className="size-4" aria-hidden />}
              onClick={() => setLegendChoice(!legendOpen)}
            >
              {tr("copy.legend_5846955")}</Button>
            <Segmented<View>
              label={tr("copy.view_69bd4ef")}
              value={view}
              onChange={setViewChoice}
              options={[
                { value: "map", label: "Map", icon: <MapIcon className="size-4" aria-hidden /> },
                { value: "list", label: "List", icon: <List className="size-4" aria-hidden /> },
              ]}
            />
          </div>
        </div>
        {legendOpen && (
          <div
            id="journey-legend"
            role="region"
            aria-label={tr("copy.legend_5846955")}
            className="mt-4 rounded-xl border border-line bg-surface p-4 sm:absolute sm:end-6 sm:top-full sm:mt-1 sm:w-[min(760px,calc(100%-3rem))] sm:shadow-overlay lg:end-8"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                setLegendChoice(false);
              }
            }}
          >
            <div className="mb-3 flex items-start justify-between gap-3">
              <p className="text-sm text-muted">{tr("copy.each_line_is_an_area_of_your_life_steps_further__e07c783")}</p>
              <IconButton label={tr("copy.close_legend_abcf47a")} size="sm" onClick={() => setLegendChoice(false)} className="-me-1.5 -mt-1.5 shrink-0">
                <X className="size-4" aria-hidden />
              </IconButton>
            </div>
            <Legend />
          </div>
        )}
      </header>

      {buildingRun && <BuildingNote runId={buildingRun.id} awaiting={buildingRun.awaiting} />}

      <div className="relative flex min-h-0 flex-1 border-t border-line">
        <div className="relative min-w-0 flex-1">
          {view === "map" ? (
            <TransitMap
              journey={journey}
              layout={layout}
              filter={filter}
              selectedKey={selectedNode?.key ?? null}
              onSelect={select}
              desktop={isDesktop}
              className="h-[68dvh] lg:h-full"
            />
          ) : (
            <div className={cn(PAD, "py-5 lg:h-full lg:overflow-y-auto")}>
              <div className="mx-auto max-w-3xl">
                <JourneyList
                  journey={journey}
                  layout={layout}
                  filter={filter}
                  grouping={grouping}
                  onGroupingChange={setGrouping}
                  selectedKey={selectedNode?.key ?? null}
                  onSelect={select}
                />
              </div>
            </div>
          )}
        </div>
        {isDesktop && <DesktopNodePanel journey={journey} node={selectedNode} onSelect={select} onClose={close} />}
      </div>
      {!isDesktop && <MobileNodeSheet journey={journey} node={selectedNode} onSelect={select} onClose={close} />}
    </div>
  );
}

export default function JourneyPage() {
  useLocale();
  const journey = useActiveJourney();
  const runs = useRecentRuns();
  const demo = useDemo();
  const run = runs.data?.find((r) => r.kind === "journey" && ACTIVE_RUN.has(r.status));

  if (journey.isPending) return <JourneySkeleton />;
  if (journey.isError) {
    return (
      <div className={cn(PAD, "py-6")}>
        <h1 className="mb-4 text-2xl">{tr("copy.your_journey_8379d05")}</h1>
        <ErrorState error={journey.error} onRetry={() => void journey.refetch()} />
      </div>
    );
  }
  if (!journey.data) {
    return (
      <div className={cn(PAD, "mx-auto flex w-full max-w-3xl flex-col gap-6 py-6 lg:py-10")}>
        <h1 className="text-2xl sm:text-3xl">{tr("copy.your_journey_8379d05")}</h1>
        {run ? (
          <BuildingPlanCard runId={run.id} />
        ) : (
          <EmptyState
            icon={<Route className="size-5" aria-hidden />}
            title={tr("copy.your_journey_appears_here_b9c9bea")}
            description={tr("copy.tell_adapt_about_your_move_and_it_maps_every_ste_f3201eb")}
            action={
              <div className="flex flex-wrap items-center gap-4">
                <Link to="/onboarding" className={buttonClass("primary", "lg")}>
                  {tr("copy.plan_my_move_7da4bc0")}</Link>
                {demo && (
                  <button type="button" onClick={() => demo.seedSample.mutate()} className="text-sm text-muted underline underline-offset-4 hover:text-ink">
                    {tr("copy.explore_with_a_sample_plan_99cef7e")}</button>
                )}
              </div>
            }
          />
        )}
      </div>
    );
  }

  return <Workspace journey={journey.data} buildingRun={run ? { id: run.id, awaiting: run.status === "awaiting_input" } : null} />;
}
