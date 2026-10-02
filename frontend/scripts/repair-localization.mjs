import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
const root=path.resolve('frontend/src');
const catalogPath=path.join(root,'i18n/locales/en.json');
const catalog=JSON.parse(fs.readFileSync(catalogPath,'utf8'));
const machine=value=>/^[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*$/.test(value)||/^[a-z]+\/[\w+.*-]+$/.test(value)||/^\w+Error$/.test(value)||['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS','Content-Type','Accept','Cache-Control','Last-Event-ID','2-digit','useSyncExternalStore','ADAPT-Mock'].includes(value);
function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?e.name==='i18n'?[]:files(path.join(dir,e.name)):/\.tsx?$/.test(e.name)&&!e.name.includes('.test.')?[path.join(dir,e.name)]:[]);}
for(const file of files(root)){
 let source=fs.readFileSync(file,'utf8');
 const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,file.endsWith('.tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS);
 const edits=[];
 function visit(n){
  if(ts.isCallExpression(n)&&ts.isIdentifier(n.expression)&&n.expression.text==='tr'&&ts.isStringLiteral(n.arguments[0])){
   const text=catalog[n.arguments[0].text];
   if(text && (machine(text)||file.endsWith('actionCard.ts'))) {edits.push({start:n.getStart(ast),end:n.end,text:JSON.stringify(text)});return;}
  }
  // Avoid wrapping element trees or conditions that render element trees; those children subscribe themselves.
  if(ts.isCallExpression(n)&&ts.isIdentifier(n.expression)&&n.expression.text==='localize'&&n.arguments.length===1){
    const x=n.arguments[0];
    if(ts.isJsxElement(x)||ts.isJsxSelfClosingElement(x)||ts.isJsxFragment(x)||ts.isConditionalExpression(x)&&[x.whenTrue,x.whenFalse].some(v=>ts.isJsxElement(v)||ts.isJsxSelfClosingElement(v)||ts.isJsxFragment(v))||ts.isBinaryExpression(x)&&[x.left,x.right].some(v=>ts.isJsxElement(v)||ts.isJsxSelfClosingElement(v)||ts.isJsxFragment(v))){
      edits.push({start:n.getStart(ast),end:x.getStart(ast),text:''},{start:x.end,end:n.end,text:''});
    }
  }
  ts.forEachChild(n,visit);
 }
 visit(ast);
 for(const e of edits.sort((a,b)=>b.start-a.start))source=source.slice(0,e.start)+e.text+source.slice(e.end);
 // Drop unused bindings after pruning presentation wrappers.
 source=source.replace(/import \{ ([^}]+) \} from "@\/i18n";\n/,(_m,names)=>{
  const rest=source.slice(source.indexOf('\n')+1);
  const used=names.split(', ').filter(n=>new RegExp(`\\b${n}\\(`).test(rest));
  return used.length?`import { ${used.join(', ')} } from "@/i18n";\n`:'';
 });
 fs.writeFileSync(file,source);
}
for(const [key,value] of Object.entries(catalog))if(machine(value))delete catalog[key];
fs.writeFileSync(catalogPath,JSON.stringify(catalog,null,2)+'\n');
