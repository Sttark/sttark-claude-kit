#!/usr/bin/env node
// A made-up Mac for local runs: it links itself with a key file, opens /mac,
// signs the challenge, sends the fixture snapshot (times moved to now), the
// archived list and its Usage by session list when the server asks, answers
// each action, and says bye when it stops. The phone pages are drawn and tried against it, and the
// server's tests use its parts. Never point it at the live server.
//
//   node tools/fake-mac.mjs [options]        (from phone/; npm run fake-mac -- [options])
//
//   --url <address>     the server, with its BASE_PATH (default http://localhost:4350;
//                       http://localhost:4350/kit for a build with BASE_PATH=/kit)
//   --name <name>       the Mac's name (default MacBook Pro)
//   --key <file>        its key file (default data/fake-macs/<name>.json): the P-256
//                       key, the Mac id and who it is linked to. Made on first run.
//   --approve           click Link itself, as the server's DEV_FAKE_USER (local runs
//                       only); without it, open the link page it prints
//   --snapshot <file>   default fixtures/snapshot.macbook-pro.json
//   --archived <file>   default fixtures/archived.json
//   --usage <file>      default fixtures/usage.macbook-pro.json (none: never answers want_usage,
//                       as a Kit from before Usage by session)
//   --answer <how>      how it answers actions: auto (default: as a Kit would, from
//                       its own state), ok, gone, not_now, not_here, bad, cycle (each
//                       of those in turn) or silent (never: the phone gets timeout)
//   --delay <seconds>   wait before each answer (default 1), so Sending... shows
//   --for <seconds>     stay this long, then say bye and stop (default: until Ctrl-C)
//   --bye <why>         sleep, quit (default) or update, said on stopping
//   --no-shift          send the fixtures' times as they are
//
// Two Macs, one away: start one with --name "Mac mini" --snapshot
// fixtures/snapshot.mac-mini-away.json --for 5 --bye sleep.
import { createHash, generateKeyPairSync, createPrivateKey, createPublicKey, randomBytes, sign as cryptoSign } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocket } from 'ws';

const PHONE = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// ---------- the key file ----------

/** The Mac's key file: made with a new P-256 key and Mac id when missing. */
export function loadKey(file, { name = 'MacBook Pro', kind = 'keychain' } = {}) {
  if (existsSync(file)) {
    const k = JSON.parse(readFileSync(file, 'utf8'));
    return { ...k, file, privateKey: createPrivateKey(k.private_key) };
  }
  const { privateKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
  const k = {
    v: 1, mac: `mac_${randomBytes(9).toString('base64url')}`, name, kind,
    private_key: privateKey.export({ format: 'pem', type: 'pkcs8' }).toString(), linked_to: null,
  };
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(k, null, 2) + '\n', { mode: 0o600 });
  return { ...k, file, privateKey };
}

export function saveKey(k) {
  const { file, privateKey: _p, ...rest } = k;
  writeFileSync(file, JSON.stringify(rest, null, 2) + '\n', { mode: 0o600 });
}

/** The public half as the link request sends it: SPKI, DER, base64. */
export const publicKeyOf = (k) => createPublicKey(k.privateKey).export({ format: 'der', type: 'spki' }).toString('base64');

/** The signature auth carries: ECDSA P-256 with SHA-256 over
 *  "kit-mac-v1\n<mac id>\n<nonce>", DER, base64 (what SecKeyCreateSignature
 *  gives). raw: the 64-byte r and s instead (CryptoKit's rawRepresentation). */
export function signChallenge(k, nonce, { raw = false } = {}) {
  const data = Buffer.from(`kit-mac-v1\n${k.mac}\n${nonce}`, 'utf8');
  return cryptoSign('sha256', data, { key: k.privateKey, dsaEncoding: raw ? 'ieee-p1363' : 'der' }).toString('base64');
}

// ---------- the server's address ----------

/** origin, base, and the addresses under it, from --url. */
export function where(url) {
  const u = new URL(url);
  const base = u.pathname.replace(/\/+$/, '');
  const http = `${u.origin}${base}`;
  return { origin: u.origin, base, http, ws: http.replace(/^http/, 'ws') };
}

// ---------- linking ----------

/** Asks to link (schema/link.v1.json, request); answers the link page, the
 *  poll token and the code.
 *  @param {{ hint?: string | null, kit?: string }} [options] */
export async function requestLink(at, k, options = {}) {
  const { hint = null, kit = '1.140' } = options;
  const r = await fetch(`${at.http}/api/mac/link`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ v: 1, mac: k.mac, name: k.name, kit, key: publicKeyOf(k), kind: k.kind, hint }),
  });
  const body = await r.json();
  if (r.status !== 201) throw new Error(`link request refused (${r.status}): ${body.words ?? JSON.stringify(body)}`);
  return body;
}

/** Clicks Link as the server's DEV_FAKE_USER (a local run signs everyone in
 *  as that person). */
export async function approveLink(at, link) {
  const r = await fetch(link, { method: 'POST', redirect: 'manual', headers: { origin: at.origin, 'content-type': 'application/x-www-form-urlencoded' }, body: 'link=1' });
  return r.status === 303;
}

export async function pollLink(at, poll) {
  const r = await fetch(`${at.http}/api/mac/link/${poll}`);
  return r.json();
}

// ---------- a socket with an inbox ----------

/** A WebSocket whose messages wait in an inbox until a test or the fake Mac
 *  takes them. */
export class Conn {
  static open(url, options = {}) {
    return new Promise((done, fail) => {
      const ws = new WebSocket(url, options);
      const c = new Conn(ws);
      ws.once('open', () => done(c));
      ws.once('unexpected-response', (_req, res) => fail(Object.assign(new Error(`HTTP ${res.statusCode}`), { status: res.statusCode })));
      ws.once('error', (e) => fail(e));
    });
  }

  constructor(ws) {
    this.ws = ws;
    this.inbox = [];
    /** Every message received, taken or not. */
    this.seen = [];
    this.waiters = [];
    this.closed = null;
    ws.on('message', (data) => {
      let msg;
      try {
        msg = JSON.parse(String(data));
      } catch {
        return;
      }
      this.seen.push(msg);
      this.inbox.push(msg);
      this.wake();
    });
    ws.on('close', (code, reason) => {
      this.closed = { code, reason: String(reason) };
      this.wake();
    });
    ws.on('error', () => {});
  }

  wake() {
    for (const w of [...this.waiters]) w();
  }

  send(msg) {
    this.ws.send(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }

  /** The first message with this event (any event when left out). */
  next(event, ms = 3000) {
    return new Promise((done, fail) => {
      const look = () => {
        const i = this.inbox.findIndex((m) => !event || m.event === event);
        if (i >= 0) {
          finish();
          done(this.inbox.splice(i, 1)[0]);
        } else if (this.closed) {
          finish();
          fail(new Error(`closed ${this.closed.code} (${this.closed.reason}) while waiting for ${event ?? 'a message'}`));
        }
      };
      const finish = () => {
        clearTimeout(t);
        this.waiters = this.waiters.filter((w) => w !== look);
      };
      const t = setTimeout(() => {
        finish();
        fail(new Error(`no ${event ?? 'message'} in ${ms} ms (inbox: ${this.inbox.map((m) => m.event).join(', ') || 'empty'})`));
      }, ms);
      this.waiters.push(look);
      look();
    });
  }

  /** Resolves with {code, reason} once the socket is closed (ms Infinity:
   *  however long it takes). */
  closedWith(ms = 3000) {
    return new Promise((done, fail) => {
      const look = () => {
        if (!this.closed) return;
        clearTimeout(t);
        this.waiters = this.waiters.filter((w) => w !== look);
        done(this.closed);
      };
      const t = Number.isFinite(ms) ? setTimeout(() => fail(new Error(`still open after ${ms} ms`)), ms) : undefined;
      this.waiters.push(look);
      look();
    });
  }

  close() {
    this.ws.close();
  }
}

/** Opens /mac and signs in: challenge, auth, welcome. */
export async function macConnect(at, k, { kit = '1.140', raw = false } = {}) {
  const c = await Conn.open(`${at.ws}/mac`);
  const { payload } = await c.next('challenge');
  c.send({ event: 'auth', success: true, payload: { mac: k.mac, sig: signChallenge(k, payload.nonce, { raw }), kit } });
  c.welcome = (await c.next('welcome')).payload;
  return c;
}

// ---------- what the made-up Mac holds ----------

const read = (file) => JSON.parse(readFileSync(resolve(PHONE, file), 'utf8'));

/** Moves every Unix time (a number of 1700000000 or more) by delta seconds.
 *  Percentages and counts are never that large. */
export function shiftTimes(v, delta) {
  if (Array.isArray(v)) return v.map((x) => shiftTimes(x, delta));
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, shiftTimes(x, delta)]));
  return typeof v === 'number' && v >= 1_700_000_000 ? v + delta : v;
}

export const revOf = (items) => createHash('sha256').update(JSON.stringify(items)).digest('hex').slice(0, 16);

const LEVEL = { low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra', max: 'Max' };
const W = {
  waitGone: 'That wait already ended. Nothing was changed.',
  sessionGone: 'This session is no longer on your Mac. It may be archived. Nothing was changed.',
  waiting: 'It does not run while it waits. Set the effort when it comes back.',
  notArchived: 'It is not archived now. It is in your list.',
  notHere: 'Its conversation is not on this Mac, so this Mac cannot bring it back.',
  bad: 'This change is not possible for this session. Nothing was changed.',
};
const REASONS = ['ok', 'gone', 'not_now', 'not_here', 'bad'];

/** The made-up Mac: its snapshot and archived list, and how it answers. */
export class FakeMac {
  constructor({ name = 'MacBook Pro', snapshot = 'fixtures/snapshot.macbook-pro.json', archived = 'fixtures/archived.json', usage = 'fixtures/usage.macbook-pro.json', shift = true, answer = 'auto', delay = 1, log = () => {} } = {}) {
    const snap = read(snapshot);
    const delta = shift ? Math.floor(Date.now() / 1000) - snap.at : 0;
    this.snap = shiftTimes(snap, delta);
    this.snap.mac.name = name;
    this.archived = shiftTimes(read(archived).items, delta);
    this.usage = usage && usage !== 'none' ? shiftTimes(read(usage), delta) : null;
    if (this.usage) this.usage.total.tokens = read(usage).total.tokens;   // a count, not a time
    this.history = new Map([[revOf(this.archived), this.archived]]);
    this.serverHas = null;
    this.answer = answer;
    /** How it answers the next action only, then as `answer` says. */
    this.once = null;
    this.turn = 0;
    this.delay = delay;
    this.log = log;
    this.conn = null;
  }

  snapshot() {
    const now = Math.floor(Date.now() / 1000);
    return { ...this.snap, at: Math.max(now, this.snap.at), archived_rev: revOf(this.archived), archived_count: this.archived.length };
  }

  sendSnapshot() {
    this.conn?.send({ event: 'snapshot', success: true, payload: this.snapshot() });
  }

  /** Sends remind for its first session that needs the person, as a Kit
   *  does when one has waited 10 minutes and the person is away from the Mac
   *  (phone/DESIGN.md section 5). What it sent, or null. */
  remind() {
    const row = this.snap.rows.find((r) => r.group === 'needs_you');
    if (!row || !this.conn) return null;
    const payload = { cse: row.cse, waiting_since: row.session?.waiting_since ?? row.time_at, title: row.title, why: row.session?.why ?? null };
    this.conn.send({ event: 'remind', success: true, payload });
    return payload;
  }

  /** Changes the archived list, and sends the change if the server holds
   *  the list it starts from. */
  setArchived(items) {
    const base = revOf(this.archived);
    const rev = revOf(items);
    const before = new Map(this.archived.map((i) => [i.cse, i]));
    const after = new Map(items.map((i) => [i.cse, i]));
    this.archived = items;
    this.history.set(rev, items);
    if (this.serverHas === base) {
      const add = items.filter((i) => JSON.stringify(before.get(i.cse)) !== JSON.stringify(i));
      const remove = [...before.keys()].filter((c) => !after.has(c));
      this.conn?.send({ event: 'archived_delta', success: true, payload: { v: 1, base, rev, add, remove } });
      this.serverHas = rev;
    }
  }

  onWantArchived(have) {
    const rev = revOf(this.archived);
    const from = have && have !== rev ? this.history.get(have) : null;
    if (from) {
      const was = new Map(from.map((i) => [i.cse, i]));
      const now = new Set(this.archived.map((i) => i.cse));
      const add = this.archived.filter((i) => JSON.stringify(was.get(i.cse)) !== JSON.stringify(i));
      const remove = [...was.keys()].filter((c) => !now.has(c));
      this.conn?.send({ event: 'archived_delta', success: true, payload: { v: 1, base: have, rev, add, remove } });
    } else {
      this.conn?.send({ event: 'archived', success: true, payload: { v: 1, rev, items: this.archived } });
    }
    this.serverHas = rev;
  }

  /** Its Usage by session list for a period (schema/usage.v1.json): the
   *  fixture's sessions, with the days the period covers. Today has fewer
   *  sessions, each share made up again so they add to 100. */
  usageList(period) {
    const now = Math.floor(Date.now() / 1000);
    const day = (t) => new Date(t * 1000).toISOString().slice(0, 10);
    const back = { today: 0, '7d': 6, '30d': 29 }[period];
    const [from, to] = back === undefined ? period.split('..') : [day(now - back * 86400), day(now)];
    let rows = structuredClone(this.usage.rows);
    if (period === 'today' || back === undefined) {
      rows = rows.slice(0, period === 'today' ? 6 : 10);
      const sum = rows.reduce((a, r) => a + r.share, 0);
      for (const r of rows) {
        const k = 100 / sum;
        r.agent_share = Math.round(r.agent_share * k * 10) / 10;
        r.share = Math.round(r.share * k * 10) / 10;
        r.agent_share = Math.min(r.share, r.agent_share);
      }
    }
    const agents = Math.round(rows.reduce((a, r) => a + r.agent_share, 0) * 10) / 10;
    const total = { ...this.usage.total, sessions: rows.length, agent_share: Math.min(100, agents) };
    // The fixture's human work is for 7 days: each period gets its part of it.
    if (total.human_hours !== undefined) {
      const k = (Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1) / 7;
      for (const r of rows) if (r.human_hours !== undefined) r.human_hours = Math.round(r.human_hours * k * 10) / 10;
      total.human_hours = Math.round(rows.reduce((a, r) => a + (r.human_hours ?? 0), 0) * 10) / 10;
    }
    return { ...this.usage, period, from, to, at: now, rows, total };
  }

  onWantUsage(period) {
    if (!this.usage) return this.log(`server wants the usage list for ${period}: not sending it (--usage none)`);
    this.log(`server wants the usage list for ${period}`);
    this.conn?.send({ event: 'usage', success: true, payload: this.usageList(period) });
  }

  /** The result for one action, and the change it makes to this Mac. */
  decide(act, args) {
    const rows = this.snap.rows;
    const byCse = (cse) => rows.find((r) => r.cse === cse);
    const byWaits = (ids) => rows.filter((r) => r.waits.some((w) => ids.includes(w.id)));
    const now = Math.floor(Date.now() / 1000);
    const out = (reason, words, before = null, after = null, change = null) => ({ reason, words, before, after, change });
    switch (act) {
      case 'bring_back':
      case 'stop_waits': {
        const ids = act === 'bring_back' ? [args.wait] : args.waits;
        const hit = byWaits(ids);
        if (!hit.length) return out('gone', W.waitGone);
        const row = hit[0];
        const before = { waits: row.waits.map((w) => w.id) };
        const left = row.waits.filter((w) => !ids.includes(w.id));
        const after = { waits: left.map((w) => w.id) };
        const words = act === 'bring_back' ? 'It is back in your list.' : `${ids.length === 1 ? 'Stopped waiting.' : `Stopped ${ids.length} waits.`} The session stays where it is.`;
        return out('ok', words, before, after, () => {
          row.waits = left;
          if (act === 'bring_back' || !left.length) {
            Object.assign(row, { group: 'working', time_at: now, late: false });
            if (row.session) row.session.turn_at = now;
            if (act === 'stop_waits') this.snap.rows = rows.filter((r) => r !== row);
          }
        });
      }
      case 'set_level':
      case 'set_auto': {
        const row = byCse(args.cse);
        if (!row?.session) return out('gone', W.sessionGone);
        if (row.group === 'waiting') return out('not_now', W.waiting);
        const s = row.session;
        if (act === 'set_level') {
          return out('ok', `Effort is ${LEVEL[args.level]} now. Auto is off for this session.`, { level: s.level, manual: s.manual }, { level: args.level, manual: true }, () => {
            Object.assign(s, { level: args.level, manual: true });
            Object.assign(row, { sub: 'Manual: you set the effort', sub_strong: LEVEL[args.level] });
          });
        }
        const words = args.on ? 'Auto is on. Claude sets the effort for each task.' : `Auto is off. The effort stays at ${LEVEL[s.level] ?? 'its level'}.`;
        return out('ok', words, { manual: s.manual }, { manual: !args.on }, () => {
          s.manual = !args.on;
          row.sub = args.on ? 'Auto: Claude sets the effort' : 'Manual: you set the effort';
        });
      }
      case 'set_limit': {
        const row = byCse(args.cse);
        if (!row) return out('gone', W.sessionGone);
        if (args.mode === 'hold' && !args.at) return out('bad', W.bad);
        const mode = { mode: args.mode, at: args.mode === 'hold' ? args.at : null };
        const words = { follow: 'It uses the usage limit setting in Settings now.', credits: 'It always uses usage credits at the limit now.', hold: `It never uses usage credits now. It holds at ${args.at}%.` }[args.mode];
        return out('ok', words, { limit_mode: row.limit_mode }, { limit_mode: mode }, () => {
          row.limit_mode = mode;
        });
      }
      case 'set_alerts': {
        const row = byCse(args.cse);
        if (!row) return out('gone', W.sessionGone);
        const words = args.alerts
          ? 'Alerts are on. This session reaches you the ways set in Reach me by.'
          : 'Alerts are off. Nothing about this session goes out. Its messages stay in the Kit app.';
        return out('ok', words, { alerts: row.alerts !== false }, { alerts: args.alerts }, () => {
          row.alerts = args.alerts;
        });
      }
      case 'unarchive': {
        const item = this.archived.find((i) => i.cse === args.cse);
        if (!item) return byCse(args.cse) ? out('gone', W.notArchived) : out('not_here', W.notHere);
        return out('ok', 'It is back in your list.', { archived: true }, { archived: false }, () => {
          this.setArchived(this.archived.filter((i) => i !== item));
          rows.push({
            id: item.cse, cse: item.cse, sid: null, group: 'working', title: item.title, sub: 'Brought back from the archive',
            sub_strong: null, sub_warn: null, late: false, time_at: now, url: item.url,
            session: { level: 'medium', manual: false, reason: null, needs_you: false, why: null, waiting_since: null, turn_at: now },
            background: null, waits: [], hold: null, limit_mode: { mode: 'follow', at: null }, alerts: false, // no choice: off
          });
        });
      }
      default:
        return out('bad', W.bad);
    }
  }

  /** How this Mac answers one action: from its own state (auto), or with a
   *  reason the run asked for. */
  respond(act, args) {
    const how = this.once ?? (this.answer === 'cycle' ? REASONS[this.turn++ % REASONS.length] : this.answer);
    this.once = null;
    if (how === 'silent') return null;
    const auto = this.decide(act, args);
    if (how === 'auto' || how === auto.reason) return auto;
    if (how === 'ok') return { ...auto, reason: 'ok', words: auto.reason === 'ok' ? auto.words : 'Done.', change: auto.reason === 'ok' ? auto.change : null };
    const words = {
      gone: act === 'unarchive' ? W.notArchived : act === 'bring_back' || act === 'stop_waits' ? W.waitGone : W.sessionGone,
      not_now: act === 'bring_back' ? 'The Kit cannot bring it back now. Try again in a minute.' : act === 'unarchive' ? 'It did not come back.' : W.waiting,
      not_here: W.notHere,
      bad: W.bad,
    }[how];
    return { reason: how, words, before: null, after: null, change: null };
  }

  /** Takes one server message. */
  async onMessage(msg) {
    switch (msg.event) {
      case 'want_archived':
        this.log(`server wants the archived list (it has ${msg.payload.have ?? 'none'})`);
        return this.onWantArchived(msg.payload.have);
      case 'want_usage':
        return this.onWantUsage(msg.payload.period);
      case 'watching':
        return this.log(`watching: ${msg.payload.on ? 'a phone page is open' : 'no phone page is open'}`);
      case 'action': {
        const { id, act, args, by } = msg.payload;
        this.log(`action ${act} ${JSON.stringify(args)} from ${by.name}`);
        const r = this.respond(act, args);
        if (!r) return this.log('not answering it (--answer silent)');
        if (this.delay) await new Promise((d) => setTimeout(d, this.delay * 1000));
        this.conn?.send({ event: 'result', success: r.reason === 'ok', payload: { id, reason: r.reason, words: r.words, before: r.before, after: r.after } });
        this.log(`answered ${r.reason}: ${r.words}`);
        if (r.change) {
          r.change();
          this.sendSnapshot();
        }
        return;
      }
      case 'error':
        return this.log(`server error ${msg.payload.code}: ${msg.payload.words}`);
    }
  }
}

// ---------- the command ----------

function args(argv) {
  const o = { url: 'http://localhost:4350', name: 'MacBook Pro', snapshot: 'fixtures/snapshot.macbook-pro.json', archived: 'fixtures/archived.json', usage: 'fixtures/usage.macbook-pro.json', answer: 'auto', delay: 1, bye: 'quit', shift: true, approve: false };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = () => argv[++i];
    if (k === '--url') o.url = v();
    else if (k === '--name') o.name = v();
    else if (k === '--key') o.key = v();
    else if (k === '--snapshot') o.snapshot = v();
    else if (k === '--archived') o.archived = v();
    else if (k === '--usage') o.usage = v();
    else if (k === '--answer') o.answer = v();
    else if (k === '--delay') o.delay = Number(v());
    else if (k === '--for') o.for = Number(v());
    else if (k === '--bye') o.bye = v();
    else if (k === '--approve') o.approve = true;
    else if (k === '--no-shift') o.shift = false;
    else if (k === '-h' || k === '--help') o.help = true;
    else throw new Error(`unknown option ${k} (--help says which there are)`);
  }
  if (!['auto', 'silent', 'cycle', ...REASONS].includes(o.answer)) throw new Error(`--answer ${o.answer}: auto, ok, gone, not_now, not_here, bad, cycle or silent`);
  if (!['sleep', 'quit', 'update'].includes(o.bye)) throw new Error(`--bye ${o.bye}: sleep, quit or update`);
  o.key ??= join(PHONE, 'data', 'fake-macs', `${o.name.replace(/[^A-Za-z0-9]+/g, '-').toLowerCase()}.json`);
  return o;
}

async function main() {
  const o = args(process.argv.slice(2));
  if (o.help) {
    console.log(readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(1, 30).map((l) => l.replace(/^\/\/ ?/, '')).join('\n'));
    return;
  }
  const say = (s) => console.log(`[fake-mac ${o.name}] ${s}`);
  const at = where(o.url);
  const health = await fetch(`${at.http}/healthz`).catch(() => null);
  if (!health?.ok) throw new Error(`no server at ${at.http} (start it with npm run dev)`);
  const k = loadKey(o.key, { name: o.name });
  if (!k.linked_to) {
    const a = await requestLink(at, k);
    say(`link page: ${a.link}`);
    say(`code: ${a.code} (the page shows it when the browser is not on this Mac's address)`);
    if (o.approve) say((await approveLink(at, a.link)) ? 'clicked Link as the server\'s DEV_FAKE_USER' : 'could not click Link (is DEV_FAKE_USER set on the server?)');
    else say('open the link page, sign in and click Link; waiting...');
    for (;;) {
      const p = await pollLink(at, a.poll);
      if (p.status === 'linked') {
        k.linked_to = p.email;
        saveKey(k);
        say(`linked to ${p.email}`);
        break;
      }
      if (p.status !== 'waiting') throw new Error(`the link page ${p.status}; run again for a new one`);
      await new Promise((d) => setTimeout(d, 2000));
    }
  }
  const mac = new FakeMac({ ...o, log: say });
  let stopping = false;
  let wait = 1000;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    if (mac.conn && !mac.conn.closed) {
      mac.conn.send({ event: 'bye', success: true, payload: { why: o.bye } });
      say(`bye: ${o.bye}`);
      await new Promise((d) => setTimeout(d, 300));
      mac.conn.close();
    }
    process.exit(0);
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  if (o.for) setTimeout(stop, o.for * 1000);
  for (;;) {
    try {
      const c = await macConnect(at, k);
      wait = 1000;
      mac.conn = c;
      say(`connected (${c.welcome.phones} phones get notices; ${c.welcome.watching ? 'a phone page is open' : 'no phone page is open'})`);
      mac.sendSnapshot();
      const ping = setInterval(() => c.ws.ping(), 25_000);
      c.ws.on('message', () => {
        for (const m of c.inbox.splice(0)) void mac.onMessage(m);
      });
      for (const m of c.inbox.splice(0)) void mac.onMessage(m);
      const { code, reason } = await c.closedWith(Infinity);
      clearInterval(ping);
      if (stopping) return;
      say(`closed ${code}${reason ? `: ${reason}` : ''}`);
      if (code === 4401 || code === 4403) {
        rmSync(k.file, { force: true });
        say('removed from the phone: the key is dropped. Run again to link it again.');
        process.exit(1);
      }
    } catch (e) {
      if (stopping) return;
      say(`could not connect: ${e.message}`);
    }
    await new Promise((d) => setTimeout(d, wait));
    wait = Math.min(wait * 2, 60_000);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => {
    console.error(`fake-mac: ${e.message}`);
    process.exit(1);
  });
}
