import type { APIRoute } from 'astro';
import { beginLogin, oauthConfigured } from '../../lib/auth.ts';
import { stashOauthState } from '../../lib/session.ts';
import { href } from '../../lib/paths.ts';

// Starts Google's sign-in. next is a path inside the app to come back to;
// hint (optional) is the account Google offers first.
export const GET: APIRoute = async ({ url, redirect }) => {
  if (!oauthConfigured()) return redirect(href('/signin?error=unconfigured'));
  const next = url.searchParams.get('next') ?? '/';
  const returnTo = next.startsWith('/') && !next.startsWith('//') ? next : '/';
  const { url: authUrl, state, codeVerifier, nonce } = await beginLogin(url.searchParams.get('hint'));
  stashOauthState(state, { codeVerifier, nonce, returnTo });
  return redirect(authUrl);
};
