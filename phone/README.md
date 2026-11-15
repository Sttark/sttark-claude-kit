# Kit on your phone: the server

The web app at **kit.sttark.com**: a person's Sttark Claude Kit sessions on
their phone. It is an Astro server with a SQLite database, run on the
sttark-building Linode behind nginx. The design is in `DESIGN.md` beside
this file, and the messages between the server, the Kit on each Mac and the
phone pages are in `asyncapi.yaml` and `schema/`.

What it serves:

| Path | What |
|---|---|
| `/` | **Sessions**, the first of three tabs |
| `/archived` | **Archived** |
| `/usage` | **Usage** |
| `/macs` | **Macs**, from Menu: the person's linked Macs, and **Sign out everywhere** |
| `/signin` | Sign in with Google |
| `/auth/login`, `/auth/callback` | The Google sign-in and its return |
| `/auth/logout`, `/auth/logout-everywhere` | Sign out (POST): this phone, or every phone and browser |
| `/healthz` | `{"ok": true, "db": true, "sha": "<commit>"}`: the database answers, and which commit runs; 503 when the database does not |

Until a person links a Mac, each page says "No Mac linked yet" and how to
link one. The tabs sit at the foot of a phone's screen and under the top
bar on a desktop (`../DESIGN-DECISIONS.md`, Phone pages).

## Run it

```bash
npm install
cp .env.example .env    # DEV_FAKE_USER signs you in as a made-up person
npm run dev             # http://localhost:4350
npm test                # vitest
npm run build           # dist/
npm run check           # TypeScript
npm run check:style     # sttark-shared.css matches sttark-docs main
npm run check:pages:changed   # the shared page check on the pages you changed
```

`npm run dev` and `npm run build` first copy the licensed fonts in (Fonts,
below). An AI agent's `npm run dev` runs in the background (Astro's own
choice); `npx astro dev stop` stops it.

**Production** runs `node server.mjs` in a folder that holds `server.mjs`,
`dist/`, `package.json` and the production `node_modules`. It serves, on
`HOST` and `PORT`: the built files in `dist/client`, then Astro's pages
(the node adapter in middleware mode), and the WebSocket upgrades. It sets
`NODE_ENV=production` unless told otherwise, and makes one request at boot
so the roster sync and the daily job start at once. nginx passes `/` and,
with the Upgrade headers, `/mac` and `/live` to it, with `Host` and
`X-Forwarded-Proto` (the form posts' origin check needs both).

**Sockets.** `server.mjs` passes every upgrade request to the handler set
with `onUpgrade()` (`src/lib/upgrade.ts`) and refuses it while none is set.

## Environment

| Variable | Needed | What |
|---|---|---|
| `APP_ORIGIN` | production | `https://kit.sttark.com`. Google returns to `APP_ORIGIN/auth/callback`; an `https` origin makes the sign-in cookie secure. Default `http://localhost:4350` |
| `VAULT_GOOGLE_CLIENT_ID`, `VAULT_GOOGLE_CLIENT_SECRET` | production | The shared Sttark Workspace sign-in client. Unset, Sign in with Google says it is not set up |
| `VAULT_ORG_SYNC_TOKEN` | production | The Kit's own read-only Workrouter org-sync key (`sk_org_...`), for the hourly roster. Unset, the roster stays as stored |
| `KIT_DB` | production | The database file, default `data/kit.db` (made with its folder) |
| `HOST`, `PORT` | optional | Where `server.mjs` listens, default `127.0.0.1` and `4350` |
| `WORKROUTER_URL` | optional | Workrouter's base URL, default `https://www.sttark.com` |
| `DEV_FAKE_USER` | local only | Signs everyone in as this address. Ignored when `NODE_ENV` is `production` |
| `STTARK_FONTS_DIR` | build only | A folder with the font files (Fonts, below) |

## Sign-in

- **Google, checked on the server** (`src/lib/auth.ts`): the callback
  checks the ID token's claims itself. A verified email, hosted domain
  `sttark.com` and an `@sttark.com` address, else "Only a verified
  @sttark.com Google account can sign in." Then the person must be on the
  Workrouter roster as last read, else "Your account is not on the Sttark
  roster". Before the first roster is read, nobody can sign in.
- **Sign-ins** (`src/lib/session.ts`): a random 256-bit id in the database
  and in an httpOnly cookie, nothing else in the browser. 30 days, rolled
  forward at most once a day while used, in the database and the cookie.
- **Sign out** ends this sign-in and its push subscription. **Sign out
  everywhere** (Macs page) ends every sign-in and push subscription of the
  person; their Macs stay linked.
- **Access** is one rule: everyone on the roster, and each person sees only
  their own Macs. So there is no access page.

## The roster

Every hour, and at start, the server reads Workrouter's org-sync feed
(`GET {WORKROUTER_URL}/org-sync/v1` with `VAULT_ORG_SYNC_TOKEN`), the feed
docs.sttark.com and Building read, and keeps the active roster
(`src/lib/roster.ts`). A read that fails or looks wrong (an HTTP error, a
refused key, no employees, fewer than 10 people) keeps the last good
roster, so nobody's access changes, and logs `[roster] ALERT`. A good read
logs `[roster] synced from Workrouter: N people on the roster`; a 304 keeps
the roster. Someone who leaves the roster loses access at that sync: their
sign-ins and push subscriptions end, and their Macs are removed, each with
a record.

## Storage

One SQLite file in WAL mode, `src/lib/db.ts`. A schema change is a new
statement there that is safe to run on every start (`CREATE ... IF NOT
EXISTS`, or a column in `ADDED_COLUMNS`). Times are Unix seconds. How long
each kind of row is kept:

| Table | What | Kept |
|---|---|---|
| `web_sessions` | Sign-ins | 30 days after last use |
| `oauth_states` | Google sign-ins under way | 10 minutes |
| `people` | Who has signed in | For good |
| `roster`, `meta` | The last good roster, and the sync's state | Replaced by each good sync |
| `macs` | Linked Macs and their public keys | For good; a removed Mac keeps its row, with when, why and by whom |
| `links` | Link pages waiting for a sign-in | 1 day |
| `snapshots`, `archived` | The last snapshot and archived list each Mac sent | Replaced each time; deleted when the Mac is removed |
| `push_subs` | Web Push subscriptions, one per phone | Until sign-out, or the push service says it is gone |
| `pushes_sent` | Needs you pushes sent | 2 days |
| `records` | Every change, with who made it | **1 year** |

**Records** are append only. SQLite triggers refuse to change or replace a
record, and refuse to delete one under a year old. The daily job
(`src/lib/expiry.ts`, at start and every 24 hours) deletes records over a
year old; that is the only way a record goes. It also takes out what the
table above keeps for a while.

## Fonts

Founders Grotesk is licensed to Sttark and this repo is public, so the font
files are never committed (`.gitignore`). `npm run fonts` copies them to
`src/styles/fonts/`, where `sttark-shared.css` looks for them, from the
first of: `STTARK_FONTS_DIR`; a sttark-docs checkout beside this repo
(`../../sttark-docs`); Sttark/sttark-docs main through your `gh` sign-in.
It fails when it finds none; `npm run dev` and `npm run build` run it in a
mode that only warns, and without the files pages fall back to Helvetica
Neue. A deploy runs `npm run fonts` before `npm run build`.

## Checks

- **Tests** (`npm test`, `test/`): sign-in refuses another domain, an
  unverified email and a person off the roster; sign-ins end after 30 days
  unused and roll while used; Sign out and Sign out everywhere; a failed
  roster sync keeps the last good roster; leaving the roster ends access;
  records refuse change and delete, and the daily job's expiry; the gate;
  `/healthz`; and no real person's address anywhere in `phone/`.
- **The page check** (`scripts/page-check.mjs`, the shared Sttark check
  from Sttark/sttark-docs `page-check/`; this app's part is
  `scripts/page-check.config.mjs`): every page at 390 and 1280 px, light and
  dark, as one made-up person on an empty database.
- **CI** (`../.github/workflows/phone-checks.yml`): the tests and the build
  on each change under `phone/`, then the page check and, on pull requests,
  the AI review against the guide.

## Files

| File | What it is |
|---|---|
| `server.mjs` | The production server: built files, Astro's handler, the WebSocket hook |
| `astro.config.mjs` | Astro: server output, the node adapter in middleware mode, the build's commit |
| `src/middleware.ts` | The gate: who is asking; starts the roster sync and the daily job |
| `src/lib/db.ts` | The database: schema, triggers |
| `src/lib/auth.ts`, `src/lib/session.ts` | Google sign-in and sign-ins |
| `src/lib/roster.ts` | The roster sync |
| `src/lib/records.ts`, `src/lib/expiry.ts` | Change records, and the daily job |
| `src/lib/macs.ts`, `src/lib/upgrade.ts` | Linked Macs; the WebSocket hook |
| `src/layouts/Base.astro`, `src/components/NoMac.astro` | The page frame (top bar, Menu, tabs); the empty state |
| `src/styles/sttark-shared.css`, `src/styles/app.css` | The guide's shared style file, byte for byte, and this app's own |
| `scripts/fonts.mjs`, `scripts/check-style.mjs` | The licensed fonts; the shared style file check |
| `test/` | The tests, and `sample-people.json`, the made-up people they use |
