#!/bin/zsh
# Keeps one copy of Claude Code at a fixed place, ~/.local/share/claude/stable/claude, and runs the server for
# Claude app sessions from it. Run every 30 minutes by the LaunchAgent com.sttark.claude-stable.
#
# Why: macOS files a program's Accessibility permission by where the program is. Each Claude Code update lands
# in a new folder (~/.local/share/claude/versions/<version>), so every update asked for Accessibility again.
# A copy that never moves keeps the one permission.
#
# When an update arrives, or the server still runs from the old place, it swaps in the new copy (written next to
# the old one, then renamed over it) and restarts the server. Restarting ends any open session, so it only
# happens between 2 and 5 AM, and only when no session is working. Pass --now to skip the time window.
# STABLE, LABEL, PLIST, STATE, LOG, NEWEST (the Claude Code to copy) and SCREEN_NAME point it at a test copy
# (tools/server-health-test.swift).
set -u
STABLE=${STABLE:-$HOME/.local/share/claude/stable/claude}
LABEL=${LABEL:-com.sttark.claude-rc}
PLIST=${PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}
STATE=${STATE:-$HOME/Library/Application Support/SttarkClaudeKit/state.json}
LOG=${LOG:-$HOME/Library/Logs/sttark-claude-kit.log}
log() { print -r -- "$(date '+%F %T') stable $*" >> $LOG }

newest=${NEWEST:-$(readlink -f "$HOME/.local/bin/claude" 2>/dev/null)}
[[ -x $newest ]] || exit 0
mkdir -p ${STABLE:h}

copy_in() {  # a real copy, swapped in at once so nothing ever runs a half-written file
  cp -p "$newest" "$STABLE.tmp" && codesign -v "$STABLE.tmp" 2>/dev/null && mv -f "$STABLE.tmp" "$STABLE" \
    && log "copy is now ${newest:t}" || { rm -f "$STABLE.tmp"; log "couldn't copy ${newest:t}"; return 1 }
}

# No copy yet: make one now. Nothing is running from it, so this is safe at any hour.
[[ -x $STABLE ]] || { copy_in || exit 1 }

need_copy=0; cmp -s "$newest" "$STABLE" || need_copy=1
need_move=0; [[ -f $PLIST ]] && ! grep -qF "$STABLE" "$PLIST" && need_move=1
(( need_copy || need_move )) || exit 0

# No server: refresh the copy whenever.
[[ -f $PLIST ]] || { copy_in; exit 0 }

hour=$(date +%H)
if [[ ${1:-} != --now ]] && (( 10#$hour < 2 || 10#$hour >= 5 )); then exit 0; fi

# Any session still working, in a turn or with agents or background commands running (from the menu's minute-by-minute check)? Then try again in 30 minutes.
busy=$(/usr/bin/python3 - "$STATE" <<'PY'
import json, sys, time
try: s = json.load(open(sys.argv[1]))
except Exception: s = {}
print(', '.join((x.get('app') or {}).get('title') or k for k, x in s.get('sessions', {}).items()
      if ((x.get('app') or {}).get('working') or (x.get('app') or {}).get('background')) and time.time() - (x.get('app') or {}).get('checked', 0) < 600))
PY
)
if [[ -n $busy ]]; then log "update waiting: $busy still working"; exit 0; fi

(( need_copy )) && { copy_in || exit 1 }
if (( need_move )); then
  /usr/bin/sed -i '' "s#$HOME/.local/bin/claude#$STABLE#g" "$PLIST" && log "server now starts from $STABLE"
fi

# Restart: unload the server, end every copy of it the Kit started and wait until they are gone, then load it again.
# A `claude rc` can outlive its screen, and one that still runs keeps the folder: the new one then can't register it
# ("already served by another Claude Code on this device") and stops, again and again. The Kit's copies have its
# marker (STTARK_KIT_SERVER) or the server screen's STY in their environment; a person's own `claude rc` has neither.
SCREEN_NAME=${SCREEN_NAME:-claude-rc}
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null
for s in $(screen -ls | awk -v re="^[0-9]+[.]$SCREEN_NAME\$" '$1 ~ re {print $1}'); do screen -S $s -X quit; done
copies() {
  ps -axww -o pid=,command= | awk '{n = split($2, p, "/"); if (p[n] == "claude" && ($3 == "rc" || $3 == "remote-control")) print $1}' |
    while read -r p; do
      ps -wwE -o command= -p $p 2>/dev/null | grep -qE " (STTARK_KIT_SERVER=$LABEL|STY=[0-9]+[.]$SCREEN_NAME)( |\$)" && print $p
    done
}
tree() { print $1; for c in $(pgrep -P $1); do tree $c; done }
pids=($(for p in $(copies); do tree $p; done))
if (( ${#pids} )); then
  kill -TERM $pids 2>/dev/null
  for i in {1..40}; do   # up to 20 seconds to stop, then killed
    left=(); for p in $pids; do kill -0 $p 2>/dev/null && left+=($p); done
    (( ${#left} )) || break
    sleep 0.5
  done
  (( ${#left} )) && kill -KILL $left 2>/dev/null
fi
launchctl bootstrap "gui/$UID" "$PLIST" && log "server restarted on ${newest:t}"
