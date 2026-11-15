import type { APIRoute } from 'astro';
import { destroySession } from '../../lib/session.ts';
import { href } from '../../lib/paths.ts';

// Sign out: this phone's sign-in and its push subscription.
export const POST: APIRoute = ({ cookies, redirect }) => {
  destroySession(cookies);
  return redirect(href('/signin?out=1'));
};
