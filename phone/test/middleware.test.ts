// The gate: what nobody needs a sign-in for, where everyone else is sent,
// DEV_FAKE_USER only on a local run, form posts only from this site, and
// all of it under BASE_PATH when the app is served under a path.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
vi.mock('astro:middleware', () => ({ defineMiddleware: (f: unknown) => f }));
import { devUser, isPublic, onRequest } from '../src/middleware.ts';
import { resetDbForTests } from '../src/lib/db.ts';
import { createSession, SESSION_COOKIE } from '../src/lib/session.ts';
import { fakeCookies, storeSampleRoster } from './helpers.ts';

/** Runs the middleware for one request; returns what it answered. */
async function ask(path: string, cookies = fakeCookies(), init: RequestInit = {}) {
  const url = new URL(path, 'http://localhost:4350');
  const ctx = {
    url,
    cookies,
    request: new Request(url, init),
    locals: {} as App.Locals,
    redirect: (to: string, status = 302) => new Response(null, { status, headers: { location: to } }),
  };
  const next = vi.fn(async () => new Response('page'));
  const res = (await (onRequest as any)(ctx, next)) as Response;
  return { res, next, user: ctx.locals.user };
}

beforeEach(() => {
  resetDbForTests();
  storeSampleRoster();
  vi.stubEnv('DEV_FAKE_USER', '');
  vi.stubEnv('APP_ORIGIN', 'http://localhost:4350');
});
afterEach(() => vi.unstubAllEnvs());

describe('middleware', () => {
  it('serves sign-in, the health check, the public files and the Kit\'s link calls to nobody', () => {
    for (const p of ['/signin', '/healthz', '/favicon.svg', '/robots.txt', '/auth/login', '/auth/callback', '/auth/logout', '/_astro/app.css', '/api/mac/link', '/api/mac/link/abc', '/link/abc']) expect(isPublic(p), p).toBe(true);
    for (const p of ['/', '/archived', '/usage', '/macs', '/api/anything', '/api/macs', '/favicon.svg/x', '/signin/x', '/linked']) expect(isPublic(p), p).toBe(false);
  });

  it('sends a signed-out visitor to sign in, back to where they were going', async () => {
    const { res, next } = await ask('/usage?x=1');
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe('/signin?next=%2Fusage%3Fx%3D1');
    expect(next).not.toHaveBeenCalled();
    expect((await ask('/api/anything')).res.status).toBe(401);
    expect((await ask('/healthz')).next).toHaveBeenCalled();
  });

  it('lets a signed-in person through', async () => {
    const c = fakeCookies();
    createSession(c, { email: 'ada.anvil@sttark.com', name: 'Ada Anvil' });
    const { next, user } = await ask('/', fakeCookies({ [SESSION_COOKIE]: c.jar.get(SESSION_COOKIE) }));
    expect(next).toHaveBeenCalled();
    expect(user).toEqual({ email: 'ada.anvil@sttark.com', name: 'Ada Anvil' });
  });

  it('signs in DEV_FAKE_USER on a local run only', async () => {
    expect(devUser({ DEV_FAKE_USER: 'Avery.Stone@sttark.com' })).toEqual({ email: 'avery.stone@sttark.com', name: 'avery.stone' });
    expect(devUser({ DEV_FAKE_USER: 'avery.stone@sttark.com', NODE_ENV: 'production' })).toBeNull();
    expect(devUser({})).toBeNull();
    vi.stubEnv('DEV_FAKE_USER', 'avery.stone@sttark.com');
    const { next, user } = await ask('/macs');
    expect(next).toHaveBeenCalled();
    expect(user?.email).toBe('avery.stone@sttark.com');
  });

  it('refuses a form post from another site, or with no Origin, and takes one from APP_ORIGIN', async () => {
    vi.stubEnv('DEV_FAKE_USER', 'avery.stone@sttark.com');
    const form = (origin?: string) => ({ method: 'POST', body: 'remove=m1', headers: { 'content-type': 'application/x-www-form-urlencoded', ...(origin ? { origin } : {}) } });
    expect((await ask('/macs', fakeCookies(), form('https://evil.example'))).res.status).toBe(403);
    expect((await ask('/macs', fakeCookies(), form())).res.status).toBe(403);
    const ok = await ask('/macs', fakeCookies(), form('http://localhost:4350'));
    expect(ok.next).toHaveBeenCalled();
    // The Kit's JSON link request has no Origin, and is not a form.
    const kit = await ask('/api/mac/link', fakeCookies(), { method: 'POST', body: '{}', headers: { 'content-type': 'application/json' } });
    expect(kit.next).toHaveBeenCalled();
  });

  it('works under BASE_PATH /kit: paths inside the app, redirects with the base', async () => {
    vi.stubEnv('BASE_URL', '/kit/');
    const { res, next } = await ask('/kit/usage?x=1');
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe('/kit/signin?next=%2Fusage%3Fx%3D1');
    expect(next).not.toHaveBeenCalled();
    expect((await ask('/kit/healthz')).next).toHaveBeenCalled();
    expect((await ask('/kit/api/mac/link', fakeCookies(), { method: 'POST', body: '{}', headers: { 'content-type': 'application/json' } })).next).toHaveBeenCalled();
    expect((await ask('/kit/api/anything')).res.status).toBe(401);
    expect((await ask('/kit')).res.headers.get('location')).toBe('/kit/signin?next=%2F');
  });
});
