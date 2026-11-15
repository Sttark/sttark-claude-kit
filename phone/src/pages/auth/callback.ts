import type { APIRoute } from 'astro';
import { SignInRefused, appOrigin, completeLogin } from '../../lib/auth.ts';
import { createSession, takeOauthState, touchPerson } from '../../lib/session.ts';
import { href } from '../../lib/paths.ts';

export const GET: APIRoute = async ({ url, cookies, redirect }) => {
  const state = url.searchParams.get('state');
  const stashed = state ? takeOauthState(state) : null;
  if (!state || !stashed) return redirect(href('/signin?error=expired'));
  try {
    // url.pathname holds BASE_PATH, as the redirect URI Google was given does.
    const callbackUrl = new URL(url.pathname + url.search, appOrigin());
    const person = await completeLogin(callbackUrl, { state, codeVerifier: stashed.codeVerifier, nonce: stashed.nonce });
    touchPerson(person.email, person.name);
    createSession(cookies, person);
    return redirect(href(stashed.returnTo));
  } catch (err) {
    if (err instanceof SignInRefused) {
      console.warn(`[auth] ${err.message}`);
      return redirect(href(`/signin?error=${err.reason}`));
    }
    console.error('[auth] callback failed:', err);
    return redirect(href('/signin?error=failed'));
  }
};
