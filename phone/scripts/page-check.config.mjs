// Claude Kit's part of the shared Sttark page check (Sttark/sttark-docs
// page-check/, run through scripts/page-check.mjs): its pages, the server
// the check starts and who it signs in. check-pages.mjs in that folder lists
// every key a config can have.
//
// The Kit has one kind of person: everyone on the Workrouter roster has the
// same access, and each sees only their own Macs. So the check starts one
// dev server, on its own empty database, signed in as one made-up person
// with no Mac linked. --ignore-lock keeps Astro's dev server in the
// foreground for the check, also when an AI agent runs it.
import { fileURLToPath } from 'node:url';

/** A dev server signed in as one made-up person, never a real one. */
const devServer = (name, person) => ({
  name,
  command: 'npx astro dev --port {port} --ignore-lock',
  env: { DEV_FAKE_USER: person, KIT_DB: `{dir}/${name}.db` },
  ready: '/healthz',
});

/** A page file as a path; sign-in, the error pages and routes are not walked. */
function pagePath(file) {
  if (!file.endsWith('.astro')) return null;
  const p = ('/' + file.replace(/^src\/pages\//, '').replace(/\.astro$/, '').replace(/(^|\/)index$/, '')).replace(/\/$/, '') || '/';
  return ['/404', '/500', '/signin'].includes(p) ? null : p;
}

export default {
  serve: [devServer('person', 'avery.stone@sttark.com')],
  bases: ['http://localhost:4350'],
  who: async ({ server }) => server ?? 'person',
  // Every page a person can open: the three tabs, and Macs from Menu.
  pages: async () => ['/', '/archived', '/usage', '/macs'],
  // Sessions, Archived and Usage are one section's tabs, and Macs opens from
  // Menu, so all four are one section.
  sectionOf: () => '/',
  sectionNames: ['Claude Kit'],
  // The tab row: under the top bar on a desktop, at the foot on a phone
  // (DESIGN-DECISIONS.md, Phone pages).
  selectors: { tabRow: '.tabbar', tabs: '.tabbar a' },
  changed: {
    // The app is phone/, not the repo root: paths are from here.
    root: fileURLToPath(new URL('..', import.meta.url)),
    pagePath,
    // Files no page imports that reach every page: this config, and the
    // middleware (sign-in runs on every request).
    always: ['scripts/page-check.config.mjs', 'src/middleware.ts'],
    // What the middleware only starts once: the roster sync and the daily
    // job. A change to one reaches the pages that import it, not every page.
    services: ['src/lib/roster.ts', 'src/lib/expiry.ts'],
  },
  // Menu on a phone: Macs, who is signed in, the theme switch and Sign out.
  // Opening it presses nothing in it.
  dialogs: [{ page: '/', name: 'Menu', open: '#menu-btn', dialog: '#topbar-more', widths: [390] }],
  // Design decisions: { page, rule, reason }, each with its entry in
  // DESIGN-DECISIONS.md at the repo root.
  allow: [],
};
