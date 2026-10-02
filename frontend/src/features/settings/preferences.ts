import { tr } from "@/i18n";
/**
 * Pure helpers for Settings: the conversation-language list and plain-words descriptions of
 * each preference. No I/O.
 */
import type { ConsentStatus } from "@/domain/common";
import { allLanguages, type LanguageOption } from "@/lib/languages";

export interface LanguageSelectOption {
  value: string;
  /** English name, plus the language's own name when it differs: "Arabic (العربية)". */
  label: string;
}

export function optionLabel(language: Pick<LanguageOption, "name" | "autonym">): string {
  return language.autonym && language.autonym.toLowerCase() !== language.name.toLowerCase()
    ? `${language.name} (${language.autonym})`
    : language.name;
}

function displayName(tag: string, locale: string): string | null {
  try {
    const name = new Intl.DisplayNames([locale], { type: "language" }).of(tag);
    return name && name !== tag ? name : null;
  } catch {
    return null;
  }
}

/** Label for any BCP-47 tag, including regional ones the ISO list doesn't carry ("en-GB"). */
export function tagLabel(tag: string): string {
  const name = displayName(tag, "en") ?? tag;
  const autonym = displayName(tag, tag) ?? name;
  return optionLabel({ name, autonym });
}

/**
 * Every language the browser can name, sorted by English name. The current preference is
 * always present, even when it is a regional tag, so the select never shows a wrong value.
 * Codes the browser names identically (ak and tw are both "Akan") appear once.
 */
export function languageOptions(current: string, languages: LanguageOption[] = allLanguages()): LanguageSelectOption[] {
  const seen = new Set<string>();
  const options: LanguageSelectOption[] = [];
  for (const language of languages) {
    const label = optionLabel(language);
    if (seen.has(label) && language.code !== current) continue;
    seen.add(label);
    options.push({ value: language.code, label });
  }
  if (current && !options.some((o) => o.value === current)) {
    options.push({ value: current, label: tagLabel(current) });
    options.sort((a, b) => a.label.localeCompare(b.label));
  }
  return options;
}

/** Browser languages first, for quick picking on phones; skipped when there are none. */
export function suggestedLanguages(browser: string[], options: LanguageSelectOption[]): LanguageSelectOption[] {
  return browser.map((code) => options.find((o) => o.value === code)).filter((o): o is LanguageSelectOption => Boolean(o));
}

export type Consent = Exclude<ConsentStatus, "not_asked">;

/** Consent as the settings control shows it: nothing selected until the user chooses. */
export function consentValue(status: ConsentStatus): Consent | "" {
  return status === "not_asked" ? "" : status;
}

export const COMMUNITY_OPTIONS: { value: Consent; label: string }[] = [
  { value: "granted", label: tr("copy.personalise_d270f66", { lng: "en" }) },
  { value: "declined", label: tr("copy.keep_general_5121f0c", { lng: "en" }) },
];

export const FAITH_OPTIONS: { value: Consent; label: string }[] = [
  { value: "granted", label: tr("copy.include_11c54a5", { lng: "en" }) },
  { value: "declined", label: tr("copy.leave_out_145a9fc", { lng: "en" }) },
];

/** Short, lower-case state of each consent, for summaries ("places of worship left out"). */
export const COMMUNITY_STATUS: Record<ConsentStatus, string> = { granted: "personalised", declined: tr("copy.kept_general_b404931", { lng: "en" }), not_asked: tr("copy.not_chosen_yet_9c0c146", { lng: "en" }) };
export const FAITH_STATUS: Record<ConsentStatus, string> = { granted: "included", declined: tr("copy.left_out_8d682cf", { lng: "en" }), not_asked: tr("copy.not_chosen_yet_9c0c146", { lng: "en" }) };
