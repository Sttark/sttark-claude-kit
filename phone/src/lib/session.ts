// Sign-ins (web_sessions): a random 256-bit id in the database and in an
// httpOnly cookie, and nothing else about the person in the browser. 30
// days, rolled forward (in the database and in the cookie) at most once a
// day while it is used, so someone who opens the app now and then stays
// signed in. Sign out ends one at once, Sign out everywhere all of a
// person's, and leaving the roster all of them (lib/roster.ts).
import { randomBytes } from 'node:crypto';
import type { AstroCookies } from 'astro';
import { db } from './db.ts';
import { appOrigin } from './auth.ts';

export const SESSION_COOKIE = 'sttark_kit_session';
export const TTL_S = 30 * 24 * 60 * 60;
const DAY_S = 24 * 60 * 60;
const nowS = () => Math.floor(Date.now() / 1000);

export type SessionData = { email: string; name: string };
type Cookies = Pick<AstroCookies, 'get' | 'set' | 'delete'>;

function setCookie(cookies: Cookies, id: string): void {
  cookies.set(SESSION_COOKIE, id, { path: '/', httpOnly: true, sameSite: 'lax', secure: appOrigin().startsWith('https://'), maxAge: TTL_S });
}

export function createSession(cookies: Cookies, data: SessionData, now = nowS()): string {
  const id = randomBytes(32).toString('base64url');
  db().prepare('INSERT INTO web_sessions (id, email, name, created_at, expires_at) VALUES (?, ?, ?, ?, ?)').run(id, data.email, data.name, now, now + TTL_S);
  setCookie(cookies, id);
  return id;
}

/** Who this browser is signed in as, or null. Only someone on the roster
 *  as last read: off it, every sign-in ends. */
export function readSession(cookies: Cookies, now = nowS()): SessionData | null {
  const id = cookies.get(SESSION_COOKIE)?.value;
  if (!id) return null;
  const row = db()
    .prepare('SELECT s.email, s.name, s.expires_at FROM web_sessions s JOIN roster r ON r.email = s.email WHERE s.id = ?')
    .get(id) as { email: string; name: string; expires_at: number } | undefined;
  if (!row || row.expires_at <= now) return null;
  if (row.expires_at - now < TTL_S - DAY_S) {
    db().prepare('UPDATE web_sessions SET expires_at = ? WHERE id = ?').run(now + TTL_S, id);
    setCookie(cookies, id);
    touchPerson(row.email, row.name, now);
  }
  return { email: row.email, name: row.name };
}

/** Sign out: this sign-in, and the push subscription made under it. */
export function destroySession(cookies: Cookies): void {
  const id = cookies.get(SESSION_COOKIE)?.value;
  if (id) {
    const d = db();
    d.transaction(() => {
      d.prepare('DELETE FROM push_subs WHERE web_session = ?').run(id);
      d.prepare('DELETE FROM web_sessions WHERE id = ?').run(id);
    })();
  }
  cookies.delete(SESSION_COOKIE, { path: '/' });
}

/** Sign out everywhere: every sign-in and push subscription of this person.
 *  Their Macs stay linked. */
export function destroyAllSessions(email: string): { sessions: number; pushSubs: number } {
  const d = db();
  return d.transaction(() => ({
    pushSubs: d.prepare('DELETE FROM push_subs WHERE email = ?').run(email).changes,
    sessions: d.prepare('DELETE FROM web_sessions WHERE email = ?').run(email).changes,
  }))();
}

export type OauthState = { codeVerifier: string; nonce: string; returnTo: string };

export function stashOauthState(state: string, data: OauthState, now = nowS()): void {
  db().prepare('INSERT INTO oauth_states (state, data, expires_at) VALUES (?, ?, ?)').run(state, JSON.stringify(data), now + 600);
}

/** The sign-in under way with this state, once: it is gone after. */
export function takeOauthState(state: string, now = nowS()): OauthState | null {
  const row = db().prepare('SELECT data, expires_at FROM oauth_states WHERE state = ?').get(state) as { data: string; expires_at: number } | undefined;
  db().prepare('DELETE FROM oauth_states WHERE state = ?').run(state);
  if (!row || row.expires_at < now) return null;
  return JSON.parse(row.data) as OauthState;
}

/** Notes who signed in, and when they were last here (at most daily). */
export function touchPerson(email: string, name: string, now = nowS()): void {
  db()
    .prepare(
      `INSERT INTO people (email, name, first_seen, last_seen) VALUES (?, ?, ?, ?)
       ON CONFLICT(email) DO UPDATE SET name = excluded.name, last_seen = excluded.last_seen`,
    )
    .run(email, name, now, now);
}
