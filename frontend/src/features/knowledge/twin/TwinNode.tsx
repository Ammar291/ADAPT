import { tr, localize, useLocale } from "@/i18n";
/**
 * How the private twin looks on the map: personal and warm (round pills, teal for what is
 * yours), with the public rules it links to drawn small, in civic slate blue, marked "Public rule".
 */
import type { NodeProps } from "@xyflow/react";
import { Briefcase, CalendarClock, FileText, Flag, Heart, Landmark, Target, User, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { initials } from "@/lib/format";
import { Anchors, type KgFlowNode } from "../explorer/flow";
import type { ExplorerItem } from "../explorer/model";

const LOOK: Record<string, { box: string; icon: LucideIcon; iconClass: string }> = {
  person: { box: "bg-primary-tint border-primary/30 text-ink", icon: User, iconClass: "text-primary-strong" },
  goal: { box: "bg-surface border-primary/70 border-[1.5px] text-ink", icon: Target, iconClass: "text-primary" },
  organization: { box: "bg-surface border-primary/40 text-ink", icon: Briefcase, iconClass: "text-primary" },
  document: { box: "bg-surface border-line-strong text-ink", icon: FileText, iconClass: "text-muted" },
  preference: { box: "bg-muted-surface border-dashed border-line-strong text-ink", icon: Heart, iconClass: "text-muted" },
  constraint: { box: "bg-muted-surface border-dashed border-line-strong text-ink", icon: CalendarClock, iconClass: "text-muted" },
  milestone: { box: "bg-surface border-line-strong text-ink", icon: Flag, iconClass: "text-muted" },
};
const FALLBACK = { box: "bg-surface border-line-strong text-ink", icon: User, iconClass: "text-muted" };

export function twinMinimapColor(item: ExplorerItem): string {
  if (item.nodeType === "public") return "var(--civic)";
  if (item.extra.centre) return "var(--teal)";
  return item.type === "person" || item.type === "goal" ? "color-mix(in oklab, var(--teal) 55%, var(--surface))" : "var(--line-strong)";
}

export function TwinNode({ data }: NodeProps<KgFlowNode>) {
  useLocale();
  const { item, selected } = data;
  const centre = item.extra.centre === true;
  const look = LOOK[item.type] ?? FALLBACK;
  const Icon = look.icon;
  return (
    <div
      className={cn(
        "kg-box kg-pill relative flex h-full w-full items-center gap-2 overflow-hidden rounded-full border ps-2 pe-4",
        centre ? "border-primary bg-primary text-on-primary" : look.box,
        selected && "kg-selected",
      )}
      style={{ ["--kg-ring" as string]: "var(--teal)" }}
    >
      <Anchors />
      {centre ? (
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-on-primary/15 font-display text-sm font-semibold" aria-hidden>
          {localize(initials(item.label) || tr("copy.y_23eb4d3"))}
        </span>
      ) : (
        <span className="kg-icon-wrap flex size-7 shrink-0 items-center justify-center rounded-full bg-surface/70" aria-hidden>
          <Icon className={cn("size-3.5", look.iconClass)} />
        </span>
      )}
      <div className="kg-text min-w-0 flex-1">
        <p className={cn("kg-caption", centre ? "text-on-primary/80" : "text-muted")}>{centre ? tr("copy.you_905cb32") : item.typeLabel}</p>
        <p className={cn("kg-label", centre ? "font-display font-medium" : "font-medium")}>{localize(item.label)}</p>
      </div>
      {item.extra.needsReview === true && (
        <span className="size-2 shrink-0 rounded-full bg-primary ring-2 ring-surface" title={tr("copy.needs_your_review_29dac63")}>
          <span className="sr-only">{tr("copy.needs_your_review_29dac63")}</span>
        </span>
      )}
    </div>
  );
}

export function PublicRuleNode({ data }: NodeProps<KgFlowNode>) {
  useLocale();
  const { item, selected } = data;
  return (
    <div className={cn("kg-box relative flex h-full w-full items-center gap-2 overflow-hidden rounded-[5px] border border-civic/45 bg-civic-tint px-2.5 text-ink", selected && "kg-selected")}>
      <Anchors />
      <Landmark className="kg-icon text-civic" aria-hidden />
      <div className="kg-text min-w-0 flex-1">
        <p className="kg-caption kg-keep text-civic">{tr("copy.public_rule_2878b51")}</p>
        <p className="kg-label" style={{ ["--kg-size" as string]: "12px" }}>
          {localize(item.label)}
        </p>
      </div>
    </div>
  );
}

const NODE_KEY: { box: string; label: string }[] = [
  { box: "rounded-full border-primary bg-primary", label: tr("copy.you_905cb32", { lng: "en" }) },
  { box: "rounded-full bg-primary-tint border-primary/30", label: tr("copy.people_b37554f", { lng: "en" }) },
  { box: "rounded-full bg-surface border-primary/70 border-[1.5px]", label: tr("copy.goals_48d8c62", { lng: "en" }) },
  { box: "rounded-full bg-surface border-line-strong", label: tr("copy.documents_and_organisation_e87a4c5", { lng: "en" }) },
  { box: "rounded-full bg-muted-surface border-dashed border-line-strong", label: tr("copy.preferences_and_constraints_94880de", { lng: "en" }) },
  { box: "rounded-[3px] border-civic/45 bg-civic-tint", label: tr("copy.public_rule_shared_not_yours_1fb5c4a", { lng: "en" }) },
];

const EDGE_KEY: { variant: string; label: string; marker?: boolean }[] = [
  { variant: "private", label: tr("copy.your_private_links_7cc1a8d", { lng: "en" }) },
  { variant: "cross", label: tr("copy.link_to_a_public_rule_649db48", { lng: "en" }) },
  { variant: "blocked", label: tr("copy.blocked_by_ea05d77", { lng: "en" }), marker: true },
];

export function TwinLegend({ markers }: { markers: string }) {
  useLocale();
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1.5 text-2xs text-muted">
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5" aria-label={tr("copy.kinds_of_item_2380206")}>
        {NODE_KEY.map((k) => (
          <li key={k.label} className="flex items-center gap-1.5">
            <span className={cn("kg-swatch border", k.box)} aria-hidden />
            {localize(k.label)}
          </li>
        ))}
      </ul>
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5" aria-label={tr("copy.kinds_of_link_b279252")}>
        {EDGE_KEY.map((k) => (
          <li key={k.variant} className="flex items-center gap-1.5">
            <svg className="kg-line" viewBox="0 0 30 10" aria-hidden>
              <path d="M1,5 L27,5" className={cn("kg-edge", `kg-e-${k.variant}`)} markerEnd={k.marker ? `url(#${markers}-danger)` : undefined} />
            </svg>
            {localize(k.label)}
          </li>
        ))}
      </ul>
    </div>
  );
}
