#!/usr/bin/env node
// Starts the Even Hub simulator on the app, with its automation port open,
// so scripts can tap, swipe and take screenshots (scripts/walk.mjs).
//
//   node scripts/sim.mjs [app URL]        default http://localhost:5181/?bridge=http://127.0.0.1:8741&token=mock
//   node scripts/sim.mjs --stop           stops the one this script started
//
// The simulator opens windows, and a new window can take the keyboard. So by
// default it starts only when nobody has used this Mac's keyboard or mouse
// for 2 minutes, and gives the front back to the app that had it.
// KIT_SIM_ANYWAY=1 skips the wait (you are at the Mac and expect it).
import { execFileSync, spawn } from 'node:child_process';
import { existsSync, openSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PID = join(app, '.sim.pid');
const PORT = Number(process.env.KIT_SIM_PORT || 9898);
const args = process.argv.slice(2);

function stop() {
  if (!existsSync(PID)) return;
  const pid = Number(readFileSync(PID, 'utf8'));
  try {
    process.kill(pid, 'SIGTERM');
    console.log(`sim: stopped ${pid}`);
  } catch {}
  unlinkSync(PID);
}

if (args[0] === '--stop') {
  stop();
  process.exit(0);
}

const url = args[0] || 'http://localhost:5181/?bridge=http://127.0.0.1:8741&token=mock';

function idleSeconds() {
  const out = execFileSync('ioreg', ['-c', 'IOHIDSystem']).toString();
  const m = out.match(/"HIDIdleTime" = (\d+)/);
  return m ? Number(m[1]) / 1e9 : 0;
}
function frontApp() {
  try {
    return execFileSync('osascript', ['-e', 'tell application "System Events" to get bundle identifier of first application process whose frontmost is true']).toString().trim();
  } catch {
    return '';
  }
}

if (!process.env.KIT_SIM_ANYWAY) {
  const idle = idleSeconds();
  if (idle < 120) {
    console.error(`sim: this Mac was used ${Math.round(idle)} s ago. Not starting, so the simulator does not take the screen. Run it again later, or with KIT_SIM_ANYWAY=1 at the Mac.`);
    process.exit(2);
  }
}

stop();
const front = frontApp();
const require = createRequire(import.meta.url);
// Start the native binary itself (not the npm wrapper), so --stop ends it.
const native = join(dirname(require.resolve(`@evenrealities/sim-${process.platform}-${process.arch}/package.json`)), 'bin', 'evenhub-simulator');
const child = spawn(native, [url, '--automation-port', String(PORT), '--no-glow'], {
  cwd: app,
  detached: true,
  stdio: ['ignore', openSync(join(app, '.sim.log'), 'w'), openSync(join(app, '.sim.log'), 'a')],
});
child.unref();
writeFileSync(PID, String(child.pid));

// Wait for the automation port, then hand the front back.
const base = `http://127.0.0.1:${PORT}`;
let up = false;
for (let i = 0; i < 40 && !up; i++) {
  await new Promise((r) => setTimeout(r, 250));
  try {
    up = (await (await fetch(`${base}/api/ping`)).text()) === 'pong';
  } catch {}
}
await new Promise((r) => setTimeout(r, 1500));
const nowFront = frontApp();
if (front && nowFront !== front) {
  try {
    execFileSync('osascript', ['-e', `tell application id "${front}" to activate`]);
  } catch {}
}
console.log(`sim: ${up ? 'running' : 'NOT answering'} on ${base} (pid ${child.pid}); front app ${nowFront === front ? 'unchanged' : `was taken, given back to ${front}`}`);
process.exit(up ? 0 : 1);
