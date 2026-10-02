import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
const root=path.resolve('frontend/src');
const p=path.join(root,'i18n/locales/en.json');
const en=JSON.parse(fs.readFileSync(p,'utf8'));
function edit(file,fn){const p=path.join(root,file);fs.writeFileSync(p,fn(fs.readFileSync(p,'utf8')));}
function walk(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?e.name==='i18n'?[]:walk(path.join(dir,e.name)):/\.tsx?$/.test(e.name)&&!e.name.includes('.test.')?[path.join(dir,e.name)]:[]);}
for(const file of walk(root)){
 let source=fs.readFileSync(file,'utf8');
 const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,file.endsWith('.tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS), edits=[];
 function visit(node){
  if(ts.isCallExpression(node)&&ts.isIdentifier(node.expression)&&node.expression.text==='tr'&&ts.isStringLiteral(node.arguments[0])){
    const value=en[node.arguments[0].text];
    if(value && (/^--/.test(value)||/^[a-z]{2}-[A-Z]{2}$/.test(value)||['NFKD'].includes(value))) {edits.push({start:node.getStart(ast),end:node.end,text:JSON.stringify(value)});return;}
  }
  if(ts.isCallExpression(node)&&ts.isIdentifier(node.expression)&&node.expression.text==='localize'&&node.arguments.length===1){
    let x=node.arguments[0];
    while(ts.isParenthesizedExpression(x))x=x.expression;
    if(ts.isJsxElement(x)||ts.isJsxSelfClosingElement(x)||ts.isJsxFragment(x)||ts.isConditionalExpression(x)||ts.isBinaryExpression(x)&&x.operatorToken.kind===ts.SyntaxKind.AmpersandAmpersandToken||ts.isCallExpression(x)&&ts.isPropertyAccessExpression(x.expression)&&['map','filter'].includes(x.expression.name.text)){
      const argument=node.arguments[0];
      edits.push({start:node.getStart(ast),end:argument.getStart(ast),text:''},{start:argument.end,end:node.end,text:''});
    }
  }
  ts.forEachChild(node,visit);
 }
 visit(ast);
 for(const e of edits.sort((a,b)=>b.start-a.start))source=source.slice(0,e.start)+e.text+source.slice(e.end);
 fs.writeFileSync(file,source);
}
// Add the same device-only selector to pre-session/offline and isolated demo shells.
edit('app/SessionGate.tsx',s=>s.replace('<span className="ms-auto flex items-center gap-1.5 text-xs text-muted">','<LanguagePicker className="ms-auto" /><span className="flex items-center gap-1.5 text-xs text-muted">'));
edit('features/demo/HeroDemoPage.tsx',s=>s.replace('<div className="hero-demo">','<div className="hero-demo"><div className="px-4 pt-3 lg:absolute lg:end-4 lg:top-0 lg:z-20"><LanguagePicker /></div>'));
// Known graph-library strings are centrally localized, including tooltips and hidden descriptions.
for(const file of ['features/journey/TransitMap.tsx','features/agents/WorkflowGraph.tsx','features/knowledge/explorer/GraphExplorer.tsx']){
 edit(file,s=>'import { graphA11y } from "@/i18n/graphA11y";\n'+s.replace(/ariaLabelConfig=\{\{[\s\S]*?\}\}/g,'ariaLabelConfig={graphA11y()}').replace(/(<ReactFlow(?:<[^\n]+>)?\n)(?![^]*ariaLabelConfig=)/,'$1'));
 // GraphExplorer already had config. Insert it into the other ReactFlow instances.
 if(!file.includes('GraphExplorer'))edit(file,s=>s.replace(/(<ReactFlow<[^\n]+>\n)/,'$1        ariaLabelConfig={graphA11y()}\n'));
}
const cssPath=path.join(root,'styles/index.css');
fs.appendFileSync(cssPath,`
/* Graph geometry is always LTR. Localize node text and controls without reflecting coordinates. */
:root[dir="rtl"] .adapt-flow .react-flow__node { direction: rtl; text-align: start; }
:root[dir="rtl"] .adapt-flow .react-flow__panel { direction: rtl; }
:root[dir="rtl"] .adapt-flow .react-flow__panel.left { left: auto; right: 0; }
:root[dir="rtl"] .adapt-flow .react-flow__panel.right { right: auto; left: 0; }
:root[dir="rtl"] .adapt-flow .react-flow__minimap { margin-left: 0 !important; margin-right: 60px; }
:root[dir="rtl"] .adapt-flow .react-flow__edge-label { direction: rtl; }
:root[dir="rtl"] .adapt-switch [data-state="unchecked"] { transform: translateX(-2px); }
:root[dir="rtl"] .workspace-bar .lucide-chevron-right,
:root[dir="rtl"] .lucide-chevron-left:not(.flip-rtl),
:root[dir="rtl"] .lucide-arrow-up-right:not(.flip-rtl) { transform: scaleX(-1); }
:root[lang="ar"] body, :root[lang="ur"] body { line-height: 1.65; }
:root[dir="rtl"] .uppercase { letter-spacing: normal; }
:root:is([lang="hi"], [lang="mr"], [lang="ml"], [lang="ta"], [lang="te"], [lang="kn"]) body { line-height: 1.7; }
`);
Object.assign(en,{
 'graph.keyboard':'Press Enter to open details. Press Escape to close them. Tab moves to the next item.',
 'graph.openDetails':'Press Enter to open details.',
 'graph.connection':'Graph connection',
 'graph.interaction':'Toggle graph interaction',
 'interpreter.title':'Interpreter',
 'interpreter.description':'Translate a conversation using your ADAPT assistant.',
 'interpreter.target':'Translate into',
 'interpreter.placeholder':'Enter the text you want to translate',
 'interpreter.translate':'Translate',
 'interpreter.instruction':'Translate the following text into {{language}}. Provide the translation and do not perform any other action. Text: {{text}}',
});
fs.writeFileSync(p,JSON.stringify(en,null,2)+'\n');
