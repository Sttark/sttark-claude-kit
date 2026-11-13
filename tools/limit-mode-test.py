#!/usr/bin/python3
"""Tests of each session's usage setting (Follow the menu, Always use credits, Never use credits; hold at N%)
in Resources/hooks/limit-hook.py, all on copies: a temp state folder and log, a stand-in usage file, stand-in
server events, and a temp HOME for transcripts, ~/.local/bin and install-hooks.py. Nothing real is read or
written, and no model is called. Prints each case; exits 1 if any fails.
Run: /usr/bin/python3 tools/limit-mode-test.py"""
import datetime, fcntl, importlib.util, json, os, shutil, signal, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.normpath(os.path.join(HERE, '../Resources/hooks/limit-hook.py'))
INSTALL = os.path.normpath(os.path.join(HERE, '../Resources/hooks/install-hooks.py'))
T = tempfile.mkdtemp(prefix='limit-mode-test-')
HOME = os.path.join(T, 'home')
KIT = os.path.join(T, 'kit')
LOG = os.path.join(T, 'log')
USAGE = os.path.join(T, 'usage-standin.json')
EVENTS = os.path.join(T, 'events.json')
POLLS = os.path.join(T, 'polls')
CLAIM_WAIT = 0.6   # seconds the plain hook waits for the --hold entry's answer (3 in use)
for k in [k for k in os.environ if k.startswith('CLAUDE')]:
    del os.environ[k]   # no real session's ids leak in
os.environ.update(HOME=HOME, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_LIMIT_TEST=USAGE,
                  STTARK_LIMIT_EVENTS=EVENTS, STTARK_LIMIT_TICK='0.3', STTARK_LIMIT_CLAIM_WAIT=str(CLAIM_WAIT))
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
    tmp = USAGE + '.tmp'
    json.dump(u, open(tmp, 'w'))
    os.replace(tmp, USAGE)
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


def run(args, stdin=None, env=None, timeout=30):
    e = dict(os.environ, **(env or {}))
    r = subprocess.run(['/usr/bin/python3', HOOK] + args, input=stdin, capture_output=True, text=True, env=e,
                       timeout=timeout, cwd=T)
    return r


def hook(event, sid, tp, extra=None, args=(), env=None):
    d = {'hook_event_name': event, 'session_id': sid, 'transcript_path': tp, 'cwd': '/tmp/work'}
    d.update(extra or {})
    r = run(list(args), stdin=json.dumps(d), env=env)
    return json.loads(r.stdout) if r.stdout.strip() else None


def timed(fn):
    t0 = time.time()
    r = fn()
    return r, time.time() - t0


def deny(o):
    return (o or {}).get('hookSpecificOutput', {}).get('permissionDecisionReason', '') if o else ''


def claim_as(key, kind):
    """Stand in for the --hold entry's answer for a call or a message."""
    os.makedirs(lh.HOLDS, exist_ok=True)
    with open(lh.claim_file(key), 'w') as f:
        f.write(f'{kind} {os.getpid()}')


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
HOLD80 = {S1: {'mode': 'hold', 'at': 80, 'sid': S1, 'set_at': 1}}

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
st = {'limit_modes': dict(HOLD80)}
check('follow, account without credits, 100% -> no hold', lh.hold_for(S1, '', TP1, usage(five=100, credits=False), {}) is None)
check('follow, credits spend limit reached, 100% -> no hold', lh.hold_for(S1, '', TP1, usage(five=100, spend=True), {}) is None)
h = lh.hold_for(S1, '', TP1, usage(five=85, credits=False), st)
check('hold 80, account without credits, 85% -> holds', bool(h) and h.at == 80 and h.percent == 85, h)
h = lh.hold_for(S1, '', TP1, usage(five=85), st)
check('hold line names 80% and the reset', h and lh.line(h).startswith('This session holds at 80% usage. I continue at'), h and lh.line(h))
# billable: a reply now would use usage credits
check('billable: 100% with credits on', lh.billable(usage(five=100), TP1))
check('not billable: 85%, 100% without credits, 100% at the spend limit',
      not lh.billable(usage(five=85), TP1) and not lh.billable(usage(five=100, credits=False), TP1)
      and not lh.billable(usage(five=100, spend=True), TP1))
check('billable: the Fable weekly at 100% only for a session on Fable',
      lh.billable(usage(scoped=100), TP3) and not lh.billable(usage(scoped=100), TP1))
# which limit and which reset
h = lh.hold_for(S1, '', TP1, usage(five=50, week=85), st)
check('hold 80: weekly at 85% holds, until the weekly reset', h and h.name == 'weekly' and h.percent == 85, h)
u = usage(five=90, week=81)
h = lh.hold_for(S1, '', TP1, u, st)
check('hold 80: both over 80 -> waits for the later (weekly) reset',
      h and h.name == 'weekly' and abs(h.until - lh.stamp(u['limits'][1]['resets_at'])) < 1, h)
h = lh.hold_for(S1, '', TP1, usage(five=95, week=85), st)
check('hold 80: the line names the weekly at its own 85%; the row\'s percent is the highest, 95',
      h and h.name == 'weekly' and h.percent == 85 and h.top == 95, h)
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
# an old one-time "use credits" (limit_credits, from an older Kit) never overrides the session's setting
stc = dict(st, limit_credits={S1: time.time() + 600, S1 + '/agent1': time.time() + 600})
check('hold 80 + an old limit_credits entry -> still holds', lh.hold_for(S1, '', TP1, usage(five=85), stc) is not None)

# ---- phrases ------------------------------------------------------------------------------------------------
print('-- phrases')
for text, want in (('no credits', ('hold', 80)), ('No credits.', ('hold', 80)), ('no credits 90', ('hold', 90)),
                   ('no credits 90%', ('hold', 90)), ('no credits at 70', ('hold', 70)), ('NO CREDITS 100', ('hold', 100)),
                   ('never use credits 85', ('hold', 85)), ('never use credits', ('hold', 80)),
                   ('credits ok', ('credits', None)), ('Credits OK!', ('credits', None)),
                   ('always use credits', ('credits', None)), ('follow the menu', ('follow', None)),
                   ('Follow the menu.', ('follow', None)), ('use credits', ('credits', None)), (' use  credits ', ('credits', None)),
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
check('session_cse: no ps needed when a setting names this session id', lh.session_cse(S2, s) == '')
fake_ps = os.path.join(T, 'fakebin')
os.makedirs(fake_ps)
with open(os.path.join(fake_ps, 'ps'), 'w') as f:
    f.write(f'#!/bin/sh\necho called >> "{T}/ps-calls"\necho "claude --session-id cse_01FromPs"\n')
os.chmod(os.path.join(fake_ps, 'ps'), 0o755)
saved_env = dict(os.environ)
os.environ.update(PATH=fake_ps + ':' + os.environ['PATH'], CLAUDE_PID='1', CLAUDE_CODE_SESSION_ID=S3)
st_ = {'limit_modes': {C2: {'mode': 'hold', 'at': 80, 'sid': S2, 'cse': C2, 'set_at': 1}},
       'sessions': {C2: {'transcript': TP2}, 'cse_01Third': {'transcript': TP3}}}
check('session_cse: another session with no setting: its cse from the app\'s list, no ps',
      lh.session_cse(S3, st_) == 'cse_01Third' and not os.path.exists(os.path.join(T, 'ps-calls')))
check('session_cse: ... not in the list either: no ps while every setting names its session id',
      lh.session_cse(S3, {'limit_modes': st_['limit_modes']}) == '' and not os.path.exists(os.path.join(T, 'ps-calls')))
check('session_cse: a setting with no session id (set in the menu early): then ps finds the cse',
      lh.session_cse(S3, {'limit_modes': {C2: {'mode': 'hold', 'at': 80, 'cse': C2, 'set_at': 1}}}) == 'cse_01FromPs'
      and os.path.exists(os.path.join(T, 'ps-calls')))
os.environ.clear()
os.environ.update(saved_env)
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
# a session known only by its cse: the log id is the 8 characters after cse_
lh.set_mode('', C2, 'hold', 75, 'menu')
check('log id for a session known only by its cse: the 8 characters after cse_',
      'mode   01TestSe never use credits; hold at 75% (menu)' in logtext(), logtext())
lh.set_mode('', C2, 'follow', None, 'menu')
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

# ---- what the menu writes (Swift's JSONSerialization: every number may come back as a float) -------------------
print('-- written by the menu')
SWIFT = os.path.join(T, 'swift-state.json')
with open(SWIFT, 'w') as f:   # as the app writes it: pretty-printed, numbers as floats
    f.write(json.dumps({
        'sessions': {C2: {'title': 'Site map plan', 'transcript': TP2, 'at': time.time()}},
        'limit_modes': {C2: {'mode': 'hold', 'at': 70.0, 'sid': S2, 'cse': C2, 'by': 'menu', 'title': 'Site map plan',
                             'set_at': time.time() - 5.25}},
        'limit_pauses': {S2 + '/toolu_swift': {'sid': S2, 'cse': C2, 'pid': float(os.getpid()), 'since': time.time() - 60.5,
                                               'until': time.time() + 3600.5, 'limit': '5-hour', 'mode': 'hold',
                                               'at': 70.0, 'percent': 85.0, 'what': 'hold', 'title': 'Site map plan'}},
        'limit_credits': {S1: time.time() + 3600.5}}, indent=2))
shutil.copy(SWIFT, os.path.join(KIT, 'state.json'))
s = peek()
check('a menu entry with a float percentage: hold at 70', lh.mode_of(s, S2, '') == ('hold', 70) and lh.mode_of(s, '', C2) == ('hold', 70))
h = lh.hold_for(S2, C2, TP2, usage(five=85), s)
check('... holds at 85%', h is not None and h.at == 70, h)
check('a row with a float pid counts as live', lh.others(s['limit_pauses'], 'other', S2, '') == [S2 + '/toolu_swift'])
check('an old "use credits" time is ignored', lh.hold_for(S1, '', TP1, usage(five=100), dict(s, limit_modes=HOLD80)) is not None)
r = run(['mode', '--list'])
check('claude-limit-mode --list reads it', '(22222222): never use credits; hold at 70% (set by menu' in r.stdout, r.stdout + r.stderr)
r = run(['mode', S2, 'credits'])
check('... and changes it', r.returncode == 0 and lh.mode_of(peek(), S2, C2) == ('credits', None), r.stdout + r.stderr)

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
state(limit_credits_all=True, limit_modes=dict(HOLD80))
check('held(): credits for every session: the account does not, the hold-80 session still does',
      not lh.held() and lh.held(S1, TP1, ''))

# ---- the plain hooks ---------------------------------------------------------------------------------------------
print('-- hooks')
state(limit_credits_all=True, limit_modes=dict(HOLD80))
open(LOG, 'w').close()
usage(five=85)
o, secs = timed(lambda: hook('PreToolUse', S1, TP1, {'tool_name': 'Edit', 'tool_input': {}, 'tool_use_id': 'toolu_m1'}))
check('PreToolUse: hold-80 session at 85% (no credits yet) is stopped at once with the line and the wait',
      'holds at 80% usage' in deny(o) and 'limit-hook.py" wait ' + S1 in deny(o) and secs < CLAIM_WAIT + 1.5, (o, secs))
check('log: hold line, with the tool', 'limit  hold   11111111 at 80%: the 5-hour limit is at 85%, until' in logtext()
      and '(Edit)' in logtext(), logtext())
AG = {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'agent_id': 'agentA1'}
claim_as('toolu_a1', 'holding')
o, secs = timed(lambda: hook('PreToolUse', S1, TP1, dict(AG, tool_use_id='toolu_a1')))
check('PreToolUse: an agent call that --hold holds ("holding"): no deny', o is None and secs < 2, (o, secs))
check('... the plain hook removes the claim once read', not os.path.exists(lh.claim_file('toolu_a1')))
o, secs = timed(lambda: hook('PreToolUse', S1, TP1, dict(AG, tool_use_id='toolu_a2')))
check('PreToolUse: no answer from --hold (a session without it): the agent is stopped with its own wait, as before',
      ('wait ' + S1 + '/agentA1') in deny(o) and secs >= CLAIM_WAIT, (o, secs))
claim_as('toolu_a3', 'free')
o, secs = timed(lambda: hook('PreToolUse', S1, TP1, dict(AG, tool_use_id='toolu_a3')))
check('PreToolUse: --hold answers "free": the agent is stopped at once', bool(deny(o)) and secs < CLAIM_WAIT + 1, (o, secs))
claim_as('toolu_a4', 'deciding')
threading.Timer(1.2, lambda: claim_as('toolu_a4', 'holding')).start()
o, secs = timed(lambda: hook('PreToolUse', S1, TP1, dict(AG, tool_use_id='toolu_a4')))
check('PreToolUse: "deciding", then "holding" 1.2 s later: the plain hook waits for it, no deny', o is None and secs >= 1.1, (o, secs))
# a reply now would use credits: the session's own call is left to --hold
usage(five=100)
claim_as('toolu_m2', 'holding')
o = hook('PreToolUse', S1, TP1, {'tool_name': 'Edit', 'tool_input': {}, 'tool_use_id': 'toolu_m2'})
check('PreToolUse: at 100% with credits on, the session\'s own call held by --hold: no deny, no reply', o is None, o)
o = hook('PreToolUse', S1, TP1, {'tool_name': 'Edit', 'tool_input': {}, 'tool_use_id': 'toolu_m3'})
check('PreToolUse: ... a session without the --hold entry is stopped with the line, as before', 'holds at 80% usage' in deny(o), o)
usage(five=100, credits=False)
o, secs = timed(lambda: hook('PreToolUse', S1, TP1, {'tool_name': 'Edit', 'tool_input': {}, 'tool_use_id': 'toolu_m4'}))
check('PreToolUse: 100% without credits on the account: no credits at stake, stopped with the line at once',
      'holds at 80% usage' in deny(o) and secs < CLAIM_WAIT + 1, (o, secs))
state(limit_modes={S1: {'mode': 'hold', 'at': 100, 'sid': S1, 'set_at': 1}})
usage(five=100)
claim_as('toolu_a5', 'holding')
check('PreToolUse: an agent of a hold-100 session at 100%, held by --hold: no deny',
      hook('PreToolUse', S1, TP1, dict(AG, tool_use_id='toolu_a5')) is None)
state(limit_modes={})
o, secs = timed(lambda: hook('PreToolUse', S1, TP1, dict(AG, tool_use_id='toolu_a6')))
check('PreToolUse: an agent of a follow session at the limit (credits off in the menu) is stopped at once with its own wait',
      ('wait ' + S1 + '/agentA1') in deny(o) and secs < CLAIM_WAIT + 1, (o, secs))
state(limit_credits_all=True, limit_modes=dict(HOLD80))
usage(five=85)
check('PreToolUse: the wait command itself runs',
      hook('PreToolUse', S1, TP1, {'tool_name': 'Bash', 'tool_input': {'command': 'claude-limit-wait ' + S1}}) is None)
for cmd in ('claude-limit-mode . credits', 'claude-limit-mode "Site map plan" hold 90', '~/.local/bin/claude-limit-mode follow 2>&1',
            f'/usr/bin/python3 "{HOOK}" mode . hold 90', 'claude-limit-mode --list'):
    check(f'PreToolUse: a held session may run `{cmd[:40]}`',
          hook('PreToolUse', S1, TP1, {'tool_name': 'Bash', 'tool_input': {'command': cmd}}) is None)
for cmd in ('claude-limit-mode . credits; rm -rf x', 'claude-limit-mode . credits && make', 'echo $(claude-limit-mode)',
            'rm;/x/claude-limit-mode', 'claude-limit-mode `make`'):
    check(f'PreToolUse: ... but not `{cmd}`', bool(deny(hook('PreToolUse', S1, TP1, {'tool_name': 'Bash', 'tool_input': {'command': cmd}}))))
check('PreToolUse: another session (follow) goes on with credits', hook('PreToolUse', S3, TP3, {'tool_name': 'Edit', 'tool_input': {}}) is None)
# messages
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'fix the map', 'prompt_id': 'p1'})
ctx = o and o['hookSpecificOutput']['additionalContext']
check('message while held at 85%: goes through with the wait instruction', ctx and 'holds at 80% usage' in ctx
      and 'answer the message' in ctx, ctx)
o = hook('UserPromptSubmit', S1, TP1, {'prompt': '<task-notification>\n<task-id>x</task-id>', 'prompt_id': 'p2'})
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
state(limit_modes=dict(HOLD80))
open(LOG, 'w').close()
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'use credits'})
check('typed "use credits" in a hold session at 85%: set to Always use credits, said, undo pointed at the menu',
      lh.mode_of(peek(), S1, '') == ('credits', None) and 'limit_credits' not in peek()
      and 'always use credits' in o['hookSpecificOutput']['additionalContext']
      and 'At the usage limit menu' in o['hookSpecificOutput']['additionalContext'], o)
hook('UserPromptSubmit', S1, TP1, {'prompt': 'use credits'})
check('"use credits" again: no change, logged once', logtext().count('mode   11111111 always use credits') == 1, logtext())
state(limit_modes=dict(HOLD80))
# a reply now would use credits: the message is left to --hold
state(limit_credits_all=True, limit_modes=dict(HOLD80))
usage(five=100)
claim_as('prompt-p7', 'holding')
check('a message at 100% that --hold holds: nothing added (Claude gets it as it is, after the hold)',
      hook('UserPromptSubmit', S1, TP1, {'prompt': 'fix the map', 'prompt_id': 'p7'}) is None)
claim_as('prompt-p8', 'holding')
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'no credits 90', 'prompt_id': 'p8'})
ctx = o and o['hookSpecificOutput']['additionalContext']
check('typed "no credits 90" at 100%, held by --hold: the change is said, with no wait instruction',
      ctx and 'hold at 90%' in ctx and 'Say so in one line, then go on' in ctx and ' wait ' not in ctx, ctx)
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'fix the map', 'prompt_id': 'p9'})
check('a message at 100% in a session without the --hold entry: the instruction, as before',
      o and 'holds at 90% usage' in o['hookSpecificOutput']['additionalContext'], o)

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
                  (['zzzzzzzz', 'credits'], 'no such session'), (['abc', 'credits'], 'too short to be a start'),
                  (['12345678-1234-1234-1234-123456789abc', 'hold', '80'], 'a session id this Mac has never seen'),
                  (['cse_01NoSuchSessionAnywhereHere', 'credits'], 'a cse id this Mac has never seen')):
    r = run(['mode'] + args)
    check(f'mode {" ".join(args)} -> exit 2 ({why})', r.returncode == 2 and r.stderr.startswith('claude-limit-mode: '),
          (r.returncode, r.stdout, r.stderr))
check('... and nothing was stored for them', not any(k.startswith(('12345678', 'cse_01NoSuch')) for k in peek().get('limit_modes', {})))
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

# ---- the --hold entry: holds with no model calls, ends at under N -----------------------------------------------
print('-- the --hold entry')


def start_hold(sid, tp, agent=None, env=None, tool=None, tuid=None, prompt=None, prompt_id=None, extra_args=()):
    """Start the --hold entry as Claude Code would, for a tool call (by default the session's wait command) or,
    with prompt, for a message."""
    d = {'session_id': sid, 'transcript_path': tp, 'cwd': '/tmp/work'}
    if prompt is not None:
        d.update(hook_event_name='UserPromptSubmit', prompt=prompt)
        if prompt_id:
            d['prompt_id'] = prompt_id
    else:
        name, inp = tool or ('Bash', {'command': 'claude-limit-wait ' + sid + ('/' + agent if agent else '')})
        d.update(hook_event_name='PreToolUse', tool_name=name, tool_input=inp)
        if tuid:
            d['tool_use_id'] = tuid
    if agent:
        d['agent_id'] = agent
    p = subprocess.Popen(['/usr/bin/python3', HOOK, '--hold'] + list(extra_args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ, **(env or {})), cwd=T)
    p.stdin.write(json.dumps(d))
    p.stdin.close()
    return p


def wait_for(cond, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def rows():
    return peek().get('limit_pauses', {})


def stop(*ps):
    for p in ps:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
            p.wait(5)


EDIT = ('Edit', {'file_path': '/tmp/x'})
state(limit_credits_all=True, limit_modes=dict(HOLD80))
open(LOG, 'w').close()
usage(five=85)
p = start_hold(S1, TP1, tuid='toolu_w1')
time.sleep(2)
row = rows().get(S1 + '/toolu_w1', {})
check('the session\'s wait command: --hold blocks it while held (still running after 2 s)', p.poll() is None)
check('... with a row keyed <sid>/<tool_use_id>: sid, mode hold, at 80, percent 85, what hold, its pid, no agent',
      row.get('sid') == S1 and row.get('mode') == 'hold' and row.get('at') == 80 and row.get('percent') == 85
      and row.get('what') == 'hold' and row.get('pid') == p.pid and 'agent' not in row, rows())
check('log: wait line, no model calls', 'wait   11111111 at 80%: the 5-hour limit is at 85%' in logtext(), logtext())
usage(five=70)
check('usage under 80% -> the hook ends with no output', wait_for(lambda: p.poll() is not None, 5) and p.stdout.read() == '')
check('... the row is gone', S1 + '/toolu_w1' not in rows())
check('log: resume line', 'resume 11111111 the 5-hour limit is under 80%, after 0 min' in logtext(), logtext())
r = run(['wait', S1])
check('then the wait command prints GO ON at once', r.stdout.startswith('GO ON: every usage limit is under 80%'), r.stdout)

# no limit of its own: the command's 9-minute chunk does not end a hold in the hook
usage(five=85)
p = start_hold(S1, TP1, tuid='toolu_w2', env={'STTARK_LIMIT_CHUNK': '1'})
time.sleep(2.5)
check('--hold has no time limit of its own (still holding after 2.5 s with a 1-second command chunk)', p.poll() is None)
usage(five=60)
check('... and ends when the hold ends', wait_for(lambda: p.poll() is not None, 5))

# an agent's own tool call (not the wait) is held in the hook too, and goes on when the hold ends
open(LOG, 'w').close()
usage(five=85)
pe = start_hold(S1, TP1, 'agentE', tool=EDIT, tuid='toolu_e1')
check('an agent\'s Edit call is held in the hook', wait_for(lambda: S1 + '/toolu_e1' in rows(), 5) and pe.poll() is None
      and rows()[S1 + '/toolu_e1'].get('agent') == 'agentE' and rows()[S1 + '/toolu_e1'].get('what') == 'hold', rows())
check('... its claim says holding', wait_for(lambda: open(lh.claim_file('toolu_e1')).read().startswith('holding'), 3))
check('log: the agent\'s hold line, with its tool', 'hold   11111111/agentE at 80%: the 5-hour limit is at 85%' in logtext()
      and '(Edit)' in logtext(), logtext())
usage(five=60)
check('... and goes on (no output: the Edit runs) under 80%', wait_for(lambda: pe.poll() is not None, 5)
      and pe.stdout.read() == '' and S1 + '/toolu_e1' not in rows())
check('... its claim is gone', not os.path.exists(lh.claim_file('toolu_e1')))

# the two hooks of one agent call, run together as Claude Code runs them
usage(five=85)
d = {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'agent_id': 'agentQ', 'tool_use_id': 'toolu_pair'}
ph = start_hold(S1, TP1, 'agentQ', tool=('Bash', {'command': 'ls'}), tuid='toolu_pair')
o, secs = timed(lambda: hook('PreToolUse', S1, TP1, d))
check('both hooks of one agent call: the plain one adds nothing, --hold holds', o is None and ph.poll() is None, (o, secs))
usage(five=60)
check('... and the call goes on when the hold ends', wait_for(lambda: ph.poll() is not None, 5))

# the session's own Edit at 85%: no credits at stake, so --hold leaves it to the plain hook (the visible line)
usage(five=85)
pm = start_hold(S1, TP1, None, tool=EDIT, tuid='toolu_own85')
check('the session\'s own Edit call at 85% is not held here (it gets the line and the wait)',
      wait_for(lambda: pm.poll() is not None, 3) and open(lh.claim_file('toolu_own85')).read().startswith('free'))

# agents of a follow session: --hold leaves them to the plain hook
state(limit_credits_all=True)
usage(five=85)
pf = start_hold(S1, TP1, 'agentF', tool=EDIT, tuid='toolu_f1')
check('an agent of a follow session at 85% (credits on in the menu): --hold exits at once', wait_for(lambda: pf.poll() is not None, 3))
state()
usage(five=100)
pf = start_hold(S1, TP1, 'agentF', tool=EDIT, tuid='toolu_f2')
check('an agent of a follow session at 100% (credits off in the menu): --hold exits at once; the plain hook stops it',
      wait_for(lambda: pf.poll() is not None, 3) and S1 + '/toolu_f2' not in rows())
usage(five=100, credits=False)
pf = start_hold(S1, TP1, 'agentF', tool=EDIT, tuid='toolu_f3')
check('... and at 100% on an account without credits', wait_for(lambda: pf.poll() is not None, 3))

# a reply now would use credits: the session's own call, held with no reply at all
state(limit_credits_all=True, limit_modes=dict(HOLD80))
open(LOG, 'w').close()
usage(five=100)
ps = start_hold(S1, TP1, None, tool=EDIT, tuid='toolu_s1')
o, secs = timed(lambda: hook('PreToolUse', S1, TP1, {'tool_name': 'Edit', 'tool_input': {}, 'tool_use_id': 'toolu_s1'}))
check('at 100% with credits on: the session\'s own Edit is held in --hold, and the plain hook adds nothing (no reply)',
      o is None and ps.poll() is None and S1 + '/toolu_s1' in rows(), (o, rows()))
check('log: the hold line says no reply', 'hold   11111111 at 80%: the 5-hour limit is at 100%' in logtext()
      and '(Edit; no reply: one now would use credits)' in logtext(), logtext())
usage(five=90)
time.sleep(1.5)
check('... once held with no reply, it stays held at 90% (still over 80, no longer charged)', ps.poll() is None)
usage(five=60)
check('... and goes on under 80%', wait_for(lambda: ps.poll() is not None, 5) and ps.stdout.read() == ''
      and S1 + '/toolu_s1' not in rows())

# a message at 100%: held in the --hold entry until the hold ends
usage(five=100)
pp = start_hold(S1, TP1, prompt='fix the map', prompt_id='pp1')
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'fix the map', 'prompt_id': 'pp1'})
check('a message at 100%: --hold holds it, the plain hook adds nothing', o is None and pp.poll() is None
      and wait_for(lambda: S1 + '/prompt-pp1' in rows(), 3), (o, rows()))
check('log: the hold line for a message', '(message; no reply: one now would use credits)' in logtext(), logtext())
usage(five=40)
check('... and it goes to Claude when the hold ends', wait_for(lambda: pp.poll() is not None, 5) and pp.stdout.read() == '')
# a phrase that ends the hold goes through at once
usage(five=100)
pp = start_hold(S1, TP1, prompt='credits ok', prompt_id='pp2')
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'credits ok', 'prompt_id': 'pp2'})
check('"credits ok" sent at 100%: --hold lets it through at once, and Claude is told the change',
      wait_for(lambda: pp.poll() is not None, 3) and lh.mode_of(peek(), S1, '') == ('credits', None)
      and 'always use credits' in o['hookSpecificOutput']['additionalContext'], o)
check('... logged once', logtext().count('mode   11111111 always use credits (typed)') == 1, logtext())
# a phrase that starts a hold while a reply would use credits: held at once, with no reply
state(limit_credits_all=True)
pp = start_hold(S1, TP1, prompt='no credits', prompt_id='pp3')
o = hook('UserPromptSubmit', S1, TP1, {'prompt': 'no credits', 'prompt_id': 'pp3'})
ctx = o and o['hookSpecificOutput']['additionalContext']
check('"no credits" sent at 100% in a follow session: set, and the message is held (no wait instruction)',
      lh.mode_of(peek(), S1, '') == ('hold', 80) and pp.poll() is None and ctx and ' wait ' not in ctx, (ctx, rows()))
usage(five=50)
check('... it goes on under 80%', wait_for(lambda: pp.poll() is not None, 5))

# two agents of one session, and two parallel calls of one agent: each call its own row
state(limit_credits_all=True, limit_modes=dict(HOLD80))
open(LOG, 'w').close()
usage(five=85)
pa = start_hold(S1, TP1, 'agentA', tool=EDIT, tuid='toolu_A')
pb = start_hold(S1, TP1, 'agentB', tool=EDIT, tuid='toolu_B')
pb2 = start_hold(S1, TP1, 'agentB', tool=EDIT, tuid='toolu_B2')
check('two agents, one of them with two calls: three rows', wait_for(
      lambda: {S1 + '/toolu_A', S1 + '/toolu_B', S1 + '/toolu_B2'} <= set(rows()), 5), rows())
check('... rows carry their agent id', rows()[S1 + '/toolu_B2'].get('agent') == 'agentB')
time.sleep(0.5)
check('log: one hold line per agent, not per call', logtext().count('hold   11111111/agentB') == 1
      and logtext().count('hold   11111111/agentA') == 1, logtext())
pb.send_signal(signal.SIGTERM)
pb.wait(5)
check('agent B\'s first call stopped: only its row goes; B\'s other call keeps its row',
      wait_for(lambda: S1 + '/toolu_B' not in rows(), 5) and S1 + '/toolu_B2' in rows() and S1 + '/toolu_A' in rows(), rows())
check('... and no end line yet (B still holds)', 'end    11111111/agentB' not in logtext(), logtext())
pb2.send_signal(signal.SIGTERM)
pb2.wait(5)
check('log: end line once B\'s last call stops', logtext().count('end    11111111/agentB hold ended: the turn was stopped') == 1, logtext())
usage(five=60)
check('agent A goes on when the hold ends, with one resume line',
      wait_for(lambda: pa.poll() is not None, 5) and logtext().count('resume 11111111/agentA') == 1, logtext())

# a phrase typed while it holds (the transcript's queue): "no credits 90" at 85% ends it
usage(five=85)
p = start_hold(S1, TP1, tuid='toolu_q1')
time.sleep(1)
with open(TP1, 'a') as f:
    f.write(json.dumps({'type': 'queue-operation', 'operation': 'enqueue', 'content': 'no credits 90'}) + '\n')
check('typed "no credits 90" during the hold: it ends', wait_for(lambda: p.poll() is not None, 5))
check('... the setting is now 90 (typed)', lh.mode_of(peek(), S1, '') == ('hold', 90) and
      'mode   11111111 never use credits; hold at 90% (typed)' in logtext(), logtext())
lh.set_mode(S1, '', 'hold', 80, 'command')

# "use credits" queued while two calls of the session hold: both end, it is logged once
open(LOG, 'w').close()
pa, pb = start_hold(S1, TP1, tuid='toolu_c1'), start_hold(S1, TP1, 'agentC', tool=EDIT, tuid='toolu_c2')
wait_for(lambda: {S1 + '/toolu_c1', S1 + '/toolu_c2'} <= set(rows()), 5)
with open(TP1, 'a') as f:
    f.write(json.dumps({'type': 'queue-operation', 'operation': 'enqueue', 'content': 'use credits'}) + '\n')
check('"use credits" queued during two holds: both end', wait_for(lambda: pa.poll() is not None and pb.poll() is not None, 6))
check('... and the change to always use credits is logged once', logtext().count('mode   11111111 always use credits') == 1, logtext())
check('... and is the session\'s setting now', lh.mode_of(peek(), S1, '') == ('credits', None))
with lh.state() as st_:
    st_['limit_modes'] = dict(HOLD80)

# "credits ok" typed in the Claude app (server events), checked by one held process of the session
state(limit_credits_all=True, limit_modes={C2: {'mode': 'hold', 'at': 80, 'sid': S2, 'cse': C2, 'set_at': 1}},
      sessions={C2: {'title': 'Site map plan', 'transcript': TP2}})
env2 = {'CLAUDE_CODE_BRIDGE_SESSION_ID': 'session_01TestSessionTwo', 'CLAUDE_CODE_SESSION_ID': S2, 'STTARK_LIMIT_POLLS': POLLS}
p1 = start_hold(S2, TP2, env=env2, tuid='toolu_p1')
p2 = start_hold(S2, TP2, 'agentP', env=env2, tool=EDIT, tuid='toolu_p2')
time.sleep(3.5)
pids = set(open(POLLS).read().split()) if os.path.exists(POLLS) else set()
check('two holds of one session: one process checks the server', len(pids) == 1 and pids <= {str(p1.pid), str(p2.pid)}, pids)
json.dump({'data': [{'source': 'client', 'event_type': 'user', 'payload': {
    'server_received_wall_ms': int(time.time() * 1000), 'message': {'content': 'credits ok'}}}]}, open(EVENTS, 'w'))
check('"credits ok" sent from the app (server events) during the hold: both end',
      wait_for(lambda: p1.poll() is not None and p2.poll() is not None, 6))
check('... always use credits now', lh.mode_of(peek(), S2, C2) == ('credits', None))
json.dump({'data': []}, open(EVENTS, 'w'))

# the menu: an old limit_credits entry does nothing; Always use credits picked in the menu ends the hold
state(limit_modes=dict(HOLD80))
p = start_hold(S1, TP1, tuid='toolu_m5')
time.sleep(1)
with lh.state() as st_:
    st_['limit_credits'] = {S1: time.time() + 3600}
time.sleep(1.5)
check('an old limit_credits entry: the hold goes on', p.poll() is None)
lh.set_mode(S1, '', 'credits', by='menu')
check('Always use credits picked in the menu: the hold ends', wait_for(lambda: p.poll() is not None, 5))
check('... and the old entry is dropped and logged', 'limit_credits' not in peek() and 'dropped the old one-time' in logtext(), logtext())
state(limit_modes=dict(HOLD80))
p = start_hold(S1, TP1, tuid='toolu_m6')
time.sleep(1)
with lh.state() as st_:
    st_['limit_modes'][S1] = {'mode': 'hold', 'at': 90, 'sid': S1, 'set_at': time.time()}
check('the menu raises the hold to 90%: it ends at 85%', wait_for(lambda: p.poll() is not None, 5))
r = run(['wait', S1])
check('... GO ON says why', r.stdout.startswith('GO ON: every usage limit is under 90%'), r.stdout)

# the turn is stopped: the interrupt shows in the transcript
state(limit_modes=dict(HOLD80))
p = start_hold(S1, TP1, tuid='toolu_i1')
time.sleep(1)
with open(TP1, 'a') as f:
    f.write(json.dumps({'type': 'user', 'message': {'content': [{'type': 'text', 'text': '[Request interrupted by user for tool use]'}]}}) + '\n')
check('the turn is stopped (interrupt in the transcript): the hook ends and drops its row',
      wait_for(lambda: p.poll() is not None, 5) and S1 + '/toolu_i1' not in rows())

# its Claude Code process is gone: a hold whose parent has already exited ends at once
inp = os.path.join(T, 'orphan.json')
json.dump({'hook_event_name': 'PreToolUse', 'session_id': S1, 'transcript_path': TP1, 'cwd': '/tmp/work',
           'tool_name': 'Edit', 'tool_input': {}, 'agent_id': 'agentO', 'tool_use_id': 'toolu_orphan'}, open(inp, 'w'))
open(LOG, 'w').close()
usage(five=85)
sh = subprocess.Popen(['/bin/sh', '-c', f'/usr/bin/python3 "{HOOK}" --hold orphan-test < "{inp}" > /dev/null 2>&1 & sleep 2'],
                      env=os.environ, cwd=T)
check('a hold under a parent that is still there: it holds', wait_for(lambda: S1 + '/toolu_orphan' in rows(), 3), rows())
sh.wait(5)
check('... its parent (standing in for Claude Code) exits: the hold ends, drops its row and says why', wait_for(
      lambda: not subprocess.run(['pgrep', '-f', 'orphan-test'], capture_output=True, text=True).stdout.strip(), 5)
      and S1 + '/toolu_orphan' not in rows() and 'end    11111111/agentO hold ended: the session closed' in logtext(),
      (rows(), logtext()))
subprocess.run(['/bin/sh', '-c', f'/usr/bin/python3 "{HOOK}" --hold orphan-test < "{inp}" > /dev/null 2>&1 &'], env=os.environ, cwd=T)
time.sleep(0.5)
check('a hold whose parent is already gone (parent 1) ends at once, with no row', wait_for(
      lambda: not subprocess.run(['pgrep', '-f', 'orphan-test'], capture_output=True, text=True).stdout.strip(), 5)
      and S1 + '/toolu_orphan' not in rows() and 'error' not in logtext(), (rows(), logtext()))

# a reset passes in an old read: it ends at the reset
usage(five=85, five_reset=3)
p = start_hold(S1, TP1, tuid='toolu_r1')
check('the reset time passes: the hold ends by itself', wait_for(lambda: p.poll() is not None, 10))

# a follow-the-menu wait is left to the command, as before
state()
usage(five=100)
p = start_hold(S3, TP3, tuid='toolu_fw')
check('--hold leaves a follow-the-menu wait to the command (exits at once)', wait_for(lambda: p.poll() is not None, 3))
# no id to answer by: --hold leaves the call to the plain hook
state(limit_modes=dict(HOLD80))
usage(five=85)
p = start_hold(S1, TP1, 'agentN', tool=EDIT)
check('an agent call with no tool_use_id: --hold exits at once (the plain hook stops it)', wait_for(lambda: p.poll() is not None, 3))

# ---- the command's own loop (the fallback) -------------------------------------------------------------------
print('-- claude-limit-wait')
state(limit_modes=dict(HOLD80))
usage(five=85)
r = run(['wait', S1], env={'STTARK_LIMIT_CHUNK': '2'})
out = r.stdout.splitlines()
check('wait command in hold mode: holding line, then WAIT AGAIN after its chunk',
      out and out[0].startswith('Holding at 80%: the 5-hour limit is at 85%.') and out[-1].startswith('WAIT AGAIN: still holding at 80%'),
      r.stdout)
check('... its row is gone after it', S1 not in rows())
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

# ---- a hold decision waits for a usage read another process is making --------------------------------------------
print('-- usage read in progress')
RACE = os.path.join(T, 'race')
os.makedirs(RACE)
saved = (lh.TEST, lh.USAGE, lh.DIR, lh.URL)
lh.TEST, lh.USAGE, lh.DIR, lh.URL = None, os.path.join(RACE, 'usage.json'), RACE, 'http://127.0.0.1:9/'
old_read, new_read = usage(five=70), usage(five=85)
json.dump({'at': time.time() - 3600, 'usage': old_read}, open(lh.USAGE, 'w'))
lk = open(lh.USAGE + '.lock', 'w')
fcntl.flock(lk, fcntl.LOCK_EX)   # another process is reading now


def finish_read():
    time.sleep(1)
    json.dump({'at': time.time(), 'usage': new_read}, open(lh.USAGE, 'w'))
    fcntl.flock(lk, fcntl.LOCK_UN)


got, secs = timed(lambda: lh.usage())
check('without waiting: the old read, at once', got == old_read and secs < 0.5, secs)
threading.Thread(target=finish_read).start()
got, secs = timed(lambda: lh.usage(wait=3))
check('with wait: the new read, once the other process has it', got == new_read and 0.8 < secs < 3, (got == old_read, secs))
lk.close()
lh.TEST, lh.USAGE, lh.DIR, lh.URL = saved

# ---- install-hooks.py in a temp HOME ---------------------------------------------------------------------------
print('-- install-hooks.py')
os.makedirs(os.path.join(HOME, '.claude'), exist_ok=True)
json.dump({'hooks': {}}, open(os.path.join(HOME, '.claude/settings.json'), 'w'))
r = subprocess.run(['/usr/bin/python3', INSTALL], capture_output=True, text=True, env=os.environ)
s = json.load(open(os.path.join(HOME, '.claude/settings.json')))
for event in ('PreToolUse', 'UserPromptSubmit'):
    groups = s['hooks'].get(event, [])
    hold = [g for g in groups if not g.get('matcher') and any(h['command'].endswith('limit-hook.py" --hold') for h in g['hooks'])]
    plain = [g for g in groups if any(h['command'].endswith('limit-hook.py"') for h in g['hooks'])]
    check(f'install {event}: the --hold entry (everything, 8 days) and the plain entry (60 s)',
          len(hold) == 1 and hold[0]['hooks'][0]['timeout'] == 8 * 24 * 3600 and len(plain) == 1
          and plain[0]['hooks'][0]['timeout'] == 60, json.dumps(groups)[:400])
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

# ---- a test never touches the usage cache, and leaves nothing running ------------------------------------------------
check('STTARK_LIMIT_TEST: no usage.json cache was read or written', not os.path.exists(os.path.join(KIT, 'usage.json')))
time.sleep(1)
leftover = subprocess.run(['pgrep', '-f', HOOK], capture_output=True, text=True).stdout.split()
check('no hook process left running', not leftover, leftover)
for pid in leftover:
    os.kill(int(pid), signal.SIGTERM)

shutil.rmtree(T)
print(f'\n{len(failed)} failed' if failed else '\nall passed')
sys.exit(1 if failed else 0)
