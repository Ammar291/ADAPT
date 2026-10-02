import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve('frontend/src');
function edit(file,fn){const p=path.join(root,file);fs.writeFileSync(p,fn(fs.readFileSync(p,'utf8')));}
edit('lib/languages.ts',()=>`import { getLanguage, languages } from "@/i18n/registry";
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
`);
// Mocks are also private application state. Remove the old browser-persisted profile/plan entirely.
edit('services/mock/store.ts',s=>s.replace(/Privacy: everything lives in memory\.[\s\S]*?persisted\./,'Privacy: profile, plan, graph, documents and consents live only in memory.\n * Only the UI language code is persisted by the central localization layer.')
  .replace(/interface Persisted \{[\s\S]*?\n\}\n\n/,'')
  .replace('  uiLocale: "en",','  uiLocale: resolveLocale(),')
  .replace('import type { ActionRecord', 'import { resolveLocale } from "@/i18n";\nimport type { ActionRecord')
  .replace('seed: Persisted["seed"]','seed: "sample" | "onboarding" | null')
  .replace('    this.load();','    try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* legacy storage unavailable */ }')
  .replace('    this.persist();\n','')
  .replace(/  private persist\(\) \{[\s\S]*?\n  reset\(\) \{/,'  reset() {')
  .replace(/\/\*\* Faith and free text are never written to storage\. \*\/\nfunction withoutPrivateText[\s\S]*?\n\}\n\n/,''));
// Current wording must match separate interface/conversation preferences and safe browser persistence.
const catalogPath=path.join(root,'i18n/locales/en.json');
const en=JSON.parse(fs.readFileSync(catalogPath,'utf8'));
for(const key of Object.keys(en)){
  if(en[key]==='ADAPT talks and writes to you in this language, by voice and in text. Menus and labels are in English for now.') en[key]='ADAPT talks and writes to you in this language, by voice and in text. Choose the interface language separately.';
  if(en[key].includes('The only thing saved in this browser is your theme.')) en[key]=en[key].replace('The only thing saved in this browser is your theme.','Only your theme and interface language are saved in this browser.');
}
Object.assign(en,{
  'common.unavailable':'Unavailable',
  'language.choose':'Choose language',
  'language.interface':'Interface language',
  'language.available':'Available languages',
  'language.description':'Choose the language for menus, labels and messages. Your assistant conversation language is set separately.',
  'language.savedOnDevice':'Language saved on this device',
  'language.syncFailed':'Your account could not be updated. Reconnect and choose the language again to save it to your profile.',
  'format.monthly':'{{amount}} a month',
  'format.budgetUpTo':'Up to {{amount}} a month',
  'graph.zoomIn':'Zoom in',
  'graph.zoomOut':'Zoom out',
  'graph.fit':'Fit graph to view',
  'graph.minimap':'Graph overview',
  'graph.controls':'Graph controls',
});
fs.writeFileSync(catalogPath,JSON.stringify(en,null,2)+'\n');
edit('features/simulate/model.ts',s=>'import { formatCurrency } from "@/lib/format";\n'+s.replace('`AED ${new Intl.NumberFormat(tr("copy.en_gb_db54f7f")).format(value)} a month`','tr("format.monthly", { amount: formatCurrency(value) })'));
edit('features/profile/summary.ts',s=>'import { formatCurrency } from "@/lib/format";\n'+s.replace('`Up to AED ${profile.monthlyHousingBudgetAed.toLocaleString(tr("copy.en_gb_db54f7f"))} a month`','tr("format.budgetUpTo", { amount: formatCurrency(profile.monthlyHousingBudgetAed) })'));
edit('features/knowledge/twin/facts.ts',s=>'import { formatNumber } from "@/lib/format";\n'+s.replaceAll('value.toLocaleString(tr("copy.en_gb_db54f7f"))','formatNumber(value)'));
edit('features/knowledge/governance/model.ts',s=>'import { formatNumber, formatCurrency } from "@/lib/format";\n'+s.replaceAll('`AED ${value.toLocaleString(tr("copy.en_gb_db54f7f"))}`','formatCurrency(value)').replaceAll('`AED ${value.toLocaleString("en-GB")}`','formatCurrency(value)').replaceAll('value.toLocaleString(tr("copy.en_gb_db54f7f"))','formatNumber(value)'));
// Graph canvases retain mathematical LTR coordinates, while text, controls and sibling panels follow the UI direction.
edit('features/knowledge/explorer/GraphExplorer.tsx',s=>s.replace('data-kg={scope}','dir="ltr"\n                data-kg={scope}'));
edit('features/agents/WorkflowGraph.tsx',s=>s.replace('<div ref={ref} className={cn("adapt-flow','<div ref={ref} dir="ltr" className={cn("adapt-flow'));
edit('features/onboarding/OnboardingPage.tsx',s=>'import { LanguageSelector } from "@/i18n/LanguageSelector";\n'+s.replace('<Wordmark className="lg:hidden" />','<Wordmark className="lg:hidden" />\n            <LanguageSelector className="ms-auto" />'));
