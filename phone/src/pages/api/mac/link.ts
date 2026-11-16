import type { APIRoute } from 'astro';
import { createLink, type Refusal } from '../../../lib/link.ts';
import { clientAddress } from '../../../lib/net.ts';

// POST /api/mac/link: a Mac's Kit asks to be linked (schema/link.v1.json,
// request and answer). Public: the Kit has no sign-in; the person signs in
// on the link page this answers with.
const MAX_BODY = 8 * 1024;

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
const refuse = (status: number, refusal: Refusal) => json(status, refusal);

export const POST: APIRoute = async (ctx) => {
  const { request } = ctx;
  if (Number(request.headers.get('content-length') ?? 0) > MAX_BODY) return refuse(413, { error: 'too_large', words: 'The link request is over 8 KB.' });
  if (!/^application\/json\b/i.test(request.headers.get('content-type') ?? '')) {
    return refuse(400, { error: 'bad_request', words: 'Send the link request as JSON (Content-Type: application/json).' });
  }
  const text = await request.text();
  if (text.length > MAX_BODY) return refuse(413, { error: 'too_large', words: 'The link request is over 8 KB.' });
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return refuse(400, { error: 'bad_request', words: 'The link request is not JSON.' });
  }
  let socket: string | null = null;
  try {
    socket = ctx.clientAddress;
  } catch {
    socket = null;
  }
  const out = createLink(body, clientAddress(request.headers, socket));
  return 'answer' in out ? json(out.status, out.answer) : refuse(out.status, out.refusal);
};
