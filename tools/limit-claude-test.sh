#!/bin/bash
# Real Claude Code test of the usage-limit wait, on copies: a test state folder, a fake usage read whose limit
# resets in RESET seconds, and only this repo's limit hook (no user or live Kit settings).
# Usage: tools/limit-claude-test.sh <prompt> [reset seconds]
set -u
H="$(cd "$(dirname "$0")/.." && pwd)/Resources/hooks/limit-hook.py"
RESET=${2:-75}
T=$(mktemp -d)
mkdir -p "$T/w/.claude"
R=$(python3 -c "import datetime;print((datetime.datetime.now().astimezone()+datetime.timedelta(seconds=$RESET)).isoformat())")
echo "{\"extra_usage\":{\"is_enabled\":true},\"limits\":[{\"kind\":\"session\",\"is_active\":true,\"percent\":100,\"resets_at\":\"$R\"}]}" > "$T/usage.json"
echo '{"data":[]}' > "$T/events.json"
cat > "$T/w/.claude/settings.json" <<EOF
{"hooks":{
 "PreToolUse":[{"hooks":[{"type":"command","command":"python3 '$H'","timeout":60}]}],
 "UserPromptSubmit":[{"hooks":[{"type":"command","command":"python3 '$H'","timeout":60}]}]},
 "permissions":{"allow":["Bash"]}}
EOF
export STTARK_KIT_DIR=$T/kit STTARK_KIT_LOG=$T/log STTARK_LIMIT_TEST=$T/usage.json STTARK_LIMIT_EVENTS=$T/events.json
cd "$T/w"
if [ -n "${LIMIT_AFTER:-}" ]; then   # start under the limit (95%), reach it LIMIT_AFTER seconds in
  cp "$T/usage.json" "$T/usage.at"
  sed 's/"is_active":true,"percent":100/"is_active":false,"percent":95/' "$T/usage.at" > "$T/usage.json"
  (sleep "$LIMIT_AFTER"; cp "$T/usage.at" "$T/usage.json") &
fi
if [ -n "${CREDIT_AFTER:-}" ]; then   # stand-in for "Use credits at the usage limit" in the menu
  (sleep "$CREDIT_AFTER"; mkdir -p "$T/kit"; echo '{"limit_credits_all": true}' > "$T/kit/state.json") &
fi
claude -p "$1" --setting-sources project --permission-mode bypassPermissions --output-format stream-json --verbose --model sonnet > "$T/out.jsonl" 2>&1
python3 - "$T/out.jsonl" <<'PY'
import json, sys, time
for l in open(sys.argv[1]):
    try: e = json.loads(l)
    except ValueError: print('RAW', l.strip()[:200]); continue
    t = e.get('type')
    if t == 'assistant':
        u = e['message'].get('usage', {})
        for c in e['message']['content']:
            if c['type'] == 'text': print('SAY ', c['text'][:300])
            if c['type'] == 'tool_use': print('TOOL', json.dumps(c['input'])[:200])
        print('     out_tokens', u.get('output_tokens'), 'cache_read', u.get('cache_read_input_tokens'), 'in', u.get('input_tokens'))
    elif t == 'user':
        for c in e['message']['content'] if isinstance(e['message']['content'], list) else []:
            if c.get('type') == 'tool_result':
                x = c['content'] if isinstance(c['content'], str) else ' '.join(i.get('text', '') for i in c['content'])
                print('RES ', x[:300].replace('\n', ' | '))
    elif t == 'result':
        print('COST', e.get('total_cost_usd'), 'turns', e.get('num_turns'), 'ms', e.get('duration_ms'))
PY
echo '--- log'; cat "$T/log"
rm -rf "$T"
