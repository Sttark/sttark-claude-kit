// Who may sign in: everyone on Workrouter's active roster, and nobody else.
// Each person sees only their own Macs, so the roster is the only rule.
//
// The roster comes only from Workrouter, in the background, as Building's
// circle chart does (lib/org.ts there): every hour, and at start,
// GET {WORKROUTER_URL}/org-sync/v1 with VAULT_ORG_SYNC_TOKEN (the Kit's own
// read-only key), the feed docs.sttark.com and Building read:
// {success, data: {circles, roles, employees: [{email, name, active}]}}.
// A good read replaces the stored roster in one transaction. A read that
// fails or looks wrong (an HTTP error, a refused key, no employees, fewer
// than 10 people on the roster) keeps the last good roster, so nobody gains
// or loses access, and logs [roster] ALERT. The feed's ETag is kept with a
// good roster and sent back; a 304 means nothing changed.
//
// Someone who leaves the roster loses access at that sync: their sign-ins
// and push subscriptions end, and their Macs are removed, each with a
// record (who: roster sync).
import { db } from './db.ts';
import { events } from './events.ts';
import { markRemoved } from './macs.ts';

export type RosterPerson = { email: string; name: string };
export type RosterStatus = { people: number; syncedAt: number | null; error: string | null; errorAt: number | null };

const SYNC_EVERY_MS = 60 * 60 * 1000;
const MIN_ON_ROSTER = 10;
const WORKROUTER = 'https://www.sttark.com';
const STTARK = /^[a-z0-9._%+-]+@sttark\.com$/;
const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '');
const nowS = () => Math.floor(Date.now() / 1000);

/** The active roster from the feed. Throws, in words, on anything that does
 *  not look like a whole roster. */
export function parseRoster(input: unknown): RosterPerson[] {
  let raw: any = typeof input === 'string' ? JSON.parse(input) : input;
  if (raw?.success === false) throw new Error(`Workrouter refused the read: ${str(raw.message) || 'no reason given'}`);
  if (raw && typeof raw === 'object' && raw.data && typeof raw.data === 'object' && !Array.isArray(raw.employees)) raw = raw.data;
  if (!Array.isArray(raw?.employees)) throw new Error('No roster (employees) in the feed');
  const people = new Map<string, RosterPerson>();
  for (const e of raw.employees) {
    const email = str(e?.email).toLowerCase();
    if (!STTARK.test(email) || e?.active === false) continue;
    people.set(email, { email, name: str(e?.name) || email });
  }
  if (people.size < MIN_ON_ROSTER) throw new Error(`Only ${people.size} people on the roster`);
  return [...people.values()].sort((a, b) => a.email.localeCompare(b.email));
}

const meta = (k: string) => (db().prepare('SELECT value FROM meta WHERE key = ?').get(k) as { value: string } | undefined)?.value ?? null;
const setMeta = (k: string, v: string) => db().prepare('INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value').run(k, v);
const dropMeta = (...keys: string[]) => db().prepare(`DELETE FROM meta WHERE key IN (${keys.map(() => '?').join(', ')})`).run(...keys);

/** Replaces the stored roster with a good one, and ends the access of
 *  everyone no longer on it. Returns what ended. */
export function storeRoster(people: RosterPerson[], now = nowS()): { macs: number; sessions: number; pushSubs: number } {
  const d = db();
  const off: { id: string; email: string; name: string }[] = [];
  const ended = d.transaction(() => {
    d.prepare('DELETE FROM roster').run();
    const add = d.prepare('INSERT INTO roster (email, name, synced_at) VALUES (?, ?, ?)');
    for (const p of people) add.run(p.email, p.name, now);
    off.push(...(d.prepare('SELECT id, email, name FROM macs WHERE removed_at IS NULL AND email NOT IN (SELECT email FROM roster)').all() as typeof off));
    for (const m of off) {
      markRemoved(m, { why: 'roster', by: 'roster sync', byName: 'Roster sync', words: `Removed ${m.name}: its person is no longer on the Sttark roster.` }, now);
    }
    const sessions = d.prepare('DELETE FROM web_sessions WHERE email NOT IN (SELECT email FROM roster)').run().changes;
    const pushSubs = d.prepare('DELETE FROM push_subs WHERE email NOT IN (SELECT email FROM roster)').run().changes;
    setMeta('roster_synced_at', String(now));
    return { macs: off.length, sessions, pushSubs };
  })();
  // After the transaction: the sockets of whoever left the roster close.
  for (const m of off) events.emit('mac-removed', { macId: m.id, email: m.email, why: 'roster' });
  events.emit('roster-synced');
  return ended;
}

/** Is this address on the stored roster? */
export function onRoster(email: string): boolean {
  return !!db().prepare('SELECT 1 FROM roster WHERE email = ?').get(email.trim().toLowerCase());
}

/** How many people the stored roster holds (0 before the first good read). */
export function rosterSize(): number {
  return (db().prepare('SELECT count(*) AS n FROM roster').get() as { n: number }).n;
}

export function rosterStatus(): RosterStatus {
  const num = (v: string | null) => (v === null ? null : Number(v));
  return { people: rosterSize(), syncedAt: num(meta('roster_synced_at')), error: meta('roster_error'), errorAt: num(meta('roster_error_at')) };
}

function fail(message: string, now: number): string {
  const s = rosterStatus();
  const kept = s.people ? `${s.people} people, read ${new Date((s.syncedAt ?? 0) * 1000).toISOString()}` : 'none stored';
  console.error(`[roster] ALERT: roster sync failed, keeping the last good roster (${kept}): ${message}`);
  setMeta('roster_error', message);
  setMeta('roster_error_at', String(now));
  return message;
}

type Fetch = typeof fetch;
/** One sync from Workrouter. Never throws: a failure keeps the last good
 *  roster and comes back as its message; success comes back as null. */
export async function syncRoster(env: Record<string, string | undefined> = process.env, f: Fetch = fetch, now = nowS()): Promise<string | null> {
  const token = env.VAULT_ORG_SYNC_TOKEN?.trim();
  const base = (env.WORKROUTER_URL?.trim() || WORKROUTER).replace(/\/+$/, '');
  if (!token) return rosterSize() ? null : fail('VAULT_ORG_SYNC_TOKEN is not set', now);
  try {
    const headers: Record<string, string> = { authorization: `Bearer ${token}`, accept: 'application/json' };
    const etag = rosterSize() ? meta('roster_etag') : null;
    if (etag) headers['if-none-match'] = etag;
    const r = await f(`${base}/org-sync/v1`, { headers, signal: AbortSignal.timeout(20000) });
    if (r.status === 304 && etag) {
      setMeta('roster_synced_at', String(now));
      dropMeta('roster_error', 'roster_error_at');
      console.log('[roster] Workrouter roster unchanged (304)');
      return null;
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const people = parseRoster(await r.json());
    const ended = storeRoster(people, now);
    const tag = r.headers?.get?.('etag');
    if (tag) setMeta('roster_etag', tag);
    else dropMeta('roster_etag');
    dropMeta('roster_error', 'roster_error_at');
    const gone = ended.sessions + ended.pushSubs + ended.macs ? `; off the roster: ${ended.sessions} sign-ins, ${ended.pushSubs} push subscriptions and ${ended.macs} Macs ended` : '';
    console.log(`[roster] synced from Workrouter: ${people.length} people on the roster${gone}`);
    return null;
  } catch (e) {
    return fail((e as Error)?.message ?? String(e), now);
  }
}

/** Sync now and every hour, with the server (once per process). */
export function startRosterSync(): void {
  const g = globalThis as { __kitRosterTimer?: ReturnType<typeof setInterval> };
  if (g.__kitRosterTimer) return;
  void syncRoster();
  g.__kitRosterTimer = setInterval(() => void syncRoster(), SYNC_EVERY_MS);
  g.__kitRosterTimer.unref?.();
}
