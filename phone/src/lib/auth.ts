// Google Workspace sign-in with openid-client (the certified client Building
// uses), checked on the server. The authorization request asks Google for
// hd=sttark.com, and the callback checks the ID token's claims itself,
// because hd in the request is only a hint: a verified email, hd sttark.com,
// an @sttark.com address, and a person on the Workrouter roster
// (lib/roster.ts).
import * as oidc from 'openid-client';
import { onRoster, rosterSize } from './roster.ts';
import { appUrl } from './paths.ts';

export { appOrigin } from './paths.ts';

const WORKSPACE_DOMAIN = 'sttark.com';
const HINT = /^[a-z0-9._%+-]+@sttark\.com$/;

export function oauthConfigured(): boolean {
  return Boolean(process.env.VAULT_GOOGLE_CLIENT_ID && process.env.VAULT_GOOGLE_CLIENT_SECRET);
}

/** Why a sign-in was refused; the sign-in page says each in words. */
export type Refusal = 'domain' | 'roster' | 'no-roster';
export class SignInRefused extends Error {
  constructor(readonly reason: Refusal, message: string) {
    super(message);
  }
}

let configPromise: Promise<oidc.Configuration> | undefined;
function config(): Promise<oidc.Configuration> {
  configPromise ??= oidc.discovery(new URL('https://accounts.google.com'), process.env.VAULT_GOOGLE_CLIENT_ID!, process.env.VAULT_GOOGLE_CLIENT_SECRET!);
  return configPromise;
}

/** Google's sign-in, to come back to APP_ORIGIN + BASE_PATH + /auth/callback.
 *  `hint` (a @sttark.com address, else ignored) is the account Google offers
 *  first: the link page passes the Claude Code login the Kit sent. */
export async function beginLogin(hint?: string | null): Promise<{ url: string; state: string; codeVerifier: string; nonce: string }> {
  const c = await config();
  const codeVerifier = oidc.randomPKCECodeVerifier();
  const codeChallenge = await oidc.calculatePKCECodeChallenge(codeVerifier);
  const state = oidc.randomState();
  const nonce = oidc.randomNonce();
  const loginHint = hint?.trim().toLowerCase();
  const url = oidc.buildAuthorizationUrl(c, {
    redirect_uri: appUrl('/auth/callback'),
    scope: 'openid email profile',
    hd: WORKSPACE_DOMAIN,
    state,
    nonce,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
    ...(loginHint && HINT.test(loginHint) ? { login_hint: loginHint } : {}),
  });
  return { url: url.href, state, codeVerifier, nonce };
}

/** The account check on the ID token's claims: a verified @sttark.com
 *  Google account whose person is on the roster. */
export function checkAccount(claims: Record<string, unknown>): { email: string; name: string } {
  const email = typeof claims.email === 'string' ? claims.email.trim().toLowerCase() : '';
  if (claims.email_verified !== true || claims.hd !== WORKSPACE_DOMAIN || !email.endsWith(`@${WORKSPACE_DOMAIN}`)) {
    throw new SignInRefused('domain', `sign-in refused: not a verified @${WORKSPACE_DOMAIN} account`);
  }
  if (!onRoster(email)) {
    if (rosterSize() === 0) throw new SignInRefused('no-roster', 'sign-in refused: no roster has been read from Workrouter yet');
    throw new SignInRefused('roster', 'sign-in refused: not on the Sttark roster');
  }
  const name = typeof claims.name === 'string' && claims.name.trim() ? claims.name.trim() : email;
  return { email, name };
}

export async function completeLogin(
  callbackUrl: URL,
  expected: { state: string; codeVerifier: string; nonce: string },
): Promise<{ email: string; name: string }> {
  const c = await config();
  const tokens = await oidc.authorizationCodeGrant(c, callbackUrl, {
    expectedState: expected.state,
    pkceCodeVerifier: expected.codeVerifier,
    expectedNonce: expected.nonce,
    idTokenExpected: true,
  });
  const claims = tokens.claims();
  if (!claims) throw new Error('no ID token claims');
  return checkAccount(claims as Record<string, unknown>);
}
