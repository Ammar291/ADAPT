import { tr } from "@/i18n";
import type { Capabilities, Pair } from "./types";

export function pairProblem(pair: Pair, cap: Capabilities): string | null {
  if (pair.source === pair.target) return tr("copy.choose_two_different_languages_959e0c7");
  for (const code of [pair.source, pair.target]) {
    const lang = cap.languages.find((item) => item.code === code);
    if (!lang?.input) return tr("copy.the_translation_service_does_not_offer_v0_in_thi_215b488", { v0: code });
    if (!lang.output && !(cap.fallback_enabled && lang.fallback)) return tr("copy.v0_is_supported_as_input_only_two_way_translatio_ee131dd", { v0: lang.name });
  }
  return null;
}
export function swapPair(pair: Pair): Pair { return { source: pair.target, target: pair.source }; }
export function pairFromSearch(search: string): Pair {
  const params = new URLSearchParams(search);
  return { source: (params.get("source") || "en").toLowerCase(), target: (params.get("target") || "ar").toLowerCase() };
}
export function direction(pair: Pair, speaker: "a" | "b"): Pair { return speaker === "a" ? pair : swapPair(pair); }
