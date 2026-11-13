"""Test, on copies, that a wait loop goes on in new code after a Kit update (same process, no gap, hold kept), that
only one wait loop reads usage, and that an older copy of the script never reads the endpoint once the new code
has written the cache (the `retry_at` fence)."""
import http.server, importlib.util, json, os, shutil, subprocess, sys, tempfile, threading, time

here = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(here, '../Resources/hooks/limit-hook.py')
fails = 0


def check(what, ok, extra=''):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what + (f'  [{extra}]' if extra and not ok else ''))
    fails += not ok


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


over = {'extra_usage': {'is_enabled': True}, 'limits': [
    {'kind': 'weekly_all', 'percent': 93, 'resets_at': '2099-01-01T00:00:00+00:00'}]}
under = {'extra_usage': {'is_enabled': True}, 'limits': [
    {'kind': 'weekly_all', 'percent': 40, 'resets_at': '2099-01-01T00:00:00+00:00'}]}

# ---- 1. the fence: an older copy stops reading the endpoint --------------------------------------------------
hits = []


class S(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(time.time())
        b = json.dumps(over).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(('127.0.0.1', 0), S)
threading.Thread(target=srv.serve_forever, daemon=True).start()
d = tempfile.mkdtemp()
os.environ.update(STTARK_KIT_DIR=d, STTARK_KIT_LOG=d + '/log', STTARK_LIMIT_URL=f'http://127.0.0.1:{srv.server_port}/')
old_src = subprocess.run(['git', 'show', '65d4d4f:Resources/hooks/limit-hook.py'], cwd=here, capture_output=True,
                         text=True).stdout
if old_src:
    open(d + '/old.py', 'w').write(old_src)
    new = load(SRC, 'newlh')
    old = load(d + '/old.py', 'oldlh')
    new.usage()                                   # the new code reads once and writes the cache with the fence
    n = len(hits)
    c = json.load(open(new.USAGE))
    c['at'] = 0                                   # a stale cache: the old copy would read again without the fence
    json.dump(c, open(new.USAGE, 'w'))
    for _ in range(20):
        old.usage(max_age=0)
    check('an older copy does not read the endpoint while the fence is up', len(hits) == n, f'{len(hits) - n} reads')
    check('the old copy still gets the last good read', old.usage(max_age=0) == over)
else:
    print('skip fence test: no git history')

# ---- 2. a wait loop goes on in new code after the script changes ---------------------------------------------
T = tempfile.mkdtemp()
kit, hooks = T + '/kit', T + '/hooks'
os.makedirs(kit)
os.makedirs(hooks)
script = hooks + '/limit-hook.py'
shutil.copy(SRC, script)
stand = T + '/usage.json'
json.dump(over, open(stand, 'w'))
sid = '11111111-2222-3333-4444-555555555555'
tp = T + '/t.jsonl'
open(tp, 'w').write(json.dumps({'type': 'assistant', 'message': {'model': 'claude-opus-5-5'}}) + '\n')
json.dump({'limit_modes': {sid: {'mode': 'hold', 'at': 90, 'sid': sid, 'set_at': 1}},
           'sessions': {}}, open(kit + '/state.json', 'w'))
env = dict(os.environ, STTARK_KIT_DIR=kit, STTARK_KIT_LOG=T + '/log', STTARK_LIMIT_TEST=stand, STTARK_LIMIT_TICK='0.2')
env.pop('STTARK_LIMIT_URL', None)
# a parent that stays alive (the loop ends when its parent goes)
parent = subprocess.Popen(['/bin/sh', '-c', f'"{sys.executable}" "{script}" wait {sid}; echo EXIT $?'],
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.5)
kids = subprocess.run(['pgrep', '-P', str(parent.pid)], capture_output=True, text=True).stdout.split()
pid = kids[0] if kids else ''
log = lambda: open(T + '/log').read() if os.path.exists(T + '/log') else ''
check('the wait loop runs', bool(pid))
pauses = lambda: json.load(open(kit + '/state.json')).get('limit_pauses') or {}
check('its row is in the menu', len(pauses()) == 1, pauses())
with open(script, 'a') as f:
    f.write('\n# a Kit update\n')
time.sleep(1.5)
kids2 = subprocess.run(['pgrep', '-P', str(parent.pid)], capture_output=True, text=True).stdout.split()
check('after the update the same process still waits', kids2 == kids, f'{kids} -> {kids2}')
check('the log says the wait goes on in the new code', 'reload' in log(), log())
check('the row is kept, with the same pid', [r.get('pid') for r in pauses().values()] == [int(pid)] if pid else False,
      pauses())
check('no second hold/wait line after the reload', log().count('wait   ') <= 1, log())
json.dump(under, open(stand, 'w'))           # the limit drops under 90%: the wait ends in the new code
out = parent.communicate(timeout=10)[0]
check('the wait ends when the limit is under the hold, and says GO ON', 'GO ON' in out, out)
check('it printed the waiting line once', out.count('Holding at') == 1, out)
check('the row is gone after the end', pauses() == {}, pauses())

# ---- 3. the --hold hook (an agent's tool call held) goes on in new code too ----------------------------------
json.dump(over, open(stand, 'w'))
json.dump({'limit_modes': {sid: {'mode': 'hold', 'at': 90, 'sid': sid, 'set_at': 1}}, 'sessions': {}},
          open(kit + '/state.json', 'w'))
data = {'hook_event_name': 'PreToolUse', 'session_id': sid, 'agent_id': 'agent123', 'transcript_path': tp,
        'tool_name': 'Read', 'tool_input': {'file_path': '/tmp/x'}, 'tool_use_id': 'toolu_TEST1', 'cwd': T}
inp = T + '/in.json'
json.dump(data, open(inp, 'w'))
parent = subprocess.Popen(['/bin/sh', '-c', f'"{sys.executable}" "{script}" --hold < "{inp}"; echo EXIT $?'],
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.5)
kids = subprocess.run(['pgrep', '-P', str(parent.pid)], capture_output=True, text=True).stdout.split()
check('--hold: the agent tool call is held', bool(kids) and len(pauses()) == 1, pauses())
with open(script, 'a') as f:
    f.write('# another Kit update\n')
time.sleep(1.5)
kids2 = subprocess.run(['pgrep', '-P', str(parent.pid)], capture_output=True, text=True).stdout.split()
check('--hold: after the update the same process still holds', kids2 == kids and len(pauses()) == 1,
      f'{kids} -> {kids2} {pauses()}')
json.dump(under, open(stand, 'w'))
out = parent.communicate(timeout=10)[0]
check('--hold: ends with exit 0 and no output when the limit drops', out.strip() == 'EXIT 0', out)
check('--hold: the row is gone', pauses() == {}, pauses())
print('FAILED' if fails else 'all passed')
raise SystemExit(1 if fails else 0)
