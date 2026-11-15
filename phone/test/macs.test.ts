// A person's Macs: the Macs page lists only their own, a removal keeps the
// row and its record and drops what the Mac sent, and the daily job removes
// a Mac not heard from in 90 days.
import { describe, it, expect, beforeEach } from 'vitest';
import { db, resetDbForTests } from '../src/lib/db.ts';
import { events } from '../src/lib/events.ts';
import { expireOld } from '../src/lib/expiry.ts';
import { getMac, heard, macsOf, removeMac, resetPresenceForTests, saveSnapshot, setBye, setConnected, snapshotsOf } from '../src/lib/macs.ts';
import { storeSampleRoster } from './helpers.ts';
import snapshot from '../fixtures/snapshot.macbook-pro.json';

const ADA = 'ada.anvil@sttark.com';
const DAY = 24 * 60 * 60;
const now = () => Math.floor(Date.now() / 1000);
const addMac = (id: string, email: string, name: string, lastSeen: number | null, linkedAt = now() - 200 * DAY) =>
  db().prepare("INSERT INTO macs (id, email, name, public_key, key_kind, kit_version, linked_at, last_seen) VALUES (?, ?, ?, 'k', 'keychain', '1.140', ?, ?)").run(id, email, name, linkedAt, lastSeen);

beforeEach(() => {
  resetDbForTests();
  resetPresenceForTests();
  storeSampleRoster();
});

describe('Macs', () => {
  it("lists a person's own linked Macs, by name, with their state", () => {
    addMac('m2', ADA, 'Mac mini', now() - 10);
    addMac('m1', ADA, 'MacBook Pro', now() - 3600);
    addMac('m3', 'bix.dowel@sttark.com', 'iMac', now());
    setBye('m2', 'sleep');
    expect(macsOf(ADA).map((m) => [m.name, m.state])).toEqual([['Mac mini', 'asleep'], ['MacBook Pro', 'not_heard']]);
    heard('m1');
    setConnected('m1', true);
    expect(macsOf(ADA).find((m) => m.id === 'm1')).toMatchObject({ state: 'live', connected: true });
  });

  it('a removal keeps the row with when, why and who, deletes what it sent, records it and tells the sockets', () => {
    addMac('m1', ADA, 'MacBook Pro', now());
    saveSnapshot('m1', { ...structuredClone(snapshot), at: now() });
    db().prepare("INSERT INTO archived (mac_id, hash, received_at, data) VALUES ('m1', 'abcdef12', ?, '[]')").run(now());
    expect(snapshotsOf(ADA)).toHaveLength(1);
    const heardOf: unknown[] = [];
    const listen = (e: unknown) => heardOf.push(e);
    events.on('mac-removed', listen);
    expect(removeMac('m1', { why: 'phone', by: ADA, byName: 'Ada Anvil', words: 'Removed MacBook Pro on the Macs page.' })).toBe(true);
    expect(removeMac('m1', { why: 'phone', by: ADA, byName: 'Ada Anvil', words: 'again' })).toBe(false);
    events.off('mac-removed', listen);
    expect(heardOf).toEqual([{ macId: 'm1', email: ADA, why: 'phone' }]);
    expect(getMac('m1')).toMatchObject({ removedWhy: 'phone', removedBy: ADA });
    expect(macsOf(ADA)).toEqual([]);
    expect(db().prepare('SELECT (SELECT count(*) FROM snapshots) AS s, (SELECT count(*) FROM archived) AS a').get()).toEqual({ s: 0, a: 0 });
    expect(db().prepare('SELECT who, mac_name, action, before, after, words FROM records').all()).toEqual([
      { who: ADA, mac_name: 'MacBook Pro', action: 'remove_mac', before: '{"linked":true}', after: '{"linked":false,"why":"phone"}', words: 'Removed MacBook Pro on the Macs page.' },
    ]);
  });

  it('the daily job removes a Mac not heard from in 90 days, with a record', () => {
    addMac('quiet', ADA, 'Old iMac', now() - 91 * DAY);
    addMac('never', ADA, 'Never came', null, now() - 95 * DAY);
    addMac('recent', ADA, 'MacBook Pro', now() - 89 * DAY);
    addMac('new', ADA, 'Mac mini', null, now() - DAY);
    expect(expireOld().quietMacs).toBe(2);
    expect(macsOf(ADA).map((m) => m.id).sort()).toEqual(['new', 'recent']);
    expect(db().prepare("SELECT who, mac_id, words FROM records WHERE action = 'remove_mac' ORDER BY mac_id").all()).toEqual([
      { who: 'daily job', mac_id: 'never', words: 'Removed Never came: not heard from in 90 days.' },
      { who: 'daily job', mac_id: 'quiet', words: 'Removed Old iMac: not heard from in 90 days.' },
    ]);
    expect(expireOld().quietMacs).toBe(0);
  });
});
