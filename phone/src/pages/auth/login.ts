import type { APIRoute } from 'astro';
import { beginLogin, oauthConfigured } from '../../lib/auth.ts';
import { stashOauthState } from '../../lib/session.ts';
import { href } from '../../lib/paths.ts';

export const GET: APIRoute = async ({ url, redirect }) => {
  if (!oauthConfigured()) return redirect(href('/signin?error=unconfigured'));
  // next is the app's own path (without BASE_PATH), as the gate sends it.
  const next = url.searchParams.get('next') ?? '/';
  const returnTo = next.startsWith('/') && !next.startsWith('//') ? next : '/';
  const { url: authUrl, state, codeVerifier, nonce } = await beginLogin();
  stashOauthState(state, { codeVerifier, nonce, returnTo });
  return redirect(authUrl);
};
