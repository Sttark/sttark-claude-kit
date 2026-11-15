// The roster from Workrouter: a good read replaces it, a failed or odd read
// keeps the last good one, and leaving the roster ends a person's access.
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { db, resetDbForTests } from '../src/lib/db.ts';
import { onRoster, parseRoster, rosterSize, rosterStatus, syncRoster } from '../src/lib/roster.ts';
import { createSession, readSession } from '../src/lib/session.ts';
import { ROSTER, fakeCookies, feed } from './helpers.ts';

const T0 = 1_800_000_000;
const ENV = { WORKROUTER_URL: 'https://workrouter.example.invalid', VAULT_ORG_SYNC_TOKEN: 'sk_org_test' };
const answer = (body: unknown, init: ResponseInit = {}) => vi.fn(async () => new Response(typeof body === 'string' ? body : JSON.stringify(body), init));
const people = () => (db().prepare('SELECT email FROM roster ORDER BY email').all() as { email: string }[]).map((r) => r.email);

beforeEach(() => {
  resetDbForTests();
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

describe('roster sync', () => {
  it('stores the active roster from a good read, and sends the key', async () => {
    const f = answer(feed(ROSTER, [{ email: 'old.timer@sttark.com', name: 'Old Timer', active: false }, { email: 'someone@example.com', name: 'Not Sttark', active: true }]), { headers: { etag: '"v1"' } });
    expect(await syncRoster(ENV, f, T0)).toBeNull();
    expect(f).toHaveBeenCalledOnce();
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://workrouter.example.invalid/org-sync/v1');
    expect((init.headers as Record<string, string>).authorization).toBe('Bearer sk_org_test');
    expect(people()).toEqual(ROSTER.map((p) => p.email).sort());
    expect(onRoster('Ada.Anvil@sttark.com')).toBe(true);
    expect(onRoster('old.timer@sttark.com')).toBe(false);
    expect(rosterStatus()).toMatchObject({ people: 12, syncedAt: T0, error: null });
  });

  it('a 304 keeps the roster as it is', async () => {
    await syncRoster(ENV, answer(feed(), { headers: { etag: '"v1"' } }), T0);
    const f = vi.fn(async () => new Response(null, { status: 304 }));
    expect(await syncRoster(ENV, f, T0 + 3600)).toBeNull();
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)['if-none-match']).toBe('"v1"');
    expect(rosterSize()).toBe(12);
    expect(rosterStatus().syncedAt).toBe(T0 + 3600);
  });

  it('a failed or odd read keeps the last good roster', async () => {
    await syncRoster(ENV, answer(feed()), T0);
    const before = people();
    const bad: [string, () => Promise<Response>, RegExp][] = [
      ['an HTTP error', async () => new Response('down', { status: 502 }), /HTTP 502/],
      ['a refused key', async () => new Response(JSON.stringify({ success: false, message: 'invalid key' })), /refused.*invalid key/],
      ['no roster in the feed', async () => new Response(JSON.stringify({ success: true, data: { circles: {}, roles: [] } })), /No roster/],
      ['an empty roster', async () => new Response(JSON.stringify(feed([]))), /Only 0 people/],
      ['a short roster', async () => new Response(JSON.stringify(feed(ROSTER.slice(0, 9)))), /Only 9 people/],
      ['an answer that is not JSON', async () => new Response('<html>login</html>'), /JSON/],
      ['no answer at all', async () => { throw new TypeError('fetch failed'); }, /fetch failed/],
    ];
    for (const [what, f, why] of bad) {
      expect(await syncRoster(ENV, f as typeof fetch, T0 + 60), what).toMatch(why);
      expect(people(), what).toEqual(before);
    }
    expect(rosterStatus()).toMatchObject({ people: 12, syncedAt: T0, errorAt: T0 + 60 });
    expect(rosterStatus().error).toMatch(/fetch failed/);
    // The next good read clears the error.
    expect(await syncRoster(ENV, answer(feed()), T0 + 120)).toBeNull();
    expect(rosterStatus().error).toBeNull();
  });

  it('without the key it reads nothing and keeps what is stored', async () => {
    const f = vi.fn();
    expect(await syncRoster({ WORKROUTER_URL: ENV.WORKROUTER_URL }, f as unknown as typeof fetch, T0)).toMatch(/VAULT_ORG_SYNC_TOKEN is not set/);
    await syncRoster(ENV, answer(feed()), T0);
    expect(await syncRoster({}, f as unknown as typeof fetch, T0 + 60)).toBeNull();
    expect(f).not.toHaveBeenCalled();
    expect(rosterSize()).toBe(12);
  });

  it("leaving the roster ends that person's sign-ins and push subscriptions and removes their Macs, with a record", async () => {
    await syncRoster(ENV, answer(feed()), T0);
    const ada = fakeCookies();
    const bix = fakeCookies();
    const adaId = createSession(ada, { email: 'ada.anvil@sttark.com', name: 'Ada Anvil' }, T0);
    createSession(bix, { email: 'bix.dowel@sttark.com', name: 'Bix Dowel' }, T0);
    db().prepare('INSERT INTO push_subs (endpoint, email, web_session, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?, ?)').run('https://push.example/a', 'ada.anvil@sttark.com', adaId, 'k', 'a', T0);
    db().prepare("INSERT INTO macs (id, email, name, public_key, key_kind, linked_at) VALUES ('m1', 'ada.anvil@sttark.com', 'Mac mini', 'k', 'keychain', ?)").run(T0);
    db().prepare("INSERT INTO snapshots (mac_id, at, received_at, data) VALUES ('m1', ?, ?, '{}')").run(T0, T0);

    expect(await syncRoster(ENV, answer(feed(ROSTER.filter((p) => p.email !== 'ada.anvil@sttark.com'))), T0 + 3600)).toBeNull();
    expect(readSession(ada, T0 + 3601)).toBeNull();
    expect(readSession(bix, T0 + 3601)).toMatchObject({ email: 'bix.dowel@sttark.com' });
    expect(db().prepare('SELECT count(*) AS n FROM push_subs').get()).toEqual({ n: 0 });
    expect(db().prepare('SELECT removed_at, removed_why, removed_by FROM macs').get()).toEqual({ removed_at: T0 + 3600, removed_why: 'roster', removed_by: 'roster sync' });
    expect(db().prepare('SELECT count(*) AS n FROM snapshots').get()).toEqual({ n: 0 });
    expect(db().prepare('SELECT at, who, who_name, mac_id, mac_name, action, result FROM records').all()).toEqual([
      { at: T0 + 3600, who: 'roster sync', who_name: 'Roster sync', mac_id: 'm1', mac_name: 'Mac mini', action: 'remove_mac', result: 'ok' },
    ]);
  });

  it('reads the feed with or without its data wrapper', () => {
    expect(parseRoster(feed())).toHaveLength(12);
    expect(parseRoster(feed().data)).toHaveLength(12);
  });
});
