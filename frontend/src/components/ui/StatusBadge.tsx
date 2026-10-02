import { localize, useLocale } from "@/i18n";
import { Ban, CircleCheck, CircleDashed, CircleDot, Hand, LoaderCircle, PackageCheck } from "lucide-react";
import type { JourneyNodeStatus } from "@/domain/journey";
import { STATUS_LABEL } from "@/lib/journey/analysis";
import { cn } from "@/lib/cn";

/**
 * Journey status, the same everywhere. Each status has its own icon and fill so it reads
 * without colour: blocked is a danger tint with a stop icon, "waiting for you" is solid
 * navy (the strongest call to act), completed is teal with a check.
 */
export const STATUS_STYLE: Record<JourneyNodeStatus, { className: string; icon: typeof CircleCheck }> = {
  todo: { className: "border border-line-strong text-muted bg-surface", icon: CircleDashed },
  in_progress: { className: "border border-primary/50 text-primary-strong bg-primary-tint", icon: LoaderCircle },
  blocked: { className: "bg-danger-tint text-danger border border-danger/25", icon: Ban },
  prepared: { className: "bg-surface text-primary-strong border border-primary", icon: PackageCheck },
  waiting_for_me: { className: "bg-ink text-canvas border border-ink", icon: Hand },
  done: { className: "bg-primary text-on-primary border border-primary", icon: CircleCheck },
  not_applicable: { className: "border border-dashed border-line-strong text-subtle", icon: CircleDot },
};

export function StatusBadge({ status, className }: { status: JourneyNodeStatus; className?: string }) {
  useLocale();
  const style = STATUS_STYLE[status];
  const Icon = style.icon;
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-2xs font-medium whitespace-nowrap",
        style.className,
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      {localize(STATUS_LABEL[status])}
    </span>
  );
}
