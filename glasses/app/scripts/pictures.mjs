#!/usr/bin/env node
// Tables as pictures against text cards, and a glance card as a picture
// against the lens's own text, in the simulator on the mock bridge. Saves a
// picture of each in shots/pictures/, puts them side by side in
// docs/pictures-vs-text.png, and writes how long each picture page took to
// show (shots/pictures/timing.txt).
//
//   npm run dev                  (the dev server must run; see KIT_DEV_URL)
//   node scripts/pictures.mjs
//
// It starts its own mock bridge (MOCK_PORT, 8742) and simulator (sim.mjs:
// it waits until nobody uses the Mac). KIT_DEV_URL picks another dev server
// (default http://localhost:5181/); KIT_SIM_PORT another automation port.
import { spawn } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { app, consoleLines, input, lensShot, poke, sleep, startSim, stopSim } from './simkit.mjs';
import { sheet } from './sheet.mjs';

const APP = process.env.KIT_DEV_URL || 'http://localhost:5181/';
const MOCK_PORT = Number(process.env.MOCK_PORT || 8742);
const MOCK = `http://127.0.0.1:${MOCK_PORT}`;
const shots = join(app, 'shots', 'pictures');

async function ok(url) {
  try {
    return (await fetch(url)).ok;
  } catch {
    return false;
  }
}
if (!(await ok(APP))) {
  console.error(`pictures: start the dev server first (npm run dev), or set KIT_DEV_URL (now ${APP}).`);
  process.exit(1);
}

const log = [];
async function pull() {
  for (const l of await consoleLines()) log.push(l);
}
/** Wait for a console line matching `re` after line `from`, poking the page as it waits. */
async function waitLine(re, from = 0, ms = 20000) {
  const end = Date.now() + ms;
  for (;;) {
    await pull();
    const hit = log.slice(from).find((l) => re.test(l));
    if (hit) return hit;
    if (Date.now() > end) throw new Error(`no ${re} in ${ms / 1000} s; last lines:\n${log.slice(-8).join('\n')}`);
    await poke();
    await sleep(300);
  }
}
/** One touch action; returns where the console was, to wait for what follows. */
async function act(a) {
  await pull();
  const mark = log.length;
  await input(a);
  await sleep(900); // the app drops a second swipe within 0.25 s
  return mark;
}
const devPost = (path, body = '') => fetch(new URL(path, APP), { method: 'POST', body });

const taken = {};
const timing = [];
async function shot(name) {
  taken[name] = await lensShot(join(shots, `${name}.png`));
  console.log(`pictures: shots/pictures/${name}.png`);
}
/** After `mark`: wait until the page's pictures are all sent, note the time, take the shot. */
async function pictureShot(name, mark) {
  const line = await waitLine(/\[glasses\] pictures \d+ sent/, mark);
  timing.push(`${name}: ${line.replace(/^.*\[glasses\] /, '')}`);
  await sleep(500);
  await shot(name);
}
async function textShot(name) {
  await sleep(1200);
  await poke();
  await shot(name);
}

// Home rows, in order: + New session, Press 3, Quote follow-up, South D,
// Today's open asks (need you), Atlas, Docs: HVAC (working), Rewinder 2
// (waiting), Label die (idle).
const ROW = { asks: 4, rewinder: 7, die: 8 };
let at = 0;
async function open(row) {
  while (at < row) (await act('down'), at++);
  while (at > row) (await act('up'), at--);
  const mark = await act('click');
  await waitLine(/\[kit\] screen session/, mark);
  return mark;
}
async function back() {
  const mark = await act('double_click');
  await waitLine(/\[kit\] screen home/, mark);
}

rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });
const mock = spawn(process.execPath, [join(app, 'mock-bridge', 'server.mjs')], { env: { ...process.env, MOCK_PORT: String(MOCK_PORT) }, stdio: 'ignore' });

try {
  await sleep(800);
  startSim(`${APP}?bridge=${encodeURIComponent(MOCK)}&token=mock`);
  await waitLine(/\[kit\] screen home/);
  let mark = log.length;
  await devPost('/__kit/pictures', '1');
  await waitLine(/table pictures on/, mark);
  await sleep(1500);

  // Tables as pictures.
  mark = await open(ROW.asks);
  await pictureShot('asks-picture', mark);
  await act('down');
  await textShot('asks-after');
  mark = await act('up');
  await pictureShot('asks-picture-again', mark);
  await back();

  await open(ROW.rewinder);
  mark = await act('down');
  await pictureShot('quote-picture', mark);
  mark = await act('down');
  await pictureShot('quote-picture-2', mark);
  await back();

  await open(ROW.die);
  mark = await act('down');
  await pictureShot('die-picture-1', mark);
  mark = await act('down');
  await pictureShot('die-picture-2', mark);
  await back();

  // The same tables as text cards.
  mark = log.length;
  await devPost('/__kit/pictures', '0');
  await waitLine(/table pictures off/, mark);
  await open(ROW.asks);
  await textShot('asks-cards');
  await back();
  await open(ROW.rewinder);
  await textShot('quote-cards');
  await act('down');
  await textShot('quote-cards-2');
  await back();
  await open(ROW.die);
  await textShot('die-cards');
  await back();
  await devPost('/__kit/pictures', '1');

  // The glance lab: each card as a picture, then in the lens's own text.
  mark = log.length;
  await devPost('/__kit/lab');
  await waitLine(/\[kit\] screen lab:glance1-picture/, mark);
  await pictureShot('glance1-picture', mark);
  await act('down');
  await textShot('glance1-text');
  mark = await act('down');
  await pictureShot('glance2-picture', mark);
  await act('down');
  await textShot('glance2-text');
  // Gray steps, to read how the lens shows each gray (the lab's last screen).
  mark = await act('down');
  await pictureShot('grays', mark);
} finally {
  stopSim();
  mock.kill();
}

writeFileSync(join(shots, 'timing.txt'), `${timing.join('\n')}\n`);
console.log(`\n${timing.join('\n')}\n`);

/** The side-by-side sheet: text on the left, the picture on the right. */
const FRAMES = [
  ['asks-cards', 'Text cards.', 'Each row is a card: its name, then its cells as lines. 1 row and a half show.'],
  ['asks-picture', 'Picture.', 'Real columns: 3 rows at a glance, the header dim, "Needs you" bold. A long cell is cut at a clause.'],
  ['quote-cards', 'Text cards.', 'A supplier quote: 1 supplier a page, so the prices are on different pages.'],
  ['quote-picture', 'Picture.', 'The prices of all 3 suppliers side by side. The notes go on the next page, with the names.'],
  ['die-cards', 'Text cards.', 'A table of 7 rows and 5 columns: 1 row a page, 7 pages.'],
  ['die-picture-1', 'Picture.', '4 rows a page, then 3. A cell takes a second line before it is cut.'],
  ['glance1-text', 'Glance in lens text.', 'The title is the same size as the lines; only a border marks the status.'],
  ['glance1-picture', 'Glance as a picture.', 'A 34 px bold title, 24 px lines, the "You" line dim.'],
];
const out = sheet(
  FRAMES.filter(([name]) => taken[name]).map(([name, title, text]) => ({ file: taken[name], title, text })),
  join(app, 'docs', 'pictures-vs-text.png'),
  2,
);
console.log(`pictures: ${out.replace(app + '/', '')}`);
