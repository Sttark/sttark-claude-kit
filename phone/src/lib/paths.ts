// Where the app lives: APP_ORIGIN (scheme and host, read when used) and the
// path it is served under, BASE_PATH: "" for its own origin
// (https://kit.sttark.com), "/kit" for a path on another one
// (https://building.sttark.com/kit). Every link, redirect, cookie path and
// socket path comes from here.
//
// BASE_PATH is set when the app is built or started with `astro dev`
// (astro.config.mjs makes it Astro's base); the build keeps it in
// dist/kit-build.json for server.mjs, so it cannot differ between the build
// and the running server. Pages drawn in the browser read it from the data
// the page was drawn from.

/** The public origin, without a trailing slash: https://kit.sttark.com. */
export function appOrigin(): string {
  return (process.env.APP_ORIGIN || 'http://localhost:4350').replace(/\/+$/, '');
}

/** The path the app is served under: "" or "/kit" (no trailing slash). */
export function basePath(): string {
  return normalizeBase(import.meta.env?.BASE_URL);
}

/** "", "/", "kit", "/kit/" all come out as "" or "/kit". */
export function normalizeBase(raw: string | undefined | null): string {
  const s = String(raw ?? '').trim().replace(/\/+$/, '');
  if (!s) return '';
  return s.startsWith('/') ? s : `/${s}`;
}

/** An app path ("/usage", "/s/x?from=usage") as a link on this site. The
 *  home page keeps its slash ("/kit/"), which a proxy serving "/kit/"
 *  reaches. */
export function href(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${basePath()}${p}`;
}

/** An app path as a full address: https://kit.sttark.com/link/x. */
export function appUrl(path: string): string {
  return `${appOrigin()}${href(path)}`;
}

/** The address people type on their phone, without the scheme:
 *  kit.sttark.com, or building.sttark.com/kit. */
export function siteName(): string {
  return `${appOrigin().replace(/^https?:\/\//, '')}${basePath()}`;
}

/** A request's path inside the app, without BASE_PATH: "/kit/usage" is
 *  "/usage", "/kit" is "/". A path outside the base comes back as null. */
export function appPath(pathname: string): string | null {
  const base = basePath();
  if (!base) return pathname || '/';
  if (pathname === base) return '/';
  if (pathname.startsWith(`${base}/`)) return pathname.slice(base.length);
  return null;
}

/** The sign-in cookie's path: the app's own, so a site that shares the
 *  origin never gets it. */
export function cookiePath(): string {
  return basePath() || '/';
}
