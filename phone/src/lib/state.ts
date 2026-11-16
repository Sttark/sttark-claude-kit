// What a phone page is drawn from on the server (view/model.ts, Kit): the
// person's linked Macs, the last snapshot and archived list each sent, the
// Usage by session list each sent for the period the Usage tab shows, and
// the open session's change records, all from the database. The page is
// drawn from this first; then the browser opens /live and keeps it up to
// date.
import { db } from './db.ts';
import { basePath } from './paths.ts';
import { macsOf, usageOf } from './macs.ts';
import { noticesOfSignIn, pushKey } from './push.ts';
import type { ArchivedItem, ChangeRecord, Kit, MacInfo, Snapshot, UsageList } from '../view/model.ts';

function parse<T>(text: string): T | null {
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

/** Everything the person's pages show. `session` adds that session's
 *  change records from the phone; `usage` (the Usage tab) each Mac's Usage
 *  by session list for that period; `notices` (Menu) adds the key a phone
 *  subscribes with and the notices of this sign-in (its id, or null). */
export function loadKit(
  user: { email: string },
  opts: { session?: string; now?: number; usage?: string | null; notices?: { signIn: string | null } } = {},
): Kit {
  const now = opts.now ?? Math.floor(Date.now() / 1000);
  const d = db();
  // Each Mac's state as /live says it (lib/macs.ts): from when it was last
  // heard from, in memory on this server, and its last bye.
  const rows = macsOf(user.email, now);
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
    macs.push({ id: r.id, name: snap?.mac.name ?? r.name, state: r.state, last_seen: r.lastSeen, kit: snap?.mac.kit ?? r.kit ?? '' });
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
  const kit: Kit = { base: basePath(), now, email: user.email, macs, snaps, archived, records };
  if (opts.usage) {
    const usage: Record<string, UsageList> = {};
    for (const m of macs) {
      const list = usageOf(m.id, opts.usage);
      if (list) usage[m.id] = list;
    }
    kit.usage = usage;
  }
  if (opts.notices) kit.notices = { key: pushKey(), mine: noticesOfSignIn(opts.notices.signIn) };
  return kit;
}

/** JSON safe inside a <script> element. */
export function kitJson(v: unknown): string {
  return JSON.stringify(v).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
}
