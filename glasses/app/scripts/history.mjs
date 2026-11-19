#!/usr/bin/env node
// Scrolls back through a session's earlier turns in the Even Hub simulator,
// on the mock bridge's made-up Press 3 session, and saves a picture of each
// step in shots/history/ and four of them as docs/history.png.
//
// Needs the dev server (npm run dev). It starts its own mock bridge and its
// own simulator (scripts/sim.mjs, which waits until this Mac is idle).
//   KIT_APP_URL   the dev server, default http://localhost:5181/
//   MOCK_PORT     the mock bridge's port, default 8743
//   KIT_SIM_PORT  the simulator's automation port, default 9898
import { spawn } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { sheet } from './sheet.mjs';
import { app, lensShot, sleep, startSim, step, stopSim, wait, waitScreen } from './simkit.mjs';

const APP = process.env.KIT_APP_URL || 'http://localhost:5181/';
const MOCK_PORT = Number(process.env.MOCK_PORT || 8743);
const MOCK = `http://127.0.0.1:${MOCK_PORT}`;
const shots = join(app, 'shots', 'history');

try {
  await fetch(APP);
} catch {
  console.error(`history: start the dev server first (npm run dev), or set KIT_APP_URL (now ${APP}).`);
  process.exit(1);
}

rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });
const mock = spawn(process.execPath, [join(app, 'mock-bridge', 'server.mjs')], { env: { ...process.env, MOCK_PORT: String(MOCK_PORT) }, stdio: 'ignore' });

let n = 0;
const taken = {};
async function shot(name) {
  n++;
  const file = join(shots, `${String(n).padStart(2, '0')}-${name}.png`);
  taken[name] = file;
  await lensShot(file);
  console.log(`history: ${file.replace(app + '/', '')}`);
}

try {
  await sleep(800);
  startSim(`${APP}?bridge=${encodeURIComponent(MOCK)}&token=mock`);
  await waitScreen('home');
  await wait(1500);

  // Press 3 nozzle report: the first session under + New session.
  await step('down', 'click');
  await waitScreen('session');
  await wait(2000);
  await shot('latest');

  // Up at the top of the latest turn: the turn before it, from its top.
  await step('up');
  await waitScreen('earlier:1');
  await wait(800);
  await shot('earlier-1');
  await step('up', 'up');
  await waitScreen('earlier:3');
  await wait(800);
  await shot('earlier-3');
  await step('down');
  await shot('earlier-3-page-2');

  // On up to the first turn: the older ones load as the person gets near.
  await step('up', 'up', 'up', 'up');
  await waitScreen('earlier:6');
  await wait(800);
  await shot('oldest');

  // A tap on any earlier turn: the latest turn again.
  await step('click');
  await waitScreen('session');
  await wait(800);
  await shot('back-to-latest');

  // Down from the newest earlier turn comes back to the latest too.
  await step('up');
  await waitScreen('earlier:1');
  await step('down');
  await waitScreen('session');
  await shot('down-to-latest');

  const out = sheet(
    [
      { file: taken.latest, title: '1 The latest turn.', text: 'The session opens here, as before. "▲ earlier" in the hint: swipe up for the turns before it.' },
      { file: taken['earlier-1'], title: '2 One turn up.', text: 'Which turn and when, your prompt, then its reply. Swipe down to read on.' },
      { file: taken.oldest, title: '3 The first turn.', text: 'Older turns load a few at a time as you go up. Nothing is above the first turn.' },
      { file: taken['back-to-latest'], title: '4 Back to the latest.', text: 'Tap or double tap on an earlier turn. Double tap here goes back to Home.' },
    ],
    join(app, 'docs', 'history.png'),
  );
  console.log(`history: ${out.replace(app + '/', '')}`);
} finally {
  mock.kill();
  stopSim();
}
