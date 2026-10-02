import { localize, useLocale } from "@/i18n";
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Surfaces, with radius and elevation following hierarchy rather than habit:
 *   strong — the primary object on a screen (next action, a document preview)
 *   raised — prominent content that floats above the canvas
 *   flat   — grouped secondary content
 *   sunken — inset areas (inside a sheet or a card)
 */
type Tone = "strong" | "raised" | "flat" | "sunken";

const tones: Record<Tone, string> = {
  strong: "bg-surface border border-line-strong/70 shadow-raised rounded-xl",
  raised: "bg-surface border border-line shadow-card rounded-xl",
  flat: "bg-surface border border-line rounded-lg",
  sunken: "bg-sunken rounded-lg",
};

export function Card({ tone = "flat", className, ...props }: HTMLAttributes<HTMLDivElement> & { tone?: Tone }) {
  useLocale();
  return <div className={cn(tones[tone], className)} {...props} />;
}

export function CardHeader({
  title,
  description,
  action,
  className,
  as: Heading = "h2",
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  as?: "h2" | "h3";
}) {
  useLocale();
  return (
    <div className={cn("flex items-start justify-between gap-4 px-5 pt-5", className)}>
      <div className="min-w-0">
        <Heading className="text-lg">{localize(title)}</Heading>
        {description && <p className="mt-1 text-sm text-muted">{localize(description)}</p>}
      </div>
      {action && <div className="shrink-0">{localize(action)}</div>}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  useLocale();
  return <div className={cn("p-5", className)} {...props} />;
}
