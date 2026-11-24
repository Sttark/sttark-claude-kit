#!/usr/bin/python3
"""Tests that an agent that was stopped or failed shows as done: close_ended_agents() in Resources/hooks/effort-hook.py
gives each entry with no end in a session's list of its agents the time its agent ended, from the session's record,
since Claude Code sends no SubagentStop for such an agent. On copies: a temp state folder, log and HOME, and a made-up
record of about 12 MB, in Claude Code's own line shapes, whose ends are 10 MB from its end, past the 4 MB that
ended_tasks() reads. The ends: a TaskStop with its killed <task-notification>, a failed one, a stopped one (the agent did
not finish before its session's Claude Code ended), a completed one for an entry with no agent id yet (found by the
Agent call's id), and a TaskStop alone. Not ends: a pending notice, an agent still at work, and a line with no time of
its own. Also: the time of the first line that says an agent ended; a read that starts where the entry was made and
then reads only what the record gained; a line still in the writing; entries from before `pos` was kept (read once
from the start); a `pos` past the record's end; and the hook itself on the session's step, a prompt and SubagentStop,
and no read on an agent's own step or outside Remote Control. No model call. Prints each case; exits 1 if any fails.
Run: /usr/bin/python3 tools/agent-stopped-test.py"""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.normpath(os.path.join(HERE, '../Resources/hooks/effort-hook.py'))
T = tempfile.mkdtemp(prefix='agent-stopped-test-')
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


SID = 'cse_01TESTstopped'
CID = 'f46255ef-1111-4222-8333-944455556666'
TP = os.path.join(T, 'projects', CID + '.jsonl')
os.makedirs(os.path.dirname(TP))
BASE = int(time.time()) - 6 * 3600  # the record's work started 6 hours ago

# the session's agents: (agent id, the Agent call's tool_use_id, description)
A = ('a5top00000000000a', 'toolu_01TESTstopA', 'Check the press 4 ink order')            # TaskStop, then killed
B = ('a5top00000000000b', 'toolu_01TESTfailB', 'Draft the supplier quote reply')         # failed
C = ('a5top00000000000c', 'toolu_01TESTrunsC', 'Sort the slitter blade log')             # still at work
D = ('a5top00000000000d', 'toolu_01TESTgoneD', 'Find the die sizes for the new label')   # its session's Claude Code ended
F = ('a5top00000000000f', 'toolu_01TESTcallF', 'Count the core stock')                   # completed; its entry has no id
G = ('a5top00000000000g', 'toolu_01TESTstopG', 'Review the laminate test notes')         # TaskStop alone
AGENTS = (A, B, C, D, F, G)
T_A, T_B, T_D, T_F, T_G, T_C = (BASE + 600 + 300 * i for i in range(6))


def iso(t):
    """A time as Claude Code writes it in a record."""
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(t)) + '.250Z'


def line(d):
    return json.dumps(d, separators=(',', ':')) + '\n'  # compact, as Claude Code writes its records


def write(*parts):
    with open(TP, 'a') as f:
        f.write(''.join(p if isinstance(p, str) else ''.join(p) for p in parts))


def filler(mb, t):
    text = 'Ink density for the press job, row by row, as read at the press. ' * 125  # about 8 KB
    return [line({'type': 'user', 'message': {'role': 'user', 'content': text}, 'uuid': f'u{i}', 'timestamp': iso(t)})
            for i in range(int(mb * 128))]


def agent_call(a, t):
    aid, tool, desc = a
    return [line({'parentUuid': 'p', 'isSidechain': False, 'message': {'role': 'assistant', 'content': [
                 {'type': 'tool_use', 'id': tool, 'name': 'Agent', 'input': {
                     'description': desc, 'subagent_type': 'general-purpose', 'run_in_background': True, 'prompt': desc}}]},
                  'type': 'assistant', 'uuid': 'c' + tool, 'timestamp': iso(t)}),
            line({'type': 'user', 'message': {'role': 'user', 'content': [{'tool_use_id': tool, 'type': 'tool_result', 'content': [
                {'type': 'text', 'text': f'Async agent launched successfully.\nagentId: {aid} (Use SendMessage with to: '
                                        f'{aid!r} to continue this agent.)'}]}]}, 'uuid': 'r' + tool, 'timestamp': iso(t + 1)})]


def notice(a, status, with_call=True):
    aid, tool, desc = a
    return ('<task-notification>\n<task-id>%s</task-id>\n%s<output-file>/private/tmp/claude-501/-Users-test/%s/tasks/%s.output'
            '</output-file>\n<status>%s</status>\n<summary>Agent "%s" %s</summary>\n</task-notification>'
            % (aid, f'<tool-use-id>{tool}</tool-use-id>\n' if with_call else '', CID, aid, status, desc, status))


def queued(text, t):
    """Claude Code queues a notice, hands it to the session as a prompt, takes it off the queue, and keeps a copy of
    the request to the API, which has no time of its own."""
    return [line({'type': 'queue-operation', 'operation': 'enqueue', 'timestamp': iso(t), 'sessionId': CID, 'content': text}),
            line({'parentUuid': 'p', 'isSidechain': False, 'attachment': {'type': 'queued_command', 'prompt': text,
                  'commandMode': 'task-notification'}, 'type': 'attachment', 'uuid': 'q', 'timestamp': iso(t)}),
            line({'type': 'queue-operation', 'operation': 'remove', 'timestamp': iso(t + 5), 'sessionId': CID, 'content': text}),
            line({'type': 'api-request-blob', 'sessionId': CID, 'hash': 'h0',
                  'message': {'role': 'system', 'content': [{'type': 'text', 'text': text}]}})]


def task_stop(a, t):
    aid, tool, desc = a
    call = 'toolu_01TESTtaskstop' + aid[-1]
    return [line({'parentUuid': 'p', 'isSidechain': False, 'message': {'role': 'assistant', 'content': [
                 {'type': 'tool_use', 'id': call, 'name': 'TaskStop', 'input': {'task_id': aid}, 'caller': {'type': 'direct'}}]},
                  'type': 'assistant', 'uuid': 's' + aid, 'timestamp': iso(t)}),
            line({'type': 'user', 'message': {'role': 'user', 'content': [{'tool_use_id': call, 'type': 'tool_result', 'content':
                json.dumps({'message': f'Successfully stopped task: {aid} ({desc})', 'task_id': aid})}]},
                  'uuid': 't' + aid, 'timestamp': iso(t + 1)})]


def entries():
    return {a['tool_use_id']: a for a in json.load(open(eh.STATE))['sessions'][SID].get('agents') or []}


def done(a):
    return entries().get(a[1], {}).get('done_at')


def set_state(rows, **session):
    with open(eh.STATE, 'w') as f:
        json.dump({'paused': True, 'sessions': {
            SID: dict({'level': 'high', 'title_at': time.time() + 3600, 'agents': rows}, **session),
            'cse_01TESTother': {'level': 'low', 'agents': [{'tool_use_id': 'toolu_01TESTotherrun', 'agent_id': A[0],
                                                             'type': 'Explore', 'started_at': time.time(), 'done_at': None}]}}}, f)


# The record up to the Agent calls; then each entry is made as on_agent() makes it, just before its agent starts
write(filler(1, BASE), *(agent_call(a, BASE + 60 + i) for i, a in enumerate(AGENTS)))
set_state([])
made = os.path.getsize(TP)
for a in AGENTS:
    eh.agent_entry(SID, {'tool_use_id': a[1], 'transcript_path': TP}, 'general-purpose', a[2], 'high', 'kit', 'Test.')
with eh.state() as s:  # SubagentStart gave each one its id, all but F's
    for e in s['sessions'][SID]['agents']:
        e['agent_id'] = next(a[0] for a in AGENTS if a[1] == e['tool_use_id']) if e['tool_use_id'] != F[1] else None
check('a new entry keeps where the record ended when it was made (`pos`)',
      all(e.get('pos') == made and e.get('done_at') is None for e in entries().values()), entries())
MADE_ROWS = [dict(e) for e in entries().values()]

# The work: ends 10 MB before the end of the record
write(filler(1, BASE + 120),
      queued(notice(A, 'killed'), T_A + 1), task_stop(A, T_A),  # the notice is in the record first, with a later time
      queued(notice(B, 'failed'), T_B),
      queued(notice(D, 'stopped', with_call=False), T_D),
      queued(notice(F, 'completed'), T_F),
      task_stop(G, T_G),
      queued('<task-notification>\n<task-type>queued-remote-notifications</task-type>\n<status>pending</status>\n'
             '<summary>1 unread notification</summary>\n</task-notification>', T_G + 30),
      queued(notice(C, 'pending'), T_G + 60),
      queued(notice(('b9cmd0001', 'toolu_01TESTbash', 'Run the label tests'), 'completed'), T_G + 90),
      filler(10, T_G + 120))
SIZE = os.path.getsize(TP)
tail = eh.ended_tasks(TP)
check('the ends are far from the end of the record: the 4 MB that ended_tasks() reads has none of them',
      SIZE > 11_000_000 and not {a[0] for a in AGENTS} & set(tail), (SIZE, tail))

# agent_ends() on its own
ends = eh.agent_ends(open(TP, 'rb').read())
check('agent_ends: a stopped agent ends at the first time a line gives, here its TaskStop, not the notice before it',
      ends.get(A[0]) == T_A and ends.get(A[1]) == T_A + 1, (ends.get(A[0]), ends.get(A[1]), T_A))
check('agent_ends: a notice names the agent and the Agent call that started it',
      ends.get(B[0]) == T_B and ends.get(B[1]) == T_B and ends.get(F[1]) == T_F, ends)
check('agent_ends: a stopped notice (the session\'s Claude Code ended) names the agent', ends.get(D[0]) == T_D, ends)
check('agent_ends: a TaskStop alone ends the agent', ends.get(G[0]) == T_G, ends)
check('agent_ends: a pending notice ends nothing', C[0] not in ends and C[1] not in ends, {k: v for k, v in ends.items() if 'c' in k[-1:]})
blob = line({'type': 'api-request-blob', 'sessionId': CID, 'message': {'role': 'system', 'content': [
    {'type': 'text', 'text': notice(C, 'killed')}]}}).encode()
check('agent_ends: a line with no time of its own (a copy of a request to the API) gives no end', eh.agent_ends(blob) == {}, eh.agent_ends(blob))

# close_ended_agents(): from where each entry was made, only what the record gained after that
reads = []
whole_lines = eh.whole_lines


def spy(path, start, end):
    reads.append((start, end))
    return whole_lines(path, start, end)


eh.whole_lines = spy
t0 = time.time()
eh.close_ended_agents(SID, TP)
secs = time.time() - t0
check('a stopped agent (TaskStop, then killed) shows as done, at the time it was stopped', done(A) == T_A, entries()[A[1]])
check('a failed agent shows as done, at the time of its notice', done(B) == T_B, entries()[B[1]])
check('an agent that did not finish before its session\'s Claude Code ended shows as done', done(D) == T_D, entries()[D[1]])
check('an entry with no agent id yet is found by the Agent call\'s id in the notice', done(F) == T_F, entries()[F[1]])
check('a TaskStop alone shows the agent as done', done(G) == T_G, entries()[G[1]])
check('an agent at work stays open, and its entry keeps where the read stopped',
      done(C) is None and entries()[C[1]].get('pos') == SIZE, entries()[C[1]])
check('the read starts where the entries were made, not at the start of the record', reads == [(made, SIZE)], reads)
print(f'      (read {(SIZE - made) / 1e6:.1f} MB of the record in {secs * 1000:.0f} ms)')
other = json.load(open(eh.STATE))['sessions']['cse_01TESTother']['agents'][0]
check("another session's entry with the same agent id is not touched", other.get('done_at') is None and 'pos' not in other, other)

reads.clear()
eh.close_ended_agents(SID, TP)
check('the next call with nothing new reads nothing', reads == [], reads)

# A line still in the writing is read once it is whole
end_c = line({'type': 'queue-operation', 'operation': 'enqueue', 'timestamp': iso(T_C), 'sessionId': CID, 'content': notice(C, 'killed')})
write(end_c[:len(end_c) // 2])
reads.clear()
eh.close_ended_agents(SID, TP)
check('a half-written line is not read: the agent stays open, and the next read starts at that line',
      done(C) is None and entries()[C[1]].get('pos') == SIZE and reads == [(SIZE, SIZE + len(end_c) // 2)], (entries()[C[1]], reads))
write(end_c[len(end_c) // 2:], filler(0.1, T_C + 60))
reads.clear()
eh.close_ended_agents(SID, TP)
check('once the line is whole, its end counts, and the read starts at that line',
      done(C) == T_C and reads and reads[0][0] == SIZE, (entries()[C[1]], reads))
SIZE2 = os.path.getsize(TP)

# Entries the hook wrote before it kept `pos`: the first call reads the whole record, once
H = ('a5top00000000000h', 'toolu_01TESTrunsH', 'Label the spare rolls')  # no end in the record
legacy = [{k: v for k, v in e.items() if k != 'pos'} for e in MADE_ROWS]
legacy.append(dict(legacy[0], tool_use_id=H[1], agent_id=H[0], desc=H[2]))
set_state(legacy)
reads.clear()
t0 = time.time()
eh.close_ended_agents(SID, TP)
secs = time.time() - t0
check('entries from before `pos` was kept: the first call reads the whole record', reads == [(0, SIZE2)], reads)
check('their stopped, failed and ended agents show as done, at the right times',
      (done(A), done(B), done(C), done(D), done(F), done(G)) == (T_A, T_B, T_C, T_D, T_F, T_G),
      [(e['desc'], e.get('done_at')) for e in entries().values()])
check('an agent with no end stays open, and its entry now keeps where the read stopped',
      entries()[H[1]].get('done_at') is None and entries()[H[1]].get('pos') == SIZE2, entries()[H[1]])
print(f'      (read the whole {SIZE2 / 1e6:.1f} MB record in {secs * 1000:.0f} ms)')
reads.clear()
eh.close_ended_agents(SID, TP)
check('after that, a call with nothing new reads nothing', reads == [], reads)

# A `pos` past the end of the record is not this record's: read it from the start
set_state([dict(e, pos=SIZE2 + 5000) if e['tool_use_id'] == A[1] else e for e in MADE_ROWS])
reads.clear()
eh.close_ended_agents(SID, TP)
check('an entry whose `pos` is past the end of the record is read for from the start', reads[:1] == [(0, SIZE2)] and done(A) == T_A, reads)

# An agent whose end is older than the list keeps: its entry leaves the list, as for any agent
set_state([dict(e, started_at=time.time() - 9 * 86400) if e['tool_use_id'] == B[1] else e for e in MADE_ROWS])
eh.close_ended_agents(SID, TP)
check('an entry that started more than 7 days ago with no end leaves the list, as at each write of the list',
      B[1] not in entries() and done(A) == T_A, list(entries()))
eh.whole_lines = whole_lines

# The hook itself, on copies: Auto effort is off, so a prompt or a step makes no model call
env = dict(os.environ, CLAUDE_CODE_BRIDGE_SESSION_ID=SID)
hook = lambda d, e=env: subprocess.run([sys.executable, HOOK], input=json.dumps(d), capture_output=True, text=True, env=e)
step = {'hook_event_name': 'PostToolUse', 'session_id': CID, 'transcript_path': TP, 'cwd': T, 'tool_name': 'Read',
        'tool_input': {'file_path': os.path.join(T, 'notes.txt')}, 'tool_response': {}}
set_state(MADE_ROWS)
r = hook(dict(step, agent_id=C[0], agent_type='general-purpose'))
check("the hook: an agent's own step reads nothing, so no entry changes",
      r.returncode == 0 and all(e.get('done_at') is None and e.get('pos') == made for e in entries().values()), (r, entries()))
r = hook(step)
check('the hook: a step of the session itself gives the stopped and failed agents their ends',
      r.returncode == 0 and not r.stdout.strip() and (done(A), done(B), done(D), done(F), done(G)) == (T_A, T_B, T_D, T_F, T_G)
      and done(C) == T_C, (r, entries()))
set_state(MADE_ROWS)
r = hook({'hook_event_name': 'UserPromptSubmit', 'session_id': CID, 'transcript_path': TP, 'cwd': T, 'prompt': notice(C, 'killed')})
check('the hook: a prompt (a <task-notification> comes as one) gives them their ends too',
      r.returncode == 0 and (done(A), done(G), done(C)) == (T_A, T_G, T_C), (r, entries()))
set_state(MADE_ROWS)
r = hook({'hook_event_name': 'SubagentStop', 'session_id': CID, 'transcript_path': TP, 'cwd': T, 'agent_id': H[0],
          'agent_type': 'Explore', 'agent_transcript_path': os.path.join(T, 'none.jsonl')})
check("the hook: another agent's SubagentStop gives them their ends too",
      r.returncode == 0 and not r.stdout.strip() and (done(A), done(B), done(F)) == (T_A, T_B, T_F), (r, entries()))
set_state(MADE_ROWS)
r = hook(step, {k: v for k, v in env.items() if k != 'CLAUDE_CODE_BRIDGE_SESSION_ID'})
check('the hook: a session that is not on Remote Control has no list, and nothing changes',
      r.returncode == 0 and all(e.get('done_at') is None for e in entries().values()), (r, entries()))
set_state([dict(MADE_ROWS[0], pos='not a number')])
r = hook({'hook_event_name': 'UserPromptSubmit', 'session_id': CID, 'transcript_path': TP, 'cwd': T, 'prompt': 'Go on'})
log = open(LOG).read().splitlines()
check('the hook: an entry it cannot read logs an error, and the prompt goes on to the effort hook\'s next steps',
      r.returncode == 0 and any(f'error  {SID} the ends of its agents could not be read' in x for x in log)
      and f'paused {SID} left at high | Go on' in log[-1], (r, log[-2:]))

shutil.rmtree(T)
print('all passed' if not failed else f'{len(failed)} failed')
sys.exit(1 if failed else 0)
