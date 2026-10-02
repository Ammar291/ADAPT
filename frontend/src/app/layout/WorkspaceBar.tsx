import { tr, localize, useLocale } from "@/i18n";
import { ChevronRight, Search, ShieldCheck } from "lucide-react";
import { Link, useLocation } from "react-router";
import { useUiStore } from "@/stores/ui";
import { titleFor } from "./navigation";
import { LanguageSelector } from "@/i18n/LanguageSelector";

export function WorkspaceBar() {
  useLocale();
  const { pathname } = useLocation();
  const openSearch = useUiStore((s) => s.setSearchOpen);
  return (
    <header className="workspace-bar hidden h-16 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface/80 px-8 lg:flex">
      <nav aria-label={tr("copy.breadcrumb_c766e66")} className="flex min-w-0 items-center gap-2 text-sm">
        <Link to="/home" className="text-subtle hover:text-primary">{tr("copy.your_workspace_68d409a")}</Link>
        <ChevronRight className="size-3.5 text-subtle" aria-hidden />
        {pathname.startsWith("/knowledge/") && <><Link to="/knowledge/governance" className="text-subtle hover:text-primary">{tr("copy.knowledge_dec1fcc")}</Link><ChevronRight className="size-3.5 text-subtle" aria-hidden /></>}
        <span aria-current="page" className="truncate font-medium">{localize(titleFor(pathname))}</span>
      </nav>
      <div className="flex shrink-0 items-center gap-5">
        <LanguageSelector />
        <span className="hidden items-center gap-1.5 text-xs text-muted xl:flex"><ShieldCheck className="size-3.5 text-primary" aria-hidden />{tr("copy.private_workspace_7441804")}</span>
        <button type="button" onClick={() => openSearch(true)} className="flex h-9 items-center gap-2 rounded-lg border border-line bg-muted-surface px-3 text-sm text-muted hover:border-line-strong" aria-label={tr("copy.search_adapt_3d13671")}>
          <Search className="size-4" aria-hidden /><span>{tr("copy.search_anything_7dcdc7d")}</span><kbd className="ms-3 rounded border border-line bg-surface px-1.5 text-2xs">{tr("copy.ctrl_k_a784e36")}</kbd>
        </button>
      </div>
    </header>
  );
}
