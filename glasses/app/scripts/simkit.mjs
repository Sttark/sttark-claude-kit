// Driving the Even Hub simulator from a script, through its automation port
// (scripts/sim.mjs starts it with one): touch input, pictures of the lens
// and the phone page, and the page's console. Used by walk.mjs and e2e.mjs.
//
// The simulator's page sleeps while this Mac is locked or the window is
// hidden: network replies and timers wait for the next input. So waits
// "poke" the page with a long press and its release, which the app ignores.
import { execFileSync } from 'node:child_process';
import { rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const SIM = `http://127.0.0.1:${process.env.KIT_SIM_PORT || 9898}`;
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Start the simulator on `url` (it waits until this Mac is idle; see sim.mjs). */
export function startSim(url) {
  execFileSync(process.execPath, [join(app, 'scripts', 'sim.mjs'), url], { stdio: 'inherit' });
  consoleId = 0;
  screenNow = '';
}

export function stopSim() {
  execFileSync(process.execPath, [join(app, 'scripts', 'sim.mjs'), '--stop'], { stdio: 'inherit' });
}

/** One touch action: up, down, click, double_click, long_press, long_press_release. */
export async function input(action) {
  await fetch(`${SIM}/api/input`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) });
}

export async function poke() {
  await input('long_press');
  await input('long_press_release');
}

/** Actions one after another, 0.9 s apart (the app drops a second swipe within 0.25 s). */
export async function step(...actions) {
  for (const a of actions) {
    await input(a);
    await sleep(900);
  }
}

/** Wait, poking about every second so the sleeping page keeps up. */
export async function wait(ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    await sleep(Math.min(1000, end - Date.now()));
    await poke();
  }
  await sleep(400);
}

/** The lens as a PNG: lit pixels over black (the simulator gives a clear ground). */
export async function lensShot(file) {
  const raw = file.replace(/\.png$/, '.raw.png');
  writeFileSync(raw, Buffer.from(await (await fetch(`${SIM}/api/screenshot/glasses`)).arrayBuffer()));
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=black:s=576x288', '-i', raw, '-filter_complex', '[0][1]overlay=format=auto', '-frames:v', '1', file]);
  rmSync(raw);
  return file;
}

/** The phone page as the simulator shows it. */
export async function panelShot(file) {
  writeFileSync(file, Buffer.from(await (await fetch(`${SIM}/api/screenshot/webview`)).arrayBuffer()));
  return file;
}

let consoleId = 0;
let screenNow = '';

/** New console lines since the last call. */
export async function consoleLines() {
  const r = await (await fetch(`${SIM}/api/console?since_id=${consoleId}`)).json();
  const entries = Array.isArray(r) ? r : r.entries || [];
  for (const e of entries) consoleId = Math.max(consoleId, Number(e.id) || 0);
  return entries.map((e) => String(e.message ?? ''));
}

/** The app's screen, from its "[kit] screen <key>" lines (controller.ts). */
export async function screen() {
  for (const line of await consoleLines()) {
    const m = line.match(/\[kit\] screen (\S+)/);
    if (m) screenNow = m[1];
  }
  return screenNow;
}

/** Wait until the app shows a screen whose key matches `want`, poking as it waits. */
export async function waitScreen(want, ms = 15000) {
  const re = want instanceof RegExp ? want : new RegExp(`^${want}$`);
  const end = Date.now() + ms;
  for (;;) {
    const now = await screen();
    if (re.test(now)) return now;
    if (Date.now() > end) throw new Error(`the app did not show ${re} in ${ms / 1000} s (it shows ${now || 'nothing yet'})`);
    await poke();
    await sleep(700);
  }
}
