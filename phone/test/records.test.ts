// Records are append only: the database refuses to change, replace or
// delete one, except the daily job's delete of rows over a year old.
import { describe, it, expect, beforeEach } from 'vitest';
import { db, resetDbForTests } from '../src/lib/db.ts';
import { addRecord } from '../src/lib/records.ts';
import { expireOld } from '../src/lib/expiry.ts';

const now = () => Math.floor(Date.now() / 1000);
const DAY = 24 * 60 * 60;
const ids = () => (db().prepare('SELECT id FROM records ORDER BY id').all() as { id: number }[]).map((r) => r.id);
const record = (at: number, words = 'Set effort to High from the phone.') =>
  addRecord({ at, who: 'ada.anvil@sttark.com', whoName: 'Ada Anvil', macId: 'm1', macName: 'Mac mini', session: 'cse_1', sessionName: 'Press color', action: 'set_level', before: { level: 'medium' }, after: { level: 'high' }, result: 'ok', words });

beforeEach(() => resetDbForTests());

describe('records', () => {
  it('keeps who, when, the names then, before and after', () => {
    const id = record(now());
    expect(db().prepare('SELECT who, who_name, mac_name, session_name, action, before, after, result, words FROM records WHERE id = ?').get(id)).toEqual({
      who: 'ada.anvil@sttark.com', who_name: 'Ada Anvil', mac_name: 'Mac mini', session_name: 'Press color', action: 'set_level',
      before: '{"level":"medium"}', after: '{"level":"high"}', result: 'ok', words: 'Set effort to High from the phone.',
    });
  });

  it('refuses any change to a record, old or new', () => {
    const fresh = record(now());
    const old = record(now() - 400 * DAY);
    expect(() => db().prepare("UPDATE records SET words = 'changed' WHERE id = ?").run(fresh)).toThrow(/append only/);
    expect(() => db().prepare("UPDATE records SET who = 'someone' WHERE id = ?").run(old)).toThrow(/append only/);
    expect(() => db().prepare("INSERT INTO records (id, at, who, who_name, action) VALUES (?, ?, 'x', 'x', 'x') ON CONFLICT(id) DO UPDATE SET words = 'changed'").run(fresh, now())).toThrow(/append only/);
    expect(db().prepare('SELECT words FROM records WHERE id = ?').get(fresh)).toEqual({ words: 'Set effort to High from the phone.' });
  });

  it('refuses to delete or replace a record under a year old', () => {
    const fresh = record(now());
    const elevenMonths = record(now() - 335 * DAY);
    expect(() => db().prepare('DELETE FROM records WHERE id = ?').run(fresh)).toThrow(/append only/);
    expect(() => db().prepare('DELETE FROM records WHERE id = ?').run(elevenMonths)).toThrow(/append only/);
    expect(() => db().prepare('DELETE FROM records').run()).toThrow(/append only/);
    expect(() => db().prepare("INSERT OR REPLACE INTO records (id, at, who, who_name, action) VALUES (?, ?, 'x', 'x', 'x')").run(fresh, now())).toThrow(/append only/);
    expect(() => db().prepare("REPLACE INTO records (id, at, who, who_name, action) VALUES (?, ?, 'x', 'x', 'x')").run(fresh, now())).toThrow(/append only/);
    expect(ids()).toEqual([fresh, elevenMonths]);
  });

  it('refuses a time in milliseconds, which would never expire', () => {
    expect(() => record(Date.now())).toThrow(/CHECK/);
  });

  it('the daily job deletes records over a year old, and nothing else of theirs', () => {
    const fresh = record(now());
    const elevenMonths = record(now() - 335 * DAY);
    record(now() - 366 * DAY);
    record(now() - 800 * DAY);
    expect(expireOld().records).toBe(2);
    expect(ids()).toEqual([fresh, elevenMonths]);
    expect(expireOld().records).toBe(0);
  });

  it('the daily job takes out what is kept only for a while', () => {
    const t = now();
    const d = db();
    d.prepare("INSERT INTO web_sessions (id, email, name, created_at, expires_at) VALUES ('gone', 'avery.stone@sttark.com', 'A', ?, ?), ('kept', 'avery.stone@sttark.com', 'A', ?, ?)").run(t - 40 * DAY, t - DAY, t, t + 29 * DAY);
    d.prepare("INSERT INTO oauth_states (state, data, expires_at) VALUES ('gone', '{}', ?), ('kept', '{}', ?)").run(t - 60, t + 300);
    const link = d.prepare("INSERT INTO links (token_hash, poll_hash, code, mac_id, mac_name, public_key, key_kind, created_at, expires_at) VALUES (?, ?, 'ABCD', 'm1', 'Mac mini', 'k', 'keychain', ?, ?)");
    link.run('gone', 'p-gone', t - 2 * DAY, t - 2 * DAY + 600);
    link.run('kept', 'p-kept', t - 3600, t - 3000);
    const push = d.prepare("INSERT INTO pushes_sent (email, cse, waiting_since, sent_at) VALUES ('avery.stone@sttark.com', 'cse_1', ?, ?)");
    push.run(t - 3 * DAY, t - 3 * DAY);
    push.run(t - DAY, t - DAY);
    expect(expireOld(t)).toEqual({ webSessions: 1, oauthStates: 1, links: 1, pushesSent: 1, records: 0, quietMacs: 0 });
    for (const [table, key] of [['web_sessions', 'id'], ['oauth_states', 'state'], ['links', 'token_hash']]) {
      expect(d.prepare(`SELECT ${key} AS k FROM ${table}`).all(), table).toEqual([{ k: 'kept' }]);
    }
    expect(d.prepare('SELECT count(*) AS n FROM pushes_sent').get()).toEqual({ n: 1 });
  });
});
