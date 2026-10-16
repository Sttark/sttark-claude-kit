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
set -u
STABLE=${STABLE:-$HOME/.local/share/claude/stable/claude}
LABEL=${LABEL:-com.sttark.claude-rc}
PLIST=${PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}
STATE=${STATE:-$HOME/Library/Application Support/SttarkClaudeKit/state.json}
LOG=${LOG:-$HOME/Library/Logs/sttark-claude-kit.log}
log() { print -r -- "$(date '+%F %T') stable $*" >> $LOG }

newest=$(readlink -f "$HOME/.local/bin/claude" 2>/dev/null)
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

# Any session still working (from the menu's minute-by-minute check)? Then try again in 30 minutes.
busy=$(/usr/bin/python3 - "$STATE" <<'PY'
import json, sys, time
try: s = json.load(open(sys.argv[1]))
except Exception: s = {}
print(', '.join((x.get('app') or {}).get('title') or k for k, x in s.get('sessions', {}).items()
      if (x.get('app') or {}).get('working') and time.time() - (x.get('app') or {}).get('checked', 0) < 600))
PY
)
if [[ -n $busy ]]; then log "update waiting: $busy still working"; exit 0; fi

(( need_copy )) && { copy_in || exit 1 }
if (( need_move )); then
  /usr/bin/sed -i '' "s#$HOME/.local/bin/claude#$STABLE#g" "$PLIST" && log "server now starts from $STABLE"
fi

# Restart: end the server and everything under it (screen outlives the LaunchAgent), then load it again.
kill_tree() { for c in $(pgrep -P $1); do kill_tree $c; done; kill $1 2>/dev/null }
pid=$(launchctl print "gui/$UID/$LABEL" 2>/dev/null | awk '$1 == "pid" {print $3; exit}')
[[ -n $pid ]] && kill_tree $pid
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null
launchctl bootstrap "gui/$UID" "$PLIST" && log "server restarted on ${newest:t}"
