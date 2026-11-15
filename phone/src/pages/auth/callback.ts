import type { APIRoute } from 'astro';
import { SignInRefused, appOrigin, completeLogin } from '../../lib/auth.ts';
import { createSession, takeOauthState, touchPerson } from '../../lib/session.ts';

export const GET: APIRoute = async ({ url, cookies, redirect }) => {
  const state = url.searchParams.get('state');
  const stashed = state ? takeOauthState(state) : null;
  if (!state || !stashed) return redirect('/signin?error=expired');
  try {
    const callbackUrl = new URL(url.pathname + url.search, appOrigin());
    const person = await completeLogin(callbackUrl, { state, codeVerifier: stashed.codeVerifier, nonce: stashed.nonce });
    touchPerson(person.email, person.name);
    createSession(cookies, person);
    return redirect(stashed.returnTo);
  } catch (err) {
    if (err instanceof SignInRefused) {
      console.warn(`[auth] ${err.message}`);
      return redirect(`/signin?error=${err.reason}`);
    }
    console.error('[auth] callback failed:', err);
    return redirect('/signin?error=failed');
  }
};
