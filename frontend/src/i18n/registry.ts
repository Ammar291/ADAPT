/** One source of truth for UI, conversation, onboarding and interpreter language choices. */
export interface Language {
  code: string;
  englishName: string;
  nativeName: string;
  direction: "ltr" | "rtl";
  uiSupported: boolean;
  assistantSupported: boolean;
  interpreterSupported: boolean;
}

const initial: [string, string, string, Language["direction"]][] = [
  ["en", "English", "English", "ltr"],
  ["ar", "Arabic", "العربية", "rtl"],
  ["hi", "Hindi", "हिन्दी", "ltr"],
  ["ur", "Urdu", "اردو", "rtl"],
  ["ml", "Malayalam", "മലയാളം", "ltr"],
  ["ta", "Tamil", "தமிழ்", "ltr"],
  ["te", "Telugu", "తెలుగు", "ltr"],
  ["kn", "Kannada", "ಕನ್ನಡ", "ltr"],
  ["mr", "Marathi", "मराठी", "ltr"],
  ["fr", "French", "Français", "ltr"],
  ["es", "Spanish", "Español", "ltr"],
  ["de", "German", "Deutsch", "ltr"],
  ["zh", "Chinese", "中文", "ltr"],
  ["ja", "Japanese", "日本語", "ltr"],
];

// The dedicated interpreter exposes provider capabilities separately. These are its current
// supported pairs; Arabic speech output uses the recorded fallback. UI support stays independent.
const interpreterCodes = new Set(["en", "ar", "es", "pt", "fr", "ja", "ru", "zh", "de", "ko", "hi", "id", "vi", "it"]);

// Spoken-language choices stay broad. Adding UI support needs only a registry entry and catalog.
const spokenCodes = "aa ab af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co cr cs cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn nr nv ny oc oj om or os pa pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu".split(" ");

function named(code: string, locale: string): string | undefined {
  try { const value = new Intl.DisplayNames([locale], { type: "language" }).of(code); return value === code ? undefined : value; }
  catch { return undefined; }
}

export const languages: readonly Language[] = Object.freeze([
  ...initial.map(([code, englishName, nativeName, direction]) => Object.freeze({ code, englishName, nativeName, direction, uiSupported: true, assistantSupported: true, interpreterSupported: interpreterCodes.has(code) })),
  ...spokenCodes.filter((code) => !initial.some(([id]) => id === code)).flatMap((code) => {
    const englishName = named(code, "en");
    return englishName ? [Object.freeze({ code, englishName, nativeName: named(code, code) ?? englishName, direction: (["he", "fa", "ps", "dv", "yi"].includes(code) ? "rtl" : "ltr") as Language["direction"], uiSupported: false, assistantSupported: true, interpreterSupported: interpreterCodes.has(code) })] : [];
  }),
]);

export const uiLanguages = languages.filter((language) => language.uiSupported);

export function getLanguage(tag: string | null | undefined): Language | undefined {
  const normalized = tag?.trim().toLowerCase().replaceAll("_", "-");
  return languages.find((language) => language.code.toLowerCase() === normalized)
    ?? languages.find((language) => language.code === normalized?.split("-")[0]);
}

export function supportedLocale(tag: string | null | undefined): string | undefined {
  const language = getLanguage(tag);
  return language?.uiSupported ? language.code : undefined;
}
