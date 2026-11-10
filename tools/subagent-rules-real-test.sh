#!/bin/bash
# Real check for the subagent rules hook: a claude -p run in a temp folder, with project settings that run the hook
# and a temp kit folder with the Orchestrator switch on. Pass = the subagent quotes the worker rules and the marker.
# Usage: tools/subagent-rules-real-test.sh   (CLAUDE=/path/to/claude to pick the binary)
set -u
CLAUDE=${CLAUDE:-$HOME/.local/bin/claude}
[ -x "$CLAUDE" ] || { echo "No claude CLI at $CLAUDE."; exit 2; }
"$CLAUDE" auth status 2>/dev/null | grep -q '"loggedIn": true' || { echo "The CLI is not signed in."; exit 2; }
HOOK="$(cd "$(dirname "$0")/.." && pwd)/Resources/hooks/subagent-rules-hook.py"
T=$(mktemp -d); mkdir -p "$T/.claude" "$T/kit"
echo '{"orchestrator": true}' > "$T/kit/state.json"
python3 - "$T" "$HOOK" <<'PY'
import json, sys
t, hook = sys.argv[1:3]
cmd = f'STTARK_KIT_DIR="{t}/kit" STTARK_KIT_LOG="{t}/kit.log" "{hook}"'
json.dump({"hooks": {"SubagentStart": [{"hooks": [{"type": "command", "command": cmd}]}]}}, open(f"{t}/.claude/settings.json", "w"))
PY
cd "$T"
"$CLAUDE" -p "Start one general-purpose subagent with the Agent tool. Tell it: quote, word for word, every Sttark rule and any line starting with 'Sttark' that is in your context. Do not paraphrase. When it returns, quote its full answer word for word." \
  --setting-sources project --model sonnet --allowedTools "Agent,Task,Read" < /dev/null > reply.txt 2> err.log
echo "--- reply"; cat reply.txt
echo "--- log"; cat kit.log 2>/dev/null
R=$(cat reply.txt)
ok=1
for w in "Search. Don't guess" "Do not pull, switch branches or reset unless your brief says so" "Fix every instance" "UI and layout" "Asana" "No em-dashes" "Sttark context: present."; do
  case "$R" in *"$w"*) ;; *) echo "MISSING: $w"; ok=0;; esac
done
[ $ok = 1 ] && echo "PASS" || echo "FAIL"
echo "files kept in $T"
