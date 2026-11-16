#!/usr/bin/python3
"""Tests usage-scan.py (Usage by session) on copies: a temporary Kit folder and log, and a temporary ~/.claude with
made-up records (STTARK_KIT_DIR, STTARK_KIT_LOG, STTARK_CLAUDE_DIR). Checks the weights at API prices (each token
type, fast mode, a long Haiku prompt, web searches), that a reply counts once (its parts, a resumed copy, a fork's
copy), whose use each record is (a link in the record, the Kit's record of it, an agent, a run in a session's
scratchpad, the Kit's own runs, temporary folders, many unnamed runs of one folder), the names (the Claude app's,
the record's own title, never a prompt or a reply), the days, agents started, the incremental read (only what was
added; a line still being written waits; a file that got shorter is read again; a deleted one leaves), --if-older,
and the price check: --prices fails for a model with no price, and passes on the recent records of this Mac
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
