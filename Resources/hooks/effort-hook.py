#!/usr/bin/python3
"""Claude Code hook: set each Remote Control session's effort to what the task
needs. Installed and kept up to date by the Sttark Claude Kit app.

UserPromptSubmit: the prompt and the last few messages go to a quick side call
(claude -p, with the model picked in the app's menu, the newest Sonnet by default), which picks low, medium, high, xhigh or max. If that
differs from the session's level, set-session-effort.py sends the change the
same way the Claude app's effort picker does, so the first step of the turn
already runs at the new level.

PostToolUse (in the background): at 10, 25 and 50 tool calls into a turn the
side call sees the request and the work so far, and raises or lowers the level
to match how the work is actually going.

Hands off when the app's "Auto effort" is off, when a session is set to Manual
in the app, or when the person changes a session's effort themselves (the hook
sees a level it didn't send and sets that session to Manual). A session reopening
in a new process starts from its new level instead.

Only sessions with a claude.ai session id (Remote Control) can be changed.
Every decision is logged to ~/Library/Logs/sttark-claude-kit.log.
"""
import calendar, fcntl, importlib.util, json, os, re, subprocess, sys, time, uuid
from contextlib import contextmanager

LOG = os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser('~/Library/Application Support/SttarkClaudeKit/state.json')
CLAUDE_LOG = os.path.expanduser('~/Library/Logs/Claude/main.log')  # the Claude app's log: which session is open in it
FRONT = os.path.join(os.path.dirname(STATE), 'claude-front.json')  # when the Claude app was in front, from the menu bar app
CLAUDE = os.path.expanduser('~/.local/bin/claude')
DEFAULT_MODEL = 'sonnet'  # Claude Code's alias for the newest Sonnet, the best judge in the model test
LEVELS = ['low', 'medium', 'high', 'xhigh', 'max']
CHECKPOINTS = (10, 25, 50)  # tool calls into a turn when the level is checked again
SETTLE = 30  # seconds after a send when a different reported level is just the change still arriving

RULES = """You set the effort level for a Claude Code agent before it starts on \
the user's latest message. Higher effort means more thinking and more careful \
work, but more time and cost. Pick the lowest level that still gets the work \
done right the first time.

low: quick answers, lookups, confirmations, small talk, a one-line edit.
medium: routine work with a clear path: a small edit, a short draft, a simple \
search or command or two.
high: multi-step work: code changes across a few files, debugging with a \
known cause, research that needs judgment, writing that has to be right.
xhigh: hard or open-ended work: debugging with an unknown cause, designing or \
building a tool or feature end to end, long tasks touching many systems, \
analysis where a mistake is costly.
max: the hardest work, where a wrong answer is costly and hard to undo: a \
problem earlier attempts in this conversation already failed to solve, \
subtle bugs in safety, money or production systems, or deep design work \
across many systems. Use it whenever one of these fits.

Rules:
- Short replies like "yes", "go ahead", "do option 1" take the size of the \
work they approve. Read the recent conversation to see what that work is.
- If the user names an effort level, use it.
- If torn between two levels, pick the higher one.
- UI work people will use (a page, screen, layout, dialog, mockup or visual) is \
at least high, and a new page or a redesign is at least xhigh: how it should \
work for the person using it is a judgment call, not a routine edit.

Answer on one line: the level, then " - " and a reason of under 12 words."""

RECHECK = """You check the effort level of a Claude Code agent partway through \
a task. Higher effort means more thinking and more careful work, but more time \
and cost. The goal is enough effort to finish the task right, no more.

You see the user's request, what the agent has done so far, and its current \
level. Decide what level the REST of the task needs, judging from how the work \
is actually going: errors, retries, dead ends, a cause still unknown, scope \
growing, or many systems involved mean harder than it first looked. If the hard \
part is done (the cause found, the design settled) and what remains is routine \
(repeating a known edit, a build, a commit), the rest needs less. Raise or \
lower to match.

UI work is different: looking at screenshots or renders of the result and \
judging them is where the design gets decided, not a routine check. While UI \
work still has screenshots to look at, judge or fix, keep it at high or above.

Levels: low (trivial), medium (routine), high (multi-step work with judgment), \
xhigh (hard or open-ended: unknown causes, building something end to end, \
costly mistakes), max (the agent is already at xhigh and still stuck: \
repeated failures, going in circles, or no progress toward the goal).

If torn between two levels, pick the higher one. Answer on one line: the \
level, then " - " and a reason of under 12 words."""


BROWSER_RULE = ("Browser rule from Sttark Claude Kit: when you need the person's browser, use only the Chrome window "
                "named Claude, with the claude-window command (claude-window go <url>, url, text, js '<code>'). "
                "Never open a new tab or window and never bring Chrome to the front: both take the person's screen "
                "while they're typing. If there's no Claude window, ask them to click Open Claude window in the "
                "Sttark Claude Kit menu.")


def log(line):
    with open(LOG, 'a') as f:
        f.write(time.strftime('%F %T ') + line + '\n')


@contextmanager
def state():
    """The shared state, read and written under a lock (the app uses it too):
    {"paused": bool, "sessions": {sid: {...}}}."""
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            s = json.load(open(STATE))
        except (OSError, ValueError):
            s = {}
        s.setdefault('sessions', {})
        yield s
        tmp = STATE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, STATE)


def peek():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {}


def session_id():
    """The claude.ai id of this session: from `claude --remote-control`'s
    environment, or the --session-id a `claude rc` server starts it with."""
    b = os.environ.get('CLAUDE_CODE_BRIDGE_SESSION_ID', '')
    if b:
        return 'cse_' + b.split('_', 1)[1] if b.startswith('session_') else b
    pid = os.environ.get('CLAUDE_PID', '')
    if not pid:
        return None
    args = subprocess.run(['ps', '-ww', '-o', 'args=', '-p', pid],
                          capture_output=True, text=True).stdout
    m = re.search(r'--session-id[= ](cse_\w+)', args)
    return m.group(1) if m else None


def session_process():
    """This session's Claude Code process (its pid and start time) and the --effort it was started with."""
    pid = os.environ.get('CLAUDE_PID', '')
    if not pid:
        return '', ''
    out = subprocess.run(['ps', '-ww', '-o', 'lstart=,args=', '-p', pid],
                         capture_output=True, text=True).stdout
    if not out.strip():
        return '', ''
    m = re.search(r'--effort[= ](\w+)', out)
    return f'{pid} {out[:24].strip()}', m.group(1) if m else ''


def reopened(sid, x, proc, level):
    """Inside the state lock. A session that reopens (after a restart, or when the server brings back an idle
    one) runs in a new process at the level it was started with, not the one last sent. That level becomes the
    starting point, so it isn't mistaken for the person changing it."""
    if not proc or x.get('proc') == proc:
        return
    if x.get('proc'):
        if level:
            x['level'] = x['sent'] = level
            x['sent_at'] = 0
        else:
            x.pop('sent', None)
        log(f'reopen {sid} at {level or "?"}; starting from there')
    x['proc'] = proc


NOTE = re.compile(r'<(system-reminder|local-command-[a-z]+|command-[a-z]+)>.*?</\1>', re.S)


def clean(text):
    """What the person wrote, without the notes Claude Code adds around it (system reminders, command output)."""
    return NOTE.sub('', text or '').strip()


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content
                         if isinstance(b, dict) and b.get('type') == 'text')
    return ''


def recent(path, prompt='', turns=6, each=600, last_reply=4000):
    """Last few user prompts and Claude replies. Claude's latest reply is kept
    nearly whole (start and end), since a bare "go" approves whatever it
    proposed, and plans usually sit at its top."""
    out = []
    try:
        with open(path) as f:
            lines = f.readlines()[-600:]
    except OSError:
        return ''
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('type') not in ('user', 'assistant') or e.get('isMeta'):
            continue
        t = clean(text_of((e.get('message') or {}).get('content')))
        if not t or t.startswith('<'):
            continue
        who = 'User' if e['type'] == 'user' else 'Claude'
        if out and out[-1][0] == who:
            out[-1] = (who, out[-1][1] + '\n' + t)
        else:
            out.append((who, t))
    # The prompt being judged may already be saved; it is sent separately.
    if out and out[-1][0] == 'User' and out[-1][1].strip() == prompt.strip():
        out.pop()
    out = out[-turns:]
    last = max((i for i, (w, _) in enumerate(out) if w == 'Claude'), default=-1)

    def trim(i, t):
        cap = last_reply if i == last else each
        if len(t) <= cap:
            return t
        head = cap * 5 // 8
        return t[:head] + '\n[...]\n' + t[-(cap - head):]
    return '\n\n'.join(f'{w}: {trim(i, t)}' for i, (w, t) in enumerate(out))


def model():
    return peek().get('model') or DEFAULT_MODEL


def list_models():
    """The two newest Haiku and two newest Sonnet models the API offers, newest first.
    New ones show up here without an update. Saved to the state for the app's menu."""
    import urllib.request
    h = sse().headers()
    h['anthropic-beta'] = 'oauth-2025-04-20'
    r = urllib.request.Request('https://api.anthropic.com/v1/models?limit=100', headers=h)
    ids = [m['id'] for m in json.load(urllib.request.urlopen(r, timeout=15))['data']]
    found = {}
    for i in ids:
        m = re.match(r'^claude-(haiku|sonnet)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$', i)
        if not m:
            continue
        short = 'claude-%s-%s%s' % (m.group(1), m.group(2), '-' + m.group(3) if m.group(3) else '')
        found[short] = (m.group(1), float(m.group(2) + '.' + (m.group(3) or '0')))
    out = []
    for fam in ('haiku', 'sonnet'):
        mine = sorted((v[1], k) for k, v in found.items() if v[0] == fam)[::-1][:2]
        for num, k in mine:
            label = '%s %s' % (fam.capitalize(), ('%g' % num))
            out.append({'id': k, 'label': label})
    with state() as s:
        s['models'] = out
        s['models_at'] = time.time()
    print(json.dumps(out))


def judge(ask, system=RULES):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID',
                                'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    r = subprocess.run(
        [CLAUDE, '-p', '--model', model(), '--effort', 'low',
         '--no-session-persistence', '--strict-mcp-config', '--tools', '',
         '--settings', '{"disableAllHooks":true}', '--system-prompt', system, ask],
        capture_output=True, text=True, timeout=25, env=env, cwd='/tmp')
    answer = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ''
    m = re.match(r'\W*(low|medium|high|xhigh|max)\b', answer, re.I)
    return (m.group(1).lower() if m else None), answer


def turn_so_far(path):
    """The prompt that started this turn, its uuid, how many tool calls Claude
    has made since, and a short account of that work."""
    try:
        with open(path) as f:
            lines = f.readlines()[-3000:]
    except OSError:
        return None
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            pass
    start = None
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if e.get('type') == 'user' and not e.get('isMeta'):
            t = clean(text_of((e.get('message') or {}).get('content')))
            if t and not t.startswith('<'):
                start = i
                break
    if start is None:
        return None
    prompt = text_of(entries[start]['message']['content']).strip()
    calls, errors, work = 0, 0, []
    for e in entries[start + 1:]:
        content = (e.get('message') or {}).get('content')
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'tool_use':
                calls += 1
                arg = json.dumps(b.get('input', {}), ensure_ascii=False)[:160]
                work.append(f'{calls}. {b.get("name")} {arg}')
            elif b.get('type') == 'text' and e.get('type') == 'assistant':
                work.append('Agent: ' + re.sub(r'\s+', ' ', b['text'])[:300])
            elif b.get('type') == 'tool_result' and b.get('is_error'):
                errors += 1
                work.append('   (that step failed)')
    text = '\n'.join(work)
    if len(text) > 6000:
        text = text[:1500] + '\n[...]\n' + text[-4500:]
    return entries[start].get('uuid', ''), prompt, calls, errors, text


def sse():
    spec = importlib.util.spec_from_file_location(
        'sse', os.path.join(HERE, 'set-session-effort.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def send(sid, level):
    """Change the session's effort. Returns (status, text, request id); the id tells the kit's own changes
    apart from the person's on the server."""
    rid = str(uuid.uuid4())
    with state() as s:  # saved first, so a check that reads the server mid-send knows this change is the kit's
        s['sessions'].setdefault(sid, {})['sent_id'] = rid
    try:
        return (*sse().send(sid, level, rid), rid)
    except Exception as e:
        return 0, repr(e), rid


def live(sid):
    """The session as the server sees it right now, or {} when it can't be read."""
    try:
        return sse().session(sid)
    except Exception:
        return {}


def by_hand(sid, why, d=None):
    """Whether the person picked this session's level in the Claude app; if so the session goes to Manual and
    the level is returned, else ''. The server knows the moment they pick it; the session's own steps only show
    it once the step running then finishes, which can take minutes.
    The server keeps the id of the latest change. A pick is an id that is new since the kit last looked and
    isn't the kit's own, to a level other than the one the kit set. The first look only notes the id: a change
    from before then (the kit's own from before it saved ids, or a level a reopened session left behind)
    isn't the person's. Compared with the state as it is now, not a copy read before a send."""
    meta = ((live(sid) if d is None else d) or {}).get('external_metadata') or {}
    level, rid = meta.get('effort_level') or '', meta.get('effort_request_id') or ''
    if not (level and rid):
        return ''
    with state() as s:
        x = s['sessions'].setdefault(sid, {})
        hand = ('seen_id' in x and rid not in (x['seen_id'], x.get('sent_id'))
                and level != (x.get('sent') or x.get('level')) and not x.get('manual'))
        x['seen_id'] = rid
        if hand:
            x['manual'] = True
            x['level'] = level
            log(f'manual {sid} set to {level} by hand; leaving this session alone | {why}')
    return level if hand else ''


def fetch_title(sid):
    """The session's name in the Claude app, for the app's menu."""
    try:
        d = sse().session(sid)
    except Exception as e:
        if getattr(e, 'code', 0) == 404:
            # deleted in the Claude app: take it off the menu
            with state() as s:
                s['sessions'].pop(sid, None)
        return
    with state() as s:
        x = s['sessions'].setdefault(sid, {})
        x['title'] = d.get('title') or x.get('title') or ''
        x['url'] = d.get('session_url') or x.get('url', '')
        x['title_at'] = time.time()


ASKS = """You read the last reply Claude wrote in a work session. Answer YES only when Claude can't go on \
without the person and asks them directly: a question they must answer, a plan waiting for their go-ahead, a \
choice it needs them to make, or a step only they can do (approve, sign in, test). Everything else is NO: a \
finished report or answer; an optional offer ("if you want, I can...", "want me to also...?"); a draft or \
result left for the person to send or use on their own; anything where the work is done whether or not they \
reply. If torn, answer NO. Answer YES or NO, then " - " and a reason of under 10 words."""


def last_reply(path):
    try:
        with open(path) as f:
            lines = f.readlines()[-400:]
    except OSError:
        return ''
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('type') == 'assistant':
            t = clean(text_of((e.get('message') or {}).get('content')))
            if t:
                return t
    return ''


def asks_you(text):
    if not text:
        return False, 'no reply text'
    t = text if len(text) <= 3000 else text[:1000] + '\n[...]\n' + text[-2000:]
    _, answer = judge(f'Last reply:\n{t}\n\nDoes it need the person?', ASKS)
    return answer.upper().startswith('YES'), answer.split(' - ', 1)[-1]


def on_screen():
    """When each session was on screen in the Claude app on this Mac: open in the app (its log's
    setFocusedSession lines) while the app was in front with the screen on. {sid: [(start, end), ...]}"""
    now = time.time()
    try:
        front = [(a, b or now) for a, b in json.load(open(FRONT))]
        with open(CLAUDE_LOG, 'rb') as f:
            f.seek(max(0, os.path.getsize(CLAUDE_LOG) - 3_000_000))
            text = f.read().decode('utf-8', 'replace')
    except (OSError, ValueError, TypeError):
        return {}
    marks = []  # (when, session open from then on, or None)
    for m in re.finditer(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) .*setFocusedSession: sessionId=(\S+)', text, re.M):
        sid = m.group(2)
        marks.append((time.mktime(time.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')),
                      'cse_' + sid.split('_', 1)[1] if sid.startswith('session_') else None))
    shown = {}
    for (start, sid), (end, _) in zip(marks, marks[1:] + [(now, None)]):
        if sid:
            for a, b in front:
                if min(end, b) > max(start, a):
                    shown.setdefault(sid, []).append((max(start, a), min(end, b)))
    return shown


def seen_since(spans, iso):
    """On screen for a few seconds after the moment `iso` (the session's latest event)."""
    try:
        t = calendar.timegm(time.strptime(iso[:19], '%Y-%m-%dT%H:%M:%S'))  # the API's times are UTC
    except ValueError:
        return False
    return any(b - max(a, t) >= 3 for a, b in spans)


def track():
    """Every minute, from the app: which recent sessions are waiting on you. A session waits on you when it's
    blocked on you (asking a question or a permission), or when its finished reply asks you to answer or
    decide something (judged once per reply). Archived sessions, replies that need nothing, and sessions
    you've opened or had on screen since Claude last wrote don't count.
    Saved as x['app'] for the menu's Waiting on you section and its notices."""
    cutoff = time.time() - 86400
    sessions = peek().get('sessions', {})
    shown = on_screen()
    ids = [sid for sid, x in sessions.items() if x.get('at', 0) > cutoff]
    for sid in ids:
        try:
            d = sse().session(sid)
        except Exception as e:
            if getattr(e, 'code', 0) == 404:
                with state() as s:
                    s['sessions'].pop(sid, None)
            continue
        old = sessions.get(sid, {}).get('app', {})
        bucket, last = d.get('status_bucket'), d.get('last_event_at') or ''
        working = bucket == 'working' or d.get('worker_status') == 'running'
        archived = d.get('status') == 'archived'
        needs, why = False, ''
        # opened on any device (the Claude app's own record), or seen on this Mac's screen since Claude last wrote
        seen = not d.get('unread') or seen_since(shown.get(sid, []), last)
        # once you open a session it stops waiting on you, even if it's still asking, until Claude writes again
        if not archived and not working and not seen:
            if bucket == 'blocked':
                needs, why = True, 'waiting on your answer or permission'
            else:
                if old.get('judged') == last:  # this reply was already judged
                    needs, why = old.get('needs', False), old.get('why', '')
                else:
                    needs, why = asks_you(last_reply(sessions.get(sid, {}).get('transcript', '')))
        # not opened: Claude finished, and you haven't opened it or had it on screen since
        unseen = not seen and not archived and not working
        info = {'title': d.get('title') or '', 'url': d.get('session_url') or '', 'working': working, 'unseen': unseen,
                'archived': archived, 'unread': bool(d.get('unread')), 'seen': seen, 'needs': needs, 'why': why,
                'judged': last, 'last_event_at': last, 'checked': time.time()}
        with state() as s:
            x = s['sessions'].setdefault(sid, {})
            x['app'] = info
            if info['title']:
                x['title'] = info['title']
        by_hand(sid, 'seen on the server', d)


def title_later(sid, x):
    if time.time() - x.get('title_at', 0) > 60:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), '--title', sid],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


def remember(sid, **kv):
    with state() as s:
        x = s['sessions'].setdefault(sid, {})
        x.update(kv)
        x['at'] = time.time()
        return dict(x)


def on_prompt(data, sid):
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return
    snippet = re.sub(r'\s+', ' ', prompt)[:80]
    st = peek()
    x = st.get('sessions', {}).get(sid, {})
    proc, launched = session_process()
    if proc and x.get('proc') != proc:
        with state() as s:
            reopened(sid, s['sessions'].setdefault(sid, {}), proc, os.environ.get('CLAUDE_EFFORT') or launched)
            st = s
        x = dict(st['sessions'][sid])
    title_later(sid, x)
    if st.get('paused') or x.get('manual'):
        remember(sid)
        log(f'{"paused" if st.get("paused") else "manual"} {sid} left at {x.get("level", "?")} | {snippet}')
        return
    if by_hand(sid, snippet):
        return
    current = os.environ.get('CLAUDE_EFFORT') or x.get('level', '')
    t0 = time.time()
    try:
        context = recent(data.get('transcript_path', ''), prompt)
        level, answer = judge(f'Recent conversation:\n{context or "(none)"}\n\n'
                              f'Current effort: {current or "unknown"}\n\n'
                              f'Latest user message:\n{prompt[:4000]}\n\nEffort level?')
    except Exception as e:  # never block the prompt
        log(f'error  {sid} judge failed: {e!r} | {snippet}')
        return
    secs = time.time() - t0
    if not level:
        log(f'error  {sid} unreadable answer {answer!r} | {snippet}')
        return
    reason = answer.split(' - ', 1)[-1]
    if level == current:
        remember(sid, level=level, reason=reason)
        log(f'keep   {sid} {current} ({secs:.1f}s) {answer} | {snippet}')
        return
    if by_hand(sid, snippet):  # picked while the judge was thinking
        return
    status, text, rid = send(sid, level)
    if 200 <= status < 300:
        remember(sid, level=level, sent=level, sent_at=time.time(), sent_id=rid, seen_id=rid, reason=reason)
        time.sleep(1.5)  # let the change reach the session before the turn starts
        log(f'change {sid} {current}->{level} ({secs:.1f}s) {answer} | {snippet}')
    else:
        log(f'error  {sid} send {level} failed {status} {text[:120]} | {snippet}')


def on_tool(data, sid):
    if data.get('agent_id'):  # a subagent's own steps
        return
    level_now = (data.get('effort') or {}).get('level', '')
    proc, launched = session_process()
    with state() as s:
        x = s['sessions'].setdefault(sid, {})
        x['at'] = time.time()
        reopened(sid, x, proc, level_now or os.environ.get('CLAUDE_EFFORT') or launched)
        # A level the hook didn't send, well after its last send: the person set it. Hands off.
        if (level_now and x.get('sent') and level_now != x['sent'] and not x.get('manual')
                and time.time() - x.get('sent_at', 0) > SETTLE):
            x['manual'] = True
            log(f'manual {sid} set to {level_now} by hand; leaving this session alone')
        if level_now:
            x['level'] = level_now
        seen = dict(x)
        if s.get('paused') or x.get('manual'):
            title_later(sid, seen)
            return
    title_later(sid, seen)
    turn = turn_so_far(data.get('transcript_path', ''))
    if not turn:
        return
    uuid_, prompt, calls, errors, work = turn
    due = [c for c in CHECKPOINTS if calls >= c]
    if not due:
        return
    with state() as s:  # one check per checkpoint per turn, even when steps run in parallel
        x = s['sessions'].setdefault(sid, {})
        ck = x.get('checks') or {}
        if ck.get('turn') != uuid_:
            ck = {'turn': uuid_, 'done': []}
        point = due[-1]
        if point in ck['done']:
            return
        ck['done'] = [c for c in CHECKPOINTS if c <= point]
        x['checks'] = ck
    current = level_now or x.get('level', '')
    snippet = re.sub(r'\s+', ' ', prompt)[:60]
    t0 = time.time()
    try:
        level, answer = judge(f'User request:\n{prompt[:3000]}\n\n'
                              f'Work so far ({calls} tool calls, {errors} failed):\n{work}\n\n'
                              f'Current effort: {current or "unknown"}\n\nEffort level for the rest?',
                              RECHECK)
    except Exception as e:
        log(f'error  {sid} recheck at {calls} failed: {e!r} | {snippet}')
        return
    secs = time.time() - t0
    if not level:
        log(f'error  {sid} recheck unreadable {answer!r} | {snippet}')
        return
    reason = answer.split(' - ', 1)[-1]
    if level == current:
        remember(sid, reason=reason)
        log(f'steady {sid} {current} at {calls} steps ({secs:.1f}s) {answer} | {snippet}')
        return
    if by_hand(sid, snippet):  # picked during the step that's still running
        return
    status, text, rid = send(sid, level)
    if 200 <= status < 300:
        remember(sid, level=level, sent=level, sent_at=time.time(), sent_id=rid, seen_id=rid, reason=reason)
        up = current not in LEVELS or LEVELS.index(level) > LEVELS.index(current)
        log(f'{"raise " if up else "lower "} {sid} {current}->{level} at {calls} steps ({secs:.1f}s) {answer} | {snippet}')
    else:
        log(f'error  {sid} send {level} failed {status} {text[:120]} | {snippet}')


def main():
    if sys.argv[1:] == ['--models']:
        list_models()
        return
    if sys.argv[1:] == ['--track']:
        track()
        return
    if len(sys.argv) == 3 and sys.argv[1] == '--title':
        fetch_title(sys.argv[2])
        return
    if os.environ.get('EFFORT_JUDGE'):
        return
    data = json.load(sys.stdin)
    event = data.get('hook_event_name', 'UserPromptSubmit')
    if event == 'UserPromptSubmit' and peek().get('claude_window'):
        # "Claude window in Chrome" is on: tell Claude to use it, so no one has to add this to their instructions
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': BROWSER_RULE}}))
    sid = session_id()
    if not sid:
        if event == 'UserPromptSubmit':
            log(f'skip   {data.get("session_id", "")[:8]} not a Remote Control session')
        return
    tp = data.get('transcript_path')
    if tp and peek().get('sessions', {}).get(sid, {}).get('transcript') != tp:
        with state() as s:  # the tracker reads the last reply from here
            s['sessions'].setdefault(sid, {})['transcript'] = tp
    if event == 'PostToolUse':
        on_tool(data, sid)
    else:
        on_prompt(data, sid)


if __name__ == '__main__':
    main()
