import { tr, localize, useLocale } from "@/i18n";
import { AudioLines, ChevronRight, Menu, Search, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/stores/ui";
import { BrandMark } from "./BrandMark";
import { Sheet } from "@/components/ui/Sheet";
import { allNav, bottomNav, titleFor } from "./navigation";
import { LanguageSelector } from "@/i18n/LanguageSelector";

export function MobileTopBar() {
  useLocale();
  const { pathname } = useLocation();
  const setAssistantOpen = useUiStore((s) => s.setAssistantOpen);
  const setSearchOpen = useUiStore((s) => s.setSearchOpen);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => { setMenuOpen(false); }, [pathname]);
  return (
    <>
    <header className="pt-safe sticky top-0 z-30 border-b border-line bg-canvas/95 backdrop-blur-sm lg:hidden">
      <div className="flex h-14 items-center gap-3 px-4">
        <Link to="/home" aria-label={tr("copy.adapt_home_8bcdc4f")} className="flex size-11 shrink-0 items-center justify-center">
          <BrandMark className="size-7" />
        </Link>
        <p className="flex-1 truncate font-display text-base font-medium">{localize(titleFor(pathname))}</p>
        <button type="button" onClick={() => setSearchOpen(true)} className="flex size-11 shrink-0 items-center justify-center rounded-full text-muted hover:bg-sunken" aria-label={tr("copy.search_adapt_3d13671")}><Search className="size-5" aria-hidden /></button>
        {pathname !== "/assistant" && (
          <button
            type="button"
            onClick={() => setAssistantOpen(true)}
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-full text-muted hover:bg-sunken hover:text-ink"
            aria-label={tr("copy.open_the_assistant_dc2f9bc")}
          >
            <AudioLines className="size-5" aria-hidden />
          </button>
        )}
        <button type="button" onClick={() => setMenuOpen(true)} className="flex size-11 shrink-0 items-center justify-center rounded-full text-muted hover:bg-sunken" aria-label={tr("copy.open_navigation_0f53b30")} aria-expanded={menuOpen}><Menu className="size-5" aria-hidden /></button>
      </div>
    </header>
    <Sheet open={menuOpen} onClose={() => setMenuOpen(false)} title={tr("copy.your_workspace_68d409a")} description={tr("copy.everything_you_need_for_your_move_b3044ee")}>
      <div className="mb-4"><LanguageSelector /></div>
      <nav aria-label={tr("copy.all_destinations_a693e80")} className="grid gap-1">
        {allNav.map((item) => { const Icon = item.icon; return <NavLink key={item.to} to={item.to} onClick={() => setMenuOpen(false)} className={({ isActive }) => cn("flex min-h-14 items-center gap-3 rounded-xl px-3 py-2.5", isActive ? "bg-primary-tint text-primary-strong" : "hover:bg-muted-surface")}><Icon className="size-5 shrink-0" aria-hidden /><span className="min-w-0 flex-1"><span className="block text-sm font-medium">{localize(item.label)}</span><span className="block truncate text-xs text-muted">{localize(item.hint)}</span></span><ChevronRight className="size-4 text-subtle" aria-hidden /></NavLink>; })}
      </nav>
      <p className="mt-4 flex items-center gap-2 border-t border-line pt-4 text-xs text-muted"><ShieldCheck className="size-4 text-primary" aria-hidden />{tr("copy.your_profile_and_documents_stay_private_to_you_7e8c4b7")}</p>
    </Sheet>
    </>
  );
}

/** Thumb-reachable primary destinations: Home, Journey, Discover, Documents, Profile. */
export function BottomNav() {
  useLocale();
  return (
    <nav aria-label={tr("copy.main_62bce94")} className="pb-safe fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 backdrop-blur-sm lg:hidden">
      <div className="flex h-16 items-stretch">
        {bottomNav.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  "relative flex min-w-0 flex-1 flex-col items-center justify-center gap-1 text-2xs transition-colors",
                  isActive ? "font-medium text-ink" : "text-muted",
                )
              }
            >
              {localize(({ isActive }) => (
                <>
                  <span
                    className={cn("absolute top-0 h-0.5 w-8 rounded-full transition-colors", isActive ? "bg-primary" : "bg-transparent")}
                    aria-hidden
                  />
                  <Icon className={cn("size-[22px]", isActive && "text-primary")} aria-hidden />
                  <span className="truncate">{localize(item.label)}</span>
                </>
              ))}
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}
