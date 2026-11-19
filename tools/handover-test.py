#!/usr/bin/python3
"""Tests that a prompt the Kit types into its own copy of a session is never lost, and that a handover never ends that
copy while it still works (effort-hook.py keep(), typed_state(), kit_copy_works(), confirm_typed(), lose_typed(),
typed_waits(), on_prompt(), on_tool(), start_screen(); wait.py bring_back(), pick_level(), redeliver(), tell_typed()),
on copies: a test Kit folder and log (STTARK_KIT_DIR, STTARK_KIT_LOG), a test ~/.claude (STTARK_CLAUDE_DIR) and
~/.claude.json (STTARK_CLAUDE_JSON) with made-up records, a stand-in `claude` (a small program built here, that only
sleeps) started by the Kit's own start in real screens with test names (STTARK_CHAT_CLAUDE), a stand-in level for the
effort check (STTARK_WAIT_LEVEL), and stand-ins for the Claude app's list of sessions, the session's status and this
Mac's server. No session, screen or server of this Mac is touched, no model is called and nothing is sent
(STTARK_NOTIFY_DRY, STTARK_EFFORT_DRY). It checks:
- bring_back() starts the copy at the level picked for the prompt (--effort, before the prompt, which stays last), and
  keeps the prompt in `typed` until the session answers it;
- the effort hook gives that prompt the level the Kit picked, with no model call and no change sent through the
  server; while it has no answer, another prompt and the checks at 10 steps send no change either; the server's own
  copy is not held; after the answer, changes go out again;
- a handover waits while the Kit's copy's turn runs and while the prompt it typed in has no answer (one `handover ...
  waits` line); it ends the copy when the turn ends, and the prompt, which had no answer before the server took the
  session over, is lost (`prompt lost`);
- the minute check types it in again (`prompt again`, try 2 of 3), with a line that says why, through bring_back();
  when the session answers it, it goes (`prompt in`); a session in a turn makes it wait (`prompt waits`, once);
- after 3 tries, or when the session was archived, the Kit tells the person with the prompt's text (`prompt failed`,
  and a message kept in the Kit app, as the session's alerts are off), and types nothing in;
- a copy that stopped (the Mac shut down) before it answered: the prompt is lost and goes again.
Run from the repo root: /usr/bin/python3 tools/handover-test.py"""
import importlib.util, json, os, re, shutil, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, 'Resources', 'hooks')
T = os.path.realpath(tempfile.mkdtemp(prefix='kit-handover-'))
KIT, LOG, CLAUDE = os.path.join(T, 'kit'), os.path.join(T, 'log'), os.path.join(T, 'claude')
CJ, FOLDER = os.path.join(T, 'claude.json'), os.path.join(T, 'sample-orders')
for d in (KIT, os.path.join(CLAUDE, 'sessions'), FOLDER):
    os.makedirs(d)
json.dump({'oauthAccount': {'accountUuid': 'test-account', 'organizationUuid': 'test-org'}, 'projects': {}}, open(CJ, 'w'))
FAKE = os.path.join(T, 'bin', 'claude')
os.makedirs(os.path.dirname(FAKE))
open(os.path.join(T, 'claude.c'), 'w').write('#include <unistd.h>\nint main(void) { for (;;) pause(); }\n')
if subprocess.run(['/usr/bin/cc', '-o', FAKE, os.path.join(T, 'claude.c')], capture_output=True).returncode:
    print('skip  the stand-in claude could not be built (no C compiler)')
    sys.exit(0)
os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_CLAUDE_DIR=CLAUDE, STTARK_CLAUDE_JSON=CJ,
                  STTARK_CHAT_CLAUDE=FAKE, STTARK_EFFORT_DRY='1', STTARK_NOTIFY_DRY='1', STTARK_WAIT_LEVEL='xhigh')
for k in ('CLAUDE_CODE_BRIDGE_SESSION_ID', 'CLAUDE_PID', 'CLAUDE_EFFORT', 'STTARK_WAIT_DRY', 'EFFORT_JUDGE'):
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


def log_lines(tag=''):
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


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S.', time.gmtime(t)) + '%03dZ' % int((t % 1) * 1000)


def entry(t, typ, content, **kw):
    x = {'type': typ, 'timestamp': iso(t), 'entrypoint': 'cli', 'cwd': FOLDER, 'sessionId': 'x',
         'message': {'role': 'assistant' if typ == 'assistant' else 'user', 'content': content}}
    x.update(kw)
    return x


def answer(t, text='Done: the order page shows the totals now.'):
    a = entry(t, 'assistant', [{'type': 'text', 'text': text}])
    a['message']['stop_reason'] = 'end_turn'
    return a


def add(tp, *entries):
    with open(tp, 'a') as f:
        for x in entries:
            f.write(json.dumps(x, separators=(',', ':')) + '\n')  # as Claude Code writes its records


PID = os.getpid() % 1000
CID = 't%03dhv1a-0000-4000-8000-000000000001' % PID  # its screen: kit-t<3 digits>hv1a, only this test's
CSE, TITLE, NAME = 'cse_01TESThandoverOrders', 'Order page', 'kit-' + CID[:8]
TP = os.path.join(CLAUDE, 'projects', '-sample-orders', CID + '.jsonl')
os.makedirs(os.path.dirname(TP))
add(TP, entry(time.time() - 3000, 'user', 'Build the order page'), answer(time.time() - 2900, 'The order page is built.'))
PROMPT = 'Why does the order page show no totals for the press 2 jobs? Check the last import.'

eh = load('effort-hook')
wm = load('wait')
wm.load = lambda name: eh if name == 'effort-hook' else load(name)
STATUS = {'status': 'active', 'worker_status': 'idle', 'status_bucket': 'idle'}


class SSE(object):
    @staticmethod
    def session(cse):
        return dict(STATUS)


chats, server_line, SENT, JUDGED = [], [], [], []
eh.sse = lambda: SSE
eh.all_chats = lambda pages=5: chats
eh.chat_events = lambda sid, pages=5: []
eh.send = lambda sid, level: SENT.append((sid, level)) or (200, 'ok', 'rid')
eh.archived = lambda chats: None
eh.open_tasks = lambda: {}
eh.api = lambda *a, **k: (_ for _ in ()).throw(AssertionError('the test called the Claude API'))
# the process list keep() reads: a server, a stand-in for the server's copy of the test session when it runs it, and
# this test's own copies (no other process of this Mac, so keep() never sees a real session)
eh.processes = lambda: ('/sample/claude rc --permission-mode bypassPermissions\n' + ''.join(server_line) + ''.join(
    l + '\n' for l in subprocess.run(['ps', '-axo', 'command'], capture_output=True, text=True).stdout.splitlines()
    if '--resume t%03dhv1' % PID in l))
SERVER = '/sample/claude --print --sdk-url https://api.anthropic.com/v1/code/sessions/%s --session-id %s\n' % (CSE, CSE)
ENV = 'env_01TESThandover'
state(lambda s: s.update(sessions={CSE: {'title': TITLE, 'transcript': TP, 'title_at': 1e12, 'level': 'low'}},
                         keep={'envs': [ENV], 'woke': {}, 'alone': {}}))
chats[:] = [{'id': CSE, 'title': TITLE, 'status': 'active', 'environment_id': ENV, 'environment_kind': 'bridge'}]


def kit_pid():
    for _ in range(40):
        pids = [p for p, kind in eh.copies(CSE, CID).items() if kind == 'kit']
        if pids:
            return pids[0]
        time.sleep(0.1)
    return 0


def args_of(pid):
    return subprocess.run(['ps', '-ww', '-o', 'args=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()


def copy_says(pid, status):
    json.dump({'pid': pid, 'sessionId': CID, 'status': status}, open(os.path.join(CLAUDE, 'sessions', '%d.json' % pid), 'w'))


def typed():
    return (state().get('typed') or {}).get(CSE) or []


def back(prompt, **w):
    state(lambda s: s['keep']['alone'].pop(CSE, None))  # as if its last start was long ago (wait.py STARTING)
    return wm.bring_back(dict({'id': 'same-0a1b2c3d', 'cse': CSE, 'transcript': TP, 'cwd': FOLDER, 'title': TITLE,
                               'source': 'same work'}, **w), prompt)


try:
    # --- the start: at the level picked for the prompt, and the prompt kept until it is answered -----------------
    ok = back(PROMPT)
    pid = kit_pid()
    a = args_of(pid)
    check('bring_back() starts the copy at the level picked for the prompt (--effort), before the prompt',
          ok is True and pid and ' --effort xhigh ' in a and a.endswith(PROMPT), a[-200:])
    recs = typed()
    r0 = recs[0] if recs else {}
    check('the prompt is kept until it is answered: its words, the level, try 1, where it came from',
          len(recs) == 1 and r0.get('level') == 'xhigh' and r0.get('tries') == 1 and r0.get('source') == 'same work'
          and r0.get('needle') == PROMPT and open(r0['file']).read() == PROMPT and CSE in state()['keep']['alone'], recs)

    # --- the effort hook in that copy: the level the Kit picked, and no change through the server -------------------
    def judge(ask, system=None):
        JUDGED.append(ask)
        return 'max', 'max - a test answer'
    eh.judge = judge
    os.environ['CLAUDE_PID'] = str(pid)
    eh.on_prompt({'prompt': PROMPT, 'transcript_path': TP}, CSE)
    check("the typed prompt gets the level the Kit picked: no model call, no change sent",
          not JUDGED and not SENT and log_lines('keep   ')[-1:] == [
              'keep   %s xhigh - the level the Kit selected when it typed this prompt in | %s' % (CSE, PROMPT[:80])],
          log_lines('keep   ')[-1:])
    eh.on_prompt({'prompt': '<task-notification> an agent of the turn ended </task-notification>', 'transcript_path': TP}, CSE)
    hold = log_lines('keep   ')[-1]
    check('another prompt while it has no answer: checked, but no change is sent, and the log says why',
          len(JUDGED) == 1 and not SENT and hold.startswith('keep   %s xhigh (' % CSE) and ') max - not set now: the Kit\'s '
          'copy has not answered the prompt the Kit typed in. A change now makes this Mac\'s server take control of '
          'the session |' in hold, hold)
    steps = os.path.join(CLAUDE, 'projects', '-sample-orders', CID + '-steps.jsonl')
    add(steps, entry(time.time(), 'user', PROMPT), *[entry(time.time(), 'assistant', [
        {'type': 'tool_use', 'id': 'toolu_%d' % i, 'name': 'Bash', 'input': {'command': 'ls', 'description': 'List files'}}])
        for i in range(10)])
    eh.on_tool({'transcript_path': steps, 'effort': {'level': 'xhigh'}}, CSE)
    check('the check at 10 steps: no model call and no change while it has no answer',
          len(JUDGED) == 1 and not SENT and log_lines('steady ')[-1:] and 'not checked now: ' in log_lines('steady ')[-1],
          log_lines('steady ')[-1:])
    srv = subprocess.Popen([FAKE, '--print', '--sdk-url', 'https://api.anthropic.com/v1/code/sessions/' + CSE, '--session-id', CSE])
    time.sleep(0.5)
    os.environ['CLAUDE_PID'] = str(srv.pid)
    check("the server's own copy is not held (a change there starts no new copy)", eh.typed_waits(CSE) is None)
    srv.kill()
    srv.wait()
    os.environ['CLAUDE_PID'] = str(pid)

    # --- the incident: the server takes the session over while the Kit's copy runs the prompt ---------------------
    copy_says(pid, 'busy')
    server_line[:] = [SERVER]
    n = len(log_lines())
    eh.keep()
    waits = [l for l in log_lines()[n:] if l.startswith('handover')]
    check("a handover while the Kit's copy runs its turn and has not answered the prompt: the copy is not ended",
          kit_pid() == pid and CSE in state()['keep']['alone'], waits)
    check('one `handover ... waits` line that says what still works, in plain words', len(waits) == 1 and waits[0].startswith(
        'handover %s "%s" waits: the server runs it now, but the Kit\'s copy still works (its turn runs; it has not '
        'answered the prompt the Kit typed in at ' % (CSE, TITLE)) and waits[0].endswith(
        'it tries again every 15 seconds, at most 2 hours'), waits)
    check('the prompt notes when the other copy took the session over', bool((typed() or [{}])[0].get('taken')), typed())
    eh.keep()
    check('the next check waits too, and logs nothing new', kit_pid() == pid and len(log_lines()) == n + 1, log_lines()[n:])
    # the Kit's copy ends its turn: what it wrote after the server took over reached no one
    add(TP, entry(time.time(), 'user', PROMPT), answer(time.time() + 1))
    copy_says(pid, 'idle')
    eh.keep()
    time.sleep(0.5)
    out = log_lines()[n + 1:]
    check('when its turn ends, the handover ends the copy, and says it waited for its work',
          not kit_pid() and not eh.screen_ids(NAME) and CSE not in state()['keep']['alone'] and any(
              l.startswith('handover %s "%s" the server runs it now; quit its own copy (%s) after its work ended (' % (CSE, TITLE, NAME))
              for l in out), out)
    lost = [l for l in out if l.startswith('prompt lost')]
    check('the prompt had no answer before the server took the session over, so it is lost and goes again',
          len(lost) == 1 and lost[0].startswith('prompt lost   %s "%s" the copy that received the prompt the Kit typed in at ' % (CSE, TITLE))
          and "(same work) ended before it answered: this Mac's server took control of the session; the Kit types it in again |" in lost[0]
          and (typed() or [{}])[0].get('lost', {}).get('why') == 'handover', out)

    # --- the minute check types it in again, in the copy that runs the session next --------------------------------
    STATUS.update(worker_status='running', status_bucket='working')
    n = len(log_lines())
    wm.redeliver()
    wm.redeliver()
    w1 = log_lines()[n:]
    check('a session in a turn: the prompt waits, with one `prompt waits` line', len(w1) == 1 and w1[0].startswith(
        'prompt waits  %s "%s" the prompt the Kit typed in at ' % (CSE, TITLE)) and w1[0].endswith('goes again when its turn ends')
        and not kit_pid(), w1)
    STATUS.update(worker_status='idle', status_bucket='idle')
    server_line[:] = []
    wm.redeliver()
    pid2 = kit_pid()
    a2 = args_of(pid2)
    again = [l for l in log_lines()[n:] if l.startswith('prompt again')]
    check('then it goes again through bring_back(), in a new copy, at the level picked for it',
          pid2 and pid2 != pid and ' --effort xhigh ' in a2 and len(again) == 1 and again[0].startswith(
              'prompt again  %s "%s" typed in again the prompt from ' % (CSE, TITLE)) and '(same work), try 2 of 3 |' in again[0], again)
    check('with a line that says why, then the prompt as it went the first time',
          "[Sttark Claude Kit] The Kit sends this prompt again. It went in at " in a2
          and "but the copy of this session that received it ended before it answered. Why: this Mac's server took control of the session." in a2
          and a2.endswith(PROMPT), a2[-400:])
    r1 = (typed() or [{}])[0]
    check('the prompt is kept as try 2, with no answer yet', len(typed()) == 1 and r1.get('tries') == 2 and not r1.get('lost')
          and not r1.get('taken'), typed())
    # the session answers it
    os.environ['CLAUDE_PID'] = str(pid2)
    add(TP, entry(time.time(), 'user', a2[a2.index('[Sttark Claude Kit] The Kit sends'):]), answer(time.time() + 1))
    eh.keep()
    ins = [l for l in log_lines() if l.startswith('prompt in')]
    check('when the session answers it, it goes, with a `prompt in` line', not typed() and len(ins) == 1 and ins[0].startswith(
        'prompt in     %s "%s" answered the prompt the Kit typed in at ' % (CSE, TITLE)) and ins[0].endswith('(same work), try 2 of 3')
        and not os.path.exists(r1.get('file', '-')), ins)
    eh.on_prompt({'prompt': 'Now add the tax line', 'transcript_path': TP}, CSE)
    check('after the answer, a change goes out again', SENT == [(CSE, 'max')], SENT)
    del SENT[:]

    # --- after 3 tries, the Kit tells the person, with the prompt's text --------------------------------------------
    copy_says(pid2, 'idle')
    ok = back('Show the press 2 totals by shift.')
    pid3 = kit_pid()
    state(lambda s: s['typed'][CSE][0].update(tries=3))
    server_line[:] = [SERVER]
    n = len(log_lines())
    eh.keep()  # a handover: its copy is idle, and the prompt is older than a start (TYPED_START)
    state(lambda s: s['typed'][CSE][0].update(at=time.time() - 400)) if typed() else None
    eh.keep()
    lost = [l for l in log_lines()[n:] if l.startswith('prompt lost')]
    check('the third copy that received it ends before it answered: lost, and the Kit tells the person',
          not kit_pid() and len(lost) == 1 and 'the Kit tells you, with its text' in lost[0], log_lines()[n:])
    server_line[:] = []
    wm.redeliver()
    failed = [l for l in log_lines()[n:] if l.startswith('prompt failed')]
    kept = (json.load(open(os.path.join(KIT, 'kept.json'))).get('items') or [{}])[-1] if os.path.exists(os.path.join(KIT, 'kept.json')) else {}
    check('`prompt failed`: why, and that a message with its text is kept in the Kit app (the session\'s alerts are off)',
          len(failed) == 1 and failed[0].startswith('prompt failed %s "%s" the prompt the Kit typed in at ' % (CSE, TITLE))
          and 'did not go in: the session did not answer it after 3 tries (this Mac\'s server took control of the session); '
              "the Kit kept a message with its text in the Kit app (this session's alerts are off)" in failed[0], failed)
    check("the person's message names the session and holds the prompt's text, and nothing is typed in",
          kept.get('subject') == 'A prompt did not go in: %s' % TITLE and 'Show the press 2 totals by shift.' in kept.get('body', '')
          and kept.get('cse') == CSE and kept.get('from') == 'kit' and not typed() and not kit_pid(), kept)

    # --- archived while its copy runs the prompt: the Kit tells the person, and types nothing in ---------------------
    ok = back('List the jobs that failed the import.')
    chats[:] = [dict(chats[0], status='archived')]
    state(lambda s: s['keep']['alone'][CSE].update(at=time.time() - 300))
    n = len(log_lines())
    eh.keep()
    wm.redeliver()
    out = log_lines()[n:]
    check('archived: its copy ends, and the prompt is not typed in again: the person gets its text',
          not kit_pid() and any(l.startswith('prompt lost') and 'the session was archived; the Kit tells you, with its text' in l for l in out)
          and any(l.startswith('prompt failed') and 'did not go in: the session was archived before it answered it' in l for l in out)
          and not any(l.startswith('prompt again') for l in out) and not typed(), out)
    chats[:] = [dict(chats[0], status='active')]

    # --- a copy that stopped before it answered (the Mac shut down): the prompt goes again ---------------------------
    ok = back('Recount the press 2 jobs.')
    eh.halt_copies(prefix='kit-t%03dhv1' % PID)
    os.remove(os.path.join(KIT, 'halt'))
    state(lambda s: s['typed'][CSE][0].update(at=time.time() - 200))
    n = len(log_lines())
    eh.keep()
    out = log_lines()[n:]
    check('a copy that stopped (the Mac shut down) before it answered: the prompt is lost, and goes again',
          any(l.startswith('prompt lost') and 'ended before it answered: the Mac shut down; the Kit types it in again' in l for l in out)
          and (typed() or [{}])[0].get('lost', {}).get('why') == 'halt', out)
    state(lambda s: s['keep']['alone'][CSE].update(at=time.time() - 200))  # its start, or a wake, was 2 minutes ago

    # --- an idle copy, 5 minutes on: a turn that ended with no mark of an answer counts; a prompt not in it goes again --
    wm.redeliver()  # the prompt from the halt goes again, and its copy runs now
    add(TP, entry(time.time(), 'user', 'Recount the press 2 jobs.'), answer(time.time() + 1))
    eh.keep()
    check('the prompt from the halt went again and was answered', not typed(), typed())
    ok = back('Sum the press 2 jobs by shift.')
    pid4 = kit_pid()
    copy_says(pid4, 'idle')
    add(TP, entry(time.time(), 'user', 'Sum the press 2 jobs by shift.'))  # its turn ended with an error: no answer mark
    state(lambda s: (s['typed'][CSE][0].update(at=time.time() - 400), s['keep']['alone'][CSE].update(at=time.time() - 400)))
    n = len(log_lines())
    eh.keep()
    out = log_lines()[n:]
    check('an idle copy whose turn for the prompt ended with no mark of an answer: it counts as answered',
          not typed() and any(l.startswith('prompt in') and 'with no mark of an answer, so the Kit counts it as answered' in l for l in out), out)
    ok = back('Count the late jobs.')
    pid5 = kit_pid()
    copy_says(pid5, 'idle')
    state(lambda s: (s['typed'][CSE][0].update(at=time.time() - 400), s['keep']['alone'][CSE].update(at=time.time() - 400)))
    n = len(log_lines())
    eh.keep()
    wm.redeliver()
    out = log_lines()[n:]
    check('an idle copy that never took the prompt: it is lost, and goes again in a new copy',
          any(l.startswith('prompt lost') and 'ended before it answered: its copy did not take the prompt; the Kit types it in again' in l
              for l in out) and any(l.startswith('prompt again') for l in out) and kit_pid() not in (0, pid5)
          and (typed() or [{}])[0].get('tries') == 2, out)

    # --- the words in the log carry no em-dash or double hyphen -------------------------------------------------------
    words = [l for l in log_lines() if l.startswith(('prompt', 'handover'))]
    check('no em-dash or double hyphen in the new log lines', words and not [l for l in words if '—' in l or ' -- ' in l], words)
finally:
    os.environ.pop('CLAUDE_PID', None)
    for sid in eh.screen_ids(NAME):
        eh.quit_screen(NAME)
    shutil.rmtree(T, ignore_errors=True)

print('\n%d failed' % fails if fails else '\nall passed')
sys.exit(1 if fails else 0)
