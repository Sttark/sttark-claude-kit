# Try Kit on the glasses, in the simulator

The Even Hub simulator on the Mac shows the lens and the phone page. The app gets real sessions from the Kit
glasses bridge (`glasses/bridge/`), or made-up sessions from the mock bridge. Run the commands from the repo root
of a checkout that has `glasses/app/` and `glasses/bridge/`.

## 1. The bridge

Is it on? `{"ok": true, ...}` means yes:

```bash
curl -s -H "Authorization: Bearer $(cat ~/Library/Application\ Support/Sttark\ Kit\ Glasses/token)" http://127.0.0.1:8740/api/health
```

If not, start it in a hidden screen (`glasses/bridge/README.md` has what it needs):

```bash
env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" LANG=en_US.UTF-8 TERM=xterm-256color \
  PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  /usr/bin/screen -dmS kit-g2-bridge /usr/bin/python3 "$PWD/glasses/bridge/bridge.py"
```

## 2. The app

Is it on? `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5181/` gives `200`. If not:

```bash
cd glasses/app && npm install && npm run dev
```

## 3. The simulator

From `glasses/app`. Your real sessions, with nothing sent (look only):

```bash
KIT_SIM_ANYWAY=1 node scripts/sim.mjs "http://localhost:5181/?bridge=http://127.0.0.1:8740&token=$(cat ~/Library/Application\ Support/Sttark\ Kit\ Glasses/token)&readonly=1"
```

- Remove `&readonly=1` to reply, answer and start sessions for real.
- Add `&only=G2` to show only sessions whose name starts with G2 (and the ones you start from the glasses).
- Made-up sessions: `npm run mock` in another terminal, then `KIT_SIM_ANYWAY=1 npm run sim`.
- To close it: `npm run sim -- --stop`.

## 4. The controls

Two windows open: Glasses Display (the lens, with buttons under it) and the phone page. Use the buttons, or the
keys while Glasses Display is the front window.

| On the glasses | Button | Keys |
| --- | --- | --- |
| Swipe down: the next row, the next page | Down | S, J or ↓ |
| Swipe up: the row above, the page before | Up | W, K or ↑ |
| Tap: open, answer, send. It acts on the row with `>` | Click | Space or Enter |
| Double tap: back (on Home, the question to close the app) | Double Click | Space or Enter two times, fast |

To speak a reply or a new session, the simulator records the Mac's microphone. Or type the words on the phone page,
in "Type the words instead", and click "Use these words".

Do not hold Click or press H alone: a long press opens the system menu. The app's own items there (Read to me, Stop
reading) show after a tap, then hold.

Read to me (a session's actions, or the system menu) plays its sound on the Mac in the simulator, and on the phone or
its earbuds with the glasses. Add `&mute=1` to the address to try it with no sound.
