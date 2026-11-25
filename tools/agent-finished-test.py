#!/usr/bin/python3
"""Tests that an agent Claude Code marks finished shows as done, for each type of agent and with no SubagentStop:
agent_finished(), agent_by_call(), close_ended_agents() and close_agents() (the minute check, from track()) and
on_agent_answer() in Resources/hooks/effort-hook.py. On copies: a temp state folder, log and HOME, and made-up records
in Claude Code's own shapes: a session's record, and for each agent its record and its meta.json. The agents: a
web-fetch agent in the foreground, marked finished, with no SubagentStop and no notice; an agent in the background
that still works; an entry with no agent id whose agent is marked finished; an agent that was stopped with TaskStop
in a session that sends no event after that, in an entry from before `pos` was kept. Also: the time of the end (the
agent's last entry, or the meta file's time when that is earlier); no write of the state when nothing changed; the
list and running_agents() agree; track() runs the minute check first, and goes on when it fails; the Agent tool's
answer of an agent in the foreground (`completed`) ends its entry, an answer from the background does not; and the
hook itself on the Agent tool's answer and on a step of the session. No model call, no network. Prints each case;
exits 1 if any fails.
Run: /usr/bin/python3 tools/agent-finished-test.py"""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.normpath(os.path.join(HERE, '../Resources/hooks/effort-hook.py'))
T = tempfile.mkdtemp(prefix='agent-finished-test-')
HOME, KIT, LOG = (os.path.join(T, x) for x in ('home', 'kit', 'log'))
for k in [k for k in os.environ if k.startswith('CLAUDE')]:
    del os.environ[k]
os.environ.update(HOME=HOME, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_EFFORT_DRY='1')
os.makedirs(KIT)
os.makedirs(os.path.join(HOME, '.claude'))
spec = importlib.util.spec_from_file_location('eh', HOOK)
eh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eh)

failed = []


def check(name, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + name + ('' if ok else f'  -- {detail}'))
    if not ok:
        failed.append(name)


SID, OTHER = 'cse_01TESTfinished', 'cse_01TESTstopsess'
CID, CID2 = 'f46255ef-2222-4333-8444-955566667777', 'f46255ef-3333-4444-8555-966677778888'
TP = os.path.join(T, 'projects', CID + '.jsonl')
TP2 = os.path.join(T, 'projects', CID2 + '.jsonl')
SUB = os.path.join(TP[:-len('.jsonl')], 'subagents')
os.makedirs(SUB)
os.makedirs(os.path.join(TP2[:-len('.jsonl')], 'subagents'))
NOW = time.time()
BASE = int(NOW) - 3 * 3600  # the session's work started 3 hours ago

# the agents: (agent id, the Agent call's tool_use_id, type, description)
W = ('a1fe7c4000000000w', 'toolu_01TESTfetchW', 'web-fetch', 'Fetch the ink supplier price page')  # foreground, finished
R = ('a1fe7c4000000000r', 'toolu_01TESTrunsR', 'general-purpose', 'Build the order form')          # background, works
N = ('a1fe7c4000000000n', 'toolu_01TESTnoidN', 'Explore', 'Find the die sizes for the new label')   # finished, no id
S = ('a1fe7c4000000000s', 'toolu_01TESTstopS', 'general-purpose', 'Sort the slitter blade log')     # TaskStop, quiet session
T_W, T_N, T_S = BASE + 600, BASE + 900, BASE + 1200


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(t)) + '.250Z'


def line(d):
    return json.dumps(d, separators=(',', ':')) + '\n'


def agent_files(tp, a, last, finished, meta_time=None, shape='background'):
    """An agent's record (its first entry at the session's start, its last at `last`) and its meta.json, as Claude
    Code writes them."""
    aid, tool, typ, desc = a
    base = os.path.join(tp[:-len('.jsonl')], 'subagents', f'agent-{aid}')
    with open(base + '.jsonl', 'w') as f:
        f.write(line({'isSidechain': True, 'agentId': aid, 'type': 'user', 'message': {'role': 'user', 'content': desc},
                      'timestamp': iso(BASE)}))
        f.write(line({'isSidechain': True, 'agentId': aid, 'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'text', 'text': 'The price page lists 3 inks.'}]}, 'timestamp': iso(last)}))
    meta = {'agentType': typ, 'isBuiltIn': True, 'description': desc, 'toolUseId': tool, 'spawnDepth': 1,
            'requestShape': shape, 'requestNonInteractive': True}
    if finished:
        meta['finished'] = True
    with open(base + '.meta.json', 'w') as f:
        json.dump(meta, f, separators=(',', ':'))
    mt = meta_time or last + 1  # Claude Code marks the agent finished just after its last entry
    os.utime(base + '.jsonl', (mt, mt))
    os.utime(base + '.meta.json', (mt, mt))
    return base


def entry(a, with_id=True, pos=True, **more):
    aid, tool, typ, desc = a
    e = {'tool_use_id': tool, 'agent_id': aid if with_id else None, 'type': typ, 'desc': desc, 'level': 'medium',
         'set_by': 'kit', 'reason': 'Test.', 'started_at': BASE + 60, 'done_at': None}
    if pos:
        e['pos'] = os.path.getsize(TP)
    e.update(more)
    return e


def set_state(sessions):
    with open(eh.STATE, 'w') as f:
        json.dump({'paused': True, 'sessions': sessions}, f)


def rows(sid=SID):
    return {a['tool_use_id']: a for a in json.load(open(eh.STATE))['sessions'][sid].get('agents') or []}


def session(rows_, tp=TP, **more):
    return dict({'level': 'high', 'title_at': NOW + 3600, 'transcript': tp, 'at': NOW, 'agents': rows_}, **more)


# The session's record: the Agent calls, and some work; the other session's record ends with a TaskStop
with open(TP, 'w') as f:
    f.write(line({'type': 'user', 'message': {'role': 'user', 'content': 'Get the ink prices and build the order form.'},
                  'timestamp': iso(BASE)}))
    for i, a in enumerate((W, R, N)):
        f.write(line({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': a[1], 'name': 'Agent', 'input': {'description': a[3], 'subagent_type': a[2],
                                                                         'prompt': a[3]}}]}, 'timestamp': iso(BASE + 60 + i)}))
agent_files(TP, W, T_W, True, shape='foreground')
agent_files(TP, R, int(NOW) - 30, False)
agent_files(TP, N, T_N, True)
with open(TP2, 'w') as f:
    f.write(line({'type': 'user', 'message': {'role': 'user', 'content': 'Sort the blade log.'}, 'timestamp': iso(BASE)}))
    f.write(line({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 'toolu_01TESTtaskstopS', 'name': 'TaskStop', 'input': {'task_id': S[0]}}]},
        'timestamp': iso(T_S)}))
    f.write(line({'type': 'user', 'message': {'role': 'user', 'content': [{'tool_use_id': 'toolu_01TESTtaskstopS',
                  'type': 'tool_result', 'content': 'Successfully stopped task: %s (%s)' % (S[0], S[3])}]},
                  'timestamp': iso(T_S + 1)}))
agent_files(TP2, S, T_S - 5, False)

# agent_finished() and agent_by_call() on their own
check('agent_finished: a finished agent ended at the time of the last entry in its own record (in whole seconds, as other ends)',
      eh.agent_finished(TP, W[0]) == T_W, eh.agent_finished(TP, W[0]))
check('agent_finished: an agent still at work has no end', eh.agent_finished(TP, R[0]) == 0, eh.agent_finished(TP, R[0]))
check('agent_finished: an agent with no meta.json, no id, or an id that is not one, has no end',
      (eh.agent_finished(TP, 'a1fe7c400000000zz'), eh.agent_finished(TP, ''), eh.agent_finished(TP, '../x'),
       eh.agent_finished('', W[0])) == (0, 0, 0, 0))
X = ('a1fe7c4000000000x', 'toolu_01TESTlateX', 'Explore', 'Count the core stock')
base = agent_files(TP, X, BASE + 2000, True, meta_time=BASE + 1500)
check('agent_finished: the meta file\'s time when it is earlier than the last entry (a copy wrote the record again)',
      eh.agent_finished(TP, X[0]) == BASE + 1500, eh.agent_finished(TP, X[0]))
os.remove(base + '.jsonl')
check('agent_finished: the meta file\'s time when the agent has no record', eh.agent_finished(TP, X[0]) == BASE + 1500,
      eh.agent_finished(TP, X[0]))
os.remove(base + '.meta.json')
check('agent_by_call: the agent that a call started, from the toolUseId in its meta.json',
      eh.agent_by_call(TP, N[1], BASE + 60) == N[0], eh.agent_by_call(TP, N[1], BASE + 60))
check('agent_by_call: a meta.json from before the entry was made is not read',
      eh.agent_by_call(TP, N[1], T_N + 3600) == '', eh.agent_by_call(TP, N[1], T_N + 3600))
check('agent_by_call: no agent for a call that started none', eh.agent_by_call(TP, 'toolu_01TESTnone', 0) == '')

# The minute check, with no event from either session
set_state({SID: session([entry(W), entry(R), entry(N, with_id=False)]),
           OTHER: session([entry(S, pos=False)], tp=TP2),  # an entry from before `pos` was kept
           'cse_01TESTnoagents': {'level': 'low', 'transcript': TP},
           'cse_01TESTnotrans': {'level': 'low', 'agents': [entry(W)]}})
MADE = os.path.getsize(TP)
with open(TP, 'a') as f:  # the session works on after the entries were made
    f.write(line({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Prices in.'}]},
                  'timestamp': iso(T_W + 5)}))
reads, metas = [], []
whole_lines, finished = eh.whole_lines, eh.agent_finished
eh.whole_lines = lambda p, a, b: reads.append((p, a, b)) or whole_lines(p, a, b)
eh.agent_finished = lambda tp, aid: metas.append(aid) or finished(tp, aid)
t0 = time.time()
eh.close_agents()
secs = time.time() - t0
got = rows()
check('the minute check: a web-fetch agent in the foreground, with no SubagentStop and no notice, shows as done',
      got[W[1]].get('done_at') == T_W, got[W[1]])
check('the minute check: an entry with no agent id gets the id and the end from Claude Code\'s records',
      got[N[1]].get('agent_id') == N[0] and got[N[1]].get('done_at') == T_N, got[N[1]])
check('the minute check: an agent still at work stays open, and its entry keeps where the read stopped',
      got[R[1]].get('done_at') is None and got[R[1]].get('pos') == os.path.getsize(TP), got[R[1]])
check('the minute check: an agent stopped in a session that sent no event after that shows as done, at its TaskStop',
      rows(OTHER)[S[1]].get('done_at') == T_S and rows(OTHER)[S[1]].get('pos') is None, rows(OTHER)[S[1]])
check('the minute check: the records of finished agents are not read; the session\'s record only for the open one',
      reads == [(TP, MADE, os.path.getsize(TP)), (TP2, 0, os.path.getsize(TP2))], reads)
check('the minute check: only the meta.json of entries with no end is read',
      sorted(metas) == sorted([W[0], R[0], N[0], S[0]]), metas)
st = json.load(open(eh.STATE))['sessions']
check('the minute check: a session with no transcript, or with no list, is not touched',
      st['cse_01TESTnotrans']['agents'][0].get('done_at') is None and 'agents' not in st['cse_01TESTnoagents'], st)
print(f'      (the minute check took {secs * 1000:.0f} ms)')
running = {a['aid'] for a in eh.running_agents(TP, set(), foreground=True)}
check('the list and running_agents() agree: open in the list only while running_agents() counts it',
      {t for t, a in rows().items() if not a.get('done_at')} == {R[1]} and running == {R[0]}, (rows(), running))

reads.clear()
metas.clear()
stamp = os.stat(eh.STATE).st_mtime_ns
time.sleep(0.01)
eh.close_agents()
check('the next minute check with nothing new reads only the open agent\'s meta.json, and writes no state',
      reads == [] and metas == [R[0]] and os.stat(eh.STATE).st_mtime_ns == stamp, (reads, metas))
eh.whole_lines, eh.agent_finished = whole_lines, finished

# The background agent ends: the next minute check shows it as done
agent_files(TP, R, int(NOW) - 5, True)
eh.close_agents()
check('the minute check: once Claude Code marks the background agent finished, it shows as done',
      rows()[R[1]].get('done_at') == int(NOW) - 5, rows()[R[1]])
agent_files(TP, R, int(NOW) - 30, False)

# track() runs the minute check first, and goes on when it fails
set_state({SID: session([entry(W)])})


class Stop(Exception):
    pass


def no_list():
    raise Stop()


app_list, close = eh.app_list, eh.close_agents
eh.app_list = no_list  # track() reads the Claude app's list next, from the server: never in a test
try:
    eh.track()
except Stop:
    pass
check('track(): the minute check runs first', rows()[W[1]].get('done_at') == T_W, rows()[W[1]])
eh.close_agents = lambda: 1 / 0
went_on = False
try:
    eh.track()
except Stop:
    went_on = True
check('track(): a minute check that fails logs an error, and the check of the sessions goes on',
      went_on and 'error  the ends of agents could not be read: ZeroDivisionError' in open(LOG).read(), open(LOG).read()[-300:])
eh.app_list, eh.close_agents = app_list, close

# The Agent tool's answer
fg = {'status': 'completed', 'agentId': W[0], 'agentType': 'web-fetch', 'content': [{'type': 'text', 'text': 'Done.'}],
      'totalDurationMs': 20732}
answer = lambda a, res: eh.on_agent_answer({'hook_event_name': 'PostToolUse', 'tool_name': 'Agent', 'tool_use_id': a[1],
                                            'transcript_path': TP, 'tool_response': res}, SID)
set_state({SID: session([entry(W, with_id=False), entry(R, with_id=False), entry(N)])})
answer(W, fg)
check('the answer of an agent in the foreground (completed) gives its entry the id and the end from its record',
      rows()[W[1]].get('agent_id') == W[0] and rows()[W[1]].get('done_at') == T_W, rows()[W[1]])
answer(R, {'isAsync': True, 'status': 'async_launched', 'agentId': R[0]})
check('the answer of an agent in the background (async_launched) gives the id, not an end',
      rows()[R[1]].get('agent_id') == R[0] and rows()[R[1]].get('done_at') is None, rows()[R[1]])
answer(N, {'status': 'backgrounded', 'agentId': N[0]})
check('the answer of an agent sent to the background while it ran (backgrounded) gives no end',
      rows()[N[1]].get('done_at') is None, rows()[N[1]])
Y = ('a1fe7c4000000000y', 'toolu_01TESTnometaY', 'web-fetch', 'Fetch the press manual page')
set_state({SID: session([entry(Y)])})
t0 = time.time()
answer(Y, dict(fg, agentId=Y[0]))
check('a completed answer with no meta.json of the agent: the end is now', t0 <= (rows()[Y[1]].get('done_at') or 0) <= time.time(),
      rows()[Y[1]])
first = rows()[Y[1]]['done_at']
answer(Y, dict(fg, agentId=Y[0]))
check('a second answer keeps the first end', rows()[Y[1]]['done_at'] == first, rows()[Y[1]])

# The hook itself, on copies: Auto effort is off, so a step makes no model call
env = dict(os.environ, CLAUDE_CODE_BRIDGE_SESSION_ID=SID)
hook = lambda d: subprocess.run([sys.executable, HOOK], input=json.dumps(d), capture_output=True, text=True, env=env)
set_state({SID: session([entry(W, with_id=False), entry(R)])})
r = hook({'hook_event_name': 'PostToolUse', 'session_id': CID, 'transcript_path': TP, 'cwd': T, 'tool_name': 'Agent',
          'tool_use_id': W[1], 'tool_input': {'description': W[3], 'subagent_type': W[2], 'prompt': W[3]},
          'tool_response': fg})
check('the hook: the Agent tool\'s answer of a web-fetch agent in the foreground ends its entry, with no SubagentStop',
      r.returncode == 0 and not r.stdout.strip() and rows()[W[1]].get('done_at') == T_W
      and rows()[R[1]].get('done_at') is None, (r, rows()))
set_state({SID: session([entry(W), entry(R)])})
r = hook({'hook_event_name': 'PostToolUse', 'session_id': CID, 'transcript_path': TP, 'cwd': T, 'tool_name': 'Read',
          'tool_input': {'file_path': os.path.join(T, 'notes.txt')}, 'tool_response': {}})
check('the hook: a step of the session ends the entry of an agent that Claude Code marks finished',
      r.returncode == 0 and rows()[W[1]].get('done_at') == T_W and rows()[R[1]].get('done_at') is None, (r, rows()))

shutil.rmtree(T)
print('all passed' if not failed else f'{len(failed)} failed')
sys.exit(1 if failed else 0)
