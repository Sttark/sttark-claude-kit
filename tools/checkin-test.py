#!/usr/bin/python3
"""Tests the progress check-ins (Resources/hooks/checkin.py) on copies: a test folder and log (STTARK_KIT_DIR,
STTARK_KIT_LOG), made-up sessions with agents' records, a stand-in for the Haiku call (STTARK_CHECKIN_MODEL) and
notify.py in its dry mode (nothing is sent; no model is called; no session is touched):
- what runs: an agent Claude Code has not marked finished, and active in the last 15 minutes; not a finished one, a
  quiet one, a foreground one or one of an archived session; the session's own turn as the minute check saw it;
- when: none for work under 15 minutes; one at 15 minutes; none in the next 15; the next at 30; one message for all of
  a session's agents; none when the work ends, and the session leaves the file;
- what: the summary reads only what the records gained since the last check-in, with each agent's task; the subject
  names the oldest agent's description; an agent that finished since the last check-in is in the next one; no
  em-dash goes out; with no new steps no model is called; a failed call gives the count of steps;
- how: the person's ways less the Claude app; none checked, or the Claude app alone, is logged once; a session held
  at its usage limit is skipped; the switch off stops them; a check-in is not the session's own message (no
  reach_sent, no "notify" line); STTARK_CHECKIN_DRY sends nothing; wait.py --check runs them.
Run from the repo root: /usr/bin/python3 tools/checkin-test.py"""
import importlib.util, json, os, re, stat, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, 'Resources', 'hooks')
d = tempfile.mkdtemp(prefix='kit-checkin-')
KIT = os.path.join(d, 'kit')
LOG = os.path.join(d, 'log')
os.makedirs(KIT)
fails = 0


def check(what, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what)
    fails += not ok


# --- a stand-in for the Haiku call: keeps what it read, answers with a note that has an em-dash ----------------------
FAKE = os.path.join(d, 'haiku')
open(FAKE, 'w').write('''#!/usr/bin/python3
import os, sys
text = sys.stdin.read()
with open(os.environ['FAKE_DIR'] + '/inputs', 'a') as f:
    f.write(text + '\\n=====\\n')
if os.environ.get('FAKE_FAIL'):
    print('overloaded', file=sys.stderr)
    sys.exit(1)
print('It finished the docs pages \\u2014 and opened pull request 12. Next it checks the links.')
''')
os.chmod(FAKE, os.stat(FAKE).st_mode | stat.S_IEXEC)
os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_CHECKIN_MODEL=FAKE, FAKE_DIR=d)
for k in ('STTARK_CHECKIN_DRY', 'STTARK_WAIT_DRY', 'STTARK_NOTIFY_DRY'):
    os.environ.pop(k, None)


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HOOKS, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


c = load('checkin')
HELD = set()   # Claude Code ids of the sessions held at their usage limit
SENT = []      # (subject, body, ways, title, url, cse) of each message notify.py was asked to send


class Limit(object):
    @staticmethod
    def held(sid=None, transcript=None, cse=None):
        return sid in HELD


def fake_load(name):
    m = load(name)
    if name == 'notify':
        m.DRY = True   # notify.py itself sends nothing; the check-ins log as if it had
        real = m.send

        def send(subject, body, link='', ways=None, title=None, url=None, cse='', quiet=False):
            SENT.append((subject, body, ways, title, url, cse, quiet))
            return real(subject, body, link, ways, title, url, cse, quiet)
        m.send = send
    if name == 'effort-hook':
        m.open_tasks = lambda: {}   # no lsof: no agent here waits on a background task
    if name == 'limit-hook':
        return Limit
    return m


c.load = fake_load


def inputs():
    try:
        return [x for x in open(os.path.join(d, 'inputs')).read().split('\n=====\n') if x.strip()]
    except OSError:
        return []


def log_lines(tag='checkin '):
    try:
        return [l[20:] for l in open(LOG).read().splitlines() if l[20:].startswith(tag)]
    except OSError:
        return []


# --- made-up records -----------------------------------------------------------------------------------------------
S = time.time() - 4 * 3600   # "now" at the start, 4 hours ago: a file's birth time can be set back, never ahead
n = [0]


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(t))


def use(desc, at, err=False, name='Bash'):
    n[0] += 1
    i = 'toolu_%04d' % n[0]
    return [{'type': 'assistant', 'timestamp': iso(at), 'isSidechain': True, 'message': {'content': [
                {'type': 'tool_use', 'id': i, 'name': name, 'input': {'command': 'x', 'description': desc}}]}},
            {'type': 'user', 'timestamp': iso(at), 'isSidechain': True, 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': i, 'is_error': err, 'content': 'exit 1: it broke' if err else 'ok'}]}}]


def say(text, at):
    return [{'type': 'assistant', 'timestamp': iso(at), 'message': {'content': [{'type': 'text', 'text': text}]}}]


def write(path, lines, mode='a'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(''.join(json.dumps(x) + '\n' for x in lines))


def times(path, born, changed):
    """macOS moves a file's birth time back when its change time is set before it: the agent started at `born`."""
    os.utime(path, (born, born))
    os.utime(path, (changed, changed))


PROJ = os.path.join(d, 'projects')


def agent(tp, aid, desc, task, born, changed, lines=(), finished=False, shape='background'):
    sub = os.path.join(tp[:-len('.jsonl')], 'subagents')
    path = os.path.join(sub, 'agent-%s.jsonl' % aid)
    write(path, [{'type': 'user', 'timestamp': iso(born), 'isSidechain': True, 'parentUuid': None, 'agentId': aid,
                  'message': {'role': 'user', 'content': task}}] + list(lines), 'w')
    meta = {'agentType': 'general-purpose', 'description': desc, 'toolUseId': 'toolu_' + aid, 'spawnDepth': 1,
            'requestShape': shape}
    if finished:
        meta['finished'] = True
    json.dump(meta, open(path[:-len('.jsonl')] + '.meta.json', 'w'))
    times(path, born, changed)
    return path


def finish(path):
    m = json.load(open(path[:-len('.jsonl')] + '.meta.json'))
    m['finished'] = True
    json.dump(m, open(path[:-len('.jsonl')] + '.meta.json', 'w'))


def session(name):
    tp = os.path.join(PROJ, '%s.jsonl' % name)
    write(tp, [{'type': 'user', 'timestamp': iso(S - 3600), 'message': {'role': 'user', 'content': 'Start ' + name}}], 'w')
    return tp


A, B, Q, F, E, H, R = (session(x) for x in ('docs', 'quick', 'quiet', 'front', 'turn', 'held', 'archived'))
CSE = {A: 'cse_01DocsSite000001', B: 'cse_01QuickFix000002', Q: 'cse_01QuietOne000003', F: 'cse_01Foreground0004',
       E: 'cse_01LongTurn000005', H: 'cse_01HeldOne0000006', R: 'cse_01Archived000007'}
NAMES = {A: 'Docs site', B: 'Quick fix', Q: 'Quiet one', F: 'Foreground', E: 'Long turn', H: 'Held one', R: 'Old work'}
X = agent(A, 'ax1', 'Build the docs pages', 'Build the docs pages for the new app. OLDTASK', S - 10 * 60, S - 30,
          use('OLDSTEP one', S - 9 * 60) + use('OLDSTEP two', S - 8 * 60, err=True))
agent(B, 'bx1', 'Find a file', 'Find the file.', S - 5 * 60, S - 60, use('a search', S - 4 * 60), finished=True)
agent(Q, 'qx1', 'Wait on nothing', 'Do it.', S - 40 * 60, S - 20 * 60, use('a step long ago', S - 30 * 60))
agent(F, 'fx1', 'Part of the turn', 'Do it.', S - 30 * 60, S - 10, use('a step', S - 20), shape='foreground')
agent(H, 'hx1', 'Held agent', 'Do it.', S - 30 * 60, S - 10, use('a held step', S - 20))
agent(R, 'rx1', 'Archived agent', 'Do it.', S - 30 * 60, S - 10, use('a step', S - 20))
write(E, use('TURNSTEP one', S - 10 * 60) + say('The build passes. TURNSAID', S - 9 * 60))


def state(now, ways=('email',), on=None, turn=False):
    s = {'sessions': {}, 'reach': {'ways': list(ways), 'email': 'name@sttark.com'}}
    for tp, cse in CSE.items():
        x = {'transcript': tp, 'title': NAMES[tp], 'url': 'https://claude.ai/code/session_' + cse[4:], 'at': now - 120,
             'app': {'checked': now - 20, 'working': False, 'archived': tp == R}}
        if tp == E:
            x['turn_at'] = S - 11 * 60
            x['app']['working'] = turn
        s['sessions'][cse] = x
    if on is not None:
        s['checkins'] = on
    json.dump(s, open(os.path.join(KIT, 'state.json'), 'w'))


def runs():
    return (c.read_json(c.FILE).get('sessions') or {})


HELD.add('held')
check('a file\'s birth time can be set back (the agent\'s start)', abs(os.stat(X).st_birthtime - (S - 600)) < 2)

# --- under 15 minutes: nothing --------------------------------------------------------------------------------------
state(S, turn=True)
c.check(now=S)
check('no check-in for work under 15 minutes, and no model call', not SENT and not inputs())
check('the long agent and the long turn start runs; a finished, quiet, foreground or archived agent does not',
      set(runs()) == {CSE[A], CSE[E], CSE[H]})
eh = load('effort-hook')
check('a foreground agent counts only while its turn runs (it is the turn\'s work)',
      [x['what'] for x in eh.running_agents(F, set(), S)] == [] and
      [x['what'] for x in eh.running_agents(F, set(), S, foreground=True)] == ['Part of the turn'])

# --- at 15 minutes: one check-in each ---------------------------------------------------------------------------------
T1 = S + 6 * 60
os.utime(X, (T1 - 20, T1 - 20))
state(T1, turn=True)
c.check(now=T1)
sent = {m[5]: m for m in SENT}
check('one check-in for the agent at 16 minutes and one for the turn', set(sent) == {CSE[A], CSE[E]})
a = sent.get(CSE[A]) or ('',) * 7
check('the subject names the session, the agent and how long it works: %r' % a[0], a[0] == 'Docs site: Build the docs pages, working 16 min')
check('the note has no em-dash: %r' % a[1], '—' not in a[1] and a[1].startswith('It finished the docs pages, and opened'))
check('it goes the ways picked, with the session\'s name and link, as a Kit message (quiet)',
      a[2] == ['email'] and a[3] == 'Docs site' and a[4].endswith('session_01DocsSite000001') and a[6] is True)
first = [x for x in inputs() if 'Build the docs pages' in x]
check('the summary reads the agent\'s task and its steps since it started, with the failed one',
      len(first) == 1 and 'OLDTASK' in first[0] and 'OLDSTEP one' in first[0] and 'OLDSTEP two (it failed: exit 1: it broke)' in first[0]
      and '2 steps, 1 failed' in first[0])
e = sent.get(CSE[E]) or ('',) * 7
check('a long turn with no agent: "Long turn: Working 17 min"', e[0] == 'Long turn: Working 17 min')
check('its summary reads the session\'s own steps and words', any('TURNSTEP one' in x and 'TURNSAID' in x and 'The session itself' in x for x in inputs()))
lines = log_lines()
check('a log line for each: the ways, the subject and the note',
      any(l.startswith('checkin cse_01DocsSite000001 "Docs site" sent by Email | Build the docs pages, working 16 min | It finished') for l in lines))
check('the held session is skipped, once', sum('skipped: it holds at the usage limit' in l for l in lines) == 1 and CSE[H] not in sent)
check('a check-in is not the session\'s own message: no reach_sent, no notify line',
      'reach_sent' not in c.read_json(c.STATE) and not log_lines('notify '))

# --- the next minutes: nothing new -------------------------------------------------------------------------------------
n_sent, n_in = len(SENT), len(inputs())
T2 = T1 + 60
os.utime(X, (T2 - 20, T2 - 20))
state(T2, turn=True)
c.check(now=T2)
check('none in the next 15 minutes', len(SENT) == n_sent and len(inputs()) == n_in)
check('the held one is not logged again', sum('skipped: it holds' in l for l in log_lines()) == 1)

# --- 15 minutes later: new steps, a second agent ---------------------------------------------------------------------
T3 = T1 + 15 * 60 + 10
write(X, use('NEWSTEP one', T1 + 5 * 60) + use('NEWSTEP two', T1 + 6 * 60))
Y = agent(A, 'ay2', 'Check the links', 'Check every link. YTASK', T1 + 2 * 60, T3 - 30, use('YSTEP one', T1 + 3 * 60))
os.utime(X, (T3 - 20, T3 - 20))
write(E, use('TURNSTEP two', T1 + 4 * 60))
state(T3, turn=True)
c.check(now=T3)
second = [m for m in SENT[n_sent:] if m[5] == CSE[A]]
check('the second check-in at 31 minutes, for both agents: %r' % (second[0][0] if second else None),
      len(second) == 1 and second[0][0] == 'Docs site: Build the docs pages and 1 more agent, working 31 min')
latest = [x for x in inputs()[n_in:] if 'Build the docs pages' in x]
check('it reads only what the records gained since the last one, and the new agent from its start',
      len(latest) == 1 and 'NEWSTEP one' in latest[0] and 'NEWSTEP two' in latest[0] and 'OLDSTEP' not in latest[0]
      and 'YTASK' in latest[0] and 'YSTEP one' in latest[0] and 'the last 15 min' in latest[0])
check('the turn\'s second one reads only its new step',
      any('TURNSTEP two' in x and 'TURNSTEP one' not in x for x in inputs()[n_in:]))

# --- an agent finishes: the next check-in says what it did; then the work ends: no message --------------------------
T4 = T3 + 15 * 60
finish(X)
write(X, say('All pages build. XDONE', T3 + 2 * 60))
os.utime(X, (T3 + 2 * 60, T3 + 2 * 60))
write(Y, use('YSTEP two', T3 + 3 * 60))
os.utime(Y, (T4 - 30, T4 - 30))
n_sent, n_in = len(SENT), len(inputs())
state(T4)
c.check(now=T4)
third = [m for m in SENT[n_sent:] if m[5] == CSE[A]]
check('the third: the running agent names it, and the one that finished is in the note',
      len(third) == 1 and third[0][0] == 'Docs site: Check the links, working 28 min'
      and any('XDONE' in x and 'finished since the last note' in x and 'YSTEP two' in x for x in inputs()[n_in:]))
check('the turn that ended gets no message, and its session leaves the file', CSE[E] not in runs()
      and not [m for m in SENT[n_sent:] if m[5] == CSE[E]])
finish(Y)
n_sent = len(SENT)
state(T4 + 60)
c.check(now=T4 + 60)
check('no message when the work ends; the session leaves the file', len(SENT) == n_sent and CSE[A] not in runs())
check('the end is logged with how many went',
      any(l.startswith('checkin cse_01DocsSite000001 "Docs site" work ended after 47 min; 3 check-ins sent') for l in log_lines()))

# --- the ways ----------------------------------------------------------------------------------------------------------
def fresh_agent(tp, aid, now):
    return agent(tp, aid, 'Long job ' + aid, 'Do the long job.', now - 20 * 60, now - 10, use('step of ' + aid, now - 60))


T5 = T4 + 3600
fresh_agent(B, 'b2', T5)
state(T5, ways=('push',))
n_sent = len(SENT)
c.check(now=T5)
state(T5 + 60, ways=('push',))
c.check(now=T5 + 60)
check('the Claude app alone: nothing goes, no model call, and it is logged once',
      len(SENT) == n_sent and sum('only the Claude app' in l for l in log_lines()) == 1)
state(T5 + 120, ways=())
c.check(now=T5 + 120)
check('no way checked: logged once', sum('no way is checked under Reach me by' in l for l in log_lines()) == 1 and len(SENT) == n_sent)
state(T5 + 180, ways=('email', 'push', 'chat'))
c.check(now=T5 + 180)
check('the ways picked less the Claude app', SENT[-1][2] == ['email', 'chat'] and SENT[-1][5] == CSE[B])
check('a way that cannot go is in the log line', any('sent by Email; not by Google Chat (needs a Google Chat webhook' in l for l in log_lines()))

# --- no new steps: no model call; a failed call: the count of steps ------------------------------------------------------
T6 = T5 + 180 + 15 * 60
os.utime(os.path.join(B[:-6], 'subagents', 'agent-b2.jsonl'), (T6 - 60, T6 - 60))
n_in = len(inputs())
state(T6)
c.check(now=T6)
check('no new steps: no model call, and the note says so: %r' % SENT[-1][1],
      len(inputs()) == n_in and SENT[-1][1] == 'It made no new steps in the last 15 min. Its last step: ran: step of b2.')
T7 = T6 + 15 * 60
write(os.path.join(B[:-6], 'subagents', 'agent-b2.jsonl'), use('more', T7 - 300) + use('again', T7 - 200, err=True))
os.utime(os.path.join(B[:-6], 'subagents', 'agent-b2.jsonl'), (T7 - 60, T7 - 60))
os.environ['FAKE_FAIL'] = '1'
state(T7)
c.check(now=T7)
os.environ.pop('FAKE_FAIL')
check('a failed call: the count of steps instead: %r' % SENT[-1][1], SENT[-1][1] == 'It made 2 steps in the last 15 min, and 1 of them failed.')
check('and the log says why', any('no summary (exit 1: overloaded)' in l for l in log_lines()))

# --- the switch off ----------------------------------------------------------------------------------------------------
T8 = T7 + 15 * 60
n_sent = len(SENT)
state(T8, on=False)
c.check(now=T8)
check('the switch off: none, and the file is cleared', len(SENT) == n_sent and runs() == {})
os.utime(os.path.join(B[:-6], 'subagents', 'agent-b2.jsonl'), (T8 + 30, T8 + 30))
state(T8 + 60, on=True)
c.check(now=T8 + 60)
check('on again: the work is due at once (it runs 2 hours)', len(SENT) == n_sent + 1)

# --- notify.py's quiet send: no reach_sent, no notify line ---------------------------------------------------------------
nm = load('notify')
nm.DRY = True
res = nm.send('Subject', 'Body', ways=['email'], title='Docs site', url='https://claude.ai/code/session_01x', cse='cse_01x', quiet=True)
check('notify.send(quiet=True) answers each way and writes nothing', res and res[0][0] == 'email' and res[0][1][0]
      and 'reach_sent' not in c.read_json(c.STATE) and not log_lines('notify '))
seen = {}
nm.seal = lambda obj: seen.update(obj) or 'sealed'
nm.send('Docs site: Build the docs pages, working 16 min', 'Body', ways=['email'], title='Docs site', url='', cse='cse_01x', quiet=True)
once = seen.get('subject')
nm.send('The supplier replied', 'Body', ways=['email'], title='Docs site', url='', cse='cse_01x', quiet=True)
check('the email\'s subject names the session once: %r, %r' % (once, seen.get('subject')),
      once == 'Docs site: Build the docs pages, working 16 min' and seen.get('subject') == 'Docs site: The supplier replied')

# --- STTARK_CHECKIN_DRY, and wait.py --check runs the check-ins --------------------------------------------------------
fresh_agent(Q, 'q2', time.time())
state(time.time())
USAGE = os.path.join(d, 'usage.json')   # a stand-in for the usage read, and for the Keychain: nothing of this Mac's
json.dump({'extra_usage': {'is_enabled': False}, 'limits': []}, open(USAGE, 'w'))
json.dump({}, open(os.path.join(d, 'keys.json'), 'w'))
r = subprocess.run([sys.executable, os.path.join(HOOKS, 'wait.py'), '--check'], capture_output=True, text=True,
                   env=dict(os.environ, STTARK_WAIT_DRY='1', STTARK_LIMIT_TEST=USAGE,
                            STTARK_MAIL_KEYS=os.path.join(d, 'keys.json')), timeout=120)
check('wait.py --check runs them; a dry run writes the note and sends nothing: %r' % r.stdout[-200:],
      'would send for cse_01QuietOne000003 "Quiet one": Long job q2, working 20 min' in r.stdout
      and any('"Quiet one" would send (dry) | Long job q2, working 20 min | It finished' in l for l in log_lines()))
fresh_agent(Q, 'q3', time.time())
os.remove(c.FILE)
env = dict(os.environ, STTARK_WAIT_DRY='1', STTARK_LIMIT_TEST=USAGE, STTARK_MAIL_KEYS=os.path.join(d, 'keys.json'))
env.pop('STTARK_CHECKIN_MODEL')
n_in = len(inputs())
r = subprocess.run([sys.executable, os.path.join(HOOKS, 'wait.py'), '--check'], capture_output=True, text=True, env=env, timeout=120)
check('another part\'s test run (STTARK_WAIT_DRY) makes no model call: the note is the step count: %r' % r.stdout[-160:],
      len(inputs()) == n_in and re.search(r'It made \d+ steps? since it started\.', r.stdout)
      and any('no summary (a test run of another part: no model call)' in l for l in log_lines()))
r = subprocess.run([sys.executable, os.path.join(HOOKS, 'checkin.py'), '--list'], capture_output=True, text=True, timeout=60)
check('--list says what runs and when the next one is due: %r' % r.stdout[:200],
      'Progress check-ins are on.' in r.stdout and 'agent "Long job q2"' in r.stdout)

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
