/** Stage regression: production demo build, no API/backend/credentials required. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdir, readFile, writeFile, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, extname, sep } from 'node:path';
const { chromium } = await import(process.env.ADAPT_PLAYWRIGHT_MODULE || 'playwright');
const root = resolve('frontend/dist'), output = resolve('frontend/qa-artifacts');
await mkdir(output, { recursive: true });
const types = { '.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.webmanifest':'application/manifest+json', '.svg':'image/svg+xml', '.png':'image/png', '.ico':'image/x-icon', '.woff2':'font/woff2', '.pdf':'application/pdf' };
let apiCalls = 0;
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (/^\/(api|uploads|private)(\/|$)/.test(url.pathname)) { apiCalls++; res.writeHead(503, { 'Cache-Control':'no-store' }); res.end('Integration deliberately unavailable'); return; }
  let file = resolve(root, '.' + decodeURIComponent(url.pathname));
  if (file !== root && !file.startsWith(root + sep)) { res.writeHead(403); res.end(); return; }
  try { if (file === root) file = resolve(root, 'index.html'); const data = await readFile(file); res.writeHead(200, { 'Content-Type':types[extname(file)] || 'application/octet-stream' }); res.end(data); }
  catch { if (extname(url.pathname)) { res.writeHead(404); res.end(); return; } res.writeHead(200, { 'Content-Type':'text/html' }); res.end(await readFile(resolve(root, 'index.html'))); }
});
await new Promise(done => server.listen(5183, '127.0.0.1', done));
const base = 'http://127.0.0.1:5183', checks = [], errors = [];
const browser = await chromium.launch({ headless:true, ...(process.env.ADAPT_BROWSER_EXECUTABLE ? { executablePath:process.env.ADAPT_BROWSER_EXECUTABLE } : {}) });
async function check(name, task) { await task(); checks.push({ name, result:'pass' }); console.log('PASS ' + name); }
async function scene(page, i) { await page.goto(`${base}/demo/founder-arrival?scene=${i}`); await page.getByRole('heading', { level:1 }).waitFor(); }
async function next(page) { await page.getByRole('button', { name:'Continue', exact:true }).click(); }
try {
 const context = await browser.newContext({ viewport:{ width:1440,height:1000 }, serviceWorkers:'block' });
 const page = await context.newPage(); page.on('pageerror', e => errors.push(e.message));
 await check('Full hero sequence with every API unavailable', async () => {
  await scene(page, 0); await page.getByRole('button', { name:'Demo Reset', exact:true }).click();
  await page.getByRole('button', { name:'Use scripted opening' }).click();
  await page.getByText('Indian technology founder', { exact:true }).waitFor(); await next(page);
  await page.getByRole('button', { name:'Upload demo documents' }).click();
  await page.getByRole('button', { name:'Specimens loaded' }).waitFor();
  await page.getByText('Kabir', { exact:true }).waitFor();
  assert.equal(await page.locator('input[type=file]').count(), 0);
  await next(page); await page.getByRole('img', { name:/Synthetic User Digital Twin/ }).waitFor();
  await next(page); await page.getByRole('img', { name:/Governance Graph/ }).waitFor();
  await next(page); await page.getByRole('button', { name:'Start LangGraph journey' }).click();
  await page.getByText('17 actions identified', { exact:true }).waitFor();
  await page.getByText('2 blockers', { exact:true }).waitFor();
  await page.getByText('1 approval required', { exact:true }).waitFor();
  assert.equal(await page.locator('.hero-agents .is-complete').count(), 9, 'Flow must pause before human approval');
  assert.equal(await page.locator('.hero-agents li').nth(10).evaluate(el => el.classList.contains('is-complete')), false, 'Handoff cannot appear complete before approval');
  await next(page);
  for (const label of ['User fact','Governance rule','Evidence','Next action']) await page.getByText(label, { exact:true }).first().waitFor();
  await next(page); await page.getByText('Cover letter: sponsoring your spouse', { exact:true }).waitFor();
  assert.equal(await page.getByRole('link', { name:'Continue on the official MoFA site' }).count(), 0);
  await page.getByRole('button', { name:'Approve handoff' }).click();
  await page.getByRole('link', { name:/Continue on the official MoFA site/ }).waitFor();
  assert.ok((await page.locator('main').innerText()).includes('has not booked or submitted anything'));
  await next(page); await page.getByRole('button', { name:'Start background research' }).click();
  await page.getByRole('button', { name:'Ask ADAPT', exact:true }).click();
  await page.getByText(/Start with the company application/).waitFor();
  await page.getByRole('progressbar', { name:'Research continues while you talk' }).waitFor();
  await page.reload(); await page.getByRole('button', { name:'Start background research' }).waitFor();
  assert.equal(await page.getByRole('button', { name:'Start background research' }).isDisabled(), true);
  await page.getByText('Research complete · 5 topics', { exact:true }).first().waitFor();
  for (const label of ['Indian community','Muslim community and faith','Start-up and professional community','Cultural guidance','Local starter services']) await page.getByRole('heading', { name:label, exact:true }).waitFor();
  await page.getByRole('heading', { name:'Things you may not have considered.' }).waitFor();
  await next(page); await page.getByRole('button', { name:'Move alone first', exact:true }).click();
  assert.ok(await page.locator('.hero-node-removed').count() > 0);
  await page.getByRole('button', { name:'Return to final plan' }).click();
  await page.getByRole('heading', { name:'YOUR ABU DHABI PLAN' }).waitFor();
  for (const label of ['Arrive','Settle','Connect','Build']) await page.getByRole('heading', { name:label, exact:true }).waitFor();
  await page.screenshot({ path:resolve(output, 'demo-final-desktop.png'), fullPage:true });
  const p = await page.evaluate(() => JSON.parse(localStorage.getItem('adapt.stage.v1')));
  assert.equal(p.decision, 'approved'); assert.equal(p.documents, true); assert.equal(p.alone, true);
  assert.deepEqual(Object.keys(p).sort(), ['version','scene','intro','documents','agentStartedAt','researchStartedAt','decision','alone'].sort());
  assert.equal(apiCalls, 0);
 });
 await check('Voice fails gracefully and can reconnect; microphone input is never retained', async () => {
  const voicePage = await context.newPage();
  await voicePage.addInitScript(() => {
    class Recognition {
      start() { window.__recognition = this; }
      abort() {} stop() { this.onend?.(); }
    }
    window.SpeechRecognition = Recognition;
    Object.defineProperty(window, 'speechSynthesis', { value:{ cancel() {}, getVoices() { return []; }, speak(u) { u.onerror?.(); } } });
  });
  await scene(voicePage, 0); await voicePage.getByRole('button', { name:'Demo Reset' }).click();
  await voicePage.getByRole('button', { name:'Speak the opening' }).click();
  await voicePage.evaluate(() => { window.__recognition.onerror({ error:'not-allowed' }); window.__recognition.onend(); });
  await voicePage.getByText(/Microphone access is blocked/).waitFor();
  await voicePage.getByRole('button', { name:'Speak the opening' }).click();
  await voicePage.evaluate(() => window.__recognition.onresult({ resultIndex:0, results:[{ isFinal:true, 0:{ transcript:"I'm an Indian technology founder moving to Abu Dhabi next month with my wife." } }] }));
  await voicePage.getByText('Indian technology founder', { exact:true }).waitFor();
  await voicePage.getByText(/Audio stopped/).waitFor();
  assert.equal((await voicePage.evaluate(() => localStorage.getItem('adapt.stage.v1'))).includes('transcript'), false);
  await voicePage.close();
 });
 await check('Vision/specimen preview failure keeps extraction and the full plan polished', async () => {
  await page.getByRole('button', { name:'Demo Reset' }).click();
  await page.route('**/demo-specimens/**', route => route.abort());
  await scene(page, 1); await page.getByRole('button', { name:'Upload demo documents' }).click();
  await page.getByText(/Document preview unavailable. Continuing/).waitFor();
  await page.getByRole('button', { name:'Specimens loaded' }).waitFor();
  await page.getByText('Kabir', { exact:true }).waitFor();
  await page.screenshot({ path:resolve(output,'demo-document-fallback.png'), fullPage:true });
  await page.unroute('**/demo-specimens/**');
 });
 await check('Demo Reset cancels work and restores exact initial state', async () => {
  await scene(page, 7); await page.getByRole('button', { name:'Start background research' }).click();
  await page.getByRole('button', { name:'Demo Reset' }).click();
  const p = await page.evaluate(() => JSON.parse(localStorage.getItem('adapt.stage.v1')));
  assert.deepEqual(p, { version:1,scene:0,intro:false,documents:false,agentStartedAt:null,researchStartedAt:null,decision:'pending',alone:false });
  await page.reload(); await page.getByRole('heading', { name:'Your next chapter starts here.' }).waitFor();
  assert.equal(await page.locator('.hero-reply').count(), 0);
 });
 await check('Deep links and refresh retain the correct chapter', async () => {
  for (const [route, i] of [['/documents',1],['/knowledge/me',2],['/knowledge/governance',3],['/agents',4],['/journey',5],['/discover',7],['/simulate',8],['/home',9]]) {
    await page.goto(base + route); await page.getByRole('heading', { level:1 }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('scene'), String(i)); await page.reload(); await page.getByRole('heading', { level:1 }).waitFor();
  }
 });
 await check('All chapters fit mobile and desktop; graphs animate and respect reduced motion', async () => {
  for (const viewport of [{width:390,height:844},{width:1440,height:1000}]) {
    await page.setViewportSize(viewport);
    for (let i = 0; i < 10; i++) {
      await scene(page, i);
      const dimensions = await page.evaluate(() => ({ width:innerWidth, scroll:document.documentElement.scrollWidth }));
      assert.ok(dimensions.scroll <= dimensions.width + 1, `Scene ${i}: horizontal overflow`);
    }
    await page.screenshot({ path:resolve(output, `demo-final-${viewport.width}.png`), fullPage:true });
  }
  await scene(page, 2); assert.equal(await page.locator('.hero-flow').first().evaluate(el => getComputedStyle(el).animationName), 'hero-flow');
  await page.emulateMedia({ reducedMotion:'reduce' }); assert.equal(await page.locator('.hero-flow').first().evaluate(el => getComputedStyle(el).animationName), 'none');
 });
 await context.close();
 await check('Installable PWA, offline deep links and only public specimen caching', async () => {
  const profile = await mkdtemp(resolve(tmpdir(), 'adapt-demo-pwa-'));
  const pwa = await chromium.launchPersistentContext(profile, { headless:true, viewport:{width:390,height:844}, ...(process.env.ADAPT_BROWSER_EXECUTABLE ? {executablePath:process.env.ADAPT_BROWSER_EXECUTABLE} : {}) });
  const p = await pwa.newPage(); p.on('pageerror', e => errors.push(e.message));
  try {
    await scene(p, 9); await p.evaluate(() => navigator.serviceWorker.ready); await p.reload(); await p.waitForFunction(() => !!navigator.serviceWorker.controller);
    const manifest = await (await fetch(base + '/manifest.webmanifest')).json();
    assert.equal(manifest.start_url, '/demo/founder-arrival'); assert.equal(manifest.display, 'standalone');
    const cdp = await pwa.newCDPSession(p);
    const install = await cdp.send('Page.getInstallabilityErrors'); assert.deepEqual(install.installabilityErrors, []);
    const cached = await p.evaluate(async () => { const paths=[]; for (const name of await caches.keys()) for (const req of await (await caches.open(name)).keys()) paths.push(new URL(req.url).pathname); return paths; });
    assert.ok(cached.some(path => path.startsWith('/demo-specimens/') && path.endsWith('.pdf')));
    assert.ok(!cached.some(path => /^\/(api|uploads|private)(\/|$)/.test(path)));
    await pwa.setOffline(true); await p.goto(base + '/simulate'); await p.getByRole('heading', { name:'What if you move alone first?' }).waitFor();
    await p.getByRole('button', { name:'Return to final plan' }).click(); await p.getByRole('heading', { name:'YOUR ABU DHABI PLAN' }).waitFor();
  } finally { await pwa.close(); }
 });
 assert.deepEqual(errors, []); assert.equal(apiCalls, 0);
} catch (error) { checks.push({name:'Audit failure', result:'fail', detail:error.stack}); console.error(error); process.exitCode=1; }
finally { await browser.close(); await new Promise(done => server.close(done)); await writeFile(resolve(output,'demo-audit.json'), JSON.stringify({testedAt:new Date().toISOString(),checks,browserErrors:errors,apiCalls},null,2)); }
