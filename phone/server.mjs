// Production entry: `node server.mjs`, run in a folder that holds this file,
// dist/, package.json and the production node_modules. One HTTP server on
// HOST (default 127.0.0.1) and PORT (default 4350), behind nginx, which
// holds the certificate for kit.sttark.com:
//
//   1. a built file from dist/client (styles, scripts, fonts, icons);
//   2. else Astro's pages and routes (dist/server/entry.mjs, the node
//      adapter in middleware mode);
//   3. WebSocket upgrades, /mac for the Kit on each Mac and /live for the
//      phone pages, through the hook below.
//
// Everything is under the base the app was built with (BASE_PATH, read
// from dist/kit-build.json): "" for https://kit.sttark.com, "/kit" when
// nginx passes https://building.sttark.com/kit/ here unchanged.
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { posix } from 'node:path';
import { fileURLToPath } from 'node:url';
import send from 'send';

// A production run unless the environment says otherwise: DEV_FAKE_USER is
// ignored (src/middleware.ts), whatever the env file holds.
process.env.NODE_ENV ??= 'production';

const { handler } = await import('./dist/server/entry.mjs');
const HOST = process.env.HOST || '127.0.0.1';
const PORT = Number(process.env.PORT || 4350);
const CLIENT = fileURLToPath(new URL('./dist/client/', import.meta.url));
let BASE = '';
try {
  BASE = JSON.parse(readFileSync(new URL('./dist/kit-build.json', import.meta.url), 'utf8')).base ?? '';
} catch {
  console.warn('[server] dist/kit-build.json is missing: serving at the root (BASE_PATH "")');
}

/** A file from dist/client, else next(). These are served before the
 *  sign-in check, so dist/client holds only public files: no page is
 *  prerendered (every page needs a sign-in). Files under /_astro/ carry a
 *  hash in their name and never change, so browsers keep them for a year. */
function builtFile(req, res, next) {
  if (req.method !== 'GET' && req.method !== 'HEAD') return next();
  let path;
  try {
    path = decodeURIComponent(new URL(req.url ?? '/', 'http://x').pathname);
  } catch {
    res.writeHead(400).end('Bad request');
    return;
  }
  if (BASE) {
    if (!path.startsWith(`${BASE}/`)) return next();
    path = path.slice(BASE.length);
  }
  if (path.endsWith('/')) return next();
  const file = send(req, posix.normalize(path), { root: CLIENT, dotfiles: 'deny', index: false, redirect: false });
  let found = false;
  file.on('file', () => {
    found = true;
  });
  file.on('error', (err) => {
    if (!found) return next();
    res.writeHead(err.statusCode ?? 500).end();
  });
  file.on('stream', () => {
    if (path.startsWith('/_astro/')) res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
  });
  file.pipe(res);
}

const server = createServer((req, res) => builtFile(req, res, () => handler(req, res)));

// The WebSocket hook. Every upgrade request goes to the function the app's
// server code sets at globalThis[Symbol.for('sttark.kit.upgrade')]
// (onUpgrade in src/lib/upgrade.ts). Until one is set, every upgrade is
// refused. nginx passes /mac and /live here with the Upgrade headers, the
// path as it came (under BASE_PATH when the site has one).
const UPGRADE = Symbol.for('sttark.kit.upgrade');
server.on('upgrade', (req, socket, head) => {
  const handle = globalThis[UPGRADE];
  if (typeof handle === 'function') return handle(req, socket, head);
  socket.end('HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
});

// A restart (a deploy): every socket closes with 1012, so each Kit and page
// connects again at once, then the server stops.
process.once('SIGTERM', () => {
  const closeAll = globalThis[Symbol.for('sttark.kit.shutdown')];
  if (typeof closeAll === 'function') closeAll();
  server.close();
  setTimeout(() => process.exit(0), 500).unref();
});

server.listen(PORT, HOST, async () => {
  console.log(`[server] Claude Kit phone server on http://${HOST}:${PORT}${BASE || ''}`);
  // One request at boot loads the middleware, which starts the hourly
  // roster sync and the daily expiry job, as Building's start.mjs does.
  const self = HOST === '0.0.0.0' || HOST === '::' ? '127.0.0.1' : HOST.includes(':') ? `[${HOST}]` : HOST;
  try {
    await fetch(`http://${self}:${PORT}${BASE}/healthz`);
  } catch (e) {
    console.error(`[server] the first request failed: ${e.message}`);
  }
});
