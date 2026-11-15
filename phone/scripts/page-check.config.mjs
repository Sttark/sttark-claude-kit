// Claude Kit's part of the shared Sttark page check (Sttark/sttark-docs
// page-check/, run through scripts/page-check.mjs): its pages, the servers
// the check starts and who they sign in. check-pages.mjs in that folder
// lists every key a config can have.
//
// The Kit has one kind of person: everyone on the Workrouter roster has the
// same access, and each sees only their own Macs. So the check signs in one
// made-up person, twice: on an empty database with no Mac linked (a dev
// server; --ignore-lock keeps it in the foreground, also when an AI agent
// runs it), and with two linked Macs from the contract's fixtures, one live
// and one asleep (test/sample.mjs), on the built app with its real sockets
// and the fake Mac signed in (test/sample-server.mjs), so each page is
// measured as it is once connected. A pending link page is the link page's
// sample.
import { fileURLToPath } from 'node:url';
import { SAMPLE_LINK } from '../test/sample.mjs';

const PERSON = 'avery.stone@sttark.com';
/** A dev server signed in as one made-up person, never a real one. */
const devServer = (name, person) => ({
  name,
  command: 'npx astro dev --port {port} --ignore-lock',
  env: { DEV_FAKE_USER: person, KIT_DB: `{dir}/${name}.db`, APP_ORIGIN: 'http://localhost:{port}' },
  ready: '/healthz',
});
/** The same person with two Macs: the built app, its sockets and the fake
 *  Mac. It runs first, so its build never overlaps the dev server's start. */
const sampleServer = (name, person) => ({
  name,
  before: 'npx astro build',
  command: 'node test/sample-server.mjs --port {port}',
  env: { DEV_FAKE_USER: person, BASE_PATH: '' },
  ready: '/healthz',
  timeout: 240,
});
/** The sample's pages: the three tabs, Menu, a search, a session of each
 *  group, an archived session, the Mac that is away and one of its
 *  sessions, and a link page waiting for Link. */
const SAMPLE_PAGES = [
  '/menu',
  '/',
  '/?q=lam',
  '/archived',
  '/usage',
  '/s/session_01SampleLaminator',
  '/s/session_01SampleHvacUpdates',
  '/s/session_01SampleSiteMap',
  '/s/session_01SampleOrderLogin',
  '/archived/session_01SampleDoorPi',
  '/mac/mac_2Vd8Rt5Wn1',
  '/s/session_01SampleBinLabels?from=mac%3Amac_2Vd8Rt5Wn1',
  `/link/${SAMPLE_LINK.token}`,
];

/** A page file as a path; sign-in, the error pages and routes are not walked. */
function pagePath(file) {
  if (!file.endsWith('.astro')) return null;
  const p = ('/' + file.replace(/^src\/pages\//, '').replace(/\.astro$/, '').replace(/(^|\/)index$/, '')).replace(/\/$/, '') || '/';
  return ['/404', '/500', '/signin'].includes(p) ? null : p;
}

export default {
  serve: [sampleServer('two-macs', PERSON), devServer('no-mac', PERSON)],
  bases: ['http://localhost:4350'],
  who: async ({ server }) => server ?? 'no-mac',
  // Every page a person can open. Menu comes first: the theme rule runs on
  // a person's first page, and the light / auto / dark choice is on Menu.
  pages: async ({ server }) => (server === 'two-macs' ? SAMPLE_PAGES : ['/menu', '/', '/archived', '/usage']),
  // Sessions, Archived and Usage are one section's tabs, and every other
  // page opens from them or from Menu, so all are one section.
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
    always: ['scripts/page-check.config.mjs', 'src/middleware.ts', 'test/sample.mjs', 'test/sample-server.mjs', 'tools/fake-mac.mjs'],
    // What the middleware only starts once: the roster sync and the daily
    // job. A change to one reaches the pages that import it, not every page.
    services: ['src/lib/roster.ts', 'src/lib/expiry.ts'],
  },
  // Menu is a page, and Remove's confirm and the ⓘ notes say what they
  // open (aria-expanded, aria-controls), so the check finds them itself.
  dialogs: [],
  // Design decisions: { page, rule, reason }, each with its entry in
  // DESIGN-DECISIONS.md at the repo root.
  allow: [
    {
      page: /^\/(?!menu(\?|$))/,
      rule: 'theme',
      reason: 'The light / auto / dark choice is on the Menu page, not in the top bar (DESIGN-DECISIONS.md: Phone pages, Menu); a full run checks it there',
    },
  ],
};
