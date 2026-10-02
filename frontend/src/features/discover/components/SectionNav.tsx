import { tr, localize, useLocale } from "@/i18n";
import { Bookmark } from "lucide-react";
import { useEffect, useRef } from "react";
import type { DiscoverSection } from "@/domain/discover";
import { cn } from "@/lib/cn";

const CHIP = "inline-flex shrink-0 items-center gap-1.5 rounded-full text-sm font-medium whitespace-nowrap transition-colors";

/**
 * Sticky section chips: jump to a section, or show only saved results. Scrolls sideways on
 * narrow screens and keeps the current section's chip in view.
 */
export function SectionNav({
  sections,
  counts,
  active,
  savedOnly,
  savedCount,
  onSavedOnly,
  onJump,
}: {
  sections: { id: DiscoverSection; title: string }[];
  counts: Partial<Record<DiscoverSection, number>>;
  active: DiscoverSection | null;
  savedOnly: boolean;
  savedCount: number;
  onSavedOnly: (value: boolean) => void;
  onJump: (id: DiscoverSection) => void;
}) {
  useLocale();
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const bar = scroller.current;
    const chip = bar?.querySelector<HTMLElement>(`[data-section="${active}"]`);
    if (!bar || !chip) return;
    const start = chip.offsetLeft - 16;
    const end = chip.offsetLeft + chip.offsetWidth + 16;
    if (start < bar.scrollLeft || end > bar.scrollLeft + bar.clientWidth) bar.scrollTo({ left: start, behavior: "smooth" });
  }, [active]);

  return (
    <nav
      aria-label={tr("copy.discover_sections_97d25d1")}
      className="sticky top-[calc(3.5rem+env(safe-area-inset-top))] z-20 -mx-4 border-b border-line bg-canvas/95 px-4 py-2.5 backdrop-blur-sm sm:-mx-8 sm:px-8 lg:top-0 lg:-mx-10 lg:px-10"
    >
      <div
        ref={scroller}
        className="flex items-center gap-2 overflow-x-auto scrollbar-none [mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)] rtl:[mask-image:linear-gradient(to_left,black_calc(100%-2rem),transparent)]"
      >
        <div role="group" aria-label={tr("copy.which_results_706bf92")} className="flex shrink-0 gap-1 rounded-full bg-sunken p-1">
          <button
            type="button"
            aria-pressed={!savedOnly}
            onClick={() => onSavedOnly(false)}
            className={cn(CHIP, "h-7 px-3 pointer-coarse:h-9", !savedOnly ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink")}
          >
            {tr("copy.all_6a72085")}</button>
          <button
            type="button"
            aria-pressed={savedOnly}
            onClick={() => onSavedOnly(true)}
            className={cn(CHIP, "h-7 px-3 pointer-coarse:h-9", savedOnly ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink")}
          >
            <Bookmark className="size-3.5" aria-hidden />
            {tr("copy.saved_c0ae8f6")}<span className="tabular text-2xs text-subtle">{localize(savedCount)}</span>
          </button>
        </div>
        <span className="h-6 w-px shrink-0 bg-line-strong" aria-hidden />
        {sections.map((section) => {
          const current = section.id === active;
          return (
            <button
              key={section.id}
              type="button"
              data-section={section.id}
              onClick={() => onJump(section.id)}
              aria-current={current ? "location" : undefined}
              className={cn(
                CHIP,
                "h-9 px-3.5 pointer-coarse:h-11",
                current ? "bg-ink text-canvas" : "border border-line bg-surface text-muted hover:border-line-strong hover:text-ink",
              )}
            >
              {localize(section.title)}
              {counts[section.id] ? <span className={cn("tabular text-2xs", current ? "text-canvas/70" : "text-subtle")}>{localize(counts[section.id])}</span> : null}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
