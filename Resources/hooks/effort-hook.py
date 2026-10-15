#!/usr/bin/python3
"""Claude Code hook: set each Remote Control session's effort to what the task
needs. Installed and kept up to date by the Sttark Effort app.

UserPromptSubmit: the prompt and the last few messages go to a quick side call
(claude -p, Haiku), which picks low, medium, high, xhigh or max. If that
differs from the session's level, set-session-effort.py sends the change the
same way the Claude app's effort picker does, so the first step of the turn
already runs at the new level.

PostToolUse (in the background): at 10, 25 and 50 tool calls into a turn the
side call sees the request and the work so far, and raises or lowers the level
to match how the work is actually going.

Hands off when the app's "Auto effort" is off, when a session is set to Manual
in the app, or when the person changes a session's effort themselves (the hook
sees a level it didn't send and sets that session to Manual).

Only sessions with a claude.ai session id (Remote Control) can be changed.
Every decision is logged to ~/Library/Logs/claude-effort-hook.log.
"""
import fcntl, importlib.util, json, os, re, subprocess, sys, time
from contextlib import contextmanager

LOG = os.path.expanduser('~/Library/Logs/claude-effort-hook.log')
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser('~/Library/Application Support/SttarkEffort/state.json')
CLAUDE = os.path.expanduser('~/.local/bin/claude')
MODEL = 'haiku'
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

Levels: low (trivial), medium (routine), high (multi-step work with judgment), \
xhigh (hard or open-ended: unknown causes, building something end to end, \
costly mistakes), max (the agent is already at xhigh and still stuck: \
repeated failures, going in circles, or no progress toward the goal).

If torn between two levels, pick the higher one. Answer on one line: the \
level, then " - " and a reason of under 12 words."""


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
        t = text_of((e.get('message') or {}).get('content')).strip()
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


def judge(ask, system=RULES):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID',
                                'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    r = subprocess.run(
        [CLAUDE, '-p', '--model', MODEL, '--effort', 'low',
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
            t = text_of((e.get('message') or {}).get('content')).strip()
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
    try:
        return sse().send(sid, level)
    except Exception as e:
        return 0, repr(e)


def fetch_title(sid):
    """The session's name in the Claude app, for the app's menu."""
    try:
        d = sse().session(sid)
    except Exception:
        return
    with state() as s:
        x = s['sessions'].setdefault(sid, {})
        x['title'] = d.get('title') or x.get('title') or ''
        x['url'] = d.get('session_url') or x.get('url', '')
        x['title_at'] = time.time()


def title_later(sid, x):
    if time.time() - x.get('title_at', 0) > 600:
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
    title_later(sid, x)
    if st.get('paused') or x.get('manual'):
        remember(sid)
        log(f'{"paused" if st.get("paused") else "manual"} {sid} left at {x.get("level", "?")} | {snippet}')
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
    status, text = send(sid, level)
    if 200 <= status < 300:
        remember(sid, level=level, sent=level, sent_at=time.time(), reason=reason)
        time.sleep(1.5)  # let the change reach the session before the turn starts
        log(f'change {sid} {current}->{level} ({secs:.1f}s) {answer} | {snippet}')
    else:
        log(f'error  {sid} send {level} failed {status} {text[:120]} | {snippet}')


def on_tool(data, sid):
    if data.get('agent_id'):  # a subagent's own steps
        return
    level_now = (data.get('effort') or {}).get('level', '')
    with state() as s:
        x = s['sessions'].setdefault(sid, {})
        x['at'] = time.time()
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
    status, text = send(sid, level)
    if 200 <= status < 300:
        remember(sid, level=level, sent=level, sent_at=time.time(), reason=reason)
        up = current not in LEVELS or LEVELS.index(level) > LEVELS.index(current)
        log(f'{"raise " if up else "lower "} {sid} {current}->{level} at {calls} steps ({secs:.1f}s) {answer} | {snippet}')
    else:
        log(f'error  {sid} send {level} failed {status} {text[:120]} | {snippet}')


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--title':
        fetch_title(sys.argv[2])
        return
    if os.environ.get('EFFORT_JUDGE'):
        return
    data = json.load(sys.stdin)
    sid = session_id()
    event = data.get('hook_event_name', 'UserPromptSubmit')
    if not sid:
        if event == 'UserPromptSubmit':
            log(f'skip   {data.get("session_id", "")[:8]} not a Remote Control session')
        return
    if event == 'PostToolUse':
        on_tool(data, sid)
    else:
        on_prompt(data, sid)


if __name__ == '__main__':
    main()
