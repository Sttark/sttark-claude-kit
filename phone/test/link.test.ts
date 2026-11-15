// Linking a Mac once (schema/link.v1.json): the Kit's request, its poll,
// the link page's states, Link (once, with a record), and the page's
// 10 minutes. The two routes are called as Astro calls them.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { generateKeyPairSync } from 'node:crypto';
import { db, resetDbForTests } from '../src/lib/db.ts';
import { approveLink, linkHint, linkPage, pollLink, resetLinkRateForTests, LINK_TTL_S } from '../src/lib/link.ts';
import { checkLink } from '../src/lib/contract.ts';
import { qrSvg } from '../src/lib/qr.ts';
import { POST } from '../src/pages/api/mac/link.ts';
import { GET } from '../src/pages/api/mac/link/[poll].ts';
import { publicKeyOf } from '../tools/fake-mac.mjs';
import { storeSampleRoster } from './helpers.ts';
import { newMac } from './kit.ts';

const ADA = { email: 'ada.anvil@sttark.com', name: 'Ada Anvil' };
const BIX = { email: 'bix.dowel@sttark.com', name: 'Bix Dowel' };
const T0 = Math.floor(Date.now() / 1000);
const HOME = '198.51.100.7';

function request(over: Record<string, unknown> = {}) {
  const k = newMac(String(over.name ?? 'MacBook Pro'));
  return { k, body: { v: 1, mac: k.mac, name: k.name, kit: '1.140', key: publicKeyOf(k), kind: 'secure-enclave', hint: null, ...over } };
}
const post = async (body: unknown, headers: Record<string, string> = {}, raw?: string) => {
  const res = (await (POST as any)({
    request: new Request('http://localhost:4350/api/mac/link', { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: raw ?? JSON.stringify(body) }),
    clientAddress: HOME,
  })) as Response;
  return { status: res.status, body: await res.json() };
};
const poll = async (token: string) => {
  const res = (await (GET as any)({ params: { poll: token } })) as Response;
  return { status: res.status, body: await res.json() };
};
const tokenOf = (link: string) => link.split('/link/')[1];
const count = (sql: string) => (db().prepare(sql).get() as { n: number }).n;

beforeEach(() => {
  resetDbForTests();
  resetLinkRateForTests();
  storeSampleRoster();
  vi.stubEnv('APP_ORIGIN', 'https://kit.sttark.com');
});
afterEach(() => vi.unstubAllEnvs());

describe('the link request', () => {
  it('answers with the link page, a poll token and a code, as the contract says', async () => {
    const { body } = request({ hint: 'ada.anvil@sttark.com' });
    const r = await post(body);
    expect(r.status).toBe(201);
    expect(checkLink('answer', r.body)).toEqual({ ok: true });
    expect(r.body.link).toMatch(/^https:\/\/kit\.sttark\.com\/link\/[A-Za-z0-9_-]{43}$/);
    expect(r.body.code).toMatch(/^[A-HJ-NP-Z]{4}$/);
    expect(r.body.expires_at - T0).toBeGreaterThanOrEqual(LINK_TTL_S - 2);
    // Only hashes of the tokens are kept.
    const row = db().prepare('SELECT token_hash, poll_hash, address, hint FROM links').get() as Record<string, string>;
    expect(row.token_hash).not.toContain(tokenOf(r.body.link));
    expect(row.poll_hash).not.toBe(r.body.poll);
    expect(row).toMatchObject({ address: HOME, hint: 'ada.anvil@sttark.com' });
    expect(linkHint(tokenOf(r.body.link))).toBe('ada.anvil@sttark.com');
  });

  it('refuses a field it does not know, a wrong key, and what is not JSON', async () => {
    const { body } = request();
    expect(await post({ ...body, prompt: 'x' })).toMatchObject({ status: 400, body: { error: 'bad_request' } });
    const { body: noHint } = request();
    delete (noHint as any).hint;
    expect((await post(noHint)).status).toBe(400);
    expect((await post({ ...body, hint: 'someone@example.com' })).status).toBe(400);
    const p384 = generateKeyPairSync('ec', { namedCurve: 'P-384' }).publicKey.export({ format: 'der', type: 'spki' }).toString('base64');
    expect(await post({ ...body, key: p384 })).toMatchObject({ status: 400, body: { words: expect.stringMatching(/P-256/) } });
    expect((await post({ ...body, key: 'A'.repeat(120) })).status).toBe(400);
    expect((await post(null, {}, 'not json')).status).toBe(400);
    expect((await post(body, { 'content-type': 'text/plain' })).status).toBe(400);
    expect(await post(null, {}, JSON.stringify({ ...body, name: 'x'.repeat(9000) }))).toMatchObject({ status: 413, body: { error: 'too_large' } });
    expect(count('SELECT count(*) AS n FROM links')).toBe(0);
  });

  it('never links a Mac id twice, and limits requests from one address', async () => {
    const { k, body } = request();
    const first = await post(body);
    approveLink(tokenOf(first.body.link), ADA);
    expect(await post(body)).toMatchObject({ status: 409, body: { error: 'mac_taken' } });
    for (let i = 0; i < 18; i++) await post(request().body);
    expect((await post(request().body)).status).toBe(429);
    expect(k.mac).toBeTruthy();
  });
});

describe('linking', () => {
  it('works once: the Mac is saved to the person with a record, and the poll says linked', async () => {
    const { k, body } = request();
    const r = await post(body);
    const token = tokenOf(r.body.link);
    expect(await poll(r.body.poll)).toEqual({ status: 200, body: { status: 'waiting', email: null, name: null } });
    expect(linkPage(token, ADA.email, HOME)).toMatchObject({ kind: 'ask', macName: 'MacBook Pro', kit: '1.140', code: r.body.code, showCode: false });
    expect(approveLink(token, ADA)).toEqual({ kind: 'linked', macName: 'MacBook Pro', mine: true });
    expect(approveLink(token, ADA)).toEqual({ kind: 'linked', macName: 'MacBook Pro', mine: true });
    expect(approveLink(token, BIX)).toEqual({ kind: 'linked', macName: 'MacBook Pro', mine: false });
    expect(db().prepare('SELECT id, email, name, public_key, key_kind, kit_version FROM macs').all()).toEqual([
      { id: k.mac, email: ADA.email, name: 'MacBook Pro', public_key: publicKeyOf(k), key_kind: 'secure-enclave', kit_version: '1.140' },
    ]);
    expect(db().prepare('SELECT who, who_name, mac_id, action, after, result FROM records').all()).toEqual([
      { who: ADA.email, who_name: 'Ada Anvil', mac_id: k.mac, action: 'link_mac', after: '{"linked":true,"key":"secure-enclave"}', result: 'ok' },
    ]);
    const answer = await poll(r.body.poll);
    expect(answer).toEqual({ status: 200, body: { status: 'linked', email: ADA.email, name: 'Ada Anvil' } });
    expect(checkLink('poll', answer.body)).toEqual({ ok: true });
  });

  it('expires after 10 minutes without Link', async () => {
    const r = await post(request().body);
    const token = tokenOf(r.body.link);
    const later = T0 + LINK_TTL_S + 5;
    expect(linkPage(token, ADA.email, HOME, later)).toEqual({ kind: 'expired', macName: 'MacBook Pro' });
    expect(approveLink(token, ADA, later)).toEqual({ kind: 'expired', macName: 'MacBook Pro' });
    expect(pollLink(r.body.poll, later)).toEqual({ status: 'expired', email: null, name: null });
    expect(count('SELECT count(*) AS n FROM macs')).toBe(0);
    expect(await poll('A'.repeat(43))).toEqual({ status: 404, body: { status: 'expired', email: null, name: null } });
    expect(linkPage('made-up', ADA.email, HOME)).toEqual({ kind: 'unknown' });
  });

  it('shows the code when the browser is not on the address the Mac asked from', async () => {
    const r = await post(request().body);
    const token = tokenOf(r.body.link);
    expect(linkPage(token, ADA.email, '203.0.113.9')).toMatchObject({ kind: 'ask', showCode: true });
    expect(linkPage(token, ADA.email, null)).toMatchObject({ kind: 'ask', showCode: true });
  });

  it('a Mac id linked by another page, and a person with 20 Macs, cannot link', async () => {
    const { body } = request();
    const one = tokenOf((await post(body)).body.link);
    const two = tokenOf((await post(body)).body.link);
    approveLink(one, ADA);
    expect(linkPage(two, ADA.email, HOME)).toEqual({ kind: 'taken', macName: 'MacBook Pro' });
    expect(approveLink(two, BIX).kind).toBe('taken');
    expect(count('SELECT count(*) AS n FROM macs')).toBe(1);
    for (let i = 0; i < 19; i++) {
      resetLinkRateForTests();
      approveLink(tokenOf((await post(request({ name: `Mac ${i}` }).body)).body.link), ADA);
    }
    const full = tokenOf((await post(request({ name: 'One too many' }).body)).body.link);
    expect(linkPage(full, ADA.email, HOME)).toEqual({ kind: 'full', macName: 'One too many' });
    expect(approveLink(full, ADA).kind).toBe('full');
    expect(count("SELECT count(*) AS n FROM macs WHERE email = 'ada.anvil@sttark.com'")).toBe(20);
  });

  it('under BASE_PATH /kit, the link page is under /kit', async () => {
    vi.stubEnv('BASE_URL', '/kit/');
    vi.stubEnv('APP_ORIGIN', 'https://building.sttark.com');
    const r = await post(request().body);
    expect(r.body.link).toMatch(/^https:\/\/building\.sttark\.com\/kit\/link\/[A-Za-z0-9_-]{43}$/);
    expect(checkLink('answer', r.body)).toEqual({ ok: true });
  });

  it('draws a QR code of the address', () => {
    const svg = qrSvg('https://kit.sttark.com/', 'QR code for kit.sttark.com');
    expect(svg).toMatch(/^<svg [^>]*viewBox="0 0 (\d+) \1"[^>]*aria-label="QR code for kit\.sttark\.com"><path fill="currentColor" d="(M\d+ \d+h1v1h-1z)+"\/><\/svg>$/);
  });
});
