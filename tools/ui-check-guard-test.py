"""Test the page-check guard (Resources/hooks/ui-check-guard.py) and its install (install-hooks.py), on copies
only: a temp kit folder, a temp log, temp git repos, fake transcripts and a temp HOME. No model calls.
Run: /usr/bin/python3 tools/ui-check-guard-test.py"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, 'Resources', 'hooks')
HOOK = os.path.join(HOOKS, 'ui-check-guard.py')
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


tmp = tempfile.mkdtemp(prefix='ui-check-guard-test-')
KIT = os.path.join(tmp, 'kit')
LOG = os.path.join(tmp, 'kit.log')
os.makedirs(KIT)
ENV = dict(os.environ, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG)


def switch(on):
    json.dump({'orchestrator': on}, open(os.path.join(KIT, 'state.json'), 'w'))


def git(cwd, *a):
    subprocess.run(['git', '-C', cwd, *a], capture_output=True, check=True)


APP = os.path.join(tmp, 'app')
os.makedirs(os.path.join(APP, 'scripts'))
open(os.path.join(APP, 'scripts', 'page-check.mjs'), 'w').write('// page check\n')
git(APP, 'init', '-q')
PLAIN = os.path.join(tmp, 'plain')
os.makedirs(PLAIN)
git(PLAIN, 'init', '-q')
git(PLAIN, 'remote', 'add', 'origin', 'https://github.com/x/plain.git')


def transcript(name, edits, final='Done.', tool='Edit', handback=None, errors=()):
    p = os.path.join(tmp, name + '.jsonl')
    with open(p, 'w') as f:
        f.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'go'}}) + '\n')
        for n, e in enumerate(edits):
            f.write(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': 'tu%d' % n, 'name': tool, 'input': {'file_path': e}}]}}) + '\n')
            f.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': 'tu%d' % n, 'is_error': n in errors,
                 'content': 'error' if n in errors else 'ok'}]}}) + '\n')
        blocks = [{'type': 'text', 'text': final}]
        if handback:
            blocks.append({'type': 'tool_use', 'name': 'SubagentHandback', 'input': {'message': handback}})
        f.write(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': blocks}}) + '\n')
    return p


def run(cwd=APP, agent='implementer', tp=None, last=None, active=False):
    data = dict(hook_event_name='SubagentStop', session_id='s1', agent_id='a1', agent_type=agent, cwd=cwd,
                stop_hook_active=active)
    if tp:
        data['agent_transcript_path'] = tp
    if last is not None:
        data['last_assistant_message'] = last
    r = subprocess.run([sys.executable, HOOK], input=json.dumps(data), capture_output=True, text=True, env=ENV)
    return json.loads(r.stdout) if r.stdout.strip() else None


def log():
    return open(LOG).read().splitlines() if os.path.exists(LOG) else []


TSX = os.path.join(APP, 'src', 'components', 'Card.tsx')
UI = transcript('ui', [TSX])
GOOD = 'Changed Card.tsx. page-check: Every page passes (12 page views)'

switch(False)
check('switch off allows', run(tp=UI, last='Done.') is None)
switch(True)
check('non-implementer allows', run(agent='validator', tp=UI, last='Done.') is None)
check('plain repo allows', run(cwd=PLAIN, tp=UI, last='Done.') is None)
out = run(tp=UI, last='Done.')
check('UI change without page-check output blocks', out is not None and out.get('decision') == 'block')
check('reason names the file and script', 'Card.tsx' in out['reason'] and 'scripts/page-check.mjs' in out['reason']
      and out['reason'].startswith('You changed UI files (Card.tsx) and your report has no page-check output.'))
check('page-check output in last message allows', run(tp=UI, last=GOOD) is None)
check('page-check name without a result is not enough', run(tp=UI, last='I will run page-check later.') is not None)
check('generic word ok is not page-check output', run(tp=UI, last='I did not run page-check; that is ok.') is not None)
check('pass/fail/error words are not page-check output',
      run(tp=UI, last='page-check: tests pass, no error, nothing failed') is not None)
check('pasted real result block allows',
      run(tp=UI, last='Ran:\n```\nnode scripts/page-check.mjs\n\nEvery page passes (12 page views)\n```') is None)
check('problems result near the name allows',
      run(tp=UI, last='page-check output:\n3 problems (5 with every page) on 12 page views') is None)
check('result far from the name does not allow',
      run(tp=UI, last='page-check later.\n' + 'x\n' * 10 + 'Every page passes (1 page views)') is not None)
check('denied edit does not count', run(tp=transcript('t7', [TSX], errors=(0,)), last='Done.') is None)
check('failed edit does not count', run(tp=transcript('t8', [TSX], errors=(0,)), last='Done.') is None)
check('one failed, one ok edit blocks', run(tp=transcript('t9', [TSX, os.path.join(APP, 'b.css')], errors=(0,)),
                                           last='Done.') is not None)
check('successful edit blocks without output', run(tp=transcript('t10', [TSX]), last='Done.') is not None)
check('output in transcript text allows', run(tp=transcript('t2', [TSX], final=GOOD), last='') is None)
check('output in SubagentHandback message allows',
      run(tp=transcript('t3', [TSX], handback=GOOD), last='Done.') is None)
check('non-UI change allows', run(tp=transcript('t4', [os.path.join(APP, 'src', 'lib', 'util.ts'),
                                                       os.path.join(APP, 'README.md'),
                                                       os.path.join(APP, 'src', 'components', 'Card.test.tsx')]),
                                   last='Done.') is None)
check('MultiEdit and Write count', run(tp=transcript('t5', [os.path.join(APP, 'a.css')], tool='Write'),
                                        last='Done.') is not None)
many = transcript('t6', [os.path.join(APP, 'pages', 'p%d.html' % i) for i in range(7)])
check('reason lists up to 5 names', run(tp=many, last='x')['reason'].count('.html') == 5)
check('stop_hook_active allows', run(tp=UI, last='Done.', active=True) is None)
check('missing transcript allows', run(tp=os.path.join(tmp, 'none.jsonl'), last='Done.') is None)
check('no transcript path allows', run(last='Done.') is None)
r = subprocess.run([sys.executable, HOOK], input='not json', capture_output=True, text=True, env=ENV)
check('bad input allows', r.returncode == 0 and not r.stdout.strip())
lines = [l[20:] for l in log()]
check('log: block line', any(l.startswith('uicheck block, 1 UI files: Card.tsx') for l in lines))
check('log: allow with reason line', any(l.startswith('uicheck allow, page-check output found') for l in lines))
check('log: already blocked line', any(l.startswith('uicheck allow, already blocked once') for l in lines))
check('log: error lines', sum(l.startswith('uicheck error') for l in lines) >= 2)

# is_ui rules
import importlib.util
spec = importlib.util.spec_from_file_location('uic', HOOK)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
for path, want in [('src/app/page.tsx', True), ('src/lib/x.ts', False), ('a/b.vue', True), ('public/logo.svg', True),
                   ('docs/x.md', False), ('app/README.md', False), ('app/x.test.tsx', False),
                   ('src/ui/y.js', True), ('app/db/models.py', False), ('app/api/users/route.ts', False),
                   ('app/page.tsx', True), ('components/Button.vue', True), ('src/ui/x.ts', True),
                   ('src/lib/x.js', False), ('public/font.woff2', True), ('public/data.json', False),
                   ('server/x.ts', False), ('e2e/home.spec.ts', False), ('styles/a.scss', True)]:
    check('is_ui %s = %s' % (path, want), m.is_ui(path) is want)

# install-hooks.py
home = os.path.join(tmp, 'home')
ikit = os.path.join(tmp, 'ikit')
os.makedirs(os.path.join(home, '.claude'))
shutil.copytree(HOOKS, os.path.join(ikit, 'hooks'))
SET = os.path.join(home, '.claude', 'settings.json')
json.dump({'hooks': {'SubagentStop': [{'hooks': [{'type': 'command', 'command': 'other-hook.sh'}]}]}}, open(SET, 'w'))
IENV = dict(os.environ, HOME=home)
IENV.pop('STTARK_KIT_DIR', None)


def install(*args):
    return subprocess.run([sys.executable, os.path.join(ikit, 'hooks', 'install-hooks.py')] + list(args),
                          capture_output=True, text=True, env=IENV).stdout.strip()


def groups():
    s = json.load(open(SET))
    return [g for g in s.get('hooks', {}).get('SubagentStop', [])
            if any('ui-check-guard.py' in h['command'] for h in g['hooks'])]


install()
check('install, switch off: no uicheck entry', groups() == [])
check('--status uicheck false', json.loads(install('--status'))['uicheck'] is False)
out = install('--orchestrator', 'on')
check('--orchestrator on: output names uicheck', out.endswith('guard on, subrules on, uicheck on'))
check('--orchestrator on: one entry, matcher implementer, command quoted',
      len(groups()) == 1 and groups()[0]['matcher'] == 'implementer'
      and groups()[0]['hooks'][0]['command'].startswith('"') and groups()[0]['hooks'][0]['command'].endswith('ui-check-guard.py"'))
check('--status uicheck true', json.loads(install('--status'))['uicheck'] is True)
install()
check('launch run keeps one entry', len(groups()) == 1)
out = install('--orchestrator', 'off')
check('--orchestrator off: entry removed, output names uicheck', groups() == [] and out.endswith('uicheck off'))
check('other SubagentStop hooks left alone',
      any(h.get('command') == 'other-hook.sh' for g in json.load(open(SET))['hooks']['SubagentStop'] for h in g['hooks']))
install('--orchestrator', 'on')
install('--remove')
check('--remove removes the entry', groups() == [])

shutil.rmtree(tmp, ignore_errors=True)
print('\n%d passed, %d failed' % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
