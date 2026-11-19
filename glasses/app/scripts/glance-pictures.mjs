#!/usr/bin/env node
// Glance cards in lens text against the same cards as pictures, in the
// simulator on the mock bridge's glance sessions (MOCK_SET=glance: made-up
// replies). Saves each in shots/glance-pictures/, the time each took to show
// in shots/glance-pictures/timing.txt, and puts them side by side in
// docs/glance-pictures.png: lens text on the left, the picture on the right.
//
//   npm run dev                  (the dev server must run; see APP)
//   node scripts/glance-pictures.mjs
//
// It starts its own mock bridge (MOCK_PORT, 8745) and simulator (sim.mjs:
// it waits until nobody uses the Mac). APP picks another dev server
// (default http://localhost:5181/); KIT_SIM_PORT another automation port.
import { spawn } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { sheet } from './sheet.mjs';
import { app, consoleLines, input, lensShot, poke, sleep, startSim, stopSim } from './simkit.mjs';

const APP = process.env.APP || 'http://localhost:5181/';
const MOCK_PORT = Number(process.env.MOCK_PORT || 8745);
const MOCK = `http://127.0.0.1:${MOCK_PORT}`;
const shots = join(app, 'shots', 'glance-pictures');

if (!(await fetch(APP).then((r) => r.ok).catch(() => false))) {
  console.error(`glance-pictures: start the dev server first (npm run dev), or give its address in APP (now ${APP}).`);
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
/** Touch actions, 0.9 s apart (the app drops a second swipe within 0.25 s); returns where the console was before them. */
async function act(...actions) {
  await pull();
  const mark = log.length;
  for (const a of actions) {
    await input(a);
    await sleep(900);
  }
  return mark;
}
const devPost = (path, body = '') => fetch(new URL(path, APP), { method: 'POST', body });

const taken = {};
const timing = {};
async function shot(name) {
  taken[name] = await lensShot(join(shots, `${name}.png`));
  console.log(`glance-pictures: shots/glance-pictures/${name}.png`);
}

// Home, in order: + New session; Harbor Film quote, Press 3 nozzle report,
// Press 5 die change, Today's open asks (all need you); Laminator feeder (working).
const CARDS = [
  { name: 'working', row: 5 },
  { name: 'quote', row: 1 },
  { name: 'question', row: 2 },
  { name: 'table', row: 4 },
];
/** From Home, open the session `row` rows below + New session; returns the console mark. */
async function open(row) {
  return act(...Array(8).fill('up'), ...Array(row).fill('down'), 'click');
}
async function home() {
  const mark = await act('double_click');
  await waitLine(/\[kit\] screen home/, mark);
}
const ms = (line) => Number(line.match(/in (\d+) ms/)?.[1]);

rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });
const mock = spawn(process.execPath, [join(app, 'mock-bridge', 'server.mjs')], {
  env: { ...process.env, MOCK_PORT: String(MOCK_PORT), MOCK_SET: 'glance' },
  stdio: 'ignore',
});

try {
  await sleep(800);
  startSim(`${APP}?bridge=${encodeURIComponent(MOCK)}&token=mock`);
  await waitLine(/\[kit\] screen home/, 0, 30000);
  await sleep(2500);

  // Lens text: the time from the tap's draw to the page on the lens.
  let mark = log.length;
  await devPost('/__kit/pictures', '0');
  await waitLine(/\[kit\] pictures off/, mark);
  for (const c of CARDS) {
    mark = await open(c.row);
    await waitLine(/\[kit\] screen card/, mark);
    const line = await waitLine(/\[glasses\] page rebuilt in \d+ ms/, mark);
    timing[`${c.name}-text`] = ms(line);
    await sleep(800);
    await poke();
    await shot(`${c.name}-text`);
    await home();
  }

  // Pictures: the same cards; the time to the last picture on the lens.
  mark = log.length;
  await devPost('/__kit/pictures', '1');
  await waitLine(/\[kit\] pictures on/, mark);
  for (const c of CARDS) {
    mark = await open(c.row);
    await waitLine(/\[kit\] screen card/, mark);
    const line = await waitLine(/\[glasses\] pictures \d+ sent .*\(card\)/, mark);
    timing[`${c.name}-picture`] = ms(line.replace(/^.*page shown/, 'page shown'));
    // A card can draw twice as it opens (the list's card, then the detail's):
    // the tiles of both draws count.
    timing[`${c.name}-picture-tiles`] = log
      .slice(mark)
      .filter((l) => /\[glasses\] pictures \d+ sent/.test(l))
      .reduce((a, l) => a + Number(l.match(/pictures (\d+) sent/)[1]), 0);
    await sleep(600);
    await shot(`${c.name}-picture`);
    if (c.name === 'question') {
      // A swipe moves the ▶ to the next answer: only the buttons' words
      // change, so no picture goes again.
      mark = await act('down');
      await sleep(1200);
      await pull();
      timing['question-swipe-pictures-sent'] = log.slice(mark).filter((l) => /\[glasses\] pictures \d+ sent/.test(l)).length;
      await shot('question-pick-picture');
    }
    await home();
  }

  // An answer from the card: "You:" says it is on its way (only the tiles
  // it reaches go again), then the session works on it. Last, since it
  // changes the mock's Home order.
  mark = await open(2);
  await waitLine(/\[glasses\] pictures \d+ sent .*\(card\)/, mark);
  await sleep(1500); // past the tap guard
  await act('down');
  mark = await act('click');
  await waitLine(/\[kit\] screen card:sending/, mark);
  await sleep(300);
  await shot('question-sending-picture');
  await sleep(2500);
  await poke();
  await shot('question-sent-picture');
  await pull();
  timing['question-answer-pictures'] = log
    .slice(mark)
    .filter((l) => /\[glasses\] pictures \d+ sent/.test(l))
    .map((l) => l.replace(/^.*\[glasses\] /, ''))
    .join(' | ');
} finally {
  stopSim();
  mock.kill();
}

const lines = Object.entries(timing).map(([k, v]) => `${k}: ${v}`);
writeFileSync(join(shots, 'timing.txt'), `${lines.join('\n')}\n`);
console.log(`\n${lines.join('\n')}\n`);

const t = (name) => `Shown in ${timing[name]} ms in the simulator.`;
const FRAMES = [
  ['working-text', 'Working, lens text.', `One font size: the title reads like a line. ${t('working-text')}`],
  ['working-picture', 'Working, picture.', `34 px bold title, 24 px lines. Done and dropped asks dim, and "You: nothing now". ${t('working-picture')}`],
  ['quote-text', 'Supplier quote, lens text.', `The price first; what you must do in a box. ${t('quote-text')}`],
  ['quote-picture', 'Supplier quote, picture.', `The same lines, larger; "You:" bold in a box. ${t('quote-picture')}`],
  ['question-text', 'Needs you, with answers, lens text.', `The answers are buttons; a swipe moves the ▶. ${t('question-text')}`],
  ['question-picture', 'Needs you, with answers, picture.', `The buttons stay lens text, so a swipe sends no picture. ${t('question-picture')}`],
  ['table-text', 'Status table, lens text.', `One line per ask, "!" for the asks that need you. ${t('table-text')}`],
  ['table-picture', 'Status table, picture.', `The asks that need you in bold, done and dropped ones dim. ${t('table-picture')}`],
];
const out = sheet(
  FRAMES.filter(([name]) => taken[name]).map(([name, title, text]) => ({ file: taken[name], title, text })),
  join(app, 'docs', 'glance-pictures.png'),
  2,
);
console.log(`glance-pictures: ${out.replace(app + '/', '')}`);
