// Shared by the socket and link tests: a server on a free port with the
// real upgrade handler and the Kit's two link routes, a linked made-up Mac
// (tools/fake-mac.mjs makes its key and signs), and a signed-in phone page.
import { createServer, type IncomingMessage, type Server } from 'node:http';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { handleUpgrade } from '../src/lib/hub.ts';
import { createLink, approveLink } from '../src/lib/link.ts';
import { personName } from '../src/lib/macs.ts';
import { createSession, SESSION_COOKIE } from '../src/lib/session.ts';
import { appOrigin, href } from '../src/lib/paths.ts';
import { checkMessage, type Direction } from '../src/lib/contract.ts';
import { POST as linkPost } from '../src/pages/api/mac/link.ts';
import { GET as pollGet } from '../src/pages/api/mac/link/[poll].ts';
import { Conn, loadKey, publicKeyOf, where } from '../tools/fake-mac.mjs';
import { fakeCookies } from './helpers.ts';

export { Conn };
export type At = { origin: string; base: string; http: string; ws: string };

async function body(req: IncomingMessage): Promise<Buffer> {
  const parts: Buffer[] = [];
  for await (const p of req) parts.push(p as Buffer);
  return Buffer.concat(parts);
}

/** The server: the link routes over HTTP, and the sockets. */
export async function startServer(): Promise<{ at: At; server: Server; close: () => Promise<void> }> {
  const server = createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://localhost');
    const headers = Object.fromEntries(Object.entries(req.headers).map(([k, v]) => [k, String(v)]));
    let answer: Response;
    if (req.method === 'POST' && url.pathname === href('/api/mac/link')) {
      const request = new Request(url, { method: 'POST', headers, body: new Uint8Array(await body(req)) });
      answer = await (linkPost as any)({ request, clientAddress: req.socket.remoteAddress });
    } else if (req.method === 'GET' && url.pathname.startsWith(href('/api/mac/link/'))) {
      answer = await (pollGet as any)({ params: { poll: url.pathname.slice(href('/api/mac/link/').length) } });
    } else answer = new Response('not here', { status: 404 });
    res.writeHead(answer.status, Object.fromEntries(answer.headers));
    res.end(Buffer.from(await answer.arrayBuffer()));
  });
  server.on('upgrade', handleUpgrade);
  await new Promise<void>((done) => server.listen(0, '127.0.0.1', done));
  const port = (server.address() as { port: number }).port;
  const at = where(`http://127.0.0.1:${port}${href('/').replace(/\/$/, '')}`) as At;
  return { at, server, close: () => new Promise<void>((done) => { server.closeAllConnections(); server.close(() => done()); }) };
}

const keys = mkdtempSync(join(tmpdir(), 'kit-test-keys-'));
let n = 0;

/** A made-up Mac's key (a new P-256 key and Mac id). */
export function newMac(name = 'MacBook Pro') {
  return loadKey(join(keys, `mac-${++n}.json`), { name });
}

/** A Mac linked to this person through the real link flow. */
export function linkedMac(email: string, name = 'MacBook Pro') {
  const k = newMac(name);
  const out = createLink({ v: 1, mac: k.mac, name, kit: '1.140', key: publicKeyOf(k), kind: 'keychain', hint: null }, '203.0.113.5');
  if (!('answer' in out)) throw new Error(`link refused: ${out.refusal.words}`);
  const page = approveLink(out.answer.link.split('/link/')[1], { email, name: personName(email) });
  if (page.kind !== 'linked') throw new Error(`not linked: ${page.kind}`);
  return k;
}

/** A signed-in phone page's /live socket. */
export async function phone(at: At, email: string, options: { origin?: string; cookie?: string | null } = {}) {
  let cookie = options.cookie;
  if (cookie === undefined) {
    const c = fakeCookies();
    createSession(c, { email, name: personName(email) });
    cookie = `${SESSION_COOKIE}=${c.jar.get(SESSION_COOKIE)}`;
  }
  const headers: Record<string, string> = { origin: options.origin ?? appOrigin() };
  if (cookie) headers.cookie = cookie;
  return Conn.open(`${at.ws}/live`, { headers }) as Promise<any>;
}

/** Every message a socket got matches the contract for its direction. */
export function allValid(conn: { seen: unknown[] }, dir: Direction): string[] {
  return conn.seen.flatMap((m, i) => {
    const c = checkMessage(dir, m);
    return c.ok ? [] : [`#${i}: ${c.why}`];
  });
}

export const sleep = (ms: number) => new Promise((d) => setTimeout(d, ms));
