import { tr, localize, useLocale } from "@/i18n";
import { ArrowUpRight, FileText, Search, Route, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { IconButton } from "@/components/ui/Button";
import { useActiveJourney, useDocuments } from "@/lib/api/hooks";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/stores/ui";
import { allNav, type NavItem } from "./navigation";

interface Result extends NavItem { section: string }

/** Searches in-memory data only; private queries and results are never persisted. */
export function CommandSearch() {
  const uiLocale = useLocale();
  const open = useUiStore((s) => s.searchOpen);
  const setOpen = useUiStore((s) => s.setSearchOpen);
  const navigate = useNavigate();
  const journey = useActiveJourney();
  const documents = useDocuments();
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const id = useId();
  const results = useMemo(() => {
    const pages: Result[] = allNav.map((n) => ({ ...n, label: localize(n.label), hint: localize(n.hint), section: tr("copy.go_to_8a68d90") }));
    if (!query.trim()) return pages;
    const steps: Result[] = (journey.data?.nodes ?? []).map((n) => ({ to: `/journey?node=${encodeURIComponent(n.key)}`, label: n.title, hint: n.summary, icon: Route, section: tr("copy.journey_steps_d6d2a1f") }));
    const files: Result[] = (documents.data ?? []).map((d) => ({ to: `/documents?doc=${encodeURIComponent(d.id)}`, label: d.filename, hint: tr("copy.private_document_open_to_review_65ccc86"), icon: FileText, section: tr("copy.documents_687c828") }));
    const terms = query.toLowerCase().trim().split(/\s+/);
    return [...pages, ...steps, ...files].filter((r) => terms.every((t) => `${r.label} ${r.hint}`.toLowerCase().includes(t))).slice(0, 16);
  }, [query, journey.data, documents.data, uiLocale]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        if (document.querySelector("dialog[open]") && !dialog.current?.open) return;
        event.preventDefault();
        setOpen(!useUiStore.getState().searchOpen);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [setOpen]);

  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (open && !el.open) { setQuery(""); setActive(0); el.showModal(); input.current?.focus(); }
    if (!open && el.open) el.close();
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [open]);

  useEffect(() => { document.getElementById(`${id}-${active}`)?.scrollIntoView({ block: "nearest" }); }, [active, id]);
  const choose = (result: Result) => { setOpen(false); navigate(result.to); };

  return (
    <dialog ref={dialog} className="command-dialog" aria-labelledby={`${id}-title`} onCancel={(e) => { e.preventDefault(); setOpen(false); }} onClose={() => setOpen(false)} onClick={(e) => { if (e.target === dialog.current) setOpen(false); }}>
      <div className="flex max-h-[80dvh] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-overlay">
        <h2 id={`${id}-title`} className="sr-only">{tr("copy.search_your_workspace_8569a77")}</h2>
        <div className="flex items-center gap-3 border-b border-line px-4 py-3">
          <Search className="size-5 shrink-0 text-primary" aria-hidden />
          <input ref={input} autoComplete="off" value={query} placeholder={tr("copy.search_pages_steps_and_documents_201500d")} className="h-11 min-w-0 flex-1 bg-transparent text-base outline-none" role="combobox" aria-label={tr("copy.search_your_workspace_8569a77")} aria-expanded="true" aria-controls={`${id}-results`} aria-autocomplete="list" aria-activedescendant={results[active] ? `${id}-${active}` : undefined} onChange={(e) => { setQuery(e.target.value); setActive(0); }} onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a + (e.key === "ArrowDown" ? 1 : -1) + results.length) % Math.max(1, results.length)); }
            if (e.key === "Enter" && results[active]) { e.preventDefault(); choose(results[active]); }
          }} />
          <IconButton label={tr("copy.close_search_0906f92")} onClick={() => setOpen(false)}><X className="size-4" aria-hidden /></IconButton>
        </div>
        <div className="min-h-0 overflow-y-auto overscroll-contain p-2">
          {!results.length && <p role="status" className="px-4 py-10 text-center text-sm text-muted">{tr("copy.no_results_for_2a5f91d")}{localize(query)}{tr("copy.try_a_page_name_or_a_journey_step_034f5ce")}</p>}
          <ul id={`${id}-results`} role="listbox" aria-label={tr("copy.search_results_0144dae")}>
            {results.map((r, i) => { const Icon = r.icon; return (
              <li key={r.to} id={`${id}-${i}`} role="option" aria-selected={active === i}>
                {results[i - 1]?.section !== r.section && <p className="px-3 pt-3 pb-2 text-2xs font-medium text-subtle">{localize(r.section)}</p>}
                <button type="button" tabIndex={-1} onPointerMove={() => setActive(i)} onClick={() => choose(r)} className={cn("flex min-h-14 w-full items-center gap-3 rounded-lg px-3 py-2.5 text-start", active === i ? "bg-primary-tint" : "hover:bg-muted-surface")}>
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-primary"><Icon className="size-4" aria-hidden /></span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{localize(r.label)}</span><span className="block truncate text-xs text-muted">{localize(r.hint)}</span></span>
                  <ArrowUpRight className="size-4 shrink-0 text-subtle" aria-hidden />
                </button>
              </li>
            ); })}
          </ul>
        </div>
        <div className="flex justify-between border-t border-line bg-muted-surface px-5 py-3 text-2xs text-subtle"><span>{tr("copy.to_browse_enter_to_open_f2c9117")}</span><span>{tr("copy.esc_to_close_5329571")}</span></div>
      </div>
    </dialog>
  );
}
