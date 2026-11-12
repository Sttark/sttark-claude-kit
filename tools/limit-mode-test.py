#!/usr/bin/python3
"""Tests of each session's usage setting (Follow the menu, Always use credits, Never use credits; hold at N%)
in Resources/hooks/limit-hook.py, all on copies: a temp state folder and log, a stand-in usage file, stand-in
server events, and a temp HOME for transcripts, ~/.local/bin and install-hooks.py. Nothing real is read or
written, and no model is called. Prints each case; exits 1 if any fails.
Run: /usr/bin/python3 tools/limit-mode-test.py"""
import datetime, importlib.util, json, os, shutil, signal, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.normpath(os.path.join(HERE, '../Resources/hooks/limit-hook.py'))
INSTALL = os.path.normpath(os.path.join(HERE, '../Resources/hooks/install-hooks.py'))
T = tempfile.mkdtemp(prefix='limit-mode-test-')
HOME = os.path.join(T, 'home')
KIT = os.path.join(T, 'kit')
LOG = os.path.join(T, 'log')
USAGE = os.path.join(T, 'usage-standin.json')
EVENTS = os.path.join(T, 'events.json')
for k in [k for k in os.environ if k.startswith('CLAUDE')]:
    del os.environ[k]   # no real session's ids leak in
os.environ.update(HOME=HOME, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_LIMIT_TEST=USAGE,
                  STTARK_LIMIT_EVENTS=EVENTS, STTARK_LIMIT_TICK='0.3')
os.makedirs(os.path.join(HOME, '.claude/projects/-tmp-work'))
os.makedirs(KIT)
json.dump({'data': []}, open(EVENTS, 'w'))
spec = importlib.util.spec_from_file_location('lh', HOOK)
lh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lh)

failed = []


def check(name, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + name + ('' if ok else f'  -- {detail}'))
    if not ok:
        failed.append(name)


def iso(secs):
    return (datetime.datetime.now().astimezone() + datetime.timedelta(seconds=secs)).isoformat()


def usage(five=50, week=40, scoped=None, credits=True, spend=False, five_reset=3600, week_reset=3 * 86400):
    limits = [{'kind': 'session', 'percent': five, 'resets_at': iso(five_reset), 'scope': None},
              {'kind': 'weekly_all', 'percent': week, 'resets_at': iso(week_reset), 'scope': None}]
    if scoped is not None:
        limits.append({'kind': 'weekly_scoped', 'percent': scoped, 'resets_at': iso(week_reset + 60),
                       'scope': {'model': {'id': None, 'display_name': 'Fable'}}})
    u = {'extra_usage': {'is_enabled': credits, 'spend_limit_reached': spend}, 'limits': limits}
    json.dump(u, open(USAGE, 'w'))
    return u


def state(**kv):
    json.dump(kv, open(os.path.join(KIT, 'state.json'), 'w'))


def peek():
    return lh.peek()


def transcript(sid, model='claude-sonnet-5-5'):
    p = os.path.join(HOME, '.claude/projects/-tmp-work', sid + '.jsonl')
    with open(p, 'w') as f:
        f.write(json.dumps({'type': 'assistant', 'message': {'model': model, 'content': []}}).replace(' ', '') + '\n')
    return p


def run(args, stdin=None, env=None, timeout=20):
    e = dict(os.environ, **(env or {}))
    r = subprocess.run(['/usr/bin/python3', HOOK] + args, input=stdin, capture_output=True, text=True, env=e,
                       timeout=timeout, cwd=T)
    return r


def hook(event, sid, tp, extra=None, args=(), env=None):
    d = {'hook_event_name': event, 'session_id': sid, 'transcript_path': tp, 'cwd': '/tmp/work'}
    d.update(extra or {})
    r = run(list(args), stdin=json.dumps(d), env=env)
    return json.loads(r.stdout) if r.stdout.strip() else None


def logtext():
    try:
        return open(LOG).read()
    except OSError:
        return ''


S1 = '11111111-aaaa-4bbb-8ccc-000000000001'
S2 = '22222222-aaaa-4bbb-8ccc-000000000002'
C2 = 'cse_01TestSessionTwo'
S3 = '33333333-aaaa-4bbb-8ccc-000000000003'
TP1, TP2, TP3 = transcript(S1), transcript(S2), transcript(S3, 'claude-fable-5-2')

# ---- every setting against usage at 50, 85 and 100% --------------------------------------------------------
print('-- settings against usage')
for credits_all in (False, True):
    for mode, entry in (('follow', None), ('credits', {'mode': 'credits'}), ('hold 80', {'mode': 'hold', 'at': 80})):
        modes = {S1: dict(entry, sid=S1, set_at=time.time())} if entry else {}
        st = {'limit_credits_all': credits_all, 'limit_modes': modes}
        for p, want in ((50, None), (85, 'hold' if mode == 'hold 80' else None),
                        (100, None if mode == 'credits' or (mode == 'follow' and credits_all) else
                         ('hold' if mode == 'hold 80' else 'follow'))):
            h = lh.hold_for(S1, '', TP1, usage(five=p), st)
            got = h.mode if h else None
            check(f'{mode:8} credits_all={credits_all!s:5} 5-hour {p:3}% -> {want}', got == want, f'got {h}')
# no usage credits on the account
st = {'limit_modes': {S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}}}
check('follow, account without credits, 100% -> no hold', lh.hold_for(S1, '', TP1, usage(five=100, credits=False), {}) is None)
check('follow, credits spend limit reached, 100% -> no hold', lh.hold_for(S1, '', TP1, usage(five=100, spend=True), {}) is None)
h = lh.hold_for(S1, '', TP1, usage(five=85, credits=False), st)
check('hold 80, account without credits, 85% -> holds', bool(h) and h.at == 80 and h.percent == 85, h)
h = lh.hold_for(S1, '', TP1, usage(five=85), st)
check('hold line names 80% and the reset', h and lh.line(h).startswith('This session holds at 80% usage. I continue at'), h and lh.line(h))
# which limit and which reset
h = lh.hold_for(S1, '', TP1, usage(five=50, week=85), st)
check('hold 80: weekly at 85% holds, until the weekly reset', h and h.name == 'weekly' and h.percent == 85, h)
u = usage(five=90, week=81)
h = lh.hold_for(S1, '', TP1, u, st)
check('hold 80: both over 80 -> waits for the later (weekly) reset',
      h and h.name == 'weekly' and abs(h.until - lh.stamp(u['limits'][1]['resets_at'])) < 1, h)
h = lh.hold_for(S1, '', TP1, usage(five=85, five_reset=-60), st)
check('hold 80: a limit whose reset has passed no longer counts', h is None, h)
h = lh.hold_for(S1, '', TP1, usage(five=79), st)
check('hold 80: 79% goes on', h is None, h)
st100 = {'limit_modes': {S1: {'mode': 'hold', 'at': 100, 'sid': S1, 'set_at': 1}}, 'limit_credits_all': True}
check('hold 100 with credits_all on: 99% goes on, 100% holds',
      lh.hold_for(S1, '', TP1, usage(five=99), st100) is None and lh.hold_for(S1, '', TP1, usage(five=100), st100) is not None)
# a model's own weekly limit
st3 = {'limit_modes': {S3: {'mode': 'hold', 'at': 80, 'sid': S3, 'set_at': 1}, S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}}}
h = lh.hold_for(S3, '', TP3, usage(scoped=90), st3)
check('Fable weekly at 90% holds a session on Fable', h and h.name == 'Fable weekly', h)
check('... and not a session on another model', lh.hold_for(S1, '', TP1, usage(scoped=90), st3) is None)
# "use credits" for one session
stc = dict(st, limit_credits={S1: time.time() + 600})
check('hold 80 + "use credits" until the reset -> goes on', lh.hold_for(S1, '', TP1, usage(five=85), stc) is None)
check('... once=False still sees the hold', lh.hold_for(S1, '', TP1, usage(five=85), stc, once=False) is not None)
stc = dict(st, limit_credits={S1 + '/agent1': time.time() + 600})
check('a "use credits" saved under an agent row\'s key counts for the session', lh.hold_for(S1, '', TP1, usage(five=85), stc) is None)

# ---- phrases ------------------------------------------------------------------------------------------------
print('-- phrases')
for text, want in (('no credits', ('hold', 80)), ('No credits.', ('hold', 80)), ('no credits 90', ('hold', 90)),
                   ('no credits 90%', ('hold', 90)), ('no credits at 70', ('hold', 70)), ('NO CREDITS 100', ('hold', 100)),
                   ('never use credits 85', ('hold', 85)), ('never use credits', ('hold', 80)),
                   ('credits ok', ('credits', None)), ('Credits OK!', ('credits', None)),
                   ('always use credits', ('credits', None)), ('follow the menu', ('follow', None)),
                   ('Follow the menu.', ('follow', None)), ('use credits', ('once', None)), (' use  credits ', ('once', None)),
                   ([{'type': 'text', 'text': 'no credits 75'}], ('hold', 75)),
                   ('no credits were used', None), ('no credits 0', None), ('no credits 101', None), ('no credits 5000', None),
                   ('use credits now', None), ('are credits ok?', None), ('credits', None), ('please follow the menu', None),
                   ('I have no credits left, use the other plan', None), ('', None), (None, None)):
    check(f'phrase {text!r} -> {want}', lh.phrase(text) == want, lh.phrase(text))

# ---- set, look up, newest wins ---------------------------------------------------------------------------------
print('-- setting and lookup')
state(sessions={C2: {'title': 'Site map plan', 'transcript': TP2, 'at': time.time()}})
open(LOG, 'w').close()
check('set by sid and cse returns changed', lh.set_mode(S2, C2, 'hold', 70, 'menu'))
s = peek()
check('stored under the cse, with sid, cse, title, by', set(s['limit_modes']) == {C2}
      and s['limit_modes'][C2]['sid'] == S2 and s['limit_modes'][C2]['title'] == 'Site map plan'
      and s['limit_modes'][C2]['by'] == 'menu' and s['limit_modes'][C2]['at'] == 70, s['limit_modes'])
check('found by sid alone', lh.mode_of(s, S2, '') == ('hold', 70))
check('found by cse alone', lh.mode_of(s, '', C2) == ('hold', 70))
check('cse_of finds the cse from the transcript', lh.cse_of(S2, s, here=False) == C2)
check('log: mode line with the limit tag', 'limit  mode   22222222 never use credits; hold at 70% (menu)' in logtext(), logtext())
check('same setting again: no change, no new log line', not lh.set_mode(S2, C2, 'hold', 70, 'typed')
      and logtext().count('mode   22222222') == 1)
# two entries (one by sid, one by cse only): the newest wins, and a set replaces both
with lh.state() as st_:
    st_['limit_modes'] = {S2: {'mode': 'credits', 'sid': S2, 'set_at': time.time() - 100},
                          C2: {'mode': 'hold', 'at': 60, 'cse': C2, 'set_at': time.time()}}
s = peek()
check('newest wins: cse entry (newer) over sid entry', lh.mode_of(s, S2, C2) == ('hold', 60))
with lh.state() as st_:
    st_['limit_modes'][S2]['set_at'] = time.time() + 1
check('newest wins: sid entry when it is newer', lh.mode_of(peek(), S2, C2) == ('credits', None))
lh.set_mode(S2, C2, 'credits', None, 'typed')
check('a set leaves one entry', list(peek()['limit_modes']) == [C2], peek()['limit_modes'])
lh.set_mode(S2, C2, 'follow', None, 'command')
check('follow the menu removes the entry', peek()['limit_modes'] == {})
check('log: follow line', 'mode   22222222 follow the menu (command)' in logtext())
# a terminal session (no cse): keyed by sid
lh.set_mode(S1, '', 'hold', 80, 'typed', 'work')
check('no cse: keyed by the sid', S1 in peek()['limit_modes'])
# pruning
with lh.state() as st_:
    st_['sessions']['cse_01OldArchived'] = {'title': 'old', 'at': time.time() - 8 * 86400, 'app': {'archived': True}}
    st_['sessions']['cse_01NewArchived'] = {'title': 'new', 'at': time.time() - 3 * 86400, 'app': {'archived': True}}
    st_['limit_modes'].update({
        'cse_01OldArchived': {'mode': 'credits', 'cse': 'cse_01OldArchived', 'set_at': time.time() - 8 * 86400},
        'cse_01NewArchived': {'mode': 'credits', 'cse': 'cse_01NewArchived', 'set_at': time.time() - 3 * 86400},
        '99999999-aaaa-4bbb-8ccc-000000000009': {'mode': 'hold', 'at': 50, 'sid': '99999999-aaaa-4bbb-8ccc-000000000009',
                                                 'set_at': time.time() - 31 * 86400}})
lh.set_mode(S2, C2, 'hold', 80, 'menu')
m = peek()['limit_modes']
check('prune: archived 8 days -> dropped; archived 3 days -> kept (an unarchive keeps it); unused 31 days -> dropped',
      'cse_01OldArchived' not in m and 'cse_01NewArchived' in m and '99999999-aaaa-4bbb-8ccc-000000000009' not in m, list(m))

# ---- held() for the Kit's side calls -----------------------------------------------------------------------------
print('-- side calls')
state(limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}, S2: {'mode': 'credits', 'sid': S2, 'set_at': 1}})
usage(five=85)
check('held(): a hold-80 session at 85% skips its side calls', lh.held(S1, TP1, ''))
check('held(): a follow session at 85% does not', not lh.held(S3, TP3, ''))
check('held(): the account at 85% does not', not lh.held())
usage(five=100)
check('held(): the account at 100% (credits off for all) does', lh.held())
check('held(): an always-credits session at 100% does not', not lh.held(S2, TP2, ''))
state(limit_credits_all=True, limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})
check('held(): credits for every session: the account does not, the hold-80 session still does',
      not lh.held() and lh.held(S1, TP1, ''))

# ---- the hooks -------------------------------------------------------------------------------------------------
print('-- hooks')
state(limit_credits_all=True, limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})
open(LOG, 'w').close()
usage(five=85)
o = hook('PreToolUse', S1, TP1, {'tool_name': 'Edit', 'tool_input': {}})
r = o and o['hookSpecificOutput']
check('PreToolUse: hold-80 session at 85% with credits on for all is stopped', r and r['permissionDecision'] == 'deny'
      and 'holds at 80% usage' in r['permissionDecisionReason'] and 'limit-hook.py" wait ' + S1 in r['permissionDecisionReason'], o)
check('log: hold line', 'limit  hold   11111111 at 80%: the 5-hour limit is at 85%, until' in logtext(), logtext())
o = hook('PreToolUse', S1, TP1, {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'agent_id': 'agentA1'})
check('PreToolUse: an agent of a hold session is left to the --hold entry (no deny)', o is None, o)
state(limit_modes={S1: {'mode': 'hold', 'at': 100, 'sid': S1, 'set_at': 1}})
usage(five=100)
o = hook('PreToolUse', S1, TP1, {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'agent_id': 'agentA1'})
check('PreToolUse: ... also at 100% (hold 100)', o is None, o)
state(limit_modes={})
o = hook('PreToolUse', S1, TP1, {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'agent_id': 'agentA1'})
check('PreToolUse: an agent of a follow session at the limit is stopped with its own wait, as before', o and
      ('wait ' + S1 + '/agentA1') in o['hookSpecificOutput']['permissionDecisionReason'], o)
state(limit_credits_all=True, limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})
usage(five=85)
o = hook('PreToolUse', S1, TP1, {'tool_name': 'Bash', 'tool_input': {'command': 'claude-limit-wait ' + S1}})
check('PreToolUse: the wait command itself runs', o is None, o)
o = hook('PreToolUse', S3, TP3, {'tool_name': 'Edit', 'tool_input': {}})
check('PreToolUse: another session (follow) goes on with credits', o is None, o)
o = hook('PreToolUse', S1, TP1, {'tool_name': 'Edit', 'tool_input': {}}, args=['--hold'])
check('--hold: exits at once for anything but a wait command', o is None)
# messages
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'fix the map'})
ctx = o and o['hookSpecificOutput']['additionalContext']
check('message while held: goes through with the wait instruction', ctx and 'holds at 80% usage' in ctx
      and 'answer the message' in ctx, ctx)
o = hook('UserPromptSubmit', S1, TP1, {'prompt': '<task-notification>\n<task-id>x</task-id>'})
check('a task notification while held: told to handle it after GO ON',
      o and 'handle that notification' in o['hookSpecificOutput']['additionalContext'])
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'no credits 90'})
ctx = o and o['hookSpecificOutput']['additionalContext']
check('typed "no credits 90" at 85%: set, said, goes on', ctx and 'never use credits; hold at 90%' in ctx
      and 'Say so in one line, then go on' in ctx and lh.mode_of(peek(), S1, '') == ('hold', 90), ctx)
check('log: typed mode line', 'mode   11111111 never use credits; hold at 90% (typed)' in logtext())
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'No credits'})
ctx = o and o['hookSpecificOutput']['additionalContext']
check('typed "No credits" at 85%: hold at 80, and the wait instruction', ctx and 'hold at 80%' in ctx
      and 'claude-limit-wait' not in ctx and 'limit-hook.py" wait' in ctx, ctx)
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'credits ok'})
check('typed "credits ok": always use credits', lh.mode_of(peek(), S1, '') == ('credits', None)
      and 'always use credits' in o['hookSpecificOutput']['additionalContext'])
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'follow the menu'})
check('typed "follow the menu": the entry is gone', lh.mode_of(peek(), S1, '') == ('follow', None)
      and 'follow the menu' in o['hookSpecificOutput']['additionalContext'])
state(limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'use credits'})
lc = peek().get('limit_credits', {}).get(S1, 0)
check('typed "use credits" in a hold session at 85%: credits until the 5-hour reset, setting kept',
      abs(lc - lh.stamp(json.load(open(USAGE))['limits'][0]['resets_at'])) < 2 and lh.mode_of(peek(), S1, '') == ('hold', 80)
      and 'until the 5-hour limit resets' in o['hookSpecificOutput']['additionalContext'], (lc, o))

# ---- the command: claude-limit-mode ------------------------------------------------------------------------------
print('-- claude-limit-mode')
state(sessions={C2: {'title': 'Site map plan', 'transcript': TP2, 'at': time.time()},
                'cse_01OtherSession': {'title': 'Docs fixes', 'transcript': TP3, 'at': time.time()}})
open(LOG, 'w').close()
r = run(['mode', S2, 'hold', '80'])
check('mode <sid> hold 80', r.returncode == 0 and r.stdout.strip() == 'Site map plan (22222222): never use credits; hold at 80%', r.stdout + r.stderr)
check('... stored under the cse, by command, and logged', peek()['limit_modes'].get(C2, {}).get('by') == 'command'
      and 'mode   22222222 never use credits; hold at 80% (command)' in logtext())
r = run(['mode', S2])
check('mode <sid> prints the setting', r.stdout.strip() == 'Site map plan (22222222): never use credits; hold at 80%', r.stdout)
r = run(['mode', 'session_01TestSessionTwo', 'credits'])
check('mode session_<id> credits (a session_ id is the cse)', r.returncode == 0 and 'always use credits' in r.stdout
      and lh.mode_of(peek(), S2, C2) == ('credits', None), r.stdout + r.stderr)
r = run(['mode', '222222', 'hold', '75%'])
check('mode <6-character start> hold 75%', r.returncode == 0 and 'hold at 75%' in r.stdout, r.stdout + r.stderr)
r = run(['mode', 'site map PLAN', 'follow'])
check('mode <session name> follow', r.returncode == 0 and 'follow the menu' in r.stdout and peek()['limit_modes'] == {},
      r.stdout + r.stderr)
r = run(['mode', 'hold', '60'], env={'CLAUDE_CODE_SESSION_ID': S1})
check('mode hold 60 inside a session: this session', r.returncode == 0 and '(11111111): never use credits; hold at 60%' in r.stdout,
      r.stdout + r.stderr)
r = run(['mode', '.'], env={'CLAUDE_CODE_SESSION_ID': S1})
check('mode . prints this session', 'hold at 60%' in r.stdout, r.stdout)
r = run(['mode', '--list'])
check('mode --list', r.returncode == 0 and '(11111111): never use credits; hold at 60% (set by command' in r.stdout, r.stdout)
for args, why in ((['hold'], 'outside a session, no id'), ([S2, 'hold', '101'], 'over 100'), ([S2, 'hold', 'x'], 'not a number'),
                  ([S2, 'maybe'], 'unknown setting'), ([S2, 'credits', '5'], 'credits with a number'),
                  (['zzzzzzzz', 'credits'], 'no such session'), (['abc', 'credits'], 'too short to be a start')):
    r = run(['mode'] + args)
    check(f'mode {" ".join(args)} -> exit 2 ({why})', r.returncode == 2 and r.stderr.startswith('claude-limit-mode: '),
          (r.returncode, r.stdout, r.stderr))
r = run(['mode', 'cse_01', 'credits'])
check('a start that matches two sessions -> exit 2', r.returncode == 2 and 'matches 2 sessions' in r.stderr, r.stderr)
link = os.path.join(T, 'bin', 'claude-limit-mode')
os.makedirs(os.path.dirname(link))
os.symlink(HOOK, link)
r = subprocess.run(['/usr/bin/python3', link, S2], capture_output=True, text=True, env=os.environ, cwd=T)
check('called as claude-limit-mode (the link name)', r.returncode == 0 and 'Site map plan (22222222): follow the menu' in r.stdout,
      r.stdout + r.stderr)
r = run(['mode', '--help'])
check('mode --help', r.returncode == 0 and r.stdout.startswith('usage: claude-limit-mode'))

# ---- the hold in the hook: no model calls, ends at under N ------------------------------------------------------
print('-- the --hold hook')


def start_hold(sid, tp, agent=None, env=None, tool=None):
    name, inp = tool or ('Bash', {'command': 'claude-limit-wait ' + sid + ('/' + agent if agent else '')})
    d = {'hook_event_name': 'PreToolUse', 'session_id': sid, 'transcript_path': tp, 'cwd': '/tmp/work',
         'tool_name': name, 'tool_input': inp}
    if agent:
        d['agent_id'] = agent
    p = subprocess.Popen(['/usr/bin/python3', HOOK, '--hold'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=dict(os.environ, **(env or {})), cwd=T)
    p.stdin.write(json.dumps(d))
    p.stdin.close()
    return p


def wait_for(cond, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


state(limit_credits_all=True, limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})
open(LOG, 'w').close()
usage(five=85)
p = start_hold(S1, TP1)
time.sleep(2)
row = peek().get('limit_pauses', {}).get(S1, {})
check('--hold blocks while held (still running after 2 s)', p.poll() is None)
check('... with a row: sid, mode hold, at 80, percent 85, what hold, its pid',
      row.get('sid') == S1 and row.get('mode') == 'hold' and row.get('at') == 80 and row.get('percent') == 85
      and row.get('what') == 'hold' and row.get('pid') == p.pid, row)
check('log: wait line, no model calls', 'wait   11111111 at 80%: the 5-hour limit is at 85%' in logtext(), logtext())
usage(five=70)
check('usage under 80% -> the hook ends with no output', wait_for(lambda: p.poll() is not None, 5) and p.stdout.read() == '')
check('... the row is gone', S1 not in peek().get('limit_pauses', {}))
check('log: resume line', 'resume 11111111 the 5-hour limit is under 80%, after 0 min' in logtext(), logtext())
r = run(['wait', S1])
check('then the wait command prints GO ON at once', r.stdout.startswith('GO ON: every usage limit is under 80%'), r.stdout)

# an agent's own tool call (not the wait) is held in the hook too, and goes on when the hold ends
open(LOG, 'w').close()
usage(five=85)
pe = start_hold(S1, TP1, 'agentE', tool=('Edit', {'file_path': '/tmp/x'}))
time.sleep(1.5)
row = peek().get('limit_pauses', {}).get(S1 + '/agentE', {})
check('--hold: an agent\'s Edit call is held in the hook', pe.poll() is None and row.get('agent') == 'agentE'
      and row.get('what') == 'hold', row)
check('log: the agent\'s hold line', 'hold   11111111/agentE at 80%: the 5-hour limit is at 85%' in logtext()
      and '(Edit)' in logtext(), logtext())
usage(five=60)
check('... and goes on (no output: the Edit runs) under 80%', wait_for(lambda: pe.poll() is not None, 5)
      and pe.stdout.read() == '' and S1 + '/agentE' not in peek().get('limit_pauses', {}))
pm = start_hold(S1, TP1, None, tool=('Edit', {'file_path': '/tmp/x'}))
usage(five=85)
check('--hold: the session\'s own Edit call is not held here (it gets the visible wait)',
      wait_for(lambda: pm.poll() is not None, 3))
state(limit_credits_all=True)
pf = start_hold(S1, TP1, 'agentF', tool=('Edit', {'file_path': '/tmp/x'}))
check('--hold: an agent of a follow session exits at once', wait_for(lambda: pf.poll() is not None, 3))
state(limit_credits_all=True, limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})

# two agents of one session: each its own row; one ending keeps the other
usage(five=85)
pa, pb = start_hold(S1, TP1, 'agentA'), start_hold(S1, TP1, 'agentB')
check('two agents hold: two rows', wait_for(lambda: {S1 + '/agentA', S1 + '/agentB'} <= set(peek().get('limit_pauses', {})), 5),
      peek().get('limit_pauses'))
check('... rows carry the agent id', peek()['limit_pauses'].get(S1 + '/agentA', {}).get('agent') == 'agentA')
pa.send_signal(signal.SIGTERM)
pa.wait(5)
check('one agent stopped (SIGTERM): only its row goes', wait_for(lambda: S1 + '/agentA' not in peek().get('limit_pauses', {}), 5)
      and S1 + '/agentB' in peek().get('limit_pauses', {}), peek().get('limit_pauses'))
check('log: end line for the stopped agent', 'end    11111111/agentA hold ended: the turn was stopped' in logtext(), logtext())
pb.send_signal(signal.SIGTERM)
pb.wait(5)

# a phrase typed while it holds (the transcript's queue): "no credits 90" at 85% ends it
p = start_hold(S1, TP1)
time.sleep(1)
with open(TP1, 'a') as f:
    f.write(json.dumps({'type': 'queue-operation', 'operation': 'enqueue', 'content': 'no credits 90'}) + '\n')
check('typed "no credits 90" during the hold: it ends', wait_for(lambda: p.poll() is not None, 5))
check('... the setting is now 90 (typed)', lh.mode_of(peek(), S1, '') == ('hold', 90) and
      'mode   11111111 never use credits; hold at 90% (typed)' in logtext(), logtext())
lh.set_mode(S1, '', 'hold', 80, 'command')

# "use credits" typed in the Claude app (server events)
state(limit_credits_all=True, limit_modes={C2: {'mode': 'hold', 'at': 80, 'sid': S2, 'cse': C2, 'set_at': 1}},
      sessions={C2: {'title': 'Site map plan', 'transcript': TP2}})
p = start_hold(S2, TP2, env={'CLAUDE_CODE_BRIDGE_SESSION_ID': 'session_01TestSessionTwo', 'CLAUDE_CODE_SESSION_ID': S2})
time.sleep(1)
json.dump({'data': [{'source': 'client', 'event_type': 'user', 'payload': {
    'server_received_wall_ms': int(time.time() * 1000), 'message': {'content': 'credits ok'}}}]}, open(EVENTS, 'w'))
check('"credits ok" sent from the app (server events) during the hold: it ends', wait_for(lambda: p.poll() is not None, 6))
check('... always use credits now', lh.mode_of(peek(), S2, C2) == ('credits', None))
json.dump({'data': []}, open(EVENTS, 'w'))

# the menu: credits for this session (limit_credits), and a setting change
state(limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})
p = start_hold(S1, TP1)
time.sleep(1)
with lh.state() as st_:
    st_['limit_credits'] = {S1: time.time() + 3600}
check('Use credits clicked in the menu: the hold ends', wait_for(lambda: p.poll() is not None, 5))
state(limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})
p = start_hold(S1, TP1)
time.sleep(1)
with lh.state() as st_:
    st_['limit_modes'][S1] = {'mode': 'hold', 'at': 90, 'sid': S1, 'set_at': time.time()}
check('the menu raises the hold to 90%: it ends at 85%', wait_for(lambda: p.poll() is not None, 5))
r = run(['wait', S1])
check('... GO ON says why', r.stdout.startswith('GO ON: every usage limit is under 90%'), r.stdout)

# the turn is stopped: the interrupt shows in the transcript
state(limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})
p = start_hold(S1, TP1)
time.sleep(1)
with open(TP1, 'a') as f:
    f.write(json.dumps({'type': 'user', 'message': {'content': [{'type': 'text', 'text': '[Request interrupted by user for tool use]'}]}}) + '\n')
check('the turn is stopped (interrupt in the transcript): the hook ends and drops its row',
      wait_for(lambda: p.poll() is not None, 5) and S1 not in peek().get('limit_pauses', {}))

# a reset passes in an old read: it ends at the reset
usage(five=85, five_reset=3)
p = start_hold(S1, TP1)
check('the reset time passes: the hold ends by itself', wait_for(lambda: p.poll() is not None, 10))

# a follow-the-menu wait is left to the command, as before
state()
usage(five=100)
p = start_hold(S3, TP3)
check('--hold leaves a follow-the-menu wait to the command (exits at once)', wait_for(lambda: p.poll() is not None, 3))

# ---- the command's own loop (the fallback) -------------------------------------------------------------------
print('-- claude-limit-wait')
state(limit_modes={S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}})
usage(five=85)
r = run(['wait', S1], env={'STTARK_LIMIT_CHUNK': '2'})
out = r.stdout.splitlines()
check('wait command in hold mode: holding line, then WAIT AGAIN after its chunk',
      out and out[0].startswith('Holding at 80%: the 5-hour limit is at 85%.') and out[-1].startswith('WAIT AGAIN: still holding at 80%'),
      r.stdout)
state()
usage(five=100)
r = run(['wait', S3], env={'STTARK_LIMIT_CHUNK': '1'})
check('wait command at the limit (follow): as before', r.stdout.startswith('Waiting for the 5-hour usage limit to reset at')
      and 'WAIT AGAIN: still at the 5-hour usage limit' in r.stdout, r.stdout)
r = run(['wait', S3 + '/agentX'], env={'STTARK_LIMIT_CHUNK': '1'})
check('an agent\'s wait (<sid>/<agent>) runs too', 'WAIT AGAIN' in r.stdout, r.stdout)
usage(five=50)
r = run(['wait', S3])
check('wait command under the limit: GO ON at once', r.stdout.startswith('GO ON: the usage limit is clear.'), r.stdout)

# ---- install-hooks.py in a temp HOME ---------------------------------------------------------------------------
print('-- install-hooks.py')
os.makedirs(os.path.join(HOME, '.claude'), exist_ok=True)
json.dump({'hooks': {}}, open(os.path.join(HOME, '.claude/settings.json'), 'w'))
r = subprocess.run(['/usr/bin/python3', INSTALL], capture_output=True, text=True, env=os.environ)
s = json.load(open(os.path.join(HOME, '.claude/settings.json')))
pre = s['hooks'].get('PreToolUse', [])
hold = [g for g in pre if not g.get('matcher') and any(h['command'].endswith('limit-hook.py" --hold') for h in g['hooks'])]
plain = [g for g in pre if any(h['command'].endswith('limit-hook.py"') for h in g['hooks'])]
check('install: the --hold entry (every tool, 8 days) and the plain entry (60 s)',
      len(hold) == 1 and hold[0]['hooks'][0]['timeout'] == 8 * 24 * 3600 and len(plain) == 1 and plain[0]['hooks'][0]['timeout'] == 60,
      json.dumps(pre)[:400])
for name in ('claude-limit-wait', 'claude-limit-mode'):
    p_ = os.path.join(HOME, '.local/bin', name)
    check(f'install: ~/.local/bin/{name} points at limit-hook.py', os.path.islink(p_) and os.path.realpath(p_) == os.path.realpath(HOOK))
r2 = subprocess.run(['/usr/bin/python3', INSTALL], capture_output=True, text=True, env=os.environ)
check('install again: unchanged', r2.stdout.strip() == 'unchanged', r2.stdout)
r3 = subprocess.run(['/usr/bin/python3', INSTALL, '--status'], capture_output=True, text=True, env=os.environ)
check('--status reports limit', json.loads(r3.stdout).get('limit') is True, r3.stdout)
subprocess.run(['/usr/bin/python3', INSTALL, '--remove'], capture_output=True, text=True, env=os.environ)
s = json.load(open(os.path.join(HOME, '.claude/settings.json')))
check('--remove: no limit hooks and no links left', 'limit-hook.py' not in json.dumps(s)
      and not os.path.lexists(os.path.join(HOME, '.local/bin/claude-limit-mode'))
      and not os.path.lexists(os.path.join(HOME, '.local/bin/claude-limit-wait')))

# ---- a test never touches the usage cache ------------------------------------------------------------------------
check('STTARK_LIMIT_TEST: no usage.json cache was read or written', not os.path.exists(os.path.join(KIT, 'usage.json')))
leftover = subprocess.run(['pgrep', '-f', HOOK], capture_output=True, text=True).stdout.split()
check('no hook process left running', not leftover, leftover)

shutil.rmtree(T)
print(f'\n{len(failed)} failed' if failed else '\nall passed')
sys.exit(1 if failed else 0)
