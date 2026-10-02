import { tr, localize, useLocale } from "@/i18n";
import { ArrowUpRight, AudioLines, CalendarClock, Compass, KeyRound, Lightbulb, Route, TriangleAlert, CheckCheck, Clock3, Hand } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { ApprovalCard } from "@/components/approvals/ApprovalCard";
import { BuildingPlanCard } from "@/components/journey/BuildingPlanCard";
import { JourneyLines, JourneyLinesLegend } from "@/components/journey/JourneyLines";
import { NodeActionButton, needsUaePassNote } from "@/components/journey/NodeActionButton";
import { AreaLabel } from "@/components/ui/AreaLabel";
import { Badge } from "@/components/ui/Badge";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ProgressBar, ProgressRing } from "@/components/ui/Progress";
import { SourceLink } from "@/components/ui/SourceLink";
import { EmptyState, ErrorState, Skeleton, SkeletonText, UnavailableState } from "@/components/ui/States";
import { STATUS_STYLE, StatusBadge } from "@/components/ui/StatusBadge";
import { TrustBadge } from "@/components/ui/TrustBadge";
import { DISCOVER_SECTIONS } from "@/domain/discover";
import type { Journey } from "@/domain/journey";
import {
  useActiveJourney,
  useApprovals,
  useDemo,
  useDiscoverActions,
  useRecentRuns,
  useResearchStatus,
  useSession,
} from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { STATUS_LABEL, blockedNodes, completion, criticalPathDays, nextActions, nodeByKey, upcoming } from "@/lib/journey/analysis";
import { daysUntil, dueLabel, firstName, formatDate, greeting, relativeTime, formatNumber, formatPercent } from "@/lib/format";
import { useUiStore } from "@/stores/ui";

const ACTIVE_RUN = new Set(["queued", "running", "awaiting_input"]);

function SectionTitle({ icon, children, action }: { icon: ReactNode; children: ReactNode; action?: ReactNode }) {
  useLocale();
  return (
    <div className="mb-3 flex items-center gap-2">
      <span className="text-subtle" aria-hidden>
        {localize(icon)}
      </span>
      <h2 className="flex-1 text-base font-medium">{localize(children)}</h2>
      {localize(action)}
    </div>
  );
}

function NextAction({ journey }: { journey: Journey }) {
  useLocale();
  const [next, ...rest] = nextActions(journey, 4);
  if (!next) {
    const finished = completion(journey).percent === 100;
    return (
      <Card tone="strong" className="p-6">
        <h2 className="text-xl">{finished ? tr("copy.you_re_all_set_bb55050") : tr("copy.nothing_needs_you_right_now_42c17cd")}</h2>
        <p className="mt-1 text-muted">{finished ? tr("copy.you_ve_completed_every_step_in_your_plan_keep_yo_2322dfc") : tr("copy.your_remaining_steps_are_waiting_on_earlier_requ_b1f15b4")}</p>
      </Card>
    );
  }
  return (
    <section aria-labelledby="next-action">
      <Card tone="strong" className="overflow-hidden">
        <div className="p-5 sm:p-6">
          <div className="flex flex-wrap items-center gap-2">
            <span id="next-action" className="text-sm font-medium text-primary-strong">
              {tr("copy.your_next_step_9140334")}</span>
            <StatusBadge status={next.status} />
            <AreaLabel area={next.area} />
            {next.dueBy && <span className="ms-auto text-xs text-muted">{tr("copy.due_c50447d")}{localize(formatDate(next.dueBy))} {tr("copy.text_28ed3a7")}{localize(dueLabel(next.dueBy))}{tr("copy.text_e7064f0")}</span>}
          </div>
          <h3 className="mt-3 font-display text-2xl leading-snug">{localize(next.title)}</h3>
          <p className="mt-1.5 max-w-2xl text-muted">{localize(next.summary)}</p>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <NodeActionButton node={next} journeyId={journey.id} />
            <Link to={`/journey?node=${next.key}`} className={buttonClass("ghost", "md")}>
              {tr("copy.see_details_7e800ab")}</Link>
          </div>
          {(next.whyItMatters || next.blockers[0]) && <details className="mt-3 border-t border-line pt-1"><summary className="min-h-11 cursor-pointer py-3 text-xs font-medium text-muted">{tr("copy.why_this_step_matters_8bf0ba2")}</summary>{next.whyItMatters && <p className="max-w-2xl border-s-2 border-primary/40 ps-3 text-sm">{localize(next.whyItMatters)}</p>}{next.blockers[0] && next.status === "waiting_for_me" && <p className="mt-2 text-sm text-muted">{localize(next.blockers[0].resolution ?? next.blockers[0].message)}</p>}</details>}
          {next.evidence.citations[0]?.url && <a href={next.evidence.citations[0].url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1.5 text-xs font-medium text-primary-strong underline-offset-4 hover:underline" aria-label={localize(tr("copy.view_source_v0_7d43e6e", { v0: next.evidence.citations[0].title }))}>{tr("copy.view_source_31a7604")}<ArrowUpRight className="size-3.5" aria-hidden /><span className="sr-only">{tr("copy.opens_in_a_new_tab_bf5b990")}</span></a>}
          {needsUaePassNote(next) && (
            <p className="mt-3 flex items-center gap-2 text-xs text-muted">
              <KeyRound className="size-3.5 text-primary" aria-hidden />
              {tr("copy.you_sign_in_with_uae_pass_on_the_official_site_a_295d4cd")}</p>
          )}
        </div>
        {rest.length > 0 && (
          <details className="border-t border-line bg-muted-surface px-5 py-2 sm:px-6">
            <summary className="min-h-11 cursor-pointer py-3 text-xs font-medium text-muted">{tr("copy.up_next_ed0a8b3")}{localize(rest.length)} {tr("copy.more_steps_49c0218")}</summary>
            <ul className="divide-y divide-line">
              {rest.map((node) => {
                const Icon = STATUS_STYLE[node.status].icon;
                return (
                  <li key={node.key}>
                    <Link to={`/journey?node=${node.key}`} className="group flex items-center gap-3 py-2.5">
                      <Icon className={cn("size-4 shrink-0", node.status === "waiting_for_me" ? "text-ink" : "text-primary")} aria-hidden />
                      <span className="min-w-0 flex-1 truncate text-sm group-hover:underline group-hover:underline-offset-4">{localize(node.title)}</span>
                      <span className="shrink-0 text-xs text-subtle">
                        {localize(STATUS_LABEL[node.status])}
                        {node.dueBy ? `, ${dueLabel(node.dueBy)}` : ""}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </details>
        )}
      </Card>
    </section>
  );
}

function Blockers({ journey }: { journey: Journey }) {
  useLocale();
  const blocked = blockedNodes(journey).slice(0, 3);
  const risks = journey.risks.filter((r) => r.severity !== "info").slice(0, 2);
  if (!blocked.length && !risks.length) return null;
  return (
    <section>
      <SectionTitle icon={<TriangleAlert className="size-4" />} action={<Link to="/journey?filter=blocked" className="text-sm text-primary-strong hover:underline">{tr("copy.all_blocked_steps_796e106")}</Link>}>
        {tr("copy.what_s_holding_you_up_7437b7f")}</SectionTitle>
      <div className="grid gap-3 md:grid-cols-2">
        {risks.map((risk) => (
          <div key={risk.id} className={cn("rounded-lg border p-4", risk.severity === "blocking" ? "border-danger/30 bg-danger-tint" : "border-line bg-surface")}>
            <div className="flex items-center gap-2">
              <Badge tone={risk.severity === "blocking" ? "danger" : "neutral"}>{risk.severity === "blocking" ? tr("copy.serious_risk_c00bc44") : tr("copy.risk_5a8f23f")}</Badge>
            </div>
            <p className="mt-2 font-medium">{localize(risk.title)}</p>
            <p className="mt-1 text-sm text-muted">{localize(risk.detail)}</p>
            {risk.resolution && <p className="mt-2 text-sm">{localize(risk.resolution)}</p>}
          </div>
        ))}
        {blocked.map((node) => {
          const blocker = node.blockers[0];
          const related = blocker?.relatedNodeKey ? nodeByKey(journey, blocker.relatedNodeKey) : undefined;
          return (
            <div key={node.key} className="rounded-lg border border-line bg-surface p-4">
              <StatusBadge status="blocked" />
              <p className="mt-2 font-medium">{localize(node.title)}</p>
              {blocker && <p className="mt-1 text-sm text-muted">{localize(blocker.message)}</p>}
              {related && (
                <Link to={`/journey?node=${related.key}`} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-primary-strong hover:underline">
                  {tr("copy.go_to_b49acb6")}{localize(related.title)}
                  <ArrowUpRight className="flip-rtl size-3.5" aria-hidden />
                </Link>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ProgressCard({ journey }: { journey: Journey }) {
  useLocale();
  const { done, total, percent } = completion(journey);
  const arrival = journey.assumptions.find((a) => a.key === "move.arrival_date")?.value as string | null | undefined;
  const days = daysUntil(arrival ?? null);
  return (
    <Card tone="raised" className="p-5">
      <div className="flex items-center gap-4">
        <ProgressRing value={percent / 100} label={tr("copy.journey_completion_fbff4a1")} size={84} stroke={7} />
        <div className="min-w-0">
          <p className="font-medium">
            {tr("home.stepsDone", { done, total })}</p>
          {criticalPathDays(journey) > 0 && (
            <>
              <p className="mt-0.5 text-sm text-muted">{tr("copy.about_dae445c")}{localize(criticalPathDays(journey))} {tr("copy.days_to_complete_your_remaining_steps_abaeef0")}</p>
              <p className="mt-0.5 text-2xs text-subtle">{tr("copy.adapt_estimate_not_an_official_processing_time_803be53")}</p>
            </>
          )}
        </div>
      </div>
      {days !== null && (
        <div className="mt-4 flex items-center gap-2 rounded-lg bg-sunken px-3 py-2 text-sm">
          <CalendarClock className="size-4 text-primary" aria-hidden />
          {days > 0 ? tr("home.arrivalIn", { days, date: formatDate(arrival) }) : days === 0 ? tr("copy.you_arrive_today_597cf59") : tr("home.arrived", { date: formatDate(arrival) })}
        </div>
      )}
    </Card>
  );
}

function Upcoming({ journey }: { journey: Journey }) {
  useLocale();
  const approvals = useApprovals("pending");
  const appointments = upcoming(journey).filter((n) => n.kind === "appointment").slice(0, 2);
  const pending = approvals.data ?? [];
  return (
    <section>
      <SectionTitle icon={<CalendarClock className="size-4" />}>{tr("copy.coming_up_f582e20")}</SectionTitle>
      <div className="flex flex-col gap-3">
        {approvals.isPending && <Skeleton className="h-28 w-full" />}
        {pending.slice(0, 2).map((approval) => (
          <ApprovalCard key={approval.id} approval={approval} compact />
        ))}
        {pending.length > 2 && (
          <Link to="/approvals" className="text-sm font-medium text-primary-strong hover:underline">
            {localize(pending.length - 2)} {tr("copy.more_waiting_for_you_cf0f46a")}</Link>
        )}
        {appointments.map((node) => (
          <Link key={node.key} to={`/journey?node=${node.key}`} className="flex items-center gap-3 rounded-lg border border-line bg-surface p-3.5 hover:border-line-strong">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-tint text-primary">
              <CalendarClock className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{localize(node.title)}</span>
              <span className="block text-xs text-muted">{node.status === "blocked" ? node.blockers[0]?.message : node.dueBy ? tr("copy.aim_for_v0_b8f4ac7", { v0: formatDate(node.dueBy) }) : tr("copy.appointment_2d05c59")}</span>
            </span>
          </Link>
        ))}
        {!approvals.isPending && pending.length === 0 && appointments.length === 0 && <p className="text-sm text-subtle">{tr("copy.no_appointments_or_approvals_waiting_db4f410")}</p>}
      </div>
    </section>
  );
}

function ResearchStatusCard() {
  useLocale();
  const status = useResearchStatus();
  const { start } = useDiscoverActions();
  const s = status.data;
  return (
    <section>
      <SectionTitle icon={<Compass className="size-4" />}>{tr("copy.your_abu_dhabi_life_110295f")}</SectionTitle>
      <Card tone="flat" className="p-4">
        {status.isPending && <SkeletonText lines={3} />}
        {status.isError && <UnavailableState title={tr("copy.community_research_isn_t_available_yet_b9d3ea6")} description={tr("copy.your_journey_works_without_it_03a51e4")} className="border-0 p-0" />}
        {s?.state === "running" && (
          <div aria-live="polite">
            <p className="text-sm font-medium">{tr("copy.researching_communities_events_and_tips_7a7f7c6")}</p>
            <ul className="mt-3 flex flex-col gap-1.5">
              {s.categories.map((c) => (
                <li key={c.section} className="flex items-center justify-between gap-2 text-sm">
                  <span className={c.status === "skipped" ? "text-subtle" : ""}>{localize(DISCOVER_SECTIONS.find((d) => d.id === c.section)?.title)}</span>
                  <span className="text-xs text-muted">
                    {c.status === "completed" ? tr("copy.v0_found_dff5ad1", { v0: c.count }) : c.status === "running" ? tr("copy.looking_0fad6a2") : c.status === "skipped" ? tr("copy.not_included_bfca330") : c.status === "failed" ? tr("copy.couldn_t_finish_f8484ee") : tr("copy.waiting_33d3063")}
                  </span>
                </li>
              ))}
            </ul>
            <ProgressBar className="mt-3" label={tr("copy.research_progress_e043b8a")} value={s.categories.filter((c) => c.status === "completed" || c.status === "skipped").length / Math.max(1, s.categories.length)} />
            <p className="mt-2 text-xs text-subtle">{tr("copy.runs_in_the_background_your_journey_doesn_t_wait_f2f9a51")}</p>
          </div>
        )}
        {s?.state === "ready" && (
          <div>
            <p className="font-medium">{localize(s.itemCount)} {tr("copy.places_communities_and_tips_picked_for_you_668bd71")}</p>
            <p className="mt-0.5 text-xs text-muted">{tr("copy.last_checked_7d5b4eb")}{localize(relativeTime(s.lastCheckedAt))}</p>
            <Link to="/discover" className={buttonClass("secondary", "sm", "mt-3")}>
              {tr("copy.open_discover_5525c87")}</Link>
          </div>
        )}
        {s?.state === "idle" && (
          <div>
            <p className="text-sm text-muted">{tr("copy.adapt_can_research_communities_events_and_practi_d1e5e4a")}</p>
            <Button size="sm" variant="secondary" className="mt-3" loading={start.isPending} onClick={() => start.mutate(undefined)}>
              {tr("copy.start_research_bd94188")}</Button>
          </div>
        )}
        {s?.state === "unavailable" && <UnavailableState title={tr("copy.research_is_paused_b389187")} description={tr("copy.try_again_later_your_journey_works_without_it_6546c1b")} className="border-0 p-0" />}
      </Card>
    </section>
  );
}

function Considerations({ journey }: { journey: Journey }) {
  useLocale();
  if (!journey.considerations.length) return null;
  return (
    <section>
      <SectionTitle icon={<Lightbulb className="size-4" />}>{tr("copy.things_you_may_not_have_considered_74a9fb5")}</SectionTitle>
      <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
        {journey.considerations.slice(0, 4).map((c) => (
          <li key={c.id} className="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <TrustBadge kind={c.evidence.kind} />
              <AreaLabel area={c.area} />
            </div>
            <p className="mt-2 font-medium">{localize(c.title)}</p>
            <p className="mt-1 text-sm text-muted">{localize(c.detail)}</p>
            {c.evidence.citations[0] && (
              <SourceLink
                className="mt-2"
                title={localize(c.evidence.citations[0].title)}
                authority={c.evidence.citations[0].authority}
                url={c.evidence.citations[0].url}
                checkedAt={c.evidence.citations[0].retrievedAt}
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function AskAdapt() {
  useLocale();
  const open = useUiStore((s) => s.setAssistantOpen);
  const examples = [tr("copy.what_should_i_do_this_week_9810bf7"), tr("copy.what_do_i_need_to_sponsor_my_spouse_9d508d4"), tr("copy.mainland_or_adgm_for_my_company_28e65d6")];
  return (
    <Card tone="flat" className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-ink text-canvas">
        <AudioLines className="size-5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{tr("copy.ask_adapt_by_voice_or_text_c502428")}</p>
        <p className="text-sm text-muted">{localize(examples[0])} {tr("copy.get_a_little_guidance_whenever_you_need_it_32008eb")}</p>
      </div>
      <Button variant="secondary" onClick={() => open(true)}>
        {tr("copy.ask_adapt_07a99fc")}</Button>
    </Card>
  );
}

function HomeSkeleton() {
  useLocale();
  return (
    <div role="status" aria-label={tr("copy.loading_your_plan_856478b")} className="flex flex-col gap-8">
      <div>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-3 h-9 w-2/3" />
      </div>
      <div className="grid gap-8 @4xl/main:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex flex-col gap-6">
          <Skeleton className="h-64 w-full rounded-xl" />
          <Skeleton className="h-48 w-full rounded-xl" />
        </div>
        <div className="flex flex-col gap-6">
          <Skeleton className="h-36 w-full rounded-xl" />
          <Skeleton className="h-40 w-full rounded-xl" />
        </div>
      </div>
    </div>
  );
}

function headline(journey: Journey): string {
  const waiting = journey.nodes.filter((n) => n.status === "waiting_for_me").length;
  const { percent } = completion(journey);
  if (waiting > 0) return tr("copy.your_next_chapter_is_taking_shape_2f16848");
  return percent === 0 ? tr("copy.your_move_starts_here_6d88196") : tr("home.settled", { percent: formatPercent(percent / 100) });
}

export default function HomePage() {
  useLocale();
  const session = useSession();
  const journey = useActiveJourney();
  const runs = useRecentRuns();
  const demo = useDemo();
  const approvals = useApprovals("pending");
  const reduceMotion = useReducedMotion();
  const name = firstName(session.data?.displayName);
  const building = runs.data?.find((run) => run.kind === "journey" && ACTIVE_RUN.has(run.status));

  if (journey.isPending) return <HomeSkeleton />;
  if (journey.isError) return <ErrorState error={journey.error} onRetry={() => void journey.refetch()} />;

  const hello = `${greeting()}${name ? `, ${name}` : ""}`;

  if (!journey.data) {
    return (
      <div className="flex flex-col gap-8">
        <header>
          <p className="text-muted">{localize(hello)}</p>
          <h1 className="mt-2 text-3xl sm:text-4xl">{building ? tr("copy.your_plan_is_on_its_way_46b3cc8") : tr("copy.let_s_plan_your_move_8e1015d")}</h1>
        </header>
        {building ? (
          <BuildingPlanCard runId={building.id} />
        ) : (
          <EmptyState
            icon={<Route className="size-5" aria-hidden />}
            title={tr("copy.you_don_t_have_a_plan_yet_dc6e4fa")}
            description={tr("copy.tell_adapt_about_your_move_it_orders_company_res_dad0672")}
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
        <AskAdapt />
      </div>
    );
  }

  const plan = journey.data;
  const reveal = (i: number) =>
    reduceMotion ? {} : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { delay: i * 0.06, duration: 0.35, ease: [0.2, 0, 0, 1] as const } };

  return (
    <div className="flex flex-col gap-5 sm:gap-8">
      <motion.header {...reveal(0)} className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-muted">{localize(hello)}</p>
          <h1 className="mt-2 max-w-2xl text-2xl leading-tight sm:text-4xl">{localize(headline(plan))}</h1>
        </div>
      </motion.header>

      {building && <BuildingPlanCard runId={building.id} />}

      <dl className="dashboard-summary grid grid-cols-3 gap-3 rounded-xl border border-line px-4 py-4 sm:px-6">
        {[{ label: tr("copy.steps_complete_e8aa9b2"), value: `${formatNumber(completion(plan).done)} / ${formatNumber(completion(plan).total)}`, icon: CheckCheck }, { label: tr("copy.need_your_input_5e888ef"), value: plan.nodes.filter((n) => n.status === "waiting_for_me").length, icon: Hand }, { label: tr("copy.days_remaining_cf27604"), value: criticalPathDays(plan) || "—", icon: Clock3 }].map(({ label, value, icon: Icon }, i) => <div key={label} className={cn("min-w-0", i > 0 && "border-s border-line ps-3 sm:ps-6")}><dt className="flex items-center gap-1.5 text-2xs text-muted"><Icon className="hidden size-3.5 sm:block" aria-hidden />{localize(label)}</dt><dd dir="ltr" className="tabular mt-1 text-xl font-medium sm:text-2xl">{localize(value)}{Icon === Clock3 && <span className="ms-1 text-2xs font-normal text-subtle">{tr("copy.est_2f3035b")}</span>}</dd></div>)}
      </dl>

      {(approvals.data?.length ?? 0) > 0 && <Link to="/approvals" className="flex min-h-14 items-center gap-3 rounded-xl border border-dune/30 bg-dune-tint px-4 py-3"><Hand className="size-4 shrink-0 text-dune" aria-hidden /><span className="min-w-0 flex-1 text-sm"><span className="font-medium">{localize(approvals.data!.length)} {tr("copy.requests_need_your_approval_2a179bd")}</span> {tr("copy.review_what_will_be_shared_330c11c")}</span><ArrowUpRight className="size-4 shrink-0 text-dune" aria-hidden /></Link>}

      <div className="grid gap-8 @4xl/main:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-8">
          <motion.div {...reveal(1)}>
            <NextAction journey={plan} />
          </motion.div>

          <motion.section {...reveal(2)} aria-labelledby="journey-lines" className="hidden sm:block">
            <SectionTitle
              icon={<Route className="size-4" />}
              action={
                <Link to="/journey" className="text-sm text-primary-strong hover:underline">
                  {tr("copy.open_journey_map_9908827")}</Link>
              }
            >
              <span id="journey-lines">{tr("copy.your_journey_at_a_glance_662e2b8")}</span>
            </SectionTitle>
            <Card tone="raised" className="p-5">
              <JourneyLines journey={plan} />
              <div className="mt-4 flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-start sm:justify-between">
                <JourneyLinesLegend />
                <p className="shrink-0 text-2xs text-subtle">{tr("copy.further_right_means_later_in_your_plan_05c3971")}</p>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {plan.goals.map((goal) => (
                  <Badge key={goal} tone="outline">
                    {localize(goal)}
                  </Badge>
                ))}
              </div>
            </Card>
          </motion.section>

          <Link to="/journey" className="flex min-h-14 items-center gap-3 rounded-xl border border-line bg-surface p-4 sm:hidden"><Route className="size-5 text-primary" aria-hidden /><span className="min-w-0 flex-1"><span className="block text-sm font-medium">{tr("copy.your_journey_at_a_glance_472ba64")}</span><span className="block text-xs text-muted">{localize(completion(plan).done)} {tr("copy.of_2449d65")}{localize(completion(plan).total)} {tr("copy.steps_complete_123aa28")}</span></span><ArrowUpRight className="size-4 text-subtle" aria-hidden /></Link>
          <details className="rounded-xl border border-line bg-surface p-4 sm:hidden"><summary className="min-h-11 cursor-pointer py-2 text-sm font-medium">{tr("copy.risks_and_blocked_steps_dd24c90")}{localize(blockedNodes(plan).length)}</summary><div className="pt-3"><Blockers journey={plan} /></div></details>
          <div className="hidden sm:block"><Blockers journey={plan} /></div>
          <AskAdapt />
        </div>

        <aside className="flex min-w-0 flex-col gap-8" aria-label={tr("copy.your_progress_and_what_s_next_9003857")}>
          <ProgressCard journey={plan} />
          <Upcoming journey={plan} />
          <ResearchStatusCard />
          <details className="rounded-xl border border-line bg-surface p-4 sm:hidden"><summary className="min-h-11 cursor-pointer py-2 text-sm font-medium">{tr("copy.useful_things_to_know_1087418")}</summary><div className="pt-3"><Considerations journey={plan} /></div></details>
          <div className="hidden sm:block"><Considerations journey={plan} /></div>
        </aside>
      </div>
    </div>
  );
}
