#!/usr/bin/python3
"""Claude Code hook: pause at the usage limit instead of spending usage credits.
Installed and kept up to date by the Sttark Claude Kit app.

When the 5-hour or weekly limit is reached and the account would go on with usage
credits, a session waits instead:

PreToolUse: before each tool call the hook checks the limit (one usage read a
minute or less, shared by every session through a cache file). At the limit it
waits, with no model calls, until the limit resets, then lets the tool run and
the session goes on with its task by itself.

UserPromptSubmit: a message sent at the limit is stopped with the reset time and
how to use credits. A message of just "use credits" lets that session use usage
credits until the limit resets, and Claude goes on with the task.

Credits are used only when the person chooses them: "Use credits at the usage
limit" in the app's menu (every session), "Use credits" on a waiting session's
row in the menu (that session), or "use credits" typed in the session.

Accounts without usage credits, or at their spend limit, are left to Claude Code,
which stops at the limit by itself.

The other Kit hooks call held() before their own side calls to Claude, so they
spend nothing at the limit either.

Every pause, resume and choice is logged to ~/Library/Logs/sttark-claude-kit.log.
"""
import atexit, datetime, fcntl, json, os, re, signal, subprocess, sys, time, urllib.error, urllib.request
from contextlib import contextmanager

# STTARK_KIT_DIR and STTARK_LIMIT_TEST are for tests: a copy of the state folder, and a file that stands
# in for the usage read, so a test never touches the real state or the account.
DIR = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(DIR, 'state.json')
USAGE = os.path.join(DIR, 'usage.json')
TEST = os.environ.get('STTARK_LIMIT_TEST')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
URL = 'https://api.anthropic.com/api/oauth/usage'
FRESH = 60       # seconds a usage read is good for
FRESH_NEAR = 15  # ... when a limit is at 90% or more, so the pause starts soon after the limit
TICK = 10        # seconds between checks while a session waits
NAMES = {'session': '5-hour', 'weekly_all': 'weekly'}


def log(line):
    with open(LOG, 'a') as f:
        f.write(time.strftime('%F %T ') + 'limit  ' + line + '\n')


@contextmanager
def state():
    """The app's shared state file, under the same lock the app and the effort hook use."""
    os.makedirs(DIR, exist_ok=True)
    with open(STATE + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            s = json.load(open(STATE))
        except (OSError, ValueError):
            s = {}
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


def token():
    raw = subprocess.run(['security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w'],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(raw)['claudeAiOauth']['accessToken']


def fetch():
    if TEST:
        with open(TEST) as f:
            return json.load(f)
    r = urllib.request.Request(URL, headers={'Authorization': 'Bearer ' + token(),
                                             'anthropic-beta': 'oauth-2025-04-20',
                                             'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.load(resp)


def stamp(iso):
    try:
        return datetime.datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return 0


def fresh_for(u):
    near = any((l.get('percent') or 0) >= 90 for l in u.get('limits') or [])
    return FRESH_NEAR if near else FRESH


def usage(max_age=None):
    """The latest usage read, from the cache when it's no older than max_age (by default a minute, 15 seconds
    near a limit). One process reads at a time; the others use the cache. None when there's no read at all."""
    try:
        c = json.load(open(USAGE))
    except (OSError, ValueError):
        c = {}
    u = c.get('usage')
    if u and time.time() - c.get('at', 0) < (fresh_for(u) if max_age is None else max_age):
        return u
    os.makedirs(DIR, exist_ok=True)
    with open(USAGE + '.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return u   # another session is reading it now
        try:
            u = fetch()
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError, urllib.error.URLError) as e:
            if not c.get('error_logged'):
                log(f'usage read failed: {e}')
                c['error_logged'] = True
                c['at'] = time.time()   # don't retry on every tool call
                json.dump(c, open(USAGE, 'w'))
            return u
        tmp = USAGE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'at': time.time(), 'usage': u}, f)
        os.replace(tmp, USAGE)
        return u


def session_model(transcript):
    """The model this session ran on last, from the end of its transcript."""
    try:
        with open(transcript, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200000))
            found = re.findall(rb'"model":"(claude-[\w.-]+)"', f.read())
        return found[-1].decode() if found else ''
    except (OSError, TypeError):
        return ''


def wall(u, transcript=None):
    """(name, reset time) of the limit that would put this session on usage credits, or None.
    A model's own weekly limit counts only for a session on that model."""
    if not u:
        return None
    x = u.get('extra_usage') or {}
    if not x.get('is_enabled') or x.get('spend_limit_reached'):
        return None   # no credits would be spent: Claude Code stops at the limit by itself
    model = None
    hit = []
    for l in u.get('limits') or []:
        if not (l.get('is_active') or (l.get('percent') or 0) >= 100):
            continue
        scope = ((l.get('scope') or {}).get('model') or {}).get('display_name')
        if scope:
            if model is None:
                model = session_model(transcript) if transcript else ''
            if model and scope.lower() not in model.lower():
                continue
            name = f'{scope} weekly'
        else:
            name = NAMES.get(l.get('kind'), l.get('kind') or 'usage')
        hit.append((stamp(l.get('resets_at')), name))
    if not hit:
        return None
    at, name = max(hit)   # wait for the last one to reset
    return name, at


def clock(t):
    t = (int(t) + 30) // 60 * 60
    d = datetime.datetime.fromtimestamp(t)
    day = '' if d.date() == datetime.date.today() else d.strftime('%a ')
    return day + d.strftime('%I:%M %p').lstrip('0')


def credits(sid, s=None):
    """True when the person chose usage credits: for every session, or for this one until its reset."""
    s = s if s is not None else peek()
    if s.get('limit_credits_all'):
        return True
    return (s.get('limit_credits') or {}).get(sid, 0) > time.time()


def held(sid=None, transcript=None):
    """True when this session (or, with no session, the account) is at the limit and hasn't chosen credits.
    The other Kit hooks skip their side calls to Claude then."""
    try:
        w = wall(usage(), transcript)
        return bool(w) and not credits(sid)
    except Exception:
        return False


def cse():
    b = os.environ.get('CLAUDE_CODE_BRIDGE_SESSION_ID', '')
    if b:
        return 'cse_' + b.split('_', 1)[1] if b.startswith('session_') else b
    pid = os.environ.get('CLAUDE_PID', '')
    if pid:
        args = subprocess.run(['ps', '-ww', '-o', 'args=', '-p', pid], capture_output=True, text=True).stdout
        m = re.search(r'--session-id[= ](cse_\w+)', args)
        if m:
            return m.group(1)
    return ''


def title(s, c, cwd):
    t = ((s.get('sessions') or {}).get(c) or {}).get('title', '').strip() if c else ''
    return t or os.path.basename(cwd or '') or 'Session'


def drop(sid):
    with state() as s:
        p = s.get('limit_pauses') or {}
        if p.pop(sid, None) is not None:
            s['limit_pauses'] = p


def wait(data, sid, name, until):
    """Hold this tool call until the limit resets or the person chooses credits."""
    c, cwd, tp = cse(), data.get('cwd', ''), data.get('transcript_path')
    with state() as s:
        t = title(s, c, cwd)
        s.setdefault('limit_pauses', {})[sid] = {'since': time.time(), 'until': until, 'limit': name,
                                                'cse': c, 'title': t, 'pid': os.getpid()}
    atexit.register(drop, sid)

    def stopped(*_):   # the turn was stopped (from the app, or the session closed): the row goes
        log(f'end    {sid[:8]} pause ended: the turn was stopped')
        sys.exit(0)
    signal.signal(signal.SIGTERM, stopped)
    signal.signal(signal.SIGHUP, stopped)
    signal.signal(signal.SIGINT, stopped)
    log(f'pause  {sid[:8]} {t[:40]!r} at the {name} limit until {clock(until)}')
    started = time.time()
    while True:
        time.sleep(TICK)
        s = peek()
        if credits(sid, s):
            log(f'credits {sid[:8]} goes on with usage credits after {int((time.time() - started) / 60)} min')
            return
        if time.time() >= until:
            w = wall(usage(max_age=TICK), tp)   # just after the reset: read again soon, in case it lags
        else:
            w = wall(usage(), tp)   # a cache refresh every minute catches a limit that resets early
        if not w:
            log(f'resume {sid[:8]} the {name} limit reset, after {int((time.time() - started) / 60)} min')
            return
        if w[1] != until:
            name, until = w
            with state() as s:
                p = (s.get('limit_pauses') or {}).get(sid)
                if p:
                    p.update(until=until, limit=name)


def on_tool(data):
    sid = data.get('session_id', '')
    w = wall(usage(), data.get('transcript_path'))
    if not w or credits(sid):
        return
    wait(data, sid, *w)


def on_prompt(data):
    sid = data.get('session_id', '')
    asked = re.sub(r'[^a-z ]', '', (data.get('prompt') or '').lower()).strip()
    if asked == 'use credits':
        u = usage(max_age=0)
        w = wall(u, data.get('transcript_path'))
        until = w[1] if w else time.time() + 5 * 3600
        with state() as s:
            s.setdefault('limit_credits', {})[sid] = until
            s['limit_credits'] = {k: v for k, v in s['limit_credits'].items() if v > time.time()}
        log(f'credits {sid[:8]} "use credits" typed, until {clock(until)}')
        note = (f'until the {w[0]} limit resets at {clock(w[1])}' if w
                else 'if it reaches the usage limit in the next 5 hours')
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext':
            f'Sttark Claude Kit: the person typed "use credits". This session now goes on with usage credits {note}. '
            'Say so in one line, then go on with the task you were doing before the pause, if there was one.'}}))
        return
    w = wall(usage(), data.get('transcript_path'))
    if not w or credits(sid):
        return
    log(f'stop   {sid[:8]} message sent at the {w[0]} limit, until {clock(w[1])}')
    print(json.dumps({'decision': 'block', 'reason':
        f'Paused: your {w[0]} usage limit is reached, so this message was not sent and no usage credits were used. '
        f'The limit resets at {clock(w[1])}. Send it again after that, or send "use credits" to go on now with usage credits.'}))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    try:
        if data.get('hook_event_name') == 'PreToolUse':
            on_tool(data)
        elif data.get('hook_event_name') == 'UserPromptSubmit':
            on_prompt(data)
    except Exception as e:   # never stop a session because of this hook
        log(f'error  {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
