// /healthz: whether the database answers, and which commit is running.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { GET } from '../src/pages/healthz.ts';
import { resetDbForTests } from '../src/lib/db.ts';

const call = async () => {
  const res = (await (GET as any)({})) as Response;
  return { status: res.status, body: await res.json(), cache: res.headers.get('cache-control') };
};

beforeEach(() => resetDbForTests());
afterEach(() => {
  vi.unstubAllEnvs();
  resetDbForTests();
});

describe('healthz', () => {
  it('says the database answers, and the build', async () => {
    expect(await call()).toEqual({ status: 200, body: { ok: true, db: true, sha: 'unknown' }, cache: 'no-store' });
  });

  it('answers 503 when the database cannot be opened', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const file = join(mkdtempSync(join(tmpdir(), 'kit-healthz-')), 'a-file');
    writeFileSync(file, '');
    vi.stubEnv('KIT_DB', join(file, 'kit.db'));
    expect(await call()).toMatchObject({ status: 503, body: { ok: false, db: false } });
  });
});
