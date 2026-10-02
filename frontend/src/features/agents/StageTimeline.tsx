import { tr, localize, useLocale } from "@/i18n";
import { ChevronDown, Clock, GitFork, Wrench } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useMemo, type ReactNode } from "react";
import type { AgentStage, AgentWorkflow } from "@/domain/runs";
import type { RunView, StageStatus } from "@/lib/events/runEvents";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";
import { conditionLabel, stageLine } from "./flow";
import { layoutWorkflow } from "./layout";
import { KIND_META, STAGE_STATUS, StagePill, StageStatusIcon } from "./StageStatus";

/**
 * The workflow as a vertical timeline: the phone layout, and the list alternative to the
 * graph on desktop. Parallel stages are grouped; conditional stages say when they run.
 * With `renderDetail`, a stage expands in place; otherwise selecting it calls `onSelect`.
 */
export function StageTimeline({
  workflow,
  view,
  statuses,
  selectedId,
  onSelect,
  renderDetail,
  animate,
  className,
}: {
  workflow: AgentWorkflow;
  view: RunView;
  statuses: Record<string, StageStatus>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  renderDetail?: (id: string) => ReactNode;
  animate: boolean;
  className?: string;
}) {
  const uiLocale = useLocale();
  const reduce = useReducedMotion() || !animate;
  const levels = useMemo(() => layoutWorkflow(workflow, "vertical").levels, [workflow, uiLocale]);
  const stageById = useMemo(() => new Map(workflow.stages.map((s) => [s.id, s])), [workflow, uiLocale]);
  const conditionOf = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of workflow.edges) if (e.condition) map.set(e.target, e.condition);
    return map;
  }, [workflow, uiLocale]);
  // Stages reached only through a conditional edge say so (e.g. "If you approve").
  const onlyIf = (id: string) => {
    const incoming = workflow.edges.filter((e) => e.target === id);
    return incoming.length > 0 && incoming.every((e) => e.condition) ? (conditionOf.get(id) ?? null) : null;
  };

  const row = (stage: AgentStage, last: boolean) => {
    const status = statuses[stage.id] ?? "queued";
    const stageView = view.stages[stage.id];
    const selected = selectedId === stage.id;
    const condition = onlyIf(stage.id);
    const tools = stageView?.tools.length ?? 0;
    const detailId = `stage-detail-${stage.id}`;
    return (
      <li key={stage.id} className="relative flex gap-3">
        <div className="flex w-7 shrink-0 flex-col items-center">
          <span
            className={cn(
              "relative z-10 mt-3 flex size-7 items-center justify-center rounded-full border-2 transition-colors duration-300",
              STAGE_STATUS[status].rail,
            )}
            aria-hidden
          >
            <StageStatusIcon status={status} />
          </span>
          {!last && (
            <span className={cn("-mb-3 w-0.5 flex-1 transition-colors duration-500", status === "complete" ? "bg-primary" : "bg-line-strong")} aria-hidden />
          )}
        </div>
        <div className="min-w-0 flex-1 pb-2">
          <button
            type="button"
            onClick={() => onSelect(stage.id)}
            aria-expanded={renderDetail ? selected : undefined}
            aria-controls={renderDetail && selected ? detailId : undefined}
            aria-pressed={renderDetail ? undefined : selected}
            data-stage={stage.id}
            className={cn(
              "flex min-h-11 w-full items-start gap-3 rounded-lg px-3 py-2.5 text-start transition-colors hover:bg-sunken",
              selected && "bg-sunken",
              status === "awaiting" && "bg-ink/[0.05] ring-1 ring-ink/60",
            )}
          >
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-medium text-ink">{localize(stage.label)}</span>
                <span className="text-2xs text-subtle">{localize(KIND_META[stage.kind].label)}</span>
              </span>
              <span className={cn("mt-0.5 block text-sm", status === "failed" ? "text-danger" : "text-muted")}>
                {localize(stageLine(status, stageView, stage.description, view.status))}
              </span>
              <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                <StagePill status={status} animate={animate} />
                {condition && <span className="text-2xs text-muted">{localize(conditionLabel(condition))}</span>}
                {!!stageView?.durationMs && (
                  <span className="tabular inline-flex items-center gap-1 text-2xs text-subtle">
                    <Clock className="size-3" aria-hidden />
                    {localize(formatDuration(stageView.durationMs))}
                  </span>
                )}
                {tools > 0 && (
                  <span className="tabular inline-flex items-center gap-1 text-2xs text-subtle">
                    <Wrench className="size-3" aria-hidden />
                    {localize(tools)} {tools === 1 ? tr("copy.tool_call_98edbf6") : tr("copy.tool_calls_cc8b5f4")}
                  </span>
                )}
              </span>
              {status === "running" && (
                <span className="mt-2 block h-[3px] overflow-hidden rounded-full bg-primary-tint" aria-hidden>
                  <span
                    className="block h-full rounded-full bg-primary transition-[width] duration-500"
                    style={{ width: `${Math.round((stageView?.progress ?? 0.35) * 100)}%` }}
                  />
                </span>
              )}
            </span>
            {renderDetail && <ChevronDown className={cn("mt-1 size-4 shrink-0 text-subtle transition-transform", selected && "rotate-180")} aria-hidden />}
          </button>
          <AnimatePresence initial={false}>
            {renderDetail && selected && (
              <motion.div
                id={detailId}
                key="detail"
                initial={reduce ? false : { height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
                transition={{ duration: 0.25, ease: [0.2, 0, 0, 1] }}
                className="overflow-hidden"
              >
                <div className="px-3 pt-2 pb-4">{localize(renderDetail(stage.id))}</div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </li>
    );
  };

  return (
    <ol className={cn("flex flex-col", className)} aria-label={tr("copy.workflow_steps_1c09240")}>
      {levels.map((ids, index) => {
        const last = index === levels.length - 1;
        if (ids.length === 1) return row(stageById.get(ids[0]!)!, last);
        return (
          <li key={ids.join("|")} className="relative">
            <div className="flex gap-3">
              <div className="flex w-7 shrink-0 justify-center" aria-hidden>
                <span className="w-0.5 bg-line-strong" />
              </div>
              <p className="flex items-center gap-1.5 py-1 text-2xs font-medium text-muted">
                <GitFork className="size-3.5" aria-hidden />
                {tr("copy.these_run_at_the_same_time_2ffd7fc")}</p>
            </div>
            <ol className="flex flex-col">{ids.map((id, i) => row(stageById.get(id)!, last && i === ids.length - 1))}</ol>
          </li>
        );
      })}
    </ol>
  );
}
