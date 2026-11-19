#!/usr/bin/env node
// Walks every screen and action of the app in the Even Hub simulator, on the
// mock bridge's made-up sessions, and saves a picture of each step:
//   shots/NN-step.png       the lens, lit pixels drawn green on black
//   shots/panel-*.png       the phone panel, as the simulator shows it
//
// Needs the dev server (npm run dev, port 5181). It starts its own mock
// bridge (port 8742) and its own simulator (scripts/sim.mjs, which waits
// until this Mac is idle so it never takes the screen).
//
// The simulator's page sleeps while this Mac is locked or the window is
// hidden: network replies and timers wait for the next input. So after each
// wait the walk "pokes" the page with a long press and its release, which
// the app ignores.
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const shots = join(app, 'shots');
const SIM = 'http://127.0.0.1:9898';
const MOCK_PORT = 8742;
const MOCK = `http://127.0.0.1:${MOCK_PORT}`;
const APP = 'http://localhost:5181/';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function ok(url) {
  try {
    return (await fetch(url)).status < 500;
  } catch {
    return false;
  }
}

if (!(await ok(APP))) {
  console.error('walk: start the dev server first (npm run dev).');
  process.exit(1);
}

rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

let mock = null;
function startMock() {
  mock = spawn(process.execPath, [join(app, 'mock-bridge', 'server.mjs')], {
    env: { ...process.env, MOCK_PORT: String(MOCK_PORT) },
    stdio: 'ignore',
  });
}
function stopMock() {
  mock?.kill();
  mock = null;
}

function sim(url) {
  execFileSync(process.execPath, [join(app, 'scripts', 'sim.mjs'), url], { stdio: 'inherit' });
}

async function input(action) {
  await fetch(`${SIM}/api/input`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) });
}
async function poke() {
  await input('long_press');
  await input('long_press_release');
}
async function step(...actions) {
  for (const a of actions) {
    await input(a);
    await sleep(900);
  }
}
async function wait(ms) {
  // Poke every second or so, so the sleeping page keeps up.
  const end = Date.now() + ms;
  while (Date.now() < end) {
    await sleep(Math.min(1000, end - Date.now()));
    await poke();
  }
  await sleep(400);
}

let n = 0;
async function shot(name) {
  n++;
  const file = join(shots, `${String(n).padStart(2, '0')}-${name}.png`);
  const raw = file.replace('.png', '.raw.png');
  const png = Buffer.from(await (await fetch(`${SIM}/api/screenshot/glasses`)).arrayBuffer());
  (await import('node:fs')).writeFileSync(raw, png);
  // The simulator gives lit pixels over a clear ground: draw them on black.
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=black:s=576x288', '-i', raw, '-filter_complex', '[0][1]overlay=format=auto', '-frames:v', '1', file]);
  rmSync(raw);
  console.log(`walk: ${file.replace(app + '/', '')}`);
}
async function panel(name) {
  const png = Buffer.from(await (await fetch(`${SIM}/api/screenshot/webview`)).arrayBuffer());
  const file = join(shots, `panel-${name}.png`);
  (await import('node:fs')).writeFileSync(file, png);
  console.log(`walk: ${file.replace(app + '/', '')}`);
}
async function mockPost(path) {
  await fetch(`${MOCK}${path}`, { method: 'POST' });
}

try {
  startMock();
  await sleep(800);
  sim(`${APP}?bridge=${encodeURIComponent(MOCK)}&token=mock`);
  await wait(3000);

  // Home: needs-you sessions first, + New session on top.
  await shot('home');
  await panel('connected');
  await step('down');
  await shot('home-row-selected');

  // A session that asks a question: reply pages, then its answers.
  await step('click');
  await wait(1500);
  await shot('session-question-page1');
  await step('down');
  await shot('session-question-page2');
  await step('down', 'down');
  await shot('session-question-last-page');
  await step('click');
  await shot('actions-question');
  await step('double_click', 'double_click');
  await wait(1000);

  // A session that asks for an OK.
  await step('down', 'down', 'click');
  await wait(1500);
  await shot('session-permission');
  await step('click');
  await shot('actions-permission');
  await step('double_click', 'double_click');
  await wait(1000);

  // A plan to approve.
  await step('down', 'down', 'down', 'click');
  await wait(1500);
  await shot('session-plan');
  await step('click');
  await shot('actions-plan');
  await step('double_click', 'double_click');
  await wait(1000);

  // Answer the question with one tap; the session works, then replies.
  await step('down', 'click');
  await wait(1500);
  await step('click');
  await step('click');
  await wait(800);
  await shot('answered');
  await wait(6500);
  await shot('new-reply');

  // Reply by voice: the simulator records this Mac's microphone; the mock
  // turns any sound into a made-up sentence, a few words at a time.
  await step('click');
  await shot('actions-no-question');
  await step('click');
  await shot('voice-listening');
  await wait(5500);
  await shot('voice-words');
  await panel('listening');
  await step('click');
  await wait(2500);
  await shot('reply-sent');

  // Back to the list; another session starts to need you: a notice.
  await step('double_click');
  await wait(800);
  await mockPost('/mock/flip');
  await wait(1500);
  await shot('home-notice');

  // A new session by voice: speak, confirm, start.
  await wait(6000); // let the notice go
  await step('click');
  await wait(5000);
  await shot('new-voice');
  await step('click');
  await wait(2500);
  await shot('new-confirm');
  await step('click');
  await wait(1500);
  await shot('new-started');
  await wait(7000);
  await shot('new-replied');
  await step('double_click');
  await wait(1000);
  await shot('home-later');

  // The Mac goes away: the list stays, marked offline.
  stopMock();
  await wait(12000);
  await shot('home-offline');
  await step('down', 'click');
  await wait(1500);
  await shot('session-offline');
  await panel('offline');

  // Never connected: a bridge that does not answer, then no token at all.
  sim(`${APP}?bridge=${encodeURIComponent('http://127.0.0.1:9')}&token=mock`);
  await wait(4000);
  await shot('cant-reach');
  await panel('cant-reach');
  sim(`${APP}?bridge=${encodeURIComponent(MOCK)}&token=`);
  await wait(3000);
  await shot('set-up');
  await panel('set-up');
} finally {
  stopMock();
  execFileSync(process.execPath, [join(app, 'scripts', 'sim.mjs'), '--stop'], { stdio: 'inherit' });
}
