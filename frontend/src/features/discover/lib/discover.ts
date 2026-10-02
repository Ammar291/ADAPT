import { tr } from "@/i18n";
/**
 * Pure helpers for Discover: grouping results into sections, choosing each section's lead
 * item and card layout, and describing research progress in plain words.
 */
import type { ConsentStatus } from "@/domain/common";
import { DISCOVER_SECTIONS, type DiscoverItem, type DiscoverSection, type ResearchCategoryProgress, type ResearchStatus } from "@/domain/discover";

export interface SectionGroup {
  id: DiscoverSection;
  title: string;
  description: string;
  items: DiscoverItem[];
}

/**
 * The lead item of a section: the first with a reason it fits the user and a page to open,
 * then the first with a reason, else the first. Other items keep their order.
 */
export function leadFirst(items: DiscoverItem[]): DiscoverItem[] {
  const index = Math.max(
    0,
    [(i: DiscoverItem) => Boolean(i.relevance && i.source.url), (i: DiscoverItem) => Boolean(i.relevance)]
      .map((test) => items.findIndex(test))
      .find((found) => found >= 0) ?? 0,
  );
  if (index === 0) return items;
  return [items[index]!, ...items.slice(0, index), ...items.slice(index + 1)];
}

/** Results in DISCOVER_SECTIONS order, each section led by its best item. */
export function groupBySection(items: DiscoverItem[], options: { savedOnly?: boolean } = {}): SectionGroup[] {
  const pool = options.savedOnly ? items.filter((i) => i.saved) : items;
  return DISCOVER_SECTIONS.map((section) => ({
    ...section,
    items: leadFirst(pool.filter((item) => item.section === section.id)),
  }));
}

/**
 * How each card in a section sits in the 12-column wide grid (1 column on narrow pages,
 * 2 on medium). With three or more results the lead item is a full-width feature, and the
 * rest fill rows of three, switching to pairs so no card is left alone on the last row.
 * Two results sit side by side, the lead slightly wider.
 */
export type CardSlot = "feature" | "lead" | "pair" | "half" | "third";

export function cardSlots(count: number): CardSlot[] {
  if (count <= 0) return [];
  if (count === 1) return ["feature"];
  if (count === 2) return ["lead", "pair"];
  const rest = count - 1;
  const halves = rest % 3 === 0 ? 0 : rest % 3 === 2 ? 2 : 4;
  return ["feature", ...Array.from({ length: rest }, (_, i): CardSlot => (i >= rest - halves ? "half" : "third"))];
}

/** Container variants (`@container/main`), so the grid adapts when the assistant is docked. */
export const SLOT_CLASS: Record<CardSlot, string> = {
  feature: "@3xl/main:col-span-2 @5xl/main:col-span-12",
  lead: "@5xl/main:col-span-7",
  pair: "@5xl/main:col-span-5",
  half: "@5xl/main:col-span-6",
  third: "@5xl/main:col-span-4",
};

// --- research status ---------------------------------------------------------------------------

export const FAITH_NOT_OPTED_IN = "faith_not_opted_in";

/** Faith results appear only after the user opts in. ADAPT never infers faith. */
export function faithNeedsOptIn(status: ResearchStatus | undefined, faithConsent: ConsentStatus | undefined): boolean {
  const category = status?.categories.find((c) => c.section === "faith");
  if (category?.status === "skipped" && category.reason === FAITH_NOT_OPTED_IN) return true;
  return faithConsent !== undefined && faithConsent !== "granted";
}

export function categoryFor(status: ResearchStatus | undefined, section: DiscoverSection): ResearchCategoryProgress | undefined {
  return status?.categories.find((c) => c.section === section);
}

/** Per-section progress in plain words. */
export function categoryStatusText(category: ResearchCategoryProgress): string {
  switch (category.status) {
    case "pending":
      return tr("copy.waiting_33d3063");
    case "running":
      return tr("copy.checking_sources_1056792");
    case "completed":
      return category.count === 1 ? tr("copy.1_found_efc38d5") : `${category.count} found`;
    case "failed":
      return tr("copy.couldn_t_finish_f8484ee");
    case "skipped":
      return category.reason === FAITH_NOT_OPTED_IN ? tr("copy.only_if_you_opt_in_740611a") : tr("copy.not_included_bfca330");
  }
}

/** Share of categories that have finished (completed, failed or skipped), 0–1. */
export function researchProgress(categories: ResearchCategoryProgress[]): number {
  if (!categories.length) return 0;
  const finished = categories.filter((c) => c.status === "completed" || c.status === "failed" || c.status === "skipped").length;
  return finished / categories.length;
}

export type SectionState =
  | "loading" // results are loading
  | "searching" // research is looking at this section right now or soon
  | "failed" // research couldn't finish this section
  | "faith_invite" // faith section while the user hasn't opted in
  | "not_started" // no research has run yet
  | "empty" // research finished and found nothing
  | "items";

export function sectionState(args: {
  section: DiscoverSection;
  items: DiscoverItem[];
  status: ResearchStatus | undefined;
  loading: boolean;
  faithOptIn: boolean;
  savedOnly?: boolean;
}): SectionState {
  const { section, items, status, loading, faithOptIn, savedOnly } = args;
  if (section === "faith" && faithOptIn && !items.length) return "faith_invite";
  if (loading) return "loading";
  if (items.length) return "items";
  if (savedOnly) return "empty";
  const category = categoryFor(status, section);
  if (status?.state === "running" && (category?.status === "pending" || category?.status === "running")) return "searching";
  if (category?.status === "failed") return "failed";
  if (!status || status.state === "idle") return "not_started";
  return "empty";
}

/** "Last checked" dates older than 30 days are flagged by the service; this is a fallback. */
export function isStale(item: DiscoverItem, now = new Date()): boolean {
  if (item.needsRecheck) return true;
  const checked = new Date(item.lastCheckedAt).getTime();
  return !Number.isFinite(checked) || checked > now.getTime() || now.getTime() - checked > 30 * 86_400_000;
}

export function countBySection(items: DiscoverItem[]): Record<DiscoverSection, number> {
  const out = Object.fromEntries(DISCOVER_SECTIONS.map((s) => [s.id, 0])) as Record<DiscoverSection, number>;
  for (const item of items) out[item.section] = (out[item.section] ?? 0) + 1;
  return out;
}
