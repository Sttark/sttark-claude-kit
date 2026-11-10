"""Test the browser lock (Resources/hooks/browser-lock.py) and its install (install-hooks.py), on copies only:
a temp kit folder, a temp log and a temp HOME. No model calls, no Chrome.
Run: /usr/bin/python3 tools/browser-lock-test.py"""
import json, os, re, shutil, subprocess, sys, tempfile, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, 'Resources', 'hooks')
HOOK = os.path.join(HOOKS, 'browser-lock.py')
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


tmp = tempfile.mkdtemp(prefix='browser-lock-test-')
KIT = os.path.join(tmp, 'kit')
LOG = os.path.join(tmp, 'kit.log')
os.makedirs(KIT)
STATE = os.path.join(KIT, 'state.json')
ENV = dict(os.environ, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_BROWSER_WAIT='1', STTARK_BROWSER_POLL='0.2',
           STTARK_BROWSER_IDLE='300')


def switch(on):
    json.dump({'orchestrator': on}, open(STATE, 'w'))


def run(data, env=None, raw=None):
    t = time.time()
    r = subprocess.run([sys.executable, HOOK], input=raw if raw is not None else json.dumps(data),
                       capture_output=True, text=True, env=env or ENV)
    out = json.loads(r.stdout) if r.stdout.strip() else None
    return out, time.time() - t, r.returncode


def pre(agent=None, cmd=None, tool='Bash', atype='implementer', sid='s1'):
    d = dict(hook_event_name='PreToolUse', session_id=sid, tool_name=tool,
             tool_input={'command': cmd} if cmd is not None else {})
    if agent:
        d.update(agent_id=agent, agent_type=atype)
    return d


def stop(agent, sid='s1'):
    return dict(hook_event_name='SubagentStop', session_id=sid, agent_id=agent, agent_type='implementer')


def denied(out):
    return bool(out) and out['hookSpecificOutput']['permissionDecision'] == 'deny'


def lock(sid='s1'):
    try:
        return json.load(open(STATE)).get('browser', {}).get(sid)
    except (OSError, ValueError):
        return None


GO = 'claude-window go https://example.com'
DONE = 'claude-window done'

# switch off
switch(False)
out, _, rc = run(pre('a1', GO))
check('switch off: allowed, nothing kept', out is None and rc == 0 and lock() is None)
switch(True)

# first agent takes, same agent again allows
out, _, _ = run(pre('a1', GO))
check('first agent: allowed and takes the lock', out is None and lock()['holder'] == 'a1'
      and lock()['agent_type'] == 'implementer')
t1 = lock()['at']
time.sleep(0.05)
out, _, _ = run(pre('a1', '~/.local/bin/claude-window js "document.title"'))
check('same agent again: allowed and refreshes', out is None and lock()['at'] > t1)

# second agent waits, then is denied
out, dt, _ = run(pre('a2', 'cd /tmp && claude-window shot', atype='researcher'))
check('second agent: denied after waiting', denied(out) and dt >= 0.7)
reason = out['hookSpecificOutput']['permissionDecisionReason']
check('deny reason names the holder and the rule',
      re.match(r'The browser is in use by another agent \(implementer a1, holding since \d+ s\)\. Wait for it to finish, '
               r'then try again\. Only one browsing agent at a time\.$', reason) is not None)
check('denied agent did not take the lock', lock()['holder'] == 'a1')

# a second agent gets in while waiting if the holder is done
import threading
res = {}
def late():
    res['out'], res['dt'], _ = run(pre('a2', GO), env=dict(ENV, STTARK_BROWSER_WAIT='4'))
th = threading.Thread(target=late)
th.start()
time.sleep(0.6)
run(pre('a1', DONE))
th.join()
check('waiting agent gets in once the holder runs done', res['out'] is None and lock()['holder'] == 'a2' and res['dt'] < 3)

# done by a non-holder changes nothing; done by the holder frees
out, _, _ = run(pre('a1', DONE))
check('done by a non-holder: allowed, lock unchanged', out is None and lock()['holder'] == 'a2')
out, _, _ = run(pre('a2', DONE))
check('done by the holder: allowed, lock freed', out is None and lock() is None)
out, _, _ = run(pre('a3', GO, atype='validator'))
check('after done, another agent takes it', out is None and lock()['holder'] == 'a3')

# idle past IDLE
s = json.load(open(STATE))
s['browser']['s1']['at'] = time.time() - 400
json.dump(s, open(STATE, 'w'))
out, _, _ = run(pre('a4', GO))
check('holder idle past IDLE: another agent takes over', out is None and lock()['holder'] == 'a4')
out, _, _ = run(pre('a5', GO), env=dict(ENV, STTARK_BROWSER_IDLE='0.1', STTARK_BROWSER_WAIT='0'))
time.sleep(0.2)
out, _, _ = run(pre('a5', GO), env=dict(ENV, STTARK_BROWSER_IDLE='0.1', STTARK_BROWSER_WAIT='0'))
check('IDLE env override works', out is None and lock()['holder'] == 'a5')

# SubagentStop
run(stop('a9'))
check('SubagentStop of a non-holder: lock kept', lock()['holder'] == 'a5')
run(stop('a5'))
check('SubagentStop of the holder frees the lock', lock() is None)

# not a browser call: untouched, not delayed
run(pre('a1', GO))
for name, d in [('npm test', pre('a2', 'npm test')),
                ('cat claude-window.sh', pre('a2', 'cat Resources/hooks/claude-window.sh')),
                ('git commit message', pre('a2', 'git commit -m "fix claude-window go"')),
                ('Read tool', pre('a2', tool='Read')),
                ('mcp other tool', pre('a2', tool='mcp__asana__get_task'))]:
    out, dt, _ = run(d)
    check('%s: allowed, not delayed' % name, out is None and dt < 0.7 and lock()['holder'] == 'a1')

# MCP chrome tool counts
out, dt, _ = run(pre('a2', tool='mcp__claude-in-chrome__navigate'))
check('mcp__claude-in-chrome__navigate by a second agent: denied', denied(out))
run(pre('a1', DONE))
out, _, _ = run(pre('a2', tool='mcp__claude-in-chrome__navigate'))
check('mcp__claude-in-chrome__navigate takes the lock', out is None and lock()['holder'] == 'a2')
run(pre('a2', DONE))

# main thread is a holder
out, _, _ = run(pre(None, GO))
check('main thread: takes the lock as "main"', out is None and lock()['holder'] == 'main'
      and lock()['agent_type'] == 'main')
out, _, _ = run(pre('a1', GO))
check('agent denied while main holds', denied(out))
out, _, _ = run(pre(None, GO))
check('main thread again: allowed', out is None)
run(pre(None, DONE))
out, _, _ = run(pre('a1', GO))
check('agent takes it after main done', out is None and lock()['holder'] == 'a1')
out, _, _ = run(pre(None, GO))
check('main denied while an agent holds', denied(out))

run(pre('a1', DONE))
# main starts an agent: its hold is freed
run(pre(None, GO))
out, dt, _ = run(pre(None, tool='Agent'))
check('main starts Agent: main hold freed', out is None and lock() is None)
out, dt, _ = run(pre('a6', GO))
check('subagent takes at once after main started an agent', out is None and dt < 0.7 and lock()['holder'] == 'a6')
run(pre('a6', DONE))
run(pre(None, GO))
out, dt, _ = run(pre('a6', GO))
check('main holds, no Agent call between: subagent still denied', denied(out) and lock()['holder'] == 'main')
run(pre('a6', tool='Task'))
check('a subagent starting an agent does not free main', lock()['holder'] == 'main')
run(pre(None, tool='Task'))
check('main starts Task: freed', lock() is None)
run(pre('a1', GO))
run(pre(None, tool='Agent'))
check('main starting an agent leaves a subagent hold alone', lock()['holder'] == 'a1')
run(pre('a1', DONE))
# wrappers
for cmd in ('timeout 30 claude-window go https://x', 'gtimeout -k 5 30 claude-window shot', 'time claude-window js 1',
            'env A=1 B=2 claude-window go x', 'nohup claude-window go x', 'exec claude-window go x',
            'sudo claude-window go x', 'A=1 claude-window go x', 'cd /t && timeout 9 claude-window go x'):
    run(pre('a1', DONE))
    run(pre('a1', cmd))
    check('wrapper counts as browser call: %s' % cmd, lock() is not None and lock()['holder'] == 'a1')
run(pre('a1', DONE))
run(pre('a1', 'timeout 30 claude-window done'))
run(pre('a1', GO))
out, _, _ = run(pre('a2', 'timeout 30 claude-window done'))
check('wrapped done by a non-holder changes nothing', lock()['holder'] == 'a1')
run(pre('a1', 'timeout 30 claude-window done'))
check('wrapped done by the holder frees', lock() is None)
for cmd in ('echo timeout claude-window', 'echo claude-window go', 'timeout 30 sleep 1'):
    run(pre('a1', GO))
    out, dt, _ = run(pre('a2', cmd))
    check('not a browser call: %s' % cmd, out is None and dt < 0.7 and lock()['holder'] == 'a1')
run(pre('a1', DONE))

# quoting and nesting
for cmd in ('sleep 1 & claude-window go x', '(claude-window go x)', 'echo $(claude-window go x)', 'echo `claude-window go x`',
            'bash -c "claude-window go x"', "sh -c 'cd /t && claude-window go x'", 'zsh -c "claude-window go x"',
            'sudo -E claude-window go x', 'echo "$(claude-window go x)"', 'git status;\nclaude-window go x',
            'git commit -m "a" && claude-window go x'):
    run(pre('a1', DONE))
    run(pre('a1', cmd))
    check('counts as browser call: %r' % cmd, lock() is not None and lock()['holder'] == 'a1')
run(pre('a1', DONE))
run(pre('a1', GO))
for cmd in ('git commit -m "fix; claude-window go x"', 'git commit -m "note\nclaude-window go x\nmore"',
            "git commit -m 'a | claude-window go x'", "echo $'a;claude-window go x'", 'echo "a && claude-window go"',
            'git log 2>&1 | head'):
    out, dt, _ = run(pre('a2', cmd))
    check('not a browser call: %r' % cmd, out is None and dt < 0.7 and lock()['holder'] == 'a1')
run(pre('a1', DONE))
run(pre('a1', GO))
s0 = lock()['since']
time.sleep(0.05)
run(pre('a1', GO))
check('since stays, at moves', lock()['since'] == s0 and lock()['at'] > s0)
run(pre('a1', DONE))

# sessions are separate
out, _, _ = run(pre('a2', GO, sid='s2'))
check('another session has its own lock', out is None and lock('s2')['holder'] == 'a2')

# old entries dropped
s = json.load(open(STATE))
s['browser']['old'] = {'holder': 'x', 'agent_type': 'x', 'at': time.time() - 90000}
json.dump(s, open(STATE, 'w'))
run(pre('a1', GO))
check('entries older than a day are dropped', lock('old') is None)

# bad input allows
for raw in ('', 'not json', '[]', '"x"', 'null', '{}', '{"hook_event_name": "PreToolUse"}'):
    out, _, rc = run(None, raw=raw)
    check('bad input %r: exit 0, no output' % raw, out is None and rc == 0)
out, _, rc = run(dict(hook_event_name='PreToolUse', session_id='s1', tool_name='Bash', tool_input='oops', agent_id='a7'))
check('tool_input not an object: allowed', out is None and rc == 0)
open(STATE, 'w').write('{broken')
out, _, rc = run(pre('a1', GO))
check('broken state file: allowed', out is None and rc == 0)
switch(True)

out, _, rc = run(pre('a1', 'echo "open'))
out2, _, _ = run(pre('a1', "claude-window go 'x"))
check('unbalanced quote: allowed', out is None and out2 is None and rc == 0)
check('unbalanced quote: one parse line per run', sum('browser parse' in l for l in open(LOG).read().splitlines()) == 2)
# log lines
lines = [l[20:] for l in open(LOG).read().splitlines()]
check('deny log line says holding since', any(l.startswith('browser deny') and 'holding since' in l for l in lines))
for word in ('wait', 'deny', 'take', 'free'):
    check('log has a "browser %s" line' % word, any(l.startswith('browser ' + word) for l in lines))

# install-hooks.py
home = os.path.join(tmp, 'home')
ikit = os.path.join(tmp, 'ikit')
os.makedirs(os.path.join(home, '.claude'))
shutil.copytree(HOOKS, os.path.join(ikit, 'hooks'))
SET = os.path.join(home, '.claude', 'settings.json')
json.dump({'hooks': {'PreToolUse': [{'hooks': [{'type': 'command', 'command': 'other-hook.sh'}]}],
                     'SubagentStop': [{'hooks': [{'type': 'command', 'command': 'other-stop.sh'}]}]}}, open(SET, 'w'))
IENV = dict(os.environ, HOME=home)
IENV.pop('STTARK_KIT_DIR', None)


def install(*args):
    return subprocess.run([sys.executable, os.path.join(ikit, 'hooks', 'install-hooks.py')] + list(args),
                          capture_output=True, text=True, env=IENV).stdout.strip()


def groups(event):
    return [g for g in json.load(open(SET)).get('hooks', {}).get(event, [])
            if any('browser-lock.py' in h['command'] for h in g['hooks'])]


install()
check('install, switch off: no browser entries', groups('PreToolUse') == [] and groups('SubagentStop') == [])
check('--status browser false', json.loads(install('--status'))['browser'] is False)
out = install('--orchestrator', 'on')
check('--orchestrator on: output ends with "browser on"', out.endswith('uicheck on, browser on'))
pg, sg = groups('PreToolUse'), groups('SubagentStop')
check('PreToolUse: one entry, matcher, quoted command, timeout over WAIT',
      len(pg) == 1 and pg[0]['matcher'] == '^(Bash|Agent|Task|mcp__claude-in-chrome__.*)$'
      and pg[0]['hooks'][0]['command'].endswith('browser-lock.py"') and pg[0]['hooks'][0]['timeout'] > 50)
check('matcher matches Bash and chrome tools only',
      all(re.search(pg[0]['matcher'], n) for n in ('Bash', 'mcp__claude-in-chrome__navigate'))
      and not any(re.search(pg[0]['matcher'], n) for n in ('Read', 'mcp__asana__get_task', 'BashOutput')))
check('SubagentStop: one entry, no matcher', len(sg) == 1 and 'matcher' not in sg[0])
check('--status browser true', json.loads(install('--status'))['browser'] is True)
install()
check('launch run keeps one entry each', len(groups('PreToolUse')) == 1 and len(groups('SubagentStop')) == 1)
check('launch run with nothing new: unchanged', install() == 'unchanged')
out = install('--orchestrator', 'off')
check('--orchestrator off: entries removed, output ends with "browser off"',
      groups('PreToolUse') == [] and groups('SubagentStop') == [] and out.endswith('uicheck off, browser off'))
check('other hooks left alone',
      any(h.get('command') == 'other-hook.sh' for g in json.load(open(SET))['hooks']['PreToolUse'] for h in g['hooks'])
      and any(h.get('command') == 'other-stop.sh' for g in json.load(open(SET))['hooks']['SubagentStop'] for h in g['hooks']))
json.dump({'orchestrator': True}, open(os.path.join(ikit, 'state.json'), 'w'))
install()
check('launch run brings entries in line with the switch (on)', len(groups('PreToolUse')) == 1 and len(groups('SubagentStop')) == 1)
install('--remove')
check('--remove removes the entries', groups('PreToolUse') == [] and groups('SubagentStop') == [])

shutil.rmtree(tmp, ignore_errors=True)
print('\n%d passed, %d failed' % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
