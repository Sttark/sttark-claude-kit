// A stand-in for /live, for trying the phone pages before the real socket
// server is in: the built app (`npm run build`) on a temp database with
// the sample data (test/sample.mjs), and a fake server and Mac behind
// /live that answer the pages as phone/asyncapi.yaml says. Test only:
// never deployed, never a live server.
//
//   npm run build && node test/live-stand-in.mjs [--port 4352] [--next gone]
//
// BASE_PATH must be the one the build was made with (dist/kit-build.json).
// It hooks in where the real one does: the upgrade handler server.mjs
// passes every upgrade to (src/lib/upgrade.ts). Type a line to steer it:
//   next <ok|gone|not_now|not_here|bad|offline|timeout|denied>
//   mac <pro|mini> <live|updating|asleep|quit|not_heard>
// test/walk.mjs imports start() and steers it the same way.
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { MACS, seed } from './sample.mjs';

const UPGRADE = Symbol.for('sttark.kit.upgrade');
const LEVEL = { low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra', max: 'Max' };

// ---------- a small WebSocket server (RFC 6455, text frames) ----------

function accept(req, socket, onText) {
  const key = req.headers['sec-websocket-key'];
  const hash = createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${hash}\r\n\r\n`);
  let buf = Buffer.alloc(0);
  const peer = {
    open: true,
    send(obj) {
      if (!peer.open) return;
      const data = Buffer.from(JSON.stringify(obj));
      const head = data.length < 126 ? Buffer.from([0x81, data.length]) : data.length < 65536 ? Buffer.from([0x81, 126, data.length >> 8, data.length & 255]) : Buffer.concat([Buffer.from([0x81, 127, 0, 0, 0, 0]), Buffer.from([(data.length >>> 24) & 255, (data.length >>> 16) & 255, (data.length >>> 8) & 255, data.length & 255])]);
      socket.write(Buffer.concat([head, data]));
    },
    close() {
      peer.open = false;
      socket.end();
    },
  };
  socket.on('data', (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    for (;;) {
      if (buf.length < 2) return;
      const op = buf[0] & 15;
      let len = buf[1] & 127;
      let off = 2;
      if (len === 126) {
        if (buf.length < 4) return;
        len = buf.readUInt16BE(2);
        off = 4;
      } else if (len === 127) {
        if (buf.length < 10) return;
        len = Number(buf.readBigUInt64BE(2));
        off = 10;
      }
      const masked = buf[1] & 128;
      const need = off + (masked ? 4 : 0) + len;
      if (buf.length < need) return;
      const mask = masked ? buf.subarray(off, off + 4) : null;
      const data = Buffer.from(buf.subarray(off + (masked ? 4 : 0), need));
      if (mask) for (let i = 0; i < data.length; i++) data[i] ^= mask[i & 3];
      buf = buf.subarray(need);
      if (op === 8) return peer.close();
      if (op === 9) socket.write(Buffer.concat([Buffer.from([0x8a, data.length]), data]));
      if (op === 1) onText(data.toString('utf8'), peer);
    }
  });
  socket.on('close', () => (peer.open = false));
  socket.on('error', () => (peer.open = false));
  return peer;
}

// ---------- the fake server and Macs ----------

/** Starts the built app with the stand-in on `port`. */
export async function start({ port = 4352, email = 'avery.stone@sttark.com', macs = 'two', timeoutMs = 3000, answerMs = 600 } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'kit-stand-in-'));
  const file = join(dir, 'kit.db');
  const now = () => Math.floor(Date.now() / 1000);
  const s = await seed(file, email, now(), { macs });
  const { db } = await import('../src/lib/db.ts');
  let base = '';
  try {
    base = JSON.parse(readFileSync(fileURLToPath(new URL('../dist/kit-build.json', import.meta.url)), 'utf8')).base ?? '';
  } catch {}

  const state = {
    macs: s.macs.filter((m) => macs === 'two' || m.id === MACS.pro),
    snaps: s.snaps,
    archived: { ...s.archived },
    next: 'ok',
    refuse: false,
  };
  // Remove on Menu: the real server closes the Mac's socket; here the Mac
  // just leaves the list.
  globalThis[Symbol.for('sttark.kit.macRemoved')] = (id) => {
    state.macs = state.macs.filter((m) => m.id !== id);
    delete state.snaps[id];
    delete state.archived[id];
    sendMacs();
  };
  const peers = new Set();
  const all = (obj) => peers.forEach((p) => p.send(obj));
  const save = (macId) => {
    const snap = state.snaps[macId];
    snap.at = now();
    db().prepare('INSERT OR REPLACE INTO snapshots (mac_id, at, received_at, data) VALUES (?, ?, ?, ?)').run(macId, snap.at, now(), JSON.stringify(snap));
    all({ event: 'snapshot', success: true, payload: { mac: macId, snapshot: snap } });
  };
  const saveArchived = (macId) => {
    const list = state.archived[macId];
    list.rev = createHash('sha1').update(JSON.stringify(list.items)).digest('hex').slice(0, 16);
    state.snaps[macId].archived_rev = list.rev;
    state.snaps[macId].archived_count = list.items.length;
    db().prepare('INSERT OR REPLACE INTO archived (mac_id, hash, received_at, data) VALUES (?, ?, ?, ?)').run(macId, list.rev, now(), JSON.stringify(list));
    all({ event: 'archived', success: true, payload: { mac: macId, rev: list.rev, items: list.items } });
  };
  const sendMacs = () => all({ event: 'macs', success: true, payload: { macs: state.macs.map((m) => ({ id: m.id, name: m.name, state: m.state, last_seen: m.state === 'live' ? now() : m.last_seen, kit: m.kit })) } });
  const record = (macId, row, act, words, before, after) => {
    const mac = state.macs.find((m) => m.id === macId);
    db()
      .prepare('INSERT INTO records (at, who, who_name, mac_id, mac_name, session, session_name, action, before, after, result, words) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
      .run(now(), email, 'Sample Person', macId, mac.name, row.cse, row.title, act, JSON.stringify(before), JSON.stringify(after), 'ok', words);
    all({ event: 'record', success: true, payload: { at: now(), mac: macId, mac_name: mac.name, cse: row.cse, session_title: row.title, act, by_name: 'Sample Person', reason: 'ok', words, before, after } });
  };

  /** What the Mac does with one action: [reason, words]. */
  function onAction(p) {
    const mac = state.macs.find((m) => m.id === p.mac);
    if (!mac) return ['denied', 'That Mac is not linked to your account. Nothing was sent.'];
    if (mac.state !== 'live') return ['offline', `${mac.name} is ${mac.state === 'asleep' ? 'asleep' : 'not connected'}. Actions work when this Mac is back.`];
    const forced = state.next;
    state.next = 'ok';
    const snap = state.snaps[mac.id];
    const a = p.args;
    const rowOf = (cse) => snap.rows.find((r) => r.cse === cse);
    const rowOfWait = (id) => snap.rows.find((r) => r.waits.some((w) => w.id === id));
    if (forced === 'timeout') return null;
    if (forced !== 'ok') {
      const words = {
        gone: p.act === 'unarchive' ? 'It is not archived now. It is in your list.' : p.act === 'stop_waits' || p.act === 'bring_back' ? 'That wait already ended. Nothing was changed.' : 'This session is no longer on your Mac. It may be archived. Nothing was changed.',
        not_now: 'It does not run while it waits. Set the effort when it comes back.',
        not_here: 'Its conversation is not on this Mac, so this Mac cannot bring it back.',
        bad: 'Your Mac did not take that action. Nothing was changed.',
        denied: 'That Mac is not linked to your account. Nothing was sent.',
        offline: `${mac.name} is not connected, so nothing was sent. Try again when it is back.`,
      }[forced];
      return [forced, words];
    }
    switch (p.act) {
      case 'stop_waits': {
        const row = rowOfWait(a.waits[0]);
        if (!row) return ['gone', 'That wait already ended. Nothing was changed.'];
        const stopped = row.waits.filter((w) => a.waits.includes(w.id));
        row.waits = row.waits.filter((w) => !a.waits.includes(w.id));
        if (!row.waits.length) {
          snap.rows = snap.rows.filter((r) => r !== row);
          (state.archived[mac.id] ??= { v: 1, rev: '00000000', items: [] }).items.unshift({ cse: row.cse, title: row.title, folder: 'src', archived_at: now(), url: row.url });
          save(mac.id);
          saveArchived(mac.id);
          const one = stopped.length === 1 && a.waits.length === 1;
          record(mac.id, row, 'stop_waits', one ? `Stopped the wait “${stopped[0].what}” from the phone.` : 'Stopped waiting from the phone.', { waits: stopped.map((w) => w.id) }, { waits: [] });
          return ['ok', one ? 'Stopped. It waits on nothing now, so it is in Archived.' : 'Stopped waiting. It is in Archived now.'];
        }
        const n = row.waits.length;
        row.sub = n === 1 ? row.waits[0].what : `${n} waits`;
        row.sub_warn = row.waits.some((w) => w.failing) ? (n === 1 ? 'Check failing' : '1 check failing') : null;
        row.time_at = row.waits[0].by;
        save(mac.id);
        record(mac.id, row, 'stop_waits', `Stopped the wait “${stopped[0].what}” from the phone.`, { waits: [...row.waits.map((w) => w.id), ...stopped.map((w) => w.id)] }, { waits: row.waits.map((w) => w.id) });
        return ['ok', `Stopped. It waits on ${n} ${n === 1 ? 'thing' : 'things'} now.`];
      }
      case 'bring_back': {
        const row = rowOfWait(a.wait);
        if (!row) return ['gone', 'That wait already ended. Nothing was changed.'];
        Object.assign(row, { group: 'working', waits: [], time_at: now(), sub: 'Auto: Claude sets the effort', sub_warn: null, sub_strong: LEVEL[row.session?.level] ?? null });
        if (row.session) row.session.turn_at = now();
        save(mac.id);
        record(mac.id, row, 'bring_back', 'Brought it back from the phone.', { waits: [a.wait] }, { waits: [] });
        return ['ok', 'Back in your list. Claude works on it now.'];
      }
      case 'set_level': {
        const row = rowOf(a.cse);
        if (!row?.session) return ['gone', 'This session is no longer on your Mac. It may be archived. Nothing was changed.'];
        if (row.group === 'waiting') return ['not_now', 'It does not run while it waits. Set the effort when it comes back.'];
        const before = { level: row.session.level, manual: row.session.manual };
        Object.assign(row.session, { level: a.level, manual: true, reason: 'You set the effort' });
        Object.assign(row, { sub_strong: LEVEL[a.level], sub: row.background ? row.sub : 'Manual: you set the effort' });
        save(mac.id);
        record(mac.id, row, 'set_level', `Set effort to ${LEVEL[a.level]} from the phone.`, before, { level: a.level, manual: true });
        return ['ok', `Effort is ${LEVEL[a.level]} now. Auto is off for this session.`];
      }
      case 'set_auto': {
        const row = rowOf(a.cse);
        if (!row?.session) return ['gone', 'This session is no longer on your Mac. It may be archived. Nothing was changed.'];
        if (row.group === 'waiting') return ['not_now', 'It does not run while it waits. Set the effort when it comes back.'];
        const before = { manual: row.session.manual };
        row.session.manual = !a.on;
        if (!row.background) row.sub = a.on ? 'Auto: Claude sets the effort' : 'Manual: you set the effort';
        save(mac.id);
        record(mac.id, row, 'set_auto', a.on ? 'Turned Auto on from the phone.' : 'Turned Auto off from the phone.', before, { manual: !a.on });
        return ['ok', a.on ? 'Auto is on. Claude sets the effort.' : `Auto is off. It stays at ${LEVEL[row.session.level] ?? 'its level'} until you change it.`];
      }
      case 'set_limit': {
        const row = rowOf(a.cse);
        if (!row) return ['gone', 'This session is no longer on your Mac. It may be archived. Nothing was changed.'];
        const before = { limit_mode: { ...row.limit_mode } };
        row.limit_mode = { mode: a.mode, at: a.at };
        const label = a.mode === 'credits' ? 'Always use credits' : a.mode === 'hold' ? `Never use credits; hold at ${a.at}%` : 'Same as Settings';
        let words = `At the usage limit is ${label} now.`;
        if (row.group === 'held' && a.mode === 'credits') {
          Object.assign(row, { group: 'working', hold: null, time_at: now(), sub: 'Auto: Claude sets the effort', sub_strong: LEVEL[row.session?.level] ?? null });
          words = 'It uses credits now and goes on, under Claude working.';
        }
        save(mac.id);
        record(mac.id, row, 'set_limit', `Set At the usage limit to ${label} from the phone.`, before, { limit_mode: row.limit_mode });
        return ['ok', words];
      }
      case 'unarchive': {
        const list = state.archived[mac.id];
        const item = list?.items.find((i) => i.cse === a.cse);
        if (!item) return ['gone', 'It is not archived now. It is in your list.'];
        list.items = list.items.filter((i) => i !== item);
        const row = {
          id: item.cse, cse: item.cse, sid: null, group: 'working', title: item.title, sub: 'Back from Archived', sub_strong: 'Medium', sub_warn: null, late: false, time_at: now(), url: item.url,
          session: { level: 'medium', manual: false, reason: 'Goes on with the work', needs_you: false, why: null, waiting_since: null, turn_at: now() },
          background: null, waits: [], hold: null, limit_mode: { mode: 'follow', at: null },
        };
        snap.rows.push(row);
        save(mac.id);
        saveArchived(mac.id);
        record(mac.id, row, 'unarchive', 'Brought it back from Archived from the phone.', { archived: true }, { archived: false });
        return ['ok', 'Back in your list on the same link. Claude works on it now, under Claude working.'];
      }
    }
    return ['bad', 'Your Mac did not take that action. Nothing was changed.'];
  }

  function onText(text, peer) {
    let m;
    try {
      m = JSON.parse(text);
    } catch {
      return peer.send({ event: 'error', success: false, payload: { code: 'bad_message', words: 'The server did not understand that message.' } });
    }
    if (m.event === 'hello') {
      peer.send({ event: 'macs', success: true, payload: { macs: state.macs.map((x) => ({ id: x.id, name: x.name, state: x.state, last_seen: x.state === 'live' ? now() : x.last_seen, kit: x.kit })) } });
      for (const x of state.macs) if (state.snaps[x.id]) peer.send({ event: 'snapshot', success: true, payload: { mac: x.id, snapshot: state.snaps[x.id] } });
    } else if (m.event === 'open_archived') {
      for (const [mac, list] of Object.entries(state.archived)) peer.send({ event: 'archived', success: true, payload: { mac, rev: list.rev, items: list.items } });
    } else if (m.event === 'action') {
      const p = m.payload;
      const mac = state.macs.find((x) => x.id === p.mac);
      const offline = !mac || mac.state !== 'live';
      setTimeout(
        () => {
          const out = onAction(p);
          if (!out) return setTimeout(() => peer.send({ event: 'action_result', success: false, payload: { id: p.id, reason: 'timeout', words: 'Your Mac did not answer in time. Check the session before you try again.' } }), timeoutMs);
          const [reason, words] = out;
          peer.send({ event: 'action_result', success: reason === 'ok', payload: { id: p.id, reason, words } });
        },
        offline ? 50 : answerMs,
      );
    }
  }

  globalThis[UPGRADE] = (req, socket) => {
    const path = new URL(req.url ?? '/', 'http://x').pathname;
    if (path !== `${base}/live` || state.refuse) return socket.end('HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
    const peer = accept(req, socket, onText);
    peers.add(peer);
    socket.on('close', () => peers.delete(peer));
  };

  Object.assign(process.env, { PORT: String(port), HOST: '127.0.0.1', NODE_ENV: 'development', DEV_FAKE_USER: email, KIT_DB: file });
  await import('../server.mjs');
  await new Promise((r) => setTimeout(r, 300));

  return {
    url: `http://127.0.0.1:${port}${base}`,
    base,
    /** The reason the Mac gives to the next action. */
    next(reason) {
      state.next = reason;
    },
    /** A Mac's state, as the socket server would see it. */
    setMac(which, st) {
      const mac = state.macs.find((m) => m.id === (MACS[which] ?? which));
      if (!mac) return;
      mac.state = st;
      if (st !== 'live') mac.last_seen = now();
      db().prepare('UPDATE macs SET last_seen = ?, bye = ?, bye_at = ? WHERE id = ?').run(st === 'live' ? now() + 86400 : mac.last_seen, st === 'live' || st === 'not_heard' ? null : { asleep: 'sleep', quit: 'quit', updating: 'update' }[st], st === 'live' ? null : now(), mac.id);
      sendMacs();
    },
    /** Refuses new sockets, as a server that is down would. */
    refuse(on) {
      state.refuse = on;
    },
    /** Drops every page's socket, as a network change would. */
    dropAll() {
      for (const p of peers) p.close();
    },
    peers: () => peers.size,
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const arg = (k, d) => {
    const i = process.argv.indexOf(k);
    return i >= 0 ? process.argv[i + 1] : d;
  };
  const s = await start({ port: Number(arg('--port', 4352)), macs: arg('--macs', 'two') });
  if (arg('--next')) s.next(arg('--next'));
  console.log(`stand-in: ${s.url}/ (type: next <reason> | mac <pro|mini> <state>)`);
  createInterface({ input: process.stdin }).on('line', (line) => {
    const [cmd, a, b] = line.trim().split(/\s+/);
    if (cmd === 'next') s.next(a);
    else if (cmd === 'mac') s.setMac(a, b);
    else if (cmd === 'drop') s.dropAll();
  });
}
