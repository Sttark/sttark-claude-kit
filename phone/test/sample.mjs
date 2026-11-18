// Made-up data for local runs and the page check: two linked Macs for one
// made-up person, from the contract's fixtures (fixtures/), with every time
// moved so the fixture's moment is now. MacBook Pro is live (its last_seen
// is a day ahead, so it stays live through a long check); Mac mini went to
// sleep when its snapshot was made. Each has its Usage by session list for
// 7 days. MacBook Pro has Alerts off in Reach me by, so it sends idle
// sessions with a kept message, and messages on a Needs you session. Never a
// real person or a live server.
//
//   node test/sample.mjs <database file> [email]
//
// Also imported by test/sample-server.mjs.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const read = (p) => JSON.parse(readFileSync(here(p), 'utf8'));

/** The fixture's moment: MacBook Pro's snapshot time. */
export const FIXTURE_AT = 1794587400;
export const MACS = { pro: 'mac_7Hq2Lx9Kp4', mini: 'mac_2Vd8Rt5Wn1' };
/** A link page waiting for Link (test/sample-server.mjs makes it): a third
 *  Mac, Mac Studio, asked from another address, so the page shows its code. */
export const SAMPLE_LINK = { token: 'sample-link-page-made-up-for-local-runs-001', mac: 'mac_SampleStudio1', name: 'Mac Studio', code: 'KXQM', address: '203.0.113.5' };

const TIME_KEYS = new Set(['at', 'time_at', 'resets', 'until', 'since', 'waiting_since', 'turn_at', 'by', 'failing_since', 'archived_at', 'last_seen', 'last_active']);
const DAY_KEYS = new Set(['from', 'to']);
/** 2026-11-13 moved by delta seconds. */
const moveDay = (day, delta) => new Date(Date.parse(`${day}T12:00:00Z`) + delta * 1000).toISOString().slice(0, 10);
/** A copy of a fixture with every time moved by delta seconds. */
export function shift(value, delta) {
  if (Array.isArray(value)) return value.map((v) => shift(v, delta));
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = TIME_KEYS.has(k) && typeof v === 'number' && v > 1.7e9 ? v + delta : DAY_KEYS.has(k) && typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? moveDay(v, delta) : shift(v, delta);
    }
    return out;
  }
  return value;
}

/** The sample as /live sends it, with the fixture's moment at `now`. */
export function sample(now = Math.floor(Date.now() / 1000)) {
  const delta = now - FIXTURE_AT;
  const pro = shift(read('../fixtures/snapshot.macbook-pro.json'), delta);
  const mini = shift(read('../fixtures/snapshot.mac-mini-away.json'), delta);
  const archived = shift(read('../fixtures/archived.json'), delta);
  const usage = { [MACS.pro]: shift(read('../fixtures/usage.macbook-pro.json'), delta), [MACS.mini]: shift(read('../fixtures/usage.mac-mini-away.json'), delta) };
  return {
    delta,
    macs: [
      { id: MACS.pro, name: pro.mac.name, state: 'live', last_seen: now, kit: pro.mac.kit },
      { id: MACS.mini, name: mini.mac.name, state: 'asleep', last_seen: mini.at, kit: mini.mac.kit },
    ],
    snaps: { [MACS.pro]: pro, [MACS.mini]: mini },
    archived: { [MACS.pro]: archived },
    usage,
  };
}

/** Writes the sample into a database: the Macs, their snapshots, the
 *  archived list and one change record. */
export async function seed(file, email = 'avery.stone@sttark.com', now = Math.floor(Date.now() / 1000), { macs = 'two' } = {}) {
  process.env.KIT_DB = file;
  const { db } = await import('../src/lib/db.ts');
  const d = db();
  const s = sample(now);
  const key = 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEsample';
  const put = d.prepare(
    `INSERT OR REPLACE INTO macs (id, email, name, public_key, key_kind, kit_version, linked_at, last_seen, bye, bye_at)
     VALUES (?, ?, ?, ?, 'keychain', ?, ?, ?, ?, ?)`,
  );
  const snap = d.prepare('INSERT OR REPLACE INTO snapshots (mac_id, at, received_at, data) VALUES (?, ?, ?, ?)');
  const list = s.macs.filter((m) => macs === 'two' || m.id === MACS.pro);
  d.transaction(() => {
    for (const [i, m] of list.entries()) {
      const live = m.state === 'live';
      put.run(m.id, email, m.name, key, m.kit, now - (30 - i) * 86400, live ? now + 86400 : m.last_seen, live ? null : 'sleep', live ? null : m.last_seen);
      snap.run(m.id, s.snaps[m.id].at, now, JSON.stringify(s.snaps[m.id]));
    }
    d.prepare('INSERT OR REPLACE INTO archived (mac_id, hash, received_at, data) VALUES (?, ?, ?, ?)').run(MACS.pro, s.archived[MACS.pro].rev, now, JSON.stringify(s.archived[MACS.pro]));
    for (const m of list) {
      const u = s.usage[m.id];
      d.prepare('INSERT OR REPLACE INTO usage_lists (mac_id, period, received_at, data) VALUES (?, ?, ?, ?)').run(m.id, u.period, now, JSON.stringify(u));
    }
    d.prepare(
      `INSERT INTO records (at, who, who_name, mac_id, mac_name, session, session_name, action, before, after, result, words)
       VALUES (?, ?, 'Sample Person', ?, 'MacBook Pro', 'session_01SampleHvacUpdates', 'HVAC updates', 'set_auto', '{"manual":true}', '{"manual":false}', 'ok', 'Turned Auto on from the phone.')`,
    ).run(now - 1500, email, MACS.pro);
  })();
  return s;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const [file, email] = process.argv.slice(2);
  if (!file) {
    console.error('usage: node test/sample.mjs <database file> [email]');
    process.exit(2);
  }
  await seed(file, email || process.env.DEV_FAKE_USER || undefined);
  console.log(`sample data written to ${file}`);
}
