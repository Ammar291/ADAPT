import { getLanguage, languages } from "@/i18n/registry";
/** Compatibility helpers backed by the central language registry. */
export interface LanguageOption { code: string; name: string; autonym: string }
let cache: LanguageOption[] | undefined;
export function allLanguages(): LanguageOption[] {
  const seen = new Set<string>();
  return cache ??= languages.filter((language) => language.assistantSupported)
    .map(({ code, englishName: name, nativeName: autonym }) => ({ code, name, autonym }))
    .filter((language) => !seen.has(language.name) && Boolean(seen.add(language.name)))
    .sort((a, b) => a.name.localeCompare(b.name));
}
export function languageName(code: string): string { return getLanguage(code)?.englishName ?? code; }
export function languageAutonym(code: string): string { return getLanguage(code)?.nativeName ?? code; }
export function searchLanguages(query: string, exclude: string[] = [], limit = 8): LanguageOption[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return allLanguages().filter((language) => !exclude.includes(language.code))
    .filter((language) => language.name.toLowerCase().startsWith(q) || language.autonym.toLowerCase().startsWith(q) || language.code === q || language.name.toLowerCase().includes(' ' + q)).slice(0, limit);
}
export function browserLanguages(): string[] {
  if (typeof navigator === "undefined") return [];
  return [...new Set((navigator.languages ?? [navigator.language]).map((tag) => tag.split("-")[0]!.toLowerCase()))]
    .filter((code) => allLanguages().some((language) => language.code === code));
}
