#!/usr/bin/python3
"""Tests that the Sttark working rules reach a session whole (working-rules-hook.py with a part number), on copies:
a temporary Kit folder and log. Claude Code shows a session at most 10,000 characters of one hook's text; past that
it shows only the first 2,000, and every rule after them is lost. build.sh runs this test, so a release whose rules
need more parts than install-hooks.py adds, or a part over SIZE, does not build.
Run: /usr/bin/python3 tools/working-rules-test.py"""
import importlib.util, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, 'Resources/hooks/working-rules-hook.py')
INSTALL = os.path.join(ROOT, 'Resources/hooks/install-hooks.py')
tmp = tempfile.mkdtemp(prefix='kit-rules-')
os.environ.update(STTARK_KIT_DIR=tmp, STTARK_KIT_LOG=os.path.join(tmp, 'log'))
fails = []


def check(what, ok, got=None):
    print(('ok    ' if ok else 'FAIL  ') + what + ('' if ok or got is None else ': %r' % (got,)))
    if not ok:
        fails.append(what)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


w = load(HOOK, 'rules')
pieces = w.parts()
check('the rules fit in the parts install-hooks.py adds (%d of %d)' % (len(pieces), w.PARTS), len(pieces) <= w.PARTS)
check('each part is at most %d characters (%s)' % (w.SIZE, ', '.join(str(len(p)) for p in pieces)),
      all(len(p) <= w.SIZE for p in pieces))
check('install-hooks.py adds one hook entry per part', load(INSTALL, 'install').WORKING_PARTS == w.PARTS)
rules = [l for l in w.RULES.strip('\n').split('\n') if l.startswith('- ')]
lines = [l for p in pieces for l in p.split('\n') if l.startswith('- ')]
check('every rule is in exactly one part, in order (%d rules)' % len(rules), lines == rules)
check('part 1 starts with the lead line', pieces[0].startswith(w.LEAD))
check('a rule for a Kit prompt is in that prompt, not here (wait ended, new messages, own reply, check-in)',
      not any(s in w.RULES for s in ('A wait you handed', 'New messages came in', 'replied themselves', 'Check-in:',
                                     'claude-notify', 'CronCreate')))
waits = [r for r in rules if r.startswith('- Waits on others:')]
check('the waits rule says when and points at claude-wait --help for the forms, which are not here',
      len(waits) == 1 and 'claude-wait --help' in waits[0] and 'channel that the answer comes on' in waits[0]
      and 'safety net' in waits[0] and '--why' in waits[0] and 'handoff line' in waits[0]
      and not any(s in w.RULES for s in ('check-script', 'check-prompt', '--query', '--mailbox', 'email-reply')))
check('each later part says which part it is', all(p.startswith(w.MORE % (i + 2, len(pieces))) for i, p in enumerate(pieces[1:])))


def run(*args, sid='sid-test'):
    r = subprocess.run(['/usr/bin/python3', HOOK] + list(args), input=json.dumps({'session_id': sid}),
                       capture_output=True, text=True, env=os.environ)
    return r.stdout.strip()


out = [run(str(i)) for i in range(1, w.PARTS + 1)]
texts = [json.loads(o)['hookSpecificOutput']['additionalContext'] for o in out if o]
check('the hook prints each part as its own text, and nothing for a part past the rules', texts == pieces
      and all(not o for o in out[len(pieces):]))
check('with no part number it prints part 1 (a settings file from before)', json.loads(run())['hookSpecificOutput']['additionalContext'] == pieces[0])
json.dump({'sid-note': ['Use "begin", not "commence".']}, open(os.path.join(tmp, 'working-notes.json'), 'w'))
last = json.loads(run(str(len(pieces)), sid='sid-note'))['hookSpecificOutput']['additionalContext']
first = json.loads(run('1', sid='sid-note'))['hookSpecificOutput']['additionalContext'] if len(pieces) > 1 else ''
check('the note from the last reply\'s check goes once, after the last part',
      last.endswith('From the check of your last reply: Use "begin", not "commence".') and 'From the check' not in first)
check('and stays under 10,000 characters there', len(last) < 10000, len(last))

print('ok' if not fails else '%d failed' % len(fails))
sys.exit(1 if fails else 0)
