"""Test the inline guard (Resources/hooks/inline-guard.py) and its install (install-hooks.py), on copies only:
a temp state folder, a temp log, and a temp HOME with a temp kit folder. No model calls.
Run: /usr/bin/python3 tools/inline-guard-test.py"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, 'Resources', 'hooks')
GUARD = os.path.join(HOOKS, 'inline-guard.py')
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


tmp = tempfile.mkdtemp(prefix='inline-guard-test-')
KIT = os.path.join(tmp, 'kit')
LOG = os.path.join(tmp, 'kit.log')
os.makedirs(KIT)
ENV = dict(os.environ, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG)


def switch(on):
    p = os.path.join(KIT, 'state.json')
    try:
        s = json.load(open(p))
    except (OSError, ValueError):
        s = {}
    s['orchestrator'] = on
    json.dump(s, open(p, 'w'))


def run(event, sid='s1', **kw):
    data = dict(hook_event_name=event, session_id=sid, **kw)
    r = subprocess.run([sys.executable, GUARD], input=json.dumps(data), capture_output=True, text=True, env=ENV)
    return json.loads(r.stdout) if r.stdout.strip() else None


def tool(name, sid='s1', **ti):
    return run('PreToolUse', sid, tool_name=name, tool_input=ti)


def denied(out, reason=None):
    h = (out or {}).get('hookSpecificOutput') or {}
    return h.get('permissionDecision') == 'deny' and (reason is None or h.get('permissionDecisionReason') == reason)


LOOK = 'Delegate this. Write a brief and start an agent.'
IMPL = 'Delegate to implementer.'
OPS = 'Delegate to implementer or ops.'

# Switch off: nothing at all
switch(False)
outs = [tool('Read', file_path='/x') for _ in range(4)] + [tool('Bash', command='make')]
check('switch off: no output for 4 reads and a build', all(o is None for o in outs))
check('switch off: no state written', 'guard' not in json.load(open(os.path.join(KIT, 'state.json'))))

switch(True)
# Subagent: always let through
outs = [run('PreToolUse', 'sa', tool_name='Read', tool_input={'file_path': '/x'}, agent_id='a1') for _ in range(4)]
outs.append(run('PreToolUse', 'sa', tool_name='Bash', tool_input={'command': 'npm test'}, agent_id='a1'))
outs.append(run('PreToolUse', 'sa', tool_name='Write', tool_input={'file_path': '/x.py', 'content': 'a\n' * 50},
                agent_id='a1'))
check('subagent (agent_id): every call let through', all(o is None for o in outs))

# Count: 2 allowed, the 3rd denied, and the deny does not count
check('1st lookup allowed', tool('Read', file_path='/a') is None)
check('2nd lookup allowed', tool('Grep', pattern='x') is None)
check('3rd lookup denied with the lookup reason', denied(tool('Glob', pattern='*'), LOOK))
check('4th lookup still denied', denied(tool('WebSearch', query='x'), LOOK))
check('count stays at 2 (denied calls not counted)',
      json.load(open(os.path.join(KIT, 'state.json')))['guard']['s1']['n'] == 2)
check('other session has its own count', tool('Read', 's2', file_path='/a') is None)

# Reset on prompt
run('UserPromptSubmit', prompt='next')
check('after a prompt: lookup allowed', tool('Read', file_path='/a') is None)
check('after a prompt: 2nd allowed', tool('WebFetch', url='https://x') is None)
check('after a prompt: 3rd denied', denied(tool('Read', file_path='/a'), LOOK))

# Reset on Agent and on Task
check('Agent call itself let through', tool('Agent', prompt='brief') is None)
check('after Agent: lookup allowed', tool('Read', file_path='/a') is None)
tool('Read', file_path='/a')
check('after Agent: 3rd denied again', denied(tool('Read', file_path='/a'), LOOK))
tool('Task', prompt='brief')
check('after Task: lookup allowed', tool('Read', file_path='/a') is None)

# MCP read tools count, mcp__ccd_ and MCP write tools do not
run('UserPromptSubmit')
for _ in range(5):
    tool('mcp__ccd_session__list_sessions')
    tool('mcp__github__create_issue')
check('mcp__ccd_ and mcp write tools not counted', tool('Read', file_path='/a') is None)
check('mcp read tool counted (2nd)', tool('mcp__github__get_file_contents') is None)
check('mcp read tool denied as 3rd', denied(tool('mcp__x__search_code'), LOOK))
run('UserPromptSubmit')
check('mcp read tool allowed after reset', tool('mcp__x__list_issues') is None)

# Edits
run('UserPromptSubmit')
small_old = 'a\nb\nc\nd\ne\nf\n'
small_new = 'a\nB\nC\nD\ne\nf\n'
check('Edit of 3 lines allowed', tool('Edit', file_path='/r/x.py', old_string=small_old, new_string=small_new) is None)
check('Edit of 1 line in 10 lines of context allowed',
      tool('Edit', file_path='/r/x.py', old_string='\n'.join('l%d' % i for i in range(10)),
           new_string='\n'.join('l%d' % i if i != 4 else 'X' for i in range(10))) is None)
big_old = '\n'.join('o%d' % i for i in range(10))
big_new = '\n'.join('n%d' % i for i in range(10))
check('Edit of 10 lines denied', denied(tool('Edit', file_path='/r/x.py', old_string=big_old, new_string=big_new), IMPL))
check('Edit adding 10 lines denied', denied(tool('Edit', file_path='/r/x.py', old_string='a', new_string='a\n' * 10), IMPL))
check('MultiEdit of 2 + 2 lines denied',
      denied(tool('MultiEdit', file_path='/r/x.py', edits=[{'old_string': 'a\nb', 'new_string': 'c\nd'},
                                                           {'old_string': 'e\nf', 'new_string': 'g\nh'}]), IMPL))
check('NotebookEdit of 10 lines denied', denied(tool('NotebookEdit', notebook_path='/r/n.ipynb', new_source='x\n' * 10), IMPL))
check('day log edit allowed (big)',
      tool('Edit', file_path=os.path.join(KIT, 'daylog', '2026-11-09.md'), old_string=big_old, new_string=big_new) is None)
check('state file write allowed (big)',
      tool('Write', file_path=os.path.join(KIT, 'orchestrator', 'state', 'plan.json'), content='x\n' * 100) is None)
check('NEXT.md edit allowed (big)', tool('Edit', file_path='/r/NEXT.md', old_string=big_old, new_string=big_new) is None)
check('next-steps.txt write allowed (any case)', tool('Write', file_path='/r/next-steps.txt', content='x\n' * 40) is None)
check('Write of a big new file denied', denied(tool('Write', file_path=os.path.join(tmp, 'new.py'), content='x\n' * 40), IMPL))
check('Write of a 3-line new file allowed', tool('Write', file_path=os.path.join(tmp, 'new.py'), content='a\nb\nc\n') is None)
open(os.path.join(tmp, 'old.py'), 'w').write('x\n')
check('Write over an existing file denied', denied(tool('Write', file_path=os.path.join(tmp, 'old.py'), content='a\n'), IMPL))
check('edits do not count as lookups', tool('Read', file_path='/a') is None)

# Long Bash runs: denied as the 1st call
for cmd in ['npm install', 'pnpm test', 'yarn build', 'npm run build', 'npm ci', 'pytest -q', 'python3 -m pytest tests',
            'swift build', 'swift test', 'xcodebuild -scheme X', 'make', 'cargo test', 'go build ./...',
            'pip install requests', 'brew install jq', './gradlew assemble', './build.sh', './install.sh',
            'cd /r && make all', 'FOO=1 sudo npm install', 'bash build.sh']:
    run('UserPromptSubmit')
    check(f'long run denied as 1st call: {cmd}', denied(tool('Bash', command=cmd), OPS))
run('UserPromptSubmit')
for cmd in ['git status', 'ls -la', 'grep -n make Makefile']:
    check(f'short Bash allowed: {cmd}', tool('Bash', command=cmd) is None)
    run('UserPromptSubmit')
check('denied long run not counted', [tool('Bash', command='make'), tool('Read', file_path='/a'),
                                       tool('Read', file_path='/a')][1:] == [None, None])

# PostToolUse: a note over 8,000 characters
note = 'That lookup was too big for inline. Delegate the next one.'
big = run('PostToolUse', tool_name='Read', tool_input={}, tool_response={'file': {'content': 'x' * 9000}})
check('PostToolUse over 8,000 adds the note',
      (big or {}).get('hookSpecificOutput', {}).get('additionalContext') == note
      and big['hookSpecificOutput']['hookEventName'] == 'PostToolUse' and 'decision' not in big)
check('PostToolUse under 8,000: nothing',
      run('PostToolUse', tool_name='Read', tool_input={}, tool_response='x' * 7000) is None)
check('PostToolUse of a non-lookup tool: nothing',
      run('PostToolUse', tool_name='Edit', tool_input={}, tool_response='x' * 9000) is None)
check('PostToolUse in a subagent: nothing',
      run('PostToolUse', tool_name='Read', tool_input={}, tool_response='x' * 9000, agent_id='a1') is None)

# Log
log = open(LOG).read().splitlines()
check('deny lines logged with "guard  deny"', any(l[20:].startswith('guard  deny   s1') for l in log))
check('big result logged with "guard  big"', any(l[20:].startswith('guard  big') for l in log))
check('no error lines in the log', not any('error' in l for l in log))

# Old entries dropped after a day
st = json.load(open(os.path.join(KIT, 'state.json')))
st['guard']['old'] = {'n': 2, 'at': 0}
json.dump(st, open(os.path.join(KIT, 'state.json'), 'w'))
run('UserPromptSubmit')
check('entries older than a day dropped', 'old' not in json.load(open(os.path.join(KIT, 'state.json'))).get('guard', {}))

# install-hooks.py: a temp HOME, and a temp kit folder (the parent of the hooks folder)
home = os.path.join(tmp, 'home')
ikit = os.path.join(tmp, 'ikit')
os.makedirs(os.path.join(home, '.claude'))
shutil.copytree(HOOKS, os.path.join(ikit, 'hooks'))
other = {'hooks': {'PreToolUse': [{'hooks': [{'type': 'command', 'command': 'other-hook.sh'}]}]}}
SET = os.path.join(home, '.claude', 'settings.json')
json.dump(other, open(SET, 'w'))
IENV = dict(os.environ, HOME=home)
IENV.pop('STTARK_KIT_DIR', None)


def install(*args):
    return subprocess.run([sys.executable, os.path.join(ikit, 'hooks', 'install-hooks.py')] + list(args),
                          capture_output=True, text=True, env=IENV).stdout.strip()


def guard_events():
    s = json.load(open(SET))
    return sorted(e for e, gs in s.get('hooks', {}).items()
                  if any('inline-guard.py' in h.get('command', '') for g in gs for h in g.get('hooks', [])))


ALL = ['PostToolUse', 'PreToolUse', 'UserPromptSubmit']
install()
check('install, switch off: no guard entries', guard_events() == [])
check('--status guard false', json.loads(install('--status'))['guard'] is False)
out = install('--orchestrator', 'on')
check('--orchestrator on: guard entries in all three events', guard_events() == ALL)
check('--orchestrator on: output says guard on', 'guard on' in out)
check('--status guard true', json.loads(install('--status'))['guard'] is True)
install()
check('launch run, switch on: guard entries kept, one copy each',
      guard_events() == ALL and json.dumps(json.load(open(SET))).count('inline-guard.py') == 3)
check('launch run with nothing new: unchanged', install() == 'unchanged')
install('--orchestrator', 'off')
check('--orchestrator off: guard entries out', guard_events() == [])
json.dump({'orchestrator': True}, open(os.path.join(ikit, 'state.json'), 'w'))   # switched on by hand
install()
check('launch run brings guard entries in line with the switch (on)', guard_events() == ALL)
json.dump({'orchestrator': False}, open(os.path.join(ikit, 'state.json'), 'w'))
install()
check('launch run brings guard entries in line with the switch (off)', guard_events() == [])
install('--orchestrator', 'on')
install('--remove')
check('--remove: guard entries out, switch on', guard_events() == [])
check('other hooks left alone',
      any(h.get('command') == 'other-hook.sh' for g in json.load(open(SET))['hooks']['PreToolUse'] for h in g['hooks']))

shutil.rmtree(tmp)
print(f'\n{len(passed)} passed, {len(failed)} failed')
sys.exit(1 if failed else 0)
