// Is the shared style file still a byte-for-byte copy of the canonical one
// in sttark-docs (main)? Prints what to do when it is not. Exit 1 on a
// difference, 2 when the canonical copy could not be read. (Building's
// check, for the one shared file this app carries.)
//   npm run check:style
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

// [path in sttark-docs, path here]
const FILES = [['app/src/styles/sttark-shared.css', 'src/styles/sttark-shared.css']];

function canonical(path) {
  try {
    const b64 = execFileSync('gh', ['api', `repos/Sttark/sttark-docs/contents/${path}?ref=main`, '--jq', '.content'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    return Buffer.from(b64.replace(/\s/g, ''), 'base64').toString('utf8');
  } catch {}
  for (const dir of [process.env.STTARK_DOCS, '../../sttark-docs'].filter(Boolean)) {
    if (!existsSync(`${dir}/${path}`)) continue;
    try {
      return execFileSync('git', ['-C', dir, 'show', `origin/main:${path}`], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    } catch {
      return readFileSync(`${dir}/${path}`, 'utf8');
    }
  }
  return undefined;
}

let code = 0;
for (const [theirsPath, oursPath] of FILES) {
  const name = oursPath.split('/').pop();
  const theirs = canonical(theirsPath);
  if (theirs === undefined) {
    console.error(`check:style could not read the canonical ${name} from Sttark/sttark-docs main (gh, STTARK_DOCS, or ../../sttark-docs).`);
    code = Math.max(code, 2);
    continue;
  }
  const ours = existsSync(oursPath) ? readFileSync(oursPath, 'utf8') : null;
  if (theirs === ours) {
    console.log(`${name} matches sttark-docs main.`);
  } else {
    console.error(`${name} differs from sttark-docs main. Copy the canonical file over:\n  gh api repos/Sttark/sttark-docs/contents/${theirsPath}?ref=main --jq .content | base64 -d > ${oursPath}`);
    code = Math.max(code, 1);
  }
}
process.exit(code);
