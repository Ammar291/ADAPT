/** Frontend lint rules using the project's existing TypeScript parser. No network tooling required. */
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
const root=path.resolve('src');
const base=path.join(root,'i18n/locales');
const en=JSON.parse(fs.readFileSync(path.join(base,'en.json'),'utf8'));
const errors=[];
const attributes=new Set(['label','title','description','placeholder','aria-label','aria-description','aria-valuetext','alt','caption','tooltip','searchPlaceholder','content','before','after','emptyLabel','pendingLabel','hint','detail','summary','message']);
function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?e.name==='vendor'?[]:files(path.join(dir,e.name)):/\.(ts|tsx)$/.test(e.name)&&!e.name.includes('.test.')&&!e.name.includes('.d.ts')?[path.join(dir,e.name)]:[]);}
for(const file of files(root)){
 const source=fs.readFileSync(file,'utf8'),ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,file.endsWith('.tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS);
 function issue(node,rule){const pos=ast.getLineAndCharacterOfPosition(node.getStart(ast));errors.push(`${path.relative(root,file)}:${pos.line+1}: ${rule}: ${node.getText(ast).slice(0,120)}`);}
 function visibleValue(node){
  if(ts.isParenthesizedExpression(node))return visibleValue(node.expression);
  if((ts.isStringLiteral(node)||ts.isNoSubstitutionTemplateLiteral(node))&&/[\p{L}]/u.test(node.text))issue(node,'no hardcoded conditional copy');
  if(ts.isTemplateExpression(node)&&/[\p{L}]/u.test(node.head.text+node.templateSpans.map(s=>s.literal.text).join('')))issue(node,'localize the full sentence template');
  if(ts.isConditionalExpression(node)){visibleValue(node.whenTrue);visibleValue(node.whenFalse);}
  if(ts.isBinaryExpression(node)){
   if([ts.SyntaxKind.BarBarToken,ts.SyntaxKind.QuestionQuestionToken].includes(node.operatorToken.kind)){visibleValue(node.left);visibleValue(node.right);}
   else if(node.operatorToken.kind===ts.SyntaxKind.AmpersandAmpersandToken)visibleValue(node.right);
  }
  if(ts.isCallExpression(node)&&ts.isIdentifier(node.expression)&&node.expression.text==='localize')visibleValue(node.arguments[0]);
 }
 function visit(node){
  if(ts.isJsxText(node)&&/[\p{L}]/u.test(node.getText(ast)))issue(node,'no hardcoded JSX copy');
  if(ts.isJsxAttribute(node)&&attributes.has(node.name.getText(ast))&&node.initializer&&ts.isStringLiteral(node.initializer)&&/[\p{L}]/u.test(node.initializer.text))issue(node,'localize accessible and visible attributes');
  if(ts.isJsxExpression(node)&&node.expression&&!node.dotDotDotToken&&(!ts.isJsxAttribute(node.parent)||attributes.has(node.parent.name.getText(ast))))visibleValue(node.expression);
  if(ts.isCallExpression(node)&&ts.isIdentifier(node.expression)&&node.expression.text==='tr'&&ts.isStringLiteral(node.arguments[0])&&!en[node.arguments[0].text])issue(node,'unknown translation key');
  ts.forEachChild(node,visit);
 }
 visit(ast);
}
const tokens=value=>[...value.matchAll(/\{\{\s*([\w.]+)(?:\s*,[^}]+)?\s*\}\}/g)].map(m=>m[1]).sort().join(',');
for(const file of fs.readdirSync(base).filter(file=>file.endsWith('.json')&&file!=='en.json')){
 const catalog=JSON.parse(fs.readFileSync(path.join(base,file),'utf8'));
 for(const [key,value] of Object.entries(catalog)){
  if(typeof value!=='string'||!value.trim())errors.push(`${file}: ${key}: empty or non-string translation`);
  if(!en[key])errors.push(`${file}: ${key}: unknown English key`);
  else if(tokens(value)!==tokens(en[key]))errors.push(`${file}: ${key}: interpolation tokens differ`);
 }
}
if(errors.length){console.error(errors.join('\n'));process.exitCode=1;}else console.log(`Frontend lint passed: JSX copy, accessibility labels, translation keys and interpolation tokens (${Object.keys(en).length} English messages).`);
