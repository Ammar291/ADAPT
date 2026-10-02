import { localize, useLocale } from "@/i18n";
import { LIFE_AREA_LABEL, type LifeArea } from "@/domain/common";
import { cn } from "@/lib/cn";

/** CSS colour of a life area's journey line. */
export function laneColor(area: LifeArea): string {
  return `var(--lane-${area})`;
}

/** A life area's name with its line colour as a small bar: the colour is never the only cue. */
export function AreaLabel({ area, className }: { area: LifeArea; className?: string }) {
  useLocale();
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-2xs font-medium text-muted", className)}>
      <span className="h-2.5 w-1 rounded-full" style={{ background: laneColor(area) }} aria-hidden />
      {localize(LIFE_AREA_LABEL[area])}
    </span>
  );
}
