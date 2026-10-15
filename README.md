# Sttark Effort

A Mac menu bar app that sets the effort level of your Claude Code sessions for you, task by task. A quick question gets low effort. A bug with no known cause, or a new tool built end to end, gets extra high. The goal is enough effort to get the work right the first time, and no more than that.

![The menu: Auto effort, Model, each session with its level, the server, Bypass permissions and Chrome switches, Open log, Check for updates](docs/menu.png)

- **Picks the level before Claude starts.** Each prompt you send goes to a quick side check (the newest Claude Sonnet, or another model you pick) along with the last few messages. Haiku picks Low, Medium, High, Extra or Max, and the session is set to that level before Claude's first step. A plain "go" after a plan gets sized to the plan.
- **Checks again partway through.** At 10, 25 and 50 steps into a task, Haiku looks at the work so far. If builds keep failing or the cause is still unknown, it raises the level, up to Max for a task that's stuck at Extra. If the hard part is done and the rest is repeat edits, it lowers it.
- **You can take over.** Turn **Auto effort** off for every session, or click one session to set it to Manual. If you change a session's effort yourself in the Claude app, Sttark Effort notices and switches that session to Manual on its own.
- **Shows its reasons.** The menu lists each session with its level; hover one for the latest reason. Every decision is logged.
- **Updates itself** when a new version is released here.

It only works on sessions that run through **Remote Control**: the ones you start from the Claude app, on your phone or any computer, on a Mac that runs a `claude rc` server, or a terminal session started with `claude --remote-control`. Effort can't be changed from outside any other kind of session. See [Start sessions from the Claude app](#start-sessions-from-the-claude-app) to set that up.

## Install

You need a Mac on macOS 14 or later, with [Claude Code](https://code.claude.com/docs/en/setup) installed and signed in (`claude` at `~/.local/bin/claude`).

1. Download **SttarkEffort.zip** from the [latest release](https://github.com/Sttark/sttark-effort/releases/latest) and open it.
2. Drag **SttarkEffort** into your **Applications** folder, then open it.
3. The first time, macOS says it can't check the app for malicious software, because it isn't sold through Apple. Click **Done**, go to **System Settings > Privacy & Security**, scroll down and click **Open Anyway**. You only do this once.

That's it. The app adds its hook to Claude Code's settings (`~/.claude/settings.json`, backed up first), starts by itself when you log in, and shows a gauge in the menu bar. The needle points at the level of the session you used last: far left for Low, straight up for High, far right for Max. No needle means no session in the last hour. A pause sign means Auto effort is off. New sessions use the hook right away. Sessions that were already open pick it up from their next prompt.

## Updates

The app checks for a new version a few times a day. When there is one, you get a notice: click it, or choose **Update to …** at the top of the menu. The app downloads the new version, swaps it in and restarts in a few seconds. Your settings, and the Accessibility permission for the Chrome approver, stay as they are. **Check for updates** in the menu checks right away.

## Using it

Click the gauge:

| Item | What it does |
|---|---|
| **Auto effort** | On: Claude picks each session's effort. Off: every session keeps the level it has, until you turn it back on. |
| **Model** | Which Claude model picks the levels: the two newest Haiku and two newest Sonnet models, read from Anthropic's list once a day, so new ones appear without an update. Haiku is faster and cheaper; Sonnet is slower and smarter. The newest Sonnet is the default. |
| **A session row** | The session's name in the Claude app and its level. A check means Auto. Click to switch to Manual, then click again for Auto. Hover it to see the latest reason for its level. Hover any item for what it does. |
| **Open log** | Opens the full log in Console. |
| **Start sessions from the Claude app** | Sets this Mac up so you can start Claude Code sessions from the Claude app. See [below](#start-sessions-from-the-claude-app). |
| **Bypass permissions for server sessions** | See [below](#bypass-permissions-for-server-sessions). Off until you turn it on. |
| **Approve Claude in Chrome** | See [below](#approve-claude-in-chrome). Off until you turn it on. |
| **Check for updates** | Looks for a new version now. Hidden while an update is waiting. |

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

## Choosing the model

A test on October 15, 2026 found **Sonnet 5.5** picks effort best, so the newest Sonnet is the default. The newest Haiku is faster and cheaper, if you'd rather pick it under **Model**.

![Which model picks effort best: Sonnet 5.5 is too low least often](docs/model-test.png)

| Model | Right level | Within one level | Too low | 2+ levels too low | Too high | Typical time |
|---|---|---|---|---|---|---|
| Sonnet 5.5 | 54% | 94% | 22% | 6% | 24% | 2.6 s |
| Sonnet 5 | 57% | 92% | 35% | 8% | 8% | 2.2 s |
| Haiku 5.5 | 52% | 89% | 29% | 8% | 19% | 1.9 s |
| Haiku 4.5 | 37% | 82% | 55% | 16% | 8% | 10.3 s |

**Why Sonnet 5.5:** a level that's too low is the costly mistake, because the work comes out wrong and has to be done again. A level that's too high only costs some extra time and usage on that task. Sonnet 5.5 is too low least often, and lands within one level 94% of the time. Sonnet 5 is right most often, but it's too low far more often. Haiku 4.5 is slow and too low over half the time.

**How the test works:** it took 100 real past turns from Claude Code session history, 20 each from five sizes (no tool calls, 1 to 5, 6 to 20, 21 to 60, and more than 60). For the answer key, Opus at max effort read each whole turn, including how the work actually went (each step, which failed, how long it took), and named the level the work truly needed. Then each model judged the same 100 prompts the way the hook does, seeing only the prompt and the conversation before it. One limit: the answer key is one model's hindsight, not a measured result.

**Run it again** when new models come out. From an empty folder:

```sh
python3 ~/path/to/sttark-effort/tools/model-test/sample.py   # picks 100 past turns: cases.json
python3 ~/path/to/sttark-effort/tools/model-test/run.py      # answer key and models: results.json (edit the model list first)
python3 ~/path/to/sttark-effort/tools/model-test/score.py    # table and chart.png
```

It reads your own session history, which stays on your Mac, and makes about 500 Claude calls with your Claude Code login.

## Start sessions from the Claude app

Sttark Effort can set your Mac up so you start Claude Code sessions from the Claude app, on your phone or any computer. Each session runs on the Mac, with the Mac's files, tools and logins, and Sttark Effort sets the effort for every one of them.

1. Click the gauge and turn on **Start sessions from the Claude app**.
2. Pick the folder sessions start in. A folder that holds all your projects works well, so any session can reach any of them.
3. Click **Start**.

From then on, open the Claude app, go to **Code**, pick your Mac, and type. The setting stays on through restarts. Turn the switch off to stop it.

The Mac has to be on and awake for sessions to run. On a laptop, set **System Settings > Battery > Options > Prevent automatic sleeping when the display is off** while it's plugged in.

If this Mac already runs a Remote Control server that you set up another way, the menu shows it as on and leaves it alone.

## Bypass permissions for server sessions

The Claude app, on desktop or phone, doesn't offer **Bypass permissions** for sessions that run on a Remote Control server. It switches each one to asking before commands, even when the server was started to bypass. Without this switch, there's no way to run those sessions in bypass.

With it on, at a session's first permission prompt Sttark Effort approves it and switches the session to Bypass permissions, so no more prompts follow. The Claude app then shows the session in Bypass permissions.

- It acts on sessions whose server was started with `--permission-mode bypassPermissions`. The server **Start sessions from the Claude app** sets up always is, so this switch alone decides.
- Plan mode, plan approvals and questions Claude asks you are left alone.
- Each switch is logged to `~/Library/Logs/claude-bypass-hook.log`.

Only turn it on if you're comfortable with Claude running commands on this Mac without checking with you first.

## Approve Claude in Chrome

When Claude uses Chrome through the Claude for Chrome extension, it stops to ask for permission on each new site. With this switch on, Sttark Effort answers for you: it clicks **Always allow actions on this site** when that's offered, otherwise **Allow this action**. It never clicks Decline, and it only clicks inside the Claude extension's own window, never on web pages.

The first time you turn it on, macOS asks you to allow **SttarkChromeApprover** under **System Settings > Privacy & Security > Accessibility**, because it has to see and click the button. Until you do, the menu shows **Needs Accessibility permission…**, which opens that page. Each approval is logged to `~/Library/Logs/claude-chrome-approver.log`.

## Cost

Each check is one short Haiku call: about 2 to 5 seconds before a prompt starts, plus about a second and a half when the level changes. The checks at 10, 25 and 50 steps run in the background and don't slow the work. They count toward your Claude plan's usage like any other Claude Code call.

## Troubleshooting

- **Nothing in the menu.** Sessions only appear once they run through Remote Control and you send a prompt. Look for `skip` lines in the log.
- **`error … send … failed`** in the log. The effort change goes through the same Anthropic server message the Claude app's effort picker sends. That interface isn't published, so a Claude Code update could change it. Check for a Sttark Effort update. Meanwhile sessions just keep their level.
- **`judge failed`.** The Haiku call didn't answer in time, or Claude Code isn't signed in. Run `claude` in Terminal once to check.

## Uninstall

Turn **Auto effort** off to pause it. To remove it completely, run [`uninstall.sh`](uninstall.sh). It takes the hooks out of Claude Code's settings, stops the Chrome approver and the server if they were turned on here, and deletes the app and its folder in Application Support. The logs stay.

## How it works

The app is a small Swift menu bar app. The work is done by a Python hook it installs into Claude Code:

1. **On launch** the app copies `Resources/hooks/*.py` to `~/Library/Application Support/SttarkEffort/hooks/` and runs `install-hooks.py`, which adds `effort-hook.py` to `~/.claude/settings.json` twice: as a `UserPromptSubmit` hook (40-second limit), and as a background `PostToolUse` hook. It does this on every launch, so an update brings new scripts and a removed hook comes back.
2. **On each prompt** the hook finds the session's claude.ai id (`CLAUDE_CODE_BRIDGE_SESSION_ID` for `claude --remote-control`, or the `--session-id cse_…` a `claude rc` server starts it with). It runs `claude -p` with the model picked in the menu, the rules in `effort-hook.py`, the prompt, and the last few messages, keeping Claude's latest reply nearly whole.
3. **To change the level**, `set-session-effort.py` posts a `control_request` with `apply_flag_settings {effortLevel}` to `https://api.anthropic.com/v1/code/sessions/<id>/events`. That's the same message the Claude app's effort picker sends. It signs in with the Claude Code login in the Mac's Keychain (`Claude Code-credentials`). Claude Code hooks can't set effort themselves, and the documented ways (`/effort`, the app's picker) need a person.
4. **Partway through**, the `PostToolUse` hook counts tool calls since the prompt in the session's transcript. At 10, 25 and 50 it sends Haiku the request plus a short account of each step and which ones failed.
5. **Bypass permissions for server sessions** adds `bypass-hook.sh` to Claude Code's settings as a `PermissionRequest` hook. It answers with Claude Code's own "switch this session to bypass" reply, only when the session's parent processes include `claude rc` or `claude remote-control` started with `--permission-mode bypassPermissions`.
6. **Approve Claude in Chrome** copies the helper `SttarkChromeApprover` (source in `Helpers/ChromeApprover.swift`) out of the app and runs it at login with a LaunchAgent, `~/Library/LaunchAgents/com.sttark.chrome-approver.plist`. The copy is replaced only when the helper changes. It watches Chrome's windows through macOS's Accessibility interface every 0.4 seconds.
7. **Start sessions from the Claude app** writes a LaunchAgent, `~/Library/LaunchAgents/com.sttark.claude-rc.plist`, that runs `claude rc` (Claude Code's Remote Control server) inside `screen` in the chosen folder, starts at login and restarts if it stops. Turning it off ends the server and removes the file.
8. **State** shared by the hook and the app is in `~/Library/Application Support/SttarkEffort/state.json`: the on/off switch, and per session the level, the last level sent, Manual, the latest reason and the name. Both lock it before writing.

### Building it yourself

`./install.sh` builds the app with Apple's command line tools (`xcode-select --install`), puts it in `~/Applications` and opens it.

### Releases

Every change to the app's code on `main` (`Sources`, `Resources`, `Helpers`, `Info.plist`, `build.sh`) makes GitHub build, sign and publish a new release by itself (`.github/workflows/release.yml`). The version is 1 followed by the number of commits, so each one is higher than the last. The app installs a new release only if it's signed with the same Sttark Effort certificate. The certificate is in the repo's secrets (`SIGN_P12`, `SIGN_P12_PASSWORD`). It's self-made, not from Apple: it keeps the Chrome approver's Accessibility permission on through updates, but can't skip the Open Anyway step on a first install.

### Files

| File | What it is |
|---|---|
| `Sources/Menu.swift` | The menu bar icon and menu. |
| `Sources/Server.swift` | The Start sessions from the Claude app switch. |
| `Sources/Switches.swift` | The Bypass permissions and Approve Claude in Chrome switches. |
| `tools/model-test/` | The model test: `sample.py`, `run.py`, `score.py`. |
| `tools/make-icon.py` | Draws the app icon. The menu bar gauge is drawn in code to match it. |
| `Helpers/ChromeApprover.swift` | The Chrome approver helper. `--dump` prints what it sees without clicking. |
| `Resources/hooks/bypass-hook.sh` | The Bypass permissions hook. |
| `Sources/State.swift` | Reads and writes the shared state; installs the hooks. |
| `Sources/Update.swift` | Checks GitHub for a new version and installs it. |
| `Resources/hooks/effort-hook.py` | The hook: picks the level, rechecks, Manual and pause. |
| `Resources/hooks/set-session-effort.py` | Sends an effort change to a session. Also usable by hand: `set-session-effort.py cse_… high`. |
| `Resources/hooks/install-hooks.py` | Adds the hook to Claude Code's settings, or removes it with `--remove`. |

## License

Copyright Sttark. For use by Sttark employees. The code is public so the app can update itself; it isn't offered for use outside Sttark.
