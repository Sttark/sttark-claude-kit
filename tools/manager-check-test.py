"""Tests the working rules' manager check (working-rules-hook.py --check) on copies: a temp state folder and log,
and sample transcripts. No model call: every sample ends with a short reply, so the STE check skips it.
Run: /usr/bin/python3 tools/manager-check-test.py"""
import json, os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../Resources/hooks/working-rules-hook.py')
d = tempfile.mkdtemp()
env = dict(os.environ, STTARK_KIT_DIR=d, STTARK_KIT_LOG=d + '/log')
fails = 0


def person(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def calls(n, name='Bash', side=False):
    out = []
    for i in range(n):
        e = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't%d' % i, 'name': name, 'input': {}}]}}
        r = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't%d' % i, 'content': 'ok'}]}}
        if side:
            e['isSidechain'] = r['isSidechain'] = True
        out += [e, r]
    return out


def reply():
    return [{'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Done.'}]}}]


def case(name, lines, want):
    global fails
    sid = 'sess-' + name.replace(' ', '-').replace(',', '')
    tp = os.path.join(d, sid + '.jsonl')
    with open(tp, 'w') as f:
        f.write('\n'.join(json.dumps(l) for l in lines) + '\n')
    subprocess.run([sys.executable, HOOK, '--check'], input=json.dumps(
        {'hook_event_name': 'Stop', 'session_id': sid, 'transcript_path': tp}), text=True, env=env)
    try:
        got = bool(json.load(open(os.path.join(d, 'working-notes.json'))).get(sid))
    except (OSError, ValueError):
        got = False
    ok = got == want
    fails += not ok
    print('ok   ' if ok else 'FAIL ', name, '-> note' if got else '-> no note')


note = '<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n</task-notification>'
case('12 calls no agent', [person('fix it')] + calls(12) + reply(), True)
case('12 calls with one Agent', [person('fix it')] + calls(11) + calls(1, 'Agent') + reply(), False)
case('12 calls with SendMessage', [person('fix it')] + calls(11) + calls(1, 'SendMessage') + reply(), False)
case('5 calls', [person('fix it')] + calls(5) + reply(), False)
case('subagent calls ignored', [person('fix it')] + calls(3) + calls(20, side=True) + reply(), False)
case('earlier turns ignored', [person('a')] + calls(12) + reply() + [person('b')] + calls(2) + reply(), False)
case('a notification turn adds up', [person('a')] + calls(6) + reply() + [person(note)] + calls(6) + reply(), True)
case('noted once, not again on the next notification turn',
     [person('a')] + calls(12) + reply() + [person(note)] + calls(1) + reply(), False)
log = open(d + '/log').read() if os.path.exists(d + '/log') else ''
ok = log.count('agents ') == 2 and 'ste    ' not in log
fails += not ok
print('ok   ' if ok else 'FAIL ', 'log: one agents line per note, no ste line')
print('all passed' if not fails else '%d failed' % fails)
sys.exit(1 if fails else 0)
