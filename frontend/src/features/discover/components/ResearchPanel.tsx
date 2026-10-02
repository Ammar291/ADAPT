import { tr, localize, useLocale } from "@/i18n";
import { Ban, CircleCheck, CircleDashed, Compass, LoaderCircle, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/Progress";
import { Skeleton, UnavailableState } from "@/components/ui/States";
import { DISCOVER_SECTIONS, type ResearchCategoryStatus, type ResearchStatus } from "@/domain/discover";
import { describeError, isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { formatDate, relativeTime } from "@/lib/format";
import { categoryStatusText, researchProgress } from "../lib/discover";

const SECTION_TITLE = Object.fromEntries(DISCOVER_SECTIONS.map((s) => [s.id, s.title]));

const CATEGORY_ICON: Record<ResearchCategoryStatus, { icon: typeof CircleCheck; className: string }> = {
  pending: { icon: CircleDashed, className: "text-subtle" },
  running: { icon: LoaderCircle, className: "animate-spin text-primary" },
  completed: { icon: CircleCheck, className: "text-primary" },
  failed: { icon: TriangleAlert, className: "text-danger" },
  skipped: { icon: Ban, className: "text-subtle" },
};

const BACKGROUND_NOTE = tr("copy.research_runs_in_the_background_and_never_holds__220c912", { lng: "en" });

function ModeLabel({ mode }: { mode: ResearchStatus["mode"] }) {
  useLocale();
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      <ShieldCheck className="size-3.5 text-subtle" aria-hidden />
      {mode === "snapshot" ? tr("copy.from_adapt_s_reviewed_source_list_5766dbb") : tr("copy.checked_on_the_web_for_you_c029b4c")}
    </span>
  );
}

function StartProblem({ error }: { error: unknown }) {
  useLocale();
  if (isApiError(error, "consent_required")) {
    return (
      <div
        role="status"
        className="mt-4 flex flex-col items-start gap-2 rounded-lg border border-line bg-muted-surface p-4 sm:flex-row sm:items-center sm:justify-between"
      >
        <p className="text-sm">
          <span className="font-medium">{tr("copy.adapt_needs_your_permission_first_8b5b137")}</span> {tr("copy.turn_on_personalised_research_in_settings_then_s_fccdcdd")}</p>
        <Link to="/settings" className={buttonClass("secondary", "sm")}>
          {tr("copy.open_settings_134635e")}</Link>
      </div>
    );
  }
  if (isApiError(error, "journey_required")) {
    return (
      <div
        role="status"
        className="mt-4 flex flex-col items-start gap-2 rounded-lg border border-line bg-muted-surface p-4 sm:flex-row sm:items-center sm:justify-between"
      >
        <p className="text-sm">
          <span className="font-medium">{tr("copy.build_your_plan_first_0c8be9f")}</span> {tr("copy.discover_uses_it_to_pick_what_fits_your_move_8f039b6")}</p>
        <Link to="/onboarding" className={buttonClass("secondary", "sm")}>
          {tr("copy.plan_my_move_7da4bc0")}</Link>
      </div>
    );
  }
  const { title, detail } = describeError(error);
  return (
    <p role="alert" className="mt-3 text-sm text-danger">
      {localize(title)}{tr("copy.text_94c67da")}{localize(detail)}
    </p>
  );
}

function Personalised({ items }: { items: string[] }) {
  useLocale();
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-muted">{tr("copy.personalised_with_4833b4f")}</span>
      {items.map((item) => (
        <span key={item} className="inline-flex h-6 items-center rounded-full border border-line px-2.5 text-2xs text-muted">
          {localize(item)}
        </span>
      ))}
    </div>
  );
}

/**
 * Where research stands: progress per section while it runs, how much it found and when,
 * and how to start or refresh it. It never blocks the journey, and says so.
 */
export function ResearchPanel({
  status,
  statusPending,
  statusError,
  hasPlan,
  onStart,
  starting,
  startError,
}: {
  status: ResearchStatus | undefined;
  statusPending: boolean;
  statusError: unknown;
  /** False when the user has no journey yet (research needs one). */
  hasPlan: boolean | undefined;
  onStart: () => void;
  starting: boolean;
  startError: unknown;
}) {
  useLocale();
  let body: ReactNode;
  if (statusPending) {
    body = (
      <div aria-hidden className="flex flex-col gap-2">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-3.5 w-48" />
      </div>
    );
  } else if (statusError || status?.state === "unavailable" || !status) {
    return (
      <UnavailableState
        title={tr("copy.research_isn_t_available_right_now_ed47707")}
        description={tr("copy.your_journey_works_without_it_adapt_will_try_aga_2029115")}
      />
    );
  } else if (status.state === "running") {
    const progress = researchProgress(status.categories);
    body = (
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="flex items-center gap-2 font-medium">
            <LoaderCircle className="size-4 animate-spin text-primary" aria-hidden />
            {tr("copy.researching_for_you_3bbe525")}</p>
          <ModeLabel mode={status.mode} />
        </div>
        <ProgressBar className="mt-3" value={progress} label={tr("copy.research_progress_e043b8a")} />
        <ul className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 @3xl/main:grid-cols-4" aria-live="polite">
          {status.categories.map((category) => {
            const style = CATEGORY_ICON[category.status];
            const Icon = style.icon;
            return (
              <li key={category.section} className="flex items-start gap-2.5">
                <Icon className={cn("mt-0.5 size-4 shrink-0", style.className)} aria-hidden />
                <span className="min-w-0">
                  <span className={cn("block text-sm", category.status === "skipped" && "text-muted")}>{localize(SECTION_TITLE[category.section])}</span>
                  <span className="block text-2xs text-muted">{localize(categoryStatusText(category))}</span>
                </span>
              </li>
            );
          })}
        </ul>
        <p className="mt-4 text-xs text-subtle">{localize(BACKGROUND_NOTE)} {tr("copy.results_appear_below_as_each_section_finishes_0459583")}</p>
      </div>
    );
  } else if (status.state === "ready") {
    body = (
      <div className="flex flex-col gap-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-medium">{status.itemCount === 1 ? tr("copy.1_result_picked_for_your_move_2773093") : tr("copy.v0_results_picked_for_your_move_a2a3e3f", { v0: status.itemCount })}</p>
            <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
              {status.lastCheckedAt && (
                <span className="text-xs text-muted" title={localize(formatDate(status.lastCheckedAt))}>
                  {tr("copy.last_checked_7d5b4eb")}{localize(relativeTime(status.lastCheckedAt))}
                </span>
              )}
              <ModeLabel mode={status.mode} />
            </p>
          </div>
          <Button variant="secondary" size="sm" loading={starting} onClick={onStart} icon={<RefreshCw className="size-4" aria-hidden />}>
            {tr("copy.refresh_56e3bad")}</Button>
        </div>
        <details className="border-t border-line pt-1"><summary className="min-h-11 cursor-pointer py-3 text-xs font-medium text-muted">{tr("copy.why_these_results_fit_your_move_0936555")}</summary><Personalised items={status.personalisedWith} /><p className="mt-2 text-xs text-subtle">{localize(BACKGROUND_NOTE)}</p></details>
      </div>
    );
  } else if (hasPlan === false) {
    body = (
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-medium">{tr("copy.build_your_plan_first_7bf17f0")}</p>
          <p className="mt-1 text-sm text-muted">{tr("copy.discover_uses_your_plan_to_find_communities_even_578d5c2")}</p>
        </div>
        <Link to="/onboarding" className={buttonClass("primary", "md")}>
          {tr("copy.plan_my_move_7da4bc0")}</Link>
      </div>
    );
  } else {
    body = (
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="max-w-2xl">
          <p className="flex items-center gap-2 font-medium">
            <Compass className="size-4 text-primary" aria-hidden />
            {tr("copy.find_communities_events_and_tips_for_your_move_4ef5ee1")}</p>
          <p className="mt-1 text-sm text-muted">{localize(BACKGROUND_NOTE)} {tr("copy.each_result_shows_its_source_and_when_it_was_che_0202b7c")}</p>
        </div>
        <Button loading={starting} onClick={onStart}>
          {tr("copy.start_research_bd94188")}</Button>
      </div>
    );
  }

  return (
    <Card tone="raised" className="p-5 sm:p-6" aria-live={status?.state === "running" ? undefined : "polite"}>
      {localize(body)}
      {startError ? <StartProblem error={startError} /> : null}
    </Card>
  );
}
