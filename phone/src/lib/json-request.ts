// The phone pages' own JSON calls (Menu > Notices, and the service worker
// when the browser renews a subscription): a signed-in page of this site
// posts JSON. The Origin must be this site's (APP_ORIGIN), and a browser on
// another site cannot post JSON here without asking first, which the server
// never allows.
import { isAppOrigin } from './paths.ts';

export const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });

/** The request's JSON body, or the answer that refuses it. */
export async function readJson(request: Request, max = 4096): Promise<{ ok: true; body: unknown } | { ok: false; refused: Response }> {
  if (!isAppOrigin(request.headers.get('origin'))) return { ok: false, refused: json(403, { words: 'This must come from the Claude Kit site.' }) };
  if (!/^application\/json\b/i.test(request.headers.get('content-type') ?? '')) return { ok: false, refused: json(400, { words: 'Send it as JSON.' }) };
  if (Number(request.headers.get('content-length') ?? 0) > max) return { ok: false, refused: json(413, { words: 'That is too large.' }) };
  const text = await request.text();
  if (text.length > max) return { ok: false, refused: json(413, { words: 'That is too large.' }) };
  try {
    return { ok: true, body: JSON.parse(text) };
  } catch {
    return { ok: false, refused: json(400, { words: 'That is not JSON.' }) };
  }
}
