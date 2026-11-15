// No person is written into the app (Sign-in and Access): every @sttark.com
// address in phone/ is one of the made-up people in sample-people.json.
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const allowed = new Set<string>(JSON.parse(readFileSync(join(root, 'test', 'sample-people.json'), 'utf8')).addresses);
const SKIP = new Set(['node_modules', 'dist', '.astro', 'data', 'fonts']);
const TEXT = /\.(ts|mjs|js|astro|css|json|md|yml|yaml|svg|txt|example)$/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    if (SKIP.has(f) || f === 'package-lock.json') return [];
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : TEXT.test(f) || f.startsWith('.env') ? [p] : [];
  });
}

describe('people', () => {
  it('names no real person', () => {
    const found: string[] = [];
    for (const f of files(root)) {
      for (const m of readFileSync(f, 'utf8').matchAll(/[a-z0-9._%+-]+@sttark\.com/gi)) {
        if (!allowed.has(m[0].toLowerCase())) found.push(`${relative(root, f)}: ${m[0]}`);
      }
    }
    expect(found).toEqual([]);
  });
});
