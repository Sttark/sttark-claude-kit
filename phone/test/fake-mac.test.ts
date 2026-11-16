// The fake Mac (tools/fake-mac.mjs), as the phone pages use it: it links
// over HTTP, signs in, sends its snapshot, its archived list when asked,
// answers an action from its own state and sends the change, and says bye.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { resetDbForTests } from '../src/lib/db.ts';
import { resetHubForTests, settings } from '../src/lib/hub.ts';
import { approveLink } from '../src/lib/link.ts';
import { resetPresenceForTests } from '../src/lib/macs.ts';
import { FakeMac, macConnect, pollLink, requestLink, revOf, shiftTimes } from '../tools/fake-mac.mjs';
import { storeSampleRoster } from './helpers.ts';
import { allValid, newMac, phone, startServer, type At } from './kit.ts';

const ADA = { email: 'ada.anvil@sttark.com', name: 'Ada Anvil' };
let at: At;
let close: () => Promise<void>;

beforeEach(async () => {
  resetDbForTests();
  resetHubForTests();
  resetPresenceForTests();
  storeSampleRoster();
  vi.stubEnv('APP_ORIGIN', 'http://localhost:4350');
  Object.assign(settings, { actionTimeoutMs: 2000, wantEveryMs: 0 });
  vi.spyOn(console, 'log').mockImplementation(() => {});
  ({ at, close } = await startServer());
});
afterEach(async () => {
  resetHubForTests();
  await close();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the fake Mac', () => {
  it('links, connects, sends, answers and says bye', async () => {
    const k = newMac('MacBook Pro');
    const a = await requestLink(at, k, { hint: ADA.email });
    expect(await pollLink(at, a.poll)).toEqual({ status: 'waiting', email: null, name: null });
    approveLink(a.link.split('/link/')[1], ADA);
    expect(await pollLink(at, a.poll)).toMatchObject({ status: 'linked', email: ADA.email });

    const c = await macConnect(at, k);
    const mac = new FakeMac({ delay: 0 });
    mac.conn = c;
    c.ws.on('message', () => { for (const m of c.inbox.splice(0)) void mac.onMessage(m); });
    mac.sendSnapshot();
    const p = await phone(at, ADA.email);
    const first = await p.next('snapshot');
    expect(first.payload.snapshot.archived_rev).toBe(revOf(mac.archived));
    // Times moved to now.
    expect(Math.abs(first.payload.snapshot.at - Date.now() / 1000)).toBeLessThan(5);

    p.send({ event: 'open_archived', success: true, payload: {} });
    expect((await p.next('archived')).payload.items).toHaveLength(mac.archived.length);

    p.send({ event: 'action', success: true, payload: { id: 'act-1', mac: k.mac, act: 'unarchive', args: { cse: 'session_01SampleWeeklyPlan' }, basis: first.payload.snapshot.at } });
    expect((await p.next('action_result')).payload).toEqual({ id: 'act-1', reason: 'ok', words: 'It is back in your list.' });
    // The change reaches the phone: the session in the list, gone from Archived.
    const after = await p.next('snapshot');
    expect(after.payload.snapshot.rows.map((r: any) => r.cse)).toContain('session_01SampleWeeklyPlan');
    expect((await p.next('archived')).payload.items.map((i: any) => i.cse)).not.toContain('session_01SampleWeeklyPlan');

    p.send({ event: 'action', success: true, payload: { id: 'act-2', mac: k.mac, act: 'set_level', args: { cse: 'session_01SampleWeeklyPlan', level: 'high' }, basis: after.payload.snapshot.at } });
    expect((await p.next('action_result')).payload.reason).toBe('ok');
    expect((await p.next('snapshot')).payload.snapshot.rows.find((r: any) => r.cse === 'session_01SampleWeeklyPlan').session.level).toBe('high');

    c.send({ event: 'bye', success: true, payload: { why: 'quit' } });
    let macs;
    do macs = (await p.next('macs')).payload.macs;
    while (macs[0].state === 'live');
    expect(macs[0].state).toBe('quit');
    expect(allValid(p, 'server_to_phone')).toEqual([]);
    expect(allValid(c, 'server_to_mac')).toEqual([]);
    p.close();
    c.close();
  });

  it('moves only times, never percentages', () => {
    expect(shiftTimes({ at: 1794587400, hold: { at: 80, percent: 100, until: 1794606000 } }, 100)).toEqual({ at: 1794587500, hold: { at: 80, percent: 100, until: 1794606100 } });
  });
});
