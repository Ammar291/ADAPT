import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { LANGUAGE_STORAGE_KEY, applyDocumentLocale, catalogs, currentLocale, localize, readStoredLocale, resolveLocale, setUiLocale, tr, useLocale } from ".";
import { getLanguage, uiLanguages } from "./registry";
import { dueLabel, formatCurrency, formatDate, formatNumber, formatPercent, formatTime, relativeTime } from "@/lib/format";
import { buildGovernanceMap } from "@/features/knowledge/governance/model";
import { buildTwinMap } from "@/features/knowledge/twin/model";
import { buildTransitLayout } from "@/features/journey/layout";
import { sampleJourney } from "@/features/journey/testFixtures";
import { layoutWorkflow } from "@/features/agents/layout";
import { JOURNEY_WORKFLOW } from "@/services/mock/workflows";
import { governanceGraph } from "@/services/mock/governance";
import { buildUserGraph } from "@/services/mock/twin";
import { sampleProfile } from "@/services/mock/store";

let stored: Map<string, string>;
let root: { lang: string; dir: string };
beforeEach(async () => {
  stored = new Map();
  root = { lang: "en", dir: "ltr" };
  vi.stubGlobal("window", { localStorage: { getItem: (key: string) => stored.get(key) ?? null, setItem: (key: string, value: string) => stored.set(key, value) } });
  vi.stubGlobal("document", { documentElement: root });
  await setUiLocale("en", false);
});
afterEach(async () => { await setUiLocale("en", false); vi.unstubAllGlobals(); });

describe("UI language lifecycle", () => {
  it("offers all fourteen UI languages with central support metadata", () => {
    expect(uiLanguages.map((language) => language.code)).toEqual(["en", "ar", "hi", "ur", "ml", "ta", "te", "kn", "mr", "fr", "es", "de", "zh", "ja"]);
    for (const language of uiLanguages) {
      expect(language.nativeName).toBeTruthy();
      expect(language.englishName).toBeTruthy();
      expect(catalogs[language.code]).toBeDefined();
      expect(typeof language.assistantSupported).toBe("boolean");
      expect(typeof language.interpreterSupported).toBe("boolean");
    }
  });
  it("switches labels immediately without navigating or reloading", async () => {
    expect(localize("Settings")).toBe("Settings");
    await setUiLocale("ar");
    expect(currentLocale()).toBe("ar");
    expect(localize("Settings")).toBe("الإعدادات");
    expect(root).toEqual({ lang: "ar", dir: "rtl" });
    await setUiLocale("ja");
    expect(localize("Settings")).toBe("設定");
    expect(root).toEqual({ lang: "ja", dir: "ltr" });
  });
  it("persists only the locale code and restores it on the next visit", async () => {
    await setUiLocale("ml");
    expect([...stored]).toEqual([[LANGUAGE_STORAGE_KEY, "ml"]]);
    expect(readStoredLocale()).toBe("ml");
    expect(resolveLocale(undefined)).toBe("ml");
  });
  it("prioritizes profile, browser preference, browser language and English", () => {
    expect(resolveLocale("ur", "fr", ["ar-AE"])).toBe("ur");
    expect(resolveLocale(null, "fr", ["ar-AE"])).toBe("fr");
    expect(resolveLocale("unsupported", "unsupported", ["ko-KR", "hi-IN"])).toBe("hi");
    expect(resolveLocale(null, undefined, ["zz"])).toBe("en");
    expect(resolveLocale("ar_AE", "en", [])).toBe("ar");
  });
  it("continues when storage is denied or contains unsupported data", async () => {
    expect(readStoredLocale({ getItem: () => { throw Error("blocked"); } })).toBeUndefined();
    stored.set(LANGUAGE_STORAGE_KEY, '{"passport":"private"}');
    expect(readStoredLocale()).toBeUndefined();
    vi.stubGlobal("window", { get localStorage() { throw Error("blocked"); } });
    await setUiLocale("ur");
    expect(currentLocale()).toBe("ur");
    expect(root.dir).toBe("rtl");
  });
  it.each(["ar", "ur"])("uses true RTL for %s and restores LTR", async (locale) => {
    await setUiLocale(locale);
    expect(root.lang).toBe(locale);
    expect(root.dir).toBe("rtl");
    await setUiLocale("de");
    expect(root.dir).toBe("ltr");
  });
  it("falls back to English and never exposes a missing translation ID", async () => {
    expect(localize("")).toBe("");
    await setUiLocale("ar");
    const key = Object.keys(catalogs.en!).find((key) => !catalogs.ar![key] && catalogs.en![key])!;
    expect(tr(key)).toBe(catalogs.en![key]);
    expect(tr("dashboard.nonexistent")).toBe("غير متاح");
    await setUiLocale("not-supported");
    expect(root).toEqual({ lang: "en", dir: "ltr" });
  });
  it("keeps user data intact at the presentation boundary", async () => {
    const document = { passport: "private", name: "User Name" };
    await setUiLocale("ar");
    expect(localize(document)).toBe(document);
    expect(localize("User Name")).toBe("User Name");
    expect(tr("format.monthly", { amount: "Home" })).toContain("Home");
    expect(getLanguage("ur-PK")?.direction).toBe("rtl");
    expect(localize(12345.6)).toBe(new Intl.NumberFormat("ar").format(12345.6));
    applyDocumentLocale("fr");
    expect(root).toEqual({ lang: "fr", dir: "ltr" });
  });
  it("renders translated strings as escaped React text", async () => {
    function Label() { useLocale(); return createElement("span", null, tr("format.monthly", { amount: "<script>private</script>" })); }
    await setUiLocale("en");
    expect(renderToStaticMarkup(createElement(Label))).toContain("&lt;script&gt;");
  });
});

describe("locale-aware presentation", () => {
  it.each(["ar", "hi", "ml", "fr", "de", "zh", "ja"])("uses Intl for dates, times, amounts and percentages in %s", async (locale) => {
    await setUiLocale(locale);
    const date = new Date("2026-09-29T09:00:00Z");
    expect(formatDate(date)).toBe(new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" }).format(date));
    expect(formatTime(date)).toBe(new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date));
    expect(formatNumber(12345.6)).toBe(new Intl.NumberFormat(locale).format(12345.6));
    expect(formatCurrency(12345.6)).toBe(new Intl.NumberFormat(locale, { style: "currency", currency: "AED", minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(12345.6));
    expect(formatPercent(0.42)).toBe(new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(0.42));
    expect(dueLabel("2026-09-30", date)).toBe(new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(1, "day"));
    expect(relativeTime(new Date(date.getTime() - 7200000), date)).toBe(new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(-2, "hour"));
  });
});

describe("graph geometry is independent of language", () => {
  it("preserves governance, twin, journey and workflow nodes, edges and coordinates in RTL", async () => {
    const governance = governanceGraph();
    const twin = buildUserGraph(sampleProfile(), [], { displayName: "Sample User", observedAt: "2026-09-29T09:00:00Z", faithGranted: false });
    const journey = sampleJourney();
    const inputs = JSON.stringify({ governance, twin, journey, workflow: JOURNEY_WORKFLOW });
    const geometry = () => {
      const publicMap = buildGovernanceMap(governance, 1.8);
      const privateMap = buildTwinMap(twin, 1.8);
      return {
        governance: { nodes: publicMap.items.map(({ id, rect }) => ({ id, rect })), edges: publicMap.edges.map(({ id, source, target, path }) => ({ id, source, target, path })) },
        twin: { nodes: privateMap.items.map(({ id, rect }) => ({ id, rect })), edges: privateMap.edges.map(({ id, source, target, path }) => ({ id, source, target, path })) },
        journey: buildTransitLayout(journey),
        workflow: layoutWorkflow(JOURNEY_WORKFLOW, "horizontal"),
      };
    };
    const original = geometry();
    for (const locale of ["ar", "ur", "ja"]) { await setUiLocale(locale); expect(geometry()).toEqual(original); }
    expect(JSON.stringify({ governance, twin, journey, workflow: JOURNEY_WORKFLOW })).toBe(inputs);
  });
});
