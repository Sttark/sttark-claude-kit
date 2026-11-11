"""Test the automatic capture of questions and agent findings (Resources/hooks/daylog.py hooks), the restore
after /clear and the rotation message, on copies only: a temp kit folder, a temp log, temp git repos and fake
transcripts. No model calls. Run: /usr/bin/python3 tools/capture-test.py"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, 'Resources', 'hooks')
DL = os.path.join(HOOKS, 'daylog.py')
ROT = os.path.join(HOOKS, 'rotation-hook.py')
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


tmp = tempfile.mkdtemp(prefix='capture-test-')
KIT = os.path.join(tmp, 'kit')
LOG = os.path.join(tmp, 'kit.log')
os.makedirs(KIT)
json.dump({'orchestrator': True}, open(os.path.join(KIT, 'state.json'), 'w'))
ENV = dict(os.environ, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_DAYLOG_DATE='2026-11-09')
G = dict(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')


def git(*a, cwd):
    subprocess.run(['git', '-C', cwd] + list(a), check=True, capture_output=True, env=dict(os.environ, **G))


def repo(name):
    p = os.path.join(tmp, name)
    os.makedirs(p)
    git('init', '-q', cwd=p)
    return p


BINS = repo('bins')
MAIN = repo('mainrepo')
git('commit', '--allow-empty', '-q', '-m', 'x', cwd=MAIN)
WT = os.path.join(tmp, 'feature-wt')
git('worktree', 'add', '-q', '-b', 'feat', WT, cwd=MAIN)
STATES = os.path.join(KIT, 'orchestrator', 'state')


def hook(data, env=None):
    r = subprocess.run([sys.executable, DL, '--hook'], input=json.dumps(data), capture_output=True, text=True,
                       env=env or ENV)
    check_exit.append(r.returncode)
    return json.loads(r.stdout) if r.stdout.strip() else None


check_exit = []


def pending(name='bins'):
    p = os.path.join(STATES, name + '.pending.md')
    return open(p).read() if os.path.exists(p) else ''


def ask(questions, response, cwd=BINS):
    return hook(dict(hook_event_name='PostToolUse', tool_name='AskUserQuestion', session_id='s1', cwd=cwd,
                     tool_input={'questions': questions}, tool_response=response))


# ---- 1. AskUserQuestion ----
Q1 = {'question': 'Should the label count round down or up?', 'header': 'Rounding',
      'options': [{'label': 'Down', 'description': 'whole labels only'}, {'label': 'Up', 'description': 'never short'}]}
ask([Q1], {'questions': [Q1], 'answers': {Q1['question']: 'Down'}})
p = pending()
check('ask: question text verbatim', 'Should the label count round down or up?' in p)
check('ask: options saved', 'Down' in p and 'Up' in p and 'whole labels only' in p)
check('ask: answer saved with a timestamp', 'answer: Down' in p and '2026-11-09' in p)
check('ask: in the Pending with Cole section', '## Pending with Cole' in p)
Q2 = {'question': 'Drop the dark mode toggle?', 'options': [{'label': 'Yes'}, {'label': 'No'}]}
ask([Q2], {'questions': [Q2], 'answers': {}})
check('ask: no answer saved as unanswered', 'Drop the dark mode toggle?' in pending() and 'unanswered' in pending())
Q3 = {'question': 'String shaped answer?', 'options': [{'label': 'A'}]}
ask([Q3], 'User has answered your questions: "String shaped answer?"="A". You can now continue.')
check('ask: string tool response answer found', 'answer: A' in pending())
ask([{'question': 'Denied one?', 'options': []}], 'The user doesn\'t want to proceed with this tool use.')
check('ask: a denied or odd response is unanswered', 'Denied one?' in pending())

# ---- 2. SubagentStop findings ----
def transcript(name, text):
    p = os.path.join(tmp, name)
    with open(p, 'w') as f:
        f.write(json.dumps({'type': 'assistant', 'message': {'role': 'assistant',
                                                             'content': [{'type': 'text', 'text': text}]}}) + '\n')
    return p


long_report = '\n'.join(['Checked the flow.'] + ['- finding %d: something is off' % i for i in range(1, 41)]
                        + ['VERDICT: FAIL | Bin search filter | gap: empty query returns all bins'])
hook(dict(hook_event_name='SubagentStop', session_id='s1', cwd=BINS, agent_type='validator',
          last_assistant_message=long_report, agent_transcript_path=transcript('t1.jsonl', long_report)))
fdir = os.path.join(STATES, 'bins', 'findings')
files = sorted(os.listdir(fdir)) if os.path.isdir(fdir) else []
check('validator: full report in findings/<timestamp>-validator.md',
      len(files) == 1 and files[0].endswith('-validator.md') and 'finding 40' in open(os.path.join(fdir, files[0])).read())
p = pending()
check('validator: state has a pointer and the VERDICT line but not the whole report',
      files and files[0] in p and 'VERDICT: FAIL | Bin search filter' in p and 'finding 40' not in p)
st = json.load(open(os.path.join(KIT, 'state.json')))
check('validator: daylog_pending behavior unchanged', st.get('daylog_pending', {}).get('s1', [{}])[0].get('verdict') == 'FAIL')
check('validator: Findings section', '## Findings' in p)
rep = '\n'.join('line %d of the report' % i for i in range(1, 60))
hook(dict(hook_event_name='SubagentStop', session_id='s1', cwd=BINS, agent_type='Explore',
          last_assistant_message=rep))
files = sorted(os.listdir(fdir))
check('other agent: findings file named with the agent', any(f.endswith('-Explore.md') for f in files))
p = pending()
check('other agent: first 15 lines in state, not line 16', 'line 15 of the report' in p and 'line 16 of the report' not in p)
check('other agent: agent type in the entry', 'Explore' in p)

# ---- 3. plain-text questions at Stop ----
msg = 'Here is the plan.\nIt has three steps.\n\nWhat I need from you:\n- Which printer is the default?\n- Is Friday the deadline?'
hook(dict(hook_event_name='Stop', session_id='s1', cwd=BINS, transcript_path=transcript('t2.jsonl', msg)))
p = pending()
check('stop: What I need from you text saved', 'Which printer is the default?' in p and 'Is Friday the deadline?' in p)
check('stop: saved as unanswered plain text', 'plain text' in p)
n = p.count('Which printer is the default?')
hook(dict(hook_event_name='Stop', session_id='s1', cwd=BINS, transcript_path=transcript('t2.jsonl', msg)))
check('stop: same message twice is saved once', pending().count('Which printer is the default?') == n)
hook(dict(hook_event_name='Stop', session_id='s1', cwd=BINS,
          transcript_path=transcript('t3.jsonl', 'Done with the fix.\nShould I also update the docs?')))
check('stop: a question line alone is saved', 'Should I also update the docs?' in pending())
before = pending()
hook(dict(hook_event_name='Stop', session_id='s1', cwd=BINS, transcript_path=transcript('t4.jsonl', 'All done. No questions.')))
check('stop: no question, nothing saved', pending() == before)
check('stop: missing transcript does not crash', hook(dict(hook_event_name='Stop', session_id='s1', cwd=BINS,
                                                          transcript_path='/nonexistent/x.jsonl')) is None)

# ---- 4. resolution on the next prompt ----
hook(dict(hook_event_name='UserPromptSubmit', session_id='s1', cwd=BINS, prompt='Use the Zebra. ' + 'x' * 400))
p = pending()
check('prompt: plain-text entries marked answered in prompt at HH:MM',
      'answered in prompt at ' in p and p.count('answered in prompt at ') == 4)
check('prompt: first 300 chars of the prompt saved, not more', 'Use the Zebra. ' + 'x' * 285 in p and 'x' * 286 not in p)
check('prompt: unanswered AskUserQuestion entries are resolved too (4 entries in all)', 'Drop the dark mode toggle?' in p and 'status: unanswered' not in p)

# ---- 5. SessionStart restore ----
def start(source, cwd=BINS):
    return hook(dict(hook_event_name='SessionStart', session_id='n1', source=source, cwd=cwd))


out = start('clear')
ctx = out['hookSpecificOutput']['additionalContext'] if out else ''
check('clear: Pending with Cole injected', 'Pending with Cole' in ctx and 'Drop the dark mode toggle?' in ctx)
check('clear: findings pointers injected', 'findings' in ctx and '-validator.md' in ctx)
check('clear: the instruction is there', 'Raise unanswered items before new work' in ctx)
check('clear: hookEventName SessionStart', out and out['hookSpecificOutput']['hookEventName'] == 'SessionStart')
for s in ('startup', 'compact', 'resume'):
    o = start(s)
    check('%s: also injects' % s, bool(o) and 'Drop the dark mode toggle?' in o['hookSpecificOutput']['additionalContext'])
check('other repo: nothing', start('clear', cwd=tmp) is None)

# ---- cap ----
for i in range(15):
    ask([{'question': 'Big question %d? ' % i + 'y' * 600, 'options': [{'label': 'A'}]}], {'answers': {}})
o = start('clear')
ctx = o['hookSpecificOutput']['additionalContext']
check('cap: injected text is about 4k chars', 0 < len(ctx) <= 4600)
check('cap: unanswered items come first', 'Big question' in ctx)

# ---- keep 20, archive ----
for i in range(30):
    ask([{'question': 'Many %d?' % i, 'options': []}], {'answers': {'Many %d?' % i: 'ok'}})
p = pending()
check('keep: 20 entries in the Pending section', p.split('## Findings')[0].count('\n- [') == 20)
arch = os.path.join(STATES, 'bins.archive.md')
check('keep: older entries moved to the archive file', os.path.exists(arch) and 'Many 0?' in open(arch).read()
      and 'Many 0?' not in p)

# ---- 7. worktree uses the main repo name ----
ask([{'question': 'Worktree question?', 'options': []}], {'answers': {'Worktree question?': 'yes'}}, cwd=WT)
check('worktree: saved under the main repo name', 'Worktree question?' in pending('mainrepo')
      and not os.path.exists(os.path.join(STATES, 'feature-wt.pending.md')))
check('worktree: restore from the worktree', 'Worktree question?' in (start('clear', cwd=WT) or {'hookSpecificOutput': {'additionalContext': ''}})['hookSpecificOutput']['additionalContext'])

# ---- 6. rotation message ----
tr = os.path.join(tmp, 'rot.jsonl')
open(tr, 'w').write(json.dumps({'type': 'assistant', 'message': {'model': 'm', 'usage': {'input_tokens': 130000}}}) + '\n')
r = subprocess.run([sys.executable, ROT], input=json.dumps(dict(session_id='r1', transcript_path=tr, cwd=BINS)),
                   capture_output=True, text=True, env=ENV)
t = json.loads(r.stdout)['hookSpecificOutput']['additionalContext'] if r.stdout.strip() else ''
check('rotation: says questions and findings are saved automatically', 'saved automatically' in t)
check('rotation: names the state file path', os.path.join(STATES, 'bins.md') in t)


# ================= round 2 =================
R2 = repo('round2')
FD2 = os.path.join(STATES, 'round2', 'findings')


def stop_text(text, cwd=R2, name='t'):
    n = [0]
    return hook(dict(hook_event_name='Stop', session_id='s2', cwd=cwd, transcript_path=transcript('r2-%s.jsonl' % name, text)))


def prompt(text, cwd=R2):
    return hook(dict(hook_event_name='UserPromptSubmit', session_id='s2', cwd=cwd, prompt=text))


def ask2(questions, response, event='PostToolUse'):
    return hook(dict(hook_event_name=event, tool_name='AskUserQuestion', session_id='s2', cwd=R2,
                     tool_input={'questions': questions}, tool_response=response))


# ---- P1: only a typed prompt resolves ----
stop_text('Plan ready.\nWhich branch should I use?', name='p1')
NOT_TYPED = ['/clear', '/loop 5m check', 'Result <task-notification> agent done </task-notification>', '<agent-message from=x>hi</agent-message>',
             'Another Claude session sent a message: do x', '[SYSTEM NOTIFICATION] build done', '<side-sessions-event>x</side-sessions-event>',
             '<ci-monitor-event>x</ci-monitor-event>', '<scheduled-task name=a>x</scheduled-task>',
             '<command-name>/foo</command-name>', '', '   \n ']
for t in NOT_TYPED:
    prompt(t)
check('P1: no non-typed prompt resolves anything (%d kinds)' % len(NOT_TYPED), 'answered in prompt' not in pending('round2'))
prompt('Use main.')
check('P1: a typed prompt resolves', 'answered in prompt at ' in pending('round2') and 'Use main.' in pending('round2'))

# ---- P2-a: string answers ----
QA = [{'question': 'Q1 ship it?', 'options': [{'label': 'A1'}]}, {'question': 'Q2 when?', 'options': [{'label': 'A2'}]}]
ask2(QA, 'The user answered: "Q1 ship it?"="A1", "Q2 when?"="A2". Read the answers carefully and continue.')
p = pending('round2')
check('P2-a: "The user answered:" form, two answers', 'answer: A1\n' in p and 'answer: A2\n' in p)
QB = [{'question': 'QB1 ok?', 'options': []}, {'question': 'QB2 where?', 'options': []}]
ask2(QB, 'User has answered your questions: "QB1 ok?"="yes, but \\"only\\" on Fridays", "QB2 where?"="if we did not make this branch, then just steal it". You can now continue.')
p = pending('round2')
check('P2-a: answer with commas and escaped quotes kept whole', 'answer: yes, but \\"only\\" on Fridays\n' in p)
check('P2-a: unescaped comma answer, last one, ends at the final ". "', 'answer: if we did not make this branch, then just steal it\n' in p)
ask2([{'question': 'QC1 who?', 'options': []}], 'Your questions have been answered: "QC1 who?"="she said "no", then left". Continue.')
check('P2-a: "Your questions have been answered:" with embedded quotes', 'answer: she said "no", then left\n' in pending('round2'))
ask2([{'question': 'QD1 dict?', 'options': []}], {'answers': {'QD1 dict?': 'dict wins'}})
check('P2-a: dict path still first', 'answer: dict wins' in pending('round2'))
ask2([{'question': 'QE unanswered?', 'options': []}], {'answers': {}})
prompt('Yes do QE.')
pe = pending('round2')
check('P2-a: an unanswered AskUserQuestion entry is resolved by the next typed prompt',
      'QE unanswered?' in pe and 'Yes do QE.' in pe.split('QE unanswered?')[1])

# ---- P2-b: empty agent_type ----
n0 = len(os.listdir(FD2)) if os.path.isdir(FD2) else 0
for at in ('', None):
    d = dict(hook_event_name='SubagentStop', session_id='s2', cwd=R2, last_assistant_message='prompt suggestion text')
    if at is not None:
        d['agent_type'] = at
    hook(d)
check('P2-b: empty or missing agent_type saves nothing', (len(os.listdir(FD2)) if os.path.isdir(FD2) else 0) == n0
      and 'prompt suggestion text' not in pending('round2'))

# ---- P2-c: noisy question detection ----
before = pending('round2')
for i, t in enumerate(['Fixed.\n```\nx = a if b else c  # why?\n```\nDone.', '## Why did it fail?\nBecause of x.',
                       'What I need from you: nothing. All done.', 'What I need from you\n- Nothing now', 'What I need from you:\nNone.',
                       '| Q | A |\n| why? | because? |', '> quoted question?\nok', '`only code?`\nok']):
    stop_text(t, name='c%d' % i)
check('P2-c: fenced, heading, table, quote, inline-code and "nothing" cases save no entry', pending('round2') == before)
stop_text('All good.\nWhich do you want next?', name='cr')
check('P2-c: a real closing question is still saved', 'Which do you want next?' in pending('round2'))

# ---- P2-d: PostToolUseFailure ----
ask2([{'question': 'Esc question?', 'options': [{'label': 'Y'}]}], None, event='PostToolUseFailure')
check('P2-d: PostToolUseFailure saved as unanswered', 'Esc question?' in pending('round2')
      and 'answer: unanswered' in pending('round2').split('Esc question?')[1].split('\n- [')[0])

# ---- P3: double capture ----
ask2([{'question': 'Which colour for the button?', 'options': []}], {'answers': {}})
stop_text('Done.\nWhich colour for the button?', name='dc')
check('P3: plain-text copy of an open AskUserQuestion is not saved again', pending('round2').count('Which colour for the button?') == 1)

# ---- P3: pruning ----
os.makedirs(FD2, exist_ok=True)
for i in range(60):
    open(os.path.join(FD2, '2020010100%04d-old.md' % i), 'w').write('x')
hook(dict(hook_event_name='SubagentStop', session_id='s2', cwd=R2, agent_type='Explore', last_assistant_message='new report'))
fs = sorted(os.listdir(FD2))
check('P3: findings folder keeps the newest 50', len(fs) == 50 and any(f.endswith('-Explore.md') for f in fs) and '202001010000000-old.md' not in fs)
arch = os.path.join(STATES, 'round2.archive.md')
open(arch, 'w').write(''.join('(Pending with Cole)\n- [2020-01-01 00:00] old %d\n  body\n' % i for i in range(600)))
for i in range(25):
    ask2([{'question': 'overflow %d?' % i, 'options': []}], {'answers': {'overflow %d?' % i: 'ok'}})
a = open(arch).read()
check('P3: archive capped at the newest 500 entries', a.count('\n- [') + (1 if a.startswith('- [') else 0) == 500 and 'old 0\n' not in a and 'old 599' in a)

# ---- P3: resolve with nothing open does not lock or rewrite ----
R3 = repo('round3')
prompt('hello', cwd=R3)
check('P3: no pending file, no lock file made', not os.path.exists(os.path.join(STATES, 'round3.pending.md.lock'))
      and not os.path.exists(os.path.join(STATES, 'round3.pending.md')))
ask([{'question': 'done q?', 'options': []}], {'answers': {'done q?': 'k'}}, cwd=R3)
pp = os.path.join(STATES, 'round3.pending.md')
os.utime(pp, (1000000000, 1000000000))
prompt('another prompt', cwd=R3)
check('P3: nothing open, file not rewritten', int(os.path.getmtime(pp)) == 1000000000)

# ---- P3: transcript fallback ----
def tr_lines(name, rows):
    p = os.path.join(tmp, name)
    with open(p, 'w') as f:
        for role, content in rows:
            f.write(json.dumps({'type': role, 'message': {'role': role, 'content': content}}) + '\n')
    return p


R4 = repo('round4')
T = [{'type': 'text', 'text': 'Old turn.\nOld question here?'}]
rows = [('user', 'first prompt'), ('assistant', T), ('user', 'typed answer'),
        ('assistant', [{'type': 'tool_use', 'name': 'Bash', 'input': {}}]),
        ('user', [{'type': 'tool_result', 'content': 'ok'}])]
hook(dict(hook_event_name='Stop', session_id='s4', cwd=R4, transcript_path=tr_lines('f1.jsonl', rows)))
check('P3: a turn with no new text saves nothing (old text is not re-read)', pending('round4') == '')
rows2 = rows[:3] + [('assistant', [{'type': 'text', 'text': 'New turn.\nNew question here?'}])]
hook(dict(hook_event_name='Stop', session_id='s4', cwd=R4, transcript_path=tr_lines('f2.jsonl', rows2)))
check('P3: text after the last typed message is saved', 'New question here?' in pending('round4') and 'Old question' not in pending('round4'))

# ---- P3: rotation names the findings folder ----
r = subprocess.run([sys.executable, ROT], input=json.dumps(dict(session_id='r2', transcript_path=tr, cwd=BINS)),
                   capture_output=True, text=True, env=ENV)
t = json.loads(r.stdout)['hookSpecificOutput']['additionalContext'] if r.stdout.strip() else ''
check('P3: rotation names the findings folder', os.path.join(STATES, 'bins', 'findings') in t)

# ---- off switch and errors ----
json.dump({'orchestrator': False}, open(os.path.join(KIT, 'state.json'), 'w'))
before = pending()
ask([{'question': 'Off switch?', 'options': []}], {'answers': {}})
check('switch off: nothing saved', pending() == before)
json.dump({'orchestrator': True}, open(os.path.join(KIT, 'state.json'), 'w'))
r = subprocess.run([sys.executable, DL, '--hook'], input=json.dumps(dict(hook_event_name='PostToolUse', tool_name='AskUserQuestion',
                   tool_input='bad', tool_response=None, cwd=BINS)), capture_output=True, text=True, env=ENV)
check('bad input: exit 0', r.returncode == 0)
check('all capture hook runs exited 0', all(c == 0 for c in check_exit))

shutil.rmtree(tmp, ignore_errors=True)
print('\n%d passed, %d failed' % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
