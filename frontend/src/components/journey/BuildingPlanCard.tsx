import { tr, localize, useLocale } from "@/i18n";
import { Link } from "react-router";
import { Card } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/Progress";
import { Spinner } from "@/components/ui/Spinner";
import { buttonClass } from "@/components/ui/Button";
import { useWorkflow } from "@/lib/api/hooks";
import { useRunEvents } from "@/lib/events/useRunEvents";
import { stageStatuses } from "@/lib/events/runEvents";

/** Live progress of a plan being built, for screens that wait on it. */
export function BuildingPlanCard({ runId }: { runId: string }) {
  useLocale();
  const { view } = useRunEvents(runId);
  const workflow = useWorkflow("journey");
  const ids = workflow.data?.stages.map((s) => s.id) ?? [];
  const statuses = stageStatuses(view, ids);
  const complete = ids.filter((id) => statuses[id] === "complete").length;
  const current = view.order.map((id) => view.stages[id]!).reverse().find((s) => s.status === "running" || s.status === "awaiting");
  const awaiting = view.status === "awaiting_input";

  return (
    <Card tone="strong" className="p-6">
      <div className="flex items-start gap-4">
        <span className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-full bg-primary-tint text-primary">
          <Spinner className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-xl">{awaiting ? tr("copy.your_plan_is_waiting_for_your_approval_c6704e8") : tr("copy.adapt_is_building_your_plan_ff4e27f")}</h2>
          <p className="mt-1 text-muted" aria-live="polite">
            {awaiting ? tr("copy.review_one_action_so_adapt_can_finish_1dd4560") : current ? `${current.label}${current.message ? `: ${current.message}` : ""}` : tr("copy.starting_7725e05")}
          </p>
          {ids.length > 0 && (
            <div className="mt-4 flex items-center gap-3">
              <ProgressBar value={complete / ids.length} label={tr("copy.plan_progress_c3433cf")} className="flex-1" />
              <span className="tabular text-xs text-muted">
                {localize(complete)} {tr("copy.of_2449d65")}{localize(ids.length)} {tr("copy.steps_6578912")}</span>
            </div>
          )}
          <Link to={`/agents?run=${runId}`} className={buttonClass(awaiting ? "primary" : "secondary", "md", "mt-5")}>
            {awaiting ? tr("copy.review_and_approve_365a840") : tr("copy.watch_it_happen_13e2e1e")}
          </Link>
        </div>
      </div>
    </Card>
  );
}
