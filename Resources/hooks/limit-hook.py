#!/usr/bin/python3
"""Claude Code hook: pause at the usage limit instead of spending usage credits.
Installed and kept up to date by the Sttark Claude Kit app.

When the 5-hour or weekly limit is reached and the account would go on with usage
credits, a session waits instead:

PreToolUse: before each tool call the hook checks the limit (one usage read a
minute or less, shared by every session through a cache file). At the limit it
denies the tool call with a reason that tells Claude to say one line about the
limit and run `claude-limit-wait <session id>` in the foreground, then try the
step again. That command is a link in ~/.local/bin to this file, which the hook
makes. It shows as a running command, waits with no model calls until the limit
resets or credits are chosen, prints why it ended, and the session goes on. After
9 minutes it prints WAIT AGAIN and Claude runs it again, so it stays under the
Bash tool's 10-minute limit.

UserPromptSubmit: a message sent at the limit goes through with the same
instruction, so nothing typed is lost. A message of just "use credits" lets that
session use usage credits until the limit resets, and Claude goes on with the
task. While the wait command runs, it watches the session's transcript and events
for a queued "use credits" and ends at once when it finds one.

Credits are used only when the person chooses them: "Use credits at the usage
limit" in the app's menu (every session), "Use credits" on a waiting session's
row in the menu (that session), or "use credits" typed in the session.

Accounts without usage credits, or at their spend limit, are left to Claude Code,
which stops at the limit by itself.

The other Kit hooks call held() before their own side calls to Claude, so they
spend nothing at the limit either.

Every pause, resume and choice is logged to ~/Library/Logs/sttark-claude-kit.log.
"""
import atexit, datetime, glob, fcntl, json, os, re, signal, subprocess, sys, time, urllib.error, urllib.request
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
        if (l.get('percent') or 0) < 100:   # is_active marks the window that applies now, not a reached limit
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


CHUNK = int(os.environ.get('STTARK_LIMIT_CHUNK') or 540)   # the longest one wait command runs, under the Bash tool's 10-minute limit
WAIT = os.path.expanduser('~/.local/bin/claude-limit-wait')


def wait_cmd(sid):
    """The command Claude runs to wait, as Claude should type it."""
    if not os.environ.get('STTARK_KIT_DIR'):
        try:   # a short name, so the wait reads clearly in the Claude app
            if os.path.realpath(WAIT) != os.path.realpath(__file__):
                if os.path.lexists(WAIT):
                    os.remove(WAIT)
                os.symlink(os.path.realpath(__file__), WAIT)
            return f'claude-limit-wait {sid}'
        except OSError:
            pass
    return f'python3 "{os.path.realpath(__file__)}" wait {sid}'


def line(until):
    return f'Usage limit reached. I continue at {clock(until)}. Type use credits to continue now on credits.'


def say(sid, name, until):
    """What Claude is told at the limit: one line to the person, then the wait command, in the foreground."""
    return (f'Sttark Claude Kit: the {name} usage limit is reached; it resets at {clock(until)}. '
            'Usage credits are spent only if the person chooses them. Do this, and nothing else first: '
            f'1) say exactly this one line: "{line(until)}" '
            f'2) run this Bash command in the foreground with timeout 600000: {wait_cmd(sid)} '
            '3) when it prints "WAIT AGAIN", run the same command again, with no other words. '
            'When it prints "GO ON", go on with the task (retry the step that was stopped, if any). '
            'Keep every reply until then to that one line or less.')


def transcript_of(sid):
    for tp in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{sid}.jsonl')):
        return tp
    return None


def wait_main(sid):
    """claude-limit-wait <session id>: wait in the open until the limit resets or the person chooses credits.
    Ends after CHUNK seconds so the Bash tool never times out; Claude then runs it again."""
    c, tp = cse(), transcript_of(sid)
    pos = size(tp)
    w = wall(usage(), tp)
    if not w or credits(sid):
        print('GO ON: ' + ('usage credits were chosen.' if w else 'the usage limit is clear.'))
        return
    name, until = w
    with state() as s:
        s.setdefault('limit_pauses', {})[sid] = {'since': time.time(), 'until': until, 'limit': name, 'cse': c,
                                                'title': title(s, c, os.getcwd()), 'pid': os.getpid(),
                                                'what': 'wait'}
    atexit.register(drop, sid)

    def stopped(*_):
        log(f'end    {sid[:8]} wait ended: the turn was stopped')
        sys.exit(0)
    for g in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(g, stopped)
    print(f'Waiting for the {name} usage limit to reset at {clock(until)}. '
          'Type "use credits" to continue now on credits.', flush=True)
    log(f'wait   {sid[:8]} at the {name} limit until {clock(until)}')
    started = asked = time.time()
    while time.time() - started < CHUNK:
        time.sleep(TICK)
        found, pos = queued_credits(tp, pos)
        if not found and time.time() - asked >= TICK * 3:   # the server every 30 s
            asked = time.time()
            found = typed_credits(c, int(started * 1000))
        if found:
            with state() as s:
                s.setdefault('limit_credits', {})[sid] = until
            log(f'credits {sid[:8]} "use credits" typed during the wait, until {clock(until)}')
            print(f'GO ON: "use credits" was typed. This session uses usage credits until {clock(until)}.')
            return
        if credits(sid):
            log(f'credits {sid[:8]} chosen in the menu')
            print(f'GO ON: usage credits were chosen in the Kit menu, until {clock(until)}.')
            return
        w = wall(usage(max_age=TICK) if time.time() >= until else usage(), tp)
        if not w:
            log(f'resume {sid[:8]} the {name} limit reset, after {int((time.time() - started) / 60)} min')
            print(f'GO ON: the {name} usage limit reset.')
            return
        name, until = w
    print(f'WAIT AGAIN: still at the {name} usage limit until {clock(until)}.')


def is_wait(cmd):
    return bool(re.search(r'(claude-limit-wait|limit-hook\.py"? wait)\b', cmd or ''))


def on_tool(data):
    sid = data.get('session_id', '')
    if data.get('tool_name') == 'Bash' and is_wait((data.get('tool_input') or {}).get('command')):
        return   # the wait itself always runs
    w = wall(usage(), data.get('transcript_path'))
    if not w or credits(sid):
        return
    log(f'stop   {sid[:8]} {data.get("tool_name")} at the {w[0]} limit until {clock(w[1])}')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                             'permissionDecisionReason': say(sid, *w)}}))


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
    log(f'message {sid[:8]} at the {w[0]} limit until {clock(w[1])}: Claude says so and waits')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext':
                      say(sid, *w) + ' After "GO ON", answer the message the person just sent.'}}))


def main():
    if (len(sys.argv) >= 3 and sys.argv[1] == 'wait') or os.path.basename(sys.argv[0]) == 'claude-limit-wait':
        return wait_main(sys.argv[-1])
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
