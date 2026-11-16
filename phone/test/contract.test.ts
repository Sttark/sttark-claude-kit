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
