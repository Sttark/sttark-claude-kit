// What a phone page is drawn from on the server (view/model.ts, Kit): the
// person's linked Macs, the last snapshot and archived list each sent, and
// the open session's change records, all from the database. The page is
// drawn from this first; then the browser opens /live and keeps it up to
// date.
import { db } from './db.ts';
import { basePath } from './paths.ts';
import type { ArchivedItem, ChangeRecord, Kit, MacInfo, MacState, Snapshot } from '../view/model.ts';

type MacRow = { id: string; name: string; kit_version: string | null; last_seen: number | null; bye: string | null; bye_at: number | null };

/** A Mac's state from what the database holds, as the socket server says
 *  it (phone/DESIGN.md, section 6): live when heard from in the last 60
 *  seconds; updating for 2 minutes after bye update; asleep or quit after
 *  that bye; else not heard from. /live then sends the server's own word. */
export function macState(m: Pick<MacRow, 'last_seen' | 'bye' | 'bye_at'>, now: number): MacState {
  const byeAfter = m.bye && m.bye_at != null && (m.last_seen == null || m.bye_at >= m.last_seen);
  if (byeAfter) {
    if (m.bye === 'update') return now - m.bye_at! <= 120 ? 'updating' : 'not_heard';
    if (m.bye === 'sleep') return 'asleep';
    if (m.bye === 'quit') return 'quit';
  }
  if (m.last_seen != null && now - m.last_seen <= 60) return 'live';
  return 'not_heard';
}

function parse<T>(text: string): T | null {
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

/** Everything the person's pages show. `session` adds that session's
 *  change records from the phone. */
export function loadKit(user: { email: string }, opts: { session?: string; now?: number } = {}): Kit {
  const now = opts.now ?? Math.floor(Date.now() / 1000);
  const d = db();
  const rows = d
    .prepare('SELECT id, name, kit_version, last_seen, bye, bye_at FROM macs WHERE email = ? AND removed_at IS NULL ORDER BY linked_at, name')
    .all(user.email) as MacRow[];
  const snaps: Record<string, Snapshot> = {};
  const archived: Record<string, ArchivedItem[]> = {};
  const macs: MacInfo[] = [];
  for (const r of rows) {
    const s = d.prepare('SELECT data FROM snapshots WHERE mac_id = ?').get(r.id) as { data: string } | undefined;
    const snap = s ? parse<Snapshot>(s.data) : null;
    if (snap) snaps[r.id] = snap;
    const a = d.prepare('SELECT data FROM archived WHERE mac_id = ?').get(r.id) as { data: string } | undefined;
    const list = a ? parse<{ items?: ArchivedItem[] } | ArchivedItem[]>(a.data) : null;
    if (list) archived[r.id] = Array.isArray(list) ? list : (list.items ?? []);
    macs.push({ id: r.id, name: snap?.mac.name ?? r.name, state: macState(r, now), last_seen: r.last_seen, kit: snap?.mac.kit ?? r.kit_version ?? '' });
  }
  let records: ChangeRecord[] = [];
  if (opts.session && macs.length) {
    const ids = macs.map((m) => m.id);
    records = (
      d
        .prepare(
          `SELECT at, mac_id AS mac, session AS cse, action AS act, COALESCE(result, '') AS reason, COALESCE(words, '') AS words
           FROM records WHERE session = ? AND mac_id IN (${ids.map(() => '?').join(',')}) ORDER BY at DESC, id DESC LIMIT 20`,
        )
        .all(opts.session, ...ids) as ChangeRecord[]
    );
  }
  return { base: basePath(), now, email: user.email, macs, snaps, archived, records };
}

/** JSON safe inside a <script> element. */
export function kitJson(v: unknown): string {
  return JSON.stringify(v).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
}
