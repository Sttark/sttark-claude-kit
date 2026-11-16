#!/usr/bin/python3
"""Tests usage-scan.py (Usage by session) on copies: a temporary Kit folder and log, and a temporary ~/.claude with
made-up records (STTARK_KIT_DIR, STTARK_KIT_LOG, STTARK_CLAUDE_DIR). Checks the weights at API prices (each token
type, fast mode, a long Haiku prompt, web searches), that a reply counts once (its parts, a resumed copy, a fork's
copy), whose use each record is (a link in the record, the Kit's record of it, an agent, a run in a session's
scratchpad, the Kit's own runs, temporary folders, many unnamed runs of one folder), the names (the Claude app's,
the record's own title, never a prompt or a reply), the days, agents started, the incremental read (only what was
added; a line still being written waits; a file that got shorter is read again; a deleted one leaves), --if-older,
the active time with each kind of wait left out (the usage limit, holds, claude-wait, sleeps and polls, the person,
retries), the kinds of work (and the Haiku call for an unclear one, with a stand-in), and the price check: --prices fails for a model with no price, and passes on the recent records of this Mac
(read only; skipped where there are none).
Run from the repo root: /usr/bin/python3 tools/usage-scan-test.py"""
import json, os, shutil, subprocess, sys, tempfile, time

ROOT = os.getcwd()
SCAN = os.path.join(ROOT, 'Resources/hooks/usage-scan.py')
tmp = tempfile.mkdtemp(prefix='kit-usage-')
kit, claude = os.path.join(tmp, 'kit'), os.path.join(tmp, 'claude')
projects = os.path.join(claude, 'projects')
os.makedirs(kit)
ENV = dict(os.environ, STTARK_KIT_DIR=kit, STTARK_KIT_LOG=os.path.join(tmp, 'kit.log'), STTARK_CLAUDE_DIR=claude)
fails = []
NOW = time.time()
SID_A = '11111111-aaaa-4aaa-8aaa-000000000001'
SID_B = '22222222-bbbb-4bbb-8bbb-000000000002'
SID_C = '33333333-cccc-4ccc-8ccc-000000000003'
SID_D = '44444444-dddd-4ddd-8ddd-000000000004'


def check(what, ok):
    print(('ok    ' if ok else 'FAIL  ') + what)
    if not ok:
        fails.append(what)


def near(a, b):
    return abs(a - b) < 1e-6


def stamp(days_ago=0, minutes_ago=5):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(NOW - days_ago * 86400 - minutes_ago * 60))


def reply(mid, model='claude-opus-5-5', i=0, o=0, c5=0, c1=0, cr=0, days_ago=0, minutes_ago=5, fast=False, searches=0,
          side=False, text='MARKER-REPLY the answer'):
    u = {'input_tokens': i, 'output_tokens': o, 'cache_creation_input_tokens': c5 + c1, 'cache_read_input_tokens': cr,
         'cache_creation': {'ephemeral_5m_input_tokens': c5, 'ephemeral_1h_input_tokens': c1},
         'server_tool_use': {'web_search_requests': searches, 'web_fetch_requests': 0}, 'speed': 'fast' if fast else 'standard'}
    return {'type': 'assistant', 'isSidechain': side, 'timestamp': stamp(days_ago, minutes_ago), 'cwd': '/Users/test/src/app',
            'message': {'model': model, 'id': mid, 'role': 'assistant', 'content': [{'type': 'text', 'text': text}], 'usage': u}}


def prompt(text='MARKER-PROMPT please fix it'):
    return {'type': 'user', 'timestamp': stamp(), 'message': {'role': 'user', 'content': text}}


def write(folder, name, lines, sub=None, cwd=None):
    d = os.path.join(projects, folder) if sub is None else os.path.join(projects, folder, sub, 'subagents')
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name + '.jsonl')
    with open(p, 'w') as f:
        for x in lines:
            if cwd and x.get('type') == 'assistant':
                x = dict(x, cwd=cwd)
            f.write(json.dumps(x, separators=(',', ':')) + '\n')
    return p


def run(*a):
    r = subprocess.run(['/usr/bin/python3', SCAN] + list(a), capture_output=True, text=True, env=ENV)
    return r.returncode, (r.stdout + r.stderr).strip()


def out():
    with open(os.path.join(kit, 'usage', 'by-session.json')) as f:
        return json.load(f)


def by_title(o, title):
    return [i for i, s in enumerate(o['sessions']) if s['title'] == title]


def by_key(o, key):
    return [i for i, s in enumerate(o['sessions']) if s['key'] == key]


def records():
    return sum(1 for _, _, fs in os.walk(projects) for f in fs if f.endswith('.jsonl'))


def totals(o, s, days=None):
    own = ag = tok = 0.0
    for r in o['rows']:
        if r[0] == s and (days is None or r[1] in days):
            own, ag, tok = own + r[3], ag + r[4], tok + r[5] + r[6]
    return own, ag, tok


# ---------- the made-up records ----------

src = '-Users-test-src'
# A: a session with a link in its record; one reply in two parts (the first with part of its output); a Sonnet reply
# two days ago; an old reply past the days kept; Claude Code's own note; a prompt and reply text that must not show
A = write(src, SID_A, [
    {'type': 'bridge-session', 'sessionId': SID_A, 'bridgeSessionId': 'cse_01TestA', 'lastSequenceNum': 0},
    prompt(),
    reply('msg_A1', i=1000, o=500, c5=3000, c1=4000, cr=5000),
    reply('msg_A1', i=1000, o=2000, c5=3000, c1=4000, cr=5000),
    reply('msg_A2', model='claude-sonnet-5-5', i=1000000, o=100000, days_ago=2, minutes_ago=0),
    reply('msg_A0', i=999999, days_ago=60),
    reply('msg_syn', model='<synthetic>'),
    {'type': 'custom-title', 'sessionId': SID_A, 'customTitle': 'Its own title'},
    {'type': 'last-prompt', 'sessionId': SID_A, 'lastPrompt': 'MARKER-PROMPT the last prompt'},
])
# its agents: a Haiku agent with a long prompt and a fast reply, and a fork that copies the session's own reply
write(src, 'agent-a1', [reply('msg_A3', model='claude-haiku-5-5', i=150000, o=1000), reply('msg_A4', o=1000, fast=True, searches=3)], sub=SID_A)
write(src, 'agent-a2', [reply('msg_A1', i=1000, o=2000, c5=3000, c1=4000, cr=5000), reply('msg_A5', o=100, side=True)], sub=SID_A)
# a resumed copy of A in a newer file: its copy of A's reply counts once, in A; its own new reply counts
time.sleep(0.05)
write(src, SID_D, [reply('msg_A1', i=1000, o=2000, c5=3000, c1=4000, cr=5000), reply('msg_D1', i=10, o=10)])
# a run started in A's scratchpad folder: A's agent
write('-private-tmp-claude-501--Users-test-src-' + SID_A + '-scratchpad-check', '55555555-eeee-4eee-8eee-000000000005',
      [reply('msg_S1', o=1000)])
# B: no link in its record; the Kit's state knows it, and the Claude app's list names it
write(src, SID_B, [reply('msg_B1', o=5000)])
# C: no link anywhere; its own title from the record
write(src, SID_C, [reply('msg_C1', o=3000), {'type': 'ai-title', 'sessionId': SID_C, 'aiTitle': 'Bin label sizes'}])
# the Kit's own runs, a run in a temporary folder, and many unnamed runs of another app
write('-Users-test-Library-Application-Support-SttarkClaudeKit-app-rules', '66666666-ffff-4fff-8fff-000000000006', [reply('msg_K1', o=100)])
write('-private-tmp-kit-test-work', '77777777-aaaa-4aaa-8aaa-000000000007', [reply('msg_T1', o=100)])
for n in range(6):
    write('-Users-test-Library-Application-Support-OtherApp', '8888888%d-aaaa-4aaa-8aaa-00000000000%d' % (n, n),
          [reply('msg_R%d' % n, model='claude-haiku-5-5', o=100)], cwd='/Users/test/Library/Application Support/OtherApp')
# the Kit's state: B's record and its link, and the Claude app's name for it
with open(os.path.join(kit, 'state.json'), 'w') as f:
    json.dump({'sessions': {'cse_01TestB': {'title': 'Kit name for B', 'transcript': os.path.join(projects, src, SID_B + '.jsonl')}},
               'app_list': {'at': NOW, 'sessions': [{'id': 'cse_01TestB', 'title': 'Order page login'},
                                                    {'id': 'cse_01TestA', 'title': 'Site map plan'}]}}, f)

# ---------- the first scan ----------

code, said = run()
check('the first scan runs: ' + said, code == 0)
o = out()
check('no prompt or reply text in what it writes', not any('MARKER' in open(os.path.join(kit, 'usage', f)).read()
                                                        for f in ('by-session.json', 'scan-cache.json')))
check('the days end today, in this time zone', o['days'][-1] == time.strftime('%Y-%m-%d'))
check('a reply past the days kept is left out: the days start at the oldest one kept',
      o['days'][0] == time.strftime('%Y-%m-%d', time.localtime(NOW - 2 * 86400)))
check("Claude Code's own notes are left out", all(m['id'] != '<synthetic>' for m in o['models']))
a = by_title(o, 'Site map plan')
check("A is one row, named as in the Claude app's list", len(a) == 1 and o['sessions'][a[0]]['cse'] == 'cse_01TestA')
a = a[0]
own, ag, tok = totals(o, a)
# A's own: msg_A1 in full (its second part) at Opus 5.5 prices, msg_A2 at Sonnet 5.5 prices
a1 = (1000 * 4 + 2000 * 20 + 3000 * 5 + 4000 * 8 + 5000 * 0.2) / 1e6
a2 = (1000000 * 2 + 100000 * 10) / 1e6
check('its own use: each token type at its price, a reply once, from its last part', near(own, a1 + a2))
# its agents: a long Haiku prompt at the long price, a fast reply at twice the price plus 3 web searches, the fork's own
# side line (its copy of A's reply counts in A), and the run in its scratchpad
a3 = (150000 * 0.50 + 1000 * 2.50) / 1e6
a4 = 1000 * 20 / 1e6 * 2 + 3 * 0.01
a5 = 100 * 20 / 1e6
s1 = 1000 * 20 / 1e6
check('its agents: long Haiku price, fast mode, web searches, the scratchpad run', near(ag, a3 + a4 + a5 + s1))
check('the tokens of each type add up', tok == 2000 + 3000 + 4000 + 5000 + 1000 + 1100000 + 151000 + 1000 + 100 + 1000)
started = sum(r[2] for r in o['agents'] if r[0] == a)
check('agents started: its two agents and the scratchpad run', started == 3)
d = by_key(o, 'sid:' + SID_D)
check("a resumed copy's own reply counts in its row; the reply it copied counts once, in A",
      len(d) == 1 and near(totals(o, d[0])[0], (10 * 4 + 10 * 20) / 1e6) and o['sessions'][d[0]]['title'] == 'Unnamed session')
b = by_title(o, 'Order page login')
check("B, linked only in the Kit's record, takes the Claude app's name", len(b) == 1 and o['sessions'][b[0]]['cse'] == 'cse_01TestB')
c = by_title(o, 'Bin label sizes')
check("C, with no link, takes its record's own title", len(c) == 1 and o['sessions'][c[0]]['cse'] is None
      and o['sessions'][c[0]]['kind'] == 'local')
check("the Kit's own runs are one row", len(by_title(o, 'Sttark Claude Kit checks')) == 1)
check('runs in temporary folders are one row', len(by_title(o, 'Runs in temporary folders')) == 1)
r = by_title(o, 'Runs with no name in OtherApp')
check("another app's unnamed runs are one row, named by the folder's own name", len(r) == 1 and o['sessions'][r[0]]['kind'] == 'runs')
check('no title is a path', not any('/' in s['title'] for s in o['sessions']))
check('last active is the newest reply', abs(o['sessions'][a]['last'] - (NOW - 300)) < 2)
today = len(o['days']) - 1
check('the reply two days ago is on its day', near(totals(o, a, {today - 2})[0], a2))
n = records()
check('a whole scan reads every file', said.startswith('%d records, %d read' % (n, n)))

# ---------- incremental reading ----------

with open(A, 'a') as f:
    f.write(json.dumps(reply('msg_A6', o=1000), separators=(',', ':')) + '\n')
    f.write(json.dumps(reply('msg_A7', o=1000), separators=(',', ':'))[:40])   # a line still being written
size = len(json.dumps(reply('msg_A6', o=1000), separators=(',', ':'))) + 1
code, said = run()
check('a later scan reads only the file that grew, from where it stopped: ' + said, said.startswith('%d records, 1 read (%d bytes)' % (n, size)))
own2 = totals(out(), a)[0]
check('the added reply counts; the half-written one waits', near(own2 - own, 1000 * 20 / 1e6))
with open(A, 'a') as f:
    f.write(json.dumps(reply('msg_A7', o=1000), separators=(',', ':'))[40:] + '\n')
run()
check('the rest of the line, once written, counts', near(totals(out(), a)[0] - own2, 1000 * 20 / 1e6))
code, said = run()
check('nothing new: nothing is read', said.startswith('%d records, 0 read' % n))
write(src, SID_C, [reply('msg_C2', o=10)])   # the same file, shorter: read again from the start
run()
c = by_key(out(), 'sid:' + SID_C)
check('a file that got shorter is read again from its start', len(c) == 1 and near(totals(out(), c[0])[0], 10 * 20 / 1e6))
os.remove(os.path.join(projects, src, SID_B + '.jsonl'))
code, said = run()
check('a deleted record leaves', said.startswith('%d records' % (n - 1)) and not by_title(out(), 'Order page login'))
at = out()['at']
code, said = run('--if-older', '3600')
check('--if-older does nothing while the list is fresh', said == '' and out()['at'] == at)

# ---------- prices ----------

code, said = run('--prices')
check('--prices passes when every model has a price', code == 0 and 'NO PRICE' not in said)
write(src, '99999999-aaaa-4aaa-8aaa-000000000009', [reply('msg_N1', model='claude-opus-9-9', o=1000000)])
code, said = run('--prices')
check('--prices fails for a model with no price, and names it: ' + said.splitlines()[-1], code == 1 and 'claude-opus-9-9' in said)
o = out()
check('it counts at its family price meanwhile, and is listed as unpriced', o['unpriced'].get('claude-opus-9-9', 0) == 1000000
      and not [m for m in o['models'] if m['id'] == 'claude-opus-9-9'][0]['priced'])
with open(os.path.join(tmp, 'kit.log')) as f:
    log = f.read()
check('the log says so once', log.count('no price for claude-opus-9-9') == 1)
run()
with open(os.path.join(tmp, 'kit.log')) as f:
    check('and not again the same day', f.read().count('no price for claude-opus-9-9') == 1)

# ---------- active time: waits left out ----------
# Records shaped like real ones: a wait at the usage limit (claude-limit-wait), an agent's tool call and a prompt the
# Kit held with no reply, a wait handed off with claude-wait and the Kit's prompt that brings the session back, sleeps
# and polls, a question to the person and a permission prompt, an API retry, a long think, long and quick tool runs, tools
# that run at once, and an error note. Each in a test folder of its own (STTARK_KIT_DIR, STTARK_KIT_LOG, STTARK_CLAUDE_DIR).

atmp = tempfile.mkdtemp(prefix='kit-active-')
akit, aclaude = os.path.join(atmp, 'kit'), os.path.join(atmp, 'claude')
os.makedirs(akit)
ALOG = os.path.join(atmp, 'kit.log')
KIND_STUB = os.path.join(atmp, 'kind.sh')
KIND_CALLS = os.path.join(atmp, 'kind-calls')
with open(KIND_STUB, 'w') as f:   # stands in for the Haiku call: counts its calls, answers design
    f.write('#!/bin/sh\necho x >> "%s"\necho "design"\n' % KIND_CALLS)
os.chmod(KIND_STUB, 0o755)
AENV = dict(os.environ, STTARK_KIT_DIR=akit, STTARK_KIT_LOG=ALOG, STTARK_CLAUDE_DIR=aclaude, STTARK_USAGE_KIND=KIND_STUB)
BASE = int(NOW) - 86400 - 3600


def ts(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(BASE + int(t))) + '.%03dZ' % round((t % 1) * 1000)


def logtime(t):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(BASE + t))


def ask_(t, text, origin=None):
    d = {'type': 'user', 'timestamp': ts(t), 'message': {'role': 'user', 'content': text}}
    if origin:
        d['origin'] = {'kind': origin}
    return d


def hook(t):
    return {'type': 'attachment', 'attachment': {'type': 'hook_additional_context', 'content': ['MARKER-RULES the rules']},
            'timestamp': ts(t)}


def said(t, mid, *blocks, model='claude-opus-5-5', **extra):
    return dict({'type': 'assistant', 'timestamp': ts(t), 'message': {
        'id': mid, 'model': model, 'role': 'assistant', 'content': list(blocks),
        'usage': {'input_tokens': 10, 'output_tokens': 10}}}, **extra)


def text(words='MARKER-REPLY'):
    return {'type': 'text', 'text': words}


def call(i, name, **inp):
    return {'type': 'tool_use', 'id': i, 'name': name, 'input': inp}


def done(t, *ids, source='config'):
    return {'type': 'user', 'timestamp': ts(t), 'permissionDecision': {'decision': 'accept', 'source': source},
            'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': i, 'content': 'MARKER-OUT'} for i in ids]}}


def line(t, sub, **kw):
    return dict({'type': 'system', 'subtype': sub, 'timestamp': ts(t)}, **kw)


def titled(name):
    return {'type': 'custom-title', 'customTitle': name}


def awrite(sid, lines, agent=None):
    d = os.path.join(aclaude, 'projects', '-Users-test-src', *( [sid, 'subagents'] if agent else []))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, (agent or sid) + '.jsonl')
    with open(p, 'w') as f:
        for x in lines:
            f.write(json.dumps(x, separators=(',', ':')) + '\n')
    return p


def arun():
    r = subprocess.run(['/usr/bin/python3', SCAN], capture_output=True, text=True, env=AENV)
    with open(os.path.join(akit, 'usage', 'by-session.json')) as f:
        return r.returncode, json.load(f)


def at_work(o, title):
    """{kind id: seconds} of the row with this title."""
    s = [i for i, x in enumerate(o['sessions']) if x['title'] == title]
    out = {}
    for r in o['work']:
        if s and r[0] == s[0]:
            k = o['kinds'][r[2]]['id']
            out[k] = out.get(k, 0) + r[3]
    return out


def secs(o, title):
    return sum(at_work(o, title).values())


SID = ['%d%d%d%d%d%d%d%d-aaaa-4aaa-8aaa-0000000000%02d' % ((n,) * 8 + (n,)) for n in range(1, 10)]
# 1. A wait at the usage limit, with its one line: claude-limit-wait every 9 minutes until the limit resets
awrite(SID[0], [titled('Limit wait'), ask_(0, 'MARKER-PROMPT go'), hook(1),
                said(9, 'm1', text()), said(10, 'm1', call('w1', 'Bash', command='claude-limit-wait ' + SID[0])),
                done(553, 'w1'), said(556, 'm2', call('w2', 'Bash', command='claude-limit-wait ' + SID[0])),
                done(1099, 'w2'), said(1102, 'm3', call('w3', 'Bash', command='claude-limit-wait ' + SID[0])),
                done(1102.5, 'w3'), said(1110, 'm4', text()), line(1111, 'stop_hook_summary')])
# 2. Holds with no reply: a prompt held 2 hours (its hooks' notes come when the hold ends), and an agent's tool call
# held 3 hours (the Kit's log has the hold and the resume)
awrite(SID[1], [titled('Held'), ask_(0, 'MARKER-PROMPT go on'), hook(7200), said(7205, 'b1', text())])
awrite(SID[1], [ask_(0, 'MARKER-PROMPT the brief'), said(2, 'a1', call('h1', 'Bash', command='ls')), done(3, 'h1'),
                said(5, 'a2', call('h2', 'Bash', command='git status')), done(10805, 'h2'), said(10808, 'a3', text())],
       agent='agent-a1b2c3d4e5f6a7b8c')
with open(ALOG, 'w') as f:
    f.write('%s limit  hold   %s/a1b2c3d4 at 80%%: the 5-hour limit is at 100%%, until 6:00 PM (Bash)\n' % (logtime(5), SID[1][:8]))
    f.write('%s limit  wait   %s/a1b2c3d4 at 80%%: the 5-hour limit is at 100%%, until 6:00 PM, with no model calls until it ends\n'
            % (logtime(6), SID[1][:8]))
    f.write('%s limit  resume %s/a1b2c3d4 the 5-hour limit is under 80%%, after 180 min\n' % (logtime(10804), SID[1][:8]))
# 3. A wait handed to the Kit with claude-wait, the turn ends, hooks and notes come and go, and a day later the Kit's
# prompt brings the session back
awrite(SID[2], [titled('Wait and wake'), ask_(0, 'MARKER-PROMPT tell me when they reply'), hook(1),
                said(4, 'c1', call('k1', 'Bash', command='claude-wait email-reply 1a2b --by "+2d" --why "x"')), done(4.5, 'k1'),
                said(6, 'c2', text()), line(6.5, 'stop_hook_summary'),
                {'type': 'queue-operation', 'operation': 'enqueue', 'timestamp': ts(7), 'content': 'x'},
                {'type': 'pr-link', 'timestamp': ts(100), 'prNumber': 1}, line(5000, 'bridge_status', content='x'),
                ask_(86400, '[Sttark Claude Kit] A wait you handed to the Kit has ended. MARKER-PROMPT'), hook(86401),
                said(86407, 'c3', text())])
# 4. Sleeps and polls: a long sleep, an until loop, a watch on the checks (the replies between them are the loop
# going on), and a command with a short sleep in it
awrite(SID[3], [titled('Sleeps'), ask_(0, 'MARKER-PROMPT merge it'),
                said(2, 'd1', call('s1', 'Bash', command='sleep 240; gh pr checks 5')), done(245, 's1'),
                said(247, 'd2', call('s2', 'Bash', command='until gh pr checks 5 | grep -q pass; do sleep 5; done')), done(400, 's2'),
                said(402, 'd3', call('s3', 'Bash', command='gh pr checks 5 --watch')), done(600, 's3'),
                said(603, 'd4', call('s4', 'Bash', command='sleep 3 && curl -s localhost')), done(613, 's4'),
                said(620, 'd5', text())])
# 5. The person: a question waits 20 minutes, a permission prompt 5
awrite(SID[4], [titled('Asks'), ask_(0, 'MARKER-PROMPT plan it'), said(3, 'e1', call('q1', 'AskUserQuestion', questions=[])),
                done(1203, 'q1'), said(1209, 'e2', text()), line(1210, 'stop_hook_summary'),
                ask_(2000, 'MARKER-PROMPT clean up'), said(2002, 'e3', call('q2', 'Bash', command='rm -rf build')),
                done(2302, 'q2', source='user_temporary'), said(2305, 'e4', text())])
# 6. An API retry, a 20-minute think, a long build, a slow read, two tools at once, and an error note
awrite(SID[5], [titled('Model time'), ask_(0, 'MARKER-PROMPT build it'), line(1, 'api_error', retryInMs=30000),
                said(40, 'f1', text()), ask_(41, 'MARKER-PROMPT and then'),
                said(1251, 'f2', {'type': 'thinking', 'thinking': ''}, thinkingDurationMs=1200000),
                said(1260, 'f3', call('t1', 'Bash', command='npm run build')), done(1860, 't1'),
                said(1862, 'f4', call('t2', 'Read', file_path='/x/a.py')), done(1982, 't2'),
                said(1985, 'f5', call('t3', 'Bash', command='python3 a.py')), said(1986, 'f5', call('t4', 'Bash', command='python3 b.py')),
                done(2000, 't3'), done(2001, 't4'), said(2003, 'f6', text('API Error'), model='<synthetic>')])

code, o = arun()
check('the scan reads them', code == 0)
check('no prompt, reply, command or hook text in what it writes', not any(
    w in open(os.path.join(akit, 'usage', f)).read() for f in ('by-session.json', 'scan-cache.json') for w in ('MARKER', 'claude-limit-wait', 'gh pr')))
check('the kinds of work and their factors go with it', [(k['id'], k['x']) for k in o['kinds']]
      == [('software', 12.0), ('design', 5.0), ('admin', 2.5), ('small', 2.0)])
check('usage limit: claude-limit-wait and the replies that only wait again count nothing (16 s of 1,111): %s' % secs(o, 'Limit wait'),
      abs(secs(o, 'Limit wait') - 16.5) <= 1)
check('a prompt held with no reply counts from the hooks after the hold (5 s of 7,205), and an agent held by the Kit '
      'at its tool call counts nothing for the hold (8 s of 10,808): %s' % secs(o, 'Held'), abs(secs(o, 'Held') - 13) <= 1)
check('claude-wait, the day it waits and the notes in it count nothing; the prompt that brings it back starts the next '
      'reply (10.5 s of a day): %s' % secs(o, 'Wait and wake'), abs(secs(o, 'Wait and wake') - 10.5) <= 1)
check('a long sleep, an until loop and a watch count nothing; a short sleep is taken off its command (19 s of 620): %s'
      % secs(o, 'Sleeps'), abs(secs(o, 'Sleeps') - 19) <= 1)
check('a question and a permission prompt wait on the person: nothing (14 s of 2,305): %s' % secs(o, 'Asks'),
      abs(secs(o, 'Asks') - 14) <= 1)
check('a retry waits; a long think counts all of it; a tool run counts 5 minutes at most, a read 1; tools at once '
      'count once; an error note counts nothing (1,609 s): %s' % secs(o, 'Model time'), abs(secs(o, 'Model time') - 1609) <= 1)
check('a session with less than an hour and no clear kind is small: ' + str(at_work(o, 'Wait and wake')),
      set(at_work(o, 'Wait and wake')) == {'small'})

# the agent's tool result had not come at the first read: a later scan adds it once
awrite(SID[6], [titled('Later'), ask_(0, 'MARKER-PROMPT run it'), said(2, 'g1', call('l1', 'Bash', command='python3 x.py'))])
arun()
p = awrite(SID[6], [titled('Later'), ask_(0, 'MARKER-PROMPT run it'), said(2, 'g1', call('l1', 'Bash', command='python3 x.py'))])
with open(p, 'a') as f:
    f.write(json.dumps(done(62, 'l1')) + '\n' + json.dumps(said(64, 'g2', text())) + '\n')
code, o = arun()
check('a tool run whose result comes in a later scan counts once (64 s): %s' % secs(o, 'Later'), abs(secs(o, 'Later') - 64) <= 1)
code, o = arun()
check('and again after a scan that reads nothing new: %s' % secs(o, 'Later'), abs(secs(o, 'Later') - 64) <= 1)

# ---------- the kind of work ----------

# software: tests and a pull request; its fork agent copies a reply of the session, which counts once
awrite(SID[7], [titled('Software'), ask_(0, 'MARKER-PROMPT fix it'), said(10, 'n1', call('n1t', 'Edit', file_path='/x/app.ts')),
                done(11, 'n1t'), said(20, 'n2', call('n2t', 'Bash', command='npx vitest run')), done(80, 'n2t'),
                said(90, 'n3', call('n3t', 'Bash', command='gh pr create --title x')), done(95, 'n3t'), said(100, 'n4', text())])
awrite(SID[7], [said(10, 'n1', call('n1t', 'Edit', file_path='/x/app.ts')), done(11, 'n1t'),
                said(30, 'n5', call('n5t', 'Bash', command='claude-window go https://example.com')), done(40, 'n5t')],
       agent='agent-f0f0f0f0f0f0f0f0f')
# design: a CAD file and a drawing script; admin: the browser and an email draft; small: a short question
awrite(SID[8], [titled('Design'), ask_(0, 'MARKER-PROMPT draw it'), said(10, 'p1', call('p1t', 'Write', file_path='/x/part.scad')),
                done(11, 'p1t'), said(20, 'p2', call('p2t', 'Bash', command='python3 draw_plan.py')), done(50, 'p2t'), said(60, 'p3', text())])
awrite('a' * 8 + '-aaaa-4aaa-8aaa-000000000010', [titled('Admin'), ask_(0, 'MARKER-PROMPT order it'),
                said(10, 'r1', call('r1t', 'Bash', command='claude-window go https://shop.example')), done(30, 'r1t'),
                said(40, 'r2', call('r2t', 'mcp__claude_ai_Sttark_Workrouter__gmail_create_draft', to='x')), done(45, 'r2t'), said(50, 'r3', text())])
awrite('b' * 8 + '-bbbb-4bbb-8bbb-000000000011', [titled('Question'), ask_(0, 'MARKER-PROMPT what is it'), said(20, 'u1', text())])
# mixed: more than an hour with no clear signs; Haiku (the stand-in) names it once
long_ = [titled('Unclear'), ask_(0, 'MARKER-PROMPT look into it')]
for n in range(14):
    t0 = 10 + n * 400
    long_ += [said(t0, 'x%d' % n, call('x%dt' % n, 'Bash', command='python3 job.py')), done(t0 + 390, 'x%dt' % n)]
awrite('c' * 8 + '-cccc-4ccc-8ccc-000000000012', long_)
code, o = arun()
sw = at_work(o, 'Software')
check('tests and a pull request make a unit software; its agent that drives the browser is its own unit, admin; a copied '
      'reply counts once: %s' % sw, abs(sw.get('software', 0) - 100) <= 1 and abs(sw.get('admin', 0) - 30) <= 1)
check('a CAD file and a drawing script: design ' + str(at_work(o, 'Design')), set(at_work(o, 'Design')) == {'design'})
check('the browser and an email draft: admin ' + str(at_work(o, 'Admin')), set(at_work(o, 'Admin')) == {'admin'})
check('a short question: small ' + str(at_work(o, 'Question')), set(at_work(o, 'Question')) == {'small'})
calls = open(KIND_CALLS).read().count('x') if os.path.exists(KIND_CALLS) else 0
check('over an hour with no clear kind: one Haiku call names it (design): %s, %d call' % (at_work(o, 'Unclear'), calls),
      set(at_work(o, 'Unclear')) == {'design'} and calls == 1)
arun()
calls = open(KIND_CALLS).read().count('x')
check('its answer is kept: no second call on the next scan (%d call)' % calls, calls == 1)
with open(ALOG) as f:
    check('the log says what Haiku named it', 'kind of "Unclear": design (Haiku)' in f.read())

shutil.rmtree(atmp, ignore_errors=True)

# ---------- the recent records of this Mac: every model has a price ----------

real = os.path.expanduser('~/.claude/projects')
if os.path.isdir(real) and os.listdir(real):
    mine = os.path.join(tmp, 'real-kit')
    os.makedirs(mine)
    r = subprocess.run(['/usr/bin/python3', SCAN, '--prices'], capture_output=True, text=True,
                       env=dict(os.environ, STTARK_KIT_DIR=mine, STTARK_KIT_LOG=os.path.join(tmp, 'real.log'),
                                STTARK_CLAUDE_DIR=os.path.expanduser('~/.claude')))
    print(r.stdout.strip())
    check("every model in this Mac's recent records has a price in usage-scan.py's PRICES", r.returncode == 0)
else:
    print('skip  no records on this computer to check the prices against')

shutil.rmtree(tmp, ignore_errors=True)
print('\n%d failed' % len(fails) if fails else '\nall passed')
sys.exit(1 if fails else 0)
