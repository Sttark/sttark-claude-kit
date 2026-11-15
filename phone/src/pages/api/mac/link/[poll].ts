import type { APIRoute } from 'astro';
import { pollLink } from '../../../../lib/link.ts';

// GET /api/mac/link/<poll>: the Kit asks every 2 seconds whether its person
// clicked Link (schema/link.v1.json, poll).
export const GET: APIRoute = ({ params }) => {
  const answer = pollLink(String(params.poll ?? ''));
  return new Response(JSON.stringify(answer ?? { status: 'expired', email: null, name: null }), {
    status: answer ? 200 : 404,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
};
