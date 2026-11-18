// The server's checks are the contract's: every fixture passes them, every
// invalid case fails, and a field planted anywhere in a message fails
// (schema/check.mjs checks the schemas the same way, with its own code).
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkLink, checkMessage, EVENTS, type Direction } from '../src/lib/contract.ts';

const fixtures = fileURLToPath(new URL('../fixtures/', import.meta.url));
const read = (...p: string[]) => JSON.parse(readFileSync(join(fixtures, ...p), 'utf8'));
const DIRS: Direction[] = ['server_to_mac', 'mac_to_server', 'phone_to_server', 'server_to_phone'];

/** Every object in a value, as a path to plant a field at. */
function objects(v: any, path: (string | number)[] = [], out: (string | number)[][] = []) {
  if (Array.isArray(v)) v.forEach((x, i) => objects(x, [...path, i], out));
  else if (v && typeof v === 'object') {
    out.push(path);
    for (const [k, x] of Object.entries(v)) objects(x, [...path, k], out);
  }
  return out;
}
function plant(v: any, path: (string | number)[]) {
  const copy = structuredClone(v);
  let node = copy;
  for (const p of path) node = node[p];
  node.planted_extra = 'x';
  return copy;
}

describe('contract', () => {
  it('every message fixture passes, and a field planted in any of its objects fails', () => {
    let planted = 0;
    for (const d of DIRS) {
      for (const m of read('messages', `${d}.json`)) {
        expect(checkMessage(d, m), `${d} ${m.event}`).toMatchObject({ ok: true });
        for (const p of objects(m)) {
          planted++;
          expect(checkMessage(d, plant(m, p)).ok, `${d} ${m.event} at ${p.join('.')}`).toBe(false);
        }
      }
    }
    expect(planted).toBeGreaterThan(150);
  });

  it('every invalid case fails', () => {
    for (const f of readdirSync(join(fixtures, 'invalid'))) {
      const target = f.replace(/\.json$/, '');
      if (!DIRS.includes(target as Direction)) continue;
      for (const c of read('invalid', f)) expect(checkMessage(target as Direction, c.value).ok, `${f}: ${c.why}`).toBe(false);
    }
  });

  it('a snapshot takes alerts_off, idle rows and kept messages; one from a Kit before them still passes', () => {
    const snapshot = (payload: any) => ({ event: 'snapshot', success: true, payload });
    const snap = read('snapshot.macbook-pro.json');
    expect(snap.flags.alerts_off).toBe(true);
    const idle = snap.rows.filter((r: any) => r.group === 'idle');
    expect(idle.length).toBeGreaterThan(0);
    expect(idle.every((r: any) => r.messages.length > 0 && r.sub.startsWith('Message: '))).toBe(true);
    expect(snap.rows.some((r: any) => r.group !== 'idle' && r.messages)).toBe(true);
    expect(checkMessage('mac_to_server', snapshot(snap))).toMatchObject({ ok: true });
    // The server forwards it to the person's pages as it came.
    expect(checkMessage('server_to_phone', { event: 'snapshot', success: true, payload: { mac: 'mac_7Hq2Lx9Kp4', snapshot: snap } })).toMatchObject({ ok: true });
    // A Kit before them sends none of the three.
    const old = structuredClone(snap);
    delete old.flags.alerts_off;
    old.rows = old.rows.filter((r: any) => r.group !== 'idle');
    for (const r of old.rows) delete r.messages;
    expect(checkMessage('mac_to_server', snapshot(old))).toMatchObject({ ok: true });
    // At most 3 messages, text at most 1000, why at most 80, no field it does not know (a link never goes up).
    const row = idle[0];
    const bad = (change: (r: any) => void) => {
      const s = structuredClone(snap);
      change(s.rows.find((r: any) => r.cse === row.cse));
      return checkMessage('mac_to_server', snapshot(s)).ok;
    };
    expect(bad((r) => (r.messages = [r.messages[0], r.messages[0], r.messages[0]]))).toBe(true);
    expect(bad((r) => (r.messages = [r.messages[0], r.messages[0], r.messages[0], r.messages[0]]))).toBe(false);
    expect(bad((r) => (r.messages[0].text = 'x'.repeat(1000)))).toBe(true);
    expect(bad((r) => (r.messages[0].text = 'x'.repeat(1001)))).toBe(false);
    expect(bad((r) => (r.messages[0].why = 'y'.repeat(81)))).toBe(false);
    expect(bad((r) => (r.messages[0].subject = 's'.repeat(161)))).toBe(false);
    expect(bad((r) => (r.messages[0].url = 'https://claude.ai/code/x'))).toBe(false);
    expect(bad((r) => delete r.messages[0].at)).toBe(false);
    expect(bad((r) => (r.group = 'local'))).toBe(false);
    expect(checkMessage('mac_to_server', snapshot({ ...snap, flags: { ...snap.flags, alerts_off: 'yes' } })).ok).toBe(false);
    // Every invalid snapshot case fails here too.
    for (const c of read('invalid', 'snapshot.json')) expect(checkMessage('mac_to_server', snapshot(c.value)).ok, c.why).toBe(false);
  });

  it('refuses an event of the other direction, and what is not a message', () => {
    expect(checkMessage('mac_to_server', { event: 'welcome', success: true, payload: { phones: 0, watching: false } }).ok).toBe(false);
    expect(checkMessage('phone_to_server', [1]).ok).toBe(false);
    expect(checkMessage('phone_to_server', null).ok).toBe(false);
    expect([...EVENTS.mac_to_server].sort()).toEqual(['archived', 'archived_delta', 'auth', 'bye', 'remind', 'result', 'snapshot', 'unlink', 'usage']);
    expect([...EVENTS.phone_to_server].sort()).toEqual(['action', 'hello', 'open_archived', 'open_usage', 'visible']);
  });

  it('the link refusals and answers have their shape', () => {
    expect(checkLink('refusal', { error: 'mac_taken', words: 'Make a new Mac id and ask again.' })).toEqual({ ok: true });
    expect(checkLink('refusal', { error: 'nope', words: 'x' }).ok).toBe(false);
    expect(checkLink('poll', { status: 'waiting', email: null, name: null })).toEqual({ ok: true });
    expect(checkLink('poll', { status: 'linked', email: 'someone@example.com', name: 'x' }).ok).toBe(false);
  });
});
