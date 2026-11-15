import { defineConfig } from 'astro/config';
import node from '@astrojs/node';
import { execFileSync } from 'node:child_process';
import { writeFile } from 'node:fs/promises';

// Local runs read .env into process.env, as Building does. The server reads
// process.env; in production the server's env file fills it.
try {
  process.loadEnvFile('.env');
} catch {}

// Where the site lives under its origin (src/lib/paths.ts): "" at
// kit.sttark.com, "/kit" at building.sttark.com/kit. It is Astro's base, so
// it is fixed when the app is built (or started with astro dev); every link,
// file and socket path starts with it. The build writes it to
// dist/kit-build.json, so server.mjs serves the built files under the same
// path.
function basePath() {
  let b = (process.env.BASE_PATH ?? '').trim().replace(/\/+$/, '');
  if (b && !b.startsWith('/')) b = `/${b}`;
  if (b && !/^\/[A-Za-z0-9._~-]+(\/[A-Za-z0-9._~-]+)*$/.test(b)) throw new Error(`BASE_PATH "${process.env.BASE_PATH}" is not a path such as /kit`);
  return b;
}
const BASE = basePath();

// The commit this build is made from, which /healthz reports: GITHUB_SHA in
// a workflow, else git, else "unknown".
function buildSha() {
  if (process.env.GITHUB_SHA) return process.env.GITHUB_SHA;
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch {
    return 'unknown';
  }
}

// server.mjs needs the base before the app loads (it serves the built files
// first), so the build leaves it in dist/kit-build.json.
let outDir;
const buildFacts = {
  name: 'kit-build-facts',
  hooks: {
    'astro:config:done': ({ config }) => {
      outDir = config.outDir;
    },
    'astro:build:done': async () => {
      await writeFile(new URL('kit-build.json', outDir), JSON.stringify({ base: BASE }) + '\n');
    },
  },
};

// The sockets in `astro dev`: server.mjs passes upgrades in production; here
// the dev server's own upgrades for /mac and /live go to the same handler
// (src/lib/upgrade.ts). Vite's own live-reload socket is left alone. The
// handler is set when the middleware first loads, so a socket that comes
// before any page asks for /healthz first.
const UPGRADE = Symbol.for('sttark.kit.upgrade');
const devSockets = {
  name: 'kit-dev-sockets',
  hooks: {
    'astro:server:setup': ({ server }) => {
      const http = server.httpServer;
      if (!http) return;
      http.on('upgrade', async (req, socket, head) => {
        let path = '';
        try {
          path = new URL(req.url ?? '/', 'http://x').pathname;
        } catch {}
        if (path !== `${BASE}/mac` && path !== `${BASE}/live`) return;
        if (typeof globalThis[UPGRADE] !== 'function') {
          const where = http.address();
          try {
            await fetch(`http://localhost:${typeof where === 'object' && where ? where.port : 4350}${BASE}/healthz`);
          } catch {}
        }
        const handle = globalThis[UPGRADE];
        if (typeof handle === 'function') handle(req, socket, head);
        else socket.destroy();
      });
    },
  },
};

export default defineConfig({
  output: 'server',
  base: BASE || '/',
  integrations: [buildFacts, devSockets],
  devToolbar: { enabled: false },
  // Middleware mode: server.mjs serves Astro's handler, the built files and
  // the WebSocket upgrades on one port.
  adapter: node({ mode: 'middleware' }),
  // Sign-ins are rows in the database (src/lib/session.ts), not Astro's
  // sessions.
  session: false,
  security: {
    // A form post's Origin is checked against APP_ORIGIN where the server
    // runs (src/middleware.ts), not against an origin fixed at build time.
    checkOrigin: false,
    // Behind nginx a request arrives as http on 127.0.0.1: the forwarded
    // host and protocol are trusted for the site's two possible addresses
    // only, so Astro.url says https there.
    allowedDomains: [
      { protocol: 'https', hostname: 'kit.sttark.com' },
      { protocol: 'https', hostname: 'building.sttark.com' },
    ],
  },
  server: { port: 4350 },
  vite: {
    define: { __KIT_BUILD_SHA__: JSON.stringify(buildSha()) },
    ssr: { external: ['better-sqlite3'] },
  },
});
