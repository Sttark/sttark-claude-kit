#!/bin/bash
# Claude Code UserPromptSubmit hook, turned on with "Sync Claude profile instructions" in the Sttark Claude Kit
# menu: puts the instructions from the Claude app's Profile settings in front of every prompt.
#
# CLAUDE.md is read once when a session starts, so a session already running never sees an edit. This runs on
# every prompt instead, in new and running sessions alike. It reads the synced block from ~/.claude/CLAUDE.md,
# so it costs nothing per prompt, and starts a sync in the background when the last one is over a minute old,
# so the next prompt carries any change.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SUPPORT="$HOME/Library/Application Support/SttarkClaudeKit"
FILE="$HOME/.claude/CLAUDE.md"
PY="$SUPPORT/venv/bin/python"
TRIED="$SUPPORT/profile-sync.tried"

if [ -x "$PY" ]; then
  age=$(( $(date +%s) - $(stat -f %m "$TRIED" 2>/dev/null || echo 0) ))
  [ "$age" -gt 60 ] && ( "$PY" "$HERE/profile-sync.py" >>"$HOME/Library/Logs/claude-profile-sync.log" 2>&1 & ) >/dev/null 2>&1
fi

[ -f "$FILE" ] || exit 0
block=$(awk '/profile-sync:begin/{f=1;next} /profile-sync:end/{f=0} f' "$FILE" | sed '/^<!--/,/-->/d')
[ -n "${block//[[:space:]]/}" ] || exit 0

printf '%s' "$block" | /usr/bin/python3 -c '
import json,sys
print(json.dumps({"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"The user'"'"'s standing instructions (synced from their Claude profile, authoritative):\n\n"+sys.stdin.read().strip()}}))
'
