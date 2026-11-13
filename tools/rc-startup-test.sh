#!/bin/zsh
# Tests remoteControlAtStartup in install-hooks.py, and the effort hook's transcript fallback for the session id,
# on temporary home folders and made-up transcripts. Never reads or writes your own settings.
# Run from the repo root: zsh tools/rc-startup-test.sh
cd "$(dirname "$0")/.."
I=$PWD/Resources/hooks/install-hooks.py
fails=0
check() { if [[ $2 == $3 ]]; then echo "ok   $1"; else echo "FAIL $1: got '$2', want '$3'"; fails=$((fails + 1)); fi }
key() { /usr/bin/python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(s.get("remoteControlAtStartup", "missing"))' "$1/.claude/settings.json"; }
marker() { [[ -f "$1/Library/Application Support/SttarkClaudeKit/remote-control-at-startup.kit" ]] && echo yes || echo no; }

H=$(mktemp -d); mkdir -p $H/.claude
HOME=$H /usr/bin/python3 -I $I >/dev/null
check "a fresh install sets it" "$(key $H)" True
check "and records that the Kit set it" "$(marker $H)" yes
/usr/bin/python3 -c 'import json,sys; p=sys.argv[1]; s=json.load(open(p)); s.pop("remoteControlAtStartup"); json.dump(s, open(p, "w"))' $H/.claude/settings.json
HOME=$H /usr/bin/python3 -I $I >/dev/null
check "a key the person removed stays removed" "$(key $H)" missing
HOME=$H /usr/bin/python3 -I $I --remove >/dev/null
check "--remove clears the marker" "$(marker $H)" no

H=$(mktemp -d); mkdir -p $H/.claude
echo '{"remoteControlAtStartup": false}' > $H/.claude/settings.json
HOME=$H /usr/bin/python3 -I $I >/dev/null
check "an explicit false is kept" "$(key $H)" False
check "and no marker" "$(marker $H)" no

H=$(mktemp -d); mkdir -p $H/.claude
echo '{"remoteControlAtStartup": true}' > $H/.claude/settings.json
HOME=$H /usr/bin/python3 -I $I >/dev/null
HOME=$H /usr/bin/python3 -I $I --remove >/dev/null
check "a true the person set stays after --remove" "$(key $H)" True

H=$(mktemp -d); mkdir -p $H/.claude
echo '{"model": "x"}' > $H/.claude/settings.json
HOME=$H /usr/bin/python3 -I $I >/dev/null
check "a backup is saved before the change" "$(ls $H/.claude | grep -c 'settings.json.bak-effort')" 1
HOME=$H /usr/bin/python3 -I $I --remove >/dev/null
check "--remove takes out the true the Kit set" "$(key $H)" missing

# the session id from the transcript, for a session Remote Control connected some other way
T=$(mktemp -d)
printf '%s\n' '{"type":"user"}' '{"type":"bridge-session","bridgeSessionId":"session_01OLD"}' '{"type":"assistant"}' \
  '{"type":"bridge-session","bridgeSessionId":"cse_01NEW"}' '{"type":"user"}' > $T/rc.jsonl
echo '{"type":"user"}' > $T/plain.jsonl
sid() { env -u CLAUDE_CODE_BRIDGE_SESSION_ID -u CLAUDE_PID STTARK_KIT_DIR=$T/kit /usr/bin/python3 -I -c '
import importlib.util, sys
sp = importlib.util.spec_from_file_location("e", "Resources/hooks/effort-hook.py"); e = importlib.util.module_from_spec(sp); sp.loader.exec_module(e)
print(e.session_id(sys.argv[1]))' "$1" 2>&1 | tail -1; }
check "the newest bridge-session line" "$(sid $T/rc.jsonl)" cse_01NEW
check "no line: not a Remote Control session" "$(sid $T/plain.jsonl)" None
check "a missing transcript" "$(sid $T/none.jsonl)" None
check "the environment comes first" "$(CLAUDE_CODE_BRIDGE_SESSION_ID=session_01ENV /usr/bin/python3 -I -c '
import importlib.util, sys
sp = importlib.util.spec_from_file_location("e", "Resources/hooks/effort-hook.py"); e = importlib.util.module_from_spec(sp); sp.loader.exec_module(e)
print(e.session_id(sys.argv[1]))' $T/rc.jsonl)" cse_01ENV

echo; [[ $fails == 0 ]] && echo "all passed" || { echo "$fails failed"; exit 1; }
