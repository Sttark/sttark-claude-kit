import type { APIRoute } from 'astro';
import { json } from '../../../lib/json-request.ts';
import { pushKey } from '../../../lib/push.ts';

// GET /api/push/key: the public key a subscription is made with, for the
// service worker when the browser renews one; null when notices are not set
// up on this server.
export const GET: APIRoute = () => json(200, { key: pushKey() });
