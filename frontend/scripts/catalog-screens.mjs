import fs from 'node:fs';
const c=JSON.parse(fs.readFileSync('frontend/src/i18n/locales/en.json','utf8'));
for(const f of ['home/HomePage','journey/JourneyPage','knowledge/KnowledgeLayout','knowledge/GovernanceGraphPage','knowledge/TwinGraphPage','agents/AgentsPage','documents/DocumentsPage','discover/DiscoverPage','simulate/SimulatePage','assistant/AssistantPage','settings/SettingsPage']) {
  const s=fs.readFileSync('frontend/src/features/'+f+'.tsx','utf8');
  console.log(f);
  const keys=[...s.matchAll(/(?:title|description|placeholder|label)=\{tr\("([^"]+)"/g)].map(m=>m[1]);
  console.log(keys.map(key=>c[key]).join('\n'));
}
