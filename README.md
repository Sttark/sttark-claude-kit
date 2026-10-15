# Sttark Effort

A Mac menu bar app that sets the effort level of your Claude Code sessions for you, task by task. A quick question gets low effort. A bug with no known cause, or a new tool built end to end, gets extra high. The goal is enough effort to get the work right the first time, and no more than that.

![The menu: Auto effort switch, each session with its level and Claude's reason, Open log, Check for updates](docs/menu.png)

- **Picks the level before Claude starts.** Each prompt you send goes to a quick side check (Claude Haiku, or another model you pick) along with the last few messages. Haiku picks Low, Medium, High, Extra or Max, and the session is set to that level before Claude's first step. A plain "go" after a plan gets sized to the plan.
- **Checks again partway through.** At 10, 25 and 50 steps into a task, Haiku looks at the work so far. If builds keep failing or the cause is still unknown, it raises the level, up to Max for a task that's stuck at Extra. If the hard part is done and the rest is repeat edits, it lowers it.
- **You can take over.** Turn **Auto effort** off for every session, or click one session to set it to Manual. If you change a session's effort yourself in the Claude app, Sttark Effort notices and switches that session to Manual on its own.
- **Shows its reasons.** The menu lists each session with its level and Haiku's latest one-line reason, and every decision is logged.
- **Updates itself** when a new version is released here.

It only works on sessions that run through **Remote Control**: the ones you start from your phone or the Claude app on a Mac that runs a `claude rc` server, or a terminal session started with `claude --remote-control`. Effort can't be changed from outside any other kind of session. See [Start Claude Code sessions from your phone](#start-claude-code-sessions-from-your-phone) to set that up.

## Install

You need a Mac on macOS 14 or later, with [Claude Code](https://code.claude.com/docs/en/setup) installed and signed in (`claude` at `~/.local/bin/claude`).

1. Download **SttarkEffort.zip** from the [latest release](https://github.com/Sttark/sttark-effort/releases/latest) and open it.
2. Drag **SttarkEffort** into your **Applications** folder, then open it.
3. The first time, macOS says it can't check the app for malicious software, because it isn't sold through Apple. Click **Done**, go to **System Settings > Privacy & Security**, scroll down and click **Open Anyway**. You only do this once.

That's it. The app adds its hook to Claude Code's settings (`~/.claude/settings.json`, backed up first), starts by itself when you log in, and shows a gauge in the menu bar. The needle shows the level of the session you used last. A pause sign means Auto effort is off. New sessions use the hook right away. Sessions that were already open pick it up from their next prompt.

## Using it

Click the gauge:

| Item | What it does |
|---|---|
| **Auto effort** | On: Claude picks each session's effort. Off: every session keeps the level it has, until you turn it back on. |
| **Model** | Which Claude model picks the levels: the two newest Haiku and two newest Sonnet models, read from Anthropic's list once a day, so new ones appear without an update. Haiku is faster and cheaper; Sonnet is slower and smarter. The newest Haiku is the default. |
| **A session row** | The session's name in the Claude app and its level. A check means Auto. Click to switch to Manual (orange), then click again for Auto. The gray line under it is Haiku's latest reason. |
| **Open log** | Opens the full log in Console. |
| **Check for updates** | Looks for a new version now. The app also checks a few times a day and offers **Update to …** at the top of the menu. |

Sessions show for 12 hours after their last activity.

**Setting the effort yourself:** change it in the Claude app's effort picker as usual. On the session's next step, Sttark Effort sees a level it didn't send, switches that session to Manual and leaves it alone. Click the row to hand it back.

### The log

Every decision goes into `~/Library/Logs/claude-effort-hook.log`, one line each:

```
2026-10-08 11:02:48 change cse_01AbCd… high->xhigh (2.2s) xhigh - Unknown cause spanning firmware and server code | The sensor readings drop out every few hours…
2026-10-08 11:03:22 steady cse_01AbCd… xhigh at 11 steps (4.3s) xhigh - Cause still unconfirmed; needs log checks and a test. | The sensor readings drop out every few hours…
```

| First word | Meaning |
|---|---|
| `change` / `keep` | The check when a prompt arrives. |
| `raise` / `lower` / `steady` | The check at 10, 25 or 50 steps. |
| `manual` | The session is on Manual, or you just changed it yourself. |
| `paused` | Auto effort is off. |
| `skip` | Not a Remote Control session, so it can't be changed. |
| `error` | Something failed. The level was left as it was. |

To watch it live: `tail -f ~/Library/Logs/claude-effort-hook.log`.

## Start Claude Code sessions from your phone

Sttark Effort can set your Mac up so you start Claude Code sessions from the Claude app on your phone or any computer. Each session runs on the Mac, with the Mac's files, tools and logins, and Sttark Effort sets the effort for every one of them.

1. Click the gauge and turn on **Start sessions from your phone**.
2. Pick the folder sessions start in. A folder that holds all your projects works well, so any session can reach any of them.
3. Choose whether sessions may run commands without asking first. Nobody is at the Mac to approve each one, so with this off you approve them from your phone.
4. Click **Start**.

From then on, open the Claude app, go to **Code**, pick your Mac, and type. The setting stays on through restarts. Turn the switch off to stop it.

The Mac has to be on and awake for sessions to run. On a laptop, set **System Settings > Battery > Options > Prevent automatic sleeping when the display is off** while it's plugged in.

If this Mac already runs a Remote Control server that you set up another way, the menu says so and leaves it alone.

## Cost

Each check is one short Haiku call: about 2 to 5 seconds before a prompt starts, plus about a second and a half when the level changes. The checks at 10, 25 and 50 steps run in the background and don't slow the work. They count toward your Claude plan's usage like any other Claude Code call.

## Troubleshooting

- **Nothing in the menu.** Sessions only appear once they run through Remote Control and you send a prompt. Look for `skip` lines in the log.
- **`error … send … failed`** in the log. The effort change goes through the same Anthropic server message the Claude app's effort picker sends. That interface isn't published, so a Claude Code update could change it. Check for a Sttark Effort update. Meanwhile sessions just keep their level.
- **`judge failed`.** The Haiku call didn't answer in time, or Claude Code isn't signed in. Run `claude` in Terminal once to check.

## Uninstall

Turn **Auto effort** off to pause it. To remove it completely, run [`uninstall.sh`](uninstall.sh), or by hand: quit the app, delete it from Applications, run `/usr/bin/python3 ~/Library/Application\ Support/SttarkEffort/hooks/install-hooks.py --remove`, then delete `~/Library/Application Support/SttarkEffort`.

## How it works

The app is a small Swift menu bar app. The work is done by a Python hook it installs into Claude Code:

1. **On launch** the app copies `Resources/hooks/*.py` to `~/Library/Application Support/SttarkEffort/hooks/` and runs `install-hooks.py`, which adds `effort-hook.py` to `~/.claude/settings.json` twice: as a `UserPromptSubmit` hook (40-second limit), and as a background `PostToolUse` hook. It does this on every launch, so an update brings new scripts and a removed hook comes back.
2. **On each prompt** the hook finds the session's claude.ai id (`CLAUDE_CODE_BRIDGE_SESSION_ID` for `claude --remote-control`, or the `--session-id cse_…` a `claude rc` server starts it with). It runs `claude -p` with the model picked in the menu, the rules in `effort-hook.py`, the prompt, and the last few messages, keeping Claude's latest reply nearly whole.
3. **To change the level**, `set-session-effort.py` posts a `control_request` with `apply_flag_settings {effortLevel}` to `https://api.anthropic.com/v1/code/sessions/<id>/events`. That's the same message the Claude app's effort picker sends. It signs in with the Claude Code login in the Mac's Keychain (`Claude Code-credentials`). Claude Code hooks can't set effort themselves, and the documented ways (`/effort`, the app's picker) need a person.
4. **Partway through**, the `PostToolUse` hook counts tool calls since the prompt in the session's transcript. At 10, 25 and 50 it sends Haiku the request plus a short account of each step and which ones failed.
5. **Start sessions from your phone** writes a LaunchAgent, `~/Library/LaunchAgents/com.sttark.claude-rc.plist`, that runs `claude rc` (Claude Code's Remote Control server) inside `screen` in the chosen folder, starts at login and restarts if it stops. Turning it off ends the server and removes the file.
6. **State** shared by the hook and the app is in `~/Library/Application Support/SttarkEffort/state.json`: the on/off switch, and per session the level, the last level sent, Manual, the latest reason and the name. Both lock it before writing.

### Building it yourself

`./install.sh` builds the app with Apple's command line tools (`xcode-select --install`), puts it in `~/Applications` and opens it.

### Releases

Every change to the app's code on `main` (`Sources`, `Resources`, `Info.plist`, `build.sh`) makes GitHub build and publish a new release (`.github/workflows/release.yml`). The version is 1 followed by the number of commits. The app installs a new release only if its signature passes the same check as the running copy and it carries the same app ID.

### Files

| File | What it is |
|---|---|
| `Sources/Menu.swift` | The menu bar icon and menu. |
| `Sources/Server.swift` | The Start sessions from your phone switch. |
| `Sources/State.swift` | Reads and writes the shared state; installs the hooks. |
| `Sources/Update.swift` | Checks GitHub for a new version and installs it. |
| `Resources/hooks/effort-hook.py` | The hook: picks the level, rechecks, Manual and pause. |
| `Resources/hooks/set-session-effort.py` | Sends an effort change to a session. Also usable by hand: `set-session-effort.py cse_… high`. |
| `Resources/hooks/install-hooks.py` | Adds the hook to Claude Code's settings, or removes it with `--remove`. |
