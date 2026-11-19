#!/usr/bin/env node
// End to end on the real Kit glasses bridge (glasses/bridge/) in the Even Hub
// simulator: a new session from typed words, the session on Home, its reply
// pages, a one-tap answer, a typed reply and Continue. After each step it
// reads the session on the Mac side, through the bridge's own API, and waits
// for the bridge to show the result. Then the bridge's speech to text with a
// spoken sample (macOS `say`, written to a file, never played aloud).
//
// THIS STARTS A REAL CLAUDE CODE SESSION on this Mac, named
// "G2 e2e test: ...". Archive it in the Claude app when you are done.
// The app runs with only=G2: the lens shows, and can open, only sessions
// whose name starts with G2, so no other session shows in the pictures or
// can get a message.
//
//   npm run dev                                  (the app, port 5181)
//   node scripts/e2e.mjs --yes-start-a-session   (the bridge must run on 8740)
//   node scripts/e2e.mjs --session cse_...       (go on with a G2 session that
//                                                 an earlier run started and
//                                                 that still asks its question)
//
// The Kit's "Name sessions automatically" renames a new session after its
// first prompt; the app keeps a session it started in the only=G2 list.
//
// Pictures: shots/e2e/NN-step.png, and docs/end-to-end.png with captions.
// The simulator starts only when this Mac has been idle 2 minutes (sim.mjs).
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { sheet } from './sheet.mjs';
import { app, input, lensShot, poke, sleep, startSim, stopSim, wait, waitScreen } from './simkit.mjs';

const at = process.argv.indexOf('--session');
const RESUME = at > 0 ? process.argv[at + 1] : null;
if (!RESUME && !process.argv.includes('--yes-start-a-session')) {
  console.error('e2e: this starts a real Claude Code session named "G2 e2e test: ..." on this Mac.\nRun it with --yes-start-a-session, and archive the session afterward.');
  process.exit(2);
}

const BRIDGE = process.env.KIT_BRIDGE || 'http://127.0.0.1:8740';
const TOKEN = readFileSync(join(homedir(), 'Library/Application Support/Sttark Kit Glasses/token'), 'utf8').trim();
const APP = 'http://localhost:5181/';
const ONLY = 'G2';
const PROMPT =
  'G2 e2e test: label press check, then PING or PONG\n' +
  'Write two short paragraphs, about 120 words in all, on how to check a label press before a run. ' +
  'Then ask me with AskUserQuestion whether to say PING or PONG, and after my answer say only that word.';
// Each reply differs from the one before, so the Mac side can tell it came.
const REPLY = 'G2 test reply: now say PONG, and only that word. If I then say Continue, say only DONE.';
const SPOKEN = 'Run the second purge, then check head two again.';

const out = join(app, 'shots', RESUME ? 'e2e-resume' : 'e2e');
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
const t0 = Date.now();
const log = (...a) => console.log(`e2e +${String(Math.round((Date.now() - t0) / 1000)).padStart(4)}s`, ...a);

// ---------- the Mac side: the bridge's API ----------

async function api(path, init = {}) {
  const r = await fetch(BRIDGE + path, { ...init, headers: { Authorization: `Bearer ${TOKEN}`, ...(init.headers || {}) } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${path}: ${r.status} ${body.error || ''}`);
  return body;
}
const sessions = async () => (await api('/api/sessions')).sessions;
const detail = (id) => api(`/api/sessions/${id}`);
const short = (s, n = 70) => (s || '').replace(/\s+/g, ' ').trim().slice(0, n);

/** Ask the bridge every 2 s (poking the simulator, so the lens keeps up) until `ok` gives a value. */
async function until(what, ok, ms) {
  const end = Date.now() + ms;
  for (;;) {
    const v = await ok().catch(() => null);
    if (v) return v;
    if (Date.now() > end) throw new Error(`timed out after ${ms / 1000} s waiting for ${what}`);
    await poke();
    await sleep(2000);
  }
}

async function typed(words) {
  const r = await fetch(`${APP}__kit/typed`, { method: 'POST', body: words });
  if (!r.ok) throw new Error(`typed words: ${r.status}`);
}

// ---------- pictures ----------

let n = 0;
const frames = [];
async function shot(name, title, text) {
  n++;
  const file = join(out, `${String(n).padStart(2, '0')}-${name}.png`);
  await lensShot(file);
  if (title) frames.push({ file, title, text });
  log(`picture ${file.replace(app + '/', '')}`);
}

// ---------- the run ----------

const before = new Set((await sessions()).map((s) => s.id));
if (!(await fetch(APP).then((r) => r.ok).catch(() => false))) {
  console.error('e2e: start the dev server first (npm run dev).');
  process.exit(1);
}
const health = await api('/api/health');
log(`bridge ${health.version}: ${health.sessions} sessions, speech to text ${health.stt}, Chrome ${health.web?.chrome ? 'open' : 'NOT open'}`);

const facts = {};
try {
  startSim(`${APP}?bridge=${encodeURIComponent(BRIDGE)}&token=${encodeURIComponent(TOKEN)}&only=${ONLY}`);
  await waitScreen('home', 30000);
  await wait(2000);
  await shot('home-start');

  let id, asked;
  if (RESUME) {
    id = RESUME;
    facts.id = id;
    asked = await detail(id);
    if (asked.pending?.kind !== 'question') throw new Error(`${id} asks no question now`);
    if (!asked.title.startsWith(ONLY)) throw new Error(`${id} is named "${asked.title}", not ${ONLY}...`);
    log(`Mac: ${id} "${asked.title}" asks "${asked.pending.text}"`);
    // The mark starts on + New session; the rows sort as the app sorts them.
    const RANK = { needs_you: 0, working: 1, waiting: 2, idle: 3 };
    const rows = (await sessions())
      .filter((r) => r.title.trim().toLowerCase().startsWith(ONLY.toLowerCase()))
      .sort((a, b) => RANK[a.status] - RANK[b.status] || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
    const downs = rows.findIndex((r) => r.id === id) + 1;
    for (let i = 0; i < downs; i++) {
      await input('down');
      await sleep(900);
    }
  } else {
    ({ id, asked } = await startOne());
    // 2. The session on Home: back, the mark is on it.
    await wait(2000);
    await input('double_click');
    await waitScreen('home');
  }
  await wait(2500);
  const listed = (await sessions()).find((s) => s.id === id);
  await shot('home-new', '4 Home.', `The new session, the > on it. Mac: the bridge lists it as ${listed?.status}${listed?.has_pending ? ', a question waits' : ''}. Only G2 sessions show (only=G2).`);
  await openAndFinish(id, asked);
} finally {
  stopSim();
}

/** 1. A new session: + New session is the top row, where the mark starts. */
async function startOne() {
  await input('click');
  await waitScreen('voice:listening');
  await wait(4500); // the simulator records this Mac's mic; the bridge turns it into words
  await shot('new-listening', '1 New session.', 'Tap + New session. The glasses listen (the simulator records the Mac mic); here the words come typed, from the phone box.');
  await typed(PROMPT);
  await waitScreen('confirm');
  await wait(1000);
  await shot('new-confirm', '2 Start this new session?', 'The prompt to read before it goes. Tap starts it in the folder set on the phone.');
  await input('click');
  await waitScreen('session', 130000);
  const added = await until('the new session on the bridge', async () => (await sessions()).find((s) => !before.has(s.id) && s.title.startsWith(ONLY)), 60000);
  const id = added.id;
  facts.id = id;
  log(`Mac: the bridge lists ${id} "${added.title}" (${added.status})`);
  await wait(1500);
  await shot('new-started', '3 Started.', `The session screen at once. Mac: the bridge lists the new session, "${short(added.title, 30)}...", ${added.status}.`);

  // Claude writes, then asks its question.
  const asked = await until('the question', async () => {
    const d = await detail(id);
    return d.pending?.kind === 'question' ? d : null;
  }, 300000);
  facts.question = asked.pending.text;
  log(`Mac: question "${asked.pending.text}" (${asked.pending.options.map((o) => o.label).join(' / ')}); reply ${asked.last_reply.length} characters`);
  return { id, asked };
}

/** 3 to 6: open it, read its pages, answer, reply, Continue. */
async function openAndFinish(id, asked) {
  // 3. Open it and read the reply pages.
  await input('click');
  await waitScreen('session');
  await wait(2500);
  await shot('session-page1', '5 The reply, page 1.', `Mac: the bridge's detail has the reply (${asked.last_reply.length} characters) and the question.`);
  await input('down');
  await wait(1200);
  await shot('session-page2', '6 Page 2.', 'A swipe turns the page; the status line keeps the question in view.');
  await input('up');
  await sleep(900);

  // 4. Answer with one tap: the first answer is marked.
  await input('click');
  await waitScreen('actions');
  await wait(1200);
  await shot('actions-question', "7 The question's answers.", `"${short(asked.pending.text, 50)}" One tap answers.`);
  await input('click');
  await waitScreen('session', 70000);
  await wait(1200);
  await shot('answer-sent', '8 Answered.', `Sent: ${asked.pending.options[0].label}. Back on the session, Claude works.`);
  const answered = await until('the reply to the answer', async () => {
    const d = await detail(id);
    return !d.pending && d.status !== 'working' && d.last_reply && d.last_reply !== asked.last_reply ? d : null;
  }, 240000);
  facts.answered = answered.last_reply;
  log(`Mac: no question now; reply "${short(answered.last_reply)}"`);
  await wait(3000);
  await shot('answer-reply', '9 Its reply.', `Mac: the bridge's detail says "${short(answered.last_reply, 40)}".`);

  // 5. Reply by typed words: Reply by voice is the second row now, under Read to me.
  await input('click');
  await waitScreen('actions');
  await wait(1200);
  await input('down');
  await wait(1200);
  await shot('actions-reply', '10 Actions, no question.', 'Read to me, Reply by voice, Continue, Back. All rows full brightness; > marks the row a tap does.');
  await input('click');
  await waitScreen('voice:listening');
  await wait(3500);
  await typed(REPLY);
  await waitScreen('session', 70000);
  await wait(1200);
  await shot('reply-sent', '11 Reply sent.', `"${REPLY}" went from the claude.ai page in Chrome, as typed in the Claude app.`);
  const replied = await until('the reply to the message', async () => {
    const d = await detail(id);
    return d.status !== 'working' && d.last_reply && d.last_reply !== answered.last_reply ? d : null;
  }, 240000);
  facts.replied = replied.last_reply;
  log(`Mac: reply "${short(replied.last_reply)}"`);
  await wait(3000);
  await shot('reply-reply', '12 Its reply.', `Mac: the bridge's detail says "${short(replied.last_reply, 40)}".`);

  // 6. Continue: two swipes down to it.
  await input('click');
  await waitScreen('actions');
  await wait(1200);
  await input('down');
  await wait(1200);
  await input('down');
  await wait(1200);
  await shot('actions-continue', '13 Continue.', 'Two swipes move the > to Continue; a tap sends it.');
  await input('click');
  await waitScreen('session', 70000);
  await wait(1200);
  await shot('continue-sent', '14 Continue sent.', 'Sent: Continue. The session works again.');
  const continued = await until('the reply to Continue', async () => {
    const d = await detail(id);
    return d.status !== 'working' && d.last_reply && d.last_reply !== replied.last_reply ? d : null;
  }, 240000);
  facts.continued = continued.last_reply;
  log(`Mac: reply "${short(continued.last_reply)}"`);
  await wait(3000);
  await shot('continue-reply', '15 Its reply.', `Mac: the bridge's detail says "${short(continued.last_reply, 40)}".`);
}

// 7. Speech to text on the Mac, with a spoken sample.
const dir = join(tmpdir(), `kit-e2e-${process.pid}`);
mkdirSync(dir, { recursive: true });
try {
  execFileSync('say', ['-o', join(dir, 'sample.aiff'), SPOKEN]);
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-i', join(dir, 'sample.aiff'), '-f', 's16le', '-ac', '1', '-ar', '16000', join(dir, 'sample.pcm')]);
  const pcm = readFileSync(join(dir, 'sample.pcm'));
  const r = await api('/api/transcribe', { method: 'POST', body: pcm, headers: { 'Content-Type': 'application/octet-stream' } });
  facts.spoken = SPOKEN;
  facts.heard = r.text;
  log(`speech to text: said "${SPOKEN}" (${(pcm.length / 32000).toFixed(1)} s), heard "${r.text}"`);
} finally {
  rmSync(dir, { recursive: true, force: true });
}

writeFileSync(join(out, 'facts.json'), JSON.stringify(facts, null, 2));
// A resumed run has no pictures of the start: its sheet stays beside its pictures.
const picture = sheet(frames, RESUME ? join(out, 'sheet.png') : join(app, 'docs', 'end-to-end.png'));
log(`done: ${picture.replace(app + '/', '')}. Archive ${facts.id} in the Claude app.`);
