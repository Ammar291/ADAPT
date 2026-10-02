import { useEffect, useRef } from "react";

/**
 * Applies generated CSS through a constructable stylesheet (CSSOM) rather than a <style>
 * element, which the production Content-Security-Policy (`style-src 'self'`) blocks.
 * Browsers without adoptedStyleSheets simply skip the emphasis styling.
 */
export function useScopedStyleSheet(css: string): void {
  const sheet = useRef<CSSStyleSheet | null>(null);

  useEffect(() => {
    if (typeof document === "undefined" || !("adoptedStyleSheets" in document)) return;
    const created = new CSSStyleSheet();
    sheet.current = created;
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, created];
    return () => {
      document.adoptedStyleSheets = document.adoptedStyleSheets.filter((s) => s !== created);
      sheet.current = null;
    };
  }, []);

  useEffect(() => {
    sheet.current?.replaceSync(css);
  }, [css]);
}
