// Where the app lives: every address, redirect and cookie path from
// APP_ORIGIN and BASE_PATH, for kit.sttark.com and building.sttark.com/kit.
// And the addresses the link page compares.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';

const google = vi.hoisted(() => ({ params: {} as Record<string, string> }));
vi.mock('openid-client', () => ({
  discovery: async () => ({}),
  randomPKCECodeVerifier: () => 'v',
  calculatePKCECodeChallenge: async () => 'c',
  randomState: () => 's',
  randomNonce: () => 'n',
  buildAuthorizationUrl: (_c: unknown, params: Record<string, string>) => {
    google.params = params;
    return new URL('https://accounts.google.com/o/oauth2/v2/auth');
  },
}));
import { appPath, appUrl, basePath, cookiePath, href, normalizeBase, siteName } from '../src/lib/paths.ts';
import { beginLogin } from '../src/lib/auth.ts';
import { createSession, destroySession, SESSION_COOKIE } from '../src/lib/session.ts';
import { resetDbForTests } from '../src/lib/db.ts';
import { clientAddress, sameNetwork } from '../src/lib/net.ts';
import { fakeCookies, storeSampleRoster } from './helpers.ts';

const h = (o: Record<string, string>) => new Headers(o);

beforeEach(() => {
  resetDbForTests();
  storeSampleRoster();
});
afterEach(() => vi.unstubAllEnvs());

describe('APP_ORIGIN and BASE_PATH', () => {
  it('kit.sttark.com: its own origin, BASE_PATH ""', async () => {
    vi.stubEnv('APP_ORIGIN', 'https://kit.sttark.com/');
    expect([basePath(), href('/'), href('/macs'), appUrl('/link/x'), siteName(), cookiePath()]).toEqual(['', '/', '/macs', 'https://kit.sttark.com/link/x', 'kit.sttark.com', '/']);
    expect([appPath('/'), appPath('/macs')]).toEqual(['/', '/macs']);
    await beginLogin('Ada.Anvil@sttark.com');
    expect(google.params).toMatchObject({ redirect_uri: 'https://kit.sttark.com/auth/callback', hd: 'sttark.com', login_hint: 'ada.anvil@sttark.com' });
  });

  it('building.sttark.com/kit: BASE_PATH "/kit" on every address, redirect and cookie', async () => {
    vi.stubEnv('APP_ORIGIN', 'https://building.sttark.com');
    vi.stubEnv('BASE_URL', '/kit/');
    expect([basePath(), href('/'), href('/macs'), href('/signin?next=%2F'), appUrl('/'), appUrl('/auth/callback'), siteName(), cookiePath()]).toEqual([
      '/kit', '/kit/', '/kit/macs', '/kit/signin?next=%2F', 'https://building.sttark.com/kit/', 'https://building.sttark.com/kit/auth/callback', 'building.sttark.com/kit', '/kit',
    ]);
    expect([appPath('/kit'), appPath('/kit/'), appPath('/kit/macs'), appPath('/kits'), appPath('/macs')]).toEqual(['/', '/', '/macs', null, null]);
    await beginLogin('someone@example.com');
    expect(google.params.redirect_uri).toBe('https://building.sttark.com/kit/auth/callback');
    expect(google.params.login_hint).toBeUndefined();
    const c = fakeCookies();
    createSession(c, { email: 'ada.anvil@sttark.com', name: 'Ada Anvil' });
    expect(c.sets[0]).toMatchObject({ name: SESSION_COOKIE, options: { path: '/kit', secure: true, httpOnly: true } });
    const del = vi.spyOn(c, 'delete');
    destroySession(c);
    expect(del).toHaveBeenCalledWith(SESSION_COOKIE, { path: '/kit' });
  });

  it('takes BASE_PATH with or without its slashes', () => {
    expect(['', '/', 'kit', '/kit', '/kit/', ' /kit// '].map(normalizeBase)).toEqual(['', '', '/kit', '/kit', '/kit', '/kit']);
  });
});

describe('addresses', () => {
  it('reads the address nginx passes, never one the client made up', () => {
    expect(clientAddress(h({ 'x-real-ip': '203.0.113.5', 'x-forwarded-for': '1.2.3.4, 203.0.113.5' }), '127.0.0.1')).toBe('203.0.113.5');
    expect(clientAddress(h({ 'x-forwarded-for': '1.2.3.4, 203.0.113.6' }), '127.0.0.1')).toBe('203.0.113.6');
    expect(clientAddress(h({}), '::ffff:192.0.2.1')).toBe('192.0.2.1');
    expect(clientAddress(h({}), '127.0.0.1', { NODE_ENV: 'development' })).toBe('127.0.0.1');
    // Behind nginx, a loopback address means nginx passed none: unknown.
    expect(clientAddress(h({}), '127.0.0.1', { NODE_ENV: 'production' })).toBeNull();
  });

  it('one network: the same IPv4 address, or the same IPv6 /64', () => {
    expect(sameNetwork('203.0.113.5', '203.0.113.5')).toBe(true);
    expect(sameNetwork('203.0.113.5', '203.0.113.6')).toBe(false);
    expect(sameNetwork('2001:db8:1:2::10', '2001:db8:1:2:aaaa:bbbb:cccc:dddd')).toBe(true);
    expect(sameNetwork('2001:db8:1:2::10', '2001:db8:1:3::10')).toBe(false);
    expect(sameNetwork('2001:db8::1', '203.0.113.5')).toBe(false);
    expect(sameNetwork(null, '203.0.113.5')).toBe(false);
  });
});
