import { defineConfig } from 'astro/config';
import node from '@astrojs/node';
import { execFileSync } from 'node:child_process';

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

export default defineConfig({
  output: 'server',
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
    allowedDomains: [{ protocol: 'https', hostname: 'kit.sttark.com' }],
  },
  server: { port: 4350 },
  vite: {
    define: { __KIT_BUILD_SHA__: JSON.stringify(buildSha()) },
    ssr: { external: ['better-sqlite3'] },
  },
});
