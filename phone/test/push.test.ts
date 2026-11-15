// Web Push for Needs you (lib/push.ts, phone/DESIGN.md section 5): each
// phone's subscription and its own on and off, with a record for each change;
// every rule that skips a push; what one push says, decrypted by a stand-in
// push service (tools/push-sink.mjs) that checks its VAPID signature; a
// subscription the push service says is gone; and, on real sockets, a Mac's
// remind and the phones count each Mac hears.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { db, resetDbForTests } from '../src/lib/db.ts';
import { events } from '../src/lib/events.ts';
import {
  allowedEndpoint, deviceOf, noticesOf, noticesOfSignIn, payloadOf, phonesFor, pushKey, remind, setNotices, settings, startPush, subscribe, vapid, validPair,
  type Remind,
} from '../src/lib/push.ts';
import { expireOld } from '../src/lib/expiry.ts';
import { heard, resetPresenceForTests, saveSnapshot } from '../src/lib/macs.ts';
import { createSession, destroyAllSessions, destroySession, SESSION_COOKIE } from '../src/lib/session.ts';
import { resetHubForTests, settings as hubSettings } from '../src/lib/hub.ts';
import { resetLinkRateForTests } from '../src/lib/link.ts';
import { POST as subscribeRoute } from '../src/pages/api/push/subscribe.ts';
import { POST as noticesRoute } from '../src/pages/api/push/notices.ts';
import { POST as stateRoute } from '../src/pages/api/push/state.ts';
import { manifest } from '../src/pages/site.webmanifest.ts';
import { macConnect } from '../tools/fake-mac.mjs';
import { startSink } from '../tools/push-sink.mjs';
import { fakeCookies, storeSampleRoster } from './helpers.ts';
import { allValid, linkedMac, phone, sleep, startServer, type At } from './kit.ts';
import snapshot from '../fixtures/snapshot.macbook-pro.json';

const ADA = { email: 'ada.anvil@sttark.com', name: 'Ada Anvil' };
const BIX = { email: 'bix.dowel@sttark.com', name: 'Bix Dowel' };
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Mobile/15E148 Safari/604.1';
const ANDROID = 'Mozilla/5.0 (Linux; Android 16; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36';
const now = () => Math.floor(Date.now() / 1000);

let sink: Awaited<ReturnType<typeof startSink>>;
const records = () => db().prepare("SELECT who, action, before, after, result, words FROM records WHERE action = 'notices' ORDER BY id").all() as any[];
const ask = (over: Partial<Remind> = {}): Remind => ({
  macId: 'mac_x', email: ADA.email, cse: 'session_01SampleOrderLogin', waitingSince: now() - 600, title: 'Order page login', why: 'A plan waits for your go-ahead', visible: false, ...over,
});
/** Waits for the stand-in to have taken n pushes. */
async function pushes(n: number, ms = 3000) {
  for (let t = 0; t < ms && sink.received.length < n; t += 20) await sleep(20);
  return sink.received;
}

beforeEach(async () => {
  resetDbForTests();
  resetPresenceForTests();
  storeSampleRoster();
  vi.stubEnv('APP_ORIGIN', 'http://localhost:4350');
  vi.stubEnv('VAULT_VAPID_PUBLIC_KEY', '');
  vi.stubEnv('VAULT_VAPID_PRIVATE_KEY', '');
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  sink = await startSink();
});

afterEach(async () => {
  await sink.close();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the key pair', () => {
  it('production with no keys: notices are not set up, and nothing is sent', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    expect(vapid()).toBeNull();
    expect(pushKey()).toBeNull();
    expect(subscribe(ADA, null, sink.subscription(), ANDROID)).toMatchObject({ ok: false, status: 503 });
    expect((await remind(ask())).skipped).toBe('not_set_up');
  });

  it('takes the pair from the environment, and refuses one that is not a P-256 pair', () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubEnv('VAULT_VAPID_PUBLIC_KEY', 'BPfvCIMFiaaQHvldBi6DOrs4F-MkkcrWy-hs5vU0F7x6NZPZF1rC2y3dQEnGy2JY9LD44l8kL0r5SW8dE3V3XEc');
    vi.stubEnv('VAULT_VAPID_PRIVATE_KEY', 'short');
    expect(vapid()).toBeNull();
    expect(errors).toHaveBeenCalledWith(expect.stringContaining('ALERT'));
    expect(validPair('BPfvCIMFiaaQHvldBi6DOrs4F-MkkcrWy-hs5vU0F7x6NZPZF1rC2y3dQEnGy2JY9LD44l8kL0r5SW8dE3V3XEc', 'x')).toBe(false);
  });

  it('a local run makes its own pair once and keeps it', () => {
    const a = vapid();
    expect(a && validPair(a.publicKey, a.privateKey)).toBe(true);
    expect(vapid()?.publicKey).toBe(a?.publicKey);
    expect(a?.subject).toBe('https://kit.sttark.com');
  });
});

describe('subscriptions', () => {
  it('a phone turns notices on: kept with its sign-in, one record, and its person\'s Macs hear of it', () => {
    const heardOf = vi.fn();
    events.on('push-subs-changed', heardOf);
    const sub = sink.subscription('ada-iphone');
    const out = subscribe(ADA, 'signin-1', sub, IPHONE);
    events.off('push-subs-changed', heardOf);
    expect(out).toMatchObject({ ok: true, on: true });
    expect(phonesFor(ADA.email)).toBe(1);
    expect(noticesOf(ADA.email, sub.endpoint)).toMatchObject({ known: true, on: true });
    expect(noticesOfSignIn('signin-1')).toMatchObject({ on: true });
    expect(heardOf).toHaveBeenCalledWith({ email: ADA.email });
    expect(records()).toEqual([
      { who: ADA.email, action: 'notices', before: '{"notices":false}', after: '{"notices":true,"device":"iPhone"}', result: 'ok', words: 'Turned Needs you notices on for iPhone.' },
    ]);
  });

  it('refuses what is not a browser subscription, and a push service the Kit does not send to', () => {
    const sub = sink.subscription();
    expect(subscribe(ADA, null, { ...sub, extra: 1 })).toMatchObject({ ok: false, status: 400 });
    expect(subscribe(ADA, null, { ...sub, keys: { p256dh: sub.keys.p256dh, auth: 'AAAA' } })).toMatchObject({ ok: false, status: 400 });
    expect(subscribe(ADA, null, { ...sub, keys: { ...sub.keys, more: 'x' } })).toMatchObject({ ok: false, status: 400 });
    expect(subscribe(ADA, null, { ...sub, endpoint: 'https://evil.example/push/1' })).toMatchObject({ ok: false, status: 400 });
    expect(subscribe(ADA, null, 'nope')).toMatchObject({ ok: false, status: 400 });
    expect(phonesFor(ADA.email)).toBe(0);
    expect(records()).toEqual([]);
    for (const ok of ['https://fcm.googleapis.com/fcm/send/abc', 'https://web.push.apple.com/QH8', 'https://updates.push.services.mozilla.com/wpush/v2/x', 'https://wns2-par02p.notify.windows.com/w/?token=x']) {
      expect(allowedEndpoint(ok, { NODE_ENV: 'production' }), ok).toBe(true);
    }
    for (const bad of ['http://fcm.googleapis.com/fcm/send/abc', 'https://fcm.googleapis.com.evil.example/x', 'https://user:pw@web.push.apple.com/x', 'http://127.0.0.1:9/push', 'javascript:alert(1)']) {
      expect(allowedEndpoint(bad, { NODE_ENV: 'production' }), bad).toBe(false);
    }
    expect(allowedEndpoint('http://127.0.0.1:9/push/x', { NODE_ENV: 'development' })).toBe(true);
  });

  it('per phone on and off: a record each, only the person\'s own phone, and the count follows', () => {
    const a = sink.subscription('a');
    const b = sink.subscription('b');
    subscribe(ADA, null, a, IPHONE);
    subscribe(ADA, null, b, ANDROID);
    expect(phonesFor(ADA.email)).toBe(2);
    expect(setNotices(ADA, a.endpoint, false)).toMatchObject({ ok: true, on: false });
    expect(phonesFor(ADA.email)).toBe(1);
    expect(setNotices(ADA, a.endpoint, false)).toMatchObject({ ok: true, on: false });
    expect(setNotices(BIX, b.endpoint, false)).toMatchObject({ ok: false, status: 404 });
    expect(noticesOf(BIX.email, b.endpoint)).toEqual({ known: false, on: false, since: null });
    expect(setNotices(ADA, a.endpoint, 'yes')).toMatchObject({ ok: false, status: 400 });
    expect(setNotices(ADA, a.endpoint, true)).toMatchObject({ ok: true, on: true });
    expect(records().map((r) => r.words)).toEqual([
      'Turned Needs you notices on for iPhone.',
      'Turned Needs you notices on for Android phone.',
      'Turned Needs you notices off for iPhone.',
      'Turned Needs you notices on for iPhone.',
    ]);
  });

  it('a renewed subscription keeps the phone\'s choice; the same phone subscribed by another person goes to them', () => {
    const a = sink.subscription('a');
    subscribe(ADA, null, a, IPHONE);
    setNotices(ADA, a.endpoint, false);
    const renewed = sink.subscription('a2');
    expect(subscribe(ADA, null, { ...renewed, old: a.endpoint }, IPHONE)).toMatchObject({ ok: true, on: false });
    expect(noticesOf(ADA.email, a.endpoint).known).toBe(false);
    expect(noticesOf(ADA.email, renewed.endpoint)).toMatchObject({ known: true, on: false });
    expect(records().at(-1).words).toBe('The browser on iPhone renewed its Needs you notices.');
    // Bix signs in on the same phone and turns notices on: they are Bix's now.
    setNotices(ADA, renewed.endpoint, true);
    subscribe(BIX, null, renewed, IPHONE);
    expect(phonesFor(ADA.email)).toBe(0);
    expect(phonesFor(BIX.email)).toBe(1);
  });

  it('Sign out ends this phone\'s notices; Sign out everywhere ends all of them; the Macs hear each', () => {
    const heardOf = vi.fn();
    events.on('push-subs-changed', heardOf);
    const c = fakeCookies();
    const id = createSession(c, ADA);
    subscribe(ADA, id, sink.subscription('a'), IPHONE);
    subscribe(ADA, null, sink.subscription('b'), ANDROID);
    heardOf.mockClear();
    destroySession(c);
    expect(phonesFor(ADA.email)).toBe(1);
    expect(heardOf).toHaveBeenCalledTimes(1);
    destroyAllSessions(ADA.email);
    expect(phonesFor(ADA.email)).toBe(0);
    expect(heardOf).toHaveBeenCalledTimes(2);
    events.off('push-subs-changed', heardOf);
  });

  it('the device from its browser', () => {
    expect([IPHONE, ANDROID, 'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', ''].map(deviceOf))
      .toEqual(['iPhone', 'Android phone', 'iPad', 'Mac', 'Windows computer', 'browser']);
  });
});

describe('the sender', () => {
  it('no phone with notices on: no push', async () => {
    expect(await remind(ask())).toMatchObject({ skipped: 'no_phone', sent: 0 });
    const a = sink.subscription('a');
    subscribe(ADA, null, a, IPHONE);
    setNotices(ADA, a.endpoint, false);
    expect(await remind(ask())).toMatchObject({ skipped: 'no_phone', sent: 0 });
    expect(sink.received).toEqual([]);
  });

  it('one push to each phone with notices on: the title, one line, its tag, the session page, the badge, signed and encrypted', async () => {
    vi.stubEnv('APP_ORIGIN', 'https://kit.sttark.com');
    vi.stubEnv('NODE_ENV', 'development');
    const k = linkedMac(ADA.email);
    saveSnapshot(k.mac, { ...structuredClone(snapshot), at: now() });
    heard(k.mac);
    subscribe(ADA, null, sink.subscription('iphone'), IPHONE);
    subscribe(ADA, null, sink.subscription('pixel'), ANDROID);
    const out = await remind(ask({ waitingSince: now() - 660 }));
    expect(out).toEqual({ skipped: null, sent: 2, gone: 0, failed: 0 });
    const got = await pushes(2);
    expect(got.map((g) => g.phone).sort()).toEqual(['iphone', 'pixel']);
    for (const g of got) {
      expect(g.problem).toBeNull();
      expect(g.payload).toEqual({
        title: 'Claude needs you: Order page login',
        body: 'Waiting 11 min: a plan waits for your go-ahead.',
        tag: 'needs-session_01SampleOrderLogin',
        url: 'https://kit.sttark.com/s/session_01SampleOrderLogin',
        badge: 1,
      });
      expect(g.vapid).toMatchObject({ aud: sink.url, sub: 'https://kit.sttark.com', key: pushKey() });
      expect(g.vapid.exp).toBeGreaterThan(now());
      expect([g.ttl, g.urgency, g.encoding]).toEqual([String(settings.ttlS), 'high', 'aes128gcm']);
      expect(g.topic).toMatch(/^[A-Za-z0-9_-]{24}$/);
    }
  });

  it('a visible page of theirs: no push, and the same reminder later sends none either', async () => {
    subscribe(ADA, null, sink.subscription('a'), IPHONE);
    const r = ask();
    expect((await remind({ ...r, visible: true })).skipped).toBe('visible');
    expect((await remind(r)).skipped).toBe('sent');
    expect(sink.received).toEqual([]);
  });

  it('a reconnect, or two Macs at once, never send one twice; a new reply sends again', async () => {
    subscribe(ADA, null, sink.subscription('a'), IPHONE);
    const r = ask();
    const both = await Promise.all([remind({ ...r, macId: 'mac_one' }), remind({ ...r, macId: 'mac_two' })]);
    expect(both.map((x) => x.skipped).sort()).toEqual([null, 'sent']);
    expect((await remind(r)).skipped).toBe('sent');
    expect((await pushes(1)).length).toBe(1);
    expect((await remind({ ...r, waitingSince: r.waitingSince + 300 })).sent).toBe(1);
    expect((await pushes(2)).length).toBe(2);
  });

  it('keeps what it sent for 2 days only', async () => {
    subscribe(ADA, null, sink.subscription('a'), IPHONE);
    const t = now();
    await remind(ask(), t);
    expect(db().prepare('SELECT count(*) AS n FROM pushes_sent').get()).toEqual({ n: 1 });
    expect(expireOld(t + 2 * 86400 - 60).pushesSent).toBe(0);
    expect(expireOld(t + 2 * 86400 + 60).pushesSent).toBe(1);
  });

  it('a subscription the push service says is gone is dropped, with a record; the other phone still gets it', async () => {
    const heardOf = vi.fn();
    events.on('push-subs-changed', heardOf);
    subscribe(ADA, null, sink.subscription('old'), IPHONE);
    subscribe(ADA, null, sink.subscription('new'), ANDROID);
    sink.answer('old', 410);
    heardOf.mockClear();
    expect(await remind(ask())).toEqual({ skipped: null, sent: 1, gone: 1, failed: 0 });
    events.off('push-subs-changed', heardOf);
    expect(phonesFor(ADA.email)).toBe(1);
    expect(heardOf).toHaveBeenCalledWith({ email: ADA.email });
    expect(records().at(-1)).toMatchObject({ who: 'push sender', after: '{"notices":false,"why":"gone"}', words: 'Stopped Needs you notices for iPhone: its push service says the subscription is gone (410).' });
  });

  it('a push service that fails now keeps the subscription', async () => {
    subscribe(ADA, null, sink.subscription('a'), IPHONE);
    sink.answer('a', 500);
    expect(await remind(ask())).toEqual({ skipped: null, sent: 0, gone: 0, failed: 1 });
    expect(phonesFor(ADA.email)).toBe(1);
  });

  it('the line without why, and a long wait', () => {
    expect(payloadOf(ask({ why: null, waitingSince: 1_800_000_000 - 3900 }), 1_800_000_000).body).toBe('Waiting 1 hr 5 min for you.');
    expect(payloadOf(ask({ why: 'It asks which head to test first.' }), now()).body).toMatch(/: it asks which head to test first\.$/);
  });
});

describe('the pages\' calls', () => {
  const call = (route: any, body: unknown, { origin = 'http://localhost:4350', type = 'application/json', user = ADA, cookies = fakeCookies() } = {}) =>
    route({ request: new Request('http://localhost:4350/api/push/x', { method: 'POST', headers: { origin, 'content-type': type, 'user-agent': IPHONE }, body: typeof body === 'string' ? body : JSON.stringify(body) }), locals: { user }, cookies });

  it('subscribe, state and notices: JSON from this site only', async () => {
    const sub = sink.subscription('a');
    expect((await call(subscribeRoute, sub, { origin: 'https://evil.example' })).status).toBe(403);
    expect((await call(subscribeRoute, JSON.stringify(sub), { type: 'text/plain' })).status).toBe(400);
    const c = fakeCookies();
    const id = createSession(c, ADA);
    const ok = await call(subscribeRoute, sub, { cookies: c });
    expect(ok.status).toBe(200);
    expect(await ok.json()).toMatchObject({ on: true });
    expect(noticesOfSignIn(id)).toMatchObject({ on: true });
    expect(c.jar.get(SESSION_COOKIE)).toBe(id);
    const st = await call(stateRoute, { endpoint: sub.endpoint });
    expect(await st.json()).toMatchObject({ key: pushKey(), known: true, on: true });
    expect(await (await call(stateRoute, { endpoint: sub.endpoint }, { user: BIX })).json()).toMatchObject({ known: false });
    expect((await call(noticesRoute, { endpoint: sub.endpoint, on: false }, { user: BIX })).status).toBe(404);
    expect(await (await call(noticesRoute, { endpoint: sub.endpoint, on: false })).json()).toMatchObject({ on: false });
  });

  it('the manifest: a standalone app named Claude Kit, its start and scope under BASE_PATH', () => {
    expect(manifest()).toMatchObject({ name: 'Claude Kit', display: 'standalone', start_url: '/', scope: '/', id: '/' });
    vi.stubEnv('BASE_URL', '/kit/');
    const m = manifest();
    expect([m.start_url, m.scope, m.id]).toEqual(['/kit/', '/kit/', '/kit/']);
    expect(m.icons.map((i) => i.src)).toEqual(['/kit/icon-192.png?v=2', '/kit/icon-512.png?v=2', '/kit/icon-maskable-512.png?v=2']);
    expect(m.icons.at(-1)).toMatchObject({ purpose: 'maskable' });
  });
});

describe('on the sockets', () => {
  let at: At;
  let close: () => Promise<void>;
  const conns: { c: any; dir: 'server_to_mac' | 'server_to_phone' }[] = [];

  beforeEach(async () => {
    resetHubForTests();
    resetLinkRateForTests();
    Object.assign(hubSettings, { actionTimeoutMs: 400, authTimeoutMs: 400, wantEveryMs: 0, silenceMs: 60_000 });
    vi.stubEnv('DEV_FAKE_USER', '');
    startPush();
    ({ at, close } = await startServer());
  });
  afterEach(async () => {
    for (const { c, dir } of conns.splice(0)) {
      expect(allValid(c, dir)).toEqual([]);
      c.close();
    }
    resetHubForTests();
    await close();
  });

  it('welcome says how many phones get a push, and phones says each change', async () => {
    const a = sink.subscription('a');
    subscribe(ADA, null, a, IPHONE);
    const c = await macConnect(at, linkedMac(ADA.email));
    conns.push({ c, dir: 'server_to_mac' });
    expect(c.welcome).toEqual({ phones: 1, watching: false });
    setNotices(ADA, a.endpoint, false);
    expect((await c.next('phones')).payload).toEqual({ phones: 0 });
    subscribe(ADA, null, sink.subscription('b'), ANDROID);
    expect((await c.next('phones')).payload).toEqual({ phones: 1 });
    // Another person's phone changes nothing for this Mac.
    subscribe(BIX, null, sink.subscription('c'), ANDROID);
    await sleep(50);
    expect(c.inbox.filter((m: any) => m.event === 'phones')).toEqual([]);
  });

  it('a Mac\'s remind becomes one push; with a page of theirs visible, none', async () => {
    subscribe(ADA, null, sink.subscription('a'), IPHONE);
    const c = await macConnect(at, linkedMac(ADA.email));
    conns.push({ c, dir: 'server_to_mac' });
    const w = now() - 620;
    c.send({ event: 'remind', success: true, payload: { cse: 'session_01SampleOrderLogin', waiting_since: w, title: 'Order page login', why: 'A plan waits for your go-ahead' } });
    const got = await pushes(1);
    expect(got[0].payload).toMatchObject({ title: 'Claude needs you: Order page login', tag: 'needs-session_01SampleOrderLogin' });
    // The same again (a reconnect): nothing new.
    c.send({ event: 'remind', success: true, payload: { cse: 'session_01SampleOrderLogin', waiting_since: w, title: 'Order page login', why: null } });
    const p = await phone(at, ADA.email);
    conns.push({ c: p, dir: 'server_to_phone' });
    p.send({ event: 'hello', success: true, payload: { visible: true } });
    await c.next('watching');
    c.send({ event: 'remind', success: true, payload: { cse: 'session_01SampleNozzle', waiting_since: w, title: 'Nozzle check page', why: null } });
    await sleep(200);
    expect(sink.received).toHaveLength(1);
    expect(db().prepare('SELECT cse FROM pushes_sent ORDER BY cse').all()).toEqual([{ cse: 'session_01SampleNozzle' }, { cse: 'session_01SampleOrderLogin' }]);
  });
});
