import type { APIRoute } from 'astro';
import { href } from '../lib/paths.ts';

// The web app manifest: what a phone needs to add Claude Kit to its Home
// Screen as an app of its own (on iPhone, the only way it gets notices).
// Its address, start and scope are under BASE_PATH, so the app at
// building.sttark.com/kit is a different app from Building. Public: phones
// fetch it without the sign-in cookie. The icons are the Kit's own (the
// Sttark icon script, Lucide inbox; ?v= changes with them).
export const ICON_V = '?v=2';

export function manifest() {
  return {
    id: href('/'),
    name: 'Claude Kit',
    short_name: 'Claude Kit',
    description: 'Your Claude Code sessions from the Sttark Claude Kit on your Macs.',
    lang: 'en',
    start_url: href('/'),
    scope: href('/'),
    display: 'standalone',
    background_color: '#000000',
    theme_color: '#000000',
    icons: [
      { src: href(`/icon-192.png${ICON_V}`), sizes: '192x192', type: 'image/png' },
      { src: href(`/icon-512.png${ICON_V}`), sizes: '512x512', type: 'image/png' },
      { src: href(`/icon-maskable-512.png${ICON_V}`), sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
}

export const GET: APIRoute = () =>
  new Response(JSON.stringify(manifest(), null, 2) + '\n', {
    headers: { 'content-type': 'application/manifest+json; charset=utf-8', 'cache-control': 'no-cache' },
  });
