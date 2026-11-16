// Runs the shared Sttark page check from Sttark/sttark-docs main, so an app
// carries no copy of it: only this file, as scripts/page-check.mjs, and its
// config next to it (scripts/page-check.config.ts or .mjs).
//
//   npm run check:pages -- [options]   (check-pages.mjs says which)
//   node scripts/page-check.mjs tell-failed [options]
//
// A script that imports a part of the check (changed-pages.mjs, say) gets
// its folder from pageCheckDir().
//
// Where the check comes from, first that works:
//   - STTARK_PAGE_CHECK, a page-check folder (CI points it at the
//     sttark-docs checkout it already made), copied into the cache below;
//   - a copy fetched from sttark-docs main into
//     node_modules/.cache/sttark-page-check, again after ten minutes, with
//     your own git access (ssh, else https);
//   - that copy as it was, when the fetch fails (offline), with a warning.
//
// This file is canonical in Sttark/sttark-docs (page-check/launcher.mjs). It
// only finds and starts the check; what the check does changes there.
import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scripts = dirname(fileURLToPath(import.meta.url));
const app = resolve(scripts, '..');
const config = ['page-check.config.ts', 'page-check.config.mjs'].map((f) => join(scripts, f)).find(existsSync);
const REMOTES = (process.env.STTARK_DOCS_GIT ?? 'git@github.com:Sttark/sttark-docs.git https://github.com/Sttark/sttark-docs.git').split(/\s+/).filter(Boolean);

/** The folder the shared check runs from (fetched if needed). */
export function pageCheckDir() {
  const cache = join(app, 'node_modules', '.cache', 'sttark-page-check');
  // Copied in, not run where it is: inside the app it finds the app's own
  // Playwright and tsx.
  if (process.env.STTARK_PAGE_CHECK) {
    rmSync(cache, { recursive: true, force: true });
    mkdirSync(dirname(cache), { recursive: true });
    cpSync(resolve(process.env.STTARK_PAGE_CHECK), cache, { recursive: true });
    return cache;
  }
  const stamp = join(cache, '.fetched');
  if (existsSync(stamp) && Date.now() - statSync(stamp).mtimeMs < 10 * 60 * 1000) return cache;
  let why = '';
  for (const remote of REMOTES) {
    const tmp = mkdtempSync(join(tmpdir(), 'sttark-page-check-'));
    try {
      const git = (...a) => execFileSync('git', a, { stdio: ['ignore', 'ignore', 'pipe'], env: { ...process.env, GIT_TERMINAL_PROMPT: '0' } });
      git('clone', '--quiet', '--depth', '1', '--filter=blob:none', '--sparse', remote, join(tmp, 'docs'));
      git('-C', join(tmp, 'docs'), 'sparse-checkout', 'set', 'page-check');
      rmSync(cache, { recursive: true, force: true });
      mkdirSync(dirname(cache), { recursive: true });
      cpSync(join(tmp, 'docs', 'page-check'), cache, { recursive: true });
      writeFileSync(stamp, new Date().toISOString() + '\n');
      return cache;
    } catch (e) { why = String(e.stderr ?? e.message ?? e).trim().split('\n').pop(); } finally { rmSync(tmp, { recursive: true, force: true }); }
  }
  if (existsSync(join(cache, 'check-pages.mjs'))) {
    console.warn('page check: could not fetch it from Sttark/sttark-docs; using the copy fetched before.');
    return cache;
  }
  console.error(`page check: could not fetch it from Sttark/sttark-docs (git access to that repo is needed once), and there is no copy from before.${why ? ` Last error: ${why}` : ''}`);
  process.exit(2);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const dir = pageCheckDir();
  const [first, ...more] = process.argv.slice(2);
  const tool = first === 'tell-failed' ? 'tell-failed.mjs' : 'check-pages.mjs';
  const args = first === 'tell-failed' ? more : process.argv.slice(2);
  const entry = join(dir, tool);
  process.argv = [process.argv[0], entry, ...args, ...(args.includes('--config') || !config ? [] : ['--config', config])];
  await import(pathToFileURL(entry).href);
}
