import { useEffect, useRef, useState } from "react";
import { localize, tr, useLocale } from "@/i18n";
import { getLanguage } from "@/i18n/registry";
import type { InterpreterApi } from "./api";
import type { Pair } from "./types";

/** Microphone-free recovery; uses only the interpreter's authenticated translation API. */
export function TextFallback({ pair, api, onUse }: { pair: Pair; api: InterpreterApi; onUse: () => void }) {
  useLocale();
  const [text, setText] = useState("");
  const [translation, setTranslation] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => {
    setTranslation(""); setError(""); setPending(false);
    return () => { abort.current?.abort(); };
  }, [pair.source, pair.target, api]);
  async function translate() {
    onUse();
    abort.current?.abort();
    const request = new AbortController(); abort.current = request;
    setPending(true); setError(""); setTranslation("");
    try {
      const result = await api.text(pair, text.trim(), request.signal);
      if (!request.signal.aborted) setTranslation(result.translation);
    } catch {
      if (!request.signal.aborted) setError(tr("interpreter.textFailed"));
    } finally { if (!request.signal.aborted) setPending(false); }
  }
  return <details className="interp-settings interp-text-fallback" open>
    <summary>{tr("interpreter.textFallback")}</summary>
    <form onSubmit={(event) => { event.preventDefault(); void translate(); }}>
      <label htmlFor="interp-text">{tr("interpreter.typePhrase")}</label>
      <textarea id="interp-text" value={text} onChange={(event) => setText(event.target.value)} maxLength={6000} rows={3} lang={pair.source} dir={getLanguage(pair.source)?.direction ?? "ltr"} />
      <button type="submit" className="interp-enable" disabled={pending || !text.trim()}>{pending ? tr("copy.translating_b8faf22") : tr("interpreter.translateText")}</button>
      {error && <p role="alert">{error}</p>}
      {translation && <div className="interp-translation"><div className="interp-text-label">{tr("copy.translation_10ecb0e")}<span>{localize(getLanguage(pair.target)?.nativeName ?? pair.target)}</span></div><p lang={pair.target} dir={getLanguage(pair.target)?.direction ?? "ltr"} aria-live="polite">{translation}</p></div>}
    </form>
  </details>;
}
