# Glasses bridge (G2 prototype)

A small server on the Mac that lets an app on Even Realities G2 glasses see and drive the Claude Code sessions that
run on that Mac: the list with each session's state, a session's last reply, the question or permission it waits
on, a spoken message, and a new session. The glasses app (a web app in the Even app) talks to it over the local
network or the VPN.

It is a prototype beside Sttark Claude Kit. It reads the Kit's state files and uses the Kit's `claude-window` tool;
it changes nothing in the Kit app, and the Kit's release does not include it.

## Run it

```
/usr/bin/python3 glasses/bridge/bridge.py
```

- It listens on port 8740 on all addresses (`--port`, `--host` change that), and answers only requests from private
  addresses: the local network, the VPN and this Mac. Other addresses get 403.
- Every request needs the bridge's token: `Authorization: Bearer <token>` (the WebSocket takes `?token=`). The token
  is made at the first start and kept in `~/Library/Application Support/Sttark Kit Glasses/token` (mode 600). The
  start prints it, with the addresses to use. `--print-token` prints it and exits.
- It logs one line per action (never a message's words) to the screen and to
  `~/Library/Logs/sttark-kit-glasses-bridge.log`.
- To keep it running without a Terminal window, start it in a screen with a clean environment:

```
env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" LANG=en_US.UTF-8 TERM=xterm-256color \
  PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  /usr/bin/screen -dmS kit-g2-bridge /usr/bin/python3 "$PWD/glasses/bridge/bridge.py"
```

  To stop it: `pkill -f glasses/bridge/bridge.py` (quitting the screen leaves the Python process running).

What it needs on the Mac:

| What | Why |
|---|---|
| Claude Code, signed in with a claude.ai account | It reads sessions and answers prompts with that login (the Keychain item `Claude Code-credentials`). It never refreshes the login; Claude Code does |
| Sttark Claude Kit | The session states, and `claude-window` for the claude.ai page |
| Google Chrome, signed in to claude.ai, with View > Developer > Allow JavaScript from Apple Events | Messages go from a claude.ai page (below) |
| `brew install whisper-cpp` and the model (below) | Speech to text, on the Mac |

The speech model (148 MB), once:

```
mkdir -p "$HOME/Library/Application Support/Sttark Kit Glasses/models"
curl -L -o "$HOME/Library/Application Support/Sttark Kit Glasses/models/ggml-base.en.bin" \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
```

## How each action reaches a session

Claude Code (2.1.220 and later) starts a turn for a user message only when Claude's API marks the message as typed
in a Claude app: its `client_platform` is `web_claude_ai`, `desktop_app`, `ios` or `android`. The API sets that
mark only for the apps' own sign-in. A message sent with Claude Code's login (the OAuth token), with any header,
gets no mark: the session shows "Held peer message, from an unidentified session" and never acts on it. (The
open-source g2-claude-remote bridge, through claude-rc-api, sends Claude Code's login with the header
`anthropic-client-platform: web_claude_ai` for this. In a test with Claude Code 2.1.327 in November 2026, such a
message was held, on both `/v1/code/sessions/{id}/events` and `/v1/sessions/{id}/events`.)

So the bridge uses two sign-ins, each for what it can do:

| Action | How | Sign-in |
|---|---|---|
| List sessions, follow one, read its reply | `GET /v1/code/sessions`, its change stream `/watch`, and each session's events and event stream | Claude Code's login |
| Answer a question, a plan or a permission | `POST /v1/code/sessions/{id}/events`, a `control_response` to the session's `can_use_tool` request (the session accepts it from this login) | Claude Code's login |
| Send a message | `POST /v1/sessions/{id}/events` with `anthropic-client-platform: web_claude_ai`, as one synchronous XMLHttpRequest in a claude.ai page in the Kit's Claude window in Chrome. The API marks it `web_claude_ai`, so the session acts on it as the person's own message | The person's claude.ai sign-in in Chrome |
| Start a session in a folder that has a Remote Control server (the Kit's server, `~/src`) | `POST /v1/code/sessions` with the server's `environment_id`, as `claude remote-control` itself does it: the server starts the session. Then its first message goes as above. The session is in the Claude app's list like one started there | Claude Code's login, then claude.ai |
| Start a session in another folder (or when Chrome cannot send) | `claude --remote-control "<name>" --permission-mode bypassPermissions "<first message>"` in a hidden screen named `g2-<id>` in that folder, with a clean environment, as the Kit starts a session: the first message is on its command line, so it is the person's own | none (the Mac) |

The claude.ai page is `https://claude.ai/robots.txt` in the bridge's own tab of the Kit's Claude window (key
`g2-bridge`): a claude.ai page that runs no app code. The Kit's tool never brings Chrome to the front; it makes a
new window, for a moment, only when it has no spare one. With Chrome closed, a message gets 503 "Chrome is not open
on the Mac" (the bridge never opens Chrome), and a new session starts the second way.

Only these calls change anything. The bridge never archives, stops or interrupts a session, and never restarts the
Remote Control server.

## What it shows

Each session's state comes from the API (live: a turn runs, or it asks something) and from the Kit (its judgment of
a finished reply, its waits, the usage-limit holds, the progress check-ins). The groups follow the Kit window's
Sessions page:

| `status` | When | `why` |
|---|---|---|
| `needs_you` | It asks something now (`has_pending`), or its finished reply, not opened yet, needs the person (the Kit's judgment, or the API's own summary) | The question, or why it needs the person |
| `working` | A turn runs, or its agents or background commands still run | What still runs, if only that |
| `waiting` | It waits on someone else (a wait handed to the Kit), or it is held at the usage limit | What it waits for |
| `idle` | Anything else | none |

`status_line` is the latest progress check-in while it works, else the API's one-line summary of its last turn.
Archived sessions, runs of scheduled tasks, and sessions of their own whose Claude Code has ended are left out.
Opening a session on the glasses does not mark it read.

## API

All JSON. Errors: `{"ok": false, "error": "..."}` with the HTTP status (400 bad input, 401 no token, 404 no such
session, 409 nothing to answer, 503 Chrome, the speech model or the login is not ready, 502 Claude's API refused).

| Call | Answer |
|---|---|
| `GET /api/health` | `{ok: true, version, sessions, list_ok_at, list_error, kit, stt, web: {chrome, last_ok, last_error}}` |
| `GET /api/sessions` | `{sessions: [{id, title, folder, status, why, status_line, updated_at, has_pending, url, connected, unread, effort}]}`: needs you first, then working, waiting, idle; the newest first in each |
| `GET /api/sessions/:id` | The same fields, and `last_reply` (the last assistant text, plain: no Markdown marks, code blocks as plain lines, each table row a card: its name, then "  Header: cell" lines, status marks as words) and `pending`: `null` or `{kind: "question" \| "permission" \| "plan", text, options: [{id, label}], request_id}` |
| `POST /api/sessions/:id/message` `{text}` | `{ok: true, uuid}` |
| `POST /api/sessions/:id/answer` `{option_id}` | `{ok: true, done: true}`. A question with several questions takes one answer at a time: `{ok: true, done: false, pending}` shows the next; the answers go to the session after the last |
| `POST /api/sessions` `{prompt, folder?}` | `{id, folder, started: "server" \| "cli"}`. `folder` defaults to `~/src`; it must be in the home folder and trusted in Claude Code. The session's name is the prompt's first line, cut at a word to 60 characters; with the Kit's Name sessions automatically on, the Kit can rename it after its first prompt, as it does any new session. It can take up to 90 seconds |
| `GET /api/folders` | `{folders: [{path, label}]}`: `~/src` first, then the folders of recent sessions |
| `POST /api/transcribe` | Body: raw PCM, 16-bit little-endian, 16 kHz, mono (`Content-Type: application/octet-stream`). `{text}`. `?language=` (default `en`) |
| `WS /api/live?token=...` | Pushes `{type: "sessions", sessions}` at once and on each change. Send `{type: "subscribe", id}` for the session the client shows, to get `{type: "session", session}` (the detail above) at once and on each change: it takes the place of the session before, and `{type: "subscribe", id: null}` (back on the list) follows none. `{type: "unsubscribe", id}` stops one |

Option ids: a question's are `q<question>.o<option>` (`q0.o1` is the second option of the first question); a plan's
are `approve` and `keep`; a permission's are `allow` and `deny`.

```
TOKEN=$(cat "$HOME/Library/Application Support/Sttark Kit Glasses/token")
curl -s -H "Authorization: Bearer $TOKEN" http://192.168.1.20:8740/api/sessions
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text": "Use press 5 for the label job."}' http://192.168.1.20:8740/api/sessions/cse_01ExampleSession/message
```

## What stays on the Mac

Prompts, replies and audio go only between the Mac and the glasses on the local network, and to Claude's own API as
the Claude app sends them. The bridge sends nothing to kit.sttark.com or any other server. Speech to text runs on
the Mac (whisper.cpp). The token stays in the file above.

## Files

| File | What |
|---|---|
| `bridge.py` | The server: routes, the WebSocket, the live list, starting sessions |
| `rcapi.py` | Claude's Remote Control API with Claude Code's login |
| `web.py` | Calls through the claude.ai page in Chrome (messages) |
| `kitstate.py` | The Kit's state files and each session's status |
| `detail.py` | A session's last reply as plain text (tables as cards), and its prompt and answers |
| `stt.py` | Speech to text with whisper.cpp |
| `wsock.py` | The WebSocket frames |
| `test_bridge.py` | Tests on made-up data: `/usr/bin/python3 -m unittest discover -s glasses/bridge -p 'test_*.py'` |
