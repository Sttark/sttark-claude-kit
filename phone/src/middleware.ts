// The gate. Every request resolves who is asking: a sign-in in the database
// (lib/session.ts), or DEV_FAKE_USER on a local run. Only the sign-in
// pages, the health check, the public files and the Kit's link calls are
// served to nobody; any other page sends people to sign in, and an API
// answers 401. The link page (/link/<token>) signs people in itself, with
// the account hint its Kit sent.
//
// A form post must come from this site: its Origin is APP_ORIGIN (Astro's
// own check is off, since it needs the origin when the app is built, and the
// origin is set where it runs). The Kit's calls are JSON, which a browser
// on another site cannot post without asking first.
//
// Paths here are inside the app: BASE_PATH ("/kit" when the app is served
// under building.sttark.com) is taken off first, and put on every redirect.
import { defineMiddleware } from 'astro:middleware';
import { devUser, readSession } from './lib/session.ts';
import { startRosterSync } from './lib/roster.ts';
import { startExpiry } from './lib/expiry.ts';
import { startHub } from './lib/hub.ts';
import { appOrigin, appPath, href } from './lib/paths.ts';

export { devUser };

// Phones fetch the tab icon without the sign-in cookie; the Kit links with
// no cookie at all.
export const PUBLIC = new Set(['/signin', '/healthz', '/favicon.svg', '/robots.txt']);
export const PUBLIC_PREFIX = ['/auth/', '/_astro/', '/api/mac/', '/link/'];

export function isPublic(pathname: string): boolean {
  return PUBLIC.has(pathname) || PUBLIC_PREFIX.some((p) => pathname.startsWith(p));
}

const FORM = /^(application\/x-www-form-urlencoded|multipart\/form-data|text\/plain)\b/i;

/** A form post from another site (or with no Origin) is refused. */
export function crossSiteForm(request: Request): boolean {
  if (['GET', 'HEAD', 'OPTIONS'].includes(request.method)) return false;
  const type = request.headers.get('content-type') ?? '';
  if (!FORM.test(type)) return false;
  return request.headers.get('origin') !== appOrigin();
}

// The hourly roster sync, the daily expiry job and the sockets start with
// the server (server.mjs makes one request at boot), not with the first
// visitor.
if (!process.env.VITEST) {
  startRosterSync();
  startExpiry();
  startHub();
}

export const onRequest = defineMiddleware(async (ctx, next) => {
  const path = appPath(ctx.url.pathname) ?? ctx.url.pathname;
  ctx.locals.user = readSession(ctx.cookies) ?? devUser();
  if (crossSiteForm(ctx.request)) {
    return new Response('This form must be sent from the Claude Kit site.', { status: 403, headers: { 'content-type': 'text/plain; charset=utf-8' } });
  }
  if (!ctx.locals.user && !isPublic(path)) {
    if (path.startsWith('/api/')) {
      return new Response(JSON.stringify({ error: 'sign in first' }), { status: 401, headers: { 'content-type': 'application/json' } });
    }
    return ctx.redirect(href(`/signin?next=${encodeURIComponent(path + ctx.url.search)}`));
  }
  return next();
});
