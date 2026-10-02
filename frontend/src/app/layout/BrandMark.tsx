import { tr, useLocale } from "@/i18n";
import { cn } from "@/lib/cn";

/** The ADAPT mark: a route from a starting point to a destination ring, on navy. */
export function BrandMark({ className }: { className?: string }) {
  useLocale();
  return (
    <svg viewBox="0 0 512 512" className={cn("shrink-0", className)} aria-hidden>
      <rect x="8" y="8" width="496" height="496" rx="108" fill="#0F1C2E" stroke="var(--brand-outline)" strokeWidth="16" />
      <path d="M137 360V232a48 48 0 0 1 48-48h88" fill="none" stroke="#F5F4F0" strokeWidth="40" strokeLinecap="round" />
      <circle cx="137" cy="360" r="36" fill="#F5F4F0" />
      <circle cx="337" cy="184" r="56" fill="none" stroke="#4DB6BC" strokeWidth="36" />
    </svg>
  );
}

export function Wordmark({ className, inverse = false }: { className?: string; inverse?: boolean }) {
  useLocale();
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <BrandMark className="size-8" />
      <span className={cn("font-display text-lg font-semibold tracking-tight", inverse ? "text-[#e9f0f2]" : "text-ink")}>{tr("copy.adapt_2e26648")}</span>
    </span>
  );
}
