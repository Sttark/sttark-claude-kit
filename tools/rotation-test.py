"""Test the rotation hook (Resources/hooks/rotation-hook.py) on a temp kit folder, a temp log and fake transcripts.
No model calls. Run: /usr/bin/python3 tools/rotation-test.py"""
import json, os, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, 'Resources', 'hooks', 'rotation-hook.py')
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


tmp = tempfile.mkdtemp(prefix='rotation-test-')
KIT = os.path.join(tmp, 'kit')
LOG = os.path.join(tmp, 'kit.log')
os.makedirs(KIT)
ENV = dict(os.environ, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG)
ENV.pop('STTARK_CONTEXT_WINDOW', None)


def state(**kw):
    p = os.path.join(KIT, 'state.json')
    try:
        s = json.load(open(p))
    except (OSError, ValueError):
        s = {}
    s.update(kw)
    json.dump(s, open(p, 'w'))


def transcript(tokens, model='claude-opus-4-7', name='t.jsonl'):
    p = os.path.join(tmp, name)
    third = tokens // 3
    with open(p, 'w') as f:
        f.write(json.dumps({'type': 'user', 'message': {'content': 'hi'}}) + '\n')
        f.write(json.dumps({'type': 'assistant', 'message': {'model': model, 'usage': {
            'input_tokens': tokens - 2 * third, 'cache_read_input_tokens': third,
            'cache_creation_input_tokens': third}}}) + '\n')
        # a subagent's later message must not count
        f.write(json.dumps({'type': 'assistant', 'isSidechain': True, 'message': {'model': model, 'usage': {
            'input_tokens': 1}}}) + '\n')
    return p


def run(path, sid='s1', title='', env=None):
    data = dict(hook_event_name='UserPromptSubmit', session_id=sid, transcript_path=path, prompt='x')
    if title:
        data['session_title'] = title
    r = subprocess.run([sys.executable, HOOK], input=json.dumps(data), capture_output=True, text=True, env=env or ENV)
    if not r.stdout.strip():
        return None
    return json.loads(r.stdout)['hookSpecificOutput']['additionalContext']


state(orchestrator=False)
check('switch off: nothing even at 90%', run(transcript(180_000)) is None)

state(orchestrator=True)
check('50%: nothing', run(transcript(100_000), 'a') is None)
t = run(transcript(122_000), 'a')
check('61%: the 60 text', bool(t) and t.startswith('Rotation (Sttark orchestrator): context 61% used.')
      and 'claude-daylog open --repo <repo> --item' in t and '/clear' in t and 'do not start new work' not in t)
check('65%: not again', run(transcript(130_000), 'a') is None)
t = run(transcript(142_000), 'a')
check('71%: again', bool(t) and 'context 71% used' in t)
t = run(transcript(162_000), 'a')
check('81%: the now text', bool(t) and t.startswith('Rotation now (Sttark orchestrator): context 81% used.')
      and 'Do it at the first clean stopping point; do not start new work first.' in t)
check('85%: not again', run(transcript(170_000), 'a') is None)
check('another session starts fresh', bool(run(transcript(122_000), 'b')))

check('1M model by name: 250k is 25%, nothing', run(transcript(250_000, 'claude-opus-4-7[1m]'), 'c') is None)
t = run(transcript(650_000, 'claude-opus-4-7[1m]'), 'c')
check('1M model by name: 650k is 65%', bool(t) and 'context 65% used' in t)
t = run(transcript(650_000), 'd')
check('1M window from usage over 200k: 650k is 65%', bool(t) and 'context 65% used' in t)

env = dict(ENV, STTARK_CONTEXT_WINDOW='100000')
t = run(transcript(70_000), 'e', env=env)
check('env override: 70k of 100k is 70%', bool(t) and 'context 70% used' in t)

auto = {'auto_names': {'cse_1': 'Docs', 'cse_2': 'Warehouse'}}
state(**auto)
low = transcript(20_000)
check('first title seen: nothing', run(low, 'f', 'Docs') is None)
check('same title: nothing', run(low, 'f', 'Docs') is None)
t = run(low, 'f', 'Warehouse')
check('rename by the name hook: said once', bool(t) and 'context 10% used, and the session moved to a new topic.' in t
      and t.startswith('Rotation (Sttark orchestrator)'))
check('rename: not again', run(low, 'f', 'Warehouse') is None)
check('a name set by hand is not a rename', run(low, 'f', 'My Own Name') is None)

state(orchestrator=True)
before = open(LOG).read().count('rotate error')
bad = os.path.join(tmp, 'bad.jsonl')
open(bad, 'w').write('not json\n{"type":\n')
check('bad transcript: nothing', run(bad, 'g') is None)
check('missing transcript: nothing', run(os.path.join(tmp, 'none.jsonl'), 'g') is None)
# first prompt of a session: the transcript file does not exist yet; no error, title still recorded
state(**auto)
missing = os.path.join(os.path.dirname(low), 'nope.jsonl')
check('missing transcript: nothing said', run(missing, 'g', 'Docs') is None)
check('missing transcript: title recorded, no error',
      json.load(open(os.path.join(KIT, 'state.json')))['rotation']['g']['name'] == 'Docs' and open(LOG).read().count('rotate error') == before)

log = open(LOG).read()
check('missing transcript is not logged as an error', log.count('rotate error') == before)
check('log lines start with rotate', all(l.split(' ', 2)[2].startswith('rotate') for l in log.splitlines()))
check('state keeps rotation per session', 'a' in json.load(open(os.path.join(KIT, 'state.json')))['rotation'])

print(f'\n{len(passed)} passed, {len(failed)} failed')
sys.exit(1 if failed else 0)
