import fs from 'node:fs';
const update=(file,fn)=>fs.writeFileSync(file,fn(fs.readFileSync(file,'utf8')));
update('frontend/src/components/ui/Controls.tsx',s=>s.replace(/tr\("copy\.[^"]+", \{ v0: option\.count \}\)/,'tr("common.items", { count: option.count })'));
update('frontend/src/features/home/HomePage.tsx',s=>s.replace('relativeTime }','relativeTime, formatNumber, formatPercent }')
 .replace('{localize(done)} {tr("copy.of_2449d65")}{localize(total)} {tr("copy.steps_done_f99ea48")}','{tr("home.stepsDone", { done, total })}')
 .replace('`${days} days until you arrive (${formatDate(arrival)})`','tr("home.arrivalIn", { days, date: formatDate(arrival) })')
 .replace('`You arrived ${formatDate(arrival)}`','tr("home.arrived", { date: formatDate(arrival) })')
 .replace('`You\'re ${percent}% of the way to settled.`','tr("home.settled", { percent: formatPercent(percent / 100) })')
 .replace('`${completion(plan).done} / ${completion(plan).total}`','`${formatNumber(completion(plan).done)} / ${formatNumber(completion(plan).total)}`')
 .replace('<dd className="tabular','<dd dir="ltr" className="tabular'));
// Consolidate the last redundant language-name table. Raw twin facts retain English names.
update('frontend/src/services/mock/twin.ts',s=>s.replace(/const LANGUAGE_NAME:[\s\S]*?export function buildUserGraph/,'export { languageName } from "@/lib/languages";\n\nexport function buildUserGraph').replace('import type {','import { languageName } from "@/lib/languages";\nimport type {'));
