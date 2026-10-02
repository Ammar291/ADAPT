import { tr, localize, useLocale } from "@/i18n";
import { CircleAlert, Lightbulb, Quote } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { AreaLabel, laneColor } from "@/components/ui/AreaLabel";
import { Button, buttonClass } from "@/components/ui/Button";
import { SourceLink } from "@/components/ui/SourceLink";
import { TrustBadge } from "@/components/ui/TrustBadge";
import type { Journey, JourneyNode } from "@/domain/journey";
import type { ScenarioRoleRef } from "@/domain/scenario";
import { useAnswerNode, useApprovals } from "@/lib/api/hooks";
import { describeError } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { useRunEvents } from "@/lib/events/useRunEvents";
import { PlanChain } from "./PlanChain";

function AgentStages({ runId }: { runId: string }) {
  useLocale();
  const { view } = useRunEvents(runId);
  if (!view.order.length) return null;
  return (
    <ol className="flex flex-wrap gap-1.5" aria-label={tr("copy.journey_agent_stages_79beea6")} aria-live="polite">
      {view.order.map((id) => {
        const stage = view.stages[id]!;
        return (
          <li
            key={id}
            className={cn(
              "rounded-md border px-2 py-1 text-2xs",
              stage.status === "complete" && "border-primary/40 bg-primary-tint text-primary-strong",
              stage.status === "running" && "border-ink/60 bg-surface font-medium",
              (stage.status === "awaiting" || stage.status === "blocked") && "border-ink bg-ink text-canvas",
              stage.status === "queued" && "border-line text-subtle",
              stage.status === "failed" && "border-danger text-danger",
            )}
            title={localize(stage.summary ?? stage.message ?? undefined)}
          >
            {localize(stage.label)}
          </li>
        );
      })}
    </ol>
  );
}

function MissingInformation({ journey, node }: { journey: Journey; node: JourneyNode }) {
  useLocale();
  const blocker = node.blockers.find((b) => b.kind === "missing_info");
  const answer = useAnswerNode();
  const [value, setValue] = useState("");
  if (!blocker) return null;
  const question = node.questions?.[0]?.question ?? (node.action?.kind === "answer_question" ? node.action.question : null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (value.trim()) answer.mutate([journey.id, node.key, value.trim()]);
  };
  return (
    <section className="flex flex-col gap-2 rounded-xl border border-danger/50 bg-danger-tint p-4" aria-label={tr("copy.missing_information_67cc34b")}>
      <p className="flex items-center gap-2 font-medium text-danger">
        <CircleAlert className="size-4" aria-hidden />
        {localize(blocker.message)}
      </p>
      <p className="text-sm">
        {tr("copy.on_e8c6ccc")}<span className="font-medium">{localize(node.title)}</span>{tr("copy.adapt_doesn_t_guess_an_eligibility_fact_no_docum_bd966cc")}</p>
      {question && (
        <form onSubmit={submit} className="mt-1 flex flex-wrap items-end gap-2">
          <label className="flex min-w-56 flex-1 flex-col gap-1 text-xs text-muted">
            {localize(question)}
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              inputMode="numeric"
              className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-ink"
              placeholder={tr("copy.optional_answer_live_a5bfed2")}
            />
          </label>
          <Button type="submit" variant="secondary" size="sm" loading={answer.isPending} disabled={!value.trim()}>
            {tr("copy.answer_a16a4ed")}</Button>
          {answer.isError && <span className="text-xs text-danger">{localize(describeError(answer.error).title)}</span>}
        </form>
      )}
    </section>
  );
}

function EvidenceList({ journey, roles }: { journey: Journey; roles: ScenarioRoleRef[] }) {
  useLocale();
  const featured = roles.filter((r) => r.role !== "missing_information");
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {featured.map((role) => {
        const node = journey.nodes.find((n) => n.key === role.nodeKey);
        if (!node) return null;
        const citation = node.evidence.citations.find((c) => c.quote) ?? node.evidence.citations[0];
        return (
          <article key={role.role} className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-sm bg-ink px-1.5 text-[11px] leading-5 font-medium text-canvas">{localize(role.label)}</span>
              <TrustBadge kind={node.evidence.kind} />
            </div>
            <p className="text-sm font-medium">{localize(node.title)}</p>
            {citation?.quote && (
              <blockquote className="flex gap-2 border-s-2 border-civic ps-2.5 text-xs text-muted">
                <Quote className="mt-0.5 size-3 shrink-0 text-civic" aria-hidden />
                <span className="line-clamp-4">{localize(citation.quote)}</span>
              </blockquote>
            )}
            {citation ? (
              <SourceLink title={localize(citation.title)} url={citation.url} checkedAt={citation.retrievedAt} authority={citation.authority} className="mt-auto" />
            ) : (
              <p className="text-xs text-muted">{tr("copy.no_official_source_is_attached_to_this_step_0cac674")}</p>
            )}
          </article>
        );
      })}
    </div>
  );
}

export function PlanStage({ journey, runId, roles }: { journey: Journey | null; runId: string | null; roles: ScenarioRoleRef[] }) {
  useLocale();
  const pending = useApprovals("pending");
  const [focus, setFocus] = useState<string | null>(roles.find((r) => r.role === "family")?.nodeKey ?? null);
  const blockedKey = roles.find((r) => r.role === "missing_information")?.nodeKey;
  const blockedNode = journey?.nodes.find((n) => n.key === blockedKey);
  const cited = journey?.nodes.filter((n) => n.evidence.citations.length > 0).length ?? 0;

  return (
    <div className="flex flex-col gap-5">
      {runId && <AgentStages runId={runId} />}
      {journey && (
        <>
          <p className="text-sm text-muted">
            {localize(journey.nodes.length)} {tr("copy.steps_and_b32d33d")}{localize(journey.edges.length)} {tr("copy.dependencies_all_taken_from_the_cited_governance_718094d")}{localize(cited)} {tr("copy.steps_link_to_an_official_page_e87722c")}{pending.data && pending.data.length > 0 && tr("copy.the_agent_paused_for_kabir_s_approval_on_v0_prep_f5224f7", { v0: pending.data.length })}
          </p>
          <div className="flex flex-wrap gap-2" role="toolbar" aria-label={tr("copy.highlight_a_step_s_chain_e661f4e")}>
            {roles
              .filter((r) => r.role !== "missing_information")
              .map((role) => {
                const node = journey.nodes.find((n) => n.key === role.nodeKey);
                return (
                  <button
                    key={role.role}
                    type="button"
                    onClick={() => setFocus(focus === role.nodeKey ? null : role.nodeKey)}
                    aria-pressed={focus === role.nodeKey}
                    className={cn(
                      "flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-start text-xs",
                      focus === role.nodeKey ? "border-ink bg-ink text-canvas" : "border-line bg-surface hover:border-ink/40",
                    )}
                  >
                    {node && <span className="h-4 w-1 rounded-full" style={{ background: laneColor(node.area) }} aria-hidden />}
                    <span>
                      <span className="block font-medium">{localize(role.label)}</span>
                      <span className={cn("block", focus === role.nodeKey ? "text-canvas/75" : "text-muted")}>{localize(node?.title ?? tr("copy.not_in_this_plan_61127c3"))}</span>
                    </span>
                  </button>
                );
              })}
          </div>
          <PlanChain journey={journey} roles={roles} focus={focus} />
          {blockedNode && <MissingInformation journey={journey} node={blockedNode} />}
          <div className="flex flex-col gap-2">
            <h3 className="text-base font-medium">{tr("copy.evidence_behind_the_major_requirements_fe04482")}</h3>
            <EvidenceList journey={journey} roles={roles} />
          </div>
          <Link to="/journey" className={buttonClass("secondary", "sm", "self-start")}>
            {tr("copy.open_the_full_journey_map_867480a")}</Link>
        </>
      )}
    </div>
  );
}

export function ConsiderationsStage({ journey }: { journey: Journey }) {
  useLocale();
  if (!journey.considerations.length) {
    return <p className="text-sm text-muted">{tr("copy.nothing_extra_to_point_out_for_this_plan_c47808e")}</p>;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {journey.considerations.map((item) => (
        <article key={item.id} className="flex flex-col gap-3 rounded-xl border border-line-strong bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between gap-2">
            <AreaLabel area={item.area} />
            <Lightbulb className="size-4 text-primary" aria-hidden />
          </div>
          <h3 className="text-lg leading-snug">{localize(item.title)}</h3>
          <p className="text-sm leading-relaxed text-muted">{localize(item.detail)}</p>
          <div className="mt-auto flex flex-col gap-2 border-t border-line pt-3">
            <span className="flex items-center gap-2 text-xs text-muted">
              {tr("copy.based_on_81df654")}<TrustBadge kind={item.evidence.kind} />
            </span>
            {[...new Map(item.evidence.citations.map((c) => [c.url, c])).values()].slice(0, 3).map((c) => (
              <SourceLink key={c.url} title={localize(c.title)} url={c.url} checkedAt={c.retrievedAt} authority={c.authority} />
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}
