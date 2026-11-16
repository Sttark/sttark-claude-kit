import type { APIRoute } from 'astro';
import { removeOwnMac } from '../../../lib/macs.ts';
import { href } from '../../../lib/paths.ts';

// Menu > Macs > Remove (after its confirm): the person's own Mac only. Its
// row and records stay, what it sent goes, and its socket closes
// (lib/macs.ts, lib/hub.ts).
export const POST: APIRoute = ({ params, locals, redirect }) => {
  const user = locals.user!;
  if (!removeOwnMac(user, params.id ?? '')) return new Response('That Mac is not linked to your account.', { status: 404 });
  return redirect(href('/menu'), 303);
};
