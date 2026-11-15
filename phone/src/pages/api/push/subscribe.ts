import type { APIRoute } from 'astro';
import { json, readJson } from '../../../lib/json-request.ts';
import { subscribe } from '../../../lib/push.ts';
import { signInId } from '../../../lib/session.ts';

// POST /api/push/subscribe: this phone's push subscription, from a tap on
// Menu > Notices (or from the service worker when the browser renews it,
// with `old`). Answers {on, since} or {words} (lib/push.ts).
export const POST: APIRoute = async ({ request, locals, cookies }) => {
  const r = await readJson(request);
  if (!r.ok) return r.refused;
  const out = subscribe(locals.user!, signInId(cookies), r.body, request.headers.get('user-agent'));
  return out.ok ? json(200, { on: out.on, since: out.since }) : json(out.status, { words: out.words });
};
