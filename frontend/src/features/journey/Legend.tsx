import { tr, localize, useLocale } from "@/i18n";
/** What the map's shapes, outlines and lines mean. */
import type { JourneyNodeKind, JourneyNodeStatus } from "@/domain/journey";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { cn } from "@/lib/cn";
import { EDGE_COLOR, KIND_ICON, KIND_LABEL, STATION_FRAME } from "./visuals";

const STATIONS: JourneyNodeKind[] = ["task", "appointment", "action"];
const SATELLITES: JourneyNodeKind[] = ["requirement", "document", "dependency", "approval"];
const STATUSES: JourneyNodeStatus[] = ["waiting_for_me", "prepared", "todo", "in_progress", "blocked", "done"];

function Line({ color, dash, width = 1.5, opacity = 1 }: { color: string; dash?: string; width?: number; opacity?: number }) {
  useLocale();
  return (
    <svg width="30" height="10" viewBox="0 0 30 10" aria-hidden className="shrink-0">
      <line x1="1" y1="5" x2="23" y2="5" stroke={color} strokeWidth={width} strokeDasharray={dash} strokeLinecap={dash?.startsWith("0.5") ? "round" : undefined} opacity={opacity} />
      <path d="M22 1.5 L29 5 L22 8.5 Z" fill={color} opacity={opacity} />
    </svg>
  );
}

const LINES: { label: string; color: string; dash?: string; width?: number; opacity?: number }[] = [
  { label: tr("copy.must_happen_first_c7832c1", { lng: "en" }), color: EDGE_COLOR.base, opacity: 0.7 },
  { label: tr("copy.needs_this_document_or_requirement_d7633ba", { lng: "en" }), color: EDGE_COLOR.base, dash: "6 5", opacity: 0.7 },
  { label: tr("copy.waits_for_your_approval_f1aa570", { lng: "en" }), color: EDGE_COLOR.base, dash: "0.5 5", width: 2, opacity: 0.8 },
  { label: tr("copy.holding_a_step_up_d2fa5d5", { lng: "en" }), color: EDGE_COLOR.danger },
  { label: tr("copy.critical_path_c77e227", { lng: "en" }), color: EDGE_COLOR.critical, width: 2.5 },
  { label: tr("copy.already_met_919df07", { lng: "en" }), color: EDGE_COLOR.settled, opacity: 0.3 },
];

function Group({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  useLocale();
  return (
    <div className={cn("min-w-0", className)}>
      <p className="mb-2 text-xs font-medium text-ink">{localize(title)}</p>
      <ul className="flex flex-wrap gap-x-4 gap-y-2">{localize(children)}</ul>
    </div>
  );
}

export function Legend({ className }: { className?: string }) {
  useLocale();
  return (
    <div className={cn("grid gap-x-8 gap-y-4 text-2xs text-muted @3xl/main:grid-cols-[auto_auto] @6xl/main:grid-cols-[auto_auto_auto]", className)}>
      <Group title={tr("copy.steps_cdde4f2")}>
        {STATIONS.map((kind) => {
          const Icon = KIND_ICON[kind];
          return (
            <li key={kind} className="flex items-center gap-1.5">
              <span
                className={cn(
                  "relative inline-flex h-5 w-7 items-center justify-center overflow-hidden rounded-[4px]",
                  kind === "action" ? STATION_FRAME.done : STATION_FRAME.todo,
                )}
                aria-hidden
              >
                <span className="absolute inset-y-0 start-0 w-[2px] bg-lane-residency" />
                <Icon className={cn("size-3", kind === "action" ? "text-primary" : "text-muted")} />
              </span>
              {localize(KIND_LABEL[kind])}
            </li>
          );
        })}
        {SATELLITES.map((kind) => {
          const Icon = KIND_ICON[kind];
          return (
            <li key={kind} className="flex items-center gap-1.5">
              <span className="inline-flex h-5 w-7 items-center justify-center rounded-full border border-line-strong bg-surface" aria-hidden>
                <Icon className="size-3 text-lane-residency" />
              </span>
              {localize(KIND_LABEL[kind])}
            </li>
          );
        })}
      </Group>
      <Group title={tr("copy.status_bae7d5b")}>
        {STATUSES.map((status) => (
          <li key={status}>
            <StatusBadge status={status} />
          </li>
        ))}
      </Group>
      <Group title={tr("copy.links_014bcd6")} className="@3xl/main:col-span-2 @6xl/main:col-span-1">
        {LINES.map((line) => (
          <li key={line.label} className="flex items-center gap-1.5">
            <Line color={line.color} dash={line.dash} width={line.width} opacity={line.opacity} />
            {localize(line.label)}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span className="rounded-full border border-line-strong bg-surface px-1.5 leading-4">{tr("copy.either_fa98d8d")}</span>
          {tr("copy.any_one_of_these_is_enough_3db3a24")}</li>
      </Group>
    </div>
  );
}
