/** Empty, loading and recovery checks against the isolated mock development server. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const { chromium }=await import(process.env.ADAPT_PLAYWRIGHT_MODULE||'playwright');
const base=process.env.ADAPT_BASE_URL||'http://127.0.0.1:5180';
const output=resolve('frontend/qa-artifacts'); await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.ADAPT_BROWSER_EXECUTABLE?{executablePath:process.env.ADAPT_BROWSER_EXECUTABLE}:{})});
const report={checks:[],result:'pending'};
try {
 for(const viewport of [{width:390,height:844},{width:393,height:852},{width:430,height:932}]) {
  const context=await browser.newContext({viewport,isMobile:true,hasTouch:true,reducedMotion:'reduce'}); const page=await context.newPage();
  await page.goto(base+'/home',{waitUntil:'commit'});
  // A prefetched journey may resolve before the lazy Home chunk; the boot state
  // and the card skeleton are both valid progress indicators during first load.
  await page.getByRole('status').first().waitFor();
  await page.screenshot({path:resolve(output,`home-loading-${viewport.width}.png`)});
  await page.getByRole('link',{name:'Plan my move',exact:true}).first().waitFor();
  for(const route of ['/home','/journey','/knowledge/me','/documents','/simulate','/profile']) {
   await page.goto(base+route); await page.getByRole('main').waitFor();
   await page.waitForFunction(()=>!document.querySelector('[role="status"][aria-label^="Loading"]'));
   assert.ok(await page.locator('main a,main button').count()>0,route+': empty state should offer a next step');
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1); assert.equal(overflow,false);
   await page.screenshot({path:resolve(output,`empty${route.replaceAll('/','-')}-${viewport.width}.png`)});
  }
  await page.goto(base+'/missing-page'); await page.getByRole('heading',{name:'Page not found',exact:true}).waitFor(); await page.getByRole('main').getByRole('link',{name:'Go to Home'}).click(); await page.waitForURL('**/home');
  await page.route('**/src/features/discover/DiscoverPage.tsx*',route=>route.abort());
  await page.getByRole('button',{name:'Open navigation'}).click(); await page.getByRole('dialog').getByRole('link',{name:/Discover/}).click();
  await page.getByRole('heading',{name:"We couldn't open this page",exact:true}).waitFor();
  await page.screenshot({path:resolve(output,`route-error-${viewport.width}.png`)});
  await page.unroute('**/src/features/discover/DiscoverPage.tsx*'); await page.getByRole('button',{name:'Try again'}).click(); await page.getByRole('heading',{name:'Discover',exact:true}).waitFor();
  await page.goto(base+'/onboarding'); await page.getByRole('button',{name:'Answer quick questions',exact:true}).click();
  const heading=page.getByRole('heading',{level:1,name:"What's bringing you to Abu Dhabi?"}); await heading.waitFor();
  await page.waitForFunction(()=>document.activeElement?.tagName==='H1');
  await page.keyboard.press('Tab'); await page.keyboard.press('ArrowDown');
  assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('role')),'radio');
  await page.keyboard.press('Space'); await page.getByRole('heading',{name:'When do you want to arrive?',exact:true}).waitFor();
  await page.waitForFunction(()=>document.activeElement?.tagName==='H1');
  report.checks.push({viewport,emptyScreens:6,loadingState:'pass',notFoundRecovery:'pass',routeErrorRetry:'pass',onboardingKeyboardFocus:'pass'});
  await context.close();
 }
 report.result='pass';
} catch(error){report.result='fail';report.failure=error.stack;console.error(error);process.exitCode=1;}
finally{await writeFile(resolve(output,'state-audit.json'),JSON.stringify(report,null,2));await browser.close();}
console.log(JSON.stringify(report,null,2));
