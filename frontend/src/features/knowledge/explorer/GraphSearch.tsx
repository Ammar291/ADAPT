import { tr, localize, useLocale } from "@/i18n";
import { Search, X } from "lucide-react";
import { useId, useMemo, useState, type Ref } from "react";
import { cn } from "@/lib/cn";
import { searchItems, type ExplorerItem } from "./model";

/**
 * Search box. On the map it is a combobox with type-ahead results (choosing one selects,
 * highlights and centres the node); in the list view it filters the list as you type.
 */
export function GraphSearch({
  items,
  query,
  onQueryChange,
  onChoose,
  suggest,
  placeholder,
  inputRef,
}: {
  items: ExplorerItem[];
  query: string;
  onQueryChange: (query: string) => void;
  onChoose: (item: ExplorerItem) => void;
  /** Show the type-ahead list (map view). */
  suggest: boolean;
  placeholder: string;
  inputRef?: Ref<HTMLInputElement>;
}) {
  const uiLocale = useLocale();
  const id = useId();
  const listId = `${id}-results`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const results = useMemo(() => (suggest ? searchItems(items, query, 8) : []), [items, query, suggest, uiLocale]);
  const expanded = suggest && open && query.trim().length > 0;

  const choose = (item: ExplorerItem | undefined) => {
    if (!item) return;
    onChoose(item);
    setOpen(false);
  };

  return (
    <div className="relative w-full @4xl/main:w-64">
      <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-subtle" aria-hidden />
      <input
        ref={inputRef}
        type="search"
        role={suggest ? "combobox" : undefined}
        aria-label={localize(placeholder)}
        aria-autocomplete={suggest ? "list" : undefined}
        aria-expanded={suggest ? expanded : undefined}
        aria-controls={suggest ? listId : undefined}
        aria-activedescendant={expanded && results[active] ? `${listId}-${active}` : undefined}
        value={query}
        placeholder={localize(placeholder)}
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => {
          onQueryChange(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            if (expanded) {
              event.preventDefault();
              event.stopPropagation();
              setOpen(false);
            } else if (query) {
              event.preventDefault();
              event.stopPropagation();
              onQueryChange("");
            }
            return;
          }
          if (!expanded) {
            if (event.key === "ArrowDown" && suggest) setOpen(true);
            return;
          }
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((a) => Math.min(results.length - 1, a + 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((a) => Math.max(0, a - 1));
          } else if (event.key === "Enter") {
            event.preventDefault();
            choose(results[active] ?? results[0]);
          }
        }}
        className={cn(
          "h-10 w-full rounded-md border border-line-strong bg-surface ps-9 pe-16 text-sm text-ink placeholder:text-subtle",
          "focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/25 [&::-webkit-search-cancel-button]:hidden",
        )}
      />
      {query ? (
        <button
          type="button"
          onClick={() => onQueryChange("")}
          className="absolute end-1 top-1/2 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-subtle hover:bg-sunken hover:text-ink"
          aria-label={tr("copy.clear_search_67300d0")}
        >
          <X className="size-4" aria-hidden />
        </button>
      ) : (
        <kbd
          className="pointer-events-none absolute end-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-line bg-muted-surface px-1.5 font-sans text-2xs text-subtle lg:block"
          aria-hidden
        >
          {tr("copy.text_42099b4")}</kbd>
      )}
      {expanded && (
        <ul
          id={listId}
          role="listbox"
          aria-label={tr("copy.matching_items_defd0b2")}
          className="absolute inset-x-0 top-full z-30 mt-1.5 max-h-80 overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-overlay"
        >
          {results.length === 0 && <li className="px-3 py-2.5 text-sm text-muted">{tr("copy.nothing_matches_c297a37")}{localize(query.trim())}{tr("copy.try_another_word_like_a_document_or_an_authority_3176b2d")}</li>}
          {results.map((item, i) => (
            <li
              key={item.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(item)}
              className={cn("flex cursor-pointer flex-col gap-0.5 rounded-md px-3 py-2", i === active && "bg-sunken")}
            >
              <span className="text-sm font-medium text-ink">{localize(item.label)}</span>
              <span className="text-2xs text-muted">{localize(item.typeLabel)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
