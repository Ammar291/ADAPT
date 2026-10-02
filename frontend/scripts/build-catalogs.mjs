import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const base=path.resolve('frontend/src/i18n');
const en=JSON.parse(fs.readFileSync(path.join(base,'locales/en.json'),'utf8'));
const [header,...coreRows]=fs.readFileSync(path.join(base,'core-translations.txt'),'utf8').trim().split(/\r?\n/).map(line=>line.split('|'));
const rows=[...coreRows,...['screen-translations.txt','interpreter-translations.txt'].filter(file=>fs.existsSync(path.join(base,file))).flatMap(file=>{
  const [otherHeader,...messages]=fs.readFileSync(path.join(base,file),'utf8').trim().split(/\r?\n/).map(line=>line.split('|'));
  if(otherHeader.join('|')!==header.join('|'))throw Error(`Language columns differ in ${file}`);
  return messages;
})];
const codes=header.slice(1);
const catalogs=Object.fromEntries(codes.map(code=>[code,fs.existsSync(path.join(base,'locales',code+'.json'))?JSON.parse(fs.readFileSync(path.join(base,'locales',code+'.json'),'utf8')):{}]));
for(const row of rows){
  if(row.length!==header.length) throw Error(`Expected ${header.length} columns for ${row[0]}, got ${row.length}`);
  const english=row[0];
  let matches=Object.entries(en).filter(([,value])=>value.trim()===english);
  if(!matches.length){const key='common.'+crypto.createHash('sha1').update(english).digest('hex').slice(0,10);en[key]=english;matches=[[key,english]];}
  for(const [key,value] of matches) codes.forEach((code,i)=>{catalogs[code][key]=(value.startsWith(' ')?' ':'')+row[i+1]+(value.endsWith(' ')?' ':'');});
}
fs.writeFileSync(path.join(base,'locales/en.json'),JSON.stringify(en,null,2)+'\n');
for(const [code,catalog] of Object.entries(catalogs))fs.writeFileSync(path.join(base,'locales',code+'.json'),JSON.stringify(catalog,null,2)+'\n');
console.log(`Built ${codes.length+1} catalogs with ${rows.length} core translations each; English has ${Object.keys(en).length} entries.`);
