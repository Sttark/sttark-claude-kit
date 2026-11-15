// Sign-ins: only a random id in the cookie, 30 days rolling, Sign out and
// Sign out everywhere, and nobody signed in once they leave the roster.
import { describe, it, expect, beforeEach } from 'vitest';
import { db, resetDbForTests } from '../src/lib/db.ts';
import { SESSION_COOKIE, TTL_S, createSession, destroyAllSessions, destroySession, readSession, stashOauthState, takeOauthState } from '../src/lib/session.ts';
import { ROSTER, fakeCookies, storeSampleRoster } from './helpers.ts';

const DAY = 24 * 60 * 60;
const T0 = 1_800_000_000;
const ada = { email: 'ada.anvil@sttark.com', name: 'Ada Anvil' };
const bix = { email: 'bix.dowel@sttark.com', name: 'Bix Dowel' };
const count = (table: string) => (db().prepare(`SELECT count(*) AS n FROM ${table}`).get() as { n: number }).n;
const addPushSub = (email: string, webSession: string, endpoint: string) =>
  db().prepare('INSERT INTO push_subs (endpoint, email, web_session, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?, ?)').run(endpoint, email, webSession, 'k', 'a', T0);

beforeEach(() => {
  resetDbForTests();
  storeSampleRoster(ROSTER, T0);
});

describe('sign-in sessions', () => {
  it('keeps only a random id in an httpOnly cookie, and the person in the database', () => {
    const c = fakeCookies();
    const id = createSession(c, ada, T0);
    expect(id).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(c.sets[0]).toMatchObject({ name: SESSION_COOKIE, value: id, options: { httpOnly: true, sameSite: 'lax', path: '/', maxAge: TTL_S } });
    expect(c.sets[0].value).not.toContain('ada');
    expect(readSession(c, T0 + 60)).toEqual(ada);
    expect(createSession(fakeCookies(), ada, T0)).not.toBe(id);
  });

  it('ends after 30 days without use', () => {
    const unused = fakeCookies();
    createSession(unused, ada, T0);
    expect(readSession(unused, T0 + 30 * DAY)).toBeNull();
    expect(readSession(unused, T0 + 31 * DAY)).toBeNull();
    // Used once on day 29: still signed in then.
    const used = fakeCookies();
    createSession(used, ada, T0);
    expect(readSession(used, T0 + 29 * DAY)).toEqual(ada);
  });

  it('rolls 30 days forward while it is used, in the database and the cookie', () => {
    const c = fakeCookies();
    const id = createSession(c, ada, T0);
    // Within a day of the last roll: nothing to write.
    expect(readSession(c, T0 + 3600)).toEqual(ada);
    expect(c.sets).toHaveLength(1);
    // A day or more later: 30 days from now, and a fresh cookie.
    expect(readSession(c, T0 + 2 * DAY)).toEqual(ada);
    expect(c.sets).toHaveLength(2);
    expect(c.sets[1]).toMatchObject({ value: id, options: { maxAge: TTL_S } });
    expect((db().prepare('SELECT expires_at FROM web_sessions WHERE id = ?').get(id) as { expires_at: number }).expires_at).toBe(T0 + 2 * DAY + TTL_S);
    expect(readSession(c, T0 + 31 * DAY)).toEqual(ada);
    expect(readSession(c, T0 + 61 * DAY + 1)).toBeNull();
  });

  it('signs nobody in with an id it never made', () => {
    expect(readSession(fakeCookies({ [SESSION_COOKIE]: 'made-up' }), T0)).toBeNull();
    expect(readSession(fakeCookies(), T0)).toBeNull();
  });

  it('Sign out ends this sign-in and its push subscription only', () => {
    const phone = fakeCookies();
    const laptop = fakeCookies();
    const p = createSession(phone, ada, T0);
    const l = createSession(laptop, ada, T0);
    addPushSub(ada.email, p, 'https://push.example/phone');
    addPushSub(ada.email, l, 'https://push.example/laptop');
    destroySession(phone);
    expect(phone.jar.has(SESSION_COOKIE)).toBe(false);
    expect(readSession(fakeCookies({ [SESSION_COOKIE]: p }), T0)).toBeNull();
    expect(readSession(laptop, T0)).toEqual(ada);
    expect(db().prepare('SELECT endpoint FROM push_subs').all()).toEqual([{ endpoint: 'https://push.example/laptop' }]);
  });

  it('Sign out everywhere ends every sign-in and push subscription of that person, and leaves their Macs', () => {
    const a1 = fakeCookies();
    const a2 = fakeCookies();
    const b = fakeCookies();
    addPushSub(ada.email, createSession(a1, ada, T0), 'https://push.example/a1');
    createSession(a2, ada, T0);
    addPushSub(bix.email, createSession(b, bix, T0), 'https://push.example/b');
    db().prepare("INSERT INTO macs (id, email, name, public_key, key_kind, linked_at) VALUES ('m1', ?, 'Mac mini', 'k', 'keychain', ?)").run(ada.email, T0);
    expect(destroyAllSessions(ada.email)).toEqual({ sessions: 2, pushSubs: 1 });
    expect(readSession(a1, T0)).toBeNull();
    expect(readSession(a2, T0)).toBeNull();
    expect(readSession(b, T0)).toEqual(bix);
    expect(count('push_subs')).toBe(1);
    expect(db().prepare('SELECT removed_at FROM macs').get()).toEqual({ removed_at: null });
  });

  it('signs nobody in who is no longer on the roster', () => {
    const c = fakeCookies();
    createSession(c, ada, T0);
    storeSampleRoster(ROSTER.filter((p) => p.email !== ada.email), T0 + 60);
    expect(readSession(c, T0 + 120)).toBeNull();
  });

  it('a Google sign-in under way works once, for 10 minutes', () => {
    stashOauthState('s1', { codeVerifier: 'v', nonce: 'n', returnTo: '/usage' }, T0);
    expect(takeOauthState('s1', T0 + 60)).toEqual({ codeVerifier: 'v', nonce: 'n', returnTo: '/usage' });
    expect(takeOauthState('s1', T0 + 61)).toBeNull();
    stashOauthState('s2', { codeVerifier: 'v', nonce: 'n', returnTo: '/' }, T0);
    expect(takeOauthState('s2', T0 + 601)).toBeNull();
  });
});
