import { useSyncExternalStore } from "react";
import i18next from "./vendor/i18next.js";
import { getLanguage, supportedLocale, uiLanguages } from "./registry";

export const LANGUAGE_STORAGE_KEY = "adapt.locale";
export type Catalog = Record<string, string>;
const modules = import.meta.glob<Catalog>("./locales/*.json", { eager: true, import: "default" });
export const catalogs = Object.fromEntries(Object.entries(modules).map(([path, catalog]) => [path.split("/").at(-1)!.replace(".json", ""), catalog]));
const english = catalogs.en ?? {};
const keysByEnglish = new Map(Object.entries(english).map(([key, value]) => [value, key]));

export function readStoredLocale(storage?: Pick<Storage, "getItem">): string | undefined {
  try { return supportedLocale((storage ?? window.localStorage).getItem(LANGUAGE_STORAGE_KEY)); } catch { return undefined; }
}

/** Authenticated preference wins; only a language code is ever read from browser storage. */
export function resolveLocale(profile?: string | null, stored = readStoredLocale(), browser: readonly string[] = typeof navigator === "undefined" ? [] : navigator.languages): string {
  return supportedLocale(profile) ?? supportedLocale(stored) ?? browser.map(supportedLocale).find(Boolean) ?? "en";
}

export function applyDocumentLocale(locale: string, root = typeof document === "undefined" ? undefined : document.documentElement): void {
  if (!root) return;
  root.lang = supportedLocale(locale) ?? "en";
  root.dir = getLanguage(root.lang)?.direction ?? "ltr";
}

void i18next.init({
  lng: resolveLocale(),
  fallbackLng: "en",
  supportedLngs: uiLanguages.map((language) => language.code),
  resources: Object.fromEntries(uiLanguages.map(({ code }) => [code, { translation: catalogs[code] ?? {} }])),
  keySeparator: false,
  nsSeparator: false,
  returnNull: false,
  returnEmptyString: false,
  initImmediate: false,
  interpolation: {
    escapeValue: false, // React escapes text; translations never enter innerHTML.
    alwaysFormat: true,
    format: (value: unknown, _format: unknown, locale: string) => typeof value === "number"
      ? new Intl.NumberFormat(locale).format(value) : value,
  },
});
applyDocumentLocale(i18next.language);
i18next.on("languageChanged", applyDocumentLocale);

export function currentLocale(): string { return supportedLocale(i18next.language) ?? "en"; }

export async function setUiLocale(locale: string, persist = true): Promise<void> {
  const next = supportedLocale(locale) ?? "en";
  applyDocumentLocale(next);
  if (persist) { try { window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next); } catch { /* Storage denied: works for this visit. */ } }
  await i18next.changeLanguage(next);
}

function subscribe(listener: () => void) {
  i18next.on("languageChanged", listener);
  return () => i18next.off("languageChanged", listener);
}

/** Small React binding to the official i18next engine, including memoized components. */
export function useLocale(): string { return useSyncExternalStore(subscribe, currentLocale, () => "en"); }

/** Missing IDs never leak into the interface, even when absent from the English catalog. */
export function tr(key: string, values?: Record<string, unknown>): string {
  if (!Object.hasOwn(english, key) && !i18next.exists(key)) return i18next.t("common.unavailable");
  return i18next.t(key, { defaultValue: english[key] ?? english["common.unavailable"] ?? "Unavailable", ...values });
}

/** Localize known static presentation labels without altering user/server content or graph data. */
export function localize(value: number): string;
export function localize(value: string): string;
export function localize<T>(value: T): T;
export function localize(value: unknown): unknown {
  if (typeof value === "number") return new Intl.NumberFormat(currentLocale()).format(value);
  if (typeof value !== "string" || !value.trim()) return value;
  const key = keysByEnglish.get(value);
  return key ? tr(key) : value;
}

export { i18next };
