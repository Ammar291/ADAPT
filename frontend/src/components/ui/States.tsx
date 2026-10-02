import { tr, localize, useLocale } from "@/i18n";
import { AlertTriangle, Clock, RotateCw } from "lucide-react";
import type { ReactNode } from "react";
import { describeError } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { Button } from "./Button";

/** An empty screen is an invitation to act: say what will appear and how to get there. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  useLocale();
  return (
    <div className={cn("flex flex-col items-start gap-4 rounded-xl border border-line bg-surface p-6 shadow-card sm:p-8", className)}>
      {icon && <div className="flex size-10 items-center justify-center rounded-lg bg-primary-tint text-primary-strong">{localize(icon)}</div>}
      <div className="max-w-prose">
        <h3 className="text-lg">{localize(title)}</h3>
        {description && <div className="mt-1 text-muted">{localize(description)}</div>}
      </div>
      {localize(action)}
    </div>
  );
}

/** Explains what went wrong and how to recover, in the interface's voice. */
export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  useLocale();
  const { title, detail } = describeError(error);
  const unavailable = error instanceof Error && error.name === "CapabilityUnavailableError";
  if (unavailable) return <UnavailableState className={className} />;
  return (
    <div role="alert" className={cn("flex flex-col items-start gap-3 rounded-xl border border-danger/30 bg-danger-tint p-5", className)}>
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
        <div>
          <p className="font-medium text-ink">{localize(title)}</p>
          {detail && <p className="mt-0.5 text-sm text-muted">{localize(detail)}</p>}
        </div>
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" icon={<RotateCw className="size-4" aria-hidden />} onClick={onRetry}>
          {tr("copy.try_again_042c862")}</Button>
      )}
    </div>
  );
}

/** A capability the backend hasn't switched on yet (live data mode only). */
export function UnavailableState({ title = tr("copy.this_isn_t_available_yet_549211e"), description, className }: { title?: string; description?: ReactNode; className?: string }) {
  useLocale();
  return (
    <div className={cn("flex items-start gap-3 rounded-xl border border-line bg-surface p-5", className)}>
      <Clock className="mt-0.5 size-5 shrink-0 text-subtle" aria-hidden />
      <div>
        <p className="font-medium">{localize(title)}</p>
        <p className="mt-0.5 text-sm text-muted">{localize(description ?? tr("copy.we_couldn_t_connect_to_this_service_try_again_la_571e350"))}</p>
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  useLocale();
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-sunken", className)} />;
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  useLocale();
  return (
    <div aria-hidden className={cn("flex flex-col gap-2", className)}>
      {localize(Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-3.5", i === lines - 1 ? "w-2/3" : "w-full")} />
      )))}
    </div>
  );
}

export function LoadingRows({ rows = 3, label = tr("copy.loading_8f26c65"), className }: { rows?: number; label?: string; className?: string }) {
  useLocale();
  return (
    <div role="status" aria-label={localize(label)} className={cn("flex flex-col gap-3", className)}>
      {localize(Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      )))}
    </div>
  );
}

/** Loading placeholder for card grids. */
export function LoadingCards({ count = 3, label = tr("copy.loading_8f26c65"), className }: { count?: number; label?: string; className?: string }) {
  useLocale();
  return (
    <div role="status" aria-label={localize(label)} className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-3", className)}>
      {localize(Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-xl border border-line bg-surface p-5">
          <Skeleton className="mb-4 h-4 w-1/3" />
          <SkeletonText lines={3} />
        </div>
      )))}
    </div>
  );
}
