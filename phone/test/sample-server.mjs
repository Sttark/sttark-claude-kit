// The phone pages on made-up data, with the real server: the built app
// (`npm run build`, then server.mjs and its sockets) on a temp database with
// the sample data (test/sample.mjs), and the fake Mac (tools/fake-mac.mjs)
// signed in as MacBook Pro, live, with Mac mini asleep, and a link page
// waiting for Link (sample.mjs, SAMPLE_LINK). Each page is drawn
// from the database, then kept up to date by the real /live, and each action
// goes to the fake Mac and back. Test and local runs only: never deployed,
// never a live server.
//
//   npm run build && node test/sample-server.mjs [--port 4352] [--macs one]
//
// BASE_PATH is the one the build was made with (dist/kit-build.json). Type a
// line to steer it:
//   next <ok|gone|not_now|not_here|bad|timeout|offline>   how the Mac answers the next action
//   mac <pro|mini> <live|asleep|quit|updating|not_heard>   a Mac comes or goes
//   drop                                                   every page loses its socket
// test/walk.mjs and the page check use start() the same way.
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { MACS, SAMPLE_LINK, seed } from './sample.mjs';
import { FakeMac, loadKey, macConnect, publicKeyOf, where } from '../tools/fake-mac.mjs';

const UPGRADE = Symbol.for('sttark.kit.upgrade');
const SHUTDOWN = Symbol.for('sttark.kit.shutdown');
const sleep = (ms) => new Promise((d) => setTimeout(d, ms));

/** One made-up Mac that comes and goes: it signs in, sends its snapshot,
 *  answers, and connects again after a drop while it is meant to be live. */
function macRunner(at, key, mac) {
  let want = false;
  let conn = null;
  async function loop() {
    while (want) {
      try {
        conn = await macConnect(at, key);
        mac.conn = conn;
        const take = () => {
          for (const m of conn.inbox.splice(0)) void mac.onMessage(m);
        };
        conn.ws.on('message', take);
        take();
        mac.sendSnapshot();
        await conn.closedWith(Infinity);
      } catch {
        /* the server refused or is away: try again */
      }
      conn = null;
      if (want) await sleep(300);
    }
  }
  return {
    live() {
      if (want) return;
      want = true;
      void loop();
    },
    /** Goes away: with a bye (sleep, quit, update), or silent (no bye).
     *  Resolves once its socket is closed. */
    async away(why) {
      want = false;
      const c = conn;
      if (!c || c.closed) return;
      if (why) {
        c.send({ event: 'bye', success: true, payload: { why } });
        await sleep(50);
      }
      c.close();
      await c.closedWith(3000).catch(() => {});
      await sleep(100);
    },
    connected: () => !!conn && !conn.closed,
  };
}

/** Starts the built app, its sockets and the fake Macs on `port`. */
export async function start({ port = 4352, email = 'avery.stone@sttark.com', macs = 'two', answerMs = 600 } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'kit-sample-'));
  const file = join(dir, 'kit.db');
  const now = () => Math.floor(Date.now() / 1000);
  await seed(file, email, now(), { macs });
  // Real keys for the two Macs, and no made-up last seen: the fake Mac's own
  // connection says when it was heard from.
  const keys = { pro: loadKey(join(dir, 'pro.json'), { name: 'MacBook Pro' }), mini: loadKey(join(dir, 'mini.json'), { name: 'Mac mini' }) };
  keys.pro.mac = MACS.pro;
  keys.mini.mac = MACS.mini;
  const { db } = await import('../src/lib/db.ts');
  for (const [which, k] of Object.entries(keys)) db().prepare('UPDATE macs SET public_key = ? WHERE id = ?').run(publicKeyOf(k), MACS[which]);
  db().prepare('UPDATE macs SET last_seen = NULL WHERE id = ?').run(MACS.pro);
  // A link page waiting for Link, from another address (it shows the code).
  const studio = loadKey(join(dir, 'studio.json'), { name: SAMPLE_LINK.name, kind: 'secure-enclave' });
  const hash = (t) => createHash('sha256').update(t, 'utf8').digest('hex');
  db()
    .prepare(
      `INSERT INTO links (token_hash, poll_hash, code, mac_id, mac_name, public_key, key_kind, kit_version, address, created_at, expires_at, hint)
       VALUES (?, ?, ?, ?, ?, ?, 'secure-enclave', '1.140', ?, ?, ?, NULL)`,
    )
    .run(hash(SAMPLE_LINK.token), hash(`${SAMPLE_LINK.token}-poll`), SAMPLE_LINK.code, SAMPLE_LINK.mac, SAMPLE_LINK.name, publicKeyOf(studio), SAMPLE_LINK.address, now(), now() + 30 * 60);

  let base = '';
  try {
    base = JSON.parse(readFileSync(fileURLToPath(new URL('../dist/kit-build.json', import.meta.url)), 'utf8')).base ?? '';
  } catch {}
  Object.assign(process.env, { PORT: String(port), HOST: '127.0.0.1', NODE_ENV: 'development', DEV_FAKE_USER: email, KIT_DB: file, APP_ORIGIN: `http://localhost:${port}` });
  await import('../server.mjs');
  // The sockets are up once the app's middleware has loaded (server.mjs
  // asks for /healthz at start).
  for (let i = 0; i < 100 && typeof globalThis[UPGRADE] !== 'function'; i++) await sleep(50);
  const real = globalThis[UPGRADE];
  if (typeof real !== 'function') throw new Error('the server did not start its sockets');

  // Every page's socket, to count them and to drop them; and a switch that
  // refuses new sockets, as a server that is down would.
  let refusing = false;
  const pages = new Set();
  globalThis[UPGRADE] = (req, socket, head) => {
    if (refusing) return socket.end('HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
    if (new URL(req.url ?? '/', 'http://x').pathname === `${base}/live`) {
      pages.add(socket);
      socket.on('close', () => pages.delete(socket));
    }
    real(req, socket, head);
  };

  const at = where(`http://127.0.0.1:${port}${base}`);
  const fakes = {
    pro: new FakeMac({ name: 'MacBook Pro', snapshot: 'fixtures/snapshot.macbook-pro.json', delay: answerMs / 1000 }),
    mini: new FakeMac({ name: 'Mac mini', snapshot: 'fixtures/snapshot.mac-mini-away.json', delay: answerMs / 1000 }),
  };
  const runners = { pro: macRunner(at, keys.pro, fakes.pro), mini: macRunner(at, keys.mini, fakes.mini) };
  runners.pro.live();
  for (let i = 0; i < 100 && !runners.pro.connected(); i++) await sleep(50);

  return {
    url: `http://127.0.0.1:${port}${base}`,
    base,
    /** How the Mac answers the next action: a reason of its own, timeout
     *  (it does not answer; the server says timeout after 20 seconds), or
     *  offline (its socket drops without a bye just before, so it still
     *  shows live, and it comes back a moment later). */
    async next(reason) {
      if (reason === 'offline') {
        await runners.pro.away(null);
        setTimeout(() => runners.pro.live(), 1500);
      } else fakes.pro.once = reason === 'timeout' ? 'silent' : reason;
    },
    /** A Mac comes (live) or goes, as a Kit would: bye sleep, quit or update,
     *  or silence (not_heard, 60 seconds after its last word). */
    async setMac(which, state) {
      const r = runners[which];
      if (!r) return;
      if (state === 'live') r.live();
      else await r.away({ asleep: 'sleep', quit: 'quit', updating: 'update' }[state] ?? null);
    },
    refuse(on) {
      refusing = on;
    },
    /** Drops every page's socket, as a network change would. */
    dropAll() {
      for (const s of pages) s.destroy();
    },
    peers: () => pages.size,
    /** Stops the Macs and closes every socket. */
    async stop() {
      for (const r of Object.values(runners)) r.away('quit');
      await sleep(100);
      globalThis[SHUTDOWN]?.();
    },
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const arg = (k, d) => {
    const i = process.argv.indexOf(k);
    return i >= 0 ? process.argv[i + 1] : d;
  };
  const s = await start({ port: Number(arg('--port', 4352)), macs: arg('--macs', 'two') });
  if (arg('--next')) s.next(arg('--next'));
  console.log(`sample: ${s.url}/ (type: next <reason> | mac <pro|mini> <state> | drop)`);
  createInterface({ input: process.stdin }).on('line', (line) => {
    const [cmd, a, b] = line.trim().split(/\s+/);
    if (cmd === 'next') s.next(a);
    else if (cmd === 'mac') s.setMac(a, b);
    else if (cmd === 'drop') s.dropAll();
  });
}
