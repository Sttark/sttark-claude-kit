// The two sockets (asyncapi.yaml): a Mac signs in with the key saved at
// linking, a phone page sees only its person's Macs, and each action from
// the phone reaches the Mac (or answers offline, timeout or denied at once)
// with one record per outcome. Real sockets on a free port.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { db, resetDbForTests } from '../src/lib/db.ts';
import { resetHubForTests, settings, sweep, WORDS } from '../src/lib/hub.ts';
import { getMac, macState, removeMac, resetPresenceForTests, archivedOf, lastSnapshot, usageOf } from '../src/lib/macs.ts';
import { resetLinkRateForTests } from '../src/lib/link.ts';
import { macConnect, signChallenge, FakeMac } from '../tools/fake-mac.mjs';
import { ROSTER, storeSampleRoster } from './helpers.ts';
import { Conn, allValid, linkedMac, newMac, phone, sleep, startServer, type At } from './kit.ts';
import snapshot from '../fixtures/snapshot.macbook-pro.json';
import archived from '../fixtures/archived.json';
import delta from '../fixtures/archived-delta.json';
import usageFixture from '../fixtures/usage.macbook-pro.json';

const ADA = 'ada.anvil@sttark.com';
const BIX = 'bix.dowel@sttark.com';
const conns: { c: any; dir: 'server_to_mac' | 'server_to_phone' }[] = [];
let at: At;
let close: () => Promise<void>;

/** Opens a socket and remembers it, to check what it got. */
async function mac(k: unknown, opts = {}) {
  const c = await macConnect(at, k, opts);
  conns.push({ c, dir: 'server_to_mac' });
  return c;
}
async function phoneOf(email: string, opts = {}) {
  const c = await phone(at, email, opts);
  conns.push({ c, dir: 'server_to_phone' });
  return c;
}
const snap = (over: Record<string, unknown> = {}) => ({ event: 'snapshot', success: true, payload: { ...structuredClone(snapshot), at: Math.floor(Date.now() / 1000), ...over } });
const records = () => db().prepare('SELECT who, mac_id, session, session_name, action, before, after, result, words FROM records WHERE action <> ? ORDER BY id').all('link_mac') as any[];
const action = (id: string, macId: string, act: string, args: unknown) => ({ event: 'action', success: true, payload: { id, mac: macId, act, args, basis: snapshot.at } });

beforeEach(async () => {
  resetDbForTests();
  resetHubForTests();
  resetPresenceForTests();
  resetLinkRateForTests();
  storeSampleRoster();
  vi.stubEnv('APP_ORIGIN', 'http://localhost:4350');
  vi.stubEnv('DEV_FAKE_USER', '');
  Object.assign(settings, { actionTimeoutMs: 400, authTimeoutMs: 400, wantEveryMs: 0, silenceMs: 60_000 });
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  ({ at, close } = await startServer());
});

afterEach(async () => {
  // Every message the server sent matched the contract.
  for (const { c, dir } of conns.splice(0)) {
    expect(allValid(c, dir)).toEqual([]);
    c.close();
  }
  resetHubForTests();
  await close();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('a Mac signs in', () => {
  it('challenge, auth with the saved key, welcome; DER or raw signatures', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    expect(c.welcome).toEqual({ phones: 0, watching: false });
    const c2 = await mac(linkedMac(ADA, 'Mac mini'), { raw: true });
    expect(c2.welcome.phones).toBe(0);
    expect(getMac(k.mac)!.lastSeen).toBeGreaterThan(0);
  });

  it('a wrong signature closes with 4401', async () => {
    const k = linkedMac(ADA);
    const other = newMac();
    const c = await Conn.open(`${at.ws}/mac`);
    const { payload } = await c.next('challenge');
    // Signed with another key, and then with the right key over another nonce.
    c.send({ event: 'auth', success: true, payload: { mac: k.mac, sig: signChallenge({ ...other, mac: k.mac }, payload.nonce), kit: '1.140' } });
    expect((await c.closedWith()).code).toBe(4401);
    const c2 = await Conn.open(`${at.ws}/mac`);
    await c2.next('challenge');
    c2.send({ event: 'auth', success: true, payload: { mac: k.mac, sig: signChallenge(k, 'a-nonce-the-server-never-sent'), kit: '1.140' } });
    expect((await c2.closedWith()).code).toBe(4401);
  });

  it('an unknown Mac closes with 4401, and no auth in time with 4400', async () => {
    const stranger = newMac();
    await expect(mac(stranger)).rejects.toThrow(/closed 4401/);
    const c = await Conn.open(`${at.ws}/mac`);
    await c.next('challenge');
    expect((await c.closedWith()).code).toBe(4400);
    const c2 = await Conn.open(`${at.ws}/mac`);
    await c2.next('challenge');
    c2.send({ event: 'snapshot', success: true, payload: {} });
    expect((await c2.closedWith()).code).toBe(4400);
  });

  it('a removed Mac closes with 4401: removed while connected, and when it connects again', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    expect(removeMac(k.mac, { why: 'phone', by: ADA, byName: 'Ada Anvil', words: 'Removed MacBook Pro on the Macs page.' })).toBe(true);
    expect((await c.closedWith()).code).toBe(4401);
    await expect(mac(k)).rejects.toThrow(/closed 4401/);
    expect(getMac(k.mac)).toMatchObject({ removedWhy: 'phone', removedBy: ADA });
    expect(db().prepare("SELECT who, action, result FROM records WHERE action = 'remove_mac'").all()).toEqual([{ who: ADA, action: 'remove_mac', result: 'ok' }]);
  });

  it('off the roster: 4403 when it connects, and at the roster sync while connected', async () => {
    const k = linkedMac(ADA);
    const kb = linkedMac(BIX);
    const c = await mac(k);
    const p = await phoneOf(ADA);
    await p.next('macs');
    storeSampleRoster(ROSTER.filter((x) => x.email !== ADA && x.email !== BIX));
    expect((await c.closedWith()).code).toBe(4403);
    expect((await p.closedWith()).code).toBe(4403);
    expect(getMac(k.mac)).toMatchObject({ removedWhy: 'roster', removedBy: 'roster sync' });
    // Bix's Mac was not connected: it is refused 4403 when it tries.
    await expect(mac(kb)).rejects.toThrow(/closed 4403/);
  });

  it('a newer connection of the same Mac takes over (4409)', async () => {
    const k = linkedMac(ADA);
    const c1 = await mac(k);
    const c2 = await mac(k);
    expect((await c1.closedWith()).code).toBe(4409);
    c2.send(snap());
    await sleep(50);
    expect(lastSnapshot(k.mac)).toMatchObject({ v: 1 });
  });
});

describe('what a Mac sends', () => {
  it('refuses a message with a field the contract does not know, and keeps nothing of it', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    const p = await phoneOf(ADA);
    await p.next('macs');
    const bad = snap();
    (bad.payload.rows[0] as any).prompt = 'a prompt never leaves the Mac';
    c.send(bad);
    expect((await c.next('error')).payload).toEqual({ code: 'bad_message', words: WORDS.bad });
    c.send({ event: 'bye', success: true, payload: { why: 'sleep' }, extra: 1 });
    expect((await c.next('error')).payload.code).toBe('bad_message');
    c.send('not json');
    expect((await c.next('error')).payload.code).toBe('bad_message');
    expect(lastSnapshot(k.mac)).toBeNull();
    await sleep(50);
    expect(p.inbox.filter((m: any) => m.event === 'snapshot')).toEqual([]);
  });

  it('keeps the last snapshot (replaced, no history) and sends it to its person only, at once', async () => {
    const k = linkedMac(ADA);
    linkedMac(BIX);
    const c = await mac(k);
    const pa = await phoneOf(ADA);
    const pb = await phoneOf(BIX);
    await pa.next('macs');
    await pb.next('macs');
    c.send(snap());
    const got = await pa.next('snapshot');
    expect(got.payload.mac).toBe(k.mac);
    expect(got.payload.snapshot.rows).toHaveLength(snapshot.rows.length);
    c.send(snap({ rows: [] }));
    expect((await pa.next('snapshot')).payload.snapshot.rows).toEqual([]);
    expect(db().prepare('SELECT count(*) AS n FROM snapshots').get()).toEqual({ n: 1 });
    expect(lastSnapshot(k.mac).rows).toEqual([]);
    await sleep(50);
    expect(pb.inbox.filter((m: any) => m.event === 'snapshot')).toEqual([]);
    // A page that opens later gets the Macs and the last snapshot first.
    const later = await phoneOf(ADA);
    expect((await later.next('macs')).payload.macs).toMatchObject([{ id: k.mac, name: 'MacBook Pro', state: 'live', kit: '1.140' }]);
    expect((await later.next('snapshot')).payload.snapshot.rows).toEqual([]);
  });

  it('bye: asleep at once, live again when it comes back; unlink removes it with a record', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    const p = await phoneOf(ADA);
    expect((await p.next('macs')).payload.macs[0].state).toBe('live');
    c.send({ event: 'bye', success: true, payload: { why: 'sleep' } });
    expect((await p.next('macs')).payload.macs[0].state).toBe('asleep');
    c.close();
    await sleep(50);
    const again = await mac(k);
    expect((await p.next('macs')).payload.macs[0].state).toBe('live');
    again.send({ event: 'unlink', success: true, payload: {} });
    expect((await again.closedWith()).code).toBe(1000);
    expect((await p.next('macs')).payload.macs).toEqual([]);
    expect(getMac(k.mac)).toMatchObject({ removedWhy: 'mac', removedBy: ADA });
  });
});

describe('the phone socket', () => {
  it('needs a sign-in cookie and this site as its Origin', async () => {
    linkedMac(ADA);
    await expect(phone(at, ADA, { cookie: null })).rejects.toMatchObject({ status: 401 });
    await expect(phone(at, ADA, { cookie: 'sttark_kit_session=made-up' })).rejects.toMatchObject({ status: 401 });
    await expect(phone(at, ADA, { origin: 'https://evil.example' })).rejects.toMatchObject({ status: 403 });
    // DEV_FAKE_USER on a local run.
    vi.stubEnv('DEV_FAKE_USER', ADA);
    const p = await phoneOf(ADA, { cookie: null });
    expect((await p.next('macs')).payload.macs).toHaveLength(1);
  });

  it('a visible page tells its person\'s Macs watching, and a hidden one stops it', async () => {
    const c = await mac(linkedMac(ADA));
    const p = await phoneOf(ADA);
    p.send({ event: 'hello', success: true, payload: { visible: true } });
    expect((await c.next('watching')).payload).toEqual({ on: true });
    p.send({ event: 'visible', success: true, payload: { visible: false } });
    expect((await c.next('watching')).payload).toEqual({ on: false });
    p.send({ event: 'visible', success: true, payload: { visible: true } });
    await c.next('watching');
    p.close();
    expect((await c.next('watching')).payload).toEqual({ on: false });
  });
});

describe('actions', () => {
  it('goes to the Mac with who asked, and the answer comes back with one record, before and after', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    c.send(snap());
    const p = await phoneOf(ADA);
    await p.next('snapshot');
    p.send(action('act-1', k.mac, 'set_level', { cse: 'session_01SamplePressColor', level: 'max' }));
    const sent = await c.next('action');
    expect(sent.payload).toMatchObject({ act: 'set_level', args: { cse: 'session_01SamplePressColor', level: 'max' }, by: { email: ADA, name: 'Ada Anvil' } });
    expect(sent.payload.id).not.toBe('act-1');
    c.send({ event: 'result', success: true, payload: { id: sent.payload.id, reason: 'ok', words: 'Effort is Max now. Auto is off for this session.', before: { level: 'high', manual: true }, after: { level: 'max', manual: true } } });
    expect(await p.next('action_result')).toEqual({ event: 'action_result', success: true, payload: { id: 'act-1', reason: 'ok', words: 'Effort is Max now. Auto is off for this session.' } });
    expect((await p.next('record')).payload).toMatchObject({ mac: k.mac, mac_name: 'MacBook Pro', cse: 'session_01SamplePressColor', session_title: 'Press color', act: 'set_level', by_name: 'Ada Anvil', reason: 'ok', words: 'Set effort to Max from the phone.' });
    expect(records()).toEqual([{
      who: ADA, mac_id: k.mac, session: 'session_01SamplePressColor', session_name: 'Press color', action: 'set_level',
      before: '{"level":"high","manual":true}', after: '{"level":"max","manual":true}', result: 'ok', words: 'Set effort to Max from the phone.',
    }]);
  });

  it('turns a session’s alerts off on its Mac, with its record in words', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    c.send(snap());
    const p = await phoneOf(ADA);
    await p.next('snapshot');
    p.send(action('act-8', k.mac, 'set_alerts', { cse: 'session_01SamplePressColor', alerts: false }));
    const sent = await c.next('action');
    expect(sent.payload).toMatchObject({ act: 'set_alerts', args: { cse: 'session_01SamplePressColor', alerts: false }, by: { email: ADA } });
    c.send({ event: 'result', success: true, payload: { id: sent.payload.id, reason: 'ok', words: 'Alerts are off. Nothing about this session goes out. Its messages stay in the Kit app.', before: { alerts: true }, after: { alerts: false } } });
    expect((await p.next('action_result')).payload).toMatchObject({ id: 'act-8', reason: 'ok' });
    expect((await p.next('record')).payload).toMatchObject({ act: 'set_alerts', session_title: 'Press color', words: 'Turned alerts off from the phone.', before: { alerts: true }, after: { alerts: false } });
    expect(records()[0]).toMatchObject({ action: 'set_alerts', before: '{"alerts":true}', after: '{"alerts":false}', result: 'ok' });
    // set_auto's args on set_alerts: the server refuses it, and the Mac never hears of it
    p.send(action('act-9', k.mac, 'set_alerts', { cse: 'session_01SamplePressColor', on: true }));
    expect((await p.next('error')).payload.code).toBe('bad_message');
    await sleep(50);
    expect(c.inbox.filter((m: any) => m.event === 'action')).toEqual([]);
  });

  it("one person acting on another's Mac is denied, and that Mac never hears of it", async () => {
    const kb = linkedMac(BIX);
    const cb = await mac(kb);
    cb.send(snap());
    const pa = await phoneOf(ADA);
    await pa.next('macs');
    pa.send(action('act-2', kb.mac, 'set_auto', { cse: 'session_01SamplePressColor', on: true }));
    expect((await pa.next('action_result')).payload).toEqual({ id: 'act-2', reason: 'denied', words: WORDS.denied });
    pa.send(action('act-3', 'mac_madeUpId', 'set_auto', { cse: 'session_01SamplePressColor', on: true }));
    expect((await pa.next('action_result')).payload.reason).toBe('denied');
    await sleep(50);
    expect(cb.inbox.filter((m: any) => m.event === 'action')).toEqual([]);
    expect(records().map((r) => [r.who, r.result])).toEqual([[ADA, 'denied'], [ADA, 'denied']]);
  });

  it('a Mac that is not live answers offline at once, and nothing is kept for later', async () => {
    const k = linkedMac(ADA);
    const p = await phoneOf(ADA);
    await p.next('macs');
    p.send(action('act-4', k.mac, 'bring_back', { wait: 'w02' }));
    expect((await p.next('action_result')).payload).toEqual({ id: 'act-4', reason: 'offline', words: 'MacBook Pro is not connected. Actions work when this Mac is back.' });
    // Asleep, with its socket still open.
    const c = await mac(k);
    c.send({ event: 'bye', success: true, payload: { why: 'sleep' } });
    await p.next('macs');
    await p.next('macs');
    p.send(action('act-5', k.mac, 'bring_back', { wait: 'w02' }));
    expect((await p.next('action_result')).payload).toEqual({ id: 'act-5', reason: 'offline', words: 'MacBook Pro is asleep. Actions work when this Mac is back.' });
    await sleep(50);
    expect(c.inbox.filter((m: any) => m.event === 'action')).toEqual([]);
    expect(records().map((r) => r.result)).toEqual(['offline', 'offline']);
  });

  it('no answer in time is timeout; a late answer is still recorded', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    c.send(snap());
    const p = await phoneOf(ADA);
    await p.next('snapshot');
    p.send(action('act-6', k.mac, 'stop_waits', { waits: ['w02'] }));
    const sent = await c.next('action');
    expect((await p.next('action_result', 2000)).payload).toEqual({ id: 'act-6', reason: 'timeout', words: WORDS.timeout });
    expect((await p.next('record')).payload).toMatchObject({ reason: 'timeout', words: WORDS.timeout, before: null, after: null });
    c.send({ event: 'result', success: true, payload: { id: sent.payload.id, reason: 'ok', words: 'Stopped waiting. The session stays where it is.', before: { waits: ['w02'] }, after: { waits: [] } } });
    const late = await p.next('record');
    expect(late.payload).toMatchObject({ reason: 'ok', words: 'Stopped waiting from the phone.', after: { waits: [] } });
    expect(records().map((r) => [r.result, r.session])).toEqual([['timeout', late.payload.cse], ['ok', late.payload.cse]]);
    // No second action_result for the same id.
    await sleep(50);
    expect(p.inbox.filter((m: any) => m.event === 'action_result')).toEqual([]);
  });

  it('records are append only: no change, no delete', async () => {
    const k = linkedMac(ADA);
    const p = await phoneOf(ADA);
    await p.next('macs');
    p.send(action('act-7', k.mac, 'unarchive', { cse: 'session_01SampleWeeklyPlan' }));
    await p.next('action_result');
    const { id } = db().prepare("SELECT id FROM records WHERE result = 'offline'").get() as { id: number };
    expect(() => db().prepare("UPDATE records SET result = 'ok' WHERE id = ?").run(id)).toThrow(/append only/);
    expect(() => db().prepare('DELETE FROM records WHERE id = ?').run(id)).toThrow(/append only/);
  });

  it('only the six actions of the contract go through', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    const p = await phoneOf(ADA);
    await p.next('macs');
    for (const bad of [
      action('act-8', k.mac, 'run', { command: 'rm -rf ~' }),
      action('act-9', k.mac, 'set_level', { wait: 'w02' }),
      action('act-10', k.mac, 'set_level', { cse: 'x', level: 'max', prompt: 'hi' }),
    ]) {
      p.send(bad);
      expect((await p.next('error')).payload.code).toBe('bad_message');
    }
    await sleep(50);
    expect(c.inbox.filter((m: any) => m.event === 'action')).toEqual([]);
    expect(records()).toEqual([]);
  });

  it('the fake Mac answers with each reason', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    const fake = new FakeMac({ answer: 'cycle', delay: 0 });
    fake.conn = c;
    c.ws.on('message', () => { for (const m of c.inbox.splice(0)) void fake.onMessage(m); });
    fake.sendSnapshot();
    const p = await phoneOf(ADA);
    await p.next('snapshot');
    const got = [];
    for (let i = 0; i < 5; i++) {
      p.send(action(`act-c${i}`, k.mac, 'set_auto', { cse: 'session_01SamplePressColor', on: true }));
      got.push((await p.next('action_result')).payload.reason);
    }
    expect(got).toEqual(['ok', 'gone', 'not_now', 'not_here', 'bad']);
  });
});

describe('archived lists', () => {
  it('open_archived asks a Mac whose copy is old; a delta with a missing base asks again for the whole list', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    c.send(snap({ archived_rev: archived.rev, archived_count: archived.items.length }));
    const p = await phoneOf(ADA);
    await p.next('snapshot');
    // A delta before the server has any list: it asks for the whole list.
    c.send({ event: 'archived_delta', success: true, payload: delta });
    expect((await c.next('want_archived')).payload).toEqual({ have: null });
    p.send({ event: 'open_archived', success: true, payload: {} });
    expect((await c.next('want_archived')).payload).toEqual({ have: null });
    c.send({ event: 'archived', success: true, payload: archived });
    const list = await p.next('archived');
    expect(list.payload).toMatchObject({ mac: k.mac, rev: archived.rev });
    expect(list.payload.items.map((i: any) => i.cse)).toEqual(archived.items.map((i) => i.cse));
    // A delta from the list the server holds: applied, newest first, replaced.
    c.send({ event: 'archived_delta', success: true, payload: delta });
    const next = await p.next('archived');
    expect(next.payload.rev).toBe(delta.rev);
    expect(next.payload.items[0].cse).toBe('session_01SampleHvacOld');
    expect(next.payload.items.map((i: any) => i.cse)).not.toContain('session_01SampleDoorPi');
    expect(archivedOf(k.mac)!.rev).toBe(delta.rev);
    // A delta from a base it no longer holds: the whole list again.
    c.send({ event: 'archived_delta', success: true, payload: { ...delta, base: 'ffffffffffffffff', rev: '1234567812345678' } });
    expect((await c.next('want_archived')).payload).toEqual({ have: delta.rev });
    expect(archivedOf(k.mac)!.rev).toBe(delta.rev);
    // A page that opens Archived later gets the server's copy at once.
    const p2 = await phoneOf(ADA);
    p2.send({ event: 'open_archived', success: true, payload: {} });
    expect((await p2.next('archived')).payload.rev).toBe(delta.rev);
  });
});

/** A Usage by session list for a period, from the fixture. */
function usageList(period: string, over: Record<string, unknown> = {}) {
  const [from, to] = period.includes('..') ? period.split('..') : ['2026-11-07', '2026-11-13'];
  return { ...structuredClone(usageFixture), period, from, to, at: Math.floor(Date.now() / 1000), ...over };
}

describe('usage by session lists', () => {
  it('open_usage asks each live Mac once per period in the gap; its answer is kept and goes to the pages on that period only', async () => {
    settings.wantEveryMs = 10_000;
    const k = linkedMac(ADA);
    const c = await mac(k);
    c.send(snap());
    const p = await phoneOf(ADA);
    await p.next('snapshot');
    p.send({ event: 'open_usage', success: true, payload: { period: '7d' } });
    expect((await c.next('want_usage')).payload).toEqual({ period: '7d' });
    // The same period again in the gap asks nothing more; another one asks.
    p.send({ event: 'open_usage', success: true, payload: { period: '7d' } });
    const p2 = await phoneOf(ADA);
    await p2.next('snapshot');
    p2.send({ event: 'open_usage', success: true, payload: { period: '30d' } });
    expect((await c.next('want_usage')).payload).toEqual({ period: '30d' });
    await sleep(150);
    expect(c.inbox.filter((m: any) => m.event === 'want_usage')).toEqual([]);
    // The Mac's answer: kept, and sent to the page that shows 7 days only.
    c.send({ event: 'usage', success: true, payload: usageList('7d') });
    const got = await p.next('usage');
    expect(got.payload.mac).toBe(k.mac);
    expect(got.payload.list.period).toBe('7d');
    expect(got.payload.list.rows.length).toBe(usageFixture.rows.length);
    await sleep(150);
    expect(p2.inbox.filter((m: any) => m.event === 'usage')).toEqual([]);
    expect(usageOf(k.mac, '7d')!.rows[0].title).toBe('Site map plan');
    // Another person's page never gets it.
    const bix = await phoneOf(BIX);
    bix.send({ event: 'open_usage', success: true, payload: { period: '7d' } });
    await sleep(150);
    expect(bix.inbox.filter((m: any) => m.event === 'usage')).toEqual([]);
  });

  it('a page that opens later gets the kept list at once: for a Mac that is away, its last one, and nothing is asked', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    c.send(snap());
    c.send({ event: 'usage', success: true, payload: usageList('7d') });
    await sleep(150);
    c.send({ event: 'bye', success: true, payload: { why: 'sleep' } });
    c.close();
    await c.closedWith();
    await sleep(100);
    const p = await phoneOf(ADA);
    p.send({ event: 'open_usage', success: true, payload: { period: '7d' } });
    const got = await p.next('usage');
    expect(got.payload).toMatchObject({ mac: k.mac, list: { period: '7d' } });
    // Nothing for a period it never sent.
    p.send({ event: 'open_usage', success: true, payload: { period: 'today' } });
    await sleep(150);
    expect(p.inbox.filter((m: any) => m.event === 'usage')).toEqual([]);
  });

  it('asks a Mac that connects while a page shows Usage', async () => {
    const k = linkedMac(ADA);
    const p = await phoneOf(ADA);
    p.send({ event: 'open_usage', success: true, payload: { period: '30d' } });
    await sleep(100);
    const c = await mac(k);
    expect((await c.next('want_usage')).payload).toEqual({ period: '30d' });
  });

  it('keeps only the newest range of days; refuses a list with a field the contract does not know', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    c.send({ event: 'usage', success: true, payload: usageList('7d') });
    c.send({ event: 'usage', success: true, payload: usageList('2026-11-01..2026-11-05') });
    c.send({ event: 'usage', success: true, payload: usageList('2026-11-02..2026-11-06') });
    await sleep(150);
    const periods = (db().prepare('SELECT period FROM usage_lists WHERE mac_id = ? ORDER BY period').all(k.mac) as { period: string }[]).map((r) => r.period);
    expect(periods).toEqual(['2026-11-02..2026-11-06', '7d']);
    const bad = usageList('30d');
    (bad.rows[0] as any).folder = 'src';
    c.send({ event: 'usage', success: true, payload: bad });
    expect((await c.next('error')).payload.code).toBe('bad_message');
    expect(usageOf(k.mac, '30d')).toBeNull();
    // Removing the Mac deletes its lists.
    removeMac(k.mac, { why: 'phone', by: ADA, byName: 'Ada Anvil', words: 'Removed.' });
    expect(db().prepare('SELECT COUNT(*) AS n FROM usage_lists WHERE mac_id = ?').get(k.mac)).toEqual({ n: 0 });
  });
});

describe('Mac state', () => {
  it('live, updating, asleep, quit, not heard from', () => {
    const t = 1_800_000_000;
    expect(macState({ lastSeen: t - 30, bye: null, byeAt: null }, t)).toBe('live');
    expect(macState({ lastSeen: t - 61, bye: null, byeAt: null }, t)).toBe('not_heard');
    expect(macState({ lastSeen: null, bye: null, byeAt: null }, t)).toBe('not_heard');
    expect(macState({ lastSeen: t - 30, bye: 'update', byeAt: t - 100 }, t)).toBe('updating');
    expect(macState({ lastSeen: t - 30, bye: 'update', byeAt: t - 121 }, t)).toBe('not_heard');
    expect(macState({ lastSeen: t - 30, bye: 'sleep', byeAt: t - 30 }, t)).toBe('asleep');
    expect(macState({ lastSeen: t - 9000, bye: 'quit', byeAt: t - 9000 }, t)).toBe('quit');
  });

  it('a socket silent too long is dropped, and its Mac is not heard from', async () => {
    const k = linkedMac(ADA);
    const c = await mac(k);
    settings.silenceMs = 50;
    await sleep(80);
    sweep();
    expect((await c.closedWith()).code).toBe(1006);
  });
});

describe('BASE_PATH /kit', () => {
  it('serves the sockets under /kit only', async () => {
    await close();
    vi.stubEnv('BASE_URL', '/kit/');
    ({ at, close } = await startServer());
    expect(at.ws).toMatch(/\/kit$/);
    const k = linkedMac(ADA);
    const c = await mac(k);
    expect(c.welcome.watching).toBe(false);
    const p = await phoneOf(ADA);
    expect((await p.next('macs')).payload.macs).toHaveLength(1);
    await expect(Conn.open(at.ws.replace(/\/kit$/, '') + '/mac')).rejects.toMatchObject({ status: 404 });
    await expect(Conn.open(at.ws.replace(/\/kit$/, '') + '/live', { headers: { origin: 'http://localhost:4350' } })).rejects.toMatchObject({ status: 404 });
  });
});
