#!/bin/bash
# Phase 0 of the orchestrator plan: checks that the hook events the orchestrator needs work on this
# Claude Code version. Real Claude Code runs (claude -p, Sonnet) in a throwaway folder with one logging hook
# and only that folder's settings, so the Kit's own hooks stay out of it.
# Usage: tools/hook-event-test.sh            (CLAUDE=/path/to/claude to pick the binary)
# Needs a signed-in CLI: `claude auth status` says "loggedIn": true.
set -u
if [ -z "${CLAUDE:-}" ]; then
  CLAUDE=$(command -v claude || ls -d "$HOME/Library/Application Support/Claude/claude-code/"*/*/claude.app/Contents/MacOS/claude 2>/dev/null | tail -1)
fi
[ -x "$CLAUDE" ] || { echo "No claude CLI found. Set CLAUDE=/path/to/claude."; exit 2; }
"$CLAUDE" auth status 2>/dev/null | grep -q '"loggedIn": true' || { echo "The CLI is not signed in. Run: \"$CLAUDE\" auth login"; exit 2; }
echo "claude: $CLAUDE ($("$CLAUDE" --version 2>/dev/null))"

T=$(mktemp -d)
mkdir -p "$T/.claude"
echo "hello from note.txt" > "$T/note.txt"
cat > "$T/hook.py" <<'PY'
#!/usr/bin/python3
# Logs every event. SubagentStart adds a secret word; SubagentStop and Stop block once when HOOKTEST asks.
import json, sys, os
d = json.load(sys.stdin)
ev = d.get("hook_event_name")
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "events.log"), "a") as f:
    f.write(json.dumps({"event": ev, "agent_id": d.get("agent_id"), "agent_type": d.get("agent_type"),
                        "source": d.get("source"), "tool": d.get("tool_name"),
                        "stop_hook_active": d.get("stop_hook_active")}) + "\n")
def once(name):
    p = os.path.join(here, "mark-" + name)
    if os.path.exists(p): return False
    open(p, "w").close(); return True
mode = os.environ.get("HOOKTEST", "").split(",")
if ev == "SubagentStart":
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart",
        "additionalContext": "The secret word is PELICAN-42."}}))
elif ev == "SubagentStop" and "substop" in mode and once("substop"):
    print(json.dumps({"decision": "block", "reason": "Before you finish, add the line SUBSTOP-BLOCKED-OK to your final answer."}))
elif ev == "Stop" and "stop" in mode and once("stop"):
    print(json.dumps({"decision": "block", "reason": "Before you finish, reply with the line STOP-BLOCKED-OK."}))
PY
chmod +x "$T/hook.py"
python3 - "$T" <<'PY'
import json, sys
t = sys.argv[1]
h = [{"hooks": [{"type": "command", "command": f'"{t}/hook.py"'}]}]
json.dump({"hooks": {e: h for e in ["SubagentStart", "SubagentStop", "Stop", "PreToolUse", "SessionStart"]}},
          open(f"{t}/.claude/settings.json", "w"), indent=1)
PY
cd "$T"
run() { "$CLAUDE" -p "$@" --setting-sources project --allowedTools "Read,Agent,Task" --model sonnet --output-format json 2>>"$T/err.log"; }

echo "run 1: subagent (SubagentStart, SubagentStop, PreToolUse agent_id)"
HOOKTEST=substop run "Start one general-purpose subagent with the Agent tool. Tell it: read note.txt with the Read tool, then report the file's text, any secret word it was given in its context, and any extra line it was asked to add. When it returns, quote its full answer word for word." > run1.json
cp events.log events1.log 2>/dev/null; rm -f events.log
echo "run 2: Stop"
HOOKTEST=stop run "Say hi in one word." > run2.json
cp events.log events2.log 2>/dev/null; rm -f events.log
echo "run 3: /clear (SessionStart source clear)"
printf '%s\n' '{"type":"user","message":{"role":"user","content":"Say one."}}' \
  '{"type":"user","message":{"role":"user","content":"/clear"}}' \
  '{"type":"user","message":{"role":"user","content":"Say two."}}' |
  "$CLAUDE" -p --input-format stream-json --output-format stream-json --verbose --setting-sources project --model sonnet > run3.jsonl 2>>"$T/err.log"
cp events.log events3.log 2>/dev/null

python3 - "$T" <<'PY'
import json, sys, os
t = sys.argv[1]
def ev(n):
    p = os.path.join(t, f"events{n}.log")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
def res(n):
    try: return json.load(open(os.path.join(t, f"run{n}.json"))).get("result") or ""
    except Exception as e: return f"(no result: {e})"
e1, e2, e3 = ev(1), ev(2), ev(3)
r1, r2 = res(1), res(2)
rows = []
def row(name, ok, evidence): rows.append((name, "PASS" if ok else "FAIL", evidence))
starts = [e for e in e1 if e["event"] == "SubagentStart"]
row("SubagentStart adds context to a subagent", bool(starts) and "PELICAN-42" in r1,
    f"{len(starts)} SubagentStart event(s); answer has PELICAN-42: {'PELICAN-42' in r1}")
stops = [e for e in e1 if e["event"] == "SubagentStop"]
row("SubagentStop can block, and gives the agent type", len(stops) >= 2 and "SUBSTOP-BLOCKED-OK" in r1 and any(e["agent_type"] for e in stops),
    f"{len(stops)} SubagentStop event(s); agent_type={[e['agent_type'] for e in stops]}; answer has SUBSTOP-BLOCKED-OK: {'SUBSTOP-BLOCKED-OK' in r1}")
pre = [e for e in e1 if e["event"] == "PreToolUse"]
sub = [e for e in pre if e["agent_id"]]
main = [e for e in pre if not e["agent_id"]]
row("PreToolUse carries agent_id inside a subagent", bool(sub) and bool(main),
    f"main-thread calls {[e['tool'] for e in main]} without agent_id; subagent calls {[e['tool'] for e in sub]} with agent_id")
st = [e for e in e2 if e["event"] == "Stop"]
row("Stop can block a turn from ending", len(st) >= 2 and "STOP-BLOCKED-OK" in r2,
    f"{len(st)} Stop event(s), stop_hook_active={[e['stop_hook_active'] for e in st]}; reply: {r2.strip()[:80]!r}")
srcs = [e["source"] for e in e3 if e["event"] == "SessionStart"]
row("SessionStart fires with source clear (headless)", "clear" in srcs, f"SessionStart sources: {srcs}")
print()
print("| Check | Result | Evidence |\n|---|---|---|")
for r in rows: print(f"| {r[0]} | {r[1]} | {r[2]} |")
print("\nsubagent answer (run 1):", r1.strip()[:400].replace("\n", " / "))
PY
echo; echo "errors:"; tail -5 "$T/err.log"
echo "files kept in $T"
