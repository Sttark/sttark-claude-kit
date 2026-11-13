#!/usr/bin/python3
"""Checks migrate.py (Move to Remote Control) on made-up sessions in a temporary folder, with STTARK_MIGRATE_DRY,
so nothing starts, stops or is renamed: which sessions show as running only on this Mac, how a session is found,
when a move needs --yes or waits for a reply, and what a move records for keep() and the window."""
import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', 'Resources', 'hooks', 'migrate.py')
tmp = tempfile.mkdtemp(prefix='kit-migrate-')
kit, claude, desk = (os.path.join(tmp, d) for d in ('kit', 'claude', 'desktop'))
for d in (kit, os.path.join(claude, 'projects', '-Users-test-src'), os.path.join(claude, 'projects', '-private-tmp-x'),
          os.path.join(claude, 'sessions'), os.path.join(desk, 'acct', 'org')):
    os.makedirs(d, exist_ok=True)
ENV = dict(os.environ, STTARK_KIT_DIR=kit, STTARK_KIT_LOG=os.path.join(tmp, 'kit.log'), STTARK_CLAUDE_DIR=claude,
           STTARK_DESKTOP_SESSIONS=desk, STTARK_MIGRATE_DRY='1')
ENV.pop('CLAUDE_CODE_SESSION_ID', None)
now = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
failed = 0


def check(what, ok):
    global failed
    print(('ok   ' if ok else 'FAIL ') + what)
    failed += not ok


def transcript(sid, entry, text, extra=(), folder='-Users-test-src', cwd='/tmp'):
    lines = [{'type': 'user', 'entrypoint': entry, 'isSidechain': False, 'cwd': cwd, 'sessionId': sid, 'timestamp': now,
              'message': {'role': 'user', 'content': text}},
             {'type': 'assistant', 'entrypoint': entry, 'cwd': cwd, 'sessionId': sid, 'timestamp': now,
              'message': {'role': 'assistant', 'model': 'claude-haiku-5-5', 'content': [{'type': 'text', 'text': 'OK'}]}}]
    lines += list(extra)
    with open(os.path.join(claude, 'projects', folder, sid + '.jsonl'), 'w') as f:
        f.write(''.join(json.dumps(l, separators=(',', ':')) + '\n' for l in lines))


def run(*args, env=None):
    p = subprocess.run([sys.executable, SCRIPT, *args], env=env or ENV, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def local():
    run('--scan')
    with open(os.path.join(kit, 'local-sessions.json')) as f:
        return {x['id']: x for x in json.load(f)['sessions']}


T = '11111111-aaaa-4aaa-8aaa-000000000001'  # Terminal, closed
O = '22222222-bbbb-4bbb-8bbb-000000000002'  # Terminal, open and idle
B = '33333333-cccc-4ccc-8ccc-000000000003'  # Terminal, open and in a reply
D = '44444444-dddd-4ddd-8ddd-000000000004'  # desktop app, closed
A = '55555555-eeee-4eee-8eee-000000000005'  # desktop app, archived there
R = '66666666-ffff-4fff-8fff-000000000006'  # on Remote Control already
P = '77777777-0000-4000-8000-000000000007'  # a `claude -p` run
transcript(T, 'cli', 'Fix the map', [{'type': 'custom-title', 'customTitle': 'Facility Map', 'sessionId': T}])
transcript(O, 'cli', 'Open one')
transcript(B, 'cli', 'Busy one')
transcript(D, 'claude-desktop', 'Plan the week')
transcript(A, 'claude-desktop', 'Old work')
transcript(R, 'cli', 'Linked', [{'type': 'bridge-session', 'sessionId': R, 'bridgeSessionId': 'cse_01abc'}])
transcript(P, 'sdk-cli', 'Pick a level', folder='-private-tmp-x')
for sid, title, archived in ((D, 'Daily Plan', False), (A, 'Old Work', True)):
    with open(os.path.join(desk, 'acct', 'org', f'local_{sid}.json'), 'w') as f:
        json.dump({'sessionId': 'local_' + sid, 'cliSessionId': sid, 'title': title, 'isArchived': archived,
                   'bridgeSessionIds': []}, f)
# open sessions: this test's own process stands in for each one's Claude Code
sleeper_o = subprocess.Popen(['/bin/sleep', '600'])
sleeper_b = subprocess.Popen(['/bin/sleep', '600'])
for pid, sid, status in ((sleeper_o.pid, O, 'idle'), (sleeper_b.pid, B, 'busy')):
    with open(os.path.join(claude, 'sessions', f'{pid}.json'), 'w') as f:
        json.dump({'pid': pid, 'sessionId': sid, 'status': status, 'entrypoint': 'cli', 'bridgeSessionId': None}, f)

try:
    rows = local()
    check('lists Terminal and desktop sessions with no link', {T, O, B, D} <= set(rows))
    check('leaves out archived desktop, linked and `claude -p` sessions', not ({A, R, P} & set(rows)))
    check('a custom name wins: "Facility Map"', rows[T]['title'] == 'Facility Map')
    check('a desktop session takes the desktop app\'s name', rows[D]['title'] == 'Daily Plan' and rows[D]['where'] == 'desktop')
    check('an open session shows its process; a reply shows busy', rows[O].get('pid') == sleeper_o.pid and rows[B].get('busy') is True)
    check('the model it ran on is kept', rows[T]['model'] == 'claude-haiku-5-5')

    code, out = run('--list')
    check('--list names each one', code == 0 and 'Facility Map' in out and 'Daily Plan' in out)

    code, out = run('nothing-like-this')
    check('an unknown session exits 2', code == 2)

    code, out = run(O)
    check('an open session needs --yes (exit 4)', code == 4 and 'Terminal' in out)
    code, out = run(B)
    check('a session in a reply needs --yes (exit 4)', code == 4)
    code, out = run(B, '--yes')
    st = json.load(open(os.path.join(kit, 'state.json')))
    check('with --yes it waits for the reply to end', code == 0 and B in st.get('migrate_pending', {}))
    check('...and shows as waiting in the window', local()[B].get('pending') is True)

    code, out = run('Facility Map')
    st = json.load(open(os.path.join(kit, 'state.json')))
    alone = st.get('keep', {}).get('alone', {})
    new = next((k for k, v in alone.items() if v['transcript'].endswith(T + '.jsonl')), '')
    check('found by name and moved', code == 0 and 'moved to Remote Control' in out and new)
    check('keep() starts it on its own after a restart, with its model', alone.get(new, {}).get('own') is True
          and alone[new].get('model') == 'claude-haiku-5-5')
    check('the window shows it under its name at once', st['sessions'].get(new, {}).get('title') == 'Facility Map')
    log = open(os.path.join(tmp, 'kit.log')).read()
    check('logged as migrate', f'migrate {T[:8]} "Facility Map" moved to Remote Control as {new}' in log)

    code, out = run('44444444')
    check('found by the start of its id', code == 0 and 'Daily Plan' in out)

    code, out = run(O, '--yes')
    check('an open idle session with --yes moves (closing it there)', code == 0 and 'moved' in out)
    log = open(os.path.join(tmp, 'kit.log')).read()
    check('...and the log says where it was closed', 'closed it in Terminal' in log)

    code, out = run(R)
    check('a linked session says it is on Remote Control already', code == 0 and 'already' in out)

    code, out = run(D, env=dict(ENV, CLAUDE_CODE_SESSION_ID=D))
    st = json.load(open(os.path.join(kit, 'state.json')))
    check('a session moving itself waits for its reply to end', code == 0 and 'when this reply ends' in out)
finally:
    sleeper_o.kill()
    sleeper_b.kill()

print(f'\n{"all passed" if not failed else f"{failed} failed"} ({tmp})')
sys.exit(1 if failed else 0)
