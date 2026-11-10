"""Test the subagent rules hook (Resources/hooks/subagent-rules-hook.py) and its install (install-hooks.py),
on copies only: a temp kit folder, a temp log, temp git repos and a temp HOME. No model calls.
Run: /usr/bin/python3 tools/subagent-rules-test.py"""
import importlib.util, json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, 'Resources', 'hooks')
HOOK = os.path.join(HOOKS, 'subagent-rules-hook.py')
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


tmp = tempfile.mkdtemp(prefix='subagent-rules-test-')
KIT = os.path.join(tmp, 'kit')
LOG = os.path.join(tmp, 'kit.log')
os.makedirs(KIT)
ENV = dict(os.environ, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG)


def switch(on):
    json.dump({'orchestrator': on}, open(os.path.join(KIT, 'state.json'), 'w'))


def run(cwd, agent='implementer'):
    data = dict(hook_event_name='SubagentStart', session_id='s1', agent_id='a1', agent_type=agent, cwd=cwd)
    r = subprocess.run([sys.executable, HOOK], input=json.dumps(data), capture_output=True, text=True, env=ENV)
    return json.loads(r.stdout) if r.stdout.strip() else None


def run_raw(raw):
    r = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True, text=True, env=ENV)
    return r.returncode, r.stdout.strip()


def text_of(out):
    return ((out or {}).get('hookSpecificOutput') or {}).get('additionalContext') or ''


def git(cwd, *args):
    subprocess.run(['git', '-C', cwd, *args], capture_output=True, check=True)


plain = os.path.join(tmp, 'plain')
app = os.path.join(tmp, 'app')
for d in (plain, app):
    os.makedirs(d)
    git(d, 'init', '-q')
    open(os.path.join(d, 'README.md'), 'w').write('x\n')
os.makedirs(os.path.join(app, 'scripts'))
open(os.path.join(app, 'scripts', 'page-check.mjs'), 'w').write('// launcher\n')
git(app, 'add', '-A')

# Switch off: nothing
switch(False)
check('switch off: no output', run(plain) is None)
check('switch off: no log line', not os.path.exists(LOG) or 'added' not in open(LOG).read())

# Switch on: the worker rules, not the person rules
switch(True)
out = run(plain)
t = text_of(out)
check('output form: SubagentStart additionalContext',
      out is not None and out['hookSpecificOutput']['hookEventName'] == 'SubagentStart' and t)
WORKER = ["Don't know it? Search. Don't guess.", 'Repo work: read the project docs before you change anything. Do not pull, switch branches or reset unless your brief says so.', 'treat it as one instance of a pattern. Fix every instance',
          'UI and layout: function over form', 'Asana tasks: give the full URL', 'No em-dashes or double hyphens in text a person reads']
for w in WORKER:
    check('worker rule present: ' + w[:40], w in t)
check('repo-work rule: no pull-latest wording', 'pull latest' not in t)
check('6 rule lines', len([l for l in t.splitlines() if l.startswith('- ')]) == 6)
for p in ['Simplified Technical English', 'asks table', 'number the asks', 'two lines plus a step count', 'Answer the person',
          'Shortest reply', 'End of turn', 'Work like a manager', 'Visuals are better', 'A question is not an instruction']:
    check('person rule absent: ' + p, p not in t)
check('lead line', t.startswith('Sttark worker rules (from Sttark Claude Kit), for this subagent:'))
check('marker line present', 'Sttark context: present.' in t.splitlines())
check('plain repo: no chapters pointer, no page-check line', 'chapters.json' not in t and 'page-check' not in t)
check('outside any repo: no pointer', 'chapters.json' not in text_of(run(tmp)))

# Valid JSON that is not an object: exit 0, no output
for raw in ('[]', '"x"', '5', 'null', 'true'):
    check('non-object JSON %s: exit 0, no output' % raw, run_raw(raw) == (0, ''))
check('bad JSON: exit 0, no output', run_raw('{') == (0, ''))

# A Sttark app repo
ta = text_of(run(app, 'validator'))
check('app repo: chapters pointer with the full path', os.path.join(KIT, 'app-rules', 'chapters.json') in ta)
check('app repo: page-check line', 'Run page-check before you report UI work, and include its output.' in ta)
check('app repo: worker rules and marker still there', "Don't know it?" in ta and 'Sttark context: present.' in ta)
check('app repo: chapters not copied in', len(ta) < 3000)

# A missing rule is skipped and logged
spec = importlib.util.spec_from_file_location('subrules', HOOK)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.LOG = LOG
work = importlib.util.spec_from_file_location('work', os.path.join(HOOKS, 'working-rules-hook.py'))
wm = importlib.util.module_from_spec(work)
work.loader.exec_module(wm)
cut = '\n'.join(l for l in wm.RULES.splitlines() if not l.startswith('- Asana tasks:'))
lines = mod.worker_rules(cut)
check('missing rule: skipped, 5 left', len(lines) == 5 and not any('Asana' in l for l in lines))
check('missing rule: logged', any('missing rule, skipped: - Asana tasks:' in l for l in open(LOG)))
check('missing rule: hook builds without failing', 'Sttark context: present.' in mod.build(plain, cut)[0])

# Log lines
log = open(LOG).read().splitlines()
check('log: "subrules implementer added worker rules"', any(l[20:].startswith('subrules implementer added worker rules') for l in log))
check('log: app repo line with agent type', any(l[20:].startswith('subrules validator added worker rules and app pointer') for l in log))

# install-hooks.py: a temp HOME, and a temp kit folder (the parent of the hooks folder)
home = os.path.join(tmp, 'home')
ikit = os.path.join(tmp, 'ikit')
os.makedirs(os.path.join(home, '.claude'))
shutil.copytree(HOOKS, os.path.join(ikit, 'hooks'))
SET = os.path.join(home, '.claude', 'settings.json')
json.dump({'hooks': {'SubagentStart': [{'hooks': [{'type': 'command', 'command': 'other-hook.sh'}]}]}}, open(SET, 'w'))
IENV = dict(os.environ, HOME=home)
IENV.pop('STTARK_KIT_DIR', None)


def install(*args):
    return subprocess.run([sys.executable, os.path.join(ikit, 'hooks', 'install-hooks.py')] + list(args),
                          capture_output=True, text=True, env=IENV).stdout.strip()


def sub():
    s = json.load(open(SET))
    return [h['command'] for g in s.get('hooks', {}).get('SubagentStart', []) for h in g['hooks']
            if 'subagent-rules-hook.py' in h['command']]


install()
check('install, switch off: no SubagentStart entry', sub() == [])
check('--status subrules false', json.loads(install('--status'))['subrules'] is False)
out = install('--orchestrator', 'on')
check('--orchestrator on: output says guard on, subrules on', out.endswith('guard on, subrules on'))
check('--orchestrator on: SubagentStart entry added', len(sub()) == 1)
check('--status subrules true', json.loads(install('--status'))['subrules'] is True)
install()
check('launch run, switch on: one copy', len(sub()) == 1)
check('launch run with nothing new: unchanged', install() == 'unchanged')
install('--orchestrator', 'off')
check('--orchestrator off: entry out', sub() == [])
json.dump({'orchestrator': True}, open(os.path.join(ikit, 'state.json'), 'w'))
install()
check('launch run brings entry in line with the switch (on)', len(sub()) == 1)
json.dump({'orchestrator': False}, open(os.path.join(ikit, 'state.json'), 'w'))
install()
check('launch run brings entry in line with the switch (off)', sub() == [])
install('--orchestrator', 'on')
install('--remove')
check('--remove: entry out, switch on', sub() == [])
check('other SubagentStart hooks left alone',
      any(h.get('command') == 'other-hook.sh' for g in json.load(open(SET))['hooks']['SubagentStart'] for h in g['hooks']))

shutil.rmtree(tmp)
print(f'\n{len(passed)} passed, {len(failed)} failed')
sys.exit(1 if failed else 0)
