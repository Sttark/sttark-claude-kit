"""Test the day log (Resources/hooks/daylog.py), its hooks, the inline-guard exemption and the install
(install-hooks.py), on copies only: a temp kit folder, a temp log, temp git repos, fake transcripts and a temp
HOME. No model calls. Run: /usr/bin/python3 tools/daylog-test.py"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, 'Resources', 'hooks')
DL = os.path.join(HOOKS, 'daylog.py')
GUARD = os.path.join(HOOKS, 'inline-guard.py')
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


tmp = tempfile.mkdtemp(prefix='daylog-test-')
KIT = os.path.join(tmp, 'kit')
LOG = os.path.join(tmp, 'kit.log')
os.makedirs(KIT)
ENV = dict(os.environ, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_DAYLOG_DATE='2026-11-09')


def switch(on):
    p = os.path.join(KIT, 'state.json')
    try:
        st = json.load(open(p))
    except (OSError, ValueError):
        st = {}
    st['orchestrator'] = on
    json.dump(st, open(p, 'w'))


def git_repo(name):
    p = os.path.join(tmp, name)
    os.makedirs(p)
    subprocess.run(['git', '-C', p, 'init', '-q'], check=True, capture_output=True)
    return p


BINS, LABELS = git_repo('bins'), git_repo('labels')
NOREPO = os.path.join(tmp, 'norepo')
os.makedirs(NOREPO)


def cli(*args, cwd=NOREPO, env=None):
    r = subprocess.run([sys.executable, DL] + list(args), capture_output=True, text=True, cwd=cwd, env=env or ENV)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def day(d='2026-11-09'):
    p = os.path.join(KIT, 'daylog', d + '.md')
    return open(p).read() if os.path.exists(p) else None


def hook(data, env=None):
    r = subprocess.run([sys.executable, DL, '--hook'], input=json.dumps(data), capture_output=True, text=True,
                       env=env or ENV)
    return json.loads(r.stdout) if r.stdout.strip() else None


def log():
    return open(LOG).read().splitlines() if os.path.exists(LOG) else []


# ---- the file ----
rc, out, err = cli('add', '--repo', 'bins', '--kind', 'done', '--text', 'Fix label count rounding | bug | PASS | evidence: 48 tests | pr: u | asana: none')
check('add exits 0 with one line', rc == 0 and out.count('\n') == 0 and 'bins' in out and err == '')
t = day()
check('template: header, asana line, repo section, Done', t.startswith('# Day log 2026-11-09\nasana-synced: no\n\n## bins\n### Done\n- ')
      and t.endswith('| Fix label count rounding | bug | PASS | evidence: 48 tests | pr: u | asana: none\n'))
import re
check('line has HH:MM time', re.search(r'^- \d\d:\d\d \| Fix label', t, re.M) is not None)
cli('add', '--repo', 'bins', '--kind', 'dropped', '--text', 'Dark mode toggle | why: not needed now | by: you')
cli('add', '--repo', 'bins', '--kind', 'decision', '--text', 'Label counts round down | why: whole labels | by: you')
cli('add', '--repo', 'bins', '--kind', 'kicked', '--text', 'Bin search filter | feature | FAIL | gap: empty query | retry: yes')
rc, _, _ = cli('open', '--repo', 'bins', '--item', 'Bulk edit | feature | state: grilling round 2')
heads = re.findall(r'^### (.*)$', day(), re.M)
check('subsections in order whatever the write order', heads == ['Done', 'Kicked back', 'Decisions', 'Dropped', 'Open'])
check('each kind lands in its subsection', '### Kicked back\n- ' in day() and '### Decisions\n- ' in day()
      and '### Dropped\n- ' in day() and '### Open\n- Bulk edit | feature | state: grilling round 2\n' in day())
cli('open', '--repo', 'bins', '--item', 'A | x | state: s', '--item', 'B | y | state: t')
check('open replaces the list', day().split('### Open\n')[1] == '- A | x | state: s\n- B | y | state: t\n')
cli('open', '--repo', 'bins')
check('open with no item clears the list', '### Open' not in day())
cli('add', '--kind', 'done', '--text', 'Loose | chore | PASS | evidence: e', cwd=LABELS)
cli('add', '--kind', 'decision', '--text', 'D | why: w | by: you')
cli('add', '--kind', 'done', '--text', 'Rel | chore | PASS | evidence: e', cwd=os.path.join(LABELS))
check('--repo defaults to the cwd repo', '## labels\n### Done\n- ' in day())
check('outside a repo: General, and it comes last', re.findall(r'^## (.*)$', day(), re.M) == ['bins', 'labels', 'General'])
rc, out, err = cli('add', '--kind', 'done', '--text', '   ')
check('empty text is an error on stderr, exit 1', rc == 1 and out == '' and 'empty' in err)
rc, out, err = cli('add', '--kind', 'bogus', '--text', 'x')
check('bad kind: exit 1, stderr', rc == 1 and err != '')
rc, out, err = cli('nope')
check('bad command: exit 1', rc == 1 and err != '')
p = cli('path')[1]
check('path prints today\'s file', p == os.path.join(KIT, 'daylog', '2026-11-09.md'))
check('path of a new day with --create makes the file',
      cli('path', '--create', env=dict(ENV, STTARK_DAYLOG_DATE='2026-11-12'))[1].endswith('2026-11-12.md')
      and day('2026-11-12') == '# Day log 2026-11-12\nasana-synced: no\n')
os.remove(os.path.join(KIT, 'daylog', '2026-11-12.md'))
rc, out, _ = cli('show', '--repo', 'labels')
check('show --repo prints one section', rc == 0 and out.startswith('## labels') and 'bins' not in out and 'General' not in out)
cli('open', '--repo', 'labels', '--item', 'X | feature | state: s')
check('show --open prints the Open items', cli('show', '--open', '--repo', 'labels')[1] == '- X | feature | state: s')
check('show --open, cwd repo default', cli('show', '--open', cwd=LABELS)[1] == '- X | feature | state: s')
check('show: whole file', cli('show')[1].startswith('# Day log 2026-11-09') and '## General' in cli('show')[1])
check('show --open with nothing', cli('show', '--open', '--repo', 'zzz')[1] == 'No open items.')
sp = cli('state-path', '--repo', 'bins')[1]
check('state-path', sp == os.path.join(KIT, 'orchestrator', 'state', 'bins.md') and os.path.isdir(os.path.dirname(sp)))
check('state-path defaults to the cwd repo', cli('state-path', cwd=LABELS)[1].endswith('state/labels.md'))

# ---- carry forward ----
cli('open', '--repo', 'bins', '--item', 'Carry me | feature | state: grilling')
cli('open', '--repo', 'General', '--item', 'Gen item | chore | state: s')
os.rename(os.path.join(KIT, 'daylog', '2026-11-09.md'), os.path.join(KIT, 'daylog', '2026-11-05.md'))
shutil.copy(os.path.join(KIT, 'daylog', '2026-11-05.md'), os.path.join(KIT, 'daylog', '2026-11-02.md'))
E12 = dict(ENV, STTARK_DAYLOG_DATE='2026-11-12')
cli('add', '--repo', 'bins', '--kind', 'done', '--text', 'New day | chore | PASS | evidence: e', env=E12)
t = day('2026-11-12')
check('new day carries Open items from the latest earlier file, skipping missing days',
      '### Open\n- Carry me | feature | state: grilling\n' in t and '## General\n### Open\n- Gen item' in t)
check('carry-forward leaves Done lines behind', t.count('### Done') == 1 and 'Fix label count' not in t)
check('carry-forward: asana flag starts as no', 'asana-synced: no' in t)
check('show on a day without a file reads the carried items without creating it',
      cli('show', '--open', '--repo', 'bins', env=dict(ENV, STTARK_DAYLOG_DATE='2026-11-13'))[1].startswith('- Carry me')
      and day('2026-11-13') is None)
os.remove(os.path.join(KIT, 'daylog', '2026-11-12.md'))
os.rename(os.path.join(KIT, 'daylog', '2026-11-05.md'), os.path.join(KIT, 'daylog', '2026-11-09.md'))

# ---- lock under parallel writes ----
procs = [subprocess.Popen([sys.executable, DL, 'add', '--repo', 'par', '--kind', 'done', '--text', 'item %d-%d' % (i, j)],
                          env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
         for i in range(5) for j in range(8)]
for pr in procs:
    pr.wait()
mine = re.findall(r'\| item \d-\d$', day(), re.M)
check('40 parallel writes from separate processes: no lost lines', len(mine) == 40 and len(set(mine)) == 40)

# ---- verdict recorder ----
switch(True)
PEND = lambda: json.load(open(os.path.join(KIT, 'state.json'))).get('daylog_pending', {})


def stop_validator(last=None, handback=None, sid='s1', cwd=BINS, agent='validator', final=None):
    d = dict(hook_event_name='SubagentStop', session_id=sid, agent_id='a1', agent_type=agent, cwd=cwd)
    if last is not None:
        d['last_assistant_message'] = last
    if handback is not None or final is not None:
        p = os.path.join(tmp, 'tr%d.jsonl' % len(os.listdir(tmp)))
        with open(p, 'w') as f:
            blocks = [{'type': 'text', 'text': final or 'ok'}]
            if handback is not None:
                blocks.append({'type': 'tool_use', 'name': 'SubagentHandback', 'input': {'message': handback}})
            f.write(json.dumps({'message': {'role': 'assistant', 'content': blocks}}) + '\n')
        d['agent_transcript_path'] = p
    return hook(d)


stop_validator(last='Report\n\nVERDICT: PASS | Pending label thing | 48 tests, page-check ok')
e = PEND()['s1'][0]
check('verdict PASS recorded', e['item'] == 'Pending label thing' and e['verdict'] == 'PASS'
      and e['evidence'] == '48 tests, page-check ok' and e['repo'] == 'bins' and isinstance(e['at'], float))
stop_validator(handback='Findings...\n`VERDICT: FAIL | Bin search filter | empty query returns all bins`\n', sid='s2', cwd=LABELS)
e = PEND()['s2'][0]
check('verdict FAIL recorded from the SubagentHandback message, backticks stripped',
      e['verdict'] == 'FAIL' and e['item'] == 'Bin search filter' and e['evidence'] == 'empty query returns all bins'
      and e['repo'] == 'labels')
stop_validator(final='x\nVERDICT: PASS | From transcript text | ev', sid='s3')
check('verdict from the last transcript text', PEND()['s3'][0]['item'] == 'From transcript text')
before = json.dumps(PEND(), sort_keys=True)
stop_validator(last='All good, no verdict line here.', sid='s4')
stop_validator(last='VERDICT: PASS | Not last | e\nand then more text', sid='s4')
stop_validator(last='VERDICT: PASS | Wrong agent | e', sid='s4', agent='implementer')
check('a report without the verdict line (or not last, or not a validator) records nothing',
      json.dumps(PEND(), sort_keys=True) == before)
check('log: verdict lines', any(l[20:].startswith('daylog verdict s1') for l in log())
      and any('no VERDICT line' in l for l in log()))
stop_validator(last='VERDICT: PASS | pending LABEL thing | newer', sid='s1')
check('same item again replaces, not duplicates', len(PEND()['s1']) == 1 and PEND()['s1'][0]['evidence'] == 'newer')
switch(False)
stop_validator(last='VERDICT: PASS | Switch off | e', sid='s5')
check('switch off: nothing recorded', 's5' not in PEND())
switch(True)

# ---- Stop check ----
def stop(sid='s1', active=False):
    return hook(dict(hook_event_name='Stop', session_id=sid, stop_hook_active=active, cwd=BINS))


check('Stop with no pending item allows', stop('nobody') is None)
out = stop('s1')
check('Stop blocks when the entry is missing, with the command',
      out and out['decision'] == 'block' and out['reason'].startswith('Write the day log entry for pending LABEL thing: claude-daylog add --repo bins --kind done --text ')
      and "'pending LABEL thing | task | PASS | evidence: newer'" in out['reason'])
check('PASS command exact', out['reason'].endswith("claude-daylog add --repo bins --kind done --text 'pending LABEL thing | task | PASS | evidence: newer'"))
out = stop('s2')
check('FAIL item: kind kicked, gap', out and '--repo labels --kind kicked' in out['reason'] and 'FAIL | gap: empty query returns all bins' in out['reason']
      and out['reason'].endswith("--text 'Bin search filter | task | FAIL | gap: empty query returns all bins'"))
cli('add', '--repo', 'bins', '--kind', 'done', '--text', ' Pending Label Thing  | bug | PASS | evidence: ok')
check('Stop allows once written (case and spaces ignored) and drops it', stop('s1') is None and 's1' not in PEND())
cli('add', '--repo', 'labels', '--kind', 'done', '--text', 'Bin search filter | feature | PASS | evidence: wrong section')
check('an entry in the wrong subsection or repo does not count; stop_hook_active still checks and counts as the 2nd block', stop('s2', active=True) is not None)
check('gives up after 2 blocks: allows and drops', stop('s2') is None and 's2' not in PEND())
check('log: block and give up lines', any('daylog block s2' in l for l in log()) and any('gave up on Bin search filter' in l for l in log()))
# a Stop in another session does not touch this one
stop_validator(last='VERDICT: PASS | Other | e', sid='sx')
check('other sessions are left alone', stop('sy') is None and 'sx' in PEND())
# errors allow
keep = open(os.path.join(KIT, 'state.json')).read()
open(os.path.join(KIT, 'state.json'), 'w').write('{broken')
check('broken state file: allows', stop('sx') is None)
open(os.path.join(KIT, 'state.json'), 'w').write(keep)
r = subprocess.run([sys.executable, DL, '--hook'], input='not json', capture_output=True, text=True, env=ENV)
check('bad input allows', r.returncode == 0 and not r.stdout.strip())

# ---- SessionStart ----
def start(source, cwd=BINS, sid='c1'):
    return hook(dict(hook_event_name='SessionStart', session_id=sid, source=source, cwd=cwd))


cli('open', '--repo', 'bins', '--item', 'Bulk edit | feature | state: grilling round 2')
open(cli('state-path', '--repo', 'bins')[1], 'w').write('# Orchestrator state: bins\nbranch: orchestrator\nnext command: start validator\n')
out = start('clear')
ctx = out['hookSpecificOutput']['additionalContext']
check('clear: lead line, state file and Open items',
      out['hookSpecificOutput']['hookEventName'] == 'SessionStart'
      and ctx.startswith('Restored after /clear (Sttark orchestrator):') and 'next command: start validator' in ctx
      and '- Bulk edit | feature | state: grilling round 2' in ctx)
check('startup, resume and compact: nothing', all(start(s) is None for s in ('startup', 'resume', 'compact')))
ctx = start('clear', cwd=LABELS)['hookSpecificOutput']['additionalContext']
check('clear in another repo: only its own Open items, no state file', 'Bulk edit' not in ctx and 'X | feature' in ctx
      and 'State file' not in ctx)
check('clear with nothing to restore: nothing', start('clear', cwd=git_repo('empty')) is None)
switch(False)
check('switch off: nothing', start('clear') is None)
switch(True)

# ---- inline guard exemption ----
def guard(cmd, sid='g1'):
    r = subprocess.run([sys.executable, GUARD], input=json.dumps(dict(hook_event_name='PreToolUse', session_id=sid,
                       tool_name='Bash', tool_input={'command': cmd})), capture_output=True, text=True, env=ENV)
    return 'deny' in r.stdout


check('guard: claude-daylog commands are never lookups', not any(guard(c) for c in [
    'claude-daylog add --repo x --kind done --text "a | b; c"'] * 5 + ['claude-daylog show', '~/.local/bin/claude-daylog open --item x',
    'timeout 5 claude-daylog path --create', 'claude-daylog show && claude-daylog path']))
check('guard: claude-daylog with another lookup still counts', guard('claude-daylog show; cat a', 'g2') is False
      and guard('claude-daylog show; cat a', 'g2') is False and guard('claude-daylog show; cat a', 'g2') is True)
check('guard: a long run is still denied next to it', guard('claude-daylog show; make') is True)

# ---- install ----
home = os.path.join(tmp, 'home')
ikit = os.path.join(tmp, 'ikit')
os.makedirs(os.path.join(home, '.claude'))
shutil.copytree(HOOKS, os.path.join(ikit, 'hooks'))
SET = os.path.join(home, '.claude', 'settings.json')
json.dump({'hooks': {'SubagentStop': [{'hooks': [{'type': 'command', 'command': 'other-hook.sh'}]}],
                     'Stop': [{'hooks': [{'type': 'command', 'command': 'other-stop.sh'}]}]}}, open(SET, 'w'))
IENV = dict(os.environ, HOME=home)
IENV.pop('STTARK_KIT_DIR', None)


def install(*args):
    return subprocess.run([sys.executable, os.path.join(ikit, 'hooks', 'install-hooks.py')] + list(args),
                          capture_output=True, text=True, env=IENV).stdout.strip()


def entries(event):
    return [g for g in json.load(open(SET)).get('hooks', {}).get(event, [])
            if any('daylog.py' in h['command'] for h in g['hooks'])]


def cmds(event):
    return [h['command'] for g in json.load(open(SET)).get('hooks', {}).get(event, []) for h in g['hooks']]


install()
check('switch off: no daylog entries', all(entries(e) == [] for e in ('SubagentStop', 'Stop', 'SessionStart')))
check('--status daylog false', json.loads(install('--status'))['daylog'] is False)
stop_before = cmds('Stop')
out = install('--orchestrator', 'on')
check('--orchestrator on: output ends with daylog on, rotation on', out.endswith('daylog on, rotation on, prod on'))
sg, st, ss = entries('SubagentStop'), entries('Stop'), entries('SessionStart')
check('SubagentStop: one entry, matcher validator, quoted command with --hook',
      len(sg) == 1 and sg[0]['matcher'] == 'validator' and sg[0]['hooks'][0]['command'].startswith('"')
      and sg[0]['hooks'][0]['command'].endswith('daylog.py" --hook'))
check('Stop: one entry, no matcher; SessionStart: one entry, matcher clear',
      len(st) == 1 and 'matcher' not in st[0] and len(ss) == 1 and ss[0]['matcher'] == 'clear')
check('--status daylog true', json.loads(install('--status'))['daylog'] is True)
check('the kit own Stop hook (working rules --check, async) and other Stop hooks are unaffected',
      any(c.endswith('working-rules-hook.py" --check') for c in cmds('Stop')) and 'other-stop.sh' in cmds('Stop'))
install()
check('launch run keeps one entry each', len(entries('SubagentStop')) == 1 and len(entries('Stop')) == 1
      and len(entries('SessionStart')) == 1)
check('other hooks stay in order', cmds('Stop')[0] == 'other-stop.sh' and cmds('SubagentStop')[0] == 'other-hook.sh')
out = install('--orchestrator', 'off')
check('--orchestrator off: removed, output says daylog off, rotation off', out.endswith('daylog off, rotation off, prod off')
      and all(entries(e) == [] for e in ('SubagentStop', 'Stop', 'SessionStart')))
check('other Stop and SubagentStop hooks left alone', cmds('Stop')[0] == 'other-stop.sh' and 'other-hook.sh' in cmds('SubagentStop'))
check('the working-rules Stop hook is still there after off', any('working-rules-hook.py' in c for c in cmds('Stop')))
install('--orchestrator', 'on')
install('--remove')
check('--remove removes them', all(entries(e) == [] for e in ('SubagentStop', 'Stop', 'SessionStart')))

# ---- permission allow rule ----
RULE = 'Bash(claude-daylog:*)'


def perms():
    return json.load(open(SET)).get('permissions')


def raw():
    return json.load(open(SET))


check('allow: removed after --remove, and no permissions key was left behind', 'permissions' not in raw())
install('--orchestrator', 'on')
check('allow: added once with the switch on, permissions created', perms() == {'allow': [RULE]})
install()
install('--orchestrator', 'on')
check('allow: not duplicated on launch or a second on', perms()['allow'].count(RULE) == 1)
check('--status daylog_allow true', json.loads(install('--status'))['daylog_allow'] is True)
install('--orchestrator', 'off')
check('allow: gone with the switch off, empty permissions the kit made is dropped',
      'permissions' not in raw() and json.loads(install('--status'))['daylog_allow'] is False)
d = raw()
d['permissions'] = {'allow': ['Bash(git status:*)'], 'deny': ['Bash(rm:*)']}
json.dump(d, open(SET, 'w'))
install('--orchestrator', 'on')
check('allow: own rules kept, ours appended', perms() == {'allow': ['Bash(git status:*)', RULE], 'deny': ['Bash(rm:*)']})
install('--orchestrator', 'off')
check('allow: off removes only ours; own allow and deny untouched', perms() == {'allow': ['Bash(git status:*)'], 'deny': ['Bash(rm:*)']})
install('--orchestrator', 'on')
install('--remove')
check('allow: --remove removes only ours', perms() == {'allow': ['Bash(git status:*)'], 'deny': ['Bash(rm:*)']})
d = raw()
d['permissions'] = {'allow': [], 'deny': ['Bash(rm:*)']}
json.dump(d, open(SET, 'w'))
install('--orchestrator', 'on')
install('--orchestrator', 'off')
check('allow: a person own empty allow list stays empty', perms() == {'allow': [], 'deny': ['Bash(rm:*)']})
d = raw()
d.pop('permissions')
json.dump(d, open(SET, 'w'))
install('--orchestrator', 'on')
install('--orchestrator', 'off')

# the person's own copy of the rule is never removed
d = raw()
d['permissions'] = {'allow': [RULE, 'Bash(git status:*)']}
json.dump(d, open(SET, 'w'))
for args in (('--orchestrator', 'on'), (), (), ('--orchestrator', 'on'), ('--orchestrator', 'off'), (), ('--remove',), ()):
    install(*args)
    if perms() != {'allow': [RULE, 'Bash(git status:*)']}:
        break
check('allow: the person own rule survives on, launches, off and --remove', perms() == {'allow': [RULE, 'Bash(git status:*)']})
# the kit added it, then it is removed even if other rules came after
install('--orchestrator', 'off')
d = raw()
d['permissions'] = {'allow': ['Bash(git status:*)']}
json.dump(d, open(SET, 'w'))
install('--orchestrator', 'on')
d = raw()
d['permissions']['allow'].append('Bash(ls:*)')
json.dump(d, open(SET, 'w'))
install()
install('--orchestrator', 'off')
check('allow: the rule the kit added is removed, later own rules stay', perms() == {'allow': ['Bash(git status:*)', 'Bash(ls:*)']})
d = raw()
d.pop('permissions')
json.dump(d, open(SET, 'w'))
baks = len([f for f in os.listdir(os.path.dirname(SET)) if f.startswith('settings.json.bak-effort-')])
install('--orchestrator', 'on')
install('--orchestrator', 'off')
check('save: backups made in one second do not overwrite each other',
      len([f for f in os.listdir(os.path.dirname(SET)) if f.startswith('settings.json.bak-effort-')]) >= baks + 2)

# ---- I28: a worktree uses the main repo's name ----
def git(*a, cwd):
    subprocess.run(['git', '-C', cwd] + list(a), check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t'))


MAIN = git_repo('mainrepo')
git('commit', '--allow-empty', '-q', '-m', 'x', cwd=MAIN)
WT = os.path.join(tmp, 'feature-wt')
git('worktree', 'add', '-q', '-b', 'feat', WT, cwd=MAIN)
os.makedirs(os.path.join(MAIN, 'sub'))
for where, label in ((MAIN, 'main repo'), (os.path.join(MAIN, 'sub'), 'main repo subfolder'), (WT, 'worktree')):
    cli('add', '--kind', 'done', '--text', 'WT %s | chore | PASS | evidence: e' % label, cwd=where)
heads = re.findall(r'^## (.*)$', day(), re.M)
check('worktree: section is the main repo name, not the worktree folder', 'mainrepo' in heads and 'feature-wt' not in heads)
check('worktree: all three runs land in one section', day().split('## mainrepo\n')[1].split('\n## ')[0].count('| WT ') == 3)
check('worktree: --repo default and show work from the worktree', 'WT worktree' in cli('show', cwd=WT)[1] or 'WT worktree' in day())

# ---- rotation install ----
def rot():
    return [c for c in cmds('UserPromptSubmit') if 'rotation-hook.py' in c]


check('rotation: none after --remove; --status rotation false', rot() == [] and json.loads(install('--status'))['rotation'] is False)
def others():
    return [c for c in cmds('UserPromptSubmit') if 'rotation-hook.py' not in c and 'inline-guard.py' not in c and 'prod-guard.py' not in c]


install()
other_ups = others()
install('--orchestrator', 'on')
check('rotation: one quoted entry with the switch on; --status true',
      len(rot()) == 1 and rot()[0].startswith('"') and rot()[0].endswith('rotation-hook.py"')
      and json.loads(install('--status'))['rotation'] is True)
install()
check('rotation: launch run keeps one copy', len(rot()) == 1)
check('rotation: other UserPromptSubmit hooks unchanged', others() == other_ups)
install('--orchestrator', 'off')
check('rotation: removed with the switch off', rot() == [] and others() == other_ups)
install('--orchestrator', 'on')
install('--remove')
check('rotation: --remove removes it', rot() == [])

shutil.rmtree(tmp, ignore_errors=True)
print('\n%d passed, %d failed' % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
