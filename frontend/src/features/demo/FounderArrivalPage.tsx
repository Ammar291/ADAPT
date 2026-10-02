import { tr, localize, useLocale } from "@/i18n";
import { Check, CircleAlert, Pause, Play, RotateCcw, StepForward } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/Badge";
import { Button, buttonClass } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorState, LoadingRows, UnavailableState } from "@/components/ui/States";
import type { DemoScenario } from "@/domain/scenario";
import { cn } from "@/lib/cn";
import { DocumentsStage } from "./components/DocumentsStage";
import { ActionsStage, ResearchStage, WhatIfStage } from "./components/OutcomeStages";
import { ConsiderationsStage, PlanStage } from "./components/PlanStage";
import { ACT_ORDER, type ActKey, type ActStatus, type FounderArrival, useFounderArrival } from "./useFounderArrival";

const RUN_LABEL: Record<ActKey, string> = {
  profile: tr("copy.save_kabir_s_profile_fd92cc0", { lng: "en" }),
  documents: tr("copy.upload_and_read_the_documents_52ea560", { lng: "en" }),
  plan: tr("copy.build_the_settlement_plan_d3d00d2", { lng: "en" }),
  considerations: tr("copy.show_the_findings_66a11bf", { lng: "en" }),
  research: tr("copy.start_background_research_fe10d6f", { lng: "en" }),
  what_if: tr("copy.run_the_what_if_a6b9669", { lng: "en" }),
  actions: tr("copy.show_the_action_cards_35d7728", { lng: "en" }),
};

const LINK: Partial<Record<ActKey, { to: string; label: string }>> = {
  documents: { to: "/documents", label: tr("copy.documents_687c828", { lng: "en" }) },
  plan: { to: "/agents", label: tr("copy.agent_run_f5b3ee2", { lng: "en" }) },
  research: { to: "/discover", label: tr("copy.discover_4827ea2", { lng: "en" }) },
  what_if: { to: "/simulate", label: tr("copy.what_if_9b0576a", { lng: "en" }) },
  actions: { to: "/approvals", label: tr("copy.approvals_deb9d03", { lng: "en" }) },
};

function StatusMark({ status, number }: { status: ActStatus; number: number }) {
  useLocale();
  if (status === "done") return <Check className="size-4" aria-hidden />;
  if (status === "running") return <Spinner className="size-4" />;
  if (status === "failed") return <CircleAlert className="size-4" aria-hidden />;
  return <span className="tabular text-xs">{localize(number)}</span>;
}

function ActRail({ scenario, state }: { scenario: DemoScenario; state: FounderArrival }) {
  useLocale();
  return (
    <nav aria-label={tr("copy.demo_acts_f0222e3")} className="sticky top-0 z-20 -mx-1 border-b border-line bg-canvas/95 px-1 py-2 backdrop-blur">
      <ol className="flex gap-1 overflow-x-auto">
        {ACT_ORDER.map((act, index) => {
          const status = state.statusOf(act);
          const meta = scenario.acts.find((a) => a.key === act);
          return (
            <li key={act} className="shrink-0">
              <a
                href={`#act-${act}`}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm",
                  status === "locked" ? "text-subtle" : "text-ink hover:bg-sunken",
                  status === "running" && "bg-sunken font-medium",
                )}
              >
                <span
                  className={cn(
                    "grid size-6 shrink-0 place-items-center rounded-full border",
                    status === "done" && "border-primary bg-primary text-on-primary",
                    status === "running" && "border-ink",
                    status === "failed" && "border-danger text-danger",
                    (status === "ready" || status === "locked") && "border-line-strong",
                  )}
                >
                  <StatusMark status={status} number={index + 1} />
                </span>
                <span className="whitespace-nowrap">{localize(meta?.title ?? act)}</span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function Act({ act, scenario, state, children }: { act: ActKey; scenario: DemoScenario; state: FounderArrival; children?: ReactNode }) {
  useLocale();
  const status = state.statusOf(act);
  const meta = scenario.acts.find((a) => a.key === act);
  const link = LINK[act];
  const canRun = (status === "ready" || status === "failed") && !state.busy && !state.isPlaying;
  return (
    <section id={`act-${act}`} aria-labelledby={`act-${act}-title`} className={cn("scroll-mt-16 border-t border-line pt-6", status === "locked" && "opacity-55")}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={`act-${act}-title`} className="font-display text-2xl leading-tight">
            {localize(meta?.title)}
          </h2>
          <p className="mt-1 max-w-[62ch] text-sm text-muted">{localize(meta?.description)}</p>
        </div>
        <div className="flex items-center gap-2">
          {link && status === "done" && (
            <Link to={link.to} className={buttonClass("ghost", "sm")}>
              {tr("copy.open_79d37e2")}{localize(link.label)}
            </Link>
          )}
          {status !== "done" && (
            <Button size="sm" variant={act === state.next ? "primary" : "secondary"} disabled={!canRun} loading={status === "running"} onClick={() => void state.run(act)}>
              {status === "failed" ? tr("copy.try_again_042c862") : RUN_LABEL[act]}
            </Button>
          )}
        </div>
      </header>
      {state.failed?.act === act && <p className="mb-4 rounded-md bg-danger-tint px-3 py-2 text-sm text-danger">{localize(state.failed.message)}</p>}
      {localize(children)}
    </section>
  );
}

function Persona({ scenario }: { scenario: DemoScenario }) {
  useLocale();
  return (
    <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div>
        <p className="font-display text-3xl leading-tight">{localize(scenario.persona.name)}</p>
        <p className="mt-1 text-muted">{localize(scenario.persona.headline)}</p>
        <p className="mt-3 max-w-[62ch] leading-relaxed">{localize(scenario.persona.summary)}</p>
      </div>
      <dl className="divide-y divide-line rounded-xl border border-line bg-surface">
        {scenario.persona.facts.map((fact) => (
          <div key={fact.label} className="flex items-start justify-between gap-3 px-3 py-2 text-sm">
            <dt className="text-muted">{localize(fact.label)}</dt>
            <dd className="flex flex-col items-end gap-1 text-end">
              <span>{localize(fact.value)}</span>
              <Badge tone={fact.source === "document" ? "primary" : fact.source === "missing" ? "danger" : "neutral"}>
                {fact.source === "document" ? tr("copy.from_a_document_446794d") : fact.source === "missing" ? tr("copy.not_known_9feddee") : tr("copy.stated_763f230")}
              </Badge>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function FounderArrivalPage() {
  useLocale();
  const state = useFounderArrival();
  if (!state.available) {
    return (
      <UnavailableState
        title={tr("copy.the_founder_arrival_demo_runs_on_the_adapt_api_2f6f134")}
        description={tr("copy.start_the_backend_with_demo_sign_in_enabled_the__68e8d21")}
      />
    );
  }
  if (state.scenario.isPending) return <LoadingRows rows={4} label={tr("copy.loading_the_demo_script_11e43ec")} />;
  if (state.scenario.isError || !state.scenario.data) return <ErrorState error={state.scenario.error} onRetry={() => void state.scenario.refetch()} />;
  const scenario = state.scenario.data;
  const plan = state.plan;
  const opened = (act: ActKey) => state.statusOf(act) === "done";

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl leading-none">{localize(scenario.title)}</h1>
            <p className="mt-2 max-w-[62ch] text-muted">{localize(scenario.tagline)}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" icon={<RotateCcw className="size-4" aria-hidden />} onClick={() => void state.freshStart()} disabled={state.busy !== null}>
              {tr("copy.start_a_fresh_run_784bd74")}</Button>
            {state.isPlaying ? (
              <Button variant="secondary" icon={<Pause className="size-4" aria-hidden />} onClick={state.stop}>
                {tr("copy.pause_after_this_act_d80f849")}</Button>
            ) : (
              <>
                <Button variant="secondary" icon={<Play className="size-4" aria-hidden />} onClick={() => void state.playAll()} disabled={state.busy !== null || state.next === null}>
                  {tr("copy.play_all_ebb2ffd")}</Button>
                <Button icon={<StepForward className="size-4" aria-hidden />} onClick={() => state.next && void state.run(state.next)} disabled={state.busy !== null || state.next === null}>
                  {tr("copy.continue_2e02623")}</Button>
              </>
            )}
          </div>
        </div>
        <p className="rounded-md border border-dashed border-line-strong px-3 py-2 text-sm text-muted">
          {localize(scenario.syntheticNotice)} {tr("copy.every_result_below_comes_from_adapt_s_real_pipel_97bc68b")}</p>
      </header>

      <div className="flex flex-col gap-6">
        <ActRail scenario={scenario} state={state} />
        <div className="flex min-w-0 flex-col gap-8">
          <Act act="profile" scenario={scenario} state={state}>
            <Persona scenario={scenario} />
          </Act>
          <Act act="documents" scenario={scenario} state={state}>
            {(state.statusOf("documents") !== "locked" || state.docs.some((d) => d.upload)) && <DocumentsStage docs={state.docs} />}
          </Act>
          <Act act="plan" scenario={scenario} state={state}>
            {(plan || state.planRunId) && <PlanStage journey={plan} runId={state.planRunId} roles={scenario.roles} />}
          </Act>
          <Act act="considerations" scenario={scenario} state={state}>
            {plan && opened("considerations") && <ConsiderationsStage journey={plan} />}
          </Act>
          <Act act="research" scenario={scenario} state={state}>
            <ResearchStage status={state.research} groups={scenario.researchGroups} />
          </Act>
          <Act act="what_if" scenario={scenario} state={state}>
            <p className="mb-4 text-sm">
              <span className="font-medium">{localize(scenario.whatIf.title)}{tr("copy.text_3a52ce7")}</span> <span className="text-muted">{localize(scenario.whatIf.description)}</span>
            </p>
            <WhatIfStage outcome={state.whatIf} progress={state.whatIfProgress} roles={scenario.roles} />
          </Act>
          <Act act="actions" scenario={scenario} state={state}>
            {opened("actions") && <ActionsStage />}
          </Act>
        </div>
      </div>
    </div>
  );
}
