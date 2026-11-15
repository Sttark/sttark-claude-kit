// Sign-in is checked on the server: a verified @sttark.com Google account
// whose person is on the Workrouter roster. Google's answer is stood in for.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const claims = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock('openid-client', () => ({
  discovery: async () => ({}),
  authorizationCodeGrant: async () => ({ claims: () => claims.value }),
}));
import { SignInRefused, completeLogin } from '../src/lib/auth.ts';
import { resetDbForTests } from '../src/lib/db.ts';
import { storeSampleRoster } from './helpers.ts';

const signIn = (c: Record<string, unknown>) => {
  claims.value = c;
  return completeLogin(new URL('http://localhost/auth/callback?code=1&state=s'), { state: 's', codeVerifier: 'v', nonce: 'n' });
};
const refusal = async (c: Record<string, unknown>) => {
  try {
    await signIn(c);
    return 'accepted';
  } catch (e) {
    return e instanceof SignInRefused ? e.reason : `error: ${(e as Error).message}`;
  }
};
const ok = { email: 'ada.anvil@sttark.com', email_verified: true, hd: 'sttark.com', name: 'Ada Anvil' };

beforeEach(() => {
  resetDbForTests();
  storeSampleRoster();
});

describe('sign-in', () => {
  it('accepts a verified @sttark.com account on the roster', async () => {
    await expect(signIn(ok)).resolves.toEqual({ email: 'ada.anvil@sttark.com', name: 'Ada Anvil' });
    // Google may send the address in another case; the roster is lower case.
    await expect(signIn({ ...ok, email: 'Ada.Anvil@Sttark.com' })).resolves.toMatchObject({ email: 'ada.anvil@sttark.com' });
  });

  it.each([
    ['another domain', { email: 'ada.anvil@gmail.com', email_verified: true, hd: 'gmail.com' }],
    ['another domain with hd sttark.com', { email: 'ada.anvil@gmail.com', email_verified: true, hd: 'sttark.com' }],
    ['a look-alike domain', { email: 'ada.anvil@sttark.com.evil.com', email_verified: true, hd: 'sttark.com' }],
    ['a subdomain', { email: 'ada.anvil@mail.sttark.com', email_verified: true, hd: 'sttark.com' }],
    ['no hosted domain', { email: 'ada.anvil@sttark.com', email_verified: true }],
    ['a personal Google account', { email: 'ada.anvil@sttark.com', email_verified: true, hd: 'evil.com' }],
  ])('refuses %s', async (_, c) => {
    expect(await refusal(c)).toBe('domain');
  });

  it('refuses an unverified email', async () => {
    expect(await refusal({ ...ok, email_verified: false })).toBe('domain');
    expect(await refusal({ ...ok, email_verified: 'true' })).toBe('domain');
  });

  it('refuses a person off the roster', async () => {
    expect(await refusal({ ...ok, email: 'jules.park@sttark.com', name: 'Jules Park' })).toBe('roster');
  });

  it('refuses everyone before the first roster is read', async () => {
    resetDbForTests();
    expect(await refusal(ok)).toBe('no-roster');
  });
});
