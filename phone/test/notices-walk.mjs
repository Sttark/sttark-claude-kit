// Walks Web Push for Needs you, headless at 390 by 844, against the real
// server and the fake Mac (test/sample-server.mjs): the web app manifest and
// its icons, the service worker under BASE_PATH, Menu > Notices in each state
// (off, on, light and dark, an iPhone in the browser, blocked, a browser with
// no Web Push, a push service that does not answer), and one reminder end to
// end: the fake Mac sends remind, the server encrypts and signs a push to a
// stand-in push service (tools/push-sink.mjs), which decrypts it; then that
// payload goes to the page's real service worker through the DevTools
// protocol, as a phone's push service would deliver it, and the worker's
// notice is read back. A second reminder while a page shows sends nothing.
// Saves a screenshot of each state; fails on a problem. Test only; never a
// live server.
//
//   npm run build && node test/notices-walk.mjs --out <folder> [--chrome <path>]
//
// Headless Chromium has no push service, so the page's PushManager hands out
// the stand-in's subscription. The headless shell cannot show a notice, so
// this uses Playwright's full Chromium (npx playwright install chromium), or
// the browser at --chrome.
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { start } from './sample-server.mjs';
import { startSink } from '../tools/push-sink.mjs';

const arg = (k, d) => {
  const i = process.argv.indexOf(k);
  return i >= 0 ? process.argv[i + 1] : d;
};
const OUT = arg('--out', join(tmpdir(), 'kit-notices-walk'));
mkdirSync(OUT, { recursive: true });
const ANDROID = 'Mozilla/5.0 (Linux; Android 16; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36';
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Mobile/15E148 Safari/604.1';

const s = await start({ port: Number(arg('--port', 4353)) });
// The page's origin is APP_ORIGIN (localhost), so the worker opens the
// session's page the server names.
const URL0 = s.url.replace('127.0.0.1', 'localhost');
const origin = new URL(URL0).origin;
const sink = await startSink();
const sub = sink.subscription('pixel');
const browser = await chromium.launch(arg('--chrome') ? { executablePath: arg('--chrome') } : { channel: 'chromium' });
const problems = [];
const say = (...a) => console.log(...a);
const expect = (ok, what) => {
  say(`${ok ? 'ok  ' : 'FAIL'} ${what}`);
  if (!ok) problems.push(what);
};

/** A phone's browser. `push`: the stand-in's subscription behind PushManager;
 *  `none`: no Web Push at all. `permission`: what Notification.permission
 *  says (headless Chromium says denied even when it is granted). */
async function phone({ ua = ANDROID, theme = 'light', push = 'push', permission = 'granted', fail = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, colorScheme: theme, userAgent: ua, isMobile: true, hasTouch: true });
  if (permission === 'granted') await ctx.grantPermissions(['notifications'], { origin });
  await ctx.addInitScript(({ sub, push, permission, fail }) => {
    if (push === 'none') {
      delete window.PushManager;
      return;
    }
    Object.defineProperty(Notification, 'permission', { get: () => permission });
    Notification.requestPermission = async () => permission;
    let current = null;
    const made = { endpoint: sub.endpoint, expirationTime: null, options: { userVisibleOnly: true, applicationServerKey: null }, toJSON: () => sub, unsubscribe: async () => ((current = null), true) };
    PushManager.prototype.subscribe = async () => {
      if (fail) throw new DOMException('Registration failed - push service not available', 'AbortError');
      return (current = made);
    };
    PushManager.prototype.getSubscription = async () => current;
  }, { sub, push, permission, fail });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => problems.push(`${page.url()}: script error: ${e.message}`));
  return { ctx, page };
}
const card = (page) =>
  page.locator('#notices').evaluate((e) => ({ state: e.dataset.state, line: e.querySelector('#notices-line').textContent, checked: e.querySelector('.switch').getAttribute('aria-checked'), disabled: e.querySelector('.switch').getAttribute('aria-disabled') === 'true' }));
let n = 0;
async function shot(page, name) {
  await page.evaluate(() => {
    const h = document.getElementById('notices-h');
    if (h) scrollTo({ top: h.getBoundingClientRect().top + scrollY - 140 });
  });
  await page.waitForTimeout(150);
  await page.screenshot({ path: join(OUT, `${String(++n).padStart(2, '0')}-${name}.png`) });
}
const menu = async (page) => {
  await page.goto(`${URL0}/menu`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
};
const turned = (page, state) => page.waitForFunction((st) => document.querySelector('#notices')?.dataset.state === st, state, { timeout: 5000 }).then(() => true, () => false);

// ---------- the manifest, the icons and the service worker ----------
{
  const { ctx, page } = await phone();
  await menu(page);
  const head = await page.evaluate(() => ({ manifest: document.querySelector('link[rel=manifest]')?.getAttribute('href'), touch: document.querySelector('link[rel=apple-touch-icon]')?.getAttribute('href') }));
  // Fetched as a phone does: with no sign-in cookie.
  const anon = await browser.newContext();
  const m = await (await anon.request.get(`${URL0.replace(/\/$/, '')}${head.manifest.slice(s.base.length)}`)).json().catch(() => ({}));
  expect(m.name === 'Claude Kit' && m.display === 'standalone' && m.start_url === `${s.base}/` && m.scope === `${s.base}/`, `the manifest, with no sign-in: ${m.name}, ${m.display}, start ${m.start_url}, scope ${m.scope}`);
  for (const src of [...(m.icons ?? []).map((i) => i.src), head.touch, `${s.base}/favicon.ico`, `${s.base}/notice-badge.png?v=2`, `${s.base}/sw.js`]) {
    const r = await anon.request.get(`${origin}${src}`);
    expect(r.status() === 200, `${src} loads with no sign-in (${r.status()}, ${r.headers()['content-type']})`);
  }
  await anon.close();
  const sw = await page.evaluate(async () => {
    const r = await navigator.serviceWorker.ready;
    return { scope: r.scope, state: r.active?.state, script: r.active?.scriptURL };
  });
  expect(sw.scope === `${origin}${s.base}/` && sw.state === 'activated', `the service worker: ${sw.script}, scope ${sw.scope}, ${sw.state}`);

  // ---------- off, then on, from a tap ----------
  const off = await card(page);
  expect(off.state === 'off' && off.checked === 'false' && !off.disabled, `Notices, off: "${off.line}"`);
  await shot(page, 'notices-off');
  await page.tap('[data-act="notices"]');
  expect(await turned(page, 'on'), 'a tap turns notices on');
  const on = await card(page);
  expect(/^On for this phone since /.test(on.line) && on.checked === 'true', `Notices, on: "${on.line}"`);
  await shot(page, 'notices-on');

  // ---------- one reminder, end to end ----------
  // The app goes to the background, as a phone's does: no page shows.
  const hide = (hidden) =>
    page.evaluate((h) => {
      Object.defineProperty(document, 'visibilityState', { get: () => (h ? 'hidden' : 'visible'), configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    }, hidden);
  await hide(true);
  await page.waitForTimeout(300);
  const sent = s.remind();
  for (let i = 0; i < 100 && !sink.received.length; i++) await page.waitForTimeout(50);
  const got = sink.received[0];
  expect(!!got && !got.problem, `the fake Mac's remind reached the stand-in push service, signed and decrypted${got?.problem ? `: ${got.problem}` : ''}`);
  expect(got?.payload?.title === `Claude needs you: ${sent?.title}` && got?.payload?.tag === `needs-${sent?.cse}` && got?.payload?.url === `${origin}${s.base}/s/${sent?.cse}`,
    `the push: "${got?.payload?.title}", "${got?.payload?.body}", ${got?.payload?.tag}, ${got?.payload?.url}, badge ${got?.payload?.badge}`);
  const cdp = await ctx.newCDPSession(page);
  const regs = [];
  cdp.on('ServiceWorker.workerRegistrationUpdated', (e) => regs.push(...e.registrations));
  await cdp.send('ServiceWorker.enable');
  for (let i = 0; i < 40 && !regs.some((r) => r.scopeURL === `${origin}${s.base}/`); i++) await page.waitForTimeout(50);
  const reg = regs.find((r) => r.scopeURL === `${origin}${s.base}/`);
  const notices = () =>
    page.evaluate(async () => (await (await navigator.serviceWorker.ready).getNotifications()).map((x) => ({ title: x.title, body: x.body, tag: x.tag, url: x.data?.url, icon: x.icon, badge: x.badge })));
  if (reg && got?.payload) {
    await cdp.send('ServiceWorker.deliverPushMessage', { origin, registrationId: reg.registrationId, data: JSON.stringify(got.payload) });
    await page.waitForTimeout(800);
    const shown = await notices();
    expect(shown.length === 1 && shown[0].title === got.payload.title && shown[0].body === got.payload.body && shown[0].tag === got.payload.tag && shown[0].url === got.payload.url,
      `the service worker showed one notice: ${JSON.stringify(shown[0] ?? null)}`);
    await cdp.send('ServiceWorker.deliverPushMessage', { origin, registrationId: reg.registrationId, data: JSON.stringify({ ...got.payload, body: 'A newer line.' }) });
    await page.waitForTimeout(600);
    const after = await notices();
    expect(after.length === 1 && after[0].body === 'A newer line.', 'a newer push for the same session replaces its notice (the same tag)');
  } else expect(false, 'the service worker shows a pushed notice (no registration seen over the DevTools protocol)');
  // A page that shows the session already gets no push.
  await hide(false);
  await page.waitForTimeout(300);
  const before = sink.received.length;
  await s.remind();
  await page.waitForTimeout(800);
  expect(sink.received.length === before, 'a reminder while a page of the person shows: no push');

  // ---------- off again ----------
  await page.tap('[data-act="notices"]');
  expect(await turned(page, 'off'), 'a second tap turns notices off');
  await ctx.close();
}

// ---------- on, dark ----------
{
  const { ctx, page } = await phone({ theme: 'dark' });
  await menu(page);
  await page.tap('[data-act="notices"]');
  expect(await turned(page, 'on'), 'dark: a tap turns notices on');
  await shot(page, 'notices-on-dark');
  await ctx.close();
}

// ---------- an iPhone in Safari: notices need the Home Screen app ----------
{
  const { ctx, page } = await phone({ ua: IPHONE, push: 'none', permission: 'default' });
  await menu(page);
  const c = await card(page);
  expect(c.state === 'install' && c.disabled && /add Claude Kit to your Home Screen/.test(c.line), `iPhone in Safari: "${c.line.replace(/\s+/g, ' ')}"`);
  await shot(page, 'notices-iphone-add-to-home-screen');
  await ctx.close();
}

// ---------- blocked, no Web Push, a push service that does not answer ----------
{
  const { ctx, page } = await phone({ permission: 'denied' });
  await menu(page);
  const c = await card(page);
  expect(c.state === 'blocked' && c.disabled, `blocked in the phone's settings: "${c.line}"`);
  await shot(page, 'notices-blocked');
  await ctx.close();
}
{
  const { ctx, page } = await phone({ push: 'none', permission: 'default' });
  await menu(page);
  const c = await card(page);
  expect(c.state === 'unsupported' && c.disabled, `a browser with no Web Push: "${c.line}"`);
  await shot(page, 'notices-unsupported');
  await ctx.close();
}
{
  const { ctx, page } = await phone({ fail: true });
  await menu(page);
  await page.tap('[data-act="notices"]');
  const note = await page.waitForSelector('#notices + .note', { timeout: 5000 }).then(() => true, () => false);
  const c = await card(page);
  expect(note && c.state === 'off', `the push service does not answer: still off, and the page says so`);
  await shot(page, 'notices-push-service-failed');
  await ctx.close();
}

await browser.close();
await sink.close();
await s.stop();
say(problems.length ? `\n${problems.length} problem(s):\n  ${problems.join('\n  ')}` : `\nno problems; screenshots in ${OUT}`);
process.exit(problems.length ? 1 : 0);
