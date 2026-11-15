// Walks every phone page and state, headless, against the stand-in for
// /live (test/live-stand-in.mjs), and saves a screenshot of each at 390 by
// 844 and at 1280 by 800, light and dark. It fails on a script error, one
// of the app's own files that does not load, a page that never connects
// to /live, or an action whose answer never shows. Test only; never a live
// server, never a visible browser.
//
//   npm run build && node test/walk.mjs --out <folder>
//   BASE_PATH=/kit npm run build && node test/walk.mjs --out <folder> --short
//
// --short walks one pass of the main pages and one action (for the second
// BASE_PATH).
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { start } from './live-stand-in.mjs';

const arg = (k, d) => {
  const i = process.argv.indexOf(k);
  return i >= 0 ? process.argv[i + 1] : d;
};
const OUT = arg('--out', join(tmpdir(), 'kit-walk'));
const SHORT = process.argv.includes('--short');
mkdirSync(OUT, { recursive: true });

const s = await start({ port: Number(arg('--port', 4352)) });
const browser = await chromium.launch();
const problems = [];
const origin = new URL(s.url).origin;

async function context(width, height, theme = 'light') {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2, colorScheme: theme });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => problems.push(`${page.url()}: script error: ${e.message}`));
  page.on('response', (r) => {
    if (r.status() >= 400 && r.url().startsWith(origin) && ['script', 'stylesheet', 'image', 'font'].includes(r.request().resourceType())) problems.push(`${r.url()} answered ${r.status()}`);
  });
  return { ctx, page };
}
const go = async (page, path, { live = true } = {}) => {
  await page.goto(s.url + path, { waitUntil: 'networkidle' });
  // Connected: the page opened /live.
  if (live) {
    for (let i = 0; i < 50 && s.peers() < 1; i++) await page.waitForTimeout(100);
    if (s.peers() < 1) problems.push(`${path}: not connected to /live`);
  }
  await page.waitForTimeout(250);
};
let n = 0;
const shot = async (page, name, { tall = false } = {}) => {
  const file = join(OUT, `${String(++n).padStart(2, '0')}-${name}.png`);
  if (tall) {
    const vp = page.viewportSize();
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.setViewportSize({ width: vp.width, height: Math.max(vp.height, h) });
    await page.screenshot({ path: file });
    await page.setViewportSize(vp);
  } else await page.screenshot({ path: file });
};
/** Taps a control and waits for the answer to show. */
const answer = async (page, sel, name, { sending = true } = {}) => {
  await page.click(sel);
  if (sending) {
    await page.waitForTimeout(120);
    await shot(page, `${name}-sending`);
  }
  await page.waitForSelector('.result', { timeout: 8000 }).catch(() => problems.push(`${name}: no answer showed`));
  await page.waitForTimeout(250);
  await shot(page, name);
};

const P = { lam: '/s/session_01SampleLaminator', usage: '/s/session_01SampleUsageRetry', hvac: '/s/session_01SampleHvacUpdates', kit: '/s/session_01SampleKitDesign', site: '/s/session_01SampleSiteMap', order: '/s/session_01SampleOrderLogin', press: '/s/session_01SamplePressColor', powder: '/s/session_01SamplePowderWatch' };

// ---------- phone, light ----------
{
  const { ctx, page } = await context(390, 844);
  await go(page, '/');
  await shot(page, 'sessions-two-macs');
  await shot(page, 'sessions-two-macs-all', { tall: true });
  if (!SHORT) {
    await page.click('.bar-btn.search');
    await page.fill('#sq', 'lam');
    await page.waitForTimeout(150);
    await shot(page, 'sessions-search');
    await go(page, P.lam);
    await shot(page, 'session-waiting', { tall: true });
    await page.click('[data-act=info][data-key=waits]');
    await shot(page, 'session-waits-info');
  }
  await go(page, P.lam);
  await answer(page, '[data-act=stop][data-wait=w02]', 'stop-one-wait');
  if (!SHORT) {
    await shot(page, 'stop-one-wait-all', { tall: true });
    await go(page, P.usage);
    await answer(page, '[data-act=bring]', 'bring-back-now', { sending: false });
    await go(page, '/');
    await shot(page, 'sessions-after-bring-back');
    await go(page, P.hvac);
    await answer(page, '[data-act=level][data-level=high]', 'effort-high');
    await shot(page, 'effort-high-all', { tall: true });
    await answer(page, '[data-act=auto]', 'auto-on', { sending: false });
    await go(page, P.site);
    await shot(page, 'session-held', { tall: true });
    await page.selectOption('#limit-sel', 'credits');
    await page.waitForSelector('.result', { timeout: 8000 }).catch(() => problems.push('limit: no answer'));
    await page.waitForTimeout(250);
    await shot(page, 'limit-credits-result');
    await go(page, P.order);
    await shot(page, 'session-needs-you', { tall: true });
    await go(page, P.powder);
    await answer(page, '[data-act=stopall]', 'stop-waiting', { sending: false });

    // Every answer's words.
    for (const [reason, sel, path] of [
      ['gone', '[data-act=stop][data-wait=w03]', P.lam],
      ['not_now', '[data-act=level][data-level=max]', P.kit],
      ['offline', '[data-act=level][data-level=low]', P.press],
      ['timeout', '[data-act=level][data-level=low]', P.press],
      ['denied', '[data-act=auto]', P.press],
      ['bad', '[data-act=auto]', P.press],
    ]) {
      await go(page, path);
      s.next(reason);
      await answer(page, sel, `result-${reason}`, { sending: reason === 'timeout' });
    }

    // Archived.
    await go(page, '/archived');
    await shot(page, 'archived', { tall: true });
    await page.fill('#aq', 'lam');
    await page.waitForTimeout(150);
    await shot(page, 'archived-search');
    await page.fill('#aq', 'zzz');
    await page.waitForTimeout(150);
    await shot(page, 'archived-search-none');
    await go(page, '/archived/session_01SampleDoorPi');
    await shot(page, 'archived-item');
    await answer(page, '[data-act=unarchive]', 'unarchive');
    await go(page, '/archived/session_01SampleTileFan');
    s.next('not_here');
    await answer(page, '[data-act=unarchive]', 'unarchive-not-here', { sending: false });

    // Usage.
    await go(page, '/usage');
    await shot(page, 'usage', { tall: true });
    await page.click('[data-act=info][data-key=holds]');
    await shot(page, 'usage-holds-info', { tall: true });

    // A Mac that is away, and its session.
    await go(page, '/mac/mac_2Vd8Rt5Wn1');
    await shot(page, 'mac-away', { tall: true });
    await go(page, '/s/session_01SampleBinLabels?from=mac%3Amac_2Vd8Rt5Wn1');
    await shot(page, 'mac-away-session', { tall: true });

    // Menu, and Remove's confirm.
    await go(page, '/menu');
    await shot(page, 'menu', { tall: true });
    await page.click('[data-act=remove][data-mac=mac_2Vd8Rt5Wn1]');
    await shot(page, 'menu-remove-confirm');

    // The Mac goes to sleep while a session page is open: the page turns
    // to "As of", gray, with no buttons; it comes back live.
    await go(page, P.press);
    s.setMac('pro', 'asleep');
    await page.waitForTimeout(400);
    await shot(page, 'mac-fell-asleep-session', { tall: true });
    await go(page, '/');
    await shot(page, 'sessions-every-mac-away');
    s.setMac('pro', 'live');
    await page.waitForTimeout(400);
    await shot(page, 'sessions-mac-back');

    // The server goes away: after 4 s the page says so.
    s.refuse(true);
    s.dropAll();
    await page.waitForTimeout(5000);
    await shot(page, 'not-connected');
    await go(page, P.press, { live: false });
    await page.click('[data-act=level][data-level=low]').catch(() => {});
    await page.waitForTimeout(300);
    await shot(page, 'not-connected-action');
    s.refuse(false);

    // Remove Mac mini for real: one Mac, no Mac names on the rows.
    await go(page, '/menu');
    await page.click('[data-act=remove][data-mac=mac_2Vd8Rt5Wn1]');
    await page.click('#rm-mac_2Vd8Rt5Wn1 button[type=submit]');
    await page.waitForLoadState('networkidle');
    await shot(page, 'menu-one-mac');
    await go(page, '/');
    await shot(page, 'sessions-one-mac', { tall: true });
  }
  await ctx.close();
}

// ---------- desktop, light ----------
{
  const { ctx, page } = await context(1280, 800);
  for (const [path, name] of [['/', 'w-sessions'], [P.lam, 'w-session'], ['/archived', 'w-archived'], ['/archived/session_01SampleWeeklyPlan', 'w-archived-item'], ['/usage', 'w-usage'], ['/menu', 'w-menu'], ['/mac/mac_2Vd8Rt5Wn1', 'w-mac']]) {
    if (SHORT && !['/', '/menu'].includes(path)) continue;
    await go(page, path);
    await shot(page, name, { tall: true });
  }
  await ctx.close();
}

// ---------- phone, dark ----------
if (!SHORT) {
  const { ctx, page } = await context(390, 844, 'dark');
  for (const [path, name] of [['/', 'd-sessions'], [P.lam, 'd-session'], ['/usage', 'd-usage'], ['/archived', 'd-archived'], ['/menu', 'd-menu']]) {
    await go(page, path);
    await shot(page, name);
  }
  await ctx.close();
}

await browser.close();
if (problems.length) {
  console.error(`walk: ${problems.length} problem(s):\n  ${[...new Set(problems)].join('\n  ')}`);
  process.exit(1);
}
console.log(`walk: ${n} screenshots in ${OUT}, base "${s.base}", no problems`);
process.exit(0);
