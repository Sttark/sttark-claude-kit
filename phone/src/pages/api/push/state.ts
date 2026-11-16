import type { APIRoute } from 'astro';
import { json, readJson } from '../../../lib/json-request.ts';
import { noticesOf, pushKey } from '../../../lib/push.ts';

// POST /api/push/state {endpoint}: what the server knows of the subscription
// this phone's browser holds: {key, known, on, since}. Read only.
export const POST: APIRoute = async ({ request, locals }) => {
  const r = await readJson(request);
  if (!r.ok) return r.refused;
  const { endpoint } = (r.body ?? {}) as { endpoint?: unknown };
  const mine = typeof endpoint === 'string' ? noticesOf(locals.user!.email, endpoint) : { known: false, on: false, since: null };
  return json(200, { key: pushKey(), ...mine });
};
