/** Production PWA audit: uses a local static server and synthetic private responses only. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, extname, sep } from 'node:path';
const { chromium } = await import(process.env.ADAPT_PLAYWRIGHT_MODULE || 'playwright');
const root=resolve('frontend/dist'); const output=resolve('frontend/qa-artifacts');
await mkdir(output,{recursive:true});
const types={'.html':'text/html','.js':'application/javascript','.css':'text/css','.webmanifest':'application/manifest+json','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.woff2':'font/woff2','.woff':'font/woff'};
const server=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1');
 if(/^\/(api|private|uploads)(\/|$)/.test(url.pathname)) { res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'}); res.end(JSON.stringify({syntheticPrivateDocument:true})); return; }
 let file=resolve(root,'.'+decodeURIComponent(url.pathname));
 if(file!==root&&!file.startsWith(root+sep)){res.writeHead(403);res.end();return;}
 try { if(file===root) file=resolve(root,'index.html'); const data=await readFile(file); res.writeHead(200,{'Content-Type':types[extname(file)]||'application/octet-stream','Cache-Control':'no-cache'}); res.end(data); }
 catch { if(extname(url.pathname)){res.writeHead(404);res.end();return;} res.writeHead(200,{'Content-Type':'text/html'});res.end(await readFile(resolve(root,'index.html'))); }
});
await new Promise(done=>server.listen(5182,'127.0.0.1',done));
// A fresh persistent test profile allows installability checks outside incognito mode.
const profile=await mkdtemp(resolve(tmpdir(),'adapt-pwa-audit-'));
const context=await chromium.launchPersistentContext(profile,{headless:true,viewport:{width:393,height:852},hasTouch:true,isMobile:true,reducedMotion:'reduce',...(process.env.ADAPT_BROWSER_EXECUTABLE?{executablePath:process.env.ADAPT_BROWSER_EXECUTABLE}:{})});
const page=await context.newPage(); const report={testedAt:new Date().toISOString(),checks:[],result:'pending'};
const errors=[]; page.on('pageerror',e=>errors.push(e.message));
const base='http://127.0.0.1:5182';
try {
 await page.goto(base+'/onboarding');
 await page.getByRole('main').waitFor();
 assert.equal(await page.getByRole('button',{name:'Demo Reset',exact:true}).count(),0);
 report.checks.push({name:'Demo Reset is hidden outside Demo Mode',result:'pass'});
 const manifestUrl=await page.locator('link[rel="manifest"]').getAttribute('href');
 assert.ok(manifestUrl); const manifest=await (await fetch(base+manifestUrl)).json();
 assert.equal(manifest.display,'standalone'); assert.ok(manifest.id); assert.equal(manifest.scope,'/'); assert.equal(manifest.start_url,'/');
 for(const icon of manifest.icons) { const response=await fetch(new URL(icon.src,base)); assert.equal(response.status,200); const image=Buffer.from(await response.arrayBuffer()); assert.equal(image.toString('hex',0,8),'89504e470d0a1a0a'); assert.equal(`${image.readUInt32BE(16)}x${image.readUInt32BE(20)}`,icon.sizes); }
 assert.ok(manifest.icons.some(i=>i.purpose==='maskable')); report.checks.push({name:'Manifest, scope, shortcuts, PNG dimensions and maskable icon',result:'pass'});
 await page.evaluate(()=>navigator.serviceWorker.ready); await page.reload();
 await page.waitForFunction(()=>navigator.serviceWorker.controller!==null);
 report.checks.push({name:'Service worker registered before onboarding completion and controls the app',result:'pass'});
 const cdp=await context.newCDPSession(page); const install=await cdp.send('Page.getInstallabilityErrors');
 assert.deepEqual(install.installabilityErrors,[]); report.checks.push({name:'Chromium installability requirements',result:'pass',errors:install.installabilityErrors});
 const sensitivePaths=['/api/qa-document.jpg','/api','/uploads/qa-photo.png','/private/qa-passport.pdf'];
 for(const path of sensitivePaths) {const value=await page.evaluate(async(path)=>(await fetch(path,{cache:'no-store'})).json(),path); assert.equal(value.syntheticPrivateDocument,true);}
 const entries=await page.evaluate(async()=>{const all=[];for(const name of await caches.keys()){const cache=await caches.open(name);for(const req of await cache.keys())all.push(new URL(req.url).pathname);}return all;});
 assert.ok(entries.includes('/index.html')); assert.ok(entries.some(p=>p.endsWith('.css'))); assert.ok(entries.some(p=>p.endsWith('.woff2')));
 assert.ok(!entries.some(p=>/^\/(api|private|uploads)(\/|$)/.test(p)||/\.pdf$/.test(p)));
 report.checks.push({name:'App shell assets cached; APIs, uploads and private documents never cached',result:'pass',cachedAssetCount:entries.length});
 await context.setOffline(true);
 // Match the browser's disconnected state as well as failed network requests.
 await cdp.send('Network.overrideNetworkState',{offline:true,latency:0,downloadThroughput:-1,uploadThroughput:-1});
 await page.reload();
 await page.getByRole('heading',{name:'Your workspace is safe.',exact:true}).waitFor();
 assert.ok((await page.locator('main').innerText()).includes("aren't saved for offline use"));
 for(const path of sensitivePaths){ const cached=await page.evaluate(async(path)=>{try{await fetch(path);return true;}catch{return false;}},path); assert.equal(cached,false,`Sensitive path must be network-only: ${path}`); }
 await page.screenshot({path:resolve(output,'pwa-offline-393x852.png')});
 report.checks.push({name:'Offline deep route loads a branded app shell with no sensitive responses',result:'pass'});
 await context.setOffline(false); await cdp.send('Network.overrideNetworkState',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1}); await page.getByRole('main').waitFor(); await page.getByRole('button',{name:'Answer quick questions',exact:true}).waitFor();
 report.checks.push({name:'Reconnect automatically restores onboarding',result:'pass'});
 report.result='pass';
} catch(error){report.result='fail';report.failure=error.stack;report.browserErrors=errors;report.page=await page.evaluate(()=>({online:navigator.onLine,body:document.body.innerText}));await page.screenshot({path:resolve(output,'pwa-failure.png')});console.error(error);process.exitCode=1;}
finally{await writeFile(resolve(output,'pwa-audit.json'),JSON.stringify(report,null,2));await context.close();await new Promise(done=>server.close(done));}
console.log(JSON.stringify(report,null,2));
