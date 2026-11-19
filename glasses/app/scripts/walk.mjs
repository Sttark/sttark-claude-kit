#!/usr/bin/env node
// Walks every screen and action of the app in the Even Hub simulator, on the
// mock bridge's made-up sessions, and saves a picture of each step:
//   shots/NN-step.png       the lens, lit pixels drawn green on black
//   shots/panel-*.png       the phone panel, as the simulator shows it
//   docs/lens-screens.png   six of the lens pictures, with captions
//
// Needs the dev server (npm run dev, port 5181). It starts its own mock
// bridge (port 8742) and its own simulator (scripts/sim.mjs, which waits
// until this Mac is idle so it never takes the screen).
import { spawn } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { sheet } from './sheet.mjs';
import { app, lensShot, panelShot, sleep, startSim as sim, step, stopSim, wait } from './simkit.mjs';

const shots = join(app, 'shots');
const MOCK_PORT = 8742;
const MOCK = `http://127.0.0.1:${MOCK_PORT}`;
const APP = 'http://localhost:5181/';

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

let n = 0;
const taken = {};
async function shot(name) {
  n++;
  const file = join(shots, `${String(n).padStart(2, '0')}-${name}.png`);
  taken[name] = file;
  await lensShot(file);
  console.log(`walk: ${file.replace(app + '/', '')}`);
}
async function panel(name) {
  const file = await panelShot(join(shots, `panel-${name}.png`));
  console.log(`walk: ${file.replace(app + '/', '')}`);
}
async function mockPost(path) {
  await fetch(`${MOCK}${path}`, { method: 'POST' });
}

try {
  startMock();
  await sleep(800);
  // mute=1: Read to me plays with no volume, so the walk makes no sound.
  sim(`${APP}?bridge=${encodeURIComponent(MOCK)}&token=mock&mute=1`);
  await wait(3000);

  // Home: needs-you sessions first, + New session on top. The rows, in
  // order: + New session, Press 3, Quote follow-up, South D (all need you),
  // Atlas, Docs: HVAC (working), Rewinder 2 (waiting), Label die (idle).
  // Back on Home, the mark stays on the session last opened.
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

  // A session that asks for an OK: the next row.
  await step('down', 'click');
  await wait(1500);
  await shot('session-permission');
  await step('click');
  await shot('actions-permission');
  await step('double_click', 'double_click');
  await wait(1000);

  // A plan to approve: the next row.
  await step('down', 'click');
  await wait(1500);
  await shot('session-plan');
  await step('click');
  await shot('actions-plan');
  await step('double_click', 'double_click');
  await wait(1000);

  // Answer the question with one tap; the session works, then replies.
  // Press 3 is two rows up.
  await step('up', 'up', 'click');
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

  // Read to me: the first row when nothing is asked. The Mac makes the sound
  // (the mock with macOS say) and the phone plays it; the top line says so.
  // A tap on the same row stops it.
  await step('click');
  await wait(2500);
  await shot('reading');
  await panel('reading');
  await step('click');
  await wait(800);

  // Reply by voice: the next row.
  await step('down', 'click');
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

  // A new session by voice: speak, confirm, start. + New session is the
  // top row; a swipe up at the top stays there.
  await wait(6000); // let the notice go
  await step(...Array(8).fill('up'));
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
  await step('click');
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

  const out = sheet(
    [
      { file: taken['home-row-selected'], title: '1 Home.', text: 'Needs you first. Swipe moves the >, tap opens.' },
      { file: taken['session-question-page1'], title: '2 Session.', text: 'Status, then the last reply in pages. Swipe for the next page.' },
      { file: taken['actions-question'], title: '3 Actions.', text: "The question's answers first. One tap answers." },
      { file: taken['voice-words'], title: '4 Reply by voice.', text: 'Words show as you speak. Tap sends.' },
      { file: taken['new-confirm'], title: '5 New session.', text: 'Speak the prompt, read it, tap to start.' },
      { file: taken['home-notice'], title: '6 Notice.', text: 'A session starts to need you: the top line says so.' },
    ],
    join(app, 'docs', 'lens-screens.png'),
  );
  console.log(`walk: ${out.replace(app + '/', '')}`);
} finally {
  stopMock();
  stopSim();
}
