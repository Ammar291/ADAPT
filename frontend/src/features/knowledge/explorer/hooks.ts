import { useEffect, useState, type RefObject } from "react";

/** The element's content-box size, updated as it resizes (container-aware layouts). */
export function useElementSize(ref: RefObject<HTMLElement | null>): { width: number; height: number } {
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setSize((prev) => (prev.width === el.clientWidth && prev.height === el.clientHeight ? prev : { width: el.clientWidth, height: el.clientHeight }));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

/** `/` or Ctrl/Cmd+K runs `onTrigger` (focus search), except while typing in another field. */
export function useSearchShortcut(onTrigger: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target?.closest("input, textarea, select, [contenteditable='true']");
      const isSlash = event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey;
      const isCmdK = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
      if ((isSlash && !typing) || isCmdK) {
        if (document.querySelector("dialog[open]")) return;
        event.preventDefault();
        onTrigger();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onTrigger]);
}

/**
 * The shape (width / height) the map will be shown at, rounded so small resizes don't re-run
 * the layout. Null until the page has been measured. On desktop the map fills the viewport
 * below the page chrome; on phones it is ~62% of the screen height.
 */
export function useMapAspect(ref: RefObject<HTMLElement | null>, desktop: boolean): number | null {
  const { width } = useElementSize(ref);
  if (!width) return null;
  const height = typeof window === "undefined" ? 800 : desktop ? Math.max(360, window.innerHeight - 260) : Math.max(420, window.innerHeight * 0.62);
  return Math.round((width / height) * 5) / 5;
}
