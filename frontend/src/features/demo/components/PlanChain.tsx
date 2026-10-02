import { tr, localize, useLocale } from "@/i18n";
import { CircleAlert, CircleDashed, Lock } from "lucide-react";
import { useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { laneColor } from "@/components/ui/AreaLabel";
import { LIFE_AREA_LABEL } from "@/domain/common";
import type { Journey } from "@/domain/journey";
import type { ScenarioRoleRef } from "@/domain/scenario";
import { cn } from "@/lib/cn";
import { chainOf, layoutChain, SIZE, type ChainNode } from "../chain";

const STATUS_WORDS: Record<string, string> = {
  todo: tr("copy.can_start_now_0e49f9f", { lng: "en" }),
  blocked: tr("copy.waits_for_earlier_steps_2e34323", { lng: "en" }),
  waiting_for_me: tr("copy.needs_kabir_29ab9d0", { lng: "en" }),
  prepared: tr("copy.prepared_d8b21a6", { lng: "en" }),
  in_progress: tr("copy.in_progress_b6bd42e", { lng: "en" }),
  done: tr("copy.done_e9b450d", { lng: "en" }),
  not_applicable: tr("copy.not_needed_2518be9", { lng: "en" }),
};

function NodeCard({
  item,
  dimmed,
  removed,
  missingInfo,
  onFocus,
}: {
  item: ChainNode;
  dimmed: boolean;
  removed: boolean;
  missingInfo: boolean;
  onFocus: (key: string | null) => void;
}) {
  useLocale();
  const featured = item.roles.length > 0;
  const { node } = item;
  return (
    <button
      type="button"
      onMouseEnter={() => onFocus(item.key)}
      onMouseLeave={() => onFocus(null)}
      onFocus={() => onFocus(item.key)}
      onBlur={() => onFocus(null)}
      className={cn(
        "absolute flex flex-col justify-center overflow-hidden rounded-md border bg-surface px-2.5 text-start transition-opacity duration-200",
        featured ? "border-ink/70 shadow-card" : "border-line",
        missingInfo && "border-danger ring-2 ring-danger/25",
        removed && "border-dashed bg-sunken",
        dimmed && "opacity-30",
      )}
      style={{ left: item.x, top: item.y, width: item.w, height: item.h }}
      aria-label={localize(`${node.title}. ${STATUS_WORDS[node.status] ?? node.status}${removed ? ". Not in this scenario" : ""}`)}
    >
      <span className="absolute inset-y-0 start-0 w-1" style={{ background: laneColor(item.area) }} aria-hidden />
      {featured && (
        <span className="mb-0.5 flex flex-wrap gap-1">
          {item.roles.map((role) => (
            <span key={role.role} className="rounded-sm bg-ink px-1.5 text-[10px] font-medium leading-4 text-canvas">
              {localize(role.label)}
            </span>
          ))}
        </span>
      )}
      <span className={cn("line-clamp-2 text-xs leading-tight font-medium", removed && "line-through decoration-ink/40")}>{localize(node.title)}</span>
      {featured && (
        <span className="mt-0.5 flex items-center gap-1 text-[10px] text-muted">
          {missingInfo ? (
            <CircleAlert className="size-3 text-danger" aria-hidden />
          ) : node.status === "blocked" ? (
            <Lock className="size-3" aria-hidden />
          ) : (
            <CircleDashed className="size-3" aria-hidden />
          )}
          {missingInfo ? tr("copy.missing_information_67cc34b") : (STATUS_WORDS[node.status] ?? node.status)}
        </span>
      )}
    </button>
  );
}

/** Shrinks wide content to the container (down to `min`), so the chain fits a projector. */
function useFitScale(contentWidth: number, min = 0.78): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => setScale(Math.max(min, Math.min(1, element.clientWidth / contentWidth)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [contentWidth, min]);
  return [ref, scale];
}

/**
 * The plan as a dependency chain. Columns read left to right (what can start now, then what
 * waits longest); bands are areas of life. Hovering a step shows its whole chain. With
 * `removed`, a what-if's dropped steps and dependencies are drawn dashed instead of hidden.
 */
export function PlanChain({
  journey,
  roles,
  focus: initialFocus = null,
  removed,
}: {
  journey: Journey;
  roles: ScenarioRoleRef[];
  focus?: string | null;
  removed?: { nodes: Set<string>; edges: Set<string> };
}) {
  const uiLocale = useLocale();
  const layout = useMemo(() => layoutChain(journey, roles), [journey, roles, uiLocale]);
  const [hover, setHover] = useState<string | null>(null);
  const focus = hover ?? initialFocus;
  const lit = useMemo(() => (focus ? chainOf(journey, focus) : null), [journey, focus, uiLocale]);
  const blocked = new Set(roles.filter((r) => r.role === "missing_information").map((r) => r.nodeKey));
  const missing = (key: string) => blocked.has(key) && journey.nodes.some((n) => n.key === key && n.blockers.some((b) => b.kind === "missing_info"));
  const width = layout.width + 16;
  const height = layout.height + 36;
  const [frame, scale] = useFitScale(width);

  return (
    <div ref={frame} className="overflow-x-auto rounded-xl border border-line bg-muted-surface" role="group" aria-label={tr("copy.dependency_chain_of_the_plan_ca1c779")}>
      <div style={{ width: width * scale, height: height * scale }}>
      <div className="relative origin-top-left" style={{ width, height, transform: scale < 1 ? `scale(${scale})` : undefined }}>
        <div className="absolute inset-x-0 top-0 flex h-7 items-center text-[11px] text-subtle" aria-hidden>
          {localize(Array.from({ length: Math.round((layout.width - SIZE.label) / (SIZE.column + SIZE.gap)) }, (_, i) => (
            <span key={i} className="absolute" style={{ left: SIZE.label + i * (SIZE.column + SIZE.gap) + 2 }}>
              {i === 0 ? tr("copy.can_start_now_0e49f9f") : tr("copy.stage_v0_63511ee", { v0: i + 1 })}
            </span>
          )))}
        </div>
        <div className="absolute inset-x-0 top-7" style={{ height: layout.height }}>
          {layout.lanes.map((lane, index) => (
            <div
              key={lane.area}
              className={cn("absolute inset-x-0 border-t border-line", index % 2 === 1 && "bg-sunken/50")}
              style={{ top: lane.y, height: lane.h }}
            >
              <span className="absolute start-3 top-2.5 flex items-center gap-1.5 text-[11px] font-medium text-muted">
                <span className="h-3 w-1 rounded-full" style={{ background: laneColor(lane.area) }} aria-hidden />
                {localize(LIFE_AREA_LABEL[lane.area])}
              </span>
            </div>
          ))}
          <svg className="pointer-events-none absolute inset-0 overflow-visible" width={layout.width} height={layout.height} aria-hidden>
            {layout.edges.map((edge) => {
              const gone = removed?.edges.has(edge.id) ?? false;
              const on = lit ? lit.has(edge.from) && lit.has(edge.to) : false;
              return (
                <path
                  key={edge.id}
                  d={edge.path}
                  fill="none"
                  stroke={gone ? "var(--danger)" : on ? "var(--teal)" : "var(--line-strong)"}
                  strokeWidth={on ? 2.2 : 1.3}
                  strokeDasharray={gone ? "5 4" : undefined}
                  opacity={lit && !on ? 0.25 : gone ? 0.7 : 1}
                />
              );
            })}
          </svg>
          {layout.nodes.map((item) => (
            <NodeCard
              key={item.key}
              item={item}
              dimmed={lit !== null && !lit.has(item.key)}
              removed={removed?.nodes.has(item.key) ?? false}
              missingInfo={missing(item.key)}
              onFocus={setHover}
            />
          ))}
        </div>
      </div>
      </div>
    </div>
  );
}
