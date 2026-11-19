#!/usr/bin/env node
// Pictures of the glance card, the first thing on the session screen, on the
// mock bridge's glance sessions (MOCK_SET=glance: made-up replies like the
// ones that were hard to read on the lens), and docs/glance-cards.png with
// captions. Each card is as the real bridge writes it (mock-bridge/glances.mjs).
//
// Needs the dev server (npm run dev, or APP=http://localhost:<port>/). It
// starts its own mock bridge (port 8744, or MOCK_PORT) and its own simulator
// (scripts/sim.mjs, which waits until this Mac is idle so it never takes the
// screen).
import { spawn } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { sheet } from './sheet.mjs';
import { app, lensShot, sleep, startSim, step, stopSim, wait, waitScreen } from './simkit.mjs';

const shots = join(app, 'shots', 'glance');
const MOCK_PORT = Number(process.env.MOCK_PORT || 8744);
const MOCK = `http://127.0.0.1:${MOCK_PORT}`;
const APP = process.env.APP || 'http://localhost:5181/';

if (!(await fetch(APP).then((r) => r.ok).catch(() => false))) {
  console.error(`glance-shots: start the dev server first (npm run dev), or give its address in APP.`);
  process.exit(1);
}
rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

const mock = spawn(process.execPath, [join(app, 'mock-bridge', 'server.mjs')], {
  env: { ...process.env, MOCK_PORT: String(MOCK_PORT), MOCK_SET: 'glance' },
  stdio: 'ignore',
});
const taken = {};
async function shot(name) {
  const file = join(shots, `${String(Object.keys(taken).length + 1).padStart(2, '0')}-${name}.png`);
  taken[name] = await lensShot(file);
  console.log(`glance-shots: ${file.replace(app + '/', '')}`);
}
/** From Home, open the session `downs` rows below + New session, and wait for its card. */
async function open(downs) {
  await step(...Array(10).fill('up'), ...Array(downs).fill('down'), 'click');
  await waitScreen('card');
  await wait(1500);
}
async function home() {
  await step('double_click');
  await waitScreen('home');
}

try {
  await sleep(800);
  startSim(`${APP}?bridge=${encodeURIComponent(MOCK)}&token=mock`);
  await waitScreen('home', 30000);
  await wait(2500);
  // Home, in order: + New session; Harbor Film quote, Press 3 nozzle report,
  // Press 5 die change, Today's open asks (all need you); Laminator feeder (working).
  await open(5);
  await shot('table-working');
  await home();
  await open(1);
  await shot('quote');
  await step('down');
  await waitScreen('session');
  await wait(800);
  await shot('quote-full-reply');
  await home();
  await open(3);
  await shot('error');
  await home();
  await open(2);
  await shot('question');
  await step('down');
  await wait(600);
  await shot('question-pick');
  await step('down', 'down', 'down');
  await waitScreen('session');
  await wait(800);
  await shot('question-full-reply');
  await home();
  await open(4);
  await shot('table-asks');
  await home();
  await wait(1000);
  await shot('home');

  const out = sheet(
    [
      { file: taken['table-working'], title: 'Working.', text: 'The reply ends with a status table: one short line per row. Nothing for you now.' },
      { file: taken.quote, title: 'A supplier quote.', text: 'The price first, then lead time and the card fee. Last line: what you must do.' },
      { file: taken.error, title: 'An error.', text: 'The error first, then where. Last line: what you must do to fix it.' },
      { file: taken['table-asks'], title: 'Asks that need you.', text: 'From the status table: the asks that need you first, with !, then the rest.' },
      { file: taken.question, title: 'A question.', text: 'Its answers as buttons, plus Say it. The ▶ marks the one a tap sends.' },
      { file: taken['question-pick'], title: 'Swipe to pick.', text: 'A swipe moves the ▶ to the next answer. A tap sends it.' },
      { file: taken['quote-full-reply'], title: 'The full reply.', text: 'One swipe down from the card (past the buttons when there are some). Swipe up goes back.' },
      { file: taken.home, title: 'Home.', text: 'Each row shows the card\'s few words: what you must do, else the key fact.' },
    ],
    join(app, 'docs', 'glance-cards.png'),
  );
  console.log(`glance-shots: ${out.replace(app + '/', '')}`);
} finally {
  mock.kill();
  stopSim();
}
