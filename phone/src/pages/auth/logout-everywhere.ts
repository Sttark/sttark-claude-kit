import type { APIRoute } from 'astro';
import { SESSION_COOKIE, destroyAllSessions } from '../../lib/session.ts';
import { cookiePath, href } from '../../lib/paths.ts';

// Sign out everywhere: every sign-in and push subscription of this person.
// Their Macs stay linked.
export const POST: APIRoute = ({ locals, cookies, redirect }) => {
  if (locals.user) destroyAllSessions(locals.user.email);
  cookies.delete(SESSION_COOKIE, { path: cookiePath() });
  return redirect(href('/signin?out=all'));
};
