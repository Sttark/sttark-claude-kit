#!/usr/bin/python3
"""One session for the same work: a new session's first prompt that is the work of a session already open on this
Mac gets one question before anything else, so the person keeps one session for each piece of work. Claude Code can't
merge two sessions, so the Kit stops the split at the start. Installed and kept up to date by the Sttark Claude Kit app.

UserPromptSubmit, a session's first prompt only, while the "One session for the same work" switch is on (`same_work`
in the state file; missing is on): the other sessions the Claude app lists (app_list in the state file: open, not
archived, not a run of a scheduled task) whose saved conversation is on this Mac are the candidates; when the new
session runs in a git repository, only those in the same repository (a worktree counts as its repository) or in no
repository. A session that runs now in the Claude desktop app or in a terminal is left out, since a prompt can't be
typed into it from outside; the server's copy and the Kit's own copy can take one. With any left, one Haiku call (no
tools, hooks off, run outside the session, in parallel with the effort check) reads the prompt and each one's name,
folder, first prompt, latest prompts and the effort check's latest reason, and names one only when it is clearly the
same work. On a match the hook adds context: Claude's first step is AskUserQuestion with one question that names that
session and its age, with two options, "Send to <name>" and "Keep here". Nothing else asks, and nothing at all when the
prompt is the Kit's own, a task notice or a command, carries a picture or a file (a typed prompt can't carry those), or
the session holds at the usage limit.

PostToolUse (AskUserQuestion): the answer to that question. "Send to <name>": the Kit delivers the person's prompt to
that session as if they typed it there: wait.py bring_back(), the start the waits use, which starts the session on its
own link with the prompt as its first message, typed locally so Claude Code runs it as the person's own (a message
posted through the server would be held). Claude then replies with one line and the session's link, and does nothing
else. A session in a turn, or with agents still at work, gets it when they end: the prompt waits in the queue, which
wait.py's minute check works off (deliver()). "Keep here": the session goes on with the prompt, and is never asked
again. The Kit archives neither session: only the person archives.

    same-work.py                 the hook: UserPromptSubmit and PostToolUse, JSON on stdin
    same-work.py --deliver       send the prompts that wait for their session's turn to end (wait.py --check runs it)
    same-work.py --list          the questions asked and the prompts that wait, in plain words

Records: same-work.json in the Kit's folder (`checked`, the sessions whose first prompt was looked at; `asked`, each
question with its target and answer; `queue`, the prompts that wait), and each prompt in same-work/<session>.txt, all
kept 7 days. Logged with lines starting "same". STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and log,
STTARK_CLAUDE_DIR at a test ~/.claude (the live sessions' records), STTARK_SAME_MODEL stands in for the Haiku call (a
program that reads the question on stdin and prints the answer), and STTARK_SAME_DRY=1 decides and logs but sends no
prompt.
"""
import calendar, fcntl, glob, importlib.util, json, os, re, subprocess, sys, time
from contextlib import contextmanager

HERE = os.path.dirname(os.path.realpath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


e = load('effort-hook')
KIT = os.path.dirname(e.STATE)
FILE = os.path.join(KIT, 'same-work.json')
PROMPTS = os.path.join(KIT, 'same-work')
MODEL = 'haiku'     # Claude Code's alias for the newest Haiku: fast and cheap, and the choice is plain
STUB = os.environ.get('STTARK_SAME_MODEL', '')
DRY = bool(os.environ.get('STTARK_SAME_DRY'))
TIMEOUT = 20        # seconds the Haiku call may take; the hook's own limit is 30
FRESH = 900         # the Claude app's list counts while it is this new, as for the Kit window
MAX_OPEN = 25       # open sessions compared at most, the most recent first
KEEP = 7 * 86400    # records, prompts and a prompt that waits are kept this long
KIT_MARK = '[Sttark Claude Kit]'
HEADER = 'Same work'
KEEP_LABEL = 'Keep here'
SEND_WORDS = 'The Kit sends your prompt to that session, as if you typed it there.'
KEEP_WORDS = 'This session does the work. The Kit does not ask again.'

RULES = """A person starts a new Claude Code session. Other sessions are open on the same Mac. Decide whether one of \
them already does the work of the new session's first message, so the person can send the message there and keep \
one session for each piece of work.

A session's work is its project or area, as its name says (a session's name is usually a short handle for its project \
or area, such as "Order Page"), not only the task it did last: a new task in the same app or project belongs to it. \
Name a session only when the message clearly belongs to that work and, when a repository shows, to the same \
repository. A shared word, the same kind of task, the same tool, the same building or the same people is not enough. \
Answer NONE when the message could belong to more than one session, asks for a new or separate session, starts \
something new, or when you are not sure. A wrong session costs the person a needless question; NONE costs nothing.

Answer on one line: the session's number or NONE, then " - " and a reason of under 15 words."""


def log(line):
    e.log('same   ' + line)


def one_line(s, n):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


# --- records -----------------------------------------------------------------------------------------------------

def read():
    try:
        with open(FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    for k in ('checked', 'asked', 'queue'):
        d.setdefault(k, {})
    return d


@contextmanager
def record():
    """same-work.json, read and written under its own lock. Looks and questions older than KEEP go, and the prompts
    that nothing names any more; a prompt that waits goes only in deliver(), which logs it."""
    os.makedirs(KIT, exist_ok=True)
    with open(FILE + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        d = read()
        yield d
        now = time.time()
        d['checked'] = {k: v for k, v in d['checked'].items() if now - v < KEEP}
        d['asked'] = {k: v for k, v in d['asked'].items() if now - v.get('at', 0) < KEEP}
        named = {v.get('prompt_file') for part in ('asked', 'queue') for v in d[part].values()}
        for p in glob.glob(os.path.join(PROMPTS, '*.txt')):
            if p not in named and now - os.path.getmtime(p) > KEEP:
                os.unlink(p)
        tmp = FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, FILE)


# --- the conversation --------------------------------------------------------------------------------------------

def is_user_line(raw):
    return b'"type":"user"' in raw or b'"type": "user"' in raw


def person_text(d):
    """The words of one transcript entry when the person sent it as a prompt, else None: a tool result, Claude Code's
    own notes, a compact summary, an agent's line, a command's output, a task notice and the Kit's own prompts are not
    the person's. A prompt with only a picture is '' (it counts as a prompt)."""
    if d.get('type') != 'user' or d.get('isMeta') or d.get('isSidechain') or d.get('isCompactSummary') \
            or d.get('toolUseResult') is not None:
        return None
    c = (d.get('message') or {}).get('content')
    if isinstance(c, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c):
        return None
    t = e.clean(e.text_of(c))
    if t.startswith(('<', KIT_MARK)):
        return None
    if not t and not (isinstance(c, list) and any(isinstance(b, dict) and b.get('type') != 'text' for b in c)):
        return None
    return t


def attached(d):
    """Whether a saved prompt came with a picture or a file."""
    c = (d.get('message') or {}).get('content')
    return bool(d.get('imagePasteIds')) or (isinstance(c, list) and any(
        isinstance(b, dict) and b.get('type') not in ('text', 'tool_result') for b in c))


def first_look(tp, prompt):
    """(is this the session's first prompt, does it carry a picture or a file). The prompt may be saved in the
    conversation already, or not yet: then Claude Code's queue says whether it held more than text (an enqueue with
    the words as its content is text only). Stops at the first earlier prompt, so a long conversation costs a few
    lines."""
    mine, same, files, enqueued = e.clean(prompt), False, '[Image #' in prompt, None
    try:
        with open(tp, 'rb') as f:
            for raw in f:
                if b'"queue-operation"' in raw:
                    try:
                        q = json.loads(raw)
                    except ValueError:
                        continue
                    if q.get('operation') == 'enqueue':
                        enqueued = q
                    continue
                if not is_user_line(raw):
                    continue
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                t = person_text(d)
                if t is None:
                    continue
                if t == mine and not same:
                    same, files = True, files or attached(d)
                    continue
                return False, files
    except OSError:
        pass
    if not same and enqueued is not None and not isinstance(enqueued.get('content'), str):
        files = True
    return True, files


def prompts_in(data):
    """The person's prompts in a piece of a saved conversation, oldest first (a cut line at either end is skipped)."""
    out = []
    for raw in data.split(b'\n'):
        if not is_user_line(raw):
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        t = person_text(d)
        if t:
            out.append(t)
    return out


def facts(tp):
    """What a session's saved conversation says about its work: {'folder' (the last one it ran in), 'started' (when the
    conversation began), 'first' (its first prompt), 'latest' (its 2 newest prompts)}, from the file's first 256 KB
    and last 512 KB; None when it can't be read."""
    try:
        st = os.stat(tp)
        with open(tp, 'rb') as f:
            head = f.read(262144)
            f.seek(max(0, st.st_size - 524288))
            tail = f.read() if st.st_size > 262144 else head
    except OSError:
        return None
    first = prompts_in(head)[:1]
    latest = prompts_in(tail)[-2:]
    cwds = e.CWD_RE.findall(tail) or e.CWD_RE.findall(head)
    try:
        folder = json.loads(b'"' + cwds[-1] + b'"') if cwds else ''
    except ValueError:
        folder = ''
    return {'folder': folder, 'started': getattr(st, 'st_birthtime', 0) or st.st_mtime,
            'first': first[0] if first else '', 'latest': [p for p in latest if not first or p != first[0]]}


def repo(folder):
    """The git repository a folder is in, as its main checkout's folder (a worktree counts as its repository), or ''.
    The home folder never counts, so a home folder kept in git doesn't make every folder one repository."""
    home = os.path.realpath(os.path.expanduser('~'))
    d = os.path.realpath(folder) if folder else ''
    while d and d not in ('/', home):
        g = os.path.join(d, '.git')
        if os.path.isdir(g):
            return d
        if os.path.isfile(g):
            try:
                with open(g) as f:
                    m = re.match(r'gitdir:\s*(.+)', f.read().strip())
            except OSError:
                m = None
            if m:
                gd = m.group(1).strip()
                gd = gd if os.path.isabs(gd) else os.path.normpath(os.path.join(d, gd))
                i = gd.find('/.git/worktrees/')
                if i >= 0:
                    return gd[:i]
            return d
        d = os.path.dirname(d)
    return ''


def short_path(p):
    home = os.path.expanduser('~')
    return '~' + p[len(home):] if p == home or p.startswith(home + '/') else p


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def live_copies():
    """{conversation id: [entrypoint, ...]} of the Claude Code processes that run now, from the record Claude Code keeps
    for each (~/.claude/sessions/<pid>.json)."""
    out = {}
    for path in glob.glob(os.path.join(e.CLAUDE_DIR, 'sessions', '*.json')):
        try:
            with open(path) as f:
                d = json.load(f)
            pid = int(d.get('pid') or 0)
        except (OSError, ValueError, TypeError):
            continue
        if pid and d.get('sessionId') and alive(pid):
            out.setdefault(d['sessionId'], []).append(d.get('entrypoint') or '')
    return out


def elsewhere(cid, live):
    """Whether the conversation runs now where the Kit can't type a prompt into it: in the Claude desktop app on This
    computer, or in a terminal. The server's copy (sdk-cli) and the Kit's own copy (a kit- screen) can take one: the
    Kit ends that copy, without archiving, and starts the session with the prompt (wait.py bring_back())."""
    kinds = live.get(cid) or []
    if not kinds or all(k == 'sdk-cli' for k in kinds):
        return False
    return not e.screen_ids('kit-' + cid[:8])


def span(s):
    """A length of time in words: "under a minute", "1 minute", "5 minutes", "2 hours", "3 days"."""
    s = max(0, s)
    if s < 60:
        return 'under a minute'
    if s < 3600:
        m = int(round(s / 60))
        return '1 minute' if m == 1 else '%d minutes' % m
    if s < 86400:
        h = int(round(s / 3600))
        return '1 hour' if h == 1 else '%d hours' % h
    d = int(s // 86400)
    return '1 day' if d == 1 else '%d days' % d


def ago(t, now=None):
    """When, from now: "just now", "5 minutes ago", "2 hours ago", "yesterday", "3 days ago"."""
    s = max(0, (now or time.time()) - t)
    if s < 60:
        return 'just now'
    if 86400 <= s < 2 * 86400:
        return 'yesterday'
    return span(s) + ' ago'


# --- the check at a first prompt ---------------------------------------------------------------------------------

def open_sessions(cse, sid):
    """The other sessions the Claude app lists, whose conversation is on this Mac, the most recent first: [{cse, title,
    transcript, last, reason, url}]. None when the Claude app's list can't be read (it is read again when it is old)."""
    s = e.peek()
    lst = s.get('app_list') or {}
    if time.time() - lst.get('at', 0) > FRESH:
        try:
            e.app_list()  # one small read, as the Kit window makes; it waits after failed reads
        except Exception:
            pass
        s = e.peek()
        lst = s.get('app_list') or {}
        if time.time() - lst.get('at', 0) > FRESH:
            return None
    known = s.get('sessions') or {}
    out = []
    for x in lst.get('sessions') or []:
        c = x.get('id') or ''
        rec = known.get(c) or {}
        tp = rec.get('transcript') or ''
        if not c or c == cse or not tp.endswith('.jsonl') or not os.path.exists(tp) \
                or os.path.basename(tp)[:-len('.jsonl')] == sid:
            continue
        out.append({'cse': c, 'title': (x.get('title') or rec.get('title') or '').strip() or 'Session ' + c[-6:],
                    'transcript': tp, 'last': e.iso_time(x.get('last')) or rec.get('at', 0), 'reason': rec.get('reason') or '',
                    'url': rec.get('url') or 'https://claude.ai/code/session_' + c.split('_', 1)[1]})
    out.sort(key=lambda c: c['last'], reverse=True)
    return out[:MAX_OPEN]


def candidates(cse, sid, cwd):
    """(the open sessions the new one could be the same work as, with their facts, or None when the Claude app's list
    can't be read; why there are none). Same repository when both show one; never one that runs where the Kit can't
    type into it."""
    found = open_sessions(cse, sid)
    if found is None:
        return None, "the Claude app's list of sessions could not be read"
    if not found:
        return [], 'no other session is open on this Mac'
    mine, live, out = repo(cwd), live_copies(), []
    other, there = 0, 0
    for c in found:
        f = facts(c['transcript'])
        if not f:
            continue
        c.update(f)
        c['repo'] = repo(f['folder']) if f['folder'] else ''
        if mine and c['repo'] and c['repo'] != mine:
            other += 1
            continue
        if elsewhere(os.path.basename(c['transcript'])[:-len('.jsonl')], live):
            there += 1
            continue
        out.append(c)
    if out:
        return out, ''
    if other and not there:
        return out, '%d open session(s), none in this repository' % len(found)
    if there and not other:
        return out, '%d open session(s), each open in the Claude desktop app or a terminal, where the Kit can\'t send a prompt' % len(found)
    return out, '%d open session(s), none in this repository that the Kit can send a prompt to' % len(found)


def folder_words(folder, r):
    if not folder:
        return 'folder unknown'
    if r:
        return 'folder %s (repository %s)' % (short_path(folder), os.path.basename(r))
    return 'folder %s (not a repository)' % short_path(folder)


def question_for(prompt, cwd, cands, now=None):
    """The text the Haiku call reads: the new prompt and each open session, numbered."""
    r = repo(cwd)
    here = ('%s (repository %s)' % (short_path(cwd), os.path.basename(r)) if r
            else '%s (not one repository: it can hold many, so the message says which work it is)' % short_path(cwd or '~'))
    lines = ["New session's first message:", prompt[:3000].strip(), '', "New session's folder: " + here, '', 'Open sessions:']
    for i, c in enumerate(cands, 1):
        lines.append('%d. "%s" - %s; started %s; last active %s.' % (
            i, c['title'], folder_words(c.get('folder'), c.get('repo')), ago(c['started'], now), ago(c['last'], now) if c['last'] else 'unknown'))
        if c.get('first'):
            lines.append('   It started with: "%s"' % one_line(c['first'], 300))
        if c.get('latest'):
            lines.append('   Its latest messages: ' + ' / '.join('"%s"' % one_line(p, 200) for p in c['latest']))
        if c.get('reason'):
            lines.append('   The Kit\'s note on its latest work: "%s"' % one_line(c['reason'], 120))
    lines += ['', 'Which open session, if any, already does this work?']
    return '\n'.join(lines)


def ask_model(text):
    """One line from Haiku (MODEL): the session's number or NONE, " - " and why. No tools, hooks off, outside the
    session, as the Kit's other side calls; STTARK_SAME_MODEL stands in for it in tests."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    cmd = [STUB] if STUB else [e.CLAUDE, '-p', '--model', MODEL, '--effort', 'low', '--no-session-persistence',
                               '--strict-mcp-config', '--tools', '', '--settings', '{"disableAllHooks":true}',
                               '--system-prompt', RULES]
    r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=TIMEOUT, env=env, cwd='/tmp')
    out = r.stdout.strip()
    if r.returncode and not out:
        raise RuntimeError('exit %d: %s' % (r.returncode, one_line(r.stderr, 160)))
    return out.splitlines()[0].strip() if out else ''


def label(title):
    return 'Send to ' + (title if len(title) <= 32 else title[:31].rstrip() + '…')


def question(t, now=None):
    return 'This looks like the same work as “%s”, a session that started %s. Where do you want this prompt?' % (
        t['title'], ago(t['started'], now))


def ask_context(t, q, now=None):
    """The context that tells Claude to ask `q`, before anything else."""
    where = short_path(t.get('folder') or '') or 'its folder'
    return ('%s Same work: this is the first prompt of this session, and another session open on this Mac already does '
            'this work: "%s" (started %s, in %s; its link: %s). The person keeps one session for each piece of work, '
            'so ask them first.\n\n'
            'Your first step, before any other tool and before any text: call the AskUserQuestion tool with exactly one '
            'question, as written here:\n'
            '- question: "%s"\n'
            '- header: "%s"\n'
            '- multiSelect: false\n'
            '- options, in this order:\n'
            '  1. label: "%s"; description: "%s"\n'
            '  2. label: "%s"; description: "%s"\n'
            'The Kit acts on the answer and then tells you what to do. Do nothing else before it does.'
            % (KIT_MARK, t['title'], ago(t['started'], now), where, t['url'], q, HEADER, label(t['title']),
               SEND_WORDS, KEEP_LABEL, KEEP_WORDS))


def on_prompt(data):
    """UserPromptSubmit. The hook's output when Claude must ask, else None."""
    prompt = (data.get('prompt') or '').strip()
    sid = data.get('session_id') or ''
    tp = data.get('transcript_path') or ''
    if not prompt or not sid or prompt.startswith(('<', '/', KIT_MARK)) or e.peek().get('same_work') is False:
        return None
    if sid in read()['checked']:
        return None
    first, files = first_look(tp, prompt)
    if not first:
        return None
    with record() as d:  # one look per session, whatever it finds: a session is never asked twice
        if sid in d['checked']:
            return None
        d['checked'][sid] = time.time()
    cse = e.session_id(tp)
    if not cse:
        return None  # not a Remote Control session: no link to send to or from
    snippet = one_line(prompt, 80)
    if files:
        log(f'{cse} not checked: its first prompt has a picture or a file, which a prompt sent to another session can\'t carry | {snippet}')
        return None
    if len(prompt.split()) < 2:
        log(f'{cse} not checked: its first prompt is one word, too little to compare | {snippet}')
        return None
    e.limit_for(sid, tp, cse)
    if e.at_limit():
        log(f'{cse} not checked: skipped at the usage limit | {snippet}')
        return None
    t0 = time.time()
    cands, why = candidates(cse, sid, data.get('cwd') or '')
    if not cands:
        log(f'{cse} no match: {why} | {snippet}')
        return None
    try:
        answer = ask_model(question_for(prompt, data.get('cwd') or '', cands))
    except Exception as x:
        log(f'{cse} check failed: {type(x).__name__}: {one_line(str(x), 160)} | {snippet}')
        return None
    secs = time.time() - t0
    m = re.match(r'\W*(NONE|\d+)\b', answer, re.I)
    reason = one_line(answer.split(' - ', 1)[1] if ' - ' in answer else '', 160)
    n = int(m.group(1)) if m and m.group(1).isdigit() else 0
    if not m or (m.group(1).isdigit() and not 1 <= n <= len(cands)):
        log(f'{cse} check failed: an answer it could not read: {one_line(answer, 80)!r} | {snippet}')
        return None
    if not n:
        log(f'{cse} no match among {len(cands)} open session(s) ({secs:.1f}s) - {reason or "none does this work"} | {snippet}')
        return None
    t = cands[n - 1]
    os.makedirs(PROMPTS, exist_ok=True)
    pfile = os.path.join(PROMPTS, sid + '.txt')
    with open(pfile, 'w') as f:
        f.write(data.get('prompt') or prompt)
    target = {k: t.get(k) for k in ('cse', 'title', 'transcript', 'folder', 'url', 'started')}
    now = time.time()
    q = question(t, now)
    with record() as d:
        d['asked'][sid] = {'at': now, 'cse': cse, 'prompt_file': pfile, 'question': q, 'send': label(t['title']),
                           'target': target}
    log(f'{cse} asks: same work as {t["cse"]} "{t["title"]}", started {ago(t["started"], now)} ({secs:.1f}s) - '
        f'{reason or "the same work"} | {snippet}')
    return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ask_context(t, q, now)}}


# --- the answer, and the prompt sent ---------------------------------------------------------------------------------

def answers_of(x):
    """{question: answer} from AskUserQuestion's result (or input); {} when it has none."""
    if isinstance(x, dict) and isinstance(x.get('answers'), dict):
        return {str(k): v if isinstance(v, str) else ', '.join(map(str, v)) if isinstance(v, list) else str(v)
                for k, v in x['answers'].items()}
    if isinstance(x, str):  # the result as text: "... "question"="answer", ..."
        return dict(re.findall(r'"((?:[^"\\]|\\.)*)"="((?:[^"\\]|\\.)*)"', x))
    return {}


def bring_back(w, prompt):
    """wait.py bring_back(): the session starts on its own link with `prompt` as its first message, typed locally, so
    Claude Code runs it as the person's own. Raises RuntimeError('busy') while a turn or its agents run. A test
    replaces this function."""
    return load('wait').bring_back(w, prompt)


def send_now(item):
    """One prompt to its session now: ('sent' | 'busy' | 'failed' | 'gone', why). 'busy': in a turn, or its agents still
    work, or the Kit started it moments ago; 'failed': try again later; 'gone': it can't go."""
    t = item['target']
    try:
        with open(item['prompt_file']) as f:
            prompt = f.read()
    except OSError:
        return 'gone', 'the prompt is not on this Mac any more'
    if not prompt.strip():
        return 'gone', 'the prompt is empty'
    if not t.get('cse') or not os.path.exists(t.get('transcript') or ''):
        return 'gone', 'its conversation is not on this Mac'
    if elsewhere(os.path.basename(t['transcript'])[:-len('.jsonl')], live_copies()):
        return 'failed', 'it is open in the Claude desktop app or in a terminal now'
    if DRY:
        return 'sent', 'dry: nothing sent'
    w = {'id': 'same-' + item['from_sid'][:8], 'cse': t['cse'], 'transcript': t['transcript'],
         'cwd': t.get('folder') or '', 'title': t.get('title') or ''}
    try:
        ok = bring_back(w, prompt)
    except RuntimeError as x:
        if str(x) == 'busy':
            return 'busy', 'it is in a turn, or its agents still work'
        return 'failed', one_line(str(x), 160) or 'it did not start'
    except Exception as x:
        return 'failed', '%s: %s' % (type(x).__name__, one_line(str(x), 140))
    return ('sent', '') if ok else ('gone', 'its conversation is not on this Mac')


def reply(t, res, why):
    """The context after "Send to": the one line Claude replies with."""
    name, link = '“%s”' % t['title'], t['url']
    head = '%s The person chose "%s". ' % (KIT_MARK, label(t['title']))
    rest = ' Reply with this one line and nothing else, and do no other work in this session:\n'
    if res == 'sent':
        return head + 'The Kit sent their prompt to that session; it runs there now as their own message.' + rest + \
            'Sent to %s: %s' % (name, link)
    if res == 'busy':
        return head + 'That session is in a turn now, so the Kit sends the prompt there when the turn ends.' + rest + \
            'Sent to %s. It runs there when its current turn ends: %s' % (name, link)
    if res == 'failed':
        return head + 'The Kit could not send it yet (%s) and tries again each minute.' % why + rest + \
            'Sent to %s. It runs there as soon as the Kit can start it: %s' % (name, link)
    return head + 'The Kit could not send it: %s. Tell the person in one line, with the link %s, and ask whether to ' \
                  'do the work in this session instead.' % (why, link)


def on_answer(data):
    """PostToolUse (AskUserQuestion). The hook's output for the Kit's question, else None."""
    sid = data.get('session_id') or ''
    a = read()['asked'].get(sid)
    if not a or a.get('answer'):
        return None
    got = answers_of(data.get('tool_response')) or answers_of(data.get('tool_input'))
    ans = None
    for q, v in got.items():
        if q.strip() == a['question'].strip() or a['target']['title'] in q or v.strip() in (a['send'], KEEP_LABEL):
            ans = v.strip()
    if ans is None:
        return None  # another question
    t, low = a['target'], ans.lower()
    choice = 'send' if low == a['send'].lower() or low.startswith('send to') else 'keep' if low.startswith('keep here') else 'other'
    with record() as d:
        x = d['asked'].get(sid)
        if not x or x.get('answer'):
            return None
        x.update(answer=choice, answered_at=time.time())
    cse = a.get('cse') or sid[:8]
    if choice == 'keep':
        log(f'{cse} keeps its first prompt here: the person chose {KEEP_LABEL}, not "{t["title"]}"')
        return {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext':
                '%s The person chose "%s": this session does the work. Go on with their first prompt now, as usual. '
                'The Kit does not ask again.' % (KIT_MARK, KEEP_LABEL)}}
    if choice == 'other':
        log(f'{cse} answered the same work question in its own words, so the Kit sends nothing: {one_line(ans, 80)}')
        return None
    item = {'at': time.time(), 'from_sid': sid, 'from_cse': a.get('cse') or '', 'target': t, 'prompt_file': a['prompt_file']}
    res, why = send_now(item)
    if res == 'sent':
        log(f'{t["cse"]} "{t["title"]}" got the first prompt of {cse}: the person chose Send to'
            + (' (dry: nothing sent)' if DRY else ''))
    elif res in ('busy', 'failed'):
        with record() as d:
            d['queue'][sid] = dict(item, tried_at=time.time(), tries=1, why=why)
        log(f'{t["cse"]} "{t["title"]}" gets the first prompt of {cse} '
            + ('when its turn ends: the person chose Send to' if res == 'busy'
               else f'as soon as it can start: the person chose Send to; it could not start now: {why}'))
    else:
        log(f'{t["cse"]} "{t["title"]}" could not get the first prompt of {cse}: {why}')
    return {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': reply(t, res, why)}}


def deliver(now=None):
    """The minute check (wait.py --check): send each prompt that waits for its session, the oldest first. One that still
    can't go waits, and goes after KEEP with a log line. Returns how many went."""
    went = 0
    for sid, q in sorted(read()['queue'].items(), key=lambda kv: kv[1].get('at', 0)):
        t, now_ = q['target'], now or time.time()
        if now_ - q.get('at', now_) > KEEP:
            with record() as d:
                d['queue'].pop(sid, None)
            log(f'{t["cse"]} "{t["title"]}" never got the first prompt of {q.get("from_cse") or sid[:8]}: '
                f'{q.get("why") or "it could not start"}; dropped after 7 days')
            continue
        res, why = send_now(q)
        told = q.get('why')
        with record() as d:
            x = d['queue'].get(sid)
            if x is None:
                continue
            if res in ('sent', 'gone'):
                d['queue'].pop(sid, None)
            else:
                x.update(tried_at=time.time(), tries=x.get('tries', 0) + 1, why=why)
        if res == 'sent':
            went += 1
            log(f'{t["cse"]} "{t["title"]}" got the first prompt of {q.get("from_cse") or sid[:8]}, which waited '
                f'{span(now_ - q["at"])}' + (' (dry: nothing sent)' if DRY else ''))
        elif res == 'gone':
            log(f'{t["cse"]} "{t["title"]}" could not get the first prompt of {q.get("from_cse") or sid[:8]}: {why}')
        elif res == 'failed' and why != told:
            log(f'{t["cse"]} "{t["title"]}" could not start for the first prompt of {q.get("from_cse") or sid[:8]}: '
                f'{why}; the Kit tries again each minute')
    return went


def listing():
    d, now = read(), time.time()
    if not d['asked'] and not d['queue']:
        print('No question asked in the last 7 days, and no prompt waits.')
        return
    for sid, a in sorted(d['asked'].items(), key=lambda kv: kv[1].get('at', 0)):
        print('%s %s asked: same work as "%s"; %s' % (time.strftime('%a %-I:%M %p', time.localtime(a['at'])),
                                                     a.get('cse') or sid[:8], a['target']['title'],
                                                     'answered: ' + a['answer'] if a.get('answer') else 'no answer yet'))
    for sid, q in d['queue'].items():
        print('waits: the first prompt of %s for "%s", since %s (%d tries; %s)' % (
            q.get('from_cse') or sid[:8], q['target']['title'], ago(q['at'], now), q.get('tries', 0), q.get('why') or ''))


def main():
    if sys.argv[1:] == ['--deliver']:
        deliver()
        return
    if sys.argv[1:] == ['--list']:
        listing()
        return
    if os.environ.get('EFFORT_JUDGE'):
        return
    try:
        data = json.load(sys.stdin)
        event = data.get('hook_event_name') or 'UserPromptSubmit'
        out = on_answer(data) if event == 'PostToolUse' else on_prompt(data) if event == 'UserPromptSubmit' else None
    except Exception as x:  # never in the way of a prompt or a step
        try:
            log(f'error: {type(x).__name__}: {one_line(str(x), 200)}')
        except Exception:
            pass
        return
    if out:
        print(json.dumps(out))


if __name__ == '__main__':
    main()
