import { tr, localize, useLocale } from "@/i18n";
/**
 * How journey kinds and statuses look on the map, in the list and in the legend. Status never
 * relies on colour alone: every status has its own icon, fill and line style.
 */
import { CalendarClock, CircleCheckBig, ClipboardCheck, FileText, Link2, ListTodo, ShieldCheck, type LucideIcon } from "lucide-react";
import type { JourneyNodeKind, JourneyNodeStatus } from "@/domain/journey";
import { STATUS_STYLE } from "@/components/ui/StatusBadge";
import { STATUS_LABEL } from "@/lib/journey/analysis";
import { cn } from "@/lib/cn";

export const KIND_ICON: Record<JourneyNodeKind, LucideIcon> = {
  task: ListTodo,
  appointment: CalendarClock,
  action: CircleCheckBig,
  requirement: ClipboardCheck,
  document: FileText,
  dependency: Link2,
  approval: ShieldCheck,
};

/** Kind names as the map shows them ("action" is a finished task). */
export const KIND_LABEL: Record<JourneyNodeKind, string> = {
  task: tr("copy.task_7bb0ddf", { lng: "en" }),
  appointment: tr("copy.appointment_2d05c59", { lng: "en" }),
  action: tr("copy.completed_step_9062798", { lng: "en" }),
  requirement: tr("copy.requirement_e9c366b", { lng: "en" }),
  document: tr("copy.document_e214b8a", { lng: "en" }),
  dependency: tr("copy.outside_event_d1e0c1e", { lng: "en" }),
  approval: tr("copy.your_approval_fb85fa2", { lng: "en" }),
};

/** Frame of a station card, by status. */
export const STATION_FRAME: Record<JourneyNodeStatus, string> = {
  todo: "border border-line-strong bg-surface",
  in_progress: "border border-primary/55 bg-surface",
  blocked: "border-[1.5px] border-dashed border-danger/70 bg-surface",
  prepared: "border-[1.5px] border-primary bg-surface ring-4 ring-primary/10",
  waiting_for_me: "border-2 border-ink bg-surface shadow-raised",
  done: "border border-line bg-muted-surface",
  not_applicable: "border border-dashed border-line-strong bg-muted-surface opacity-60",
};

/** Frame of a satellite pill, by status. */
export const PILL_FRAME: Record<JourneyNodeStatus, string> = {
  todo: "border border-line-strong bg-surface",
  in_progress: "border border-primary/55 bg-surface",
  blocked: "border-[1.5px] border-dashed border-danger/70 bg-surface",
  prepared: "border-[1.5px] border-primary bg-surface",
  waiting_for_me: "border-2 border-ink bg-surface",
  done: "border border-line bg-muted-surface",
  not_applicable: "border border-dashed border-line-strong bg-muted-surface opacity-60",
};

const GLYPH: Record<JourneyNodeStatus, string> = {
  todo: "text-subtle",
  in_progress: "text-primary",
  blocked: "text-danger",
  prepared: "text-primary",
  waiting_for_me: "bg-ink text-canvas",
  done: "bg-primary text-on-primary",
  not_applicable: "text-subtle",
};

/** A status as a small round icon: filled for done and waiting for you, outline otherwise. */
export function StatusGlyph({ status, className, label = true }: { status: JourneyNodeStatus; className?: string; label?: boolean }) {
  useLocale();
  const Icon = STATUS_STYLE[status].icon;
  const filled = status === "done" || status === "waiting_for_me";
  return (
    <span className={cn("inline-flex size-5 shrink-0 items-center justify-center rounded-full", GLYPH[status], className)}>
      <Icon className={filled ? "size-3" : "size-4"} strokeWidth={filled ? 2.75 : 2} aria-hidden />
      {label && <span className="sr-only">{localize(STATUS_LABEL[status])}</span>}
    </span>
  );
}

/** Stroke colour of an edge tone. */
export const EDGE_COLOR = {
  base: "var(--ink-subtle)",
  settled: "var(--ink-subtle)",
  critical: "var(--teal)",
  danger: "var(--danger)",
  "danger-soft": "var(--danger)",
  focus: "var(--ink)",
} as const;

export const EDGE_OPACITY = {
  base: 0.55,
  settled: 0.22,
  critical: 1,
  danger: 0.85,
  "danger-soft": 0.3,
  focus: 1,
} as const;
