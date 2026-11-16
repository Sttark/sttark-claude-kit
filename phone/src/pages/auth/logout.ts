import type { APIRoute } from 'astro';
import { SESSION_COOKIE, destroySession } from '../../lib/session.ts';
import { endWebSession } from '../../lib/hub.ts';
import { href } from '../../lib/paths.ts';

// Sign out: this phone's sign-in and its push subscription; its open pages'
// sockets close.
export const POST: APIRoute = ({ cookies, redirect }) => {
  const id = cookies.get(SESSION_COOKIE)?.value;
  destroySession(cookies);
  if (id) endWebSession(id);
  return redirect(href('/signin?out=1'));
};
