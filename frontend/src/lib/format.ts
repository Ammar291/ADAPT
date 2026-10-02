import { currentLocale, tr } from "@/i18n";
/** Presentation only. Dates, amounts and IDs in API payloads remain unchanged. */
export function formattingLocale(): string { return currentLocale() === "en" ? "en-GB" : currentLocale(); }

export function formatDate(value: string | Date | null | undefined, options: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" }): string {
  if (!value) return "";
  const date = typeof value === "string" ? new Date(value.length === 10 ? `${value}T12:00:00` : value) : value;
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(formattingLocale(), options).format(date);
}

export function formatShortDate(value: string | Date | null | undefined): string {
  return formatDate(value, { day: "numeric", month: "short" });
}

export function formatTime(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(formattingLocale(), { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(formattingLocale(), options).format(value);
}
export function formatCurrency(value: number, currency = "AED"): string {
  const formatted = formatNumber(value, { style: "currency", currency, minimumFractionDigits: 0 });
  return currentLocale() === "en" ? formatted.replaceAll("\u00a0", " ") : formatted;
}
export function formatUnit(value: number, unit: string, unitDisplay: "long" | "short" | "narrow" = "long"): string {
  return formatNumber(value, { style: "unit", unit, unitDisplay });
}
export function formatPercent(value: number, maximumFractionDigits = 0): string {
  return formatNumber(value, { style: "percent", maximumFractionDigits });
}
function relative(value: number, unit: Intl.RelativeTimeFormatUnit): string {
  return new Intl.RelativeTimeFormat(formattingLocale(), { numeric: "auto" }).format(value, unit);
}

/** "2 hours ago", "yesterday", "in 3 days". */
export function relativeTime(value: string | Date | null | undefined, now = new Date()): string {
  if (!value) return "";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "";
  const seconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return relative(0, "second");
  if (abs < 3600) return relative(Math.round(seconds / 60), "minute");
  if (abs < 86_400) return relative(Math.round(seconds / 3600), "hour");
  if (abs < 86_400 * 30) return relative(Math.round(seconds / 86_400), "day");
  return formatDate(date);
}

/** Whole days from today until an ISO date (negative when past). */
export function daysUntil(value: string | null | undefined, now = new Date()): number | null {
  if (!value) return null;
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  const today = new Date(now);
  today.setHours(12, 0, 0, 0);
  return Math.round((date.getTime() - today.getTime()) / 86_400_000);
}

/** "in 5 days", "today", "3 days ago". */
export function dueLabel(value: string | null | undefined, now = new Date()): string {
  const days = daysUntil(value, now);
  if (days === null) return "";
  return Number.isFinite(days) ? relative(days, "day") : "";
}

export function formatBytes(bytes: number): string {
  const unit = bytes < 1024 ? "byte" : bytes < 1024 * 1024 ? "kilobyte" : "megabyte";
  const value = unit === "byte" ? bytes : unit === "kilobyte" ? bytes / 1024 : bytes / (1024 * 1024);
  return formatNumber(value, { style: "unit", unit, unitDisplay: "short", maximumFractionDigits: unit === "megabyte" ? 1 : 0 });
}

export function formatDuration(ms: number): string {
  return formatNumber(ms < 1000 ? ms : ms < 60_000 ? ms / 1000 : ms / 60_000, { style: "unit", unit: ms < 1000 ? "millisecond" : ms < 60_000 ? "second" : "minute", unitDisplay: "narrow", maximumFractionDigits: ms < 1000 ? 0 : 1 });
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 12) return tr("copy.good_morning_0f76892");
  if (hour < 18) return tr("copy.good_afternoon_13fd0a3");
  return tr("copy.good_evening_6a4f54e");
}

export function firstName(displayName: string | null | undefined): string | null {
  return displayName?.trim().split(/\s+/)[0] ?? null;
}

export function initials(displayName: string | null | undefined): string {
  return (displayName ?? "")
    .trim()
    .split(/\s+/)
    .map((part) => part[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
