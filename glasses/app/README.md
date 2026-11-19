# Kit on Even Realities G2 glasses

A glasses app for people who walk the plant all day and run Claude Code sessions on their Mac. On the lens it shows which sessions need you, a session's status and last reply, and lets you keep a session going: reply by voice, send "Continue", or answer a question, a permission or a plan with one tap. It also starts a short new session by voice.

The sessions stay on the Mac. A small bridge on the Mac (the Kit glasses bridge) gives this app a JSON API; the app runs on the phone, inside the Even Realities app, and draws on the glasses.

![The six lens screens with made-up sessions](docs/lens-screens.png)

## Gestures

The glasses have a touch strip on each temple (and the optional R1 ring): tap, double tap, swipe up and swipe down. The app uses no long press, since the system uses it for its own menu.

| Screen | Swipe | Tap | Double tap |
| --- | --- | --- | --- |
| Home: the sessions, needs you first, with `+ New session` on top | Moves the highlight | Opens the session, or starts a new one | Asks to close the app (the system's own question) |
| Session: title, status, the last reply in pages | Next or last page | Opens the actions | Back to Home |
| Actions: a question's answers first, then Reply by voice, Continue, Back | Moves the highlight | Does it. An answer goes at once | Back to the session |
| Reply by voice: Listening, and the words as they come | Nothing | Sends the words | Cancels |
| New session: speak, then "Start this new session?" | Nothing | Done speaking, then Start | Cancels |

Status marks on Home: `!` needs you, `▷` working, `○` waiting on someone else, `-` idle. The words after the title say the same thing.

When a session starts to need you, the top line of whatever screen is open says so for 6 seconds. It takes no input and moves nothing.

## The phone panel

The page the Even app shows for Kit. It holds the bridge address and token, the folder new sessions start in, and the swipe direction (some glasses swipe the other way). It says first whether Kit reaches the Mac. While the glasses listen, it also shows a box to type the words instead, for the simulator, which has no glasses mic.

![The phone panel](docs/panel.png)

## Run it in the simulator

Needs Node 20 or later.

```bash
cd glasses/app
npm install
npm run mock    # the mock bridge: made-up sessions on port 8741, token "mock"
npm run dev     # the app on http://localhost:5181
npm run sim     # the Even Hub simulator, on the app and the mock bridge
```

`npm run sim` opens the simulator's two windows (the lens and the phone page). A new window can take the keyboard, so it starts only when nobody has used the Mac for 2 minutes, and gives the front back to the app that had it. At the Mac, `KIT_SIM_ANYWAY=1 npm run sim` starts it at once. `npm run sim -- --stop` closes it.

In the simulator, its Up and Down controls swipe, Click taps and Double Click double taps. The simulator records the Mac's own microphone; the mock bridge turns any sound into a made-up sentence. On the phone page, the typed box works too.

`npm run walk` goes through every screen and action on its own (the dev server must run) and saves a picture of each in `shots/`: the lens as `NN-step.png`, the phone page as `panel-*.png`. It starts its own mock bridge (port 8742) and simulator.

The simulator's page sleeps while the Mac is locked or its window is covered: replies from the bridge and timers wait until the next input. The walk pokes it with a long press and its release, which the app ignores.

`npm test` checks the text layout (pages, bytes, the font's glyphs) and the screens' rows.

## Point it at the real bridge

The bridge runs on the Mac on port 8740. Its token is in `~/Library/Application Support/Sttark Kit Glasses/token`.

- **On the phone:** in the panel, enter `http://<the Mac's address>:8740` and the token, then Save and connect.
- **In the simulator:** give both in the address, so nothing is saved:
  `KIT_SIM_ANYWAY=1 node scripts/sim.mjs "http://localhost:5181/?bridge=http://127.0.0.1:8740&token=$(cat ~/Library/Application\ Support/Sttark\ Kit\ Glasses/token)&readonly=1"`
  `readonly=1` makes the app refuse to send anything (messages, answers, new sessions): use it to look at real sessions without touching them.
- **With the dev server:** `VITE_BRIDGE_URL` and `VITE_BRIDGE_TOKEN` set the panel's first values for `npm run dev` only. A build never reads them.

## Try it on the glasses

**From the dev server**, with the phone on the same network as the Mac: turn on Developer Mode in the Even app, run `npm run dev`, then `npx evenhub qr --url http://<the Mac's address>:5181` and scan the code from the Even Hub tab. Changes show without a new scan.

**As a package:**

```bash
npm run pack    # builds, then writes kit-glasses-0.1.0.ehpk
```

Upload the `.ehpk` in the Even Hub portal (your project, Builds), then install it on the phone from Even Hub, Me, Apps, Private builds.

The Even app lets the app reach only the addresses its `app.json` lists. `npm run pack` lists this Mac's bridge, `http://<LAN address>:8740`, in the packed copy (`.pack/app.json`); `KIT_BRIDGE_URL=http://192.168.1.20:8740 npm run pack` picks another. If the Mac's address changes, pack again, or give the Mac a fixed address on the network. No token is ever packed.

## The bridge API

JSON, with the header `Authorization: Bearer <token>` on every request. What the app needs from the bridge besides the table:

- CORS on every answer, the preflight included: `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Headers: Authorization, Content-Type`, `Access-Control-Allow-Methods: GET, POST, OPTIONS`. The phone's web view drops any answer without them.
- It listens on the network (`0.0.0.0:8740`), since the phone reaches the Mac by its address.
- 401 for a wrong token (the lens says "Token not accepted"), 404 for a session that is gone (the lens says so and goes back to Home).
- `why` (or `status_line`) is one short line: it follows the status on the session screen. `pending.text` shows above the answers, 3 lines at most; for a `plan`, the plan itself goes in `pending.text`, which the session screen shows as its pages.

| Request | Answer |
| --- | --- |
| `GET /api/health` | `{ok, version}` |
| `GET /api/sessions` | `{sessions: [{id, title, folder, status, why, status_line, updated_at, has_pending}]}`, needs you first. `status` is `needs_you`, `working`, `waiting` or `idle` |
| `GET /api/sessions/:id` | The same fields, and `last_reply` (text) and `pending`: `null` or `{kind, text, options: [{id, label}]}`, `kind` being `question`, `permission` or `plan` |
| `POST /api/sessions/:id/message` `{text}` | `{ok}` |
| `POST /api/sessions/:id/answer` `{option_id}` | `{ok}` |
| `POST /api/sessions` `{prompt, folder?}` | `{id}` |
| `GET /api/folders` | `{folders: [{path, label}]}` |
| `POST /api/transcribe`, body raw PCM (16 kHz, mono, 16-bit little-endian) | `{text}` |
| `WS /api/live?token=...` | The bridge sends `{type: "sessions", sessions}` and `{type: "session", session}`; the app sends `{type: "subscribe", id}` for the session it shows (`null` on Home) |

Without the live socket the app asks for the list every 5 seconds. Voice: the app sends all the audio so far every 2.5 seconds for the words to show, and once more when you tap.

## How it is built

TypeScript and Vite, with the Even Hub SDK (`@evenrealities/even_hub_sdk`) and the Even font measures (`@evenrealities/pretext`).

| File | What it does |
| --- | --- |
| `src/main.ts` | Starts the app: the SDK, settings, the panel, the input |
| `src/controller.ts` | The screens and what each gesture does there; keeps in step with the bridge |
| `src/screens.ts` | What each screen puts on the lens (pure functions) |
| `src/glasses.ts` | Draws a page: a full rebuild only when the layout or a list changes, otherwise in-place text updates, one SDK call at a time, each with a time limit |
| `src/text.ts` | Line wrap and pages measured with the glasses' own font, byte limits, glyphs the font has |
| `src/events.ts` | One shape for every input (list, text and system events) |
| `src/voice.ts` | Collects the mic's audio and asks the bridge for the words |
| `src/api.ts` | The bridge client |
| `src/panel.ts`, `index.html`, `src/styles/` | The phone panel, on `sttark-shared.css` |
| `mock-bridge/` | The mock bridge and its made-up sessions |
| `scripts/` | Simulator, walk-through, fonts and packing |

What the lens allows, and how the app lives with it:

- 576 by 288 pixels, one font with no sizes or bold, 27 px a line, five brightness steps. A full screen holds about 10 lines of about 60 characters; a reply page holds 7 lines.
- A text box holds at most 999 bytes in the simulator (1000 on the glasses), a list row 63 bytes and a list 20 rows. Everything is cut by bytes, not characters.
- The font has no emoji, `…`, `•` or curly quotes; the app swaps them (`glyphSafe`).
- A list scrolls itself and tells the app nothing until a tap. A list cannot change in place: a new list redraws the page and puts the highlight back on the first row. So the app redraws a list only when its rows change, and a tap finds its row by index (the first row's index arrives empty).
- A swipe on a text box comes to the app only at the box's top or bottom. Each reply page fits its box exactly, so every swipe turns the page.
- The first screen must use the system's close question on double tap (Even Hub review checks it).

Not tried on glasses yet (the simulator differs from them): the glasses mic, which way a swipe turns a page (the panel has Swap swipe direction for that), whether the Even app takes a LAN `http://` address in the network list, and how the app keeps up while the phone is locked.

Fonts: the panel uses Founders Grotesk, licensed to Sttark. The files are never committed (this repo is public); `scripts/fonts.mjs` copies them in for `npm run dev` and `npm run build` from the phone app, a `sttark-docs` checkout beside this repo, or Sttark/sttark-docs through `gh`.
