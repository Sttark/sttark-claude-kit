#!/usr/bin/python3
"""Tests claude-wait on copies: a temporary state folder and log, STTARK_WAIT_DRY so nothing is brought back or sent.
Checks the times it reads, that --by and --why are needed, the list, cancel, and that the minute check ends a time
wait, a deadline and a merged pull request (Sttark/sttark-claude-kit#83, read with gh) and keeps an open one.
Run from the repo root: /usr/bin/python3 tools/wait-test.py"""
import datetime as dt, importlib.util, json, os, subprocess, sys, tempfile, time

HOOK = os.path.abspath('Resources/hooks/wait.py')
d = tempfile.mkdtemp(prefix='kit-wait-')
env = dict(os.environ, STTARK_KIT_DIR=d, STTARK_KIT_LOG=os.path.join(d, 'log'), STTARK_WAIT_DRY='1')
json.dump({}, open(os.path.join(d, 'state.json'), 'w'))


def run(*a):
    r = subprocess.run(['/usr/bin/python3', HOOK] + list(a), capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


spec = importlib.util.spec_from_file_location('w', HOOK)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
thu = dt.datetime(2026, 11, 12, 16, 0)
assert dt.datetime.fromtimestamp(w.when('2 weekdays', thu)).weekday() == 0, 'Thursday + 2 weekdays is Monday'
assert w.when('+4h', thu) == (thu + dt.timedelta(hours=4)).timestamp()
assert dt.datetime.fromtimestamp(w.when('9:00', thu)).day == 13, 'a past clock time is tomorrow'
assert w.when('2026-11-16 17:00') == dt.datetime(2026, 11, 16, 17, 0).timestamp()

assert run('pr', 'Sttark/sttark-claude-kit#83', 'merged', '--why', 'x')[0] == 2, '--by is needed'
assert run('pr', 'Sttark/sttark-claude-kit#83', 'merged', '--by', '+1d')[0] == 2, '--why is needed'
assert run('pr', 'Sttark/sttark-claude-kit#83', 'merged', '--by', '+1d', '--why', 'merged one')[0] == 0
assert run('pr', 'Sttark/sttark-claude-kit#1', 'closed', '--by', '+1d', '--why', 'closed one')[0] == 0
assert run('at', '+0m', '--why', 'time one')[0] == 0
code, out = run('email-reply', 'abc', '--by', '+1d', '--what', "Sample Co's reply", '--why', 'reply one')
assert code == 0 and 'handoff line' in out and "Sample Co's reply" in out, out
s = json.load(open(os.path.join(d, 'state.json')))
late = [k for k, v in s['waits'].items() if v['why'] == 'reply one'][0]
s['waits'][late]['by'] = time.time() - 1
json.dump(s, open(os.path.join(d, 'state.json'), 'w'))
assert len(run('--list')[1].strip().splitlines()) == 4
code, out = run('--check')
assert 'was merged' in out, out
assert 'The time you set came' in out, out
assert 'The deadline came' in out, out
for k, v in json.load(open(os.path.join(d, 'state.json')))['waits'].items():
    if v['why'] == 'closed one':
        assert run('--cancel', k)[0] == 0
assert len(run('--list')[1].strip().splitlines()) == 3
print('ok')
