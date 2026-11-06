#!/bin/bash
# Test the usage-limit hold on copies: a fake usage read, fake session names and events, a test state folder.
# Never touches the real state, the server or a running session.
set -u
H="$(cd "$(dirname "$0")/.." && pwd)/Resources/hooks/limit-hook.py"
T=$(mktemp -d)
cd "$T"
R=$(python3 -c "import datetime;print((datetime.datetime.now().astimezone()+datetime.timedelta(seconds=45)).isoformat())")
echo "{\"extra_usage\":{\"is_enabled\":true},\"limits\":[{\"kind\":\"session\",\"is_active\":true,\"percent\":100,\"resets_at\":\"$R\"}]}" > usage.json
echo '{"cse_TEST1":"Hey"}' > titles.json
echo '{"data":[]}' > events.json
export STTARK_KIT_DIR=$T/kit STTARK_KIT_LOG=$T/log STTARK_LIMIT_TEST=$T/usage.json \
  STTARK_LIMIT_TITLES=$T/titles.json STTARK_LIMIT_EVENTS=$T/events.json CLAUDE_CODE_BRIDGE_SESSION_ID=session_TEST1
echo '{"hook_event_name":"UserPromptSubmit","session_id":"s1","prompt":"Hey","cwd":"/x"}' | python3 "$H" &
sleep 3
echo "during:           $(cat titles.json)"
echo '{"cse_TEST1":"Greeting chat"}' > titles.json   # the app sets its own name during the hold
sleep 32
echo "after app rename: $(cat titles.json)"
wait
echo "after release:    $(cat titles.json)"
cat log
rm -rf "$T"
