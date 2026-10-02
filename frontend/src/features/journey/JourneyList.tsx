import { tr, localize, useLocale } from "@/i18n";
/**
 * The accessible alternative to the map (and the default on phones): every step as a row,
 * grouped by life area or by stage, filtered for real. Rows open the same details.
 */
import { Layers, Rows3 } from "lucide-react";
import { useEffect, useMemo } from "react";
import { LIFE_AREA_LABEL } from "@/domain/common";
import type { Journey, JourneyNode } from "@/domain/journey";
import { laneColor } from "@/components/ui/AreaLabel";
import { Segmented } from "@/components/ui/Controls";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { JOURNEY_FILTERS, criticalPath, nodeByKey, type JourneyFilter } from "@/lib/journey/analysis";
import { cn } from "@/lib/cn";
import { listGroups, type ListGrouping } from "./graph";
import type { TransitLayout } from "./layout";
import { dueText } from "./MapNodes";
import { KIND_ICON, KIND_LABEL } from "./visuals";

function blockerSummary(journey: Journey, node: JourneyNode): string | null {
  const blocker = node.blockers[0];
  if (!blocker) return null;
  const related = blocker.relatedNodeKey ? nodeByKey(journey, blocker.relatedNodeKey) : undefined;
  const more = node.blockers.length > 1 ? ` and ${node.blockers.length - 1} more` : "";
  if (node.status === "blocked") return related ? `Waits for ${related.title}${more}` : `${blocker.message}${more}`;
  return blocker.message;
}

const EMPTY_COPY: Record<JourneyFilter, string> = {
  all: tr("copy.no_steps_yet_they_appear_here_as_adapt_builds_yo_a34b7be", { lng: "en" }),
  todo: tr("copy.nothing_to_start_right_now_steps_show_up_here_on_4fc82dd", { lng: "en" }),
  blocked: tr("copy.nothing_is_blocked_every_open_step_can_move_f9a293f", { lng: "en" }),
  prepared: tr("copy.nothing_prepared_yet_when_adapt_gets_something_r_c02ccda", { lng: "en" }),
  waiting_for_me: tr("copy.nothing_is_waiting_for_you_right_now_41806b1", { lng: "en" }),
  done: tr("copy.no_completed_steps_yet_finished_steps_collect_he_7278277", { lng: "en" }),
};

export function JourneyList({
  journey,
  layout,
  filter,
  grouping,
  onGroupingChange,
  selectedKey,
  onSelect,
}: {
  journey: Journey;
  layout: TransitLayout;
  filter: JourneyFilter;
  grouping: ListGrouping;
  onGroupingChange: (value: ListGrouping) => void;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  const uiLocale = useLocale();
  const groups = useMemo(() => listGroups(journey, layout, filter, grouping), [journey, layout, filter, grouping, uiLocale]);
  const critical = useMemo(() => new Set(criticalPath(journey)), [journey, uiLocale]);
  const bandByArea = useMemo(() => new Map(layout.bands.map((b) => [b.area, b])), [layout, uiLocale]);
  const filterLabel = JOURNEY_FILTERS.find((f) => f.id === filter)?.label;

  // Steps opened from the details panel ("Go to …") scroll into view.
  useEffect(() => {
    if (!selectedKey) return;
    document.querySelector(`[data-node-key="${CSS.escape(selectedKey)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selectedKey]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted" aria-live="polite">
          {localize(groups.reduce((sum, g) => sum + g.nodes.length, 0))} {filter === "all" ? tr("copy.steps_6578912") : tr("copy.steps_v0_f7d01aa", { v0: filterLabel?.toLowerCase() })}
        </p>
        <Segmented<ListGrouping>
          label={tr("copy.group_steps_by_8aed687")}
          size="sm"
          value={grouping}
          onChange={onGroupingChange}
          options={[
            { value: "area", label: tr("copy.by_area_ef81db6"), icon: <Rows3 className="size-3.5" aria-hidden /> },
            { value: "stage", label: tr("copy.by_stage_2f0fd4c"), icon: <Layers className="size-3.5" aria-hidden /> },
          ]}
        />
      </div>

      {groups.length === 0 && <p className="rounded-xl border border-dashed border-line-strong p-6 text-muted">{localize(EMPTY_COPY[filter])}</p>}

      {groups.map((group) => {
        const band = group.area ? bandByArea.get(group.area) : undefined;
        return (
          <section key={group.id} aria-labelledby={`group-${group.id}`}>
            <div className="mb-2 flex items-center gap-2.5">
              {group.area && <span className="h-5 w-1 rounded-full" style={{ background: laneColor(group.area) }} aria-hidden />}
              <h2 id={`group-${group.id}`} className="text-base font-medium">
                {localize(group.title)}
              </h2>
              <span className="tabular text-xs text-subtle">
                {band && filter === "all" ? tr("copy.v0_of_v1_done_63c4583", { v0: band.done, v1: band.total }) : group.description ?? tr("copy.v0_steps_5f0bea5", { v0: group.nodes.length })}
              </span>
            </div>
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
              {group.nodes.map((node) => {
                const Icon = KIND_ICON[node.kind];
                const due = dueText(node);
                const summary = blockerSummary(journey, node);
                return (
                  <li key={node.key}>
                    <button
                      type="button"
                      data-node-key={node.key}
                      onClick={() => onSelect(node.key)}
                      aria-current={selectedKey === node.key ? "true" : undefined}
                      className={cn(
                        "flex min-h-14 w-full items-start gap-3 px-4 py-3 text-start transition-colors hover:bg-muted-surface",
                        selectedKey === node.key && "bg-primary-tint/50 hover:bg-primary-tint/50",
                        node.status === "not_applicable" && "opacity-60",
                      )}
                    >
                      <span
                        className={cn(
                          "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg",
                          node.status === "done" ? "bg-primary-tint text-primary" : "bg-sunken text-muted",
                        )}
                        title={localize(KIND_LABEL[node.kind])}
                      >
                        <Icon className="size-4" aria-hidden />
                        <span className="sr-only">{localize(KIND_LABEL[node.kind])}</span>
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className={cn("block text-sm font-medium", node.status === "done" ? "text-muted" : "text-ink")}>{localize(node.title)}</span>
                        <span className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
                          {grouping === "stage" && <span>{localize(LIFE_AREA_LABEL[node.area])}</span>}
                          {summary && <span className={cn(node.status === "blocked" && "text-danger")}>{localize(summary)}</span>}
                          {critical.has(node.key) && <span className="text-primary-strong">{tr("copy.critical_path_c77e227")}</span>}
                        </span>
                      </span>
                      <span className="flex shrink-0 flex-col items-end gap-1">
                        <StatusBadge status={node.status} />
                        {due && <span className={cn("tabular text-2xs", due.overdue ? "text-danger" : "text-subtle")}>{localize(due.text)}</span>}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
