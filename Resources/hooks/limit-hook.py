#!/usr/bin/python3
"""Claude Code hook: pause at the usage limit instead of spending usage credits.
Installed and kept up to date by the Sttark Claude Kit app.

When the 5-hour or weekly limit is reached and the account would go on with usage
credits, a session waits instead:

PreToolUse: before each tool call the hook checks the limit (one usage read a
minute or less, shared by every session through a cache file). At the limit it
waits, with no model calls, until the limit resets, then lets the tool run and
the session goes on with its task by itself.

UserPromptSubmit: a message sent at the limit holds the same way, and goes to
Claude when the limit resets, so nothing typed is lost. A message of just "use
credits" lets that session use usage credits until the limit resets, and Claude
goes on with the task. Claude Code queues a message typed while a hold runs and
runs its hooks only after the hold ends, so a hold also watches the session's
transcript for a queued "use credits" and lets the session go on at once.

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
URL = os.environ.get('STTARK_LIMIT_URL') or 'https://api.anthropic.com/api/oauth/usage'   # tests: a stand-in server
FRESH = 60       # seconds a usage read is good for
FRESH_NEAR = 15  # ... when a limit is at 90% or more, so the pause starts soon after the limit
BACKOFF = 120    # seconds to wait after a failed usage read, doubling each time ...
BACKOFF_MAX = 900  # ... up to 15 minutes
TICK = 10        # seconds between checks while a session waits
SESSIONS = 'https://api.anthropic.com/v1/code/sessions/'
EVENTS = os.environ.get('STTARK_LIMIT_EVENTS')   # tests: a file that stands in for the session's server events
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
    r = urllib.request.Request(URL, headers={'Authorization': 'Bearer ' + ('test' if os.environ.get('STTARK_LIMIT_URL') else token()),
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
    near a limit). One process reads at a time; the others use the cache. After a failed read (a 429, say) no
    process reads again until the back-off ends (Retry-After, or 2 min doubling to 15 min), and every caller
    gets the last good read meanwhile. None when there's no read at all."""
    try:
        c = json.load(open(USAGE))
    except (OSError, ValueError):
        c = {}
    u = c.get('usage')
    if u and time.time() - c.get('at', 0) < (fresh_for(u) if max_age is None else max_age):
        return u
    if time.time() < c.get('retry_at', 0):
        return u   # backing off after a failed read: keep the last good one
    os.makedirs(DIR, exist_ok=True)
    with open(USAGE + '.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return u   # another session is reading it now
        try:   # read the cache again under the lock: another process may have just read or backed off
            c = json.load(open(USAGE))
        except (OSError, ValueError):
            pass
        u = c.get('usage')
        if time.time() < c.get('retry_at', 0) or (
                u and time.time() - c.get('at', 0) < (fresh_for(u) if max_age is None else max_age)):
            return u
        try:
            u = fetch()
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError, urllib.error.URLError) as e:
            fails = c.get('fails', 0) + 1
            after = 0
            if isinstance(e, urllib.error.HTTPError):
                try:
                    after = int(e.headers.get('Retry-After') or 0)
                except (TypeError, ValueError):
                    after = 0
            wait_s = max(after, min(BACKOFF * 2 ** (fails - 1), BACKOFF_MAX))
            c.update(fails=fails, retry_at=time.time() + wait_s)
            if fails == 1 or after:
                log(f'usage read failed: {e}; next read in {wait_s // 60 or 1} min, '
                    + ('using the last read' if u else 'no read yet'))
            put(c)
            return u
        put({'at': time.time(), 'usage': u})
        return u


def put(c):
    tmp = USAGE + f'.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        json.dump(c, f)
    os.replace(tmp, USAGE)


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
        if l.get('resets_at') and stamp(l.get('resets_at')) <= time.time():
            continue   # an old read: this limit has reset since
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


def asked_credits(text):
    return isinstance(text, str) and re.sub(r'[^a-z ]', '', text.lower()).strip() == 'use credits'


def queued_credits(tp, pos):
    """(found, new position): found is True when "use credits" was queued in the transcript after pos.
    Claude Code writes a queue-operation line the moment a message is typed, even while a hook holds the turn."""
    try:
        with open(tp, 'rb') as f:
            f.seek(pos)
            chunk = f.read()
    except (OSError, TypeError):
        return False, pos
    end = chunk.rfind(b'\n') + 1
    for line in chunk[:end].splitlines():
        if b'queue-operation' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get('operation') == 'enqueue' and asked_credits(d.get('content')):
            return True, pos + end
    return False, pos + end


MARK = '\u23f8 Paused'   # the start of a held session's name in the Claude app
TITLES = os.environ.get('STTARK_LIMIT_TITLES')   # tests: a file that stands in for session names on the server


def api(method, url, body=None):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                               headers={'Authorization': 'Bearer ' + token(), 'anthropic-version': '2023-06-01',
                                        'anthropic-beta': 'ccr-byoc-2025-07-29', 'x-organization-uuid': org(),
                                        'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.load(resp)


def name_of(c):
    """The session's name in the Claude app, or None when it can't be read."""
    try:
        if TITLES:
            return json.load(open(TITLES)).get(c, '')
        return api('GET', 'https://api.anthropic.com/v1/sessions/session_' + c.split('_', 1)[1]).get('title') or ''
    except Exception:
        return None


def rename_to(c, t):
    try:
        if TITLES:
            try:
                d = json.load(open(TITLES))
            except (OSError, ValueError):
                d = {}
            d[c] = t
            json.dump(d, open(TITLES, 'w'))
        else:
            api('PATCH', 'https://api.anthropic.com/v1/sessions/session_' + c.split('_', 1)[1], {'title': t})
        return True
    except Exception as e:
        log(f'rename failed: {e}')
        return False


def paused_name(base, until):
    return f'{MARK} until {clock(until)} \u00b7 type "use credits" to go on \u00b7 {base or "Session"}'


def base_name(t):
    """A name without the pause mark."""
    if t and t.startswith(MARK):
        return t.rsplit(' \u00b7 ', 1)[-1] if t.count(' \u00b7 ') >= 2 else ''
    return t or ''


def show_pause(c, until):
    """Put the pause in the session's name in the Claude app, where the person looks. Keeps the old name to
    put back. When the app or the naming hook changes the name during the hold, the mark goes back on."""
    if not c:
        return
    now = name_of(c)
    if now is None:
        return
    want = paused_name(base_name(now), until)
    if now != want:
        with state() as s:
            s.setdefault('limit_names', {})[c] = base_name(now)
        rename_to(c, want)


def clear_pause(c, sid):
    """Put the old name back once no other hold in this session is waiting."""
    if not c:
        return
    with state() as s:
        others = [k for k, p in (s.get('limit_pauses') or {}).items() if k != sid and p.get('cse') == c]
        if others:
            return
        base = (s.get('limit_names') or {}).pop(c, None)
    now = name_of(c)
    if now is not None and now.startswith(MARK):
        rename_to(c, base_name(now) or base or 'Session')


def org():
    with open(os.path.expanduser('~/.claude.json')) as f:
        return json.load(f)['oauthAccount']['organizationUuid']


def typed_credits(c, since_ms):
    """True when "use credits" was typed in the Claude app after since_ms. Read from the session's events on
    the server, which have every message the app sends, also before Claude Code writes its transcript (a new
    session whose first message waits). Newest events come first."""
    if not c:
        return False
    try:
        if EVENTS:
            with open(EVENTS) as f:
                data = json.load(f)
        else:
            r = urllib.request.Request(SESSIONS + c + '/events?limit=30', headers={
                'Authorization': 'Bearer ' + token(), 'anthropic-version': '2023-06-01',
                'anthropic-beta': 'ccr-byoc-2025-07-29', 'x-organization-uuid': org()})
            with urllib.request.urlopen(r, timeout=10) as resp:
                data = json.load(resp)
    except Exception:
        return False
    for e in data.get('data') or []:
        p = e.get('payload') or {}
        if e.get('source') != 'client' or e.get('event_type') != 'user':
            continue
        if (p.get('server_received_wall_ms') or 0) < since_ms:
            continue
        if asked_credits((p.get('message') or {}).get('content')):
            return True
    return False


def size(tp):
    try:
        return os.path.getsize(tp)
    except (OSError, TypeError):
        return 0


def wait(data, sid, name, until, what='step'):
    """Hold this tool call (or message) until the limit resets or the person chooses credits."""
    c, cwd, tp = cse(), data.get('cwd', ''), data.get('transcript_path')
    pos = size(tp)
    with state() as s:
        t = title(s, c, cwd)
        s.setdefault('limit_pauses', {})[sid] = {'since': time.time(), 'until': until, 'limit': name,
                                                'cse': c, 'title': t, 'pid': os.getpid(), 'what': what}
    atexit.register(drop, sid)
    atexit.register(clear_pause, c, sid)   # runs first (last in, first out): other holds still listed
    show_pause(c, until)

    def stopped(*_):   # the turn was stopped (from the app, or the session closed): the row goes
        log(f'end    {sid[:8]} pause ended: the turn was stopped')
        sys.exit(0)
    signal.signal(signal.SIGTERM, stopped)
    signal.signal(signal.SIGHUP, stopped)
    signal.signal(signal.SIGINT, stopped)
    log(f'pause  {sid[:8]} {t[:40]!r} {what} at the {name} limit until {clock(until)}')
    started = asked = time.time()
    while True:
        time.sleep(TICK)
        found, pos = queued_credits(tp, pos)
        if not found and time.time() - asked >= TICK * 3:   # the server every 30 s
            asked = time.time()
            found = typed_credits(c, int(started * 1000))
            if not found:
                show_pause(c, until)   # the app sets its own name a few seconds after a first message
        if found:
            with state() as s:
                s.setdefault('limit_credits', {})[sid] = until
            log(f'credits {sid[:8]} "use credits" typed during the hold, until {clock(until)}')
            return
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
            show_pause(c, until)


def on_tool(data):
    sid = data.get('session_id', '')
    w = wall(usage(), data.get('transcript_path'))
    if not w or credits(sid):
        return
    wait(data, sid, *w)


def on_prompt(data):
    sid = data.get('session_id', '')
    if asked_credits(data.get('prompt')):
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
    wait(data, sid, *w, what='message')   # the message goes to Claude when the hold ends; nothing is lost


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
