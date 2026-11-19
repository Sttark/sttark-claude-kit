#!/usr/bin/python3
"""Tests what the Kit does with a session's running work before it ends a copy of the session (effort-hook.py
running_agents(), running_work(), copy_work(), keep(), halt_copies(), the prompt hook; wait.py bring_back() and
check()), on copies: a test Kit folder and log (STTARK_KIT_DIR, STTARK_KIT_LOG), a test ~/.claude (STTARK_CLAUDE_DIR)
with made-up records, a stand-in `claude` (a small program built here, that only sleeps) in real screens with test
names, and stand-ins for the Claude app's list of sessions, the session's status and the start of a copy. No session,
screen or server of this Mac is touched, no model is called and nothing is sent.
- what runs: an agent Claude Code has not marked finished, with a record written in the last 15 minutes; not one that
  is finished, quiet, or stopped (TaskStop: the session's record says killed); one continued after it was stopped
  runs again; a Monitor until its end notice, its TaskStop or its timeout; a background command while its file is
  open and a record names it as sent to the background (a command in the turn has a file too), or, with no file
  list (the Mac shuts down), until its end notice; one copy's work by the copy that wrote its record last, from
  that copy's start; each agent's last step, whether it had a result, and the folder its last command named;
- keep(): a handover waits while the server's copy may still fail (its first 30 seconds) and the Kit's copy still
  works (`handover ... waits`, once); then it ends the copy, logs what stopped with it (`work kill`, with the agents'
  ids) and keeps the list for the session; an archive ends it at once, the same way; a copy with nothing at work ends
  at once and gets no list (tools/handover-test.py tests the wait for a turn and for a prompt the Kit typed in);
- the Mac shuts down (halt_copies()): the same, for each copy it ends;
- the session's next prompt carries the list once (`work told`), with each agent's id, its folder, its last step and
  SendMessage;
- a bring-back waits while the session's agents, background commands or Monitors run: `work defer` once, and again
  when the work changes; when the work ends it comes back (`work done`); after 2 hours it comes back, and its own
  message says what stopped; a list the session did not get yet goes in that message too; a turn still waits as
  before; an archived session's own copy is ended, and the message says so;
- claude-wait --now while the work runs: the wait comes back when the work ends, and the person reads why;
- a note of the person's own reply (watch.py) goes the same two ways, once: with the next prompt, or in a
  bring-back's message (`watch  told`).
Run from the repo root: /usr/bin/python3 tools/work-test.py"""
import importlib.util, io, json, os, shutil, subprocess, sys, tempfile, time
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, 'Resources', 'hooks')
T = tempfile.mkdtemp(prefix='kit-work-')
KIT, LOG, CLAUDE = os.path.join(T, 'kit'), os.path.join(T, 'log'), os.path.join(T, 'claude')
os.makedirs(KIT)
os.makedirs(os.path.join(CLAUDE, 'sessions'))
os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_CLAUDE_DIR=CLAUDE, STTARK_EFFORT_DRY='1',
                  STTARK_WAIT_DRY='')
for k in ('CLAUDE_CODE_BRIDGE_SESSION_ID', 'CLAUDE_PID', 'STTARK_WAIT_DRY'):
    os.environ.pop(k, None)
fails = 0


def check(what, ok, detail=''):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what + ('' if ok else '  -- %s' % (detail,)))
    fails += not ok


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HOOKS, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def log_lines(tag='work   '):
    try:
        return [l[20:] for l in open(LOG).read().splitlines() if l[20:].startswith(tag)]
    except OSError:
        return []


def state(edit=None):
    p = os.path.join(KIT, 'state.json')
    try:
        s = json.load(open(p))
    except (OSError, ValueError):
        s = {}
    if edit:
        edit(s)
        json.dump(s, open(p, 'w'))
    return s


eh = load('effort-hook')
NOW = time.time()
PID = os.getpid() % 1000


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S.', time.gmtime(t)) + '%03dZ' % int((t % 1) * 1000)


# --- made-up records ------------------------------------------------------------------------------------------------
def entry(t, typ, content, entry='cli', cwd='/sample/src', **kw):
    x = {'type': typ, 'timestamp': iso(t), 'entrypoint': entry, 'cwd': cwd, 'sessionId': 'x',
         'message': {'role': 'assistant' if typ == 'assistant' else 'user', 'content': content}}
    x.update(kw)
    return x


def call(t, use, name, inp, **kw):
    return entry(t, 'assistant', [{'type': 'tool_use', 'id': use, 'name': name, 'input': inp}], **kw)


def result(t, use, text, tur=None, **kw):
    x = entry(t, 'user', [{'tool_use_id': use, 'type': 'tool_result', 'content': text}], **kw)
    if tur is not None:
        x['toolUseResult'] = tur
    return x


def notice(t, task, status, **kw):
    return entry(t, 'user', '<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>toolu_x</tool-use-id>\n'
                            '<status>%s</status>\n<summary>It ended</summary>\n</task-notification>' % (task, status), **kw)


def write(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        for x in entries:
            f.write(json.dumps(x, separators=(',', ':')) + '\n')  # as Claude Code writes its records
    t = max([eh.iso_time(x.get('timestamp')) for x in entries] or [NOW])
    os.utime(path, (t, t))


def agent(tp, aid, desc, entries, finished=False, shape='background'):
    sub = os.path.join(tp[:-len('.jsonl')], 'subagents')
    write(os.path.join(sub, 'agent-%s.jsonl' % aid), entries)
    meta = {'agentType': 'general-purpose', 'description': desc, 'requestShape': shape}
    if finished:
        meta['finished'] = True
    json.dump(meta, open(os.path.join(sub, 'agent-%s.meta.json' % aid), 'w'))


def session(cid, main, agents):
    tp = os.path.join(CLAUDE, 'projects', '-sample-src', cid + '.jsonl')
    write(tp, main)
    for a in agents:
        agent(tp, *a)
    return tp


# --- what runs --------------------------------------------------------------------------------------------------------
CID1 = 'a0000000-0000-4000-8000-000000000001'
LABELS = 'ab0000000000label1'
tp1 = session(CID1, [
    entry(NOW - 3000, 'user', 'Build the bottle labels'),
    call(NOW - 500, 'toolu_c1', 'Bash', {'command': 'npm test', 'description': 'Run the tests', 'run_in_background': True}),
    result(NOW - 499, 'toolu_c1', 'Command running in background with ID: bc1', {'backgroundTaskId': 'bc1'}),
    call(NOW - 600, 'toolu_c2', 'Bash', {'command': 'npm run build', 'description': 'Build it', 'run_in_background': True}),
    result(NOW - 599, 'toolu_c2', 'Command running in background with ID: bc2', {'backgroundTaskId': 'bc2'}),
    notice(NOW - 50, 'bc2', 'completed'),
    call(NOW - 300, 'toolu_m1', 'Monitor', {'description': 'CI checks on the pull request', 'command': 'gh pr checks', 'timeout_ms': 1800000}),
    result(NOW - 299, 'toolu_m1', 'Monitor started (task bm1, expires in 30m unless the source ends first)',
           {'taskId': 'bm1', 'timeoutMs': 1800000, 'persistent': False}),
    call(NOW - 400, 'toolu_m2', 'Monitor', {'description': 'Deploy log', 'command': 'tail -f x', 'timeout_ms': 1800000}),
    result(NOW - 399, 'toolu_m2', 'Monitor started (task bm2, expires in 30m unless the source ends first)',
           {'taskId': 'bm2', 'timeoutMs': 1800000, 'persistent': False}),
    notice(NOW - 100, 'bm2', 'completed'),
    call(NOW - 4000, 'toolu_m3', 'Monitor', {'description': 'An old watch', 'command': 'x', 'timeout_ms': 300000}),
    result(NOW - 3999, 'toolu_m3', 'Monitor started (task bm3, expires in 5m unless the source ends first)',
           {'taskId': 'bm3', 'timeoutMs': 300000, 'persistent': False}),
    call(NOW - 200, 'toolu_m4', 'Monitor', {'description': 'A stopped watch', 'command': 'x', 'timeout_ms': 600000}),
    result(NOW - 199, 'toolu_m4', 'Monitor started (task bm4, expires in 10m unless the source ends first)',
           {'taskId': 'bm4', 'timeoutMs': 600000, 'persistent': False}),
    call(NOW - 150, 'toolu_s4', 'TaskStop', {'task_id': 'bm4'}),
    notice(NOW - 110, 'ab0000000000stop4', 'killed'),
    notice(NOW - 900, 'ab0000000000again', 'killed'),
], [
    (LABELS, 'Bottle labels with a barcode', [
        entry(NOW - 900, 'user', 'Add bottle labels'),
        call(NOW - 60, 'toolu_a1', 'Bash', {'command': 'cd ~/src/sample-labels && npm run check 2>&1 | tail -20'})]),
    ('ab0000000000quiet', 'An old review', [entry(NOW - 3600, 'user', 'Review it')]),
    ('ab0000000000done1', 'A finished one', [entry(NOW - 60, 'user', 'Do it')], True),
    ('ab0000000000stop4', 'A stopped one', [entry(NOW - 120, 'user', 'Stop me')]),
    ('ab0000000000again', 'Continued after a stop', [entry(NOW - 1000, 'user', 'x'), entry(NOW - 30, 'user', 'go on')]),
    ('ab0000000000srv01', "The server's agent", [entry(NOW - 20, 'user', 'x', entry='sdk-cli')]),
    ('ab0000000000early', 'From an earlier copy', [entry(NOW - 200, 'user', 'x')]),
])
ids = lambda items: sorted(w['id'] for w in items)
ra = {a['aid'] for a in eh.running_agents(tp1, set(), NOW)}
check('running agents: not finished and written in the last 15 minutes; not a finished, quiet or stopped one; one '
      'continued after its stop runs again', ra == {LABELS, 'ab0000000000again', 'ab0000000000srv01', 'ab0000000000early'}, ra)
w = eh.running_work(tp1, NOW, tasks={'bc1', 'bfg1'})
check('every copy: its agents, its background command (not one that ended, not a command of the turn), and its '
      'Monitor (not one that ended, ran out or was stopped)',
      ids(w['agents']) == sorted([LABELS, 'ab0000000000again', 'ab0000000000srv01', 'ab0000000000early'])
      and ids(w['commands']) == ['bc1'] and ids(w['monitors']) == ['bm1'], w)
check('a command and a Monitor say what they are', w['commands'][0]['what'] == 'Run the tests'
      and w['monitors'][0]['what'] == 'CI checks on the pull request')
a = next(x for x in w['agents'] if x['id'] == LABELS)
check("an agent: its last step, with no result yet, and the folder its last command named",
      a['open'] and a['last'].startswith('ran: cd ~/src/sample-labels && npm run check')
      and a['folder'] == os.path.expanduser('~/src/sample-labels') and a['cwd'] == '/sample/src', a)
w = eh.running_work(tp1, NOW, tasks={'bc1'}, entry='cli')
check("the Kit's copy only: not the agent the server's copy writes", 'ab0000000000srv01' not in ids(w['agents']), ids(w['agents']))
w = eh.running_work(tp1, NOW, tasks={'bc1'}, entry='cli', since=NOW - 100)
check('from that copy\'s start: not what an earlier copy left', ids(w['agents']) == sorted([LABELS, 'ab0000000000again'])
      and not w['commands'] and not w['monitors'], w)
w = eh.running_work(tp1, NOW, tasks=False)
check('with no file list (the Mac shuts down): a command counts until its record says it ended', ids(w['commands']) == ['bc1'], w)
check('the words for a log line', eh.work_words({'agents': [a], 'commands': [], 'monitors': []})
      == '1 agent (%s "Bottle labels with a barcode")' % LABELS)
check('no quote or semicolon of a description in a log line', eh.work_words(
    {'agents': [], 'commands': [{'id': 'b1', 'what': 'Run "x"; then y'}], 'monitors': []}) == "1 background command (b1 \"Run 'x', then y\")")

# --- keep(): the Kit's copy ends at once, and the session gets the list -------------------------------------------
src = os.path.join(T, 'claude.c')
open(src, 'w').write('#include <unistd.h>\nint main(void) { for (;;) pause(); }\n')
fake = os.path.join(T, 'bin', 'claude')
os.makedirs(os.path.dirname(fake))
if subprocess.run(['/usr/bin/cc', '-o', fake, src], capture_output=True).returncode:
    print('skip  the stand-in claude could not be built (no C compiler): keep() and the halt are not tested')
    fake = None


def kit_copy(cid):
    """A stand-in for the Kit's copy of a chat: claude --resume <cid> in screen kit-<first 8>, as start_screen() runs it."""
    name = 'kit-' + cid[:8]
    subprocess.run(['/usr/bin/screen', '-dmS', name, fake, '--resume', cid, '--remote-control'])
    for _ in range(40):
        if '--resume ' + cid in subprocess.run(['ps', '-axww', '-o', 'command='], capture_output=True, text=True).stdout:
            break
        time.sleep(0.1)
    time.sleep(1.1)  # its start, to the second, is before what it writes next
    return name


def up(cid):
    return '--resume ' + cid in subprocess.run(['ps', '-axww', '-o', 'command='], capture_output=True, text=True).stdout


ENV = 'env_01TESTwork'
chats = []
eh.all_chats = lambda pages=5: chats
eh.chat_events = lambda sid, pages=5: []
eh.send = lambda sid, level: (200, 'ok', 'rid')
eh.archived = lambda chats: None
eh.open_tasks = lambda: {}
server_line = []
# the process list keep() reads: a server, the server's copy of a test session, and this test's own stand-ins (no
# other process of this Mac, so keep() never sees a real session)
eh.processes = lambda: ('/sample/claude rc --permission-mode bypassPermissions\n' + ''.join(server_line) + ''.join(
    l + '\n' for l in subprocess.run(['ps', '-axo', 'command'], capture_output=True, text=True).stdout.splitlines()
    if '--resume t%03dwk1' % PID in l))

if fake:
    CID2 = 't%03dwk1a-0000-4000-8000-000000000002' % PID   # kit-t<3 digits>wk1a: only this test's screens
    CSE2 = 'cse_01TESTworkHandover'
    name2 = kit_copy(CID2)
    t = time.time()
    tp2 = session(CID2, [entry(t - 3000, 'user', 'Make the labels')], [
        (LABELS, 'Bottle labels with a barcode', [entry(t, 'user', 'Add bottle labels'),
                                                  call(t + 0.5, 'toolu_a1', 'Bash', {'command': 'cd ~/src/sample-labels && npm run check'})])])
    tp2b = session('t%03dwk1b-0000-4000-8000-000000000003' % PID, [entry(t - 3000, 'user', 'x')], [])
    state(lambda s: s.update(paused=True, sessions={CSE2: {'title': 'Bottle labels', 'transcript': tp2, 'title_at': 1e12}},
                             keep={'envs': [ENV], 'woke': {}, 'alone': {CSE2: {'transcript': tp2, 'title': 'Bottle labels', 'at': t - 100}}}))
    chats[:] = [{'id': CSE2, 'title': 'Bottle labels', 'status': 'active', 'environment_id': ENV, 'environment_kind': 'bridge'}]
    server_line[:] = ['/sample/claude --print --sdk-url https://api.anthropic.com/v1/code/sessions/%s --session-id %s\n' % (CSE2, CSE2)]
    eh.keep()
    time.sleep(0.5)
    waits = [l for l in log_lines('handover') if ' waits: ' in l]
    check('handover while its agent runs and the server\'s copy may still fail: it waits, with one `handover ... waits` line',
          up(CID2) and len(waits) == 1 and waits[0].startswith('handover %s "Bottle labels" waits: the server runs it now, but the '
                                                                "Kit's copy still works (1 agent (%s" % (CSE2, LABELS))
          and not [l for l in log_lines() if l.startswith('work   kill')]
          and CSE2 in state()['keep']['alone'], waits)
    eh.keep()
    check('the next check waits too, and logs nothing new', up(CID2) and len([l for l in log_lines('handover') if ' waits: ' in l]) == 1)
    state(lambda s: s['keep']['alone'][CSE2]['hold'].update(since=time.time() - eh.HANDOVER_GRACE - 5))
    eh.keep()
    time.sleep(0.5)
    check('30 seconds after the server\'s copy started, it holds the session: the handover ends the Kit\'s copy, also while '
          'its agent runs', not up(CID2) and not eh.screen_ids(name2))
    kills = [l for l in log_lines() if l.startswith('work   kill')]
    check('handover: a `work kill` line with the session, its name and each agent\'s id',
          len(kills) == 1 and kills[0].startswith('work   kill %s "Bottle labels" handover: 1 agent (%s "Bottle labels with a barcode")' % (CSE2, LABELS))
          and kills[0].endswith('the session is told at its next prompt'), kills)
    check('handover: still logged as a handover, with how long it waited', any(
        l.startswith('handover %s "Bottle labels" the server runs it now; quit its own copy (%s) after it waited 3' % (CSE2, name2))
        for l in log_lines('handover')), log_lines('handover'))
    kept = (state().get('sessions') or {}).get(CSE2, {}).get('stopped') or []
    text = kept[0]['text'] if kept else ''
    check('the list kept for the session: why, each agent\'s id and task, its folder, its last step, and SendMessage',
          len(kept) == 1 and text.startswith('[Sttark Claude Kit] Work of this session stopped at ') and 'the server started its own copy' in text
          and '- Agent %s, "Bottle labels with a barcode", working in %s' % (LABELS, os.path.expanduser('~/src/sample-labels')) in text
          and 'with no result yet: ran: cd ~/src/sample-labels && npm run check' in text and 'SendMessage (to: %s)' % LABELS in text, text)

    # the session's next prompt carries it, once
    def prompt(cse, words, tp):
        env = dict(os.environ, CLAUDE_CODE_BRIDGE_SESSION_ID=cse)
        r = subprocess.run([sys.executable, os.path.join(HOOKS, 'effort-hook.py')], input=json.dumps(
            {'hook_event_name': 'UserPromptSubmit', 'prompt': words, 'transcript_path': tp, 'session_id': 'x'}),
            capture_output=True, text=True, env=env, timeout=60)
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])['hookSpecificOutput']['additionalContext']
        except (ValueError, IndexError, KeyError):
            return ''
    got = prompt(CSE2, 'What is the status of the labels?', tp2)
    check('its next prompt carries the list', text and text in got, got[:300])
    check('once: the list is gone, and a `work told` line says so', not (state()['sessions'][CSE2].get('stopped'))
          and any(l.startswith('work   told %s "Bottle labels" what stopped at ' % CSE2) and 'with its next prompt' in l for l in log_lines()))
    check('the prompt after that carries nothing more', 'Work of this session stopped' not in prompt(CSE2, 'Thanks', tp2))
    # a note of the person's own reply where it watches (watch.py queue_note()) goes the same way, once
    state(lambda s: s['sessions'][CSE2].update(replied=[{
        'at': time.time(), 'ids': ['m-own'], 'title': 'Bottle labels', 'where': 'in the email thread "Bottle labels proof"',
        'text': '[Sttark Claude Kit] The person replied themselves in a place this session watches. Your records do not '
                'show this reply:\n- In the email thread "Bottle labels proof", Wed Nov 18 2:30 PM, the person sent it: '
                '"The proof is approved."'}]))
    got = prompt(CSE2, 'Any news on the labels?', tp2)
    check("a note of the person's own reply goes with the next prompt, once, with a `watch  told` line",
          'The person replied themselves' in got and '"The proof is approved."' in got
          and not state()['sessions'][CSE2].get('replied') and 'The person replied themselves' not in prompt(CSE2, 'Thanks', tp2)
          and any(l.startswith('watch  told %s "Bottle labels" of your reply in the email thread "Bottle labels proof", '
                               'with its next prompt' % CSE2) for l in log_lines('watch  ')), got[:300])

    # after the handover only the server's copy runs: what the ended Kit's copy wrote last is not its work, also when
    # that copy wrote it after the server's copy started (the server's copy runs nothing, so a bring-back need not wait)
    srv = subprocess.Popen([fake, '--print', '--sdk-url', 'https://api.anthropic.com/v1/code/sessions/' + CSE2, '--session-id', CSE2])
    time.sleep(1.2)
    with open(os.path.join(tp2[:-len('.jsonl')], 'subagents', 'agent-%s.jsonl' % LABELS), 'a') as f:
        f.write(json.dumps(entry(time.time(), 'user', 'one more line from the old copy'), separators=(',', ':')) + '\n')
    work, procs = eh.copy_work(tp2, CSE2)
    check("only the server's copy runs: the old copy's agent is not counted", list(procs.values()) == ['server']
          and not eh.work_ids(work), (procs, eh.work_words(work)))
    srv.kill()
    srv.wait()

    # a stand-down: the same; a copy with nothing at work gets no list
    CID3, CSE3 = 't%03dwk1c-0000-4000-8000-000000000004' % PID, 'cse_01TESTworkIdle'
    name3 = kit_copy(CID3)
    tp3 = session(CID3, [entry(time.time() - 3000, 'user', 'x')], [])
    state(lambda s: s['keep']['alone'].update({CSE3: {'transcript': tp3, 'title': 'Idle one', 'at': time.time() - 100}}))
    chats[:] = [{'id': CSE3, 'title': 'Idle one', 'status': 'active', 'environment_id': ENV, 'environment_kind': 'bridge'}]
    server_line[:] = ['/sample/claude --print --sdk-url https://api.anthropic.com/v1/code/sessions/%s\n' % CSE3]
    n = len(log_lines())
    eh.keep()
    time.sleep(0.5)
    check('a handover of a copy with nothing at work: it ends, with no `work` line and no list', not up(CID3)
          and len(log_lines()) == n and not (state()['sessions'].get(CSE3) or {}).get('stopped'))

    # archived while its copy runs: the person's own stop, so it ends at once; the list waits for the session to come back
    CID4, CSE4 = 't%03dwk1d-0000-4000-8000-000000000005' % PID, 'cse_01TESTworkArchived'
    name4 = kit_copy(CID4)
    t = time.time()
    tp4 = session(CID4, [entry(t - 3000, 'user', 'x')], [
        ('ab0000000000arch1', 'Draft the follow-up', [entry(t, 'user', 'Draft it')])])
    state(lambda s: s['keep']['alone'].update({CSE4: {'transcript': tp4, 'title': 'Supplier quote', 'at': t - 300}}))
    chats[:] = [{'id': CSE4, 'title': 'Supplier quote', 'status': 'archived', 'environment_id': ENV, 'environment_kind': 'bridge'}]
    server_line[:] = []
    eh.keep()
    time.sleep(0.5)
    kept = (state()['sessions'].get(CSE4) or {}).get('stopped') or []
    check('archived while its copy runs: it ends, the kill is logged and the list waits for it', not up(CID4)
          and any(l.startswith('work   kill %s "Supplier quote" archived: 1 agent (ab0000000000arch1' % CSE4) for l in log_lines())
          and kept and 'this session was archived' in kept[0]['text'])

    # the Mac shuts down: halt_copies() ends each copy first, then says what stopped in each
    CID5, CSE5 = 't%03dwk1e-0000-4000-8000-000000000006' % PID, 'cse_01TESTworkHalt'
    name5 = kit_copy(CID5)
    t = time.time()
    tp5 = session(CID5, [entry(t - 3000, 'user', 'x'),
                         call(t, 'toolu_m9', 'Monitor', {'description': 'The press log', 'command': 'tail -f x', 'timeout_ms': 1800000}),
                         result(t + 0.5, 'toolu_m9', 'Monitor started (task bm9, expires in 30m unless the source ends first)',
                                {'taskId': 'bm9', 'timeoutMs': 1800000, 'persistent': False})],
                  [('ab0000000000halt1', 'Sort the photos', [entry(t, 'user', 'Sort them')])])
    state(lambda s: s['keep']['alone'].update({CSE5: {'transcript': tp5, 'title': 'Press photos', 'at': t - 100}}))
    eh.halt_copies(prefix='kit-t%03dwk1e' % PID)
    time.sleep(0.5)
    kept = (state()['sessions'].get(CSE5) or {}).get('stopped') or []
    check('the Mac shuts down: the copy ends, and the list names its agent and its Monitor', not up(CID5) and kept
          and 'the Mac shut down' in kept[0]['text'] and 'ab0000000000halt1' in kept[0]['text'] and 'Monitor bm9, "The press log"' in kept[0]['text'], kept)
    check('the halt marks it, as before', bool(state()['keep']['alone'][CSE5].get('halted')))
    os.remove(os.path.join(KIT, 'halt'))
    for n in (name2, name3, name4, name5):
        eh.quit_screen(n)

# --- a bring-back waits for the work, at most 2 hours ---------------------------------------------------------------
wm = load('wait')
e2 = load('effort-hook')
real_load = wm.load
wm.load = lambda name: e2 if name == 'effort-hook' else real_load(name)
STATUS = {'status': 'active', 'worker_status': 'idle', 'status_bucket': 'idle'}


class SSE(object):
    @staticmethod
    def session(cse):
        return dict(STATUS)


WORK = {'now': {'agents': [], 'commands': [], 'monitors': []}}
ENDED, STARTS = [], []
e2.sse = lambda: SSE
e2.copy_work = lambda tp, cse='', which=None, rows=None, tasks=None: (WORK['now'], {4242: 'server'})
e2.end_server_copy = lambda cse, wait=10: ENDED.append(cse) or True
e2.quit_screen = lambda name: None
e2.point_at = lambda *a: None
e2.chat_events = lambda *a, **k: []
e2.waiting_since_reply = lambda events: (0, False)
e2.start_screen = lambda cid, cwd, model='', first='': STARTS.append(open(first).read() if first else '') or 'kit-x'
CSE6 = 'cse_01TESTworkBack'
W6 = {'id': 'w60001', 'cse': CSE6, 'transcript': tp1, 'title': 'Labels quote', 'cwd': T}
AGENT = {'id': LABELS, 'aid': LABELS, 'what': 'Bottle labels with a barcode', 'start': NOW - 900, 'by': '', 'cwd': '/sample/src',
         'folder': os.path.expanduser('~/src/sample-labels'), 'last': 'ran: npm run check', 'open': True}
CMD = {'id': 'bc1', 'what': 'Run the tests', 'start': NOW - 500, 'by': ''}
state(lambda s: s['sessions'].setdefault(CSE6, {'title': 'Labels quote'}) if 'sessions' in s else s.update(sessions={CSE6: {'title': 'Labels quote'}}))


class Quiet(object):
    """The reply watch, which the minute check runs after the waits: it reads no mail here."""
    @staticmethod
    def check(wm):
        pass

    @staticmethod
    def mark_told(cse, ids):
        pass


def fresh():
    """As if the session's last start was long ago: a start moments ago keeps the next one off (wait.py STARTING)."""
    state(lambda s: s.setdefault('keep', {}).setdefault('alone', {}).pop(CSE6, None))


def try_back(prompt='[Sttark Claude Kit] A wait you handed to the Kit has ended.'):
    fresh()
    try:
        return wm.bring_back(dict(W6), prompt)
    except RuntimeError as x:
        return 'busy-work' if getattr(x, 'work', False) else str(x)


WORK['now'] = {'agents': [AGENT], 'commands': [], 'monitors': []}
n0 = len(log_lines())
r1, r2 = try_back(), try_back()
defers = [l for l in log_lines()[n0:] if l.startswith('work   defer')]
check('a bring-back waits while the agents run: busy (work), the copy is not ended, nothing starts', r1 == r2 == 'busy-work'
      and not ENDED and not STARTS, (r1, r2, ENDED))
check('`work defer` once, with the session, its name and the agent\'s id', len(defers) == 1 and defers[0].startswith(
    'work   defer %s "Labels quote" bring-back waits: 1 agent (%s "Bottle labels with a barcode")' % (CSE6, LABELS)), defers)
WORK['now'] = {'agents': [AGENT], 'commands': [CMD], 'monitors': []}
try_back()
check('when the work changes, a new `work defer` line', len([l for l in log_lines()[n0:] if l.startswith('work   defer')]) == 2)
WORK['now'] = {'agents': [], 'commands': [], 'monitors': []}
r = try_back()
check('when the work ends it comes back: its copy ends, the new one starts with the message', r is True and ENDED == [CSE6]
      and len(STARTS) == 1 and 'stopped' not in STARTS[0])
check('`work done` says how long it waited', any(l.startswith('work   done %s "Labels quote" bring-back waited ' % CSE6) for l in log_lines()))
check('no `work kill` for it', not any(l.startswith('work   kill %s' % CSE6) for l in log_lines()))

# after 2 hours it comes back all the same, and its own message says what stopped
WORK['now'] = {'agents': [AGENT], 'commands': [CMD], 'monitors': []}
try_back()
state(lambda s: s['work_wait'][CSE6].update(since=time.time() - wm.HOLD_MAX - 5))
r = try_back()
check('after 2 hours of work it comes back', r is True and len(STARTS) == 2)
check("the bring-back's message says what stopped: why, each agent's id with SendMessage, the command",
      'Work of this session stopped at ' in STARTS[1] and 'had run 2 hours, the most the Kit waits for it' in STARTS[1]
      and 'SendMessage (to: %s)' % LABELS in STARTS[1] and '- Background command bc1, "Run the tests"' in STARTS[1], STARTS[1][-600:])
check("`work kill` says the session is told in the Kit's message", any(
    l.startswith('work   kill %s "Labels quote" bring-back: 1 agent' % CSE6) and l.endswith("the session is told in the Kit's message")
    for l in log_lines()))
check('the wait for the work is over', CSE6 not in (state().get('work_wait') or {}))

# a list the session did not get yet goes in the bring-back's message, once
e2.note_stopped(CSE6, 'Labels quote', {'agents': [AGENT], 'commands': [], 'monitors': []}, 'handover')
WORK['now'] = {'agents': [], 'commands': [], 'monitors': []}
try_back()
check("a list kept for the session goes in the bring-back's message", len(STARTS) == 3 and 'the server started its own copy' in STARTS[2])
check("and is gone after, with a `work told` line", not state()['sessions'][CSE6].get('stopped') and any(
    l.startswith('work   told %s' % CSE6) and l.endswith("in the Kit's message") for l in log_lines()))
e2.note_stopped(CSE6, 'Labels quote', {'agents': [AGENT], 'commands': [], 'monitors': []}, 'halt')
fresh()
wm.bring_back(dict(W6), None)
check('a bring-back with no message (the Archived page) leaves the list for the next prompt',
      bool(state()['sessions'][CSE6].get('stopped')))
state(lambda s: s['sessions'][CSE6].pop('stopped', None))

# a note of the person's own reply (watch.py queue_note()) that the session did not get yet goes in the bring-back's
# message too, once
OWN = ('[Sttark Claude Kit] The person replied themselves in a place this session watches. Your records do not show '
       'this reply:\n- In the email thread "Labels proof", Wed Nov 18 2:30 PM, the person sent it: "The proof is approved."')
state(lambda s: s['sessions'][CSE6].update(replied=[{'at': time.time(), 'ids': ['m-own'], 'title': 'Labels quote',
                                                     'where': 'in the email thread "Labels proof"', 'text': OWN}]))
try_back()
check("a note of the person's own reply goes in the bring-back's message, and is gone after, with a `watch  told` line",
      OWN in STARTS[-1] and not state()['sessions'][CSE6].get('replied') and any(
          l.startswith('watch  told %s "Labels quote" of your reply in the email thread "Labels proof"' % CSE6)
          and l.endswith("in the Kit's message") for l in log_lines('watch  ')))

# what runs can't be read: the minute check's view of the session decides, as before
real_copy_work = e2.copy_work


def broken(*a, **k):
    raise OSError('ps did not answer')


e2.copy_work = broken
state(lambda s: s['sessions'][CSE6].update(app={'background': {'agents': 1}, 'checked': time.time()}))
check("what runs can't be read, and the minute check saw agents: it waits", try_back() == 'busy-work')
state(lambda s: s['sessions'][CSE6].update(app={'background': None, 'checked': time.time()}))
n2 = len(STARTS)
check("what runs can't be read, and the minute check saw none: it comes back", try_back() is True and len(STARTS) == n2 + 1)
e2.copy_work = real_copy_work

# a turn waits as before (no `work` line); an archived session's own copy ends at once, and the message says so
STATUS.update(worker_status='running')
n1 = len(log_lines())
check('a turn: busy, as before', try_back() == 'busy' and len(log_lines()) == n1)
STATUS.update(status='archived', worker_status='idle')
WORK['now'] = {'agents': [AGENT], 'commands': [], 'monitors': []}
r = try_back()
check("archived: the Kit's copy that still runs ends, and the message says the session was archived", r is True
      and 'this session was archived' in STARTS[-1] and any(l.startswith('work   kill %s "Labels quote" archived' % CSE6) for l in log_lines()))
STATUS.update(status='active')

# claude-wait --now while the work runs: it comes back when the work ends, and the person reads why
state(lambda s: s.update(waits={'w60002': {'id': 'w60002', 'kind': 'at', 'at': time.time() - 5, 'cse': CSE6,
                                          'transcript': tp1, 'title': 'Labels quote', 'set_at': time.time() - 600, 'why': 'x'}}))
WORK['now'] = {'agents': [AGENT], 'commands': [], 'monitors': []}
fresh()
r = wm.check(only='w60002', by='window')
check("Bring it back now while the work runs: 'working', and the wait comes back when it ends", r == 'working'
      and bool(state()['waits']['w60002'].get('ready')), (r, state()['waits']['w60002']))
out = io.StringIO()
with redirect_stdout(out):
    code = (sys.argv.__setitem__(slice(1, None), ['--now', 'w60002', '--by', 'window']), wm.main())[1]
check('the person reads why (not now: 1)', code == 1 and 'still run' in out.getvalue() and 'at most 2 hours' in out.getvalue(), out.getvalue())
WORK['now'] = {'agents': [], 'commands': [], 'monitors': []}
fresh()
wm.load = lambda name: e2 if name == 'effort-hook' else (Quiet if name == 'watch' else real_load(name))
r = wm.check()
check('the next minute after the work ends, it comes back', state()['waits']['w60002'].get('stage') == 'back', state()['waits']['w60002'])

shutil.rmtree(T, ignore_errors=True)
print('\n%d failed' % fails if fails else '\nall passed')
sys.exit(1 if fails else 0)
