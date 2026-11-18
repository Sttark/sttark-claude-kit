#!/usr/bin/python3
"""Tests the progress check-ins (Resources/hooks/checkin.py) on copies: a test folder and log (STTARK_KIT_DIR,
STTARK_KIT_LOG), made-up sessions with agents' records and a stand-in for the Haiku call (STTARK_CHECKIN_MODEL); no
model is called and no session is touched:
- what runs: an agent Claude Code has not marked finished, and active in the last 15 minutes; not a finished one, a
  quiet one, a foreground one or one of an archived session; the session's own turn as the minute check saw it;
- when: none for work under 15 minutes; one at 15 minutes; none in the next 15; the next at 30; one message for all of
  a session's agents; none when the work ends, which a minute with no work does not do (a run ends after 5 minutes);
  agents that follow each other make one run; a prompt of the person starts the 15 minutes again; an agent that is
  continued counts from then; the short turn after the agents brings none;
- what: the summary reads only what the records gained since the last check-in, with each agent's task; the subject
  names the session and the oldest agent's description; an agent that stopped since the last check-in is in the next
  one, also one that started and stopped between two; no
  em-dash goes out; with no new steps no model is called; a failed call gives the count of steps;
- where: the latest note of a run is kept in checkins.json (note, note_at) for the Kit app, and dropped when the run
  ends; nothing goes out any way (notify.py is never loaded, no "notify" line, no reach_sent, no Mac notice), also
  with no Reach me by way checked; a session held at its usage limit is skipped; the switch off stops them; a test
  folder or a dry run writes the note and saves nothing; wait.py --check runs them.
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
c.DRY = c.NO_MODEL = False   # a test folder makes it dry; here the file and log are real
HELD = set()   # Claude Code ids of the sessions held at their usage limit
SENT = []      # ("<name>: <subject>", note, None, name, url, cse) of each check-in written
LOADED = set()  # the Kit's modules checkin.py loaded


class Limit(object):
    @staticmethod
    def held(sid=None, transcript=None, cse=None):
        return sid in HELD


def fake_load(name):
    LOADED.add(name)
    m = load(name)
    if name == 'effort-hook':
        m.open_tasks = lambda: {}   # no lsof: no agent here waits on a background task
    if name == 'limit-hook':
        return Limit
    return m


c.load = fake_load
real_write = c.write


def write_and_keep(cc, cse, x, title, work, now):
    n_before = cc.get('n', 0)
    real_write(cc, cse, x, title, work, now)
    if cc.get('n', 0) > n_before:
        SENT.append(('%s: %s' % (title, cc['subject']), cc['note'], None, title, x.get('url'), cse))


c.write = write_and_keep


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


def state(now, ways=('email',), on=None, turn=False, more=None):
    """The state file at `now`: E's turn runs with `turn`; `more` gives other sessions' own fields (a turn, a prompt)."""
    s = {'sessions': {}, 'reach': {'ways': list(ways), 'email': 'name@sttark.com'}}
    for tp, cse in CSE.items():
        x = {'transcript': tp, 'title': NAMES[tp], 'url': 'https://claude.ai/code/session_' + cse[4:], 'at': now - 120,
             'app': {'checked': now - 20, 'working': False, 'archived': tp == R}}
        if tp == E:
            x['turn_at'] = S - 11 * 60
            x['app']['working'] = turn
        for k, v in ((more or {}).get(tp) or {}).items():
            if k == 'working':
                x['app']['working'] = v
            else:
                x[k] = v
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
check('it is kept for the Kit app: the note and when it was written, in checkins.json',
      runs()[CSE[A]].get('note') == a[1] and runs()[CSE[A]].get('note_at') == T1
      and runs()[CSE[A]].get('subject') == 'Build the docs pages, working 16 min')
first = [x for x in inputs() if 'Build the docs pages' in x]
check('the summary reads the agent\'s task and its steps since it started, with the failed one',
      len(first) == 1 and 'OLDTASK' in first[0] and 'OLDSTEP one' in first[0] and 'OLDSTEP two (it failed: exit 1: it broke)' in first[0]
      and '2 steps, 1 failed' in first[0])
e = sent.get(CSE[E]) or ('',) * 7
check('a long turn with no agent: "Long turn: Working 17 min"', e[0] == 'Long turn: Working 17 min')
check('its summary reads the session\'s own steps and words', any('TURNSTEP one' in x and 'TURNSAID' in x and 'The session itself' in x for x in inputs()))
lines = log_lines()
check('a log line for each (a row on the Events page): the subject and the note',
      any(l.startswith('checkin cse_01DocsSite000001 "Docs site" shown in the Kit | Build the docs pages, working 16 min | It finished') for l in lines))
check('the held session is skipped, once', sum('skipped: it holds at the usage limit' in l for l in lines) == 1 and CSE[H] not in sent)
check('nothing goes out: notify.py is not loaded, no notify line, no reach_sent, no Mac notice queued',
      'notify' not in LOADED and 'reach_sent' not in c.read_json(c.STATE) and not log_lines('notify ')
      and not os.path.exists(os.path.join(KIT, 'notify-queue')))

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
      and 'YTASK' in latest[0] and 'YSTEP one' in latest[0] and 'since the last note' in latest[0])
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
check('the third: the running agent names it, with the run\'s age, and the one that stopped is in the note',
      len(third) == 1 and third[0][0] == 'Docs site: Check the links, working 46 min'
      and any('XDONE' in x and 'stopped since the last note' in x and 'YSTEP two' in x for x in inputs()[n_in:]))
check('the turn that ended gets no message; its run waits 5 minutes before it ends', runs()[CSE[E]].get('idle') == T4
      and not [m for m in SENT[n_sent:] if m[5] == CSE[E]])
finish(Y)
n_sent = len(SENT)
state(T4 + 60)
c.check(now=T4 + 60)
check('no message when the work ends, and the run is not over after one minute',
      len(SENT) == n_sent and runs()[CSE[A]].get('start') and not any('"Docs site" work ended' in l for l in log_lines()))
state(T4 + 60 + c.GAP)
c.check(now=T4 + 60 + c.GAP)
check('5 minutes with no work end the run, with no note; its last note goes (the Kit app shows it no more); the end is logged',
      len(SENT) == n_sent and not runs()[CSE[A]].get('start') and runs()[CSE[A]].get('sent') == T4
      and 'note' not in runs()[CSE[A]] and 'note_at' not in runs()[CSE[A]]
      and any(l.startswith('checkin cse_01DocsSite000001 "Docs site" work ended after 46 min; 3 check-ins') for l in log_lines())
      and any(l.startswith('checkin cse_01LongTurn000005 "Long turn" work ended after 32 min; 2 check-ins') for l in log_lines()))

# --- Reach me by has no say ---------------------------------------------------------------------------------------------
def fresh_agent(tp, aid, now):
    return agent(tp, aid, 'Long job ' + aid, 'Do the long job.', now - 20 * 60, now - 10, use('step of ' + aid, now - 60))


T5 = T4 + 3600
fresh_agent(B, 'b2', T5)
state(T5 - 16 * 60)
c.check(now=T5 - 16 * 60)
check('work first seen counts from then, at most 2 minutes back', runs()[CSE[B]]['start'] == T5 - 18 * 60)
state(T5 + 180, ways=())
n_sent = len(SENT)
c.check(now=T5 + 180)
check('no Reach me by way checked: the note is written all the same, and nothing goes out',
      len(SENT) == n_sent + 1 and SENT[-1][5] == CSE[B] and runs()[CSE[B]].get('note') == SENT[-1][1]
      and 'notify' not in LOADED and not log_lines('notify '))

# --- no new steps: no model call; a failed call: the count of steps ------------------------------------------------------
T6 = T5 + 180 + 15 * 60
os.utime(os.path.join(B[:-6], 'subagents', 'agent-b2.jsonl'), (T6 - 60, T6 - 60))
n_in = len(inputs())
state(T6)
c.check(now=T6)
check('no new steps: no model call, and the note says so: %r' % SENT[-1][1],
      len(inputs()) == n_in and SENT[-1][1] == 'It made no new steps since the last note. Its last step: ran: step of b2.')
T6b = T6 + 15 * 60
os.utime(os.path.join(B[:-6], 'subagents', 'agent-b2.jsonl'), (T6b - 60, T6b - 60))
n_sent = len(SENT)
state(T6b)
c.check(now=T6b)
check('no new steps again: no second note saying the same, logged once',
      len(SENT) == n_sent and sum('skipped: no new steps' in l for l in log_lines()) == 1)
T7 = T6b + 15 * 60
write(os.path.join(B[:-6], 'subagents', 'agent-b2.jsonl'), use('more', T7 - 300) + use('again', T7 - 200, err=True))
os.utime(os.path.join(B[:-6], 'subagents', 'agent-b2.jsonl'), (T7 - 60, T7 - 60))
os.environ['FAKE_FAIL'] = '1'
state(T7)
c.check(now=T7)
os.environ.pop('FAKE_FAIL')
check('a failed call: the count of steps instead: %r' % SENT[-1][1], SENT[-1][1] == 'It made 2 steps since the last note, and 1 of them failed.')
check('and the log says why', any('no summary (exit 1: overloaded)' in l for l in log_lines()))

# --- the switch off ----------------------------------------------------------------------------------------------------
T8 = T7 + 15 * 60
n_sent = len(SENT)
state(T8, on=False)
c.check(now=T8)
check('the switch off: none, and the records stay', len(SENT) == n_sent and runs().get(CSE[B], {}).get('sent') == T7)
os.utime(os.path.join(B[:-6], 'subagents', 'agent-b2.jsonl'), (T8 + 30, T8 + 30))
state(T8 + 60, on=True)
c.check(now=T8 + 60)
check('on again: the work is due at once (it runs 2 hours)', len(SENT) == n_sent + 1)

# --- runs: a missed minute, agents that follow each other, a prompt, an agent continued, the turn after the agents -----
U = T8 + 600
K, L, M, N, P = (session(x) for x in ('build', 'chain', 'again', 'between', 'report'))
CSE.update({K: 'cse_01LongBuild000008', L: 'cse_01Chained00000009', M: 'cse_01Continued000010', N: 'cse_01Between0000011',
            P: 'cse_01Report00000012'})
NAMES.update({K: 'Long build', L: 'Chained', M: 'Continued', N: 'Between', P: 'Report'})
write(K, use('KSTEP', U - 10 * 60))
L1 = agent(L, 'l1', 'Read the old pages', 'Read them.', U - 10 * 60, U - 30, use('LSTEP one', U - 9 * 60))
L2 = agent(L, 'l2', 'Draw the new pages', 'Draw them.', U - 2 * 60, U - 30, use('LSTEP two', U - 60))
M1 = agent(M, 'm1', 'Fix the form', 'Fix the form.', U - 2 * 3600, U - 30,
           use('OLDM', U - 2 * 3600 + 60) + use('NEWM', U - 60))
N1 = agent(N, 'n1', 'Write the guide', 'Write it.', U - 14 * 60, U - 30, use('NSTEP one', U - 13 * 60))
C = c.read_json(c.FILE)   # the records the minute check left a minute ago: K, L and N run; M's run ended an hour
C['sessions'][CSE[K]] = {'start': U - 16 * 60, 'seen': U - 60}   # ago; for P, agents ran 30 minutes and a note went at 20
C['sessions'][CSE[L]] = {'start': U - 10 * 60, 'seen': U - 60}
C['sessions'][CSE[N]] = {'start': U - 14 * 60, 'seen': U - 60}
C['sessions'][CSE[M]] = {'sent': U - 3600}
C['sessions'][CSE[P]] = {'start': U - 30 * 60, 'seen': U - 60, 'sent': U - 20 * 60, 'n': 1, 'files': {}}
c.save(C)
O = session('old')   # an agent continued two days after its birth, in a session the check has no record of
CSE[O], NAMES[O] = 'cse_01OldAgent0000013', 'Old agent'
O1 = agent(O, 'o1', 'Old task', 'Do it.', U - 48 * 3600, U - 30, use('OLD STEP', U - 48 * 3600 + 60) + use('NEW STEP', U - 60))


def at(now, k_turn=True, k_asked=U - 16 * 60, p_turn=True, live=()):
    for f in live:
        os.utime(f, (now - 20, now - 20))
    state(now, more={K: {'working': k_turn, 'turn_at': k_asked, 'asked_at': k_asked},
                     P: {'working': p_turn, 'turn_at': U - 60}})
    before = len(SENT)
    c.check(now=now)
    return {m[5]: m for m in SENT[before:]}


got = at(U, live=(L1, L2, M1, N1, O1))
check('a long turn: a note at 16 minutes after the prompt', list(got) == [CSE[K]] and got[CSE[K]][0] == 'Long build: Working 16 min')
check('an agent continued after its run ended counts from now, not from its start 2 hours ago',
      CSE[M] not in got and runs()[CSE[M]]['start'] == U - 120)
check('the short turn after the agents (quiet for 20 minutes) brings no note', CSE[P] not in got)
check('an old agent first seen counts from now, not from its birth two days ago', CSE[O] not in got
      and runs()[CSE[O]]['start'] == U - 120)
got = at(U + 60, k_turn=False, live=(L1, L2, M1, N1))
check('a minute in which the turn does not show ends nothing', not got.get(CSE[K]) and runs()[CSE[K]].get('start') == U - 16 * 60
      and runs()[CSE[K]].get('idle') == U + 60)
check('the guide agent at 15 minutes', list(got) == [CSE[N]] and got[CSE[N]][0] == 'Between: Write the guide, working 15 min')
got = at(U + 120, live=(L1, L2, M1, N1), p_turn=False)
check('the turn shows again: the same run, no second note', CSE[K] not in got and runs()[CSE[K]].get('start') == U - 16 * 60
      and not runs()[CSE[K]].get('idle'))
finish(L1)
os.utime(L1, (U + 120, U + 120))
N2 = agent(N, 'n2', 'Check one link', 'Check it.', U + 180, U + 480, use('N2STEP', U + 240), finished=True)
L3 = agent(L, 'l3', 'Check the new pages', 'Check them.', U + 480, U + 570, use('LSTEP three', U + 500))
got = at(U + 600, k_asked=U + 600, live=(L2, L3, M1, N1))
check('agents that follow each other, none 15 minutes old, make one run: a note at 20 minutes: %r'
      % (got.get(CSE[L], ('',))[0],), got.get(CSE[L], ('',))[0] == 'Chained: Draw the new pages and 1 more agent, working 20 min'
      and any('LSTEP one' in x and 'stopped since the last note' in x and 'LSTEP three' in x for x in inputs()))
got = at(U + 930, k_asked=U + 600, live=(L2, L3, M1, N1))
check('a prompt of the person starts the 15 minutes again', CSE[K] not in got)
m = got.get(CSE[M], ('',) * 7)
check('the continued agent at 17 minutes of its new run, with only its new steps: %r' % m[0],
      re.match(r'Continued: Fix the form, working 1[78] min$', m[0])
      and any('NEWM' in x and 'OLDM' not in x for x in inputs() if 'Fix the form' in x))
got = at(U + 960, k_asked=U + 600, live=(L2, L3, M1, N1))
check('an agent that started and stopped between two notes is in the next one',
      CSE[N] in got and any('N2STEP' in x and 'Check one link' in x for x in inputs() if 'Write the guide' in x))
n_in = len(inputs())
write(L2, use('LSTEP last', U + 990))
os.utime(L2, (U + 1000, U + 1000))
finish(L2)
write(L3, use('LSTEP four', U + 1900))
got = at(U + 1920, k_asked=U + 600, live=(L3, M1, N1))
x = [i for i in inputs()[n_in:] if 'Check the new pages' in i]
check('an agent that stopped since the last note: its last steps, once', CSE[L] in got and x and 'LSTEP four' in x[0]
      and 'Draw the new pages' in x[0] and 'LSTEP last' in x[0] and 'LSTEP two' not in x[0])
n_in = len(inputs())
write(L3, use('LSTEP five', U + 2800))
got = at(U + 2820, k_asked=U + 600, live=(L3, M1, N1))
x = [i for i in inputs()[n_in:] if 'Check the new pages' in i]
check('and not again in the next note', CSE[L] in got and x and 'LSTEP five' in x[0] and 'LSTEP last' not in x[0])
V = U + 2820 + 40 * 60   # the Mac slept 40 minutes; the turn that runs now started a minute ago, with no prompt
state(V, more={K: {'working': True, 'turn_at': V - 60, 'asked_at': U + 600}})
before = len(SENT)
c.check(now=V)
check('a run the check did not see for 40 minutes ended; the work now is a new run, with no note at once',
      len(SENT) == before and runs()[CSE[K]]['start'] == V - 60
      and any('"Long build" work ended after' in l for l in log_lines()))

# --- reading a record: from its place, back from the end at a whole line, another file at the same name -------------
REC = os.path.join(d, 'record.jsonl')
one, two = {'type': 'user', 'timestamp': iso(S), 'k': 1}, {'type': 'user', 'timestamp': iso(S + 60), 'k': 2}
write(REC, [one, two], 'w')
got, place = c.new_entries(REC, None, 0)
check('a record read whole, its place at its end', [x['k'] for x in got] == [1, 2] and place[0] == os.path.getsize(REC))
got, _ = c.new_entries(REC, None, 0, tail=os.path.getsize(REC) - len(json.dumps(one)) - 1)
check('a read back from the end that starts at a line keeps that line', [x['k'] for x in got] == [2])
got, _ = c.new_entries(REC, None, 0, tail=os.path.getsize(REC) - len(json.dumps(one)))
check('one that starts inside a line drops the part', [x['k'] for x in got] == [2])
write(REC, [{'type': 'user', 'timestamp': iso(S + 120), 'k': 3}])
open(REC + '.part', 'w').write('{"type": "user", "timestamp": "%s", "k": 4}' % iso(S + 130))
with open(REC, 'a') as f:
    f.write(open(REC + '.part').read())
got, place2 = c.new_entries(REC, place, 0)
check('from its place: only the new whole lines; a line still being written waits', [x['k'] for x in got] == [3])
os.rename(REC, REC + '.old')
write(REC, [one, two, {'type': 'user', 'timestamp': iso(S + 200), 'k': 5}, {'type': 'user', 'timestamp': iso(S + 210), 'k': 6}], 'w')
got, _ = c.new_entries(REC, place2, S + 200)
check('another file at the same name (a bigger one too) is read again from the time asked', [x['k'] for x in got] == [5, 6])

check('in all of it, nothing went out: notify.py was never loaded, and no notify line or Mac notice',
      'notify' not in LOADED and not log_lines('notify ') and not os.path.exists(os.path.join(KIT, 'notify-queue')))

# --- STTARK_CHECKIN_DRY, and wait.py --check runs the check-ins --------------------------------------------------------
fresh_agent(Q, 'q2', time.time())
state(time.time())
C = c.read_json(c.FILE)
C['sessions'][CSE[Q]] = {'start': time.time() - 20 * 60, 'seen': time.time() - 60}
c.save(C)
USAGE = os.path.join(d, 'usage.json')   # a stand-in for the usage read, and for the Keychain: nothing of this Mac's
json.dump({'extra_usage': {'is_enabled': False}, 'limits': []}, open(USAGE, 'w'))
json.dump({}, open(os.path.join(d, 'keys.json'), 'w'))
r = subprocess.run([sys.executable, os.path.join(HOOKS, 'wait.py'), '--check'], capture_output=True, text=True,
                   env=dict(os.environ, STTARK_WAIT_DRY='1', STTARK_LIMIT_TEST=USAGE,
                            STTARK_MAIL_KEYS=os.path.join(d, 'keys.json')), timeout=120)
check('wait.py --check runs them; a dry run writes the note and keeps nothing: %r' % r.stdout[-200:],
      'would show for cse_01QuietOne000003 "Quiet one": Long job q2, working 20 min' in r.stdout
      and any('"Quiet one" written (dry) | Long job q2, working 20 min | It finished' in l for l in log_lines())
      and not runs().get(CSE[Q], {}).get('note'))
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
