# Kit on your phone: the server

The web app at **kit.sttark.com**: a person's Sttark Claude Kit sessions on
their phone. It is an Astro server with a SQLite database, run on the
sttark-building Linode behind its own nginx site, which passes every path
to it. The design is in `DESIGN.md` beside this file, and the messages
between the server, the Kit on each Mac and the phone pages are in
`asyncapi.yaml` and `schema/`. It started at building.sttark.com/kit; the
code serves either way, by `APP_ORIGIN` and `BASE_PATH` only (Environment,
below).

What it serves (under `BASE_PATH`, Environment below):

| Path | What |
|---|---|
| `/` | **Sessions**, the first of three tabs: the four groups (Needs you first; a working row shows its last progress check-in under it; a bell with a line through it after the name of a session whose alerts are off, as each session starts until the person turns them on), Idle with a message, Macs away, the usage strip. `?q=` searches the names; `?find=1` shows the search field |
| `/s/<cse>` | **One session**: what it does (with its last progress check-in while it works), Open in Claude, the messages the Kit kept for it while alerts are off, its waits (Stop, Bring it back now, Stop waiting), effort and Auto, At the usage limit, its Alerts switch, its changes from the phone. `?from=usage`, `archived` or `mac:<id>` sets the way back |
| `/archived` | **Archived**, grouped by day; `?q=` searches names and folders, and also finds the sessions under Waiting on someone else, in their own group (a row opens it under Sessions) |
| `/archived/<cse>` | One archived session, with **Bring it back** |
| `/usage` | **Usage**: the 5-hour and weekly limits, the sessions held at them, the Use credits setting, and **By session** (The pages, below): `?p=today`, `7d` (the default), `30d` or `custom` with `from` and `to` (days, `2026-11-02`); `?all=1` shows every row |
| `/mac/<id>` | One Mac's sessions; for a Mac that is away, its last list "As of" its time, in gray, with no buttons |
| `/menu` | **Menu**: the Macs (state, last seen, **Remove**), **Sign out everywhere**, **Needs you notices** on this phone (Needs you notices, below), Light / Auto / Dark, **Sign out** |
| `/macs` | Goes to `/menu` |
| `/macs/<id>/remove` | Remove (POST, from Menu after its confirm): the person's own Mac only, with a record |
| `/signin` | Sign in with Google |
| `/auth/login`, `/auth/callback` | The Google sign-in and its return |
| `/auth/logout`, `/auth/logout-everywhere` | Sign out (POST): this phone, or every phone and browser |
| `/healthz` | `{"ok": true, "db": true, "sha": "<commit>"}`: the database answers, and which commit runs; 503 when the database does not |
| `/link/<token>` | The link page a Mac's Kit opens: sign in, then **Link** (Linking a Mac, below) |
| `/api/mac/link`, `/api/mac/link/<poll>` | The Kit asks to link (POST) and polls for the answer (GET); no sign-in (`schema/link.v1.json`) |
| `/api/push/subscribe`, `/api/push/notices`, `/api/push/state`, `/api/push/key` | Menu's notices switch and the service worker: this phone's subscription, its on or off, what the server knows of it, and the key to subscribe with (JSON from this site only; Needs you notices, below) |
| `/site.webmanifest`, `/sw.js` | The web app manifest (start and scope under `BASE_PATH`) and the service worker; no sign-in |
| `/favicon.svg`, `/favicon.ico`, `/apple-touch-icon.png`, `/icon-192.png`, `/icon-512.png`, `/icon-maskable-512.png`, `/notice-badge.png` | The Kit's icons (`public/`), and the small one Android shows beside a notice; no sign-in |
| `/mac` | Each linked Mac's WebSocket (The sockets, below) |
| `/live` | The phone pages' WebSocket (The sockets, below) |

Until a person links a Mac, each page says "No Mac linked yet" and how to
link one. The tabs sit at the foot of a phone's screen and under the top
bar on a desktop (`../DESIGN-DECISIONS.md`, Phone pages).

## The pages

The clickable prototype the owner chose is the picture for every page's
layout, words and behavior. Each page is drawn twice by the same code
(`src/view/render.ts`):

1. **On the server**, from the last snapshot and archived list each Mac
   sent (the database, `src/lib/state.ts`), so a page shows at once with no
   script.
2. **In the browser** (`src/scripts/app.ts`): the page opens `/live`, sends
   `hello` (and `open_archived` on Archived), and draws itself again, in
   place, from each `macs`, `snapshot`, `archived` and `record` message. It
   draws only the list under a search field while someone is in a field,
   so nothing moves under their hand. After 4 seconds without the server it
   says "Not connected" over the page, and connects again (1, 2, 4 ... 30
   seconds; at once when the page shows again).

**By session** on Usage lists each session's share of the person's Claude
Code use on each Mac in a period, and the part its agents did: Today, 7 days,
30 days, or Custom (From and To, then Show), in the address. Under the
period: the days it covers, a note that says a share is of your use and never
a percent of your limit (Anthropic gives only the total percent), the totals
("18 sessions · 8.1 billion tokens · agents did 77% · worth $3,106 at API
prices"), from a Kit that sends it the human work estimate ("Human work ≈ 1
person for 4.7 months · ≈ 20 people full time over these 7 days", with an ⓘ
that says how it is made, from the factors the Mac sent), a legend, then
each Mac's sessions, biggest share first: the name, the share, when it was
last active, how many agents it started and its human work ("≈ 1 person for
2.5 days"), and a bar (the session's part in the info blue, its agents' in a
lighter tint of it; never green). The top 15, then how many more and their
share, with Show all. A row with a session link has the ↗ Open in Claude; a
row opens nothing else (`../DESIGN-DECISIONS.md`, Phone pages, Usage by
session). No folder or path. A Mac that is away shows its last list for the
period, "As of" its time, in gray; a live Mac with no list yet says "Getting
the list from MacBook Pro...", and after 15 seconds that it did not send one
(a Kit from before this list does not). `DESIGN.md`, section 14.

A tap on a control sends one `action`; its button says "Sending..." and the
other controls wait. The answer shows where it was asked, in the server's
words (the first sentence bold): green for `ok`, blue for `gone`,
`not_now` and `not_here` (nothing changed), yellow for `offline`,
`timeout`, `denied` and `bad`. The page never shows a success the Mac did
not confirm: what it shows after is the Mac's next snapshot. With no
connection to the server, the action is not sent and the page says so.

The page code knows only the messages, not how the socket is served.

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
npm run fake-mac -- --approve   # with npm run dev: a made-up Mac links, connects and answers
npm run build && npm run sample   # the built app, sample data, the real sockets and the fake Mac
npm run build && npm run walk -- --out <folder>   # every page and state, screenshots
npm run build && node test/notices-walk.mjs --out <folder>   # the manifest, the service worker, Menu > Notices, one push
```

**The fake Mac** (`tools/fake-mac.mjs`, local runs only) is a made-up Mac:
it links itself with a key file (`data/fake-macs/<name>.json`, made on the
first run; `--approve` clicks Link as `DEV_FAKE_USER`, else open the link
page it prints), opens `/mac`, signs the challenge, sends a fixture's
snapshot with every time moved to now, sends its archived list when the
server asks, sends its Usage by session list for the period the server asks
for (`fixtures/usage.macbook-pro.json`; `--usage none` never does, as a Kit
from before it), answers each action (`--answer auto` from its own state, as a
Kit would; or `ok`, `gone`, `not_now`, `not_here`, `bad`, `cycle` for each
in turn, `silent` for a timeout), sends the snapshot the change makes, and
says bye when it stops (`--for <seconds>`, `--bye sleep|quit|update`, or
Ctrl-C). `--url http://localhost:4350/kit` for a `BASE_PATH` of `/kit`. A
second Mac: `--name "Mac mini" --snapshot fixtures/snapshot.mac-mini-away.json
--for 5 --bye sleep`. `--help` lists every option. The tests use its parts.

**The sample server** (`test/sample-server.mjs`, test only) runs the built
app on a temp database with two made-up Macs from `fixtures/`
(`test/sample.mjs`: MacBook Pro live, Mac mini asleep, every time moved to
now, each with its Usage by session list for 7 days) and a link page waiting for Link, with its real sockets: the fake Mac
signs in as MacBook Pro and answers each action. Type `next <reason>` to
make the next action answer that reason (`timeout` waits the server's 20
seconds; `offline` drops the Mac's socket just before), `mac <pro|mini>
<state>` to make a Mac come or go, `drop` to drop the pages' sockets.
**The walk** (`test/walk.mjs`) drives it headless at 390 by 844 and 1280 by
800, light and dark, through every page, action and answer and the link
page, and fails on a script error, a file that does not load, a page that
does not connect or an answer that never shows. Build with the `BASE_PATH`
to try (`BASE_PATH=/kit npm run build`, then `--short`). Type `remind` in
the sample server to make MacBook Pro send a reminder, as a Kit does when a
session has waited 10 minutes and its person is away from the Mac.

**The notices walk** (`test/notices-walk.mjs`) starts the sample server
and a stand-in push service (`tools/push-sink.mjs`, test and local runs
only: it makes subscriptions as a browser does, checks each push's VAPID
signature and decrypts it), and drives it headless at 390 by 844: the
manifest and every icon without a sign-in, the service worker and its
scope, Menu > Notices off, on (light and dark), on an iPhone in Safari,
blocked, in a browser with no Web Push and when the push service does not
answer, and one reminder end to end: the fake Mac's `remind`, the push the
stand-in decrypts, and the notice the page's real service worker shows when
that payload is delivered to it through the DevTools protocol. Headless
Chromium has no push service, so the page's `PushManager` hands out the
stand-in's subscription; the headless shell cannot show a notice, so it
uses Playwright's full Chromium (`npx playwright install chromium`, or
`--chrome <path>`).

`npm run dev` and `npm run build` first copy the licensed fonts in (Fonts,
below). An AI agent's `npm run dev` runs in the background (Astro's own
choice); `npx astro dev stop` stops it.

**Production** runs `node server.mjs` in a folder that holds `server.mjs`,
`dist/`, `package.json` and the production `node_modules`. It serves, on
`HOST` and `PORT`: the built files in `dist/client`, then Astro's pages
(the node adapter in middleware mode), and the WebSocket upgrades. It sets
`NODE_ENV=production` unless told otherwise, and makes one request at boot
so the roster sync, the daily job and the sockets start at once. nginx
passes `/` and, with the Upgrade headers, `/mac` and `/live` to it (under
`BASE_PATH`, as they came), with `Host`, `X-Forwarded-Proto` and
`X-Real-IP` (or `X-Forwarded-For`): the link page compares the browser's
address with the Mac's, and an address it cannot know shows the code. The
site is kit.sttark.com's own (Sttark/building ansible, "Kit on this box").
A restart (`SIGTERM`) closes every socket with 1012 first, so each Kit and
page connects again at once.

**Deploy.** `../.github/workflows/phone-deploy.yml`, on each change under
`phone/` on main and by hand: the tests, `npm run fonts` with the fonts from
Sttark/sttark-docs, `npm run build` with an empty `BASE_PATH`, then the pack
to the box's `kit-deploy`, which sets `APP_ORIGIN` (`https://kit.sttark.com`),
refuses a pack built for a path, restarts and checks `/healthz`; the
workflow then checks the public `https://kit.sttark.com/healthz` for its
commit.

**Sockets.** `server.mjs` passes every upgrade request to the handler set
with `onUpgrade()` (`src/lib/upgrade.ts`) and refuses it while none is set;
`npm run dev` passes `/mac` and `/live` to the same handler
(`astro.config.mjs`). The handler is `src/lib/hub.ts`.

## Linking a Mac

`DESIGN.md`, section 2; the calls are in `schema/link.v1.json`.

1. The Kit sends `POST /api/mac/link` (JSON): its P-256 public key (SPKI,
   DER, base64), its name, the Kit version, a random Mac id, where the key
   lives (`secure-enclave` or `keychain`) and its Claude Code login as
   Google's account hint (or null). A field the schema does not know is
   refused (400), and so is a key that is not P-256, a Mac id the server
   knows already (409: a Mac id is linked once, so linking never puts a new
   key on a Mac someone has), and more than 20 requests in 10 minutes from
   one address (429). The answer: the link page's address, a poll token
   and a 4-letter code. The page works once, for 10 minutes; only hashes of
   the two tokens are kept (`links`), and rows go after a day.
2. The Kit polls `GET /api/mac/link/<poll>` every 2 seconds: `waiting`,
   then `linked` with the person's address and name, or `expired` (404 for
   a poll it does not know).
3. The link page (`src/pages/link/[token].astro`) signs the person in
   first (Google, with the hint), then asks "Link MacBook Pro to your
   account?" with one green **Link**. When the browser is not on the
   address the Kit asked from (the same IPv4 address, or the same IPv6
   /64), it also shows the code and asks the person to check that the Kit
   shows the same. **Link** saves the key to the person (`macs`) with a
   record, and the page says "Linked. On your phone, open
   <site>", with a QR code of the address. A person has at most 20 linked
   Macs.

## The sockets

`src/lib/hub.ts`; the messages are in `asyncapi.yaml` and `schema/`, and
`src/lib/contract.ts` checks each one, in and out, against them: a message
with a field the contract does not know gets `error bad_message` and
changes nothing, and the server never sends one the contract does not
allow.

- **`/mac`**: the server sends `challenge`; the Mac answers `auth` with an
  ECDSA P-256 SHA-256 signature, with its saved key, of the UTF-8 text
  `kit-mac-v1`, its Mac id and the nonce, one per line (no newline at the
  end), DER or the 64-byte r and s, base64 (`src/lib/keys.ts`). Then
  `welcome`. Closes: 4400 no valid `auth` in 15 seconds, 4401 an unknown
  or removed Mac or a wrong signature, 4403 its person is off the roster,
  4409 a newer connection of the same Mac took over, 1000 after `unlink`,
  1012 a restart. The server pings every 25 seconds (the Mac does too), and
  drops a socket that sends nothing for 60 seconds. It keeps the last
  snapshot and archived list of each Mac (replaced; no history), and
  forwards each new snapshot to the person's pages at once.
- **A Mac's state** (`src/lib/macs.ts`, the same on the pages and on
  `/live`): live (heard from in the last 60 seconds), updating (2 minutes
  after `bye update`), asleep, quit (after that `bye`), not heard from.
  When it was last heard from is kept in memory on every frame, and in the
  database at most once a minute.
- **`/live`**: a signed-in page (the sign-in cookie, and an `Origin` of
  `APP_ORIGIN`; a local run takes `localhost` and `127.0.0.1` as one). It
  gets the person's Macs and each one's last snapshot, then each change.
  While one of the person's pages is visible, their Macs get `watching:
  true`. `open_archived` gets the server's copy of each archived list, and
  a live Mac whose copy is older (its snapshot's `archived_rev`) gets
  `want_archived`; an `archived_delta` from a list the server does not
  hold gets `want_archived` again. `open_usage {period}` (the Usage tab:
  when it opens, shows again, changes its period, and every minute) gets the
  server's copy of each Mac's Usage by session list for that period (for a
  Mac that is away, its last one), and each live Mac gets `want_usage` (at
  most once for a period in 10 seconds); a Mac's `usage` is kept and goes to
  the person's pages that show its period. A Mac that connects while a page
  shows Usage is asked at once. Sign out closes that sign-in's pages,
  Sign out everywhere every page of the person.
- **Actions**: only the seven of the contract. The server checks that the
  Mac is the person's (else `denied`) and connected and live (else
  `offline` at once; nothing is kept for later), sends it with who asked,
  and waits 20 seconds for `result` (else `timeout`). Each outcome is one
  record with before and after, and the person's pages get a `record` for
  the session; a result that comes after its timeout is recorded too.
- **Removal**: Menu > Remove, `unlink` from the Kit, the roster sync and
  the daily job all mark the Mac removed with a record and close its
  socket (`events.ts`).

## Needs you notices

`phone/DESIGN.md`, section 5, and its 8 "no double notices" rules; the
sender is `src/lib/push.ts`.

- **One kind, chosen by the Mac.** A Mac sends `remind` when a session has
  needed its person for 10 minutes, once per reply, and only when the
  person is away from that Mac (screen off or locked, or no input in 2
  minutes), a phone of theirs can get a push (`welcome`'s `phones`, then
  each `phones` message), and the session sent no Reach me by message in
  the last 30 minutes. Otherwise the Mac shows its own notice. Never both.
- **Alerts off.** A Mac with Alerts off in Reach me by sends no `remind`
  and shows no notice; each message stays in the Kit and comes up on its
  session (`flags.alerts_off`, `rows[].messages`, `DESIGN.md` section 3).
  When every live Mac has Alerts off, Menu > Notices says so in one quiet
  line under the switch.
- **What the server skips:** no key pair (production without
  `VAULT_VAPID_*`); no phone with notices on; a reminder it sent already
  (`pushes_sent`: the person, the session and its waiting time, 2 days, so
  a reconnect or two Macs never send one twice; two at once make one); a
  page of the person's that is visible (it shows the session already).
- **One push to each phone with notices on:** the title ("Claude needs you:
  Order page login"), one line ("Waiting 11 min: a plan waits for your
  go-ahead."), the tag `needs-<cse>` (a newer one replaces the old one), the
  One session page, and the Needs you count for the app icon's badge. Each
  is encrypted for its phone and signed with the key pair (`web-push`), sent
  with a TTL of an hour, urgency high and a topic per session, so a push
  service holds one per session. A push service that says a subscription is
  gone (404, 410) gets it dropped, with a record by `push sender`.
- **Which push services:** only those of the browsers people use: Chrome
  and Android (`fcm.googleapis.com`), iPhone and Safari (`*.push.apple.com`),
  Firefox (`*.push.services.mozilla.com`) and Edge (`*.notify.windows.com`),
  over https. Any other endpoint is refused, so nobody can make the server
  post to an address of their choosing. A local run also takes a stand-in
  on this computer (`tools/push-sink.mjs`).
- **Menu > Notices** (`src/view/render.ts`, `src/scripts/app.ts`): one
  switch for this phone. Opening Menu changes nothing: the page asks its
  browser for its subscription and the server what it knows of it
  (`/api/push/state`). A tap turns notices on: the phone's permission
  question comes straight from the tap (an iPhone asks only then), then a
  subscription with the server's key goes to `/api/push/subscribe`. A
  second tap turns them off for this phone (`/api/push/notices`); the
  subscription stays, so on again asks nothing. Each change has a record,
  and the line under the switch says since when. On an iPhone in Safari the
  line says how to add Claude Kit to the Home Screen (iOS 16.4 or later
  gets notices only there); a browser with no Web Push, blocked notices and
  a server with no keys each say so, and the switch waits.
- **The service worker** (`public/sw.js`), registered by every page under
  `BASE_PATH`: a push shows one notice and sets the badge; a tap on it
  opens the session's page in the app's window, or a new one; a renewed
  subscription goes to the server, which keeps the phone's on or off. It
  keeps no copy of any page and answers no request.
- **The app on the Home Screen:** the manifest names it Claude Kit, starts
  and scopes it at `BASE_PATH`, standalone, black; the icons are the Kit's
  own, from the Sttark icon script (Sttark/sttark-docs,
  `scripts/src/app-icons.ts`) with the Lucide `inbox`, its slot in brand
  Light Green. `APP_ICON_V` (`src/lib/icons.ts`, and `public/sw.js`) is
  raised when they change.
- **The badge:** each page sets the app icon's badge to the Needs you count
  as it draws; a push sets it while the app is closed.
- **Sign out** on a phone ends its subscription; **Sign out everywhere** all
  of the person's. The person's Macs hear the new count either way.
- **A subscription belongs to its address** (`APP_ORIGIN` and `BASE_PATH`,
  kept with it as `site`): its service worker is that address's. When the
  Kit moves (as from building.sttark.com/kit to kit.sttark.com), no page at
  the new address can turn the old one off, and a phone with notices on at
  both would get each notice twice. So at start the server ends every
  subscription made at another address (one with no `site` was made at the
  first address), each with a record by `server start`, and the person's
  Macs hear the new count. The person adds Claude Kit to the Home Screen
  again from the new address and turns notices on there.

## Environment

| Variable | Needed | What |
|---|---|---|
| `APP_ORIGIN` | production | The site's origin: `https://kit.sttark.com`, which the box's `kit-deploy` sets. Google returns to it (with `BASE_PATH`); the link page's address and QR code start with it; a form post and a `/live` socket must come from it; an `https` origin makes the sign-in cookie secure; a phone's notices belong to it with `BASE_PATH` (Needs you notices, above). Default `http://localhost:4350` |
| `VAULT_GOOGLE_CLIENT_ID`, `VAULT_GOOGLE_CLIENT_SECRET` | production | The shared Sttark Workspace sign-in client. Unset, Sign in with Google says it is not set up |
| `VAULT_ORG_SYNC_TOKEN` | production | The Kit's own read-only Workrouter org-sync key (`sk_org_...`), for the hourly roster. Unset, the roster stays as stored |
| `VAULT_VAPID_PUBLIC_KEY`, `VAULT_VAPID_PRIVATE_KEY` | production | The Web Push key pair (P-256, base64url, as `web-push` makes it). Unset (or not a P-256 pair), Menu says notices are not set up and nothing is sent. A local run makes its own and keeps it in the database. A new pair ends every phone's subscription, so it is made once and kept: `node -e "import('web-push').then(w=>{const k=w.generateVAPIDKeys();process.stdout.write(k.publicKey+' '+k.privateKey)})"` piped into `gh secret set`, never shown |
| `KIT_DB` | production | The database file, default `data/kit.db` (made with its folder) |
| `HOST`, `PORT` | optional | Where `server.mjs` listens, default `127.0.0.1` and `4350` |
| `BASE_PATH` | build only | The path the site lives under: empty at its own origin, `kit.sttark.com` (the default, and what the deploy builds with); `/kit` for a path on another origin, as at `building.sttark.com/kit`, where it started. Set when building (and for `npm run dev`); the build writes it to `dist/kit-build.json`, and every link, file, cookie and socket path starts with it (`src/lib/paths.ts`). Google returns to `APP_ORIGIN` + `BASE_PATH` + `/auth/callback`, and nginx passes the path as it came |
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
  everywhere** (Menu) ends every sign-in and push subscription of the
  person; their Macs stay linked. Each closes the pages' sockets too.
- **Form posts** must come from `APP_ORIGIN` (`src/middleware.ts`; Astro's
  own check is off, since it needs the origin when the app is built).
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
a record; their Macs' and pages' sockets close with 4403.

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
| `macs` | Linked Macs and their public keys | For good; a removed Mac keeps its row, with when, why (`phone`, `mac`, `roster`, `quiet`) and by whom. A Mac not heard from in 90 days is removed by the daily job |
| `links` | Link pages waiting for a sign-in (hashes of their tokens) | 1 day |
| `snapshots`, `archived` | The last snapshot and archived list each Mac sent | Replaced each time; deleted when the Mac is removed |
| `usage_lists` | The last Usage by session list each Mac sent for each period (today, 7 days, 30 days, and its newest range of days) | Replaced each time; deleted when the Mac is removed |
| `push_subs` | Web Push subscriptions, one per phone: its person, the sign-in it was made under, its keys, notices on or off, when that last changed, the kind of device, and the address it was made at | Until sign-out, the push service says it is gone, or the server starts at another address |
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
  records refuse change and delete, and the daily job's expiry; the gate
  and its form origin check; `/healthz`; and no real person's address
  anywhere in `phone/`. Linking (`link.test.ts`): once, the 10 minutes, a
  field the contract does not know, a wrong key, a Mac id linked twice, the
  code check, 20 Macs. The sockets (`hub.test.ts`, real sockets on a free
  port): the signed challenge (a wrong signature, an unknown, removed or
  off-roster Mac), a refused unknown field, snapshots to their person only,
  bye and unlink, the page's cookie and Origin, watching, an action and its
  record, one person acting on another's Mac (denied), offline, timeout and
  a late answer, the seven actions only, archived want and delta with a
  missing base, Usage by session lists (asked once for a period in the gap,
  kept, sent only to the pages on that period, a Mac that is away gives its
  last one, a Mac that connects is asked, only the newest range of days
  kept, a list with a field the contract does not know refused); and every
  message the server sent matches the contract.
  `BASE_PATH` `/kit` in the gate, the cookie, Google's return, the link
  page and the sockets (`paths.test.ts`, `middleware.test.ts`,
  `hub.test.ts`). Web Push (`push.test.ts`, with the stand-in push service):
  no keys in production, a bad pair, a local run's own pair; a phone turning
  notices on and off with a record each, only its own person, a renewed
  subscription keeping its choice, a phone that moves to another person,
  Sign out and Sign out everywhere; a subscription made at another address
  ended at start, with a record; what is not a browser subscription and
  a push service the Kit does not send to; every skip rule (no phone,
  notices off, a visible page, sent already, two Macs at once, a new reply
  sends again, not set up); the push itself decrypted, its VAPID claims,
  TTL, urgency and topic; a gone subscription dropped with a record, a
  failing push service kept; `pushes_sent` kept 2 days; the pages' calls
  (this site's JSON only); the manifest under `BASE_PATH`; and on real
  sockets, `welcome`'s `phones`, each `phones` change, and a Mac's `remind`
  becoming one push, none while a page shows. The server's checks agree with the fixtures
  (`contract.test.ts`); the fake Mac links over HTTP and answers
  (`fake-mac.test.ts`); removal and the 90 days (`macs.test.ts`).
- **The page check** (`scripts/page-check.mjs`, the shared Sttark check
  from Sttark/sttark-docs `page-check/`; this app's part is
  `scripts/page-check.config.mjs`): every page at 390 and 1280 px, light and
  dark, as one made-up person twice: on an empty database, and with the two
  sample Macs on the sample server (each session group, archived, a Mac
  away, Menu, a link page, and Usage by session for each period and with
  every row).
- **The pages** (`test/pages.test.ts`): the groups and their order
  (Idle with a message after Held), a session's kept messages and why they
  were not sent, the waits note and Menu's line with alerts off, a Mac
  that is away, Mac names only with several Macs, search, every answer,
  `BASE_PATH` in every link, a Mac's state from the database, and Remove.
  Usage by session: under the limits, biggest share first, the note, the
  totals and the legend, no folder or path and no green, the top 15 and Show
  all, ↗ only where there is a session link, a list per Mac, an away Mac's
  as of its time in gray, waiting and its 15 seconds, only the period shown,
  no use, Custom's days, and the address. The human work estimate: its words
  (`test/human.test.ts`, the same examples as the Mac window's tests), the
  line under the totals and its ⓘ note, the end of each row's line, one line
  per Mac, and a list from an older Kit shown as before.
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
| `src/lib/macs.ts`, `src/lib/upgrade.ts` | Linked Macs: state, what each sent, Remove; the WebSocket hook |
| `src/lib/hub.ts`, `src/lib/contract.ts`, `src/lib/events.ts` | The two sockets; the contract's checks; what removal and the roster tell the sockets |
| `src/lib/link.ts`, `src/lib/keys.ts`, `src/lib/net.ts`, `src/lib/qr.ts` | Linking a Mac; keys, signatures and tokens; the code check's addresses; the QR code |
| `src/lib/push.ts`, `src/lib/json-request.ts`, `src/pages/api/push/` | Web Push: the key pair, each phone's subscription, the sender and its skip rules; the pages' JSON calls |
| `src/pages/site.webmanifest.ts`, `public/sw.js`, `public/*.png`, `public/favicon.*` | The web app manifest, the service worker, the Kit's icons |
| `src/pages/link/[token].astro`, `src/pages/api/mac/` | The link page; the Kit's link calls |
| `src/layouts/Base.astro` | The page frame (top bar with Search and Menu, tabs), and the data the page was drawn from |
| `src/view/` | The pages as HTML (`render.ts`), what they draw from (`model.ts`), times in words (`time.ts`), the human work estimate in words (`human.ts`): the server and the browser both use them |
| `src/scripts/app.ts` | The pages in the browser: `/live`, actions, search, ⓘ notes, Remove's confirm, the theme |
| `src/lib/state.ts`, `src/lib/paths.ts` | The data a page is drawn from, from the database; `BASE_PATH` |
| `src/styles/sttark-shared.css`, `src/styles/app.css` | The guide's shared style file, byte for byte, and this app's own |
| `scripts/fonts.mjs`, `scripts/check-style.mjs` | The licensed fonts; the shared style file check |
| `test/` | The tests, and `sample-people.json`, the made-up people they use; `sample.mjs`, `sample-server.mjs` and `walk.mjs` (above) |
| `tools/fake-mac.mjs` | The fake Mac (above) |
| `tools/push-sink.mjs`, `test/notices-walk.mjs` | The stand-in push service, and the notices walk (above) |
