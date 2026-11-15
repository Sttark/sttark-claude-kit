import type { APIRoute } from 'astro';
import { db } from '../lib/db.ts';
import { BUILD_SHA } from '../lib/build.ts';

// For the deploy and uptime checks: is the database reachable, and which
// commit is running. Public, so it says nothing else.
export const GET: APIRoute = () => {
  let ok = false;
  try {
    ok = db().prepare('SELECT 1 AS one').get() !== undefined;
  } catch (e) {
    console.error(`[healthz] the database is not reachable: ${(e as Error).message}`);
  }
  return new Response(JSON.stringify({ ok, db: ok, sha: BUILD_SHA }), {
    status: ok ? 200 : 503,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
};
