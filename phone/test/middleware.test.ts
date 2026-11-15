// The gate: what nobody needs a sign-in for, where everyone else is sent,
// and DEV_FAKE_USER only on a local run.
import { describe, it, expect, vi, beforeEach } from 'vitest';
vi.mock('astro:middleware', () => ({ defineMiddleware: (f: unknown) => f }));
import { devUser, isPublic, onRequest } from '../src/middleware.ts';
import { resetDbForTests } from '../src/lib/db.ts';
import { createSession, SESSION_COOKIE } from '../src/lib/session.ts';
import { fakeCookies, storeSampleRoster } from './helpers.ts';

/** Runs the middleware for one request; returns what it answered. */
async function ask(path: string, cookies = fakeCookies()) {
  const url = new URL(path, 'http://localhost:4350');
  const ctx = {
    url,
    cookies,
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
});

describe('middleware', () => {
  it('serves sign-in, the health check and the public files to nobody', () => {
    for (const p of ['/signin', '/healthz', '/favicon.svg', '/robots.txt', '/auth/login', '/auth/callback', '/auth/logout', '/_astro/app.css']) expect(isPublic(p), p).toBe(true);
    for (const p of ['/', '/archived', '/usage', '/macs', '/api/anything', '/favicon.svg/x', '/signin/x']) expect(isPublic(p), p).toBe(false);
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
});
