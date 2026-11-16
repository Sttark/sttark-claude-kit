import type { APIRoute } from 'astro';
import { SESSION_COOKIE, destroyAllSessions } from '../../lib/session.ts';
import { endPerson } from '../../lib/hub.ts';
import { cookiePath, href } from '../../lib/paths.ts';

// Sign out everywhere: every sign-in and push subscription of this person,
// and every page of theirs that is open. Their Macs stay linked.
export const POST: APIRoute = ({ locals, cookies, redirect }) => {
  if (locals.user) {
    destroyAllSessions(locals.user.email);
    endPerson(locals.user.email);
  }
  cookies.delete(SESSION_COOKIE, { path: cookiePath() });
  return redirect(href('/signin?out=all'));
};
