import { tr, localize, useLocale } from "@/i18n";
import { ChevronRight, SearchX } from "lucide-react";
import { useId, type ReactNode } from "react";
import { EmptyState } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import { groupItems, matchesQuery, type ExplorerGroup, type ExplorerItem } from "./model";

/** The accessible alternative to the map: every node, grouped by kind, filtered by the search box. */
export function GraphList({
  items,
  groups,
  query,
  keepGroups,
  selectedId,
  onSelect,
  renderMeta,
}: {
  items: ExplorerItem[];
  groups: ExplorerGroup[];
  query: string;
  /** Only these groups (a type filter), or all when null. */
  keepGroups: Set<string> | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  renderMeta?: (item: ExplorerItem) => ReactNode;
}) {
  useLocale();
  const id = useId();
  const visible = items.filter((item) => (!keepGroups || keepGroups.has(item.group)) && matchesQuery(item, query));
  const grouped = groupItems(visible, groups);

  return (
    <div className="px-4 py-5 sm:px-6 lg:h-full lg:overflow-y-auto lg:px-8">
      <p className="sr-only" aria-live="polite">
        {visible.length === 1 ? tr("copy.1_item_19884f4") : tr("copy.v0_items_fd3ce74", { v0: visible.length })}
      </p>
      {grouped.length === 0 ? (
        <EmptyState
          icon={<SearchX className="size-5" aria-hidden />}
          title={tr("copy.nothing_matches_your_search_1be2b40")}
          description={tr("copy.try_a_different_word_or_clear_the_search_to_see__1747733")}
        />
      ) : (
        <div className="gap-6 @5xl/main:columns-2 @[88rem]/main:columns-3">
          {grouped.map(({ group, items: groupItemsList }) => (
            <section key={group.id} aria-labelledby={`${id}-${group.id}`} className="mb-6 break-inside-avoid">
              <h3 id={`${id}-${group.id}`} className="mb-2 flex items-baseline gap-2 text-sm font-medium">
                {localize(group.title)}
                <span className="tabular text-xs font-normal text-subtle">{localize(groupItemsList.length)}</span>
              </h3>
              <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
                {groupItemsList.map((item) => {
                  const selected = item.id === selectedId;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        aria-pressed={selected}
                        onClick={() => onSelect(item.id)}
                        className={cn(
                          "flex min-h-12 w-full items-center gap-3 px-4 py-2.5 text-start transition-colors hover:bg-muted-surface",
                          selected && "bg-sunken",
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium text-ink">{localize(item.label)}</span>
                          <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted">
                            <span>{localize(item.typeLabel)}</span>
                            {localize(renderMeta?.(item))}
                          </span>
                          {item.summary && <span className="mt-1 line-clamp-2 text-xs text-muted">{localize(item.summary)}</span>}
                        </span>
                        <ChevronRight className="flip-rtl size-4 shrink-0 text-subtle" aria-hidden />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
