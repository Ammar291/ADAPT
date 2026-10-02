/** One-time, AST-based migration. Never translates enum values, routes, API bodies or CSS. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import ts from 'typescript';

const root = path.resolve('frontend/src');
const catalogPath = path.join(root, 'i18n/locales/en.json');
const catalog = fs.existsSync(catalogPath) ? JSON.parse(fs.readFileSync(catalogPath, 'utf8')) : {};
const displayNames = new Set(['label', 'title', 'hint', 'description', 'placeholder', 'aria-label', 'alt', 'caption', 'tooltip', 'detail', 'message', 'emptyLabel', 'pendingLabel', 'valueText', 'searchPlaceholder', 'text', 'summary']);
const human = text => /[A-Za-z]/.test(text) && !/^(?:https?:|\/|#|@|\.)/.test(text) && !/[{}]|(?:^|\s)(?:bg-|text-|border-|flex|grid|inline-flex|absolute|relative|rounded-|font-|size-|h-|w-|px-|py-|mt-|gap-|opacity-|items-|justify-|transition-|\[)/.test(text) && !/^[a-z][a-z\d_.:-]*$/.test(text);
const keyFor = text => {
  let key = Object.keys(catalog).find(k => catalog[k] === text);
  if (!key) {
    key = `copy.${text.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 48) || 'text'}_${crypto.createHash('sha1').update(text).digest('hex').slice(0, 7)}`;
    catalog[key] = text;
  }
  return key;
};
const ancestors = function* (node) { for (let p=node.parent; p; p=p.parent) yield p; };
function cleanJsx(text) {
  const lines = text.split(/\r\n|\n|\r/);
  let last = 0;
  lines.forEach((line,i) => { if (/[^ \t]/.test(line)) last=i; });
  return lines.map((line,i) => {
    let value=line.replace(/\t/g,' ');
    if (i !== 0) value=value.replace(/^ +/,'');
    if (i !== lines.length-1) value=value.replace(/ +$/,'');
    return value && i !== last ? `${value} ` : value;
  }).join('');
}
function files(dir) { return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e => e.isDirectory() ? (e.name === 'i18n' ? [] : files(path.join(dir,e.name))) : /\.(tsx|ts)$/.test(e.name) && !/\.test\.|testFixtures|types\.ts$/.test(e.name) ? [path.join(dir,e.name)] : []); }
let changed=0;
for (const file of files(root)) {
  if (/[/\\](services|domain)[/\\]/.test(file)) continue; // Raw evidence, graph and user data stay unchanged.
  const source=fs.readFileSync(file,'utf8');
  if (source.includes('from "@/i18n"')) continue;
  const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const edits=[]; let translated=false; let rendered=false;
  const add=(start,end,text)=>edits.push({start,end,text});
  function replacement(node, text, values) {
    const key=keyFor(text); translated=true;
    const inFunction=[...ancestors(node)].some(ts.isFunctionLike);
    return `tr(${JSON.stringify(key)}${values ? `, { ${values} }` : !inFunction ? ', { lng: "en" }' : ''})`;
  }
  function visit(node) {
    if (ts.isTypeNode(node) || ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return;
    if (ts.isJsxText(node)) {
      const text=cleanJsx(node.getText(ast));
      if (text.trim()) { add(node.getStart(ast),node.end,`{${replacement(node,text)}}`); }
      return;
    }
    if (ts.isJsxAttribute(node)) {
      if (!displayNames.has(node.name.getText(ast))) return; // onClick, className, value, id, href etc are not copy.
      if (node.initializer && ts.isStringLiteral(node.initializer)) {
        add(node.initializer.getStart(ast),node.initializer.end,`{${replacement(node,node.initializer.text)}}`);
        return;
      }
    }
    if (ts.isJsxExpression(node) && node.expression && !node.dotDotDotToken) {
      const parent=node.parent;
      if (!ts.isJsxAttribute(parent) || displayNames.has(parent.name.getText(ast))) {
        // Presentation boundary only: exact catalog matches, never machine IDs or arbitrary user text.
        add(node.expression.getStart(ast),node.expression.getStart(ast),'localize(');
        add(node.expression.end,node.expression.end,')');
        rendered=true;
      }
    }
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      const parent=node.parent;
      if (ts.isPropertyAssignment(parent) && parent.name === node || ts.isElementAccessExpression(parent) || ts.isBinaryExpression(parent) && ![ts.SyntaxKind.QuestionQuestionToken,ts.SyntaxKind.BarBarToken].includes(parent.operatorToken.kind) || ts.isCaseClause(parent)) return;
      const props=[...ancestors(node)].filter(p=>ts.isJsxAttribute(p)||ts.isPropertyAssignment(p));
      if (props.some(p=>p.name && ['className','style','classNames','to','href','key','id','value','code','kind','status','type','event'].includes(p.name.getText(ast)))) return;
      const displayProp=ts.isPropertyAssignment(parent)&&displayNames.has(parent.name.getText(ast));
      if ((displayProp && /[A-Za-z]/.test(node.text)) || human(node.text)) {
        if (ts.isCallExpression(parent) && (ts.isIdentifier(parent.expression) && ['cn','querySelector','getElementById','navigate','includes','startsWith','endsWith','setItem','getItem','removeItem','addEventListener','removeEventListener','dispatch','getContext','import','replace','replaceAll'].includes(parent.expression.text) || ts.isPropertyAccessExpression(parent.expression) && ['includes','startsWith','endsWith','replace','replaceAll','split','join','querySelector','getElementById','addEventListener','removeEventListener','getItem','setItem','removeItem'].includes(parent.expression.name.text))) return;
        add(node.getStart(ast),node.end,replacement(node,node.text));
      }
      return;
    }
    if (ts.isTemplateExpression(node)) {
      const parent=node.parent;
      const isDisplay=ts.isJsxExpression(parent) || ts.isPropertyAssignment(parent)&&displayNames.has(parent.name.getText(ast)) || ts.isReturnStatement(parent);
      if (isDisplay && human(node.head.text + node.templateSpans.map(s=>s.literal.text).join(' '))) {
        const text=node.head.text+node.templateSpans.map((s,i)=>`{{v${i}}}${s.literal.text}`).join('');
        const values=node.templateSpans.map((s,i)=>`v${i}: ${s.expression.getText(ast)}`).join(', ');
        add(node.getStart(ast),node.end,replacement(node,text,values));
        return;
      }
    }
    ts.forEachChild(node,visit);
  }
  visit(ast);
  if (!translated && !rendered) continue;
  // Every component subscribes so labels and ARIA update without a page reload or remount.
  let subscribed=false;
  function hooks(node) {
    if (ts.isFunctionLike(node) && node.body && ts.isBlock(node.body)) {
      const name=node.name?.getText(ast) ?? (ts.isVariableDeclaration(node.parent) ? node.parent.name.getText(ast) : '');
      if (/^[A-Z]/.test(name) && source.slice(node.body.pos,node.body.end).includes('<')) {
        const memos=[];
        function findMemo(n) {
          if (n !== node && ts.isFunctionLike(n) && n.name && /^[A-Z]/.test(n.name.getText(ast))) return;
          if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && ['useMemo','useCallback'].includes(n.expression.text) && ts.isArrayLiteralExpression(n.arguments[1])) memos.push(n.arguments[1]);
          ts.forEachChild(n,findMemo);
        }
        findMemo(node.body);
        add(node.body.getStart(ast)+1,node.body.getStart(ast)+1,memos.length ? '\n  const uiLocale = useLocale();' : '\n  useLocale();');
        for (const deps of memos) add(deps.end-1,deps.end-1,`${deps.elements.length ? ', ' : ''}uiLocale`);
        subscribed=true;
      }
    }
    ts.forEachChild(node,hooks);
  }
  if (file.endsWith('.tsx')) hooks(ast);
  const imports=[translated&&'tr',rendered&&'localize',subscribed&&'useLocale'].filter(Boolean);
  edits.sort((a,b)=>b.start-a.start || b.end-a.end);
  let output=source;
  for (const edit of edits) output=output.slice(0,edit.start)+edit.text+output.slice(edit.end);
  fs.writeFileSync(file,`import { ${imports.join(', ')} } from "@/i18n";\n${output}`);
  changed++;
}
fs.mkdirSync(path.dirname(catalogPath),{recursive:true});
fs.writeFileSync(catalogPath,JSON.stringify(catalog,null,2)+'\n');
console.log(`Migrated ${changed} files; ${Object.keys(catalog).length} catalog entries.`);
