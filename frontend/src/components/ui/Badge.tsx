import { localize, useLocale } from "@/i18n";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type BadgeTone = "neutral" | "primary" | "civic" | "dune" | "danger" | "ink" | "outline" | "simulated";

const tones: Record<BadgeTone, string> = {
  neutral: "bg-sunken text-muted",
  primary: "bg-primary-tint text-primary-strong",
  civic: "bg-civic-tint text-civic",
  dune: "bg-dune-tint text-dune",
  danger: "bg-danger-tint text-danger",
  ink: "bg-ink text-canvas",
  outline: "border border-line-strong text-muted",
  /** A simulated adapter carried the action out: nothing real was sent or booked. */
  simulated: "border border-dashed border-ink/50 text-ink bg-surface",
};

export function Badge({
  tone = "neutral",
  icon,
  children,
  className,
  title,
}: {
  tone?: BadgeTone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  useLocale();
  return (
    <span
      title={localize(title)}
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2.5 text-2xs font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {localize(icon)}
      {localize(children)}
    </span>
  );
}
