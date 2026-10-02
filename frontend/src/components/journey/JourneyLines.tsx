import { tr, localize, useLocale } from "@/i18n";
import { Link } from "react-router";
import { LIFE_AREAS, LIFE_AREA_LABEL, type LifeArea } from "@/domain/common";
import type { Journey, JourneyNode, JourneyNodeStatus } from "@/domain/journey";
import { laneColor } from "@/components/ui/AreaLabel";
import { STATUS_LABEL, depthOf } from "@/lib/journey/analysis";
import { cn } from "@/lib/cn";

const SHOWN = new Set(["task", "appointment", "action", "document", "requirement", "dependency"]);

function dotStyle(status: JourneyNodeStatus, color: string): { className: string; style: React.CSSProperties } {
  switch (status) {
    case "done":
      return { className: "border-2", style: { background: color, borderColor: color } };
    case "waiting_for_me":
      return { className: "border-2 border-ink bg-ink ring-2 ring-ink/20 ring-offset-2 ring-offset-surface", style: {} };
    case "prepared":
    case "in_progress":
      return { className: "border-[3px] bg-surface", style: { borderColor: color } };
    case "blocked":
      return { className: "border-2 border-dashed border-danger bg-danger-tint", style: {} };
    default:
      return { className: "border-2 border-line-strong bg-surface", style: {} };
  }
}

/**
 * The journey as a compact transit map: one line per area of life, one station per step,
 * placed by dependency depth so stations further right come later.
 */
export function JourneyLines({ journey, className, linkTo = (n) => `/journey?node=${n.key}` }: { journey: Journey; className?: string; linkTo?: (node: JourneyNode) => string }) {
  useLocale();
  const depth = depthOf(journey);
  const maxDepth = Math.max(1, ...journey.nodes.map((n) => depth.get(n.key) ?? 0));
  const areas = LIFE_AREAS.filter((area) => journey.nodes.some((n) => n.area === area && SHOWN.has(n.kind)));

  const rows = areas.map((area) => {
    const nodes = journey.nodes
      .filter((n) => n.area === area && SHOWN.has(n.kind) && n.status !== "not_applicable")
      .sort((a, b) => (depth.get(a.key) ?? 0) - (depth.get(b.key) ?? 0));
    const done = nodes.filter((n) => n.status === "done").length;
    // Nudge stations that share a depth so none overlap.
    const seen = new Map<number, number>();
    const placed = nodes.map((node) => {
      const d = depth.get(node.key) ?? 0;
      const i = seen.get(d) ?? 0;
      seen.set(d, i + 1);
      return { node, pct: (d / maxDepth) * 92 + 2, nudge: i * 16 };
    });
    return { area, placed, done, total: nodes.length };
  });

  return (
    <div className={cn("flex flex-col", className)}>
      {rows.map(({ area, placed, done, total }) => (
        <div key={area} className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-center gap-3 py-2 sm:grid-cols-[7.5rem_minmax(0,1fr)]">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{localize(LIFE_AREA_LABEL[area as LifeArea])}</p>
            <p className="tabular text-2xs text-subtle">
              {localize(done)} {tr("copy.of_2449d65")}{localize(total)} {tr("copy.done_e5fd9cf")}</p>
          </div>
          <div dir="ltr" className="relative h-8" role="list" aria-label={localize(tr("copy.v0_v1_of_v2_steps_done_31ec83b", { v0: localize(LIFE_AREA_LABEL[area as LifeArea]), v1: done, v2: total }))}>
            <span className="absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full opacity-35" style={{ background: laneColor(area as LifeArea) }} aria-hidden />
            {placed.map(({ node, pct, nudge }) => {
              const dot = dotStyle(node.status, laneColor(area as LifeArea));
              return (
                <Link
                  key={node.key}
                  role="listitem"
                  to={linkTo(node)}
                  title={`${node.title}: ${localize(STATUS_LABEL[node.status])}`}
                  aria-label={`${node.title}, ${localize(STATUS_LABEL[node.status])}`}
                  className="group absolute top-1/2 flex size-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full"
                  style={{ left: `calc(${pct}% + ${nudge}px)` }}
                >
                  <span className={cn("block size-3.5 rounded-full transition-transform group-hover:scale-125 group-focus-visible:scale-125", dot.className)} style={dot.style} />
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function JourneyLinesLegend({ className }: { className?: string }) {
  useLocale();
  const items: { status: JourneyNodeStatus; label: string }[] = [
    { status: "done", label: tr("copy.done_e9b450d") },
    { status: "waiting_for_me", label: tr("copy.needs_you_0d9d0df") },
    { status: "prepared", label: tr("copy.ready_or_in_progress_f16ee1c") },
    { status: "blocked", label: tr("copy.blocked_99613c7") },
    { status: "todo", label: tr("copy.later_56e2f5d") },
  ];
  return (
    <ul className={cn("flex flex-wrap gap-x-4 gap-y-1.5 text-2xs text-muted", className)} aria-label={tr("copy.legend_5846955")}>
      {items.map((item) => {
        const dot = dotStyle(item.status, "var(--lane-residency)");
        return (
          <li key={item.status} className="flex items-center gap-1.5">
            <span className={cn("block size-3 rounded-full", dot.className, "ring-0 ring-offset-0")} style={dot.style} aria-hidden />
            {localize(item.label)}
          </li>
        );
      })}
    </ul>
  );
}
