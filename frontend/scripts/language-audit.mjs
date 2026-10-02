/** Real Chromium checks against a production PWA build and synthetic mock data only. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir, mkdtemp } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
const { chromium } = await import(process.env.ADAPT_PLAYWRIGHT_MODULE || 'playwright');
const root=resolve('frontend/dist');
const output=resolve('frontend/qa-artifacts');
await mkdir(output,{recursive:true});
const types={'.html':'text/html','.js':'application/javascript','.css':'text/css','.webmanifest':'application/manifest+json','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.woff2':'font/woff2'};
const server=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1');
 if(/^\/(api|private|uploads)(\/|$)/.test(url.pathname)){res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify({syntheticPrivateDocument:true}));return;}
 let file=resolve(root,'.'+decodeURIComponent(url.pathname));
 if(file!==root&&!file.startsWith(root+sep)){res.writeHead(403);res.end();return;}
 try{if(file===root)file=resolve(root,'index.html');const bytes=await readFile(file);res.writeHead(200,{'Content-Type':types[extname(file)]||'application/octet-stream'});res.end(bytes);}
 catch{if(extname(url.pathname)){res.writeHead(404);res.end();return;}res.writeHead(200,{'Content-Type':'text/html'});res.end(await readFile(resolve(root,'index.html')));}
});
await new Promise(done=>server.listen(5184,'127.0.0.1',done));
const profile=await mkdtemp(resolve(output,'i18n-profile-'));
const context=await chromium.launchPersistentContext(profile,{headless:true,viewport:{width:1440,height:1000},reducedMotion:'reduce',...(process.env.ADAPT_BROWSER_EXECUTABLE?{executablePath:process.env.ADAPT_BROWSER_EXECUTABLE}:{})});
const page=await context.newPage();
const report={checks:[],errors:[],result:'pending'};
page.on('pageerror',error=>report.errors.push(error.message));
const base='http://127.0.0.1:5184';
const en=JSON.parse(await readFile(resolve('frontend/src/i18n/locales/en.json'),'utf8'));
const labels={en:'English',ar:'العربية',hi:'हिन्दी',ur:'اردو',ml:'മലയാളം',ta:'தமிழ்',te:'తెలుగు',kn:'ಕನ್ನಡ',mr:'मराठी',fr:'Français',es:'Español',de:'Deutsch',zh:'中文',ja:'日本語'};
async function choose(code){
 const locale=await page.locator('html').getAttribute('lang');
 const catalog=locale==='en'?en:JSON.parse(await readFile(resolve('frontend/src/i18n/locales/'+locale+'.json'),'utf8'));
 await page.getByRole('button',{name:catalog['language.choose']||en['language.choose'],exact:true}).filter({visible:true}).first().click();
 await page.locator('[role="group"] button').filter({has:page.locator('bdi[lang="'+code+'"]')}).click();
 await page.waitForFunction(code=>document.documentElement.lang===code,code);
 assert.equal(await page.locator('html').getAttribute('dir'),['ar','ur'].includes(code)?'rtl':'ltr');
}
try{
 await page.goto(base+'/home?seed=sample');await page.getByRole('main').waitFor();await page.locator('.workspace-bar').waitFor();
 await page.evaluate(()=>{window.__localeSentinel='same-document';});
 for(const code of Object.keys(labels)){
  await choose(code);
  assert.equal(await page.evaluate(()=>window.__localeSentinel),'same-document');
  assert.equal(await page.evaluate(()=>localStorage.getItem('adapt.locale')),code);
  assert.ok(!/(?:copy\.|dashboard\.|language\.)[a-z_]+/.test(await page.locator('body').innerText()));
 }
 report.checks.push('All 14 languages switch immediately, update lang/dir and persist without reloading or exposing keys');
 await choose('ar');
 const sidebar=await page.locator('.workspace-sidebar').boundingBox();assert.ok(sidebar.x>1000,'RTL sidebar moves to the inline start on the right');
 await page.screenshot({path:resolve(output,'i18n-desktop-ar.png')});
 await page.reload();await page.locator('.workspace-bar').waitFor();assert.equal(await page.locator('html').getAttribute('lang'),'ar');
 report.checks.push('Preference survives a production reload');
 for(const route of ['/knowledge/governance','/knowledge/me','/journey']){
  await page.goto(base+route+'?seed=sample');await page.locator('.react-flow').waitFor();
  const positions=()=>page.locator('.react-flow__node').evaluateAll(nodes=>nodes.map(node=>({id:node.getAttribute('data-id'),transform:node.style.transform})).sort((a,b)=>a.id.localeCompare(b.id)));
  const before=await positions();await choose('en');await choose('ar');assert.deepEqual(await positions(),before,route+' coordinates');
  assert.equal(await page.locator('.react-flow').evaluate(el=>getComputedStyle(el.closest('[dir]')).direction),'ltr');
 }
 report.checks.push('Governance, private twin and journey retain coordinates and readable RTL controls');
 await page.goto(base+'/profile?seed=sample');await page.getByRole('main').waitFor();await page.setViewportSize({width:393,height:852});
 await choose('ml');await page.screenshot({path:resolve(output,'i18n-mobile-ml.png')});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
 report.checks.push('Mobile Profile selector and Malayalam typography fit the phone viewport');
 await page.evaluate(()=>navigator.serviceWorker.ready);await page.reload();await page.waitForFunction(()=>navigator.serviceWorker.controller);
 const cdp=await context.newCDPSession(page);const install=await cdp.send('Page.getInstallabilityErrors');assert.deepEqual(install.installabilityErrors,[]);
 report.checks.push('Manifest, service worker and Chromium installability remain valid');
 for(const route of ['/api/qa-passport.pdf','/uploads/qa-marriage.pdf','/private/qa-graph.json'])await page.evaluate(route=>fetch(route,{cache:'no-store'}),route);
 const entries=await page.evaluate(async()=>{const requests=[];for(const name of await caches.keys()){for(const req of await (await caches.open(name)).keys())requests.push(new URL(req.url).pathname);}return requests;});
 assert.ok(entries.includes('/index.html'));assert.ok(!entries.some(path=>/^\/(api|uploads|private)(\/|$)/.test(path)||path.endsWith('.pdf')));
 assert.equal(await page.evaluate(()=>sessionStorage.getItem('adapt.mock.v1')),null);
 report.checks.push('Private documents, graphs and mock profiles never reach service-worker or browser storage');
 await context.setOffline(true);await cdp.send('Network.overrideNetworkState',{offline:true,latency:0,downloadThroughput:-1,uploadThroughput:-1});
 await page.reload();await page.locator('main').waitFor();assert.equal(await page.locator('html').getAttribute('lang'),'ml');await choose('ur');
 await page.screenshot({path:resolve(output,'i18n-offline-ur.png')});
 report.checks.push('Offline shell restores the saved language and can switch to RTL using precached catalogs');
 await context.setOffline(false);await cdp.send('Network.overrideNetworkState',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
 await page.goto(base+'/settings');await page.locator('main').waitFor();
 await cdp.send('PWA.install',{manifestId:base+'/',installUrlOrBundleUrl:base+'/settings'});
 await cdp.send('PWA.changeAppUserSettings',{manifestId:base+'/',displayMode:'standalone'});
 const opened=context.waitForEvent('page');
 await cdp.send('PWA.launch',{manifestId:base+'/',url:base+'/settings'});
 const installed=await opened;await installed.locator('main').waitFor();
 assert.equal(await installed.evaluate(()=>matchMedia('(display-mode: standalone)').matches),true);
 assert.equal(await installed.locator('html').getAttribute('lang'),'ur');
 const ur=JSON.parse(await readFile(resolve('frontend/src/i18n/locales/ur.json'),'utf8'));
 await installed.getByRole('button',{name:ur['language.choose'],exact:true}).filter({visible:true}).first().click();
 await installed.locator('[role="group"] button').filter({has:installed.locator('bdi[lang="ja"]')}).click();
 await installed.reload();await installed.locator('main').waitFor();assert.equal(await installed.locator('html').getAttribute('lang'),'ja');
 await installed.screenshot({path:resolve(output,'i18n-installed-ja.png')});
 report.checks.push('Actual installed Chromium standalone PWA restores Urdu and persists a switch to Japanese after reload');
 assert.deepEqual(report.errors,[]);report.result='pass';
}catch(error){report.result='fail';report.failure=error.stack;console.error(error);await page.screenshot({path:resolve(output,'i18n-failure.png')});process.exitCode=1;}
finally{await writeFile(resolve(output,'i18n-audit.json'),JSON.stringify(report,null,2));await context.close();await new Promise(done=>server.close(done));}
console.log(JSON.stringify(report,null,2));
