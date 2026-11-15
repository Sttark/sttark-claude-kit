// The gate. Every request resolves who is asking: a sign-in in the database
// (lib/session.ts), or DEV_FAKE_USER on a local run. Only the sign-in
// pages, the health check and the public files are served to nobody; any
// other page sends people to sign in, and an API answers 401.
import { defineMiddleware } from 'astro:middleware';
import { readSession } from './lib/session.ts';
import { startRosterSync } from './lib/roster.ts';
import { startExpiry } from './lib/expiry.ts';

// Phones fetch the tab icon without the sign-in cookie.
export const PUBLIC = new Set(['/signin', '/healthz', '/favicon.svg', '/robots.txt']);
export const PUBLIC_PREFIX = ['/auth/', '/_astro/'];

export function isPublic(pathname: string): boolean {
  return PUBLIC.has(pathname) || PUBLIC_PREFIX.some((p) => pathname.startsWith(p));
}

/** The made-up person a local run signs in as (DEV_FAKE_USER), never in
 *  production: anyone who reaches the server would be that person. */
export function devUser(env: Record<string, string | undefined> = process.env): { email: string; name: string } | null {
  const email = env.DEV_FAKE_USER?.trim().toLowerCase();
  if (!email || env.NODE_ENV === 'production') return null;
  return { email, name: email.split('@')[0] };
}

// The hourly roster sync and the daily expiry job start with the server
// (server.mjs makes one request at boot), not with the first visitor.
if (!process.env.VITEST) {
  startRosterSync();
  startExpiry();
}

export const onRequest = defineMiddleware(async (ctx, next) => {
  const { pathname } = ctx.url;
  ctx.locals.user = readSession(ctx.cookies) ?? devUser();
  if (!ctx.locals.user && !isPublic(pathname)) {
    if (pathname.startsWith('/api/')) {
      return new Response(JSON.stringify({ error: 'sign in first' }), { status: 401, headers: { 'content-type': 'application/json' } });
    }
    return ctx.redirect(`/signin?next=${encodeURIComponent(pathname + ctx.url.search)}`);
  }
  return next();
});
