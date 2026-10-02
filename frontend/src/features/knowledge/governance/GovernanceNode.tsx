import { tr, localize, useLocale } from "@/i18n";
/**
 * How governance entities look on the map: institutional, rectangular, civic slate blue.
 * Each kind differs by fill and line style as well as colour, so the legend works in greyscale.
 */
import type { NodeProps } from "@xyflow/react";
import { CalendarClock, FileText, Landmark, ListChecks, MapPin, MousePointerClick, Scale, Split, UserCheck, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { Anchors, type KgFlowNode } from "../explorer/flow";
import type { ExplorerItem } from "../explorer/model";
import { withoutAcronym } from "./model";

interface Look {
  box: string;
  icon: LucideIcon | null;
  caption: string;
  /** Minimap fill. */
  fill: string;
}

const LOOK: Record<string, Look> = {
  service: { box: "kg-hub bg-surface border-civic/60 border-s-[3px] border-s-civic text-ink", icon: null, caption: "text-civic", fill: "var(--civic)" },
  appointment: { box: "bg-surface border-civic/35 text-ink", icon: CalendarClock, caption: "text-civic", fill: "var(--civic)" },
  dependency: { box: "bg-surface border-dashed border-civic text-ink", icon: Split, caption: "text-civic", fill: "var(--civic)" },
  process_step: { box: "bg-surface border-civic/35 text-ink", icon: null, caption: "text-civic", fill: "var(--civic)" },
  document: { box: "bg-surface border-line-strong text-ink", icon: FileText, caption: "text-muted", fill: "var(--ink-subtle)" },
  document_type: { box: "bg-surface border-line-strong text-ink", icon: FileText, caption: "text-muted", fill: "var(--ink-subtle)" },
  requirement: { box: "bg-civic-tint border-dashed border-civic/55 text-ink", icon: ListChecks, caption: "text-civic", fill: "var(--line-strong)" },
  eligibility_rule: { box: "bg-civic-tint border-dashed border-civic/55 text-ink", icon: UserCheck, caption: "text-civic", fill: "var(--line-strong)" },
  fee: { box: "bg-civic-tint border-dashed border-civic/55 text-ink", icon: null, caption: "text-civic", fill: "var(--line-strong)" },
  portal: { box: "bg-sunken border-line-strong text-ink", icon: MousePointerClick, caption: "text-muted", fill: "var(--line-strong)" },
  official_channel: { box: "bg-sunken border-line-strong text-ink", icon: MousePointerClick, caption: "text-muted", fill: "var(--line-strong)" },
  location: { box: "bg-sunken border-line-strong text-ink", icon: MapPin, caption: "text-muted", fill: "var(--line-strong)" },
  authority: { box: "kg-authority bg-civic border-civic text-surface", icon: Landmark, caption: "text-surface/80", fill: "var(--civic)" },
  legal_instrument: { box: "bg-surface border-civic text-civic", icon: Scale, caption: "text-civic", fill: "var(--civic)" },
};

const FALLBACK: Look = { box: "bg-surface border-line-strong text-ink", icon: null, caption: "text-muted", fill: "var(--line-strong)" };

export function governanceLook(type: string): Look {
  return LOOK[type] ?? FALLBACK;
}

export function governanceMinimapColor(item: ExplorerItem): string {
  return governanceLook(item.type).fill;
}

export function GovernanceNode({ data }: NodeProps<KgFlowNode>) {
  useLocale();
  const { item, selected } = data;
  const look = governanceLook(item.type);
  const acronym = typeof item.extra.acronym === "string" ? item.extra.acronym : null;
  const short = typeof item.extra.short === "string" ? item.extra.short : item.label;
  const Icon = look.icon;
  return (
    <div className={cn("kg-box relative flex h-full w-full items-center gap-2 overflow-hidden rounded-[5px] border px-2.5", look.box, selected && "kg-selected")}>
      <Anchors />
      {Icon && <Icon className={cn("kg-icon", look.caption)} aria-hidden />}
      <div className="kg-text min-w-0 flex-1">
        {acronym ? (
          <>
            <p className="kg-acronym font-display font-semibold">{localize(acronym)}</p>
            <p className="kg-label kg-sub text-surface/85" style={{ ["--kg-lines" as string]: 1, ["--kg-size" as string]: "11.5px" }}>
              {localize(withoutAcronym(item.label))}
            </p>
          </>
        ) : (
          <>
            <p className={cn("kg-caption", look.caption)}>{localize(item.typeLabel)}</p>
            <p className={cn("kg-label kg-full", item.type === "service" && "font-medium")}>{localize(item.label)}</p>
            <p className={cn("kg-label kg-short", item.type === "service" && "font-medium")} aria-hidden>
              {localize(short)}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function Swatch({ type }: { type: string }) {
  useLocale();
  return <span className={cn("kg-swatch rounded-[3px] border", governanceLook(type).box)} aria-hidden />;
}

function Line({ variant, arrow, markers }: { variant: string; arrow?: boolean; markers: string }) {
  useLocale();
  return (
    <svg className="kg-line" viewBox="0 0 30 10" aria-hidden>
      <path d="M1,5 L27,5" className={cn("kg-edge", `kg-e-${variant}`)} markerEnd={arrow ? `url(#${markers}-ink)` : undefined} />
    </svg>
  );
}

const NODE_KEY: { type: string; label: string }[] = [
  { type: "service", label: tr("copy.service_329cb8b", { lng: "en" }) },
  { type: "authority", label: tr("copy.authority_97a9869", { lng: "en" }) },
  { type: "document", label: tr("copy.document_e214b8a", { lng: "en" }) },
  { type: "requirement", label: tr("copy.requirement_or_rule_37f121b", { lng: "en" }) },
  { type: "portal", label: tr("copy.where_to_apply_b48c089", { lng: "en" }) },
  { type: "dependency", label: tr("copy.either_or_step_d6682f2", { lng: "en" }) },
];

const EDGE_KEY: { variant: string; label: string; arrow?: boolean }[] = [
  { variant: "depends", label: tr("copy.comes_after_4917032", { lng: "en" }), arrow: true },
  { variant: "requires", label: tr("copy.requires_63c2178", { lng: "en" }) },
  { variant: "may", label: tr("copy.may_require_9e2ff06", { lng: "en" }) },
  { variant: "produces", label: tr("copy.produces_d1cb8e5", { lng: "en" }) },
  { variant: "applies", label: tr("copy.rule_applies_to_9046381", { lng: "en" }) },
  { variant: "quiet", label: tr("copy.provider_or_channel_5669de9", { lng: "en" }) },
];

export function GovernanceLegend({ markers }: { markers?: string }) {
  useLocale();
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1.5 text-2xs text-muted">
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5" aria-label={tr("copy.kinds_of_item_2380206")}>
        {NODE_KEY.map((k) => (
          <li key={k.type} className="flex items-center gap-1.5">
            <Swatch type={k.type} />
            {localize(k.label)}
          </li>
        ))}
      </ul>
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5" aria-label={tr("copy.kinds_of_link_b279252")}>
        {EDGE_KEY.map((k) => (
          <li key={k.variant} className="flex items-center gap-1.5">
            <Line variant={k.variant} arrow={k.arrow} markers={markers ?? ""} />
            {localize(k.label)}
          </li>
        ))}
      </ul>
    </div>
  );
}
