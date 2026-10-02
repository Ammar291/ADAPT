/**
 * Reads and removes the `?seed=sample` demo shortcut before the router is created, so the
 * router never sees it (and can't write it back when a page updates its own search params).
 * Imported first in main.tsx.
 */
let requested: string | null = null;

if (typeof window !== "undefined") {
  const url = new URL(window.location.href);
  requested = url.searchParams.get("seed");
  if (requested) {
    url.searchParams.delete("seed");
    window.history.replaceState(window.history.state, "", url);
  }
}

/** The demo seed requested by the initial URL, if any. */
export const requestedSeed: string | null = requested;
