import { tr, localize, useLocale } from "@/i18n";
import {
  ArrowRight,
  CalendarClock,
  ExternalLink,
  FlaskConical,
  KeyRound,
  Link2,
  ListChecks,
  Minus,
  RefreshCw,
  Route,
  ShieldAlert,
  Sparkles,
  Unlink,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { AreaLabel } from "@/components/ui/AreaLabel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/Controls";
import { domainOf } from "@/domain/common";
import type { RiskSeverity } from "@/domain/journey";
import type { RiskChange, ScenarioOutcome } from "@/domain/simulate";
import { formatNumber, formatPercent, formatUnit } from "@/lib/format";
import { cn } from "@/lib/cn";
import { assumptionName, assumptionValueLabel } from "./model";
import {
  alignPaths,
  daysDelta,
  describeFieldChange,
  focusRows,
  focusSteps,
  newActions,
  pathSummary,
  splitChangedNodes,
  type PathStep,
  type PathSummary,
} from "./paths";

// --- small pieces ------------------------------------------------------------------------------------

function Section({ icon, title, count, children, className }: { icon: ReactNode; title: string; count?: number; children: ReactNode; className?: string }) {
  useLocale();
  return (
    <section className={cn("flex flex-col gap-2", className)}>
      <h3 className="flex items-center gap-2 font-sans text-base font-medium">
        <span className="text-subtle" aria-hidden>
          {localize(icon)}
        </span>
        {localize(title)}
        {count !== undefined && <span className="tabular rounded-full bg-sunken px-1.5 text-2xs text-muted">{localize(count)}</span>}
      </h3>
      {localize(children)}
    </section>
  );
}

const SEVERITY: Record<RiskSeverity, { label: string; tone: "danger" | "neutral" | "outline" }> = {
  blocking: { label: tr("copy.serious_risk_c00bc44", { lng: "en" }), tone: "danger" },
  warning: { label: tr("copy.risk_5a8f23f", { lng: "en" }), tone: "neutral" },
  info: { label: tr("copy.note_2c924e3", { lng: "en" }), tone: "outline" },
};

const RISK_CHANGE: Record<RiskChange["change"], string> = {
  added: tr("copy.new_in_this_scenario_81c9197", { lng: "en" }),
  removed: tr("copy.no_longer_applies_35cdb8b", { lng: "en" }),
  changed: tr("copy.severity_changes_f81b232", { lng: "en" }),
};

/** The simulation disclaimer: always visible above results. */
export function SimulationNotice({ stale, onRerun, running }: { stale: boolean; onRerun: () => void; running: boolean }) {
  useLocale();
  return (
    <div role="note" className="flex flex-col gap-3 rounded-lg border border-ink/15 bg-surface px-4 py-3 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <FlaskConical className="mt-0.5 size-5 shrink-0 text-ink" aria-hidden />
        <p className="text-sm">
          <span className="font-medium">{tr("copy.your_plan_hasn_t_changed_this_is_a_simulation_7251e5a")}</span>{localize(" ")}
          <span className="text-muted">{stale ? tr("copy.these_results_are_for_your_previous_changes_0df8ebb") : tr("copy.saved_as_a_scenario_for_comparison_4748104")}</span>
        </p>
      </div>
      {stale && (
        <Button size="sm" variant="secondary" onClick={onRerun} loading={running} icon={<RefreshCw className="size-3.5" aria-hidden />}>
          {tr("copy.run_with_your_latest_changes_ce220a2")}</Button>
      )}
    </div>
  );
}

// --- summary ----------------------------------------------------------------------------------------

function Metric({ label, before, after, note }: { label: string; before: string; after: string; note?: ReactNode }) {
  useLocale();
  const same = before === after;
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-xs text-muted">{localize(label)}</dt>
      <dd className="flex flex-wrap items-baseline gap-x-2">
        {!same && (
          <>
            <span className="tabular text-sm text-muted">{localize(before)}</span>
            <ArrowRight className="flip-rtl size-3.5 self-center text-subtle" aria-label={tr("copy.becomes_4e58ac7")} />
          </>
        )}
        <span className="tabular font-display text-xl font-semibold">{localize(after)}</span>
      </dd>
      {note && <dd className="text-2xs text-muted">{localize(note)}</dd>}
    </div>
  );
}

function Summary({ outcome, base, scenario }: { outcome: ScenarioOutcome; base: PathSummary; scenario: PathSummary }) {
  useLocale();
  const delta = daysDelta(base.criticalDays, scenario.criticalDays);
  return (
    <Card tone="strong" className="p-5 sm:p-6">
      <h2 className="text-xl leading-snug sm:text-2xl">{localize(outcome.diff.summary)}</h2>
      {outcome.diff.changes.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2" aria-label={tr("copy.what_you_changed_e1160c2")}>
          {outcome.diff.changes.map((change) => (
            <li key={change.key} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span className="text-muted">{localize(assumptionName(change.key, change.label))}{tr("copy.text_05a79f0")}</span>
              <span className="text-muted line-through decoration-line-strong">{localize(assumptionValueLabel(change.key, change.from))}</span>
              <ArrowRight className="flip-rtl size-3.5 text-subtle" aria-label={tr("copy.changed_to_128b470")} />
              <span className="font-medium">{localize(assumptionValueLabel(change.key, change.to))}</span>
            </li>
          ))}
        </ul>
      )}
      <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-line pt-5 sm:grid-cols-3">
        {(base.criticalDays > 0 || scenario.criticalDays > 0) && (
          <Metric
            label={tr("copy.longest_chain_of_steps_f4248ca")}
            before={formatUnit(base.criticalDays, "day")}
            after={formatUnit(scenario.criticalDays, "day")}
            note={<span className={cn(delta.direction === "shorter" && "font-medium text-primary-strong")}>{delta.text}</span>}
          />
        )}
        <Metric label={tr("copy.steps_in_the_plan_9811d58")} before={formatNumber(base.completion.total)} after={formatNumber(scenario.completion.total)} />
        <Metric label={tr("copy.done_so_far_8f57305")} before={formatPercent(base.completion.percent / 100)} after={formatPercent(scenario.completion.percent / 100)} />
      </dl>
      {(base.criticalDays > 0 || scenario.criticalDays > 0) && (
        <p className="mt-4 text-2xs text-subtle">{tr("copy.day_counts_are_adapt_estimates_not_official_proc_e126560")}</p>
      )}
    </Card>
  );
}

// --- paths ----------------------------------------------------------------------------------------------

function StepDot({ step }: { step: PathStep }) {
  useLocale();
  return (
    <span
      aria-hidden
      className={cn(
        "relative z-10 mt-1 block size-3 shrink-0 rounded-full border-2",
        step.change === "removed"
          ? "border-dashed border-line-strong bg-surface"
          : step.change === "added"
            ? "border-primary bg-primary"
            : step.critical
              ? "border-ink bg-ink"
              : "border-line-strong bg-surface",
      )}
    />
  );
}

function StepCell({ step, side }: { step: PathStep; side: "base" | "scenario" }) {
  useLocale();
  const removed = step.change === "removed";
  return (
    <div className={cn("flex h-full items-start gap-2.5 rounded-md px-2.5 py-2", step.change === "added" && "bg-primary-tint", removed && "bg-sunken/70")}>
      <StepDot step={step} />
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            "text-sm leading-snug",
            removed ? "text-muted line-through decoration-line-strong" : "text-ink",
            step.change === "added" && "font-medium",
          )}
        >
          {localize(step.title)}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-2xs text-muted">
          <AreaLabel area={step.area} />
          {step.estimatedDays !== null && step.estimatedDays > 0 && <span className="tabular">{tr("copy.about_dae445c")}{localize(step.estimatedDays)} {tr("copy.days_5548ae4")}</span>}
          {step.critical && !removed && (
            <span className="inline-flex items-center gap-1 font-medium text-ink">
              <Route className="size-3" aria-hidden />
              {tr("copy.longest_chain_d20baf6")}</span>
          )}
        </p>
      </div>
      {step.change === "added" && <Badge tone="primary">{tr("copy.new_6403f2b")}</Badge>}
      {removed && <Badge tone="outline">{tr("copy.not_needed_2518be9")}</Badge>}
      {step.change === "changed" && side === "scenario" && <Badge tone="outline">{tr("copy.changed_cb5424f")}</Badge>}
    </div>
  );
}

function EmptyCell({ label }: { label: string }) {
  useLocale();
  return (
    <div className="flex h-full min-h-12 items-center gap-2 px-2.5 text-2xs text-subtle">
      <Minus className="size-3.5 shrink-0" aria-hidden />
      <span>{localize(label)}</span>
    </div>
  );
}

function PathHeader({ title, summary, tone }: { title: string; summary: PathSummary; tone: "base" | "scenario" }) {
  useLocale();
  return (
    <div className={cn("rounded-lg px-3 py-2.5", tone === "scenario" ? "bg-primary-tint/60" : "bg-sunken")}>
      <p className="text-sm font-medium">{localize(title)}</p>
      <p className="tabular text-xs text-muted">
        {localize(summary.completion.total)} {tr("copy.steps_6578912")}{summary.criticalDays > 0 ? tr("copy.longest_chain_about_v0_days_56d67e5", { v0: summary.criticalDays }) : ""}{tr("copy.text_d3bc9a3")}{localize(summary.completion.percent)}{tr("copy.done_ef97506")}</p>
    </div>
  );
}

function StackedPath({ title, summary, side, all }: { title: string; summary: PathSummary; side: "base" | "scenario"; all: boolean }) {
  useLocale();
  const steps = all ? summary.steps : focusSteps(summary.steps);
  return (
    <section aria-label={localize(title)} className="flex flex-col gap-2">
      <PathHeader title={localize(title)} summary={localize(summary)} tone={side} />
      <ol className="flex flex-col gap-1">
        {steps.map((step) => (
          <li key={step.key}>
            <StepCell step={step} side={side} />
          </li>
        ))}
      </ol>
    </section>
  );
}

function Paths({ base, scenario }: { base: PathSummary; scenario: PathSummary }) {
  const uiLocale = useLocale();
  const [mode, setMode] = useState<"focus" | "all">("focus");
  const rows = useMemo(() => alignPaths(base, scenario), [base, scenario, uiLocale]);
  const shown = mode === "all" ? rows : focusRows(rows);
  const hidden = rows.length - focusRows(rows).length;

  return (
    <section aria-labelledby="paths-title" className="@container/paths flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="paths-title" className="text-lg">
            {tr("copy.your_current_path_and_the_alternative_cbbb1e4")}</h2>
          <p className="mt-0.5 text-sm text-muted">{tr("copy.steps_in_the_order_their_dependencies_allow_earl_ea24018")}</p>
        </div>
        <Segmented
          label={tr("copy.steps_to_show_8979f4e")}
          size="sm"
          value={mode}
          onChange={setMode}
          options={[
            { value: "focus", label: tr("copy.changes_and_longest_chain_8992163") },
            { value: "all", label: tr("copy.all_steps_8c26e05") },
          ]}
        />
      </div>

      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-2xs text-muted" aria-label={tr("copy.legend_5846955")}>
        <li className="flex items-center gap-1.5">
          <span className="size-3 rounded-full border-2 border-primary bg-primary" aria-hidden />
          {tr("copy.new_step_fe37aa5")}</li>
        <li className="flex items-center gap-1.5">
          <span className="size-3 rounded-full border-2 border-dashed border-line-strong" aria-hidden />
          {tr("copy.no_longer_needed_003f751")}</li>
        <li className="flex items-center gap-1.5">
          <span className="size-3 rounded-full border-2 border-ink bg-ink" aria-hidden />
          {tr("copy.on_the_longest_chain_396609c")}</li>
      </ul>

      {/* Wide: one row per step, aligned across both plans. */}
      <div className="hidden @2xl/paths:block">
        <div className="grid grid-cols-2 gap-x-3">
          <PathHeader title={tr("copy.your_current_plan_7cf511e")} summary={localize(base)} tone="base" />
          <PathHeader title={tr("copy.with_your_changes_503a67d")} summary={localize(scenario)} tone="scenario" />
        </div>
        <ol className="mt-2 flex flex-col gap-1" aria-label={tr("copy.both_plans_step_by_step_97b8a99")}>
          {shown.map((row) => (
            <li key={row.key} className="grid grid-cols-2 gap-x-3">
              <div>{row.base ? <StepCell step={row.base} side="base" /> : <EmptyCell label={tr("copy.not_in_your_current_plan_7516347")} />}</div>
              <div>{row.scenario ? <StepCell step={row.scenario} side="scenario" /> : <EmptyCell label={tr("copy.not_needed_with_your_changes_14b537a")} />}</div>
            </li>
          ))}
        </ol>
      </div>

      {/* Narrow: each plan as its own list, one above the other. */}
      <div className="flex flex-col gap-6 @2xl/paths:hidden">
        <StackedPath title={tr("copy.your_current_plan_7cf511e")} summary={localize(base)} side="base" all={mode === "all"} />
        <StackedPath title={tr("copy.with_your_changes_503a67d")} summary={localize(scenario)} side="scenario" all={mode === "all"} />
      </div>

      {mode === "focus" && hidden > 0 && (
        <button type="button" onClick={() => setMode("all")} className="self-start text-sm font-medium text-primary-strong underline-offset-4 hover:underline">
          {tr("copy.show_all_382ebd6")}{localize(rows.length)} {tr("copy.steps_b7fe5e9")}{localize(hidden)} {tr("copy.unchanged_1a9094a")}</button>
      )}
    </section>
  );
}

// --- details ----------------------------------------------------------------------------------------------

function Details({ outcome, stageLabel }: { outcome: ScenarioOutcome; stageLabel: (id: string) => string }) {
  const uiLocale = useLocale();
  const { base, scenario, diff } = outcome;
  const actions = useMemo(() => newActions(base, scenario), [base, scenario, uiLocale]);
  const actionByKey = new Map(actions.map((a) => [a.key, a]));
  const changedActions = actions.filter((a) => !a.newStep);
  const { datesOnly, other } = splitChangedNodes(diff.changedNodes);
  const newCount = diff.addedTasks.length + changedActions.length;

  const actionLine = (key: string) => {
    const action = actionByKey.get(key);
    if (!action) return null;
    return (
      <div className="mt-1 flex flex-col gap-1 text-xs text-muted">
        <span>
          {tr("copy.next_action_7a21525")}<span className="text-ink">{localize(action.label)}</span>
          {action.url && (
            <>
              {localize(" ")}
              <a
                href={action.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 font-medium text-primary-strong underline-offset-4 hover:underline"
              >
                {tr("copy.on_03fcaa9")}{localize(domainOf(action.url))}
                <ExternalLink className="size-3" aria-hidden />
                <span className="sr-only">{tr("copy.opens_the_official_site_in_a_new_tab_2cd60b0")}</span>
              </a>
            </>
          )}
        </span>
        {action.requiresUserAuthentication && (
          <span className="inline-flex items-center gap-1">
            <KeyRound className="size-3 text-primary" aria-hidden />
            {tr("copy.you_sign_in_with_uae_pass_on_the_official_site_80b865f")}</span>
        )}
      </div>
    );
  };

  const nothing = !newCount && !diff.removedTasks.length && !diff.changedDependencies.length && !diff.changedRisks.length && !diff.changedNodes.length;

  return (
    <div className="@container/details">
      {nothing ? (
        <p className="text-sm text-muted">{tr("copy.nothing_else_about_your_steps_dependencies_or_ri_5641b13")}</p>
      ) : (
        <div className="grid gap-x-8 gap-y-8 @2xl/details:grid-cols-2">
          {newCount > 0 && (
            <Section icon={<Sparkles className="size-4" />} title={tr("copy.new_actions_98fa5e5")} count={newCount}>
              <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
                {diff.addedTasks.map((task) => (
                  <li key={task.key} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm font-medium">{localize(task.title)}</p>
                      <Badge tone="primary">{tr("copy.new_step_fe37aa5")}</Badge>
                    </div>
                    <AreaLabel area={task.area} className="mt-1" />
                    {localize(actionLine(task.key))}
                  </li>
                ))}
                {changedActions.map((action) => (
                  <li key={action.key} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm font-medium">{localize(action.title)}</p>
                      <Badge tone="outline">{tr("copy.new_action_04438cc")}</Badge>
                    </div>
                    <AreaLabel area={action.area} className="mt-1" />
                    {localize(actionLine(action.key))}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {diff.removedTasks.length > 0 && (
            <Section icon={<ListChecks className="size-4" />} title={tr("copy.steps_you_would_no_longer_need_98c570f")} count={diff.removedTasks.length}>
              <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
                {diff.removedTasks.map((task) => (
                  <li key={task.key} className="flex items-center justify-between gap-3 px-4 py-3">
                    <span className="text-sm text-muted line-through decoration-line-strong">{localize(task.title)}</span>
                    <AreaLabel area={task.area} className="shrink-0" />
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {diff.changedDependencies.length > 0 && (
            <Section icon={<Link2 className="size-4" />} title={tr("copy.what_waits_for_what_786e633")} count={diff.changedDependencies.length}>
              <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
                {diff.changedDependencies.map((dep) => (
                  <li key={`${dep.change}-${dep.source}-${dep.target}-${dep.relation}`} className="flex items-start gap-3 px-4 py-3 text-sm">
                    {dep.change === "added" ? (
                      <Link2 className="mt-0.5 size-4 shrink-0 text-ink" aria-hidden />
                    ) : (
                      <Unlink className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
                    )}
                    <span>
                      <span className="font-medium">{localize(dep.sourceTitle)}</span> {dep.change === "added" ? tr("copy.now_waits_for_84aa030") : tr("copy.no_longer_waits_for_109f7fd")}{localize(" ")}
                      <span className="font-medium">{localize(dep.targetTitle)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {diff.changedRisks.length > 0 && (
            <Section icon={<ShieldAlert className="size-4" />} title={tr("copy.risks_92ddd0d")} count={diff.changedRisks.length}>
              <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
                {diff.changedRisks.map((risk) => (
                  <li key={`${risk.id}-${risk.change}`} className="flex flex-col gap-1.5 px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={risk.change === "removed" ? "outline" : SEVERITY[risk.severity].tone}>{localize(SEVERITY[risk.severity].label)}</Badge>
                      <span className="text-xs text-muted">{localize(RISK_CHANGE[risk.change])}</span>
                    </div>
                    <p className={cn("text-sm", risk.change === "removed" ? "text-muted line-through decoration-line-strong" : "font-medium")}>{localize(risk.title)}</p>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {diff.changedNodes.length > 0 && (
            <Section icon={<CalendarClock className="size-4" />} title={tr("copy.steps_that_change_c1552eb")} count={diff.changedNodes.length}>
              <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
                {other.map((change) => (
                  <li key={change.key} className="px-4 py-3">
                    <p className="text-sm font-medium">{localize(change.title)}</p>
                    <ul className="mt-1 flex flex-col gap-0.5">
                      {change.fields.map((field) => {
                        const d = describeFieldChange(base, scenario, change.key, field);
                        return (
                          <li key={field} className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted">
                            <span>{localize(d.field)}{tr("copy.text_05a79f0")}</span>
                            {d.from && d.to ? (
                              <>
                                <span>{localize(d.from)}</span>
                                <ArrowRight className="flip-rtl size-3" aria-label={tr("copy.changes_to_eda9ea7")} />
                                <span className="text-ink">{localize(d.to)}</span>
                              </>
                            ) : (
                              <span>{tr("copy.changes_49a04ba")}</span>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </li>
                ))}
                {datesOnly.length > 0 && (
                  <li className="px-4 py-3">
                    <details className="group">
                      <summary className="flex min-h-8 cursor-pointer list-none items-center justify-between gap-3 text-sm [&::-webkit-details-marker]:hidden">
                        <span>
                          <span className="font-medium">{tr("copy.target_dates_move_8a64d9f")}</span> {tr("copy.for_79e2a21")}{localize(datesOnly.length)} {datesOnly.length === 1 ? tr("copy.step_bd370d1") : tr("copy.steps_6578912")}
                        </span>
                        <span className="text-xs font-medium text-primary-strong group-open:hidden">{tr("copy.show_d97d1ee")}</span>
                        <span className="hidden text-xs font-medium text-primary-strong group-open:inline">{tr("copy.hide_34d8b60")}</span>
                      </summary>
                      <ul className="mt-2 flex flex-col gap-1">
                        {datesOnly.map((change) => {
                          const d = describeFieldChange(base, scenario, change.key, "dueBy");
                          return (
                            <li key={change.key} className="flex flex-wrap items-center justify-between gap-x-3 text-xs">
                              <span className="text-ink">{localize(change.title)}</span>
                              <span className="tabular flex items-center gap-1.5 text-muted">
                                {localize(d.from)}
                                <ArrowRight className="flip-rtl size-3" aria-label={tr("copy.moves_to_7d62c4e")} />
                                <span className="text-ink">{localize(d.to)}</span>
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    </details>
                  </li>
                )}
              </ul>
            </Section>
          )}
        </div>
      )}

      {diff.rerunStages.length > 0 && (
        <div className="mt-8 flex flex-wrap items-center gap-2 border-t border-line pt-4 text-xs text-muted">
          <span>{tr("copy.adapt_re_ran_c91d45f")}</span>
          {diff.rerunStages.map((id) => (
            <Badge key={id} tone="outline">
              {localize(stageLabel(id))}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

// --- results ------------------------------------------------------------------------------------------------

export function Results({
  outcome,
  stale,
  running,
  onRerun,
  stageLabel,
}: {
  outcome: ScenarioOutcome;
  stale: boolean;
  running: boolean;
  onRerun: () => void;
  stageLabel: (id: string) => string;
}) {
  const uiLocale = useLocale();
  const base = useMemo(() => pathSummary(outcome.base, outcome.diff, "base"), [outcome, uiLocale]);
  const scenario = useMemo(() => pathSummary(outcome.scenario, outcome.diff, "scenario"), [outcome, uiLocale]);
  return (
    <div className={cn("flex flex-col gap-8 transition-opacity", stale && "opacity-80")}>
      <div className="flex flex-col gap-4">
        <SimulationNotice stale={stale} onRerun={onRerun} running={running} />
        <Summary outcome={outcome} base={base} scenario={scenario} />
      </div>
      <Paths base={base} scenario={scenario} />
      <section aria-labelledby="details-title" className="flex flex-col gap-4">
        <h2 id="details-title" className="text-lg">
          {tr("copy.what_else_changes_d1c5d34")}</h2>
        <Details outcome={outcome} stageLabel={stageLabel} />
      </section>
      <p className="flex items-center gap-2 border-t border-line pt-4 text-sm text-muted">
        <FlaskConical className="size-4 shrink-0" aria-hidden />
        {tr("copy.your_plan_hasn_t_changed_this_is_a_simulation_7251e5a")}</p>
    </div>
  );
}
