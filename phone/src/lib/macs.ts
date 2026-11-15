// A person's linked Macs (macs, lib/db.ts): who each belongs to, its state,
// what it last sent, and how one is removed.
//
// State (phone/DESIGN.md section 6, the contract's server_to_phone.macs):
//   live       heard from in the last 60 seconds;
//   updating   after bye update, for up to 2 minutes;
//   asleep     after bye sleep;   quit  after bye quit;
//   not_heard  60 seconds of silence with no bye (or never connected).
// Anything a Mac sends after a bye, or a new connection, ends the bye.
// When a Mac was last heard from is kept in memory on every frame (pings
// too) and written to the database at most once a minute, and at each bye
// and close.
import { db } from './db.ts';
import { addRecord } from './records.ts';
import { events, type RemovedWhy } from './events.ts';

export type MacState = 'live' | 'updating' | 'asleep' | 'quit' | 'not_heard';
export type Bye = 'sleep' | 'quit' | 'update';
/** Heard from in the last LIVE_S seconds: live. */
export const LIVE_S = 60;
/** Updating for at most UPDATE_S seconds after bye update. */
export const UPDATE_S = 120;
/** A Mac not heard from in this many days is removed by the daily job. */
export const QUIET_DAYS = 90;
/** At most this many linked Macs per person (the contract's macs list). */
export const MAX_MACS = 20;

const nowS = () => Math.floor(Date.now() / 1000);

export type MacRow = {
  id: string;
  email: string;
  name: string;
  publicKey: string;
  keyKind: string;
  kitVersion: string | null;
  linkedAt: number;
  lastSeen: number | null;
  bye: Bye | null;
  byeAt: number | null;
  removedAt: number | null;
  removedWhy: RemovedWhy | null;
  removedBy: string | null;
};

const COLS = `id, email, name, public_key AS publicKey, key_kind AS keyKind, kit_version AS kitVersion, linked_at AS linkedAt,
  last_seen AS lastSeen, bye, bye_at AS byeAt, removed_at AS removedAt, removed_why AS removedWhy, removed_by AS removedBy`;

/** One Mac by id, removed or not. */
export function getMac(id: string): MacRow | undefined {
  return db().prepare(`SELECT ${COLS} FROM macs WHERE id = ?`).get(id) as MacRow | undefined;
}

// ---------- presence: in memory, one process ----------

type Presence = { heard: number; written: number; connected: boolean };
const PRESENCE = Symbol.for('sttark.kit.presence');
const presence: Map<string, Presence> = ((globalThis as Record<symbol, unknown>)[PRESENCE] ??= new Map()) as Map<string, Presence>;

function seen(id: string): Presence {
  let p = presence.get(id);
  if (!p) presence.set(id, (p = { heard: 0, written: 0, connected: false }));
  return p;
}

/** The Mac sent something (a message, a ping or a pong). */
export function heard(id: string, now = nowS(), write = false): void {
  const p = seen(id);
  p.heard = Math.max(p.heard, now);
  if (write || p.heard - p.written >= 60) {
    db().prepare('UPDATE macs SET last_seen = ? WHERE id = ? AND (last_seen IS NULL OR last_seen < ?)').run(p.heard, id, p.heard);
    p.written = p.heard;
  }
}

export function setConnected(id: string, on: boolean): void {
  seen(id).connected = on;
}

/** Has this Mac an authenticated socket open on this server now? */
export function isConnected(id: string): boolean {
  return presence.get(id)?.connected ?? false;
}

/** The Mac said bye: its state changes at once, for the phone. */
export function setBye(id: string, why: Bye, now = nowS()): void {
  heard(id, now, true);
  db().prepare('UPDATE macs SET bye = ?, bye_at = ? WHERE id = ?').run(why, now, id);
}

/** The Mac is back (a new connection, or a message after its bye). */
export function clearBye(id: string): void {
  db().prepare('UPDATE macs SET bye = NULL, bye_at = NULL WHERE id = ? AND bye IS NOT NULL').run(id);
}

/** Tests only. */
export function resetPresenceForTests(): void {
  presence.clear();
}

/** The state from when it was last heard from and its last bye. */
export function macState(m: { lastSeen: number | null; bye: Bye | null; byeAt: number | null }, now = nowS()): MacState {
  if (m.bye && m.byeAt !== null) {
    if (m.bye === 'update') return now - m.byeAt <= UPDATE_S ? 'updating' : 'not_heard';
    return m.bye === 'sleep' ? 'asleep' : 'quit';
  }
  return m.lastSeen !== null && now - m.lastSeen <= LIVE_S ? 'live' : 'not_heard';
}

// ---------- a person's Macs ----------

export type Mac = {
  id: string;
  name: string;
  /** The Kit version it last sent. */
  kit: string | null;
  linkedAt: number;
  /** Unix seconds, or null when it never connected. */
  lastSeen: number | null;
  state: MacState;
  /** An authenticated socket is open now: actions can reach it. */
  connected: boolean;
  bye: Bye | null;
  byeAt: number | null;
};

/** One Mac as the pages and the sockets show it. */
export function macView(r: MacRow, now = nowS()): Mac {
  const p = presence.get(r.id);
  const lastSeen = Math.max(r.lastSeen ?? 0, p?.heard ?? 0) || null;
  return {
    id: r.id, name: r.name, kit: r.kitVersion, linkedAt: r.linkedAt, lastSeen,
    state: macState({ lastSeen, bye: r.bye, byeAt: r.byeAt }, now),
    connected: p?.connected ?? false, bye: r.bye, byeAt: r.byeAt,
  };
}

/** A person's linked Macs (not removed), the first linked first. */
export function macsOf(email: string, now = nowS()): Mac[] {
  const rows = db().prepare(`SELECT ${COLS} FROM macs WHERE email = ? AND removed_at IS NULL ORDER BY linked_at, name`).all(email) as MacRow[];
  return rows.map((r) => macView(r, now));
}

/** The name a person signed in with, else the roster's, else the address. */
export function personName(email: string): string {
  const row = (db().prepare('SELECT name FROM people WHERE email = ?').get(email) ?? db().prepare('SELECT name FROM roster WHERE email = ?').get(email)) as { name: string } | undefined;
  return row?.name || email;
}

// ---------- what each Mac last sent ----------

/** The last snapshot a Mac sent (replaced each time; no history). */
export function saveSnapshot(id: string, snapshot: { at: number; mac: { name: string; kit: string } }, now = nowS()): void {
  const d = db();
  d.prepare(
    `INSERT INTO snapshots (mac_id, at, received_at, data) VALUES (?, ?, ?, ?)
     ON CONFLICT(mac_id) DO UPDATE SET at = excluded.at, received_at = excluded.received_at, data = excluded.data`,
  ).run(id, Math.floor(snapshot.at), now, JSON.stringify(snapshot));
  d.prepare('UPDATE macs SET name = ?, kit_version = ? WHERE id = ? AND (name <> ? OR kit_version IS NOT ?)').run(snapshot.mac.name, snapshot.mac.kit, id, snapshot.mac.name, snapshot.mac.kit);
}

export function lastSnapshot(id: string): any | null {
  const row = db().prepare('SELECT data FROM snapshots WHERE mac_id = ?').get(id) as { data: string } | undefined;
  return row ? JSON.parse(row.data) : null;
}

/** Each linked Mac of a person with its last snapshot, for the pages. */
export function snapshotsOf(email: string, now = nowS()): { mac: Mac; snapshot: any; receivedAt: number }[] {
  // No column name is in both tables, so COLS needs no table names.
  const rows = db()
    .prepare(`SELECT ${COLS}, s.data, s.received_at AS receivedAt FROM macs m JOIN snapshots s ON s.mac_id = m.id WHERE m.email = ? AND m.removed_at IS NULL ORDER BY m.linked_at, m.name`)
    .all(email) as (MacRow & { data: string; receivedAt: number })[];
  return rows.map((r) => ({ mac: macView(r, now), snapshot: JSON.parse(r.data), receivedAt: r.receivedAt }));
}

export type ArchivedItem = { cse: string; title: string; folder: string; archived_at: number | null; url: string };

/** The last archived list a Mac sent (rev and items; replaced each time). */
export function saveArchived(id: string, rev: string, items: ArchivedItem[], now = nowS()): void {
  db()
    .prepare(
      `INSERT INTO archived (mac_id, hash, received_at, data) VALUES (?, ?, ?, ?)
       ON CONFLICT(mac_id) DO UPDATE SET hash = excluded.hash, received_at = excluded.received_at, data = excluded.data`,
    )
    .run(id, rev, now, JSON.stringify(items));
}

export function archivedOf(id: string): { rev: string; items: ArchivedItem[]; receivedAt: number } | null {
  const row = db().prepare('SELECT hash, data, received_at FROM archived WHERE mac_id = ?').get(id) as { hash: string; data: string; received_at: number } | undefined;
  if (!row) return null;
  // The items, or (as test/sample.mjs writes it) the whole list with them.
  const v = JSON.parse(row.data);
  return { rev: row.hash, items: Array.isArray(v) ? v : (v?.items ?? []), receivedAt: row.received_at };
}

// ---------- removing a Mac ----------

export type Removal = { why: RemovedWhy; by: string; byName: string; words: string };

/** Marks one Mac removed inside the caller's transaction: the row stays,
 *  with when, why and by whom; what it sent goes; one record says so. It
 *  tells nobody: the caller emits mac-removed after its transaction. */
export function markRemoved(m: { id: string; name: string }, r: Removal, now = nowS()): void {
  const d = db();
  d.prepare('UPDATE macs SET removed_at = ?, removed_why = ?, removed_by = ? WHERE id = ?').run(now, r.why, r.by, m.id);
  d.prepare('DELETE FROM snapshots WHERE mac_id = ?').run(m.id);
  d.prepare('DELETE FROM archived WHERE mac_id = ?').run(m.id);
  addRecord({
    at: now, who: r.by, whoName: r.byName, macId: m.id, macName: m.name, action: 'remove_mac',
    before: { linked: true }, after: { linked: false, why: r.why }, result: 'ok', words: r.words,
  });
}

/** Removes one linked Mac and closes its socket (lib/hub.ts hears it).
 *  False when it is not linked (unknown, or removed already). */
export function removeMac(id: string, r: Removal, now = nowS()): boolean {
  const d = db();
  const m = d.prepare('SELECT id, email, name FROM macs WHERE id = ? AND removed_at IS NULL').get(id) as { id: string; email: string; name: string } | undefined;
  if (!m) return false;
  d.transaction(() => markRemoved(m, r, now))();
  presence.delete(id);
  events.emit('mac-removed', { macId: id, email: m.email, why: r.why });
  return true;
}

/** Remove from the phone (Menu > Macs > Remove): the person's own linked
 *  Mac only. False when it is not. */
export function removeOwnMac(user: { email: string; name: string }, macId: string, now = nowS()): boolean {
  const m = getMac(macId);
  if (!m || m.email !== user.email || m.removedAt !== null) return false;
  return removeMac(macId, { why: 'phone', by: user.email, byName: user.name, words: `Removed ${m.name} from the phone.` }, now);
}

/** The daily job: Macs not heard from in 90 days are removed, each with a
 *  record. Returns how many. */
export function removeQuietMacs(now = nowS()): number {
  const quiet = db()
    .prepare('SELECT id, name FROM macs WHERE removed_at IS NULL AND COALESCE(last_seen, linked_at) < ?')
    .all(now - QUIET_DAYS * 24 * 60 * 60) as { id: string; name: string }[];
  let n = 0;
  for (const m of quiet) {
    if (isConnected(m.id)) continue;
    if (removeMac(m.id, { why: 'quiet', by: 'daily job', byName: 'Daily job', words: `Removed ${m.name}: not heard from in ${QUIET_DAYS} days.` }, now)) n++;
  }
  return n;
}
