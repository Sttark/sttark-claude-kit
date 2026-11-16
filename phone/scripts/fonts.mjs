// Puts the licensed Founders Grotesk files where the shared style file looks
// for them: src/styles/fonts/, beside sttark-shared.css. They are licensed to
// Sttark and this repo is public, so they are never committed (.gitignore).
// They come from the first of these that has them: STTARK_FONTS_DIR; a
// sttark-docs checkout beside this repo (../../sttark-docs); Sttark/sttark-docs
// main through your own gh sign-in.
//
//   npm run fonts                    fails when it finds none (the deploy)
//   node scripts/fonts.mjs --soft    warns instead (npm run dev and build
//                                    run it first; without the files, pages
//                                    fall back to Helvetica Neue and ask for
//                                    files that are not there)
import { execFileSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(app, 'src', 'styles', 'fonts');
const FILES = ['founders-grotesk-regular.woff2', 'founders-grotesk-regular-italic.woff2', 'founders-grotesk-semibold.woff2', 'founders-grotesk-semibold-italic.woff2'];
const soft = process.argv.includes('--soft');
const all = (dir) => FILES.every((f) => existsSync(join(dir, f)));

if (all(out)) process.exit(0);
mkdirSync(out, { recursive: true });
for (const dir of [process.env.STTARK_FONTS_DIR, join(app, '..', '..', 'sttark-docs', 'app', 'src', 'styles', 'fonts')]) {
  if (!dir || !all(dir)) continue;
  for (const f of FILES) copyFileSync(join(dir, f), join(out, f));
  console.log(`fonts: copied from ${dir}`);
  process.exit(0);
}
try {
  for (const f of FILES) {
    const bytes = execFileSync('gh', ['api', '-H', 'Accept: application/vnd.github.raw', `repos/Sttark/sttark-docs/contents/app/src/styles/fonts/${f}?ref=main`], { stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: 16 * 1024 * 1024 });
    writeFileSync(join(out, f), bytes);
  }
  console.log('fonts: fetched from Sttark/sttark-docs main');
  process.exit(0);
} catch {}
const why = 'fonts: the Founders Grotesk files are not in src/styles/fonts/ and none were found (STTARK_FONTS_DIR, ../../sttark-docs, or gh with access to Sttark/sttark-docs).';
if (soft) {
  console.warn(`${why} Pages fall back to Helvetica Neue.`);
  process.exit(0);
}
console.error(why);
process.exit(1);
