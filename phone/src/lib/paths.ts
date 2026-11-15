// The path the app is served under, BASE_PATH: "" for its own origin
// (https://kit.sttark.com), "/kit" for a path on another one
// (https://building.sttark.com/kit). Every link, redirect, cookie path and
// socket path comes from here. BASE_PATH is set when the app is built or
// started with `astro dev` (astro.config.mjs makes it Astro's base); the
// build keeps it in dist/kit-build.json for server.mjs, so it cannot differ
// between the build and the running server. Pages drawn in the browser
// read it from the data the page was drawn from.

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

/** An app path ("/usage", "/s/x?from=usage") as a link on this site. */
export function href(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${basePath()}${p}`;
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
