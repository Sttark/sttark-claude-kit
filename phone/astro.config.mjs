import { defineConfig } from 'astro/config';
import node from '@astrojs/node';
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';

// Local runs read .env into process.env, as Building does. The server reads
// process.env; in production the server's env file fills it.
try {
  process.loadEnvFile('.env');
} catch {}

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

// Where the site lives under its origin: "" at kit.sttark.com, "/kit" at
// building.sttark.com/kit. Set at build time (BASE_PATH); every link, file
// and socket path starts with it (src/lib/base.ts). The build writes it to
// dist/kit-build.json, so server.mjs serves the built files under the same path.
function basePath() {
  const b = (process.env.BASE_PATH ?? '').trim().replace(/\/+$/, '');
  if (b && !/^\/[A-Za-z0-9._~-]+(\/[A-Za-z0-9._~-]+)*$/.test(b)) throw new Error(`BASE_PATH "${process.env.BASE_PATH}" is not a path such as /kit`);
  return b;
}
const BASE = basePath();

export default defineConfig({
  output: 'server',
  base: BASE || '/',
  integrations: [
    {
      name: 'kit-base-path',
      hooks: {
        'astro:build:done': () => writeFileSync(new URL('./dist/kit-build.json', import.meta.url), JSON.stringify({ base: BASE }) + '\n'),
      },
    },
  ],
  devToolbar: { enabled: false },
  // Middleware mode: server.mjs serves Astro's handler, the built files and
  // the WebSocket upgrades on one port.
  adapter: node({ mode: 'middleware' }),
  // Sign-ins are rows in the database (src/lib/session.ts), not Astro's
  // sessions.
  session: false,
  security: {
    checkOrigin: true,
    // Behind nginx a request arrives as http on 127.0.0.1. Trusting the
    // forwarded host and protocol for this domain only is what lets the
    // origin check pass on form posts, as on Building and docs.sttark.com.
    // building.sttark.com is the other address the site may have (/kit).
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
