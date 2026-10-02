/** Browser/PWA acceptance tests. All provider responses are explicit synthetic fixtures. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir, mkdtemp } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
const { chromium } = await import(process.env.ADAPT_PLAYWRIGHT_MODULE || 'playwright');
const root = resolve('frontend/dist');
const output = resolve('frontend/qa-artifacts/interpreter');
await mkdir(output, { recursive: true }); await mkdir(resolve('var'), { recursive: true });
const profile = await mkdtemp(resolve('var/interpreter-browser-'));
const base = 'http://127.0.0.1:5184';
const types = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.webmanifest': 'application/manifest+json', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.woff': 'font/woff' };
const cap = { provider: 'openai', model: 'gpt-realtime-translate', mode: 'live', fallback_enabled: true, source: 'https://developers.openai.com/cookbook/examples/voice_solutions/realtime_translation_guide', languages: [
  { code: 'en', name: 'English', input: true, output: true, fallback: true, rtl: false },
  { code: 'ar', name: 'Arabic', input: true, output: false, fallback: true, rtl: true },
  { code: 'hi', name: 'Hindi', input: true, output: true, fallback: true, rtl: false },
] };
const tone = Buffer.alloc(44 + 16000); tone.write('RIFF', 0); tone.writeUInt32LE(tone.length - 8, 4); tone.write('WAVEfmt ', 8); tone.writeUInt32LE(16, 16); tone.writeUInt16LE(1, 20); tone.writeUInt16LE(1, 22); tone.writeUInt32LE(16000, 24); tone.writeUInt32LE(32000, 28); tone.writeUInt16LE(2, 32); tone.writeUInt16LE(16, 34); tone.write('data', 36); tone.writeUInt32LE(16000, 40);
for (let i = 0; i < 8000; i++) tone.writeInt16LE(Math.round(Math.sin(i * 2 * Math.PI * 440 / 16000) * 2000), 44 + i * 2);
let pair = { source: 'en', target: 'hi' }; let generation = 0;
const requests = [];
const makeSession = () => ({ session_id: 'audit-session', mode: 'live', expires_at: Date.now() / 1000 + 3600, streams: ['a', 'b'].map((speaker) => {
  const source = speaker === 'a' ? pair.source : pair.target; const target = speaker === 'a' ? pair.target : pair.source;
  return { speaker, source, target, transport: pair.recorded || target === 'ar' ? 'recorded' : 'webrtc', client_secret: `ek-audit-${speaker}-${generation}`, credential_expires_at: Date.now() / 1000 + 120, session_expires_at: Date.now() / 1000 + 3600, webrtc_url: 'https://api.openai.com/v1/realtime/translations/calls' };
}) });
const server = createServer(async (req, res) => {
  const url = new URL(req.url, base);
  res.setHeader('Permissions-Policy', 'microphone=(self), camera=()');
  if (url.pathname.startsWith('/api/')) {
    let body = ''; for await (const chunk of req) body += chunk;
    requests.push({ path: url.pathname, method: req.method });
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    if (url.pathname === '/api/system/info') return res.end(JSON.stringify({ app_name: 'ADAPT', version: 'audit', environment: 'test', demo_mode: false, adapters: [], features: { demo_auth: true } }));
    if (url.pathname === '/api/me') return res.end(JSON.stringify({ id: 'audit-user', is_demo: false, preferences: {}, created_at: new Date().toISOString() }));
    if (url.pathname.endsWith('/capabilities')) return res.end(JSON.stringify(cap));
    if (url.pathname.endsWith('/text')) { const input = JSON.parse(body); return res.end(JSON.stringify({ speaker: 'a', original: input.text, translation: 'مرحبا', audio_mime: 'audio/mpeg' })); }
    if (url.pathname.endsWith('/session')) { pair = JSON.parse(body); generation++; return res.end(JSON.stringify(makeSession())); }
    if (url.pathname.endsWith('/reconnect')) { generation++; return res.end(JSON.stringify(makeSession())); }
    if (url.pathname.endsWith('/recording')) return res.end(JSON.stringify({ speaker: 'a', original: 'I need help finding this address.', translation: 'أحتاج إلى مساعدة في العثور على هذا العنوان.', audio_base64: tone.toString('base64'), audio_mime: 'audio/wav' }));
    return res.end('{}');
  }
  const file = resolve(root, '.' + decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname));
  if (!file.startsWith(root + sep)) { res.writeHead(403); res.end(); return; }
  try { const data = await readFile(file); res.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-cache' }); res.end(data); }
  catch { if (extname(url.pathname)) { res.writeHead(404); res.end(); } else { res.writeHead(200, { 'Content-Type': 'text/html' }); res.end(await readFile(resolve(root, 'index.html'))); } }
});
await new Promise((done) => server.listen(5184, '127.0.0.1', done));
const context = await chromium.launchPersistentContext(profile, { headless: true, viewport: { width: 1440, height: 1050 }, reducedMotion: 'reduce', args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'], ...(process.env.ADAPT_BROWSER_EXECUTABLE ? { executablePath: process.env.ADAPT_BROWSER_EXECUTABLE } : {}) });
await context.grantPermissions(['microphone'], { origin: base });
await context.route('https://api.openai.com/v1/realtime/translations/calls', async (route) => {
  const auth = route.request().headers()['authorization']; assert.match(auth, /^Bearer ek-audit-/);
  const speaker = auth.includes('-a-') ? 'a' : 'b';
  const credential = makeSession().streams.find((s) => s.speaker === speaker);
  await route.fulfill({ status: 200, contentType: 'application/sdp', body: JSON.stringify(credential) });
});
const fixtureBootstrap = () => {
  window.__audit = { micCalls: 0, roots: [], connections: [], events: [], audioPlays: 0 };
  const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (...args) => {
    window.__audit.micCalls++;
    if (new URLSearchParams(location.search).has('deny')) throw new DOMException('Audit permission denied', 'NotAllowedError');
    const stream = await getUserMedia(...args); window.__audit.roots.push(stream); return stream;
  };
  const names = ['interpreter_started', 'speaker_detected', 'translation_started', 'translation_received', 'audio_playing', 'translation_completed', 'reconnecting', 'interpreter_error', 'interpreter_stopped'];
  for (const name of names) window.addEventListener(name, (event) => window.__audit.events.push(event.detail));
  document.addEventListener('playing', () => window.__audit.audioPlays++, true);
  window.RTCPeerConnection = class {
    connectionState = 'new'; localDescription = null; ontrack = null; onconnectionstatechange = null;
    channel = { readyState: 'open', onmessage: null, onclose: null, close() {} };
    constructor() { window.__audit.connections.push(this); }
    createDataChannel() { return this.channel; }
    addTrack(track) { this.input = track; }
    async createOffer() { return { type: 'offer', sdp: 'synthetic-audit-offer' }; }
    async setLocalDescription(offer) { this.localDescription = offer; }
    async setRemoteDescription(answer) {
      this.credential = JSON.parse(answer.sdp);
      this.ctx = new AudioContext(); const dest = this.ctx.createMediaStreamDestination();
      this.gain = this.ctx.createGain(); this.gain.gain.value = 0;
      this.osc = this.ctx.createOscillator(); this.osc.connect(this.gain); this.gain.connect(dest); this.osc.start();
      await this.ctx.resume(); this.ontrack?.({ streams: [dest.stream], track: dest.stream.getAudioTracks()[0] });
      this.channel.onmessage?.({ data: JSON.stringify({ type: 'session.created' }) });
      this.connectionState = 'connected'; this.onconnectionstatechange?.();
    }
    interpret() {
      const source = { en: 'I need help finding this address.', hi: 'मुझे यह पता ढूँढने में मदद चाहिए।', ar: 'أحتاج إلى مساعدة في العثور على هذا العنوان.' };
      this.channel.onmessage?.({ data: JSON.stringify({ type: 'session.input_transcript.delta', delta: source[this.credential.source] }) });
      this.channel.onmessage?.({ data: JSON.stringify({ type: 'session.output_transcript.delta', delta: source[this.credential.target] }) });
      this.gain.gain.value = .1; setTimeout(() => { if (this.gain) this.gain.gain.value = 0; }, 700);
    }
    close() { this.connectionState = 'closed'; this.osc?.stop(); void this.ctx?.close(); }
  };
};
await context.addInitScript(fixtureBootstrap);
const report = { testedAt: new Date().toISOString(), provider: 'synthetic fixtures; no OpenAI credentials', checks: [], installedPwa: 'pending', result: 'pending' };
const page = await context.newPage(); const errors = []; page.on('pageerror', (e) => errors.push(e.message)); page.setDefaultTimeout(10000);
const check = (name) => report.checks.push({ name, result: 'pass' });
async function languageDemo(p, target) {
  await p.goto(`${base}/interpreter?source=en&target=${target}&demo=1`);
  await p.getByRole('button', { name: 'Start demo interpreter' }).click();
  await p.getByRole('button', { name: 'Play sample for selected speaker' }).click();
  await p.locator('.interp-translation p').first().filter({ hasText: target === 'ar' ? 'العنوان' : 'पता' }).waitFor();
  await p.getByRole('button', { name: 'Other person speaks' }).click();
  await p.getByRole('button', { name: 'Play sample for selected speaker' }).click();
  await p.locator('.interp-translation p').last().filter({ hasText: 'Of course.' }).waitFor();
  assert.equal(await p.evaluate(() => window.__audit.micCalls), 0);
  await p.getByRole('button', { name: 'Pause', exact: true }).click(); await p.locator('.interp-state-paused').waitFor();
  await p.getByRole('button', { name: 'Resume', exact: true }).click();
  await p.getByRole('button', { name: 'Mute', exact: true }).click(); assert.match(await p.locator('.interp-status').innerText(), /Muted/);
  await p.getByRole('button', { name: 'Unmute', exact: true }).click();
  await p.getByRole('button', { name: 'Subtitles on' }).click(); assert.equal(await p.locator('.interp-hidden').count(), 2);
  await p.getByRole('button', { name: 'Subtitles off' }).click();
  await p.getByRole('button', { name: 'Swap languages' }).click(); await p.waitForFunction((target) => document.querySelector('select[aria-label="Language A"]').value === target, target);
  await p.getByRole('button', { name: 'Stop', exact: true }).click(); await p.locator('.interp-state-stopped').waitFor();
}
try {
  await page.goto(`${base}/home?seed=sample`); await page.locator('a[href="/interpreter"]').first().click();
  await page.locator('.interp-pair').waitFor();
  assert.deepEqual(await page.locator('.interp-pair select').evaluateAll(nodes => nodes.map(node => node.value)), ['en', 'ar']);
  check('Dashboard navigation opens the independent English/Arabic interpreter');
  await languageDemo(page, 'ar'); check('English ↔ Arabic scripted UI, speaker identity, RTL, pause/resume, mute, subtitles, live swap, end');
  await page.screenshot({ path: resolve(output, 'desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 393, height: 852 }); await languageDemo(page, 'hi');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); check('English ↔ Hindi scripted UI and 393px mobile layout without horizontal overflow');
  await page.screenshot({ path: resolve(output, 'mobile.png'), fullPage: true });
  await page.goto(`${base}/interpreter?source=en&target=xx&demo=1`); await page.getByRole('alert').waitFor(); assert.equal(await page.getByRole('button', { name: 'Start demo interpreter' }).isDisabled(), true); check('Unsupported language pair is explained and cannot start');
  await page.goto(`${base}/interpreter?source=en&target=hi&deny=1`); await page.getByRole('button', { name: 'Start interpreter', exact: true }).click(); await page.getByRole('alert').filter({ hasText: 'denied' }).waitFor(); check('Microphone permission denial is visible and recoverable');
  await page.locator('#interp-text').fill('Hello'); await page.getByRole('button', { name: 'Translate text', exact: true }).click();
  await page.locator('.interp-text-fallback .interp-translation').filter({ hasText: 'مرحبا' }).waitFor();
  check('Microphone denial offers a usable authenticated text fallback');
  await page.goto(`${base}/interpreter?source=en&target=hi`); await page.getByRole('button', { name: 'Start interpreter', exact: true }).waitFor();
  assert.equal(await page.evaluate(() => window.__audit.micCalls), 0);
  await page.getByRole('button', { name: 'Start interpreter', exact: true }).click(); await page.locator('.interp-state-listening').waitFor();
  assert.deepEqual(await page.evaluate(() => window.__audit.connections.map((pc) => pc.input.enabled)), [true, false]);
  await page.evaluate(() => window.__audit.connections[0].interpret()); await page.locator('.interp-state-speaking').waitFor();
  assert.deepEqual(await page.evaluate(() => window.__audit.connections.map((pc) => pc.input.enabled)), [false, false]);
  await page.locator('.interp-state-listening').waitFor(); await page.getByRole('button', { name: 'Replay latest translation for you' }).waitFor({ state: 'visible' });
  assert.equal(await page.getByRole('button', { name: 'Replay latest translation for you' }).isEnabled(), true);
  await page.getByRole('button', { name: 'Replay latest translation for you' }).click(); await page.locator('.interp-state-paused').waitFor(); await page.getByRole('button', { name: 'Resume', exact: true }).click();
  await page.getByRole('button', { name: 'Other person speaks' }).click(); assert.deepEqual(await page.evaluate(() => window.__audit.connections.map((pc) => pc.input.enabled)), [false, true]);
  await page.evaluate(() => window.__audit.connections[1].interpret()); await page.locator('.interp-state-speaking').waitFor(); await page.locator('.interp-state-listening').waitFor();
  await page.getByRole('button', { name: 'Stop', exact: true }).click(); assert.equal(await page.evaluate(() => window.__audit.roots.every((s) => s.getTracks().every((t) => t.readyState === 'ended'))), true);
  check('Real Chromium microphone permission/capture, remote audio playback, feedback gate, replay and complete device release with synthetic translation transport');
  await page.goto(`${base}/interpreter?source=en&target=ar`); await page.getByText('Arabic output uses recorded translation.', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Start interpreter', exact: true }).click(); await page.getByRole('button', { name: 'Record selected speaker' }).click(); await page.getByRole('button', { name: 'Translate recording' }).click();
  await page.locator('.interp-translation p').first().filter({ hasText: 'العنوان' }).waitFor(); await page.locator('.interp-state-listening').waitFor(); check('English → Arabic recorded fallback receives separate text and plays real browser audio');
  await page.getByRole('button', { name: 'Other person speaks' }).click();
  await page.evaluate(() => window.__audit.connections[0].interpret());
  await page.locator('.interp-state-speaking').waitFor(); await page.locator('.interp-state-listening').waitFor();
  assert.match(await page.locator('.interp-original p').last().innerText(), /العنوان/);
  assert.match(await page.locator('.interp-translation p').last().innerText(), /address/);
  await page.getByRole('button', { name: 'Swap languages', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.interp-pair select').value === 'ar');
  await page.locator('.interp-state-listening').waitFor();
  const swapped = await page.locator('.interp-pair select').evaluateAll(nodes => nodes.map(node => node.value));
  for (const [width, height] of [[390,844],[393,852],[430,932]]) {
    await page.setViewportSize({ width, height });
    for (const locale of ['en','ar','hi','ur']) {
      await page.locator('.interp-locale').click();
      await page.locator('[role="group"] button').filter({ has: page.locator(`bdi[lang="${locale}"]`) }).click();
      await page.waitForFunction(locale => document.documentElement.lang === locale, locale);
      assert.equal(await page.locator('html').getAttribute('dir'), ['ar','ur'].includes(locale) ? 'rtl' : 'ltr');
      assert.deepEqual(await page.locator('.interp-pair select').evaluateAll(nodes => nodes.map(node => node.value)), swapped);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.evaluate(() => localStorage.getItem('adapt.locale')), locale);
      assert.ok(!/(?:copy\.|interpreter\.|language\.)[a-z_]+/.test(await page.locator('body').innerText()));
    }
  }
  await page.locator('.interp-locale').click(); await page.locator('[role="group"] button').filter({ has: page.locator('bdi[lang="en"]') }).click();
  check('Arabic response plays English audio; Swap and en/ar/hi/ur UI switches preserve the pair across all three phone sizes');
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await page.evaluate(() => navigator.serviceWorker.ready); await page.reload(); await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
  const cdp = await context.newCDPSession(page); const installability = await cdp.send('Page.getInstallabilityErrors'); assert.deepEqual(installability.installabilityErrors, []);
  const manifest = await (await fetch(base + '/manifest.webmanifest')).json(); assert.ok(manifest.shortcuts.some((s) => s.url.startsWith('/interpreter'))); check('PWA installability, deep route and interpreter shortcut');
  try {
    await cdp.send('PWA.install', { manifestId: base + '/', installUrlOrBundleUrl: base + '/interpreter?demo=1' });
    await cdp.send('PWA.changeAppUserSettings', { manifestId: base + '/', displayMode: 'standalone' });
    const opened = context.waitForEvent('page', { timeout: 10000 });
    const launched = await cdp.send('PWA.launch', { manifestId: base + '/', url: base + '/interpreter?source=en&target=hi' });
    const installed = await opened; installed.setDefaultTimeout(10000);
    await installed.addInitScript(fixtureBootstrap);
    await installed.route('https://api.openai.com/v1/realtime/translations/calls', async (route) => {
      const speaker = route.request().headers()['authorization'].includes('-a-') ? 'a' : 'b';
      await route.fulfill({ status: 200, contentType: 'application/sdp', body: JSON.stringify(makeSession().streams.find((s) => s.speaker === speaker)) });
    });
    await installed.reload(); await installed.bringToFront();
    await installed.getByRole('button', { name: 'Start interpreter', exact: true }).waitFor();
    const installedCdp = await context.newCDPSession(installed);
    report.installedTarget = await installedCdp.send('Target.getTargetInfo', { targetId: launched.targetId });
    assert.equal(await installed.evaluate(() => matchMedia('(display-mode: standalone)').matches), true);
    await installed.getByRole('button', { name: 'Start interpreter', exact: true }).click(); await installed.locator('.interp-state-listening').waitFor();
    await installed.evaluate(() => window.__audit.connections[0].interpret()); await installed.locator('.interp-state-speaking').waitFor(); await installed.locator('.interp-state-listening').waitFor();
    await installed.screenshot({ path: resolve(output, 'installed-pwa.png'), fullPage: true }); await installed.getByRole('button', { name: 'Stop', exact: true }).click();
    report.installedPwa = 'pass: installed Chromium standalone app, real microphone and playback, synthetic provider'; check('Installed Chromium PWA interpreter microphone and remote playback');
  } catch (error) {
    report.installedPwa = `not verified: ${error.message}`;
    const last = context.pages().at(-1);
    if (last) { report.installedBody = await last.locator('body').innerText().catch(() => 'closed'); report.installedDiagnostics = await last.evaluate(() => ({ hidden: document.hidden, standalone: matchMedia('(display-mode: standalone)').matches, micCalls: window.__audit?.micCalls, events: window.__audit?.events })).catch(() => ({})); await last.screenshot({ path: resolve(output, 'installed-failure.png'), fullPage: true }).catch(() => undefined); }
  }
  finally { await cdp.send('PWA.uninstall', { manifestId: base + '/' }).catch(() => undefined); }
  const cached = await page.evaluate(async () => { const all = []; for (const key of await caches.keys()) for (const request of await (await caches.open(key)).keys()) all.push(new URL(request.url).pathname); return all; });
  assert.ok(cached.some((p) => p.includes('InterpreterPage'))); assert.ok(!cached.some((p) => p.startsWith('/api/'))); check('Interpreter code precached; credentials and transcripts never cached as API responses');
  assert.deepEqual(errors, []); report.result = 'pass';
} catch (error) { report.result = 'fail'; report.failure = error.stack; report.browserErrors = errors; report.body = await page.locator('body').innerText(); await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }); process.exitCode = 1; }
finally { report.requests = requests; await writeFile(resolve(output, 'report.json'), JSON.stringify(report, null, 2)); await context.close(); await new Promise((done) => server.close(done)); }
console.log(JSON.stringify({ result: report.result, installedPwa: report.installedPwa, checks: report.checks, failure: report.failure, browserErrors: report.browserErrors }, null, 2));
