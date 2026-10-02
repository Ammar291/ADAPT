import { tr, localize, useLocale } from "@/i18n";
import { Suspense, useEffect, useRef } from "react";
import { Outlet, ScrollRestoration, useLocation, useMatches } from "react-router";
import { LoadingRows } from "@/components/ui/States";
import { Toaster } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { AssistantDock, AssistantFab } from "./AssistantDock";
import { BottomNav, MobileTopBar } from "./MobileNav";
import { Sidebar } from "./Sidebar";
import { WorkspaceBar } from "./WorkspaceBar";
import { CommandSearch } from "./CommandSearch";
import { titleFor } from "./navigation";
import { DevBadge, LifeBriefNotifier, OfflineBanner } from "./SystemNotices";

/**
 * Page layouts, set per route with `handle: { layout }`:
 *   default — readable column (max 1120px), window scroll
 *   wide    — wider column for dense pages
 *   full    — edge to edge; on desktop the page fills the viewport and scrolls internally
 *             (graph canvases). The page root should be `flex min-h-0 flex-1 flex-col`.
 */
export type PageLayout = "default" | "wide" | "full";

function useLayout(): PageLayout {
  const matches = useMatches();
  for (let i = matches.length - 1; i >= 0; i--) {
    const layout = (matches[i]?.handle as { layout?: PageLayout } | undefined)?.layout;
    if (layout) return layout;
  }
  return "default";
}

export function AppShell() {
  const uiLocale = useLocale();
  const layout = useLayout();
  const full = layout === "full";
  const { pathname } = useLocation();
  const previous = useRef(pathname);
  useEffect(() => {
    document.title = `${localize(titleFor(pathname))} · ADAPT`;
    if (previous.current !== pathname) document.getElementById("main")?.focus({ preventScroll: true });
    previous.current = pathname;
  }, [pathname, uiLocale]);

  return (
    <div className="flex min-h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:start-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-overlay"
      >
        {tr("copy.skip_to_content_0a4470d")}</a>
      <Sidebar />
      <div className={cn("flex min-w-0 flex-1 flex-col", full && "lg:h-dvh")}>
        <OfflineBanner />
        <MobileTopBar />
        <WorkspaceBar />
        <main
          id="main"
          tabIndex={-1}
          className={cn(
            "flex min-w-0 flex-1 flex-col focus:outline-none",
            full ? "min-h-0 pb-[calc(4rem+env(safe-area-inset-bottom))] lg:pb-0" : "px-4 pt-6 pb-40 sm:px-8 lg:px-10 lg:pt-9 lg:pb-20",
          )}
        >
          {/* A size container: pages lay out for the space they get (e.g. with the assistant docked). */}
          <div className={cn("@container/main flex w-full flex-1 flex-col", !full && "mx-auto", layout === "default" && "max-w-[1120px]", layout === "wide" && "max-w-[1400px]", full && "min-h-0")}>
            <Suspense fallback={<LoadingRows rows={4} label={tr("common.1c57727adf")} className={full ? "p-6" : undefined} />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
      <AssistantDock />
      <BottomNav />
      <AssistantFab />
      <Toaster />
      <CommandSearch />
      <LifeBriefNotifier />
      <DevBadge />
      <ScrollRestoration />
    </div>
  );
}
