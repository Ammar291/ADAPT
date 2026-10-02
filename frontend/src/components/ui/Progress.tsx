import { localize, useLocale } from "@/i18n";
import { formatPercent } from "@/lib/format";
import { cn } from "@/lib/cn";

export function ProgressBar({ value, label, className, tone = "primary" }: { value: number; label: string; className?: string; tone?: "primary" | "ink" }) {
  useLocale();
  const percent = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div
      role="progressbar"
      aria-label={localize(label)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={formatPercent(percent / 100)}
      className={cn("h-1.5 overflow-hidden rounded-full bg-sunken", className)}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-500 ease-out", tone === "ink" ? "bg-ink" : "bg-primary")}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

/** Circular progress with the percentage in the middle. */
export function ProgressRing({ value, size = 72, stroke = 6, label }: { value: number; size?: number; stroke?: number; label: string }) {
  useLocale();
  const percent = Math.max(0, Math.min(100, Math.round(value * 100)));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  return (
    <div
      role="progressbar"
      aria-label={localize(label)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={formatPercent(percent / 100)}
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--surface-sunken)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--teal)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - percent / 100)}
          className="transition-[stroke-dashoffset] duration-700 ease-out"
        />
      </svg>
      <span className="tabular absolute font-display text-lg font-semibold">{formatPercent(percent / 100)}</span>
    </div>
  );
}
