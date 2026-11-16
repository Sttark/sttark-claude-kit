#!/usr/bin/python3
"""Tests that every chat the Kit starts by itself starts in a folder Claude Code trusts, on copies: a temp state
folder and log, a copy of ~/.claude.json (STTARK_CLAUDE_JSON) and a stand-in for Claude Code (STTARK_CHAT_CLAUDE)
that, like Claude Code, waits at its question "Quick safety check: Is this a project you created or one you trust?"
in a folder with no trust, and records a link in the conversation when it has trust. The chats run in real screens
with test names (kit-zz...), quit at the end. No model is called, no session is changed, and no real screen,
server or ~/.claude.json is touched. Prints each case; exits 1 if any fails.
Run: /usr/bin/python3 tools/trust-test.py"""
import importlib.util, json, os, shutil, stat, subprocess, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.normpath(os.path.join(HERE, '../Resources/hooks'))
T = os.path.realpath(tempfile.mkdtemp(prefix='trust-test-'))  # Claude Code records a folder by its real path
KIT, LOG, CJ = os.path.join(T, 'kit'), os.path.join(T, 'log'), os.path.join(T, 'claude.json')
PROJ, RUNS, FAKE = os.path.join(T, 'projects'), os.path.join(T, 'runs.jsonl'), os.path.join(T, 'claude')
for d in (KIT, PROJ):
    os.makedirs(d)
os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_CLAUDE_JSON=CJ, STTARK_CHAT_CLAUDE=FAKE)

with open(FAKE, 'w') as f:  # the stand-in for Claude Code
    f.write(f'''#!/usr/bin/python3
import json, os, sys, time
args = sys.argv[1:]
cid, cwd = args[args.index('--resume') + 1], os.getcwd()
with open({RUNS!r}, 'a') as f:
    f.write(json.dumps({{'cid': cid, 'cwd': cwd, 'args': args}}) + '\\n')
projects = json.load(open({CJ!r})).get('projects') or {{}}
if (projects.get(cwd) or {{}}).get('hasTrustDialogAccepted') is not True:
    print('Quick safety check: Is this a project you created or one you trust? (Like your own code, a well-known')
    print('open source project, or work from your team).')
    print(' > 1. No, exit')
    print('   2. Yes, I trust this folder', flush=True)
else:
    tp = os.path.join({PROJ!r}, cid + '.jsonl')
    link = [x['bridgeSessionId'] for x in map(json.loads, open(tp)) if x.get('type') == 'bridge-session'][-1]
    with open(tp, 'a') as f:  # as Claude Code writes it
        f.write(json.dumps({{'type': 'bridge-session', 'sessionId': cid, 'bridgeSessionId': link}}, separators=(',', ':')) + '\\n')
    print('Remote Control connected', flush=True)
time.sleep(300)
''')
os.chmod(FAKE, 0o755)


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HOOKS, file))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


eh = load('eh', 'effort-hook.py')
eh.LINK_WAIT = 12


def no_api(*a, **k):
    raise AssertionError('the test called the Claude API')


eh.api = no_api
failed, screens = [], []


def check(name, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + name + ('' if ok else f'  -- {detail}'))
    if not ok:
        failed.append(name)


def log_lines():
    try:
        return open(LOG).read().splitlines()
    except OSError:
        return []


def folder(name):
    p = os.path.join(T, 'src', name)
    os.makedirs(p)
    return p


def settings(d=None, mode=0o600):
    if d is not None:
        with open(CJ, 'w') as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        os.chmod(CJ, mode)
    with open(CJ) as f:
        return json.load(f)


def trusted(p):
    return ((settings().get('projects') or {}).get(p) or {}).get('hasTrustDialogAccepted') is True


def runs(cid):
    try:
        return [r for r in map(json.loads, open(RUNS)) if r['cid'] == cid]
    except OSError:
        return []


def chat(letter, cwd):
    """A saved conversation that last ran in `cwd`, with an id whose screen name can't be a real one."""
    cid = f'zz{letter}{os.getpid() % 100000:05d}-test-{letter}'
    sid = 'cse_01TEST' + letter * 6
    tp = os.path.join(PROJ, cid + '.jsonl')
    with open(tp, 'w') as f:
        for line in ({'type': 'user', 'cwd': cwd, 'sessionId': cid, 'message': {'role': 'user', 'content': 'Hi'}},
                     {'type': 'assistant', 'cwd': cwd, 'sessionId': cid,
                      'message': {'role': 'assistant', 'model': 'claude-haiku-5-5', 'content': 'OK'}}):
            f.write(json.dumps(line) + '\n')
    screens.append('kit-' + cid[:8])
    return cid, sid, tp


BASE = {'numStartups': 12, 'theme': 'dark', 'oauthAccount': {'accountUuid': 'acct-test', 'organizationUuid': 'org-test',
                                                            'emailAddress': 'test@example.com'},
        'note': 'café, naïve, ✓', 'projects': {'/somewhere/else': {'allowedTools': ['Bash'], 'hasTrustDialogAccepted': True},
                                               '/an/other': {'hasTrustDialogAccepted': False, 'lastCost': 1.25}}}
try:
    # 1. trust_folder() on a copy
    a = folder('alpha')
    settings(json.loads(json.dumps(BASE)))
    check('trust: a folder with no trust is trusted', eh.trust_folder(a) is True and trusted(a))
    want = json.loads(json.dumps(BASE))
    want['projects'][a] = {'hasTrustDialogAccepted': True}
    check('trust: every other key is kept, as it was', settings() == want, settings())
    check('trust: the file keeps its permissions', stat.S_IMODE(os.stat(CJ).st_mode) == 0o600, oct(os.stat(CJ).st_mode))
    check('trust: words in other languages stay as they were', '"café, naïve, ✓"' in open(CJ, encoding='utf-8').read())
    check('trust: no temp file and no lock are left', sorted(os.listdir(T)) == ['claude', 'claude.json', 'kit', 'log', 'projects', 'src'],
          os.listdir(T))
    check('trust: the log says so', any(l.endswith(f'trust  {a} trusted in Claude Code, so a chat that ran there starts '
                                                   'without its safety question') for l in log_lines()), log_lines()[-1:])
    before = os.stat(CJ)
    time.sleep(0.05)
    check('trust: trusted already, so the file is not written again', eh.trust_folder(a) is True and
          (os.stat(CJ).st_ino, os.stat(CJ).st_mtime_ns) == (before.st_ino, before.st_mtime_ns))

    b = folder('beta')
    d = settings()
    d['projects'][b] = {'allowedTools': ['Read'], 'hasTrustDialogAccepted': False, 'lastCost': 0.5}
    settings(d)
    eh.trust_folder(b)
    check('trust: a folder Claude Code knows keeps its own keys', settings()['projects'][b] ==
          {'allowedTools': ['Read'], 'hasTrustDialogAccepted': True, 'lastCost': 0.5}, settings()['projects'][b])

    text = open(CJ).read()
    home = os.path.expanduser('~')
    check('trust: never the home folder (Claude Code keeps its trust for one session only)',
          eh.trust_folder(home) is False and open(CJ).read() == text)
    check('trust: never a folder that is gone, or none', eh.trust_folder(os.path.join(T, 'gone')) is False and
          eh.trust_folder('') is False and open(CJ).read() == text)

    # Claude Code's own lock on the file (a folder next to it, held for a moment at a time)
    c = folder('gamma')
    os.mkdir(CJ + '.lock')
    threading.Timer(0.5, lambda: os.rmdir(CJ + '.lock')).start()
    t0 = time.time()
    ok = eh.trust_folder(c)
    check('trust: it waits for a Claude process that holds the lock, then writes', ok and trusted(c) and time.time() - t0 >= 0.45,
          time.time() - t0)
    check('trust: and lets go of its own lock', not os.path.exists(CJ + '.lock'))

    e = folder('delta')
    os.mkdir(CJ + '.lock')
    eh.TRUST_LOCK_WAIT = 0.3
    t0 = time.time()
    check('trust: a lock held too long: it writes anyway after the wait', eh.trust_folder(e) and trusted(e) and
          0.25 <= time.time() - t0 < 2, time.time() - t0)
    check('trust: and leaves the other process\'s lock alone', os.path.isdir(CJ + '.lock'))
    os.rmdir(CJ + '.lock')

    f_ = folder('epsilon')
    os.mkdir(CJ + '.lock')
    os.utime(CJ + '.lock', (time.time() - 60, time.time() - 60))
    eh.TRUST_LOCK_WAIT = 5
    t0 = time.time()
    check('trust: a lock left behind (not touched for 10 s) is no reason to wait', eh.trust_folder(f_) and trusted(f_) and
          time.time() - t0 < 1, time.time() - t0)
    os.rmdir(CJ + '.lock')
    eh.TRUST_LOCK_WAIT = 2

    g = folder('zeta')
    good = open(CJ).read()
    with open(CJ, 'w') as fh:
        fh.write(good[:len(good) // 2])  # cut off, as by a writer that isn't atomic
    check('trust: a file it can\'t read is left as it is, and the start goes on', eh.trust_folder(g) is False and
          open(CJ).read() == good[:len(good) // 2])
    check('trust: the log says why', any(f'trust  {g} could not be marked trusted' in l for l in log_lines()))
    with open(CJ, 'w') as fh:
        fh.write(good)

    # 2. The bug: a chat the server won't start, started on its own, in a folder with no trust (move() in keep())
    h = folder('airpark-home')
    cid, sid, tp = chat('A', h)
    with open(eh.STATE, 'w') as fh:
        json.dump({'sessions': {sid: {'transcript': tp}}}, fh)
    check('setup: the chat\'s folder has no trust', not trusted(h))
    r = eh.move({'id': sid, 'title': 'Trust test A'}, 7)
    check('keep: the chat starts in its own folder, trusted first, and reattaches its link',
          bool(r) and r['id'] == sid and trusted(h), (r, trusted(h)))
    run = (runs(cid) or [{}])[-1]
    check('keep: Claude Code runs in the chat\'s folder, with Remote Control and Bypass permissions',
          run.get('cwd') == h and run.get('args') == ['--resume', cid, '--remote-control', '--permission-mode',
                                                       'bypassPermissions'], run)
    check('keep: the log says reattach', any(f'reattach {sid} "Trust test A"' in l for l in log_lines()))
    check('keep: the chat runs in one screen', len(eh.screen_ids('kit-' + cid[:8])) == 1)

    # the same start before this fix: no trust, so Claude Code waits at its question, and the log now says so
    i = folder('no-trust')
    cid, sid, tp = chat('B', i)
    with open(eh.STATE, 'w') as fh:
        json.dump({'sessions': {sid: {'transcript': tp}}}, fh)
    real = eh.trust_folder
    eh.trust_folder = lambda cwd: False
    r = eh.move({'id': sid, 'title': 'Trust test B'}, 7)
    eh.trust_folder = real
    line = [l for l in log_lines() if f'keep   {sid} "Trust test B"' in l]
    check('keep: with no trust the chat does not start', r is None and not trusted(i), r)
    check('keep: the failure line says it waits at the trust question, in which screen and folder',
          bool(line) and line[-1].endswith(f"won't start, and starting it on a new link didn't work either - it waits in "
                                           f"kit-{cid[:8]} at Claude Code's question whether to trust {i}"), line)

    # 3. Move to Remote Control (migrate.py)
    mg = load('mg', 'migrate.py')
    j = folder('moved')
    cid, sid, tp = chat('C', j)
    with open(tp, 'a') as fh:  # migrate waits for the first link; the stand-in copies the last one
        fh.write(json.dumps({'type': 'bridge-session', 'sessionId': cid, 'bridgeSessionId': 'cse_01TESTmoved'},
                            separators=(',', ':')) + '\n')
    x = {'id': cid, 'cwd': j, 'model': 'claude-haiku-5-5', 'transcript': tp}
    name = mg.launch(x)
    check('migrate: the move starts in the session\'s folder, trusted first, and gets its link',
          name == 'kit-' + cid[:8] and mg.wait_link(x, name, 1, wait=12) == 'cse_01TESTmoved' and trusted(j))
    run = (runs(cid) or [{}])[-1]
    check('migrate: with the model it ran on', run.get('cwd') == j and run.get('args', [])[-2:] == ['--model', 'claude-haiku-5-5'],
          run)

    # 4. Bring a session back (wait.py: a wait that comes due, the Archived page, the phone)
    wt = load('wt', 'wait.py')

    class Sessions:
        def session(self, cse):
            return {'status': 'archived'}
    eh.sse = lambda: Sessions()
    eh.chat_events = lambda sid, pages=5: []
    wt.load = lambda n: eh if n == 'effort-hook' else load(n, n + '.py')
    k = folder('waited')
    cid, sid, tp = chat('D', k)
    started = wt.bring_back({'id': 'w1', 'cse': sid, 'transcript': tp, 'cwd': k, 'title': 'Trust test D'},
                            'The pull request merged. Go on.')
    for _ in range(50):
        if runs(cid):
            break
        time.sleep(0.1)
    run = (runs(cid) or [{}])[-1]
    check('wait: the session comes back in its folder, trusted first', started and run.get('cwd') == k and trusted(k), run)
    check('wait: with its first message', run.get('args', [''])[-1] == 'The pull request merged. Go on.', run.get('args'))
    check('wait: and the keep check knows it runs on its own', sid in (eh.peek().get('keep', {}).get('alone') or {}))
finally:
    for n in screens:
        eh.quit_screen(n)
    shutil.rmtree(T, ignore_errors=True)

print(f'\n{len(failed)} failed' if failed else '\nall passed')
raise SystemExit(1 if failed else 0)
