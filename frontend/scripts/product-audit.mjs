/** Product regression audit. Run against a VITE_DATA_MODE=mock development server.
 * npm run audit:ui (requires Playwright), or set ADAPT_PLAYWRIGHT_MODULE to its file URL.
 * ADAPT_BASE_URL and ADAPT_BROWSER_EXECUTABLE can override the server and browser.
 * Screenshots and the machine-readable report go to frontend/qa-artifacts.
 */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const { chromium } = await import(process.env.ADAPT_PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.ADAPT_BASE_URL || 'http://127.0.0.1:5180';
const output = resolve('frontend/qa-artifacts');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.ADAPT_BROWSER_EXECUTABLE ? { executablePath: process.env.ADAPT_BROWSER_EXECUTABLE } : {}) });
const sizes = [{ width:390, height:844 }, { width:393, height:852 }, { width:430, height:932 }];
const routes = ['/onboarding','/home','/journey','/knowledge/governance','/knowledge/me','/agents','/documents','/discover','/simulate','/assistant','/profile','/settings'];
const report = { testedAt:new Date().toISOString(), data:'Isolated sample data; no live account or real document submissions', screens:[], interactions:[], errors:[] };
async function ready(page) {
 await page.getByRole('main').waitFor();
 await page.waitForFunction(() => !document.querySelector('[role="status"][aria-label^="Loading"]'));
 await page.evaluate(() => document.fonts.ready);
 await page.locator('main').waitFor({state:'visible'});
}
async function dismissNotifications(page) {
 for (const button of await page.getByRole('button',{name:'Dismiss notification'}).all()) if(await button.isVisible()) await button.click();
 await page.waitForFunction(()=>!document.querySelector('ol[aria-label="Notifications"] li'));
}
async function visit(page,route,seed=true) {
 await page.goto(base+route+(seed?(route.includes('?')?'&':'?')+'seed=sample':''));
 await ready(page);
 await dismissNotifications(page);
}
async function measure(page,label,viewport) {
 const dimensions=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight}));
 assert.ok(dimensions.scroll<=dimensions.width+1,`${label}: horizontal overflow ${dimensions.scroll}>${dimensions.width}`);
 const small=await page.locator('.adapt-button,.adapt-icon-button,.adapt-segment').evaluateAll(elements=>elements.filter(el=>{const box=el.getBoundingClientRect();return box.width>0&&box.height>0&&getComputedStyle(el).visibility!=='hidden'&&box.height<43.5;}).map(el=>({text:el.getAttribute('aria-label')||el.textContent,height:el.getBoundingClientRect().height})));
 assert.deepEqual(small,[],`${label}: touch targets smaller than 44px`);
 const visibleCopy=await page.locator('main').innerText();
 assert.equal(/Lorem ipsum|\bTODO\b|coming soon/.test(visibleCopy),false,`${label}: placeholder copy`);
 if(label==='/home') { const action=await page.locator('main .adapt-button').first().boundingBox(); assert.ok(action&&action.y+action.height<=viewport.height-64,`${label}: primary action must be visible above the mobile bottom bar`); }
 const slug=label.replaceAll('/','-').replaceAll('?','-').replaceAll('=','-');
 await page.screenshot({path:resolve(output,`${slug}-${viewport.width}x${viewport.height}.png`)});
 report.screens.push({screen:label,viewport,...dimensions,horizontalOverflow:false,touchTargets:'pass'});
}
async function interaction(name,task) { await task(); report.interactions.push({name,result:'pass'}); console.log('PASS '+name); }
try {
 for(const viewport of sizes) {
  const context=await browser.newContext({viewport,isMobile:true,hasTouch:true,reducedMotion:'reduce'});
  const page=await context.newPage();
  page.on('pageerror',error=>report.errors.push(error.message));
  for(const route of routes) { await visit(page,route,route!=='/onboarding'); await measure(page,route,viewport); }
  await interaction(`All destinations reachable via mobile menu ${viewport.width}`,async()=>{
   await page.getByRole('button',{name:'Open navigation'}).click();
   const menu=page.getByRole('dialog',{name:'Your workspace'});
   await menu.waitFor({state:'visible'});
   assert.equal(await menu.getByRole('link').count(),11);
   const box=await menu.boundingBox(); assert.ok(Math.abs(box.y+box.height-viewport.height)<2,'Menu should be a bottom sheet');
   assert.equal(await page.evaluate(()=>document.body.style.overflow),'hidden');
   await page.keyboard.press('Escape'); await menu.waitFor({state:'hidden'});
   assert.notEqual(await page.evaluate(()=>document.body.style.overflow),'hidden');
   assert.equal(await page.getByRole('button',{name:'Open navigation'}).evaluate(el=>el===document.activeElement),true,'Focus returns to menu trigger');
   await page.getByRole('navigation',{name:'Main',exact:true}).getByRole('link',{name:'Journey',exact:true}).click();
   await page.waitForURL('**/journey');
  });
  await interaction(`Search keyboard navigation ${viewport.width}`,async()=>{
   await page.getByRole('button',{name:'Search ADAPT',exact:true}).click();
   const input=page.getByRole('combobox',{name:'Search your workspace'});
   await input.fill('digital twin');
   await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
   await page.waitForURL('**/knowledge/me');
   await page.getByRole('button',{name:'Search ADAPT',exact:true}).click();
   await input.fill('zzzz-no-results');
   await page.getByText('No results for',{exact:false}).waitFor();
   await page.keyboard.press('Escape');
  });
  await interaction(`Camera, file picker, invalid upload and sheet focus ${viewport.width}`,async()=>{
   await visit(page,'/documents');
   await page.getByRole('button',{name:'Upload a document',exact:true}).click();
   const sheet=page.locator('dialog[open]'); await sheet.waitFor();
   await sheet.getByRole('button',{name:'Scan with camera'}).waitFor();
   assert.equal(await sheet.locator('input[capture="environment"]').count(),1);
   await sheet.locator('label').filter({hasText:'The page with your photo'}).click();
   const chooser=page.waitForEvent('filechooser'); await sheet.getByRole('button',{name:'Choose a file',exact:true}).click(); await chooser;
   await sheet.locator('input[type="file"]:not([capture])').setInputFiles({name:'invalid.txt',mimeType:'text/plain',buffer:Buffer.from('synthetic QA file')});
   await sheet.getByRole('alert').waitFor();
   await page.screenshot({path:resolve(output,`upload-error-${viewport.width}.png`)});
   await sheet.getByRole('button',{name:'Close',exact:true}).click();
   assert.notEqual(await page.evaluate(()=>document.body.style.overflow),'hidden');
  });
  await interaction(`Touch pan, node details and evidence ${viewport.width}`,async()=>{
   await visit(page,'/knowledge/governance');
   const pane=page.locator('.react-flow__pane'); await pane.waitFor();
   const before=await page.locator('.react-flow__viewport').getAttribute('style');
   const box=await pane.boundingBox(); const x=Math.round(box.x+box.width*0.7); const y=Math.round(box.y+50);
   const cdp=await context.newCDPSession(page);
   await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
   for(let i=1;i<=5;i++) await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x-i*16,y:y+i*4}]});
   await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
   await page.waitForFunction(previous=>document.querySelector('.react-flow__viewport')?.getAttribute('style')!==previous,before);
   await page.locator('button').filter({hasText:/^List$/}).click();
   const first=page.locator('main button').filter({hasText:'Initial approval'}).first();
   await first.click(); await page.locator('dialog[open]').waitFor();
   assert.ok(await page.locator('dialog[open] a[target="_blank"]').count()>0,'Evidence should be one click away');
   await page.keyboard.press('Escape');
   await visit(page,'/journey');
   await page.locator('button').filter({hasText:/^Map$/}).click(); await page.locator('.react-flow__pane').waitFor();
  });
  await interaction(`Nine onboarding steps and review ${viewport.width}`,async()=>{
   await visit(page,'/onboarding',false);
   await page.getByRole('button',{name:'Answer quick questions',exact:true}).click();
   await page.getByRole('radio',{name:'Taking up a job',exact:true}).click();
   await page.getByRole('checkbox',{name:"I'm flexible or don't know yet"}).check();
   await page.getByRole('button',{name:'Continue',exact:true}).click();
   await page.getByRole('radio',{name:'Moving alone',exact:true}).click();
   await page.getByRole('radio',{name:'No',exact:true}).click();
   await page.getByRole('button',{name:'Skip for now',exact:true}).click();
   await page.getByRole('button',{name:'Skip',exact:true}).click();
   await page.getByRole('radio',{name:'Keep them general',exact:false}).click();
   await page.getByRole('radio',{name:'Leave them out',exact:true}).click();
   await page.getByRole('button',{name:'Continue',exact:true}).click();
   await page.getByRole('button',{name:'Build my plan',exact:true}).waitFor();
   await measure(page,'/onboarding-review',viewport);
   await page.screenshot({path:resolve(output,`onboarding-review-full-${viewport.width}.png`),fullPage:true});
  });
  await interaction(`Voice entry and text conversation ${viewport.width}`,async()=>{
   await visit(page,'/home');
   await page.getByRole('button',{name:'Open the assistant'}).click(); await page.locator('dialog[open]').waitFor();
   await page.keyboard.press('Escape');
   await visit(page,'/assistant');
   const composer=page.getByRole('textbox',{name:'Message ADAPT'});
   await composer.fill("What's next in my plan?"); await composer.press('Enter');
   await page.getByText('You',{exact:true}).waitFor();
   await page.waitForFunction(()=>document.querySelectorAll('[dir="auto"]').length>=2);
   assert.equal(await composer.inputValue(),'');
  });
  await interaction(`Approvals disclose consequences ${viewport.width}`,async()=>{
   await visit(page,'/documents?tab=approvals');
   await page.getByRole('heading',{name:'Waiting for your approval'}).waitFor();
   await page.getByText('Exactly what will be shared').first().waitFor();
   await page.getByRole('button',{name:'Not now',exact:true}).first().click();
   await page.getByText('Nothing was sent. You can prepare it again later.',{exact:true}).waitFor();
   await measure(page,'/documents-approvals',viewport);
  });
  await interaction(`Simulation produces a comparison ${viewport.width}`,async()=>{
   await visit(page,'/simulate');
   await page.getByRole('button',{name:'Move alone first',exact:true}).click();
   await page.getByRole('button',{name:'Run simulation',exact:true}).click();
   await page.getByText('Testing your what-if',{exact:true}).waitFor();
   await page.waitForFunction(()=>!document.querySelector('[aria-label="Simulation progress"]'),{timeout:30000});
   await page.screenshot({path:resolve(output,`simulation-result-${viewport.width}.png`)});
   assert.ok((await page.locator('main').innerText()).includes('Your plan'),'Simulation must explain comparison with current plan');
  });
  await context.close();
 }
 const desktop=await browser.newContext({viewport:{width:1440,height:960},reducedMotion:'reduce'});
 const page=await desktop.newPage(); page.on('pageerror',e=>report.errors.push(e.message));
 for(const route of routes) { await visit(page,route,route!=='/onboarding'); await page.screenshot({path:resolve(output,`desktop${route.replaceAll('/','-')}.png`)}); }
 await interaction('Desktop command shortcut and route title',async()=>{
  await page.keyboard.press('Control+k'); await page.getByRole('combobox',{name:'Search your workspace'}).fill('governance'); await page.keyboard.press('Enter'); await page.waitForURL('**/knowledge/governance'); await page.waitForFunction(()=>document.title==='Governance · ADAPT');
 });
 await page.emulateMedia({colorScheme:'dark'}); await visit(page,'/home'); await page.screenshot({path:resolve(output,'desktop-home-dark.png')});
 await desktop.close();
 assert.deepEqual(report.errors,[],'Uncaught browser errors');
 report.result='pass';
} catch(error) { report.result='fail'; report.failure=error.stack; console.error(error); process.exitCode=1; }
finally { await writeFile(resolve(output,'product-audit.json'),JSON.stringify(report,null,2)); await browser.close(); }
console.log(JSON.stringify({result:report.result,screens:report.screens.length,interactions:report.interactions.length,errors:report.errors},null,2));
