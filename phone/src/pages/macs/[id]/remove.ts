import type { APIRoute } from 'astro';
import { removeMac } from '../../../lib/macs.ts';
import { href } from '../../../lib/paths.ts';

// Menu > Macs > Remove (after its confirm): the person's own Mac only.
export const POST: APIRoute = ({ params, locals, redirect }) => {
  const user = locals.user!;
  if (!removeMac(user, params.id ?? '')) return new Response('That Mac is not linked to your account.', { status: 404 });
  return redirect(href('/menu'), 303);
};
