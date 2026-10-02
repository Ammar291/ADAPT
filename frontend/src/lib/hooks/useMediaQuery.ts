import { tr } from "@/i18n";
import { useSyncExternalStore } from "react";

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (callback) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", callback);
      return () => list.removeEventListener("change", callback);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** Desktop layout (persistent sidebar, docked assistant panel). Matches Tailwind `lg`. */
export function useIsDesktop(): boolean {
  return useMediaQuery(tr("copy.min_width_1024px_8e11a2a"));
}

export function usePrefersReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}
