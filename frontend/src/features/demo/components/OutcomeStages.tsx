import { tr, localize, useLocale } from "@/i18n";
import { ExternalLink, KeyRound, Minus } from "lucide-react";
import { useMemo } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/Progress";
import { toast } from "@/components/ui/Toast";
import { TrustBadge } from "@/components/ui/TrustBadge";
import { ACTION_KIND_LABEL, domainOf } from "@/domain/common";
import type { DiscoverItem, ResearchStatus } from "@/domain/discover";
import type { ScenarioResearchGroup, ScenarioRoleRef } from "@/domain/scenario";
import type { ScenarioOutcome, SimulationProgress } from "@/domain/simulate";
import { ACTION_CARD_HINT, actionCardLabels, type ActionCardLabel } from "@/lib/actionCard";
import { useActions, useApprovals, useDecideApproval, useDiscoverItems } from "@/lib/api/hooks";
import { describeError } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { removedBy } from "../chain";
import { PlanChain } from "./PlanChain";

const SOURCE_LABEL: Record<string, string> = {
  official: tr("copy.official_ac60fda", { lng: "en" }),
  organization: tr("copy.organisation_6e99c1d", { lng: "en" }),
  community: tr("copy.community_bfd58ee", { lng: "en" }),
  general_web: tr("copy.general_web_2685d88", { lng: "en" }),
};

function pathOf(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname.replace(/^www\./, "")}${parsed.pathname === "/" ? "" : parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}

function ResearchCard({ item }: { item: DiscoverItem }) {
  useLocale();
  return (
    <article className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <TrustBadge kind={item.evidenceKind} />
        <span className="text-2xs text-muted">{localize(SOURCE_LABEL[item.source.label] ?? item.source.label)}</span>
      </div>
      <p className="text-sm font-medium">{localize(item.title)}</p>
      {item.relevance && <p className="text-xs text-muted">{localize(item.relevance)}</p>}
      <dl className="mt-auto grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-line pt-2 text-2xs">
        <dt className="text-subtle">{tr("copy.source_6da13ad")}</dt>
        <dd className="min-w-0">
          {item.source.url ? (
            <a href={item.source.url} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-full items-center gap-1 text-ink underline-offset-4 hover:underline">
              <span className="truncate">{localize(pathOf(item.source.url))}</span>
              <ExternalLink className="size-3 shrink-0" aria-hidden />
              <span className="sr-only">{tr("copy.opens_in_a_new_tab_bf5b990")}</span>
            </a>
          ) : (
            item.source.title
          )}
        </dd>
        <dt className="text-subtle">{tr("copy.retrieved_5538ffd")}</dt>
        <dd>{localize(formatDate(item.retrieval?.retrievedAt ?? item.lastCheckedAt))}</dd>
        <dt className="text-subtle">{tr("copy.how_0c81abc")}</dt>
        <dd title={localize(item.retrieval?.note)}>{localize(item.retrieval?.label ?? tr("copy.adapt_reviewed_source_list_cb8d5e3"))}</dd>
      </dl>
    </article>
  );
}

export function ResearchStage({ status, groups }: { status: ResearchStatus | null; groups: ScenarioResearchGroup[] }) {
  useLocale();
  const items = useDiscoverItems();
  if (!status || status.state === "idle") return null;
  const done = status.categories.filter((c) => c.status === "completed" || c.status === "skipped").length;
  return (
    <div className="flex flex-col gap-5">
      {status.state === "running" && (
        <ProgressBar value={status.categories.length ? done / status.categories.length : 0.05} label={localize(tr("copy.researching_in_the_background_v0_of_v1_topics_62aa279", { v0: done, v1: status.categories.length }))} />
      )}
      <p className="text-sm text-muted">
        {status.mode === "snapshot"
          ? tr("copy.results_come_from_adapt_s_reviewed_source_list_r_ebead53")
          : tr("copy.results_come_from_a_live_web_search_adapt_keeps__eabc1c4")}
        {status.personalisedWith.length > 0 && tr("copy.personalised_with_v0_bd25007", { v0: status.personalisedWith.join("; ") })}
      </p>
      {groups.map((group) => {
        const inGroup = (items.data ?? []).filter((i) => group.sections.includes(i.section));
        // Results personalised from Kabir's own facts lead; generic newcomer suggestions follow.
        const personal = inGroup.filter((i) => i.factIds.length > 0);
        const found = personal.length ? personal : inGroup;
        const also = personal.length ? inGroup.filter((i) => i.factIds.length === 0) : [];
        return (
          <section key={group.key} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-base font-medium">{localize(group.title)}</h3>
              <span className="text-xs text-muted">{localize(group.description)}</span>
            </div>
            {found.length ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {found.slice(0, 6).map((item) => (
                  <ResearchCard key={item.id} item={item} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">{status.state === "running" ? tr("copy.looking_0fad6a2") : tr("copy.nothing_matched_for_this_topic_2a7f86f")}</p>
            )}
            {also.length > 0 && <p className="text-xs text-muted">{tr("copy.also_suggested_for_any_newcomer_51bf76f")}{localize(also.map((i) => i.title).join(", "))}{tr("copy.text_3a52ce7")}</p>}
          </section>
        );
      })}
    </div>
  );
}

export function WhatIfStage({
  outcome,
  progress,
  roles,
}: {
  outcome: ScenarioOutcome | null;
  progress: SimulationProgress | null;
  roles: ScenarioRoleRef[];
}) {
  const uiLocale = useLocale();
  const removed = useMemo(() => (outcome ? removedBy(outcome.base, outcome.scenario) : null), [outcome, uiLocale]);
  if (!outcome) {
    return progress ? <ProgressBar value={progress.progress} label={localize(tr("copy.simulating_on_a_copy_of_the_plan_v0_fa5f784", { v0: progress.label }))} /> : null;
  }
  const { base, scenario, diff } = outcome;
  const title = (key: string) => base.nodes.find((n) => n.key === key)?.title ?? key;
  const movedFindings = base.considerations.filter((c) => !scenario.considerations.some((s) => s.id === c.id));
  const lostDeps = diff.changedDependencies
    .filter((d) => d.change === "removed")
    .sort((a, b) => title(a.source).localeCompare(title(b.source)) || title(a.target).localeCompare(title(b.target)));
  return (
    <div className="flex flex-col gap-5">
      <p className="text-base">{localize(diff.summary)}</p>
      <dl className="grid grid-cols-3 gap-3">
        {[
          { label: tr("copy.steps_that_leave_the_first_arrival_plan_d3fa80a"), value: diff.removedTasks.length },
          { label: tr("copy.dependencies_that_disappear_e876e08"), value: lostDeps.length },
          { label: tr("copy.findings_that_move_to_ayesha_s_later_phase_e04e7a1"), value: movedFindings.length },
        ].map((stat) => (
          <div key={stat.label} className="rounded-lg border border-line bg-surface p-3">
            <dd className="font-display text-3xl tabular">{localize(stat.value)}</dd>
            <dt className="text-xs text-muted">{localize(stat.label)}</dt>
          </div>
        ))}
      </dl>
      {removed && <PlanChain journey={base} roles={roles} removed={removed} />}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="flex flex-col gap-2">
          <h3 className="text-base font-medium">{tr("copy.what_no_longer_waits_for_what_24c35d2")}</h3>
          <ul className="flex flex-col gap-1 text-sm">
            {lostDeps.slice(0, 8).map((d) => (
              <li key={`${d.source}<-${d.target}`} className="flex gap-2">
                <Minus className="mt-1 size-3.5 shrink-0 text-danger" aria-hidden />
                <span>
                  {localize(title(d.source))} <span className="text-muted">{tr("copy.no_longer_waits_for_109f7fd")}</span> {localize(title(d.target))}
                </span>
              </li>
            ))}
            {lostDeps.length > 8 && <li className="text-muted">{tr("copy.and_97e2118")}{localize(lostDeps.length - 8)} {tr("copy.more_e7c95b4")}</li>}
          </ul>
        </section>
        <section className="flex flex-col gap-2">
          <h3 className="text-base font-medium">{tr("copy.findings_for_later_7e2e5f4")}</h3>
          {movedFindings.length ? (
            <ul className="flex flex-col gap-2 text-sm">
              {movedFindings.map((c) => (
                <li key={c.id} className="rounded-md border border-dashed border-line-strong px-3 py-2">
                  {localize(c.title)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">{tr("copy.the_same_findings_apply_53ef732")}</p>
          )}
          <p className="text-xs text-muted">{tr("copy.the_real_plan_is_unchanged_this_ran_on_a_copy_an_b460110")}</p>
        </section>
      </div>
    </div>
  );
}

const LABEL_TONE: Record<ActionCardLabel, "neutral" | "ink" | "civic" | "simulated"> = {
  Prepared: "neutral",
  "Approval required": "ink",
  "Official handoff": "civic",
  "Demo adapter": "simulated",
};

export function ActionsStage() {
  useLocale();
  const actions = useActions();
  const approvals = useApprovals();
  const decide = useDecideApproval();
  const approvalFor = (actionId: string) => approvals.data?.find((a) => a.actionId === actionId);
  if (!actions.data?.length) return <p className="text-sm text-muted">{tr("copy.no_actions_prepared_yet_af8b905")}</p>;
  // A fixed order (decisions first, then by title): the API lists actions created together
  // in no particular order, and every run of the demo should look the same.
  const ordered = [...actions.data].sort(
    (a, b) => Number(approvalFor(b.id)?.status === "pending") - Number(approvalFor(a.id)?.status === "pending") || a.title.localeCompare(b.title),
  );
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        {tr("copy.adapt_has_no_government_integration_so_nothing_b_d8bd145")}</p>
      <div className="grid gap-3 lg:grid-cols-2">
        {ordered.map((action) => {
          const approval = approvalFor(action.id);
          const labels = actionCardLabels({ status: action.status, kind: action.kind, isSimulated: action.isSimulated, approvalStatus: approval?.status });
          const pending = approval?.status === "pending";
          return (
            <article key={action.id} className={cn("flex flex-col gap-3 rounded-xl border bg-surface p-4", pending ? "border-ink/70 shadow-card" : "border-line")}>
              <div className="flex flex-wrap items-center gap-1.5">
                {labels.map((label) => (
                  <Badge key={label} tone={LABEL_TONE[label]} title={localize(ACTION_CARD_HINT[label])}>
                    {localize(label)}
                  </Badge>
                ))}
                <span className="ms-auto text-2xs text-subtle">{localize(ACTION_KIND_LABEL[action.kind])}</span>
              </div>
              <div>
                <h3 className="text-base font-medium">{localize(action.title)}</h3>
                <p className="mt-0.5 text-sm text-muted">{localize(action.message)}</p>
              </div>
              {approval && approval.consequences.length > 0 && (
                <ul className="flex flex-col gap-1 text-xs text-muted">
                  {approval.consequences.slice(0, 3).map((c) => (
                    <li key={c}>{localize(c)}</li>
                  ))}
                </ul>
              )}
              <div className="mt-auto flex flex-wrap items-center gap-2">
                {pending && (
                  <Button
                    size="sm"
                    loading={decide.isPending && decide.variables?.id === approval.id}
                    onClick={() =>
                      decide.mutate(
                        { id: approval.id, decision: "approve" },
                        { onError: (error) => toast({ title: describeError(error).title, description: describeError(error).detail, tone: "error" }) },
                      )
                    }
                  >
                    {tr("copy.approve_7b2c7f1")}</Button>
                )}
                {action.handoffUrl && (action.status === "handoff_required" || action.kind === "official_handoff") && (
                  <a href={action.handoffUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm text-primary underline-offset-4 hover:underline">
                    {tr("copy.continue_on_9d5570d")}{localize(domainOf(action.handoffUrl))}
                    <ExternalLink className="size-3.5" aria-hidden />
                    <span className="sr-only">{tr("copy.opens_the_official_site_in_a_new_tab_2cd60b0")}</span>
                  </a>
                )}
              </div>
              {action.status === "handoff_required" && (
                <p className="flex items-start gap-2 text-xs text-muted">
                  <KeyRound className="mt-0.5 size-3.5 shrink-0 text-primary" aria-hidden />
                  {tr("copy.kabir_finishes_this_on_the_official_site_with_hi_cf97a18")}</p>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
