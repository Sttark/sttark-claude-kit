#!/usr/bin/env node
// A stand-in for the Kit glasses bridge, with made-up sessions, so the app
// can be built and tried without a Mac's real sessions. Same API and live
// socket as the real bridge (README, "The bridge API"). It acts like Claude
// in the simplest way: a message or an answer makes a session work for a
// few seconds, then it replies and needs you again.
//
//   node mock-bridge/server.mjs            port 8741, token "mock"
//   MOCK_PORT=8750 MOCK_TOKEN=x node ...
//
// Test hooks, no token: POST /mock/reset (fresh sample data),
// POST /mock/flip (the working "Docs: HVAC chapter" session needs you now).
import http from 'node:http';
import { WebSocketServer } from 'ws';
import { FOLDERS, SPOKEN, glanceSessions, sampleSessions } from './data.mjs';
import { GLANCES } from './glances.mjs';

const PORT = Number(process.env.MOCK_PORT || 8741);
const TOKEN = process.env.MOCK_TOKEN || 'mock';
const VERSION = 'mock-0.1.0';
// Each session's turns, oldest first: its earlier turns, then the prompt of
// its last_reply. A message adds a turn; its reply fills it in.
function withTurns(list) {
  for (const s of list) {
    const latest = { ...(s.prompt || { at: s.updated_at, from: 'you', user_text: s.title }), reply_text: s.last_reply || '' };
    s.turns = [...(s.earlier || []), latest];
  }
  return list;
}
// MOCK_SET=glance: the sessions of the glance pictures (scripts/glance-shots.mjs).
const fresh = () =>
  withTurns((process.env.MOCK_SET === 'glance' ? glanceSessions() : sampleSessions()).map((s) => ({ ...s, glance: GLANCES[s.id] ?? null })));

let sessions = fresh();
let spokenIndex = 0;
let lastAudioBytes = 0;
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

const row = ({ last_reply, pending, earlier, prompt, turns, ...r }) => ({ ...r, has_pending: !!pending });
const RANK = { needs_you: 0, working: 1, waiting: 2, idle: 3 };
const list = () =>
  sessions
    .map(row)
    .sort((a, b) => RANK[a.status] - RANK[b.status] || String(b.updated_at).localeCompare(String(a.updated_at)));
const find = (id) => sessions.find((s) => s.id === id);
const now = () => new Date().toISOString();

// ---------- live socket ----------

const clients = new Set();
// Every change: the list to everyone, and the changed session's detail to
// whoever has it open.
function broadcast(s) {
  const detail = s ? { ...row(s), last_reply: s.last_reply, pending: s.pending } : null;
  for (const c of clients) {
    send(c, { type: 'sessions', sessions: list() });
    if (detail && c.subscribed === s.id) send(c, { type: 'session', session: detail });
  }
}
function send(ws, msg) {
  if (ws.readyState === 1) ws.send(JSON.stringify(msg));
}

// Claude's side, made up: work for a while, then reply.
// Its glance card as the bridge would write it, in the simplest way: the
// reply's first sentence. A new prompt is a new turn; its reply fills it in.
function work(s, reply, ms = 5000, prompt = null) {
  const turn = prompt ? { at: now(), from: 'you', user_text: prompt, reply_text: '' } : null;
  if (turn) s.turns.push(turn);
  s.status = 'working';
  s.why = 'Working on your message';
  s.status_line = s.why;
  s.pending = null;
  s.glance = { status_word: 'WORKING', lines: ['Claude works on it'], you: 'nothing now', options: [], phrase: 'Claude works on it' };
  s.updated_at = now();
  broadcast(s);
  setTimeout(() => {
    s.status = 'needs_you';
    s.why = 'Reply ready';
    s.status_line = 'Reply ready';
    s.last_reply = reply;
    if (turn) turn.reply_text = reply;
    const first = reply.split(/(?<=[.!?])\s/)[0];
    s.glance = { status_word: 'NEEDS YOU', lines: [first], you: 'read the reply', options: [], phrase: 'read the reply' };
    s.updated_at = now();
    log(`"${s.title}" replied`);
    broadcast(s);
  }, ms);
}

// ---------- http ----------

function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Max-Age', '600');
}
function json(res, code, body) {
  cors(res);
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}
function body(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks)));
  });
}
const parse = (buf) => {
  try {
    return JSON.parse(buf.toString() || '{}');
  } catch {
    return {};
  }
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;
  if (req.method === 'OPTIONS') {
    cors(res);
    res.writeHead(204);
    return res.end();
  }

  if (path === '/mock/reset' && req.method === 'POST') {
    sessions = fresh();
    spokenIndex = 0;
    broadcast();
    log('reset');
    return json(res, 200, { ok: true });
  }
  if (path === '/mock/flip' && req.method === 'POST') {
    const s = find('mock-hvac');
    s.status = 'needs_you';
    s.why = 'Reply ready';
    s.status_line = 'Reply ready';
    s.last_reply =
      'The unit locations section is written: South A, B and E, one table each, with the space each unit serves and its rating. Look at it before I publish it?';
    s.glance = GLANCES['mock-hvac-flip'] ?? null;
    s.updated_at = now();
    broadcast(s);
    log('flipped HVAC to needs you');
    return json(res, 200, { ok: true });
  }

  if ((req.headers.authorization || '') !== `Bearer ${TOKEN}`) return json(res, 401, { error: 'bad token' });

  if (path === '/api/health' && req.method === 'GET') return json(res, 200, { ok: true, version: VERSION });
  if (path === '/api/sessions' && req.method === 'GET') return json(res, 200, { sessions: list() });
  if (path === '/api/folders' && req.method === 'GET') return json(res, 200, { folders: FOLDERS });

  if (path === '/api/sessions' && req.method === 'POST') {
    const { prompt, folder } = parse(await body(req));
    if (!prompt) return json(res, 400, { error: 'prompt is empty' });
    const id = `mock-new-${Date.now().toString(36)}`;
    const title = String(prompt).split(/\s+/).slice(0, 5).join(' ');
    const s = { id, title, folder: (FOLDERS.find((f) => f.path === folder) || FOLDERS[0]).label, status: 'working', why: 'Starting', status_line: 'Starting', updated_at: now(), last_reply: '', pending: null, turns: [] };
    sessions.push(s);
    log(`new session "${title}"`);
    work(s, `Started on: "${prompt}". I looked at what is there and I am ready for the next step.`, 6000, prompt);
    return json(res, 200, { id });
  }

  const m = path.match(/^\/api\/sessions\/([^/]+)(\/(message|answer|turns))?$/);
  if (m) {
    const s = find(decodeURIComponent(m[1]));
    if (!s) return json(res, 404, { error: 'no such session' });
    if (!m[2] && req.method === 'GET') return json(res, 200, { ...row(s), last_reply: s.last_reply, pending: s.pending });
    if (m[3] === 'turns' && req.method === 'GET') {
      const total = s.turns.length;
      const limit = Math.max(1, Math.min(20, Number(url.searchParams.get('limit') || 5)));
      const before = url.searchParams.has('before') ? Math.max(0, Math.min(total, Number(url.searchParams.get('before')))) : total;
      const all = s.turns.map((t, index) => ({ index, ...t }));
      const latest = [...all].reverse().find((t) => t.reply_text)?.index ?? -1;
      return json(res, 200, { turns: all.slice(Math.max(0, before - limit), before), total, latest });
    }
    if (m[3] === 'message' && req.method === 'POST') {
      const { text } = parse(await body(req));
      if (!text) return json(res, 400, { error: 'text is empty' });
      log(`message to "${s.title}": ${text}`);
      work(s, text === 'Continue' ? 'I went on with the work. The next step is done, and nothing else needs you now.' : `Done: "${text}". Nothing else needs you now.`, 5000, text);
      return json(res, 200, { ok: true });
    }
    if (m[3] === 'answer' && req.method === 'POST') {
      const { option_id } = parse(await body(req));
      const opt = s.pending?.options.find((o) => o.id === option_id);
      if (!opt) return json(res, 409, { error: 'that question is already answered' });
      log(`answer to "${s.title}": ${opt.label}`);
      // An answer is not a new prompt: the reply goes on in the same turn.
      const latest = s.turns[s.turns.length - 1];
      work(s, `You chose "${opt.label}". That is done; the result is in the log.`);
      if (latest) setTimeout(() => (latest.reply_text = s.last_reply), 5000);
      return json(res, 200, { ok: true });
    }
  }

  if (path === '/api/transcribe' && req.method === 'POST') {
    const audio = await body(req);
    const seconds = audio.length / 32000;
    // A new dictation starts smaller than the last one sent.
    if (audio.length < lastAudioBytes) spokenIndex = (spokenIndex + 1) % SPOKEN.length;
    lastAudioBytes = audio.length;
    const words = SPOKEN[spokenIndex].split(' ');
    const heard = words.slice(0, Math.max(1, Math.round(seconds * 2.5))).join(' ');
    return json(res, 200, { text: seconds < 0.3 ? '' : heard });
  }

  json(res, 404, { error: 'not found' });
});

const wss = new WebSocketServer({ noServer: true });
server.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname !== '/api/live' || url.searchParams.get('token') !== TOKEN) {
    socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
    return socket.destroy();
  }
  wss.handleUpgrade(req, socket, head, (ws) => {
    clients.add(ws);
    ws.subscribed = null;
    send(ws, { type: 'sessions', sessions: list() });
    ws.on('message', (raw) => {
      let msg;
      try {
        msg = JSON.parse(String(raw));
      } catch {
        return;
      }
      if (msg.type === 'subscribe') {
        ws.subscribed = msg.id || null;
        const s = msg.id && find(msg.id);
        if (s) send(ws, { type: 'session', session: { ...row(s), last_reply: s.last_reply, pending: s.pending } });
      }
    });
    ws.on('close', () => clients.delete(ws));
  });
});

server.listen(PORT, '0.0.0.0', () => log(`mock bridge on http://0.0.0.0:${PORT} (token "${TOKEN}")`));

