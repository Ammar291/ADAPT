import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import ts from 'typescript';
const root=path.resolve('frontend/src');
const p=path.join(root,'i18n/locales/en.json');
const catalog=JSON.parse(fs.readFileSync(p,'utf8'));
const display=new Set(['label','title','description','placeholder','aria-label','aria-description','aria-valuetext','alt','caption','tooltip','searchPlaceholder','content']);
const keyFor=text=>{
 let key=Object.keys(catalog).find(k=>catalog[k]===text);
 if(!key){key='copy.'+text.toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/g,'').slice(0,48)+'_'+crypto.createHash('sha1').update(text).digest('hex').slice(0,7);catalog[key]=text;}
 return key;
};
const clean=text=>text.trim().replace(/\s*\n\s*/g,' ');
function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?e.name==='i18n'?[]:files(path.join(dir,e.name)):/\.tsx$/.test(e.name)?[path.join(dir,e.name)]:[]);}
for(const file of files(root)){
 if(file.includes(path.join('features','interpreter')))continue;
 let source=fs.readFileSync(file,'utf8');
 const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX), edits=[];
 function visit(node){
  if(ts.isJsxText(node)&&/[\p{L}]/u.test(node.getText(ast))){const text=clean(node.getText(ast));edits.push({start:node.getStart(ast),end:node.end,text:`{tr(${JSON.stringify(keyFor(text))})}`});return;}
  if(ts.isJsxAttribute(node)&&node.initializer&&ts.isStringLiteral(node.initializer)&&display.has(node.name.getText(ast))&&/[\p{L}]/u.test(node.initializer.text)){
   edits.push({start:node.initializer.getStart(ast),end:node.initializer.end,text:`{tr(${JSON.stringify(keyFor(node.initializer.text))})}`});return;
  }
  if(ts.isCallExpression(node)&&ts.isIdentifier(node.expression)&&node.expression.text==='tr'&&ts.isStringLiteral(node.arguments[0])&&catalog[node.arguments[0].text]==='') {edits.push({start:node.getStart(ast),end:node.end,text:'""'});return;}
  ts.forEachChild(node,visit);
 }
 visit(ast);
 if(!edits.length)continue;
 for(const e of edits.sort((a,b)=>b.start-a.start))source=source.slice(0,e.start)+e.text+source.slice(e.end);
 if(!source.includes('from "@/i18n"')) source='import { tr } from "@/i18n";\n'+source;
 else if(!/^import \{ [^}]*\btr\b/m.test(source))source=source.replace('import { ','import { tr, ');
 fs.writeFileSync(file,source);
}
fs.writeFileSync(p,JSON.stringify(catalog,null,2)+'\n');
