import type { APIRoute } from 'astro';
import { json, readJson } from '../../../lib/json-request.ts';
import { setNotices } from '../../../lib/push.ts';

// POST /api/push/notices {endpoint, on}: Menu > Notices on this phone, on or
// off. The person's own subscription only; each change has a record.
export const POST: APIRoute = async ({ request, locals }) => {
  const r = await readJson(request);
  if (!r.ok) return r.refused;
  const { endpoint, on } = (r.body ?? {}) as { endpoint?: unknown; on?: unknown };
  const out = setNotices(locals.user!, endpoint, on);
  return out.ok ? json(200, { on: out.on, since: out.since }) : json(out.status, { words: out.words });
};
