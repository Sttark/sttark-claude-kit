// The two WebSockets (asyncapi.yaml, phone/DESIGN.md sections 4 to 6 and
// 13): /mac, the socket each linked Mac's Kit opens and keeps, and /live,
// the socket each open phone page holds. server.mjs (and astro.config.mjs's
// dev hook) passes every upgrade here through lib/upgrade.ts.
//
// /mac: challenge, then the Mac's auth (a P-256 signature with the key saved
// at linking, lib/keys.ts), then welcome. Closes: 4400 no valid auth in
// time, 4401 an unknown or removed Mac or a wrong signature, 4403 its person
// is off the roster, 4409 a newer connection of the same Mac took over, 1000
// after unlink, 1012 a server restart. Every message is checked against the
// contract first (lib/contract.ts); one that fails gets error bad_message
// and changes nothing.
//
// /live: a signed-in phone page (the sign-in cookie, Origin APP_ORIGIN). It
// gets the person's Macs, each Mac's last snapshot, each new one at once,
// and the archived lists it asks for. Its actions go to the Mac with who
// asked, never kept for later: a Mac that is not live answers offline at
// once, and no answer in 20 seconds is timeout. Each outcome is one record
// (lib/records.ts) with before and after.
//
// What is in memory only: the open sockets, which phone pages are visible,
// and the actions waiting for an answer (lib/macs.ts keeps presence).
import type { IncomingMessage } from 'node:http';
import type { Duplex } from 'node:stream';
import { randomBytes } from 'node:crypto';
import { WebSocketServer, WebSocket, type RawData } from 'ws';
import { db } from './db.ts';
import { addRecord } from './records.ts';
import { events } from './events.ts';
import { checkMessage, type Direction, type Message } from './contract.ts';
import { newNonce, verifyMacSignature } from './keys.ts';
import { href, isAppOrigin } from './paths.ts';
import { onRoster } from './roster.ts';
import { devUser, sessionFromCookieHeader, sessionStillValid } from './session.ts';
import { onUpgrade } from './upgrade.ts';
import {
  type ArchivedItem, type MacRow, archivedOf, clearBye, getMac, heard, lastSnapshot, macView, macsOf, personName,
  removeMac, saveArchived, saveSnapshot, setBye, setConnected,
} from './macs.ts';

/** Timings, here so the tests can make them short. */
export const settings = {
  /** No result from the Mac in this long: timeout (phone/DESIGN.md section 4). */
  actionTimeoutMs: 20_000,
  /** A new /mac socket must authenticate in this long. */
  authTimeoutMs: 15_000,
  /** The server pings each socket this often (the Mac pings too). */
  pingEveryMs: 25_000,
  /** A socket that sends nothing (not even a pong) this long is dropped. */
  silenceMs: 60_000,
  /** How often the server looks at every socket and Mac state. */
  sweepEveryMs: 5_000,
  /** At most one want_archived per Mac in this long. */
  wantEveryMs: 10_000,
  /** A result that comes after its timeout is still recorded, this long. */
  lateKeepMs: 10 * 60_000,
};

const MAX_MAC_MESSAGE = 1 << 20;
const MAX_PHONE_MESSAGE = 64 << 10;
const MAX_PHONE_SOCKETS = 12;
const nowS = () => Math.floor(Date.now() / 1000);
const cut = (s: string | null | undefined, n: number) => [...String(s ?? '')].slice(0, n).join('');

export const WORDS = {
  bad: 'The server did not understand that message.',
  tooFast: 'Too many messages in a short time. The server skipped some.',
  denied: 'That Mac is not linked to your account. Nothing was sent.',
  timeout: 'Your Mac did not answer in time. Check the session before you try again.',
};
const LEVEL: Record<string, string> = { low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra', max: 'Max' };

type Bucket = { tokens: number; last: number; cap: number; perS: number; warned: number };
const bucket = (cap: number, perS: number): Bucket => ({ tokens: cap, last: Date.now(), cap, perS, warned: 0 });
function take(b: Bucket): boolean {
  const t = Date.now();
  b.tokens = Math.min(b.cap, b.tokens + ((t - b.last) / 1000) * b.perS);
  b.last = t;
  if (b.tokens < 1) return false;
  b.tokens -= 1;
  return true;
}

type Sock = { ws: WebSocket; lastFrame: number; lastPing: number; bucket: Bucket };
type MacSock = Sock & {
  kind: 'mac'; nonce: string; authed: boolean; id: string; email: string; name: string;
  authTimer?: ReturnType<typeof setTimeout>; wantAt: number; watching: boolean | null; bye: boolean; closing: number | null;
};
type PhoneSock = Sock & { kind: 'phone'; email: string; name: string; session: string | null; visible: boolean; archived: boolean };
type Asked = {
  id: string; macId: string; macName: string; email: string; name: string; phone: PhoneSock | null; phoneId: string;
  act: string; args: any; cse: string | null; title: string | null;
};
type Pending = Asked & { timer: ReturnType<typeof setTimeout> };
type Late = Asked & { until: number };

type HubState = {
  macs: Map<string, MacSock>;
  unauthed: Set<MacSock>;
  phones: Set<PhoneSock>;
  pending: Map<string, Pending>;
  late: Map<string, Late>;
  shown: Map<string, string>;
  sweep: ReturnType<typeof setInterval> | null;
  listening: boolean;
};
const STATE = Symbol.for('sttark.kit.hub');
const H: HubState = ((globalThis as Record<symbol, unknown>)[STATE] ??= {
  macs: new Map(), unauthed: new Set(), phones: new Set(), pending: new Map(), late: new Map(), shown: new Map(), sweep: null, listening: false,
} satisfies HubState) as HubState;

const wss = new WebSocketServer({ noServer: true, maxPayload: MAX_MAC_MESSAGE, perMessageDeflate: false, clientTracking: false });

// ---------- sending ----------

/** Sends one message, after checking it against the contract: the server
 *  never sends what the contract does not allow. */
function send(ws: WebSocket, dir: Direction, msg: Message): boolean {
  const c = checkMessage(dir, msg);
  if (!c.ok) {
    console.error(`[hub] ALERT: not sending a ${dir} message the contract does not allow: ${c.why}`);
    return false;
  }
  if (ws.readyState !== WebSocket.OPEN) return false;
  ws.send(JSON.stringify(msg));
  return true;
}

function close(ws: WebSocket, code: number, reason: string): void {
  try {
    ws.close(code, reason.slice(0, 120));
  } catch {
    ws.terminate();
  }
}

function refuse(socket: Duplex, status: number, text: string): void {
  socket.write(`HTTP/1.1 ${status} ${text}\r\nConnection: close\r\nContent-Type: text/plain\r\nContent-Length: ${text.length}\r\n\r\n${text}`);
  socket.destroy();
}

const phonesOf = (email: string) => [...H.phones].filter((p) => p.email === email);
const macSocksOf = (email: string) => [...H.macs.values()].filter((m) => m.email === email);

function toPhones(email: string, msg: Message, only?: (p: PhoneSock) => boolean): void {
  for (const p of phonesOf(email)) if (!only || only(p)) send(p.ws, 'server_to_phone', msg);
}

/** On the roster as last read, or the made-up person of a local run. */
function allowed(email: string): boolean {
  return onRoster(email) || devUser()?.email === email;
}

// ---------- the person's Macs, for the phone ----------

function macsMessage(email: string): Message {
  const macs = macsOf(email).map((m) => ({ id: m.id, name: cut(m.name, 80), state: m.state, last_seen: m.lastSeen, kit: m.kit && /^[0-9]+(\.[0-9]+)*$/.test(m.kit) ? m.kit : '0' }));
  return { event: 'macs', success: true, payload: { macs } };
}

/** Sends the person's Macs to their phones when a state, name or version
 *  changed since the last time (not for last seen alone). */
function showMacs(email: string, force = false): void {
  const msg = macsMessage(email);
  const key = JSON.stringify(msg.payload.macs.map((m: any) => [m.id, m.name, m.state, m.kit]));
  if (!force && H.shown.get(email) === key) return;
  H.shown.set(email, key);
  toPhones(email, msg);
}

function watchingOf(email: string): boolean {
  return phonesOf(email).some((p) => p.visible);
}

/** Tells the person's Macs whether one of their phone pages is visible. */
function updateWatching(email: string): void {
  const on = watchingOf(email);
  for (const m of macSocksOf(email)) {
    if (m.watching === on) continue;
    m.watching = on;
    send(m.ws, 'server_to_mac', { event: 'watching', success: true, payload: { on } });
  }
}

function pushPhones(email: string): number {
  const n = (db().prepare('SELECT count(*) AS n FROM push_subs WHERE email = ? AND notices = 1').get(email) as { n: number }).n;
  return Math.min(50, n);
}

// ---------- archived lists ----------

const newestFirst = (items: ArchivedItem[]) =>
  items.map((it, i) => ({ it, i })).sort((a, b) => (b.it.archived_at ?? -Infinity) - (a.it.archived_at ?? -Infinity) || a.i - b.i).map((x) => x.it);

function askArchived(m: MacSock, have: string | null): void {
  if (Date.now() - m.wantAt < settings.wantEveryMs) return;
  m.wantAt = Date.now();
  send(m.ws, 'server_to_mac', { event: 'want_archived', success: true, payload: { have } });
}

function archivedMessage(macId: string): Message | null {
  const a = archivedOf(macId);
  return a ? { event: 'archived', success: true, payload: { mac: macId, rev: a.rev, items: a.items } } : null;
}

/** A phone opened Archived: each Mac's list from the server's copy, and a
 *  want_archived to each live Mac whose copy is older than its snapshot's
 *  archived_rev. */
function openArchived(p: PhoneSock): void {
  p.archived = true;
  for (const mac of macsOf(p.email)) {
    const msg = archivedMessage(mac.id);
    if (msg) send(p.ws, 'server_to_phone', msg);
    const live = H.macs.get(mac.id);
    const want = lastSnapshot(mac.id)?.archived_rev ?? null;
    const have = archivedOf(mac.id)?.rev ?? null;
    if (live && want && want !== have) askArchived(live, have);
  }
}

// ---------- /mac ----------

function frame(s: Sock): void {
  s.lastFrame = Date.now();
  if ((s as MacSock).kind === 'mac' && (s as MacSock).authed) heard((s as MacSock).id);
}

function badMessage(s: MacSock | PhoneSock, why: string): void {
  console.warn(`[hub] ${s.kind === 'mac' ? `Mac ${s.authed ? s.id : '(not signed in)'}` : `phone of ${s.email}`}: bad message: ${why}`);
  send(s.ws, s.kind === 'mac' ? 'server_to_mac' : 'server_to_phone', { event: 'error', success: false, payload: { code: 'bad_message', words: WORDS.bad } });
}

function tooFast(s: MacSock | PhoneSock): void {
  if (Date.now() - s.bucket.warned < 10_000) return;
  s.bucket.warned = Date.now();
  send(s.ws, s.kind === 'mac' ? 'server_to_mac' : 'server_to_phone', { event: 'error', success: false, payload: { code: 'too_fast', words: WORDS.tooFast } });
}

function parse(data: RawData, isBinary: boolean, max: number): unknown {
  if (isBinary) return undefined;
  const buf = Buffer.isBuffer(data) ? data : Array.isArray(data) ? Buffer.concat(data) : Buffer.from(data);
  const text = buf.toString('utf8');
  if (text.length > max) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function acceptMac(req: IncomingMessage, socket: Duplex, head: Buffer): void {
  wss.handleUpgrade(req, socket, head, (ws) => {
    const m: MacSock = {
      kind: 'mac', ws, nonce: newNonce(), authed: false, id: '', email: '', name: '', wantAt: 0, watching: null, bye: false, closing: null,
      lastFrame: Date.now(), lastPing: Date.now(), bucket: bucket(30, 1),
    };
    H.unauthed.add(m);
    ws.on('message', (data, isBinary) => onMacMessage(m, data, isBinary));
    ws.on('ping', () => frame(m));
    ws.on('pong', () => frame(m));
    ws.on('close', () => onMacClose(m));
    ws.on('error', (e) => console.warn(`[hub] Mac socket error: ${e.message}`));
    m.authTimer = setTimeout(() => {
      if (!m.authed) close(ws, 4400, 'no valid auth in time');
    }, settings.authTimeoutMs);
    send(ws, 'server_to_mac', { event: 'challenge', success: true, payload: { nonce: m.nonce } });
  });
}

function onAuth(m: MacSock, value: unknown): void {
  const c = checkMessage('mac_to_server', value);
  if (!c.ok || c.message.event !== 'auth') return close(m.ws, 4400, 'the first message must be auth');
  const { mac: id, sig, kit } = c.message.payload as { mac: string; sig: string; kit: string };
  const row = getMac(id);
  if (!row) return close(m.ws, 4401, 'this Mac is not linked');
  if (!verifyMacSignature(row.publicKey, id, m.nonce, sig)) {
    console.warn(`[hub] ${row.name} (${id}): wrong signature, closed 4401`);
    return close(m.ws, 4401, 'wrong signature');
  }
  if (!allowed(row.email)) return close(m.ws, 4403, 'its person is not on the Sttark roster');
  if (row.removedAt !== null) return close(m.ws, 4401, 'this Mac was removed');
  clearTimeout(m.authTimer);
  H.unauthed.delete(m);
  Object.assign(m, { authed: true, id, email: row.email, name: row.name });
  const old = H.macs.get(id);
  if (old && old !== m) close(old.ws, 4409, 'a newer connection of this Mac took over');
  H.macs.set(id, m);
  setConnected(id, true);
  heard(id, nowS(), true);
  clearBye(id);
  if (kit !== row.kitVersion) db().prepare('UPDATE macs SET kit_version = ? WHERE id = ?').run(kit, id);
  m.watching = watchingOf(row.email);
  send(m.ws, 'server_to_mac', { event: 'welcome', success: true, payload: { phones: pushPhones(row.email), watching: m.watching } });
  console.log(`[hub] ${row.name} (${id}) connected, Kit ${kit}`);
  showMacs(row.email);
}

function onMacMessage(m: MacSock, data: RawData, isBinary: boolean): void {
  frame(m);
  const value = parse(data, isBinary, MAX_MAC_MESSAGE);
  if (!m.authed) return onAuth(m, value);
  if (!take(m.bucket)) return tooFast(m);
  if (value === undefined) return badMessage(m, 'not a JSON text message');
  const c = checkMessage('mac_to_server', value);
  if (!c.ok) return badMessage(m, c.why);
  const { event, payload } = c.message;
  if (event === 'auth') return badMessage(m, 'auth on a socket that is signed in');
  if (event !== 'bye' && m.bye) {
    m.bye = false;
    clearBye(m.id);
    showMacs(m.email);
  }
  switch (event) {
    case 'snapshot':
      return onSnapshot(m, payload);
    case 'archived':
      saveArchived(m.id, payload.rev, newestFirst(payload.items));
      return sendArchived(m);
    case 'archived_delta':
      return onArchivedDelta(m, payload);
    case 'result':
      return onResult(m, payload);
    case 'remind':
      events.emit('remind', { macId: m.id, email: m.email, cse: payload.cse, waitingSince: payload.waiting_since, title: payload.title, why: payload.why });
      return;
    case 'bye':
      m.bye = true;
      setBye(m.id, payload.why);
      console.log(`[hub] ${m.name} (${m.id}) said bye: ${payload.why}`);
      return showMacs(m.email);
    case 'unlink':
      m.closing = 1000;
      removeMac(m.id, { why: 'mac', by: m.email, byName: personName(m.email), words: `Removed ${m.name}: Kit on your phone was turned off on this Mac.` });
      return;
  }
}

function onSnapshot(m: MacSock, snap: any): void {
  saveSnapshot(m.id, snap);
  const renamed = snap.mac.name !== m.name;
  m.name = snap.mac.name;
  toPhones(m.email, { event: 'snapshot', success: true, payload: { mac: m.id, snapshot: snap } });
  if (renamed) showMacs(m.email);
  // An Archived tab is open: keep its list current.
  const have = archivedOf(m.id)?.rev ?? null;
  if (snap.archived_rev && snap.archived_rev !== have && phonesOf(m.email).some((p) => p.archived)) askArchived(m, have);
}

function sendArchived(m: MacSock): void {
  const msg = archivedMessage(m.id);
  if (msg) toPhones(m.email, msg, (p) => p.archived);
}

function onArchivedDelta(m: MacSock, d: { base: string; rev: string; add: ArchivedItem[]; remove: string[] }): void {
  const have = archivedOf(m.id);
  if (!have || have.rev !== d.base) {
    // Not the list the delta starts from: ask for the whole list again.
    return askArchived(m, have?.rev ?? null);
  }
  const drop = new Set([...d.remove, ...d.add.map((i) => i.cse)]);
  const items = newestFirst([...d.add, ...have.items.filter((i) => !drop.has(i.cse))]).slice(0, 200);
  saveArchived(m.id, d.rev, items);
  sendArchived(m);
}

function onMacClose(m: MacSock): void {
  clearTimeout(m.authTimer);
  H.unauthed.delete(m);
  if (!m.authed || H.macs.get(m.id) !== m) return;
  H.macs.delete(m.id);
  setConnected(m.id, false);
  heard(m.id, Math.floor(m.lastFrame / 1000), true);
  console.log(`[hub] ${m.name} (${m.id}) disconnected`);
  showMacs(m.email);
}

// ---------- actions ----------

/** The session an action is about, from the Mac's last snapshot (and its
 *  archived list), for the record: its id and its name then. */
function target(macId: string, act: string, args: any): { cse: string | null; title: string | null } {
  const snap = lastSnapshot(macId);
  const rows: any[] = snap?.rows ?? [];
  if (act === 'bring_back' || act === 'stop_waits') {
    const ids: string[] = act === 'bring_back' ? [args.wait] : args.waits;
    const row = rows.find((r) => (r.waits ?? []).some((w: any) => ids.includes(w.id)));
    return row ? { cse: row.cse, title: row.title } : { cse: null, title: null };
  }
  const row = rows.find((r) => r.cse === args.cse);
  if (row) return { cse: row.cse, title: row.title };
  const item = act === 'unarchive' ? archivedOf(macId)?.items.find((i) => i.cse === args.cse) : undefined;
  return { cse: args.cse, title: item?.title ?? null };
}

/** The record's words for a change the Mac made. */
function describe(act: string, args: any): string {
  switch (act) {
    case 'set_level':
      return `Set effort to ${LEVEL[args.level] ?? args.level} from the phone.`;
    case 'set_auto':
      return args.on ? 'Turned Auto on from the phone.' : 'Turned Auto off from the phone.';
    case 'set_limit':
      return `Set At the usage limit to ${args.mode === 'follow' ? 'Same as Settings' : args.mode === 'credits' ? 'Always use credits' : `Never use credits; hold at ${args.at}%`} from the phone.`;
    case 'stop_waits':
      return args.waits.length === 1 ? 'Stopped waiting from the phone.' : `Stopped ${args.waits.length} waits from the phone.`;
    case 'bring_back':
      return 'Brought it back now from the phone.';
    case 'unarchive':
      return 'Brought it back from the archive from the phone.';
    default:
      return 'Changed from the phone.';
  }
}

function offlineWords(r: MacRow): string {
  if (r.removedAt !== null) return `${r.name} is no longer linked.`;
  switch (macView(r).state) {
    case 'asleep':
      return `${r.name} is asleep. Actions work when this Mac is back.`;
    case 'quit':
      return `The Kit on ${r.name} is not running. Actions work when it is back.`;
    case 'updating':
      return `The Kit on ${r.name} is updating. Try again in a minute.`;
    default:
      return `${r.name} is not connected. Actions work when this Mac is back.`;
  }
}

function reply(phone: PhoneSock | null, id: string, reason: string, words: string): void {
  if (!phone) return;
  send(phone.ws, 'server_to_phone', { event: 'action_result', success: reason === 'ok', payload: { id, reason, words: cut(words, 160) } });
}

/** One record per outcome; the person's phones hear of it (the session
 *  page that is open lists it) unless it was denied. */
function record(a: Asked, reason: string, words: string, before: unknown, after: unknown, tell: boolean): void {
  const at = nowS();
  const said = cut(reason === 'ok' ? describe(a.act, a.args) : words, 160);
  addRecord({ at, who: a.email, whoName: a.name, macId: a.macId, macName: a.macName, session: a.cse, sessionName: a.title, action: a.act, before: before ?? null, after: after ?? null, result: reason, words: said });
  if (!tell || !a.cse) return;
  toPhones(a.email, {
    event: 'record', success: true,
    payload: { at, mac: a.macId, mac_name: cut(a.macName, 80), cse: a.cse, session_title: cut(a.title, 160), act: a.act, by_name: cut(a.name, 120), reason, words: said, before: before ?? null, after: after ?? null },
  });
}

function onAction(p: PhoneSock, a: { id: string; mac: string; act: string; args: any; basis: number }): void {
  if (p.session && !sessionStillValid(p.session)) return close(p.ws, 4401, 'signed out');
  const row = getMac(a.mac);
  const asked: Asked = { id: '', macId: a.mac, macName: row?.name ?? '', email: p.email, name: p.name, phone: p, phoneId: a.id, act: a.act, args: a.args, cse: null, title: null };
  if (!row || row.email !== p.email) {
    console.warn(`[hub] ${p.email} asked ${a.act} on a Mac that is not theirs (${a.mac}): denied`);
    record({ ...asked, ...(row ? target(row.id, a.act, a.args) : {}) }, 'denied', WORDS.denied, null, null, false);
    return reply(p, a.id, 'denied', WORDS.denied);
  }
  Object.assign(asked, target(row.id, a.act, a.args));
  const live = H.macs.get(row.id);
  if (row.removedAt !== null || !live || macView(row).state !== 'live') {
    const words = offlineWords(row);
    record(asked, 'offline', words, null, null, true);
    return reply(p, a.id, 'offline', words);
  }
  asked.id = `a_${randomBytes(12).toString('base64url')}`;
  const pending: Pending = { ...asked, timer: setTimeout(() => onTimeout(asked.id), settings.actionTimeoutMs) };
  H.pending.set(asked.id, pending);
  send(live.ws, 'server_to_mac', { event: 'action', success: true, payload: { id: asked.id, act: a.act, args: a.args, by: { email: p.email, name: cut(p.name, 120) } } });
}

function onTimeout(id: string): void {
  const p = H.pending.get(id);
  if (!p) return;
  H.pending.delete(id);
  record(p, 'timeout', WORDS.timeout, null, null, true);
  reply(p.phone, p.phoneId, 'timeout', WORDS.timeout);
  const { timer: _t, ...asked } = p;
  H.late.set(id, { ...asked, phone: null, until: Date.now() + settings.lateKeepMs });
}

function onResult(m: MacSock, r: { id: string; reason: string; words: string; before: unknown; after: unknown }): void {
  const p = H.pending.get(r.id);
  if (p && p.macId === m.id) {
    clearTimeout(p.timer);
    H.pending.delete(r.id);
    record(p, r.reason, r.words, r.before, r.after, true);
    return reply(p.phone, p.phoneId, r.reason, r.words);
  }
  // After its timeout: the change still happened, so it is recorded.
  const late = H.late.get(r.id);
  if (late && late.macId === m.id) {
    H.late.delete(r.id);
    return record(late, r.reason, r.words, r.before, r.after, true);
  }
  console.warn(`[hub] ${m.name} (${m.id}) answered an action it was not sent: ${r.id}`);
}

// ---------- /live ----------

function acceptPhone(req: IncomingMessage, socket: Duplex, head: Buffer): void {
  if (!isAppOrigin(req.headers.origin)) return refuse(socket, 403, 'Forbidden');
  const s = sessionFromCookieHeader(req.headers.cookie);
  const dev = s ? null : devUser();
  const who = s ? { email: s.email, name: s.name, session: s.id } : dev ? { ...dev, session: null } : null;
  if (!who) return refuse(socket, 401, 'Unauthorized');
  if (phonesOf(who.email).length >= MAX_PHONE_SOCKETS) return refuse(socket, 429, 'Too Many Requests');
  wss.handleUpgrade(req, socket, head, (ws) => {
    const p: PhoneSock = { kind: 'phone', ws, ...who, visible: false, archived: false, lastFrame: Date.now(), lastPing: Date.now(), bucket: bucket(20, 2) };
    H.phones.add(p);
    ws.on('message', (data, isBinary) => onPhoneMessage(p, data, isBinary));
    ws.on('ping', () => frame(p));
    ws.on('pong', () => frame(p));
    ws.on('close', () => {
      H.phones.delete(p);
      for (const x of H.pending.values()) if (x.phone === p) x.phone = null;
      updateWatching(p.email);
    });
    ws.on('error', (e) => console.warn(`[hub] phone socket error: ${e.message}`));
    send(ws, 'server_to_phone', macsMessage(p.email));
    for (const mac of macsOf(p.email)) {
      const snapshot = lastSnapshot(mac.id);
      if (snapshot) send(ws, 'server_to_phone', { event: 'snapshot', success: true, payload: { mac: mac.id, snapshot } });
    }
  });
}

function onPhoneMessage(p: PhoneSock, data: RawData, isBinary: boolean): void {
  frame(p);
  if (!take(p.bucket)) return tooFast(p);
  const value = parse(data, isBinary, MAX_PHONE_MESSAGE);
  if (value === undefined) return badMessage(p, 'not a JSON text message');
  const c = checkMessage('phone_to_server', value);
  if (!c.ok) return badMessage(p, c.why);
  const { event, payload } = c.message;
  switch (event) {
    case 'hello':
    case 'visible':
      p.visible = payload.visible;
      return updateWatching(p.email);
    case 'open_archived':
      return openArchived(p);
    case 'action':
      return onAction(p, payload);
  }
}

// ---------- the hook, and what ends sockets ----------

/** Every WebSocket upgrade on the server's port. */
export function handleUpgrade(req: IncomingMessage, socket: Duplex, head: Buffer): void {
  let path: string;
  try {
    path = new URL(req.url ?? '/', 'http://x').pathname;
  } catch {
    return refuse(socket, 400, 'Bad Request');
  }
  if (path === href('/mac')) return acceptMac(req, socket, head);
  if (path === href('/live')) return acceptPhone(req, socket, head);
  refuse(socket, 404, 'Not Found');
}

/** Sign out: this sign-in's phone pages close. */
export function endWebSession(id: string): void {
  for (const p of H.phones) if (p.session === id) close(p.ws, 4401, 'signed out');
}

/** Sign out everywhere: every phone page of the person closes. Their Macs
 *  stay linked and connected. */
export function endPerson(email: string): void {
  for (const p of phonesOf(email)) close(p.ws, 4401, 'signed out');
}

/** Each timer tick: pings, silent sockets, Mac states, late results. */
export function sweep(): void {
  const t = Date.now();
  for (const s of [...H.unauthed, ...H.macs.values(), ...H.phones] as Sock[]) {
    if (t - s.lastFrame > settings.silenceMs) s.ws.terminate();
    else if (t - s.lastPing >= settings.pingEveryMs) {
      s.lastPing = t;
      try {
        s.ws.ping();
      } catch {
        /* closing */
      }
    }
  }
  for (const email of new Set([...H.phones].map((p) => p.email))) showMacs(email);
  for (const [id, l] of H.late) if (l.until < t) H.late.delete(id);
}

/** A server restart: every socket closes with 1012, and each Kit and page
 *  connects again. */
export function closeAll(code = 1012, reason = 'server restart'): void {
  for (const s of [...H.unauthed, ...H.macs.values(), ...H.phones]) close(s.ws, code, reason);
}

function listen(): void {
  if (H.listening) return;
  H.listening = true;
  events.on('mac-linked', ({ email }) => showMacs(email, true));
  events.on('mac-removed', ({ macId, email, why }) => {
    const m = H.macs.get(macId);
    if (m) close(m.ws, m.closing ?? (why === 'roster' ? 4403 : 4401), why === 'mac' ? 'unlinked' : 'this Mac was removed');
    for (const p of [...H.pending.values()].filter((x) => x.macId === macId)) {
      clearTimeout(p.timer);
      H.pending.delete(p.id);
      const words = `${p.macName} was removed.`;
      record(p, 'offline', words, null, null, true);
      reply(p.phone, p.phoneId, 'offline', words);
    }
    showMacs(email, true);
  });
  events.on('roster-synced', () => {
    for (const m of H.macs.values()) if (!allowed(m.email)) close(m.ws, 4403, 'its person is not on the Sttark roster');
    for (const p of H.phones) if (!allowed(p.email)) close(p.ws, 4403, 'not on the Sttark roster');
  });
}
listen();

/** With the server: the upgrade hook, the shutdown hook and the sweep. */
export function startHub(): void {
  onUpgrade(handleUpgrade);
  (globalThis as Record<symbol, unknown>)[Symbol.for('sttark.kit.shutdown')] = closeAll;
  if (!H.sweep) {
    H.sweep = setInterval(sweep, settings.sweepEveryMs);
    H.sweep.unref?.();
  }
}

/** Tests only: closes every socket and forgets every action. */
export function resetHubForTests(): void {
  for (const s of [...H.unauthed, ...H.macs.values(), ...H.phones]) s.ws.terminate();
  for (const p of H.pending.values()) clearTimeout(p.timer);
  for (const m of H.unauthed) clearTimeout(m.authTimer);
  H.macs.clear();
  H.unauthed.clear();
  H.phones.clear();
  H.pending.clear();
  H.late.clear();
  H.shown.clear();
}
