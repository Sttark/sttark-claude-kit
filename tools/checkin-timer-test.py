#!/usr/bin/python3
"""Tests the check-in timer in the session (Resources/hooks/checkin-timer.py) on copies: a test Kit folder, log and
~/.claude (STTARK_KIT_DIR, STTARK_KIT_LOG, STTARK_CLAUDE_DIR), made-up records, and stand-in Claude Code processes
(CLAUDE_PID points at a sleep this test starts). No session is touched and no model is called:
- the ask: an agent the session itself starts in the background (async_launched) or a Bash command it sends to the
  background gets one ask, as additionalContext, with CronCreate, a cron every 15 minutes (never minute 0 or 30, the
  first one about 15 minutes out), durable false and the prompt word for word; agents started together get one ask;
  an agent's own step, a foreground agent, a Bash command in the turn, a one-shot claude -p and the switch off get none;
- the timer: CronCreate with the prompt records its job, and then no ask comes; a CronCreate with another prompt is not
  the timer; a second timer gets a note to delete it; CronDelete of the job clears it, and the next background work
  asks again; a timer of a Claude Code that ended, or of a process that now runs another conversation, counts as gone;
- the check-in: what runs (each agent's task and last step, the Kit's fresh note) goes to the session, with the job;
  with no work, the session is told to delete the timer with its id; with the switch off, too; when the Kit cannot
  read what runs, the session still gets how to answer (the working rules hold none of it);
- other prompts: a timer left set with no work gets a reminder; with work, or with no timer, nothing;
- the log lines the Events page reads; bad input never fails; install-hooks.py adds the two entries and takes them out.
Run from the repo root: /usr/bin/python3 tools/checkin-timer-test.py"""
import contextlib, importlib.util, io, json, os, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, 'Resources', 'hooks')
HOOK = os.path.join(HOOKS, 'checkin-timer.py')
d = tempfile.mkdtemp(prefix='kit-timer test ')   # a space in the name, as in Application Support
KIT = os.path.join(d, 'kit')
LOG = os.path.join(d, 'log')
CLAUDE = os.path.join(d, 'claude')
PROJ = os.path.join(CLAUDE, 'projects', '-Users-name-src')
for p in (KIT, os.path.join(CLAUDE, 'sessions'), PROJ):
    os.makedirs(p)
fails = 0
procs = []


def check(what, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what)
    fails += not ok


def copy(args=('/bin/sleep', '600')):
    """A stand-in Claude Code process: its pid is the hook's CLAUDE_PID."""
    p = subprocess.Popen(list(args), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


def run(data, pid, state=None):
    """The hook, as Claude Code runs it: the event on its input, its answer on its output. (the additionalContext or
    '', the raw output)"""
    if state is not None:
        with open(os.path.join(KIT, 'state.json'), 'w') as f:
            json.dump(state, f)
    env = dict(os.environ, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_CLAUDE_DIR=CLAUDE, CLAUDE_PID=str(pid))
    r = subprocess.run([sys.executable, HOOK], input=data if isinstance(data, str) else json.dumps(data),
                       capture_output=True, text=True, env=env, timeout=60)
    ctx = ''
    if r.stdout.strip():
        try:
            ctx = json.loads(r.stdout)['hookSpecificOutput']['additionalContext']
        except (ValueError, KeyError):
            ctx = '<not json: %r>' % r.stdout
    return ctx, r


def log_lines():
    try:
        return [ln.rstrip('\n') for ln in open(LOG)]
    except OSError:
        return []


def timers():
    try:
        return json.load(open(os.path.join(KIT, 'checkin-timers.json')))
    except (OSError, ValueError):
        return {}


SID, SID2, SID3 = ('5e1a0000-0000-4000-8000-00000000000%d' % i for i in (1, 2, 3))
TP = {s: os.path.join(PROJ, s + '.jsonl') for s in (SID, SID2, SID3)}
for tp in TP.values():
    with open(tp, 'w') as f:
        f.write(json.dumps({'type': 'user', 'timestamp': '2026-01-05T15:00:00.000Z', 'message': {'content': 'Build it'}}) + '\n')
STATE = {'sessions': {'cse_01PressColorTest01': {'transcript': TP[SID], 'title': 'Press color'},
                      'cse_01LabelStockTest2': {'transcript': TP[SID2], 'title': 'Label stock'}}}


def agent_record(sid, aid, what, finished=False, last='npm test'):
    sub = os.path.join(PROJ, sid, 'subagents')
    os.makedirs(sub, exist_ok=True)
    with open(os.path.join(sub, 'agent-%s.meta.json' % aid), 'w') as f:
        json.dump({'description': what, 'finished': finished}, f)
    with open(os.path.join(sub, 'agent-%s.jsonl' % aid), 'w') as f:
        f.write(json.dumps({'type': 'assistant', 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime()),
                            'entrypoint': 'sdk-cli', 'message': {'content': [
                                {'type': 'tool_use', 'id': 'toolu_1', 'name': 'Bash',
                                 'input': {'command': last, 'description': 'Run the tests'}}]}}) + '\n')


def agent_start(sid, what='Build the color page', bg=None, aid=None, status='async_launched'):
    inp = {'description': what, 'prompt': 'Build it.'}
    if bg is not None:
        inp['run_in_background'] = bg
    e = {'hook_event_name': 'PostToolUse', 'session_id': sid, 'transcript_path': TP[sid], 'tool_name': 'Agent',
         'tool_input': inp, 'tool_response': {'status': status, 'agentId': 'a1b2c3d4', 'description': what}}
    if aid:
        e['agent_id'] = aid
    return e


def cron_create(sid, prompt, job):
    return {'hook_event_name': 'PostToolUse', 'session_id': sid, 'transcript_path': TP[sid], 'tool_name': 'CronCreate',
            'tool_input': {'cron': '6,21,36,51 * * * *', 'prompt': prompt, 'recurring': True, 'durable': False},
            'tool_response': {'id': job, 'humanSchedule': 'Every 15 minutes', 'recurring': True, 'durable': False}}


def prompt(sid, text):
    return {'hook_event_name': 'UserPromptSubmit', 'session_id': sid, 'transcript_path': TP[sid], 'prompt': text}


os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_CLAUDE_DIR=CLAUDE)  # for the module loaded here too
spec = importlib.util.spec_from_file_location('checkin_timer', HOOK)
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

# --- the cron ------------------------------------------------------------------------------------------------------
bad = []
for minute in range(60):
    now = time.mktime((2026, 1, 5, 10, minute, 30, 0, 0, -1))
    mins = [int(m) for m in T.cron_for(now).split()[0].split(',')]
    nxt = min((m - minute) % 60 or 60 for m in mins)
    if 0 in mins or 30 in mins or not (13 <= nxt <= 15) or sorted((b - a) % 60 for a, b in zip(mins, mins[1:] + mins[:1])) != [15] * 4:
        bad.append((minute, mins, nxt))
check('the cron: every 15 minutes, the first one 13 to 15 minutes out, never minute 0 or 30 (all 60 minutes): %r' % bad[:3], not bad)

# --- the ask -------------------------------------------------------------------------------------------------------
copy1 = copy()
ctx, r = run(agent_start(SID), copy1.pid, STATE)
cron = T.cron_for(time.time())
check('an agent the session starts in the background: one ask, with CronCreate, the cron, durable false and the prompt',
      r.returncode == 0 and 'CronCreate' in ctx and '"%s"' % cron in ctx and 'durable false' in ctx and 'recurring true' in ctx
      and T.PROMPT in ctx and 'select:CronCreate,CronDelete' in ctx and 'set no timer' in ctx.lower())
check('the ask carries the whole timer rule, as the working rules hold none of it: one timer, keep its id, CronDelete '
      'when no work runs', 'Set no second timer' in ctx and 'Keep the job id' in ctx
      and 'When no agent or background command of yours still runs, call CronDelete with that id' in ctx)
check('the prompt starts with the mark and tells the session to delete the timer when its work ends',
      T.PROMPT.startswith('[Sttark Claude Kit] Check-in:') and 'CronDelete' in T.PROMPT and '—' not in T.PROMPT + ctx
      and '--' not in T.PROMPT)
check('the ask is logged with the session\'s name and the work: %r' % log_lines()[-1:],
      any('checkin cse_01PressColorTest01 "Press color" timer asked | agent "Build the color page" started, every 15 min' in ln
          for ln in log_lines()))
ctx2, _ = run(agent_start(SID, 'Check the links'), copy1.pid)
check('a second agent started with it: no second ask', ctx2 == '' and timers()[SID].get('asked_pid') == copy1.pid)
ctx, _ = run(agent_start(SID2, aid='a9f8e7d6c5b4a3921'), copy1.pid)
check('an agent\'s own agent: no ask (an agent keeps no timer)', ctx == '' and SID2 not in timers())
ctx, _ = run(agent_start(SID2, bg=False, status='completed'), copy1.pid)
check('a foreground agent: no ask', ctx == '')
ctx, _ = run(agent_start(SID2, status='completed'), copy1.pid)
check('an agent that ran in the turn, though run_in_background was not given: no ask', ctx == '')
bash = {'hook_event_name': 'PostToolUse', 'session_id': SID2, 'transcript_path': TP[SID2], 'tool_name': 'Bash',
        'tool_input': {'command': 'make test', 'description': 'Run the tests'}, 'tool_response': {'stdout': 'ok'}}
ctx, _ = run(bash, copy1.pid)
check('a Bash command in the turn: no ask', ctx == '')
off = dict(STATE, checkins_chat=False)
bash['tool_response'] = {'backgroundTaskId': 'b7x2k9q1', 'stdout': ''}
ctx, _ = run(bash, copy1.pid, off)
check('Check-ins in the session off: no ask', ctx == '' and SID2 not in timers())
ctx, _ = run(bash, copy1.pid, STATE)
check('a Bash command sent to the background: one ask', 'CronCreate' in ctx and any(
    '"Label stock" timer asked | background command "Run the tests" started' in ln for ln in log_lines()))
oneshot = copy([sys.executable, '-c', 'import time; time.sleep(600)', '-p'])
ctx, _ = run(agent_start(SID3), oneshot.pid)
check('a one-shot claude -p: no ask, as no timer would come before it ends', ctx == '')
ctx, _ = run(agent_start(SID3), copy1.pid)
check('a session the Kit does not list is asked too, and named by its conversation id in the log',
      'CronCreate' in ctx and any('checkin %s "Session 5e1a0000" timer asked' % SID3 in ln for ln in log_lines()))

# --- the timer -----------------------------------------------------------------------------------------------------
ctx, _ = run(cron_create(SID, 'Remind me to look at the press at 3 PM', 'aa11bb22'), copy1.pid)
check('a CronCreate with another prompt is not the timer', ctx == '' and not timers()[SID].get('job'))
ctx, _ = run(cron_create(SID, T.PROMPT, '3f9a2c1d'), copy1.pid)
t = timers()[SID]
check('CronCreate with the prompt records the timer: its job, its Claude Code and when',
      ctx == '' and t.get('job') == '3f9a2c1d' and t.get('pid') == copy1.pid and time.time() - t.get('set_at', 0) < 60
      and any('"Press color" timer set 3f9a2c1d | every 15 min' in ln for ln in log_lines()))
ctx, _ = run(agent_start(SID, 'Draw the pictures'), copy1.pid)
check('a timer is set: no ask at the next agent', ctx == '')
ctx, _ = run(cron_create(SID, T.PROMPT, '77ee88ff'), copy1.pid)
check('a second timer gets a note to delete it, and the first one stays',
      'CronDelete' in ctx and '"77ee88ff"' in ctx and '3f9a2c1d' in ctx and timers()[SID]['job'] == '3f9a2c1d'
      and any('timer second 77ee88ff | asked to delete it, as timer 3f9a2c1d is set' in ln for ln in log_lines()))
res = {'hook_event_name': 'PostToolUse', 'session_id': SID, 'transcript_path': TP[SID], 'tool_name': 'CronCreate',
       'tool_input': {'cron': '6,21,36,51 * * * *', 'prompt': T.PROMPT},
       'tool_response': 'Scheduled recurring job 9c8b7a6d (Every 15 minutes). Next run: 10:21 AM.'}
check('the job id is read from the text of the result too', T.job_id(res['tool_response']) == '9c8b7a6d'
      and T.job_id({'id': 'x1'}) == 'x1')

# --- the check-in --------------------------------------------------------------------------------------------------
agent_record(SID, 'a1b2c3d4e5f6a7b8c', 'Build the color page', last='npm test -- color')
with open(os.path.join(KIT, 'checkins.json'), 'w') as f:
    json.dump({'sessions': {'cse_01PressColorTest01': {'note': 'The agent built the color page. Next it runs the tests.',
                                                       'note_at': time.time() - 240}}}, f)
ctx, r = run(prompt(SID, T.PROMPT), copy1.pid)
check('a check-in with an agent at work: the session gets what runs, the agent\'s last step, the Kit\'s note and the job: %r'
      % ctx[:300], r.returncode == 0 and 'Agent "Build the color page" (a1b2c3d4e5f6a7b8c)' in ctx
      and 'its last step: ran: Run the tests' in ctx
      and 'The agent built the color page. Next it runs the tests.' in ctx and '4 min ago' in ctx
      and 'job 3f9a2c1d' in ctx and 'no tool call' in ctx)
check('the check-in is logged with what runs', any('"Press color" timer check-in 3f9a2c1d | 1 agent' in ln for ln in log_lines())
      and time.time() - timers()[SID].get('fired_at', 0) < 60)
with open(os.path.join(KIT, 'checkins.json'), 'w') as f:
    json.dump({'sessions': {'cse_01PressColorTest01': {'note': 'An old note.', 'note_at': time.time() - 3600}}}, f)
ctx, _ = run(prompt(SID, T.PROMPT), copy1.pid)
check('an old note of the Kit\'s is not news, so it does not go', 'An old note.' not in ctx and 'Build the color page' in ctx)
ctx, _ = run(prompt(SID, 'How does the color page look?'), copy1.pid)
check('the person\'s prompt while the work runs: nothing added', ctx == '')
agent_record(SID, 'a1b2c3d4e5f6a7b8c', 'Build the color page', finished=True)
ctx, _ = run(prompt(SID, '<task-notification><task-id>a1b2c3d4e5f6a7b8c</task-id><status>completed</status></task-notification>'), copy1.pid)
check('the notice that the last agent ended: a reminder to delete the timer with its id: %r' % ctx[:200],
      'CronDelete' in ctx and 'id "3f9a2c1d"' in ctx and 'Say nothing about it' in ctx
      and any('"Press color" timer reminder 3f9a2c1d | no work runs: asked to delete it' in ln for ln in log_lines()))
ctx, _ = run(prompt(SID, T.PROMPT), copy1.pid)
check('a check-in with no work: the session is told to delete the timer with its id and reply in one line',
      'CronDelete with id "3f9a2c1d"' in ctx and 'one line' in ctx and 'no other tool' in ctx.lower()
      and 'If none' not in ctx
      and any('timer check-in 3f9a2c1d | no work runs: asked to delete it' in ln for ln in log_lines()))
check('with every agent marked ended, the note is firm', 'Each agent and background command you started has ended' in ctx)
agent_record(SID, 'c3d4e5f6a7b8c9d0e', 'Order the die')   # not finished, but quiet for 20 minutes: the Kit is not sure
q = os.path.join(PROJ, SID, 'subagents', 'agent-c3d4e5f6a7b8c9d0e.jsonl')
os.utime(q, (time.time() - 1200, time.time() - 1200))
ctx, _ = run(prompt(SID, T.PROMPT), copy1.pid)
check('an agent that went quiet with no notice: the note to delete is only if none still runs, with the reply rules: %r' % ctx[:240],
      '1 agent went quiet' in ctx and 'If none of your agents or background commands still runs' in ctx
      and 'CronDelete with id "3f9a2c1d"' in ctx and T.REPLY in ctx)
os.remove(q)
os.remove(q[:-len('.jsonl')] + '.meta.json')
agent_record(SID, 'b2c3d4e5f6a7b8c9d', 'Check the links')
ctx, _ = run(prompt(SID, T.PROMPT), copy1.pid, off)
check('a check-in with the switch off: the session is told to delete the timer',
      'off' in ctx and 'CronDelete with id "3f9a2c1d"' in ctx and 'Check-ins stopped.' in ctx
      and any('timer check-in 3f9a2c1d | check-ins in the session are off: asked to delete it' in ln for ln in log_lines()))
ctx, _ = run(prompt(SID, 'Next step?'), copy1.pid, off)
check('the person\'s prompt with the switch off and a timer set: told to delete it', 'CronDelete with id "3f9a2c1d"' in ctx)
run({}, copy1.pid, STATE)
os.environ['CLAUDE_PID'] = str(copy1.pid)   # the hook in this process, as copy1


def unreadable(tp, now):
    raise OSError('the records cannot be read')


T.running, real_running = unreadable, T.running
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    T.on_prompt(prompt(SID, T.PROMPT), time.time())
T.running = real_running
os.environ.pop('CLAUDE_PID')
ctx = json.loads(buf.getvalue())['hookSpecificOutput']['additionalContext'] if buf.getvalue().strip() else ''
check('a check-in when the Kit cannot read what runs: the session still gets how to answer, and to delete the timer '
      'with its id when no work runs', T.REPLY in ctx and 'CronDelete with id "3f9a2c1d"' in ctx and 'one line' in ctx
      and timers()[SID]['job'] == '3f9a2c1d')
delete = {'hook_event_name': 'PostToolUse', 'session_id': SID, 'transcript_path': TP[SID], 'tool_name': 'CronDelete',
          'tool_input': {'id': '77ee88ff'}, 'tool_response': {'id': '77ee88ff'}}
run(delete, copy1.pid)
check('CronDelete of another job leaves the timer', timers()[SID]['job'] == '3f9a2c1d')
delete['tool_input'] = {'id': '3f9a2c1d'}
run(delete, copy1.pid)
check('CronDelete of the timer clears it, and logs it', not timers()[SID]['job']
      and any('"Press color" timer ended 3f9a2c1d' in ln for ln in log_lines()))
ctx, _ = run(prompt(SID, 'Thanks'), copy1.pid)
check('no timer: nothing on the next prompt', ctx == '')
ctx, _ = run(agent_start(SID, 'Draw the pictures'), copy1.pid)
check('new background work after the timer ended: the Kit asks again', 'CronCreate' in ctx)

# --- a timer that is gone ------------------------------------------------------------------------------------------
run(cron_create(SID, T.PROMPT, '5d4c3b2a'), copy1.pid)
copy1.kill()
copy1.wait()
copy2 = copy()
ctx, _ = run(agent_start(SID, 'Draw the pictures'), copy2.pid)
check('the Claude Code that set the timer ended (the session moved to a new copy): the new copy is asked', 'CronCreate' in ctx)
run(cron_create(SID, T.PROMPT, '1a2b3c4d'), copy2.pid)
with open(os.path.join(CLAUDE, 'sessions', '%d.json' % copy2.pid), 'w') as f:
    json.dump({'pid': copy2.pid, 'sessionId': SID2}, f)
check('a process that now runs another conversation holds no timer of this one', not T.live(timers()[SID], SID, time.time()))
os.remove(os.path.join(CLAUDE, 'sessions', '%d.json' % copy2.pid))
r0 = timers()[SID]
check('after 7 days the timer counts as gone, as CronCreate ends it', T.live(r0, SID, time.time())
      and not T.live(r0, SID, time.time() + 7 * 86400 + 60))
ctx, _ = run(prompt(SID3, T.PROMPT), copy2.pid)
check('a check-in from a timer the Kit did not see set (no work): the session finds its id itself with CronList',
      'CronList' in ctx and 'CronDelete' in ctx)

# --- bad input -----------------------------------------------------------------------------------------------------
for bad_in in ('', 'not json', '[1, 2]', json.dumps({'hook_event_name': 'PostToolUse'})):
    ctx, r = run(bad_in, copy2.pid)
    if r.returncode != 0 or r.stdout.strip():
        check('bad input %r: no answer, no failure' % bad_in, False)
        break
else:
    check('bad input: no answer, no failure', True)
check('no error in the log', not any('timer error' in ln for ln in log_lines()))

# --- install-hooks.py ----------------------------------------------------------------------------------------------
home = os.path.join(d, 'home')
os.makedirs(home)
env = dict(os.environ, HOME=home, STTARK_KIT_DIR=KIT)
subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'install-hooks.py')], env=env, capture_output=True, timeout=60)
s = json.load(open(os.path.join(home, '.claude', 'settings.json')))
post = [g for g in s['hooks'].get('PostToolUse', []) if any('checkin-timer.py' in h['command'] for h in g['hooks'])]
ups = [g for g in s['hooks'].get('UserPromptSubmit', []) if any('checkin-timer.py' in h['command'] for h in g['hooks'])]
check('install-hooks.py adds the PostToolUse entry (Agent, Bash, CronCreate, CronDelete; not in the background) and the prompt entry',
      len(post) == 1 and post[0]['matcher'] == 'Agent|Task|Bash|CronCreate|CronDelete' and not post[0]['hooks'][0].get('async')
      and len(ups) == 1 and not ups[0]['hooks'][0].get('async'))
st = json.loads(subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'install-hooks.py'), '--status'], env=env,
                               capture_output=True, text=True, timeout=60).stdout)
check('--status says the timer hook is in', st.get('checkin_timer') is True)
subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'install-hooks.py'), '--remove'], env=env, capture_output=True, timeout=60)
s = json.load(open(os.path.join(home, '.claude', 'settings.json')))
check('--remove takes it out', 'checkin-timer.py' not in json.dumps(s))

for p in procs:
    try:
        p.kill()
    except OSError:
        pass
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
