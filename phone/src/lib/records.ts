// Every change, with who made it (Sign-in and Access, Every change has a
// name on it). Rows are only ever added: the database itself refuses to
// change or delete one (triggers in lib/db.ts) until it is a year old, when
// the daily job takes it out (lib/expiry.ts). A record keeps the names the
// Mac and the session had at the time.
import { db } from './db.ts';

export type NewRecord = {
  /** Unix seconds; now when left out. */
  at?: number;
  /** The person's address, or the job that made the change ("roster sync"). */
  who: string;
  whoName: string;
  macId?: string | null;
  macName?: string | null;
  /** The session's Remote Control id, and its name then. */
  session?: string | null;
  sessionName?: string | null;
  action: string;
  before?: unknown;
  after?: unknown;
  /** How it ended: ok, gone, not_now, bad, offline, timeout or denied. */
  result?: string | null;
  /** The words the person was shown. */
  words?: string | null;
};

const json = (v: unknown) => (v === undefined ? null : JSON.stringify(v));

/** Adds one record and returns its id. */
export function addRecord(r: NewRecord): number {
  const at = r.at ?? Math.floor(Date.now() / 1000);
  const info = db()
    .prepare(
      `INSERT INTO records (at, who, who_name, mac_id, mac_name, session, session_name, action, before, after, result, words)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(at, r.who, r.whoName, r.macId ?? null, r.macName ?? null, r.session ?? null, r.sessionName ?? null, r.action, json(r.before), json(r.after), r.result ?? null, r.words ?? null);
  return Number(info.lastInsertRowid);
}
