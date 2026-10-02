import { localize, useLocale } from "@/i18n";
import { cn } from "@/lib/cn";

export function Spinner({ className, label }: { className?: string; label?: string }) {
  useLocale();
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("animate-spin", className)}
      role={label ? "status" : undefined}
      aria-label={localize(label)}
      aria-hidden={label ? undefined : true}
    >
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
