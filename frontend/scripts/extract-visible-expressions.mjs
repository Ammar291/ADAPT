import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import ts from 'typescript';
const root=path.resolve('frontend/src');
const catalogPath=path.join(root,'i18n/locales/en.json');
const catalog=JSON.parse(fs.readFileSync(catalogPath,'utf8'));
const attributes=new Set(['label','title','hint','description','placeholder','aria-label','aria-description','aria-valuetext','alt','caption','tooltip','searchPlaceholder','content','message','detail','summary','emptyLabel','pendingLabel']);
const files=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?['vendor','locales'].includes(e.name)?[]:files(path.join(dir,e.name)):/\.tsx$/.test(e.name)&&!e.name.includes('.test.')?[path.join(dir,e.name)]:[]);
const keyFor=text=>{let key=Object.keys(catalog).find(k=>catalog[k]===text);if(!key){key='copy.'+text.toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/g,'').slice(0,48)+'_'+crypto.createHash('sha1').update(text).digest('hex').slice(0,7);catalog[key]=text;}return key;};
let messages=0,changed=0;
for(const file of files(root)){
 const source=fs.readFileSync(file,'utf8'),ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),edits=[];
 function value(node){
  if(ts.isParenthesizedExpression(node))return value(node.expression);
  if(ts.isStringLiteral(node)||ts.isNoSubstitutionTemplateLiteral(node)){if(/[\p{L}]/u.test(node.text)){edits.push({start:node.getStart(ast),end:node.end,text:`tr(${JSON.stringify(keyFor(node.text))})`});messages++;}return;}
  if(ts.isTemplateExpression(node)){const text=node.head.text+node.templateSpans.map((s,i)=>`{{v${i}}}${s.literal.text}`).join('');if(/[\p{L}]/u.test(node.head.text+node.templateSpans.map(s=>s.literal.text).join(''))){edits.push({start:node.getStart(ast),end:node.end,text:`tr(${JSON.stringify(keyFor(text))}, { ${node.templateSpans.map((s,i)=>`v${i}: ${s.expression.getText(ast)}`).join(', ')} })`});messages++;}return;}
  if(ts.isConditionalExpression(node)){value(node.whenTrue);value(node.whenFalse);return;}
  if(ts.isBinaryExpression(node)){if([ts.SyntaxKind.BarBarToken,ts.SyntaxKind.QuestionQuestionToken].includes(node.operatorToken.kind)){value(node.left);value(node.right);}else if(node.operatorToken.kind===ts.SyntaxKind.AmpersandAmpersandToken)value(node.right);return;}
  if(ts.isCallExpression(node)&&ts.isIdentifier(node.expression)&&node.expression.text==='localize')return value(node.arguments[0]);
 }
 function visit(node){if(ts.isJsxExpression(node)&&node.expression&&!node.dotDotDotToken&&(!ts.isJsxAttribute(node.parent)||attributes.has(node.parent.name.getText(ast))))value(node.expression);ts.forEachChild(node,visit);}
 visit(ast);
 if(!edits.length)continue;
 let result=source;for(const e of edits.sort((a,b)=>b.start-a.start))result=result.slice(0,e.start)+e.text+result.slice(e.end);
 if(!source.includes('import { tr')){if(/import \{[^}]+\} from "@\/i18n"/.test(result))result=result.replace(/import \{ ([^}]+) \} from "@\/i18n"/,'import { tr, $1 } from "@/i18n"');else result='import { tr } from "@/i18n";\n'+result;}
 fs.writeFileSync(file,result);changed++;
}
fs.writeFileSync(catalogPath,JSON.stringify(catalog,null,2)+'\n');
console.log({changed,messages,keys:Object.keys(catalog).length});
