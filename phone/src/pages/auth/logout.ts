import type { APIRoute } from 'astro';
import { destroySession } from '../../lib/session.ts';

// Sign out: this phone's sign-in and its push subscription.
export const POST: APIRoute = ({ cookies, redirect }) => {
  destroySession(cookies);
  return redirect('/signin?out=1');
};
