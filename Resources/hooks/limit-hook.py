#!/usr/bin/python3
"""Claude Code hook: pause at the usage limit instead of spending usage credits, and hold a session at a
usage percentage of its own. Installed and kept up to date by the Sttark Claude Kit app.

Each session has one of three settings (limit_modes in the app's state file):
- Follow the menu (the default): when the 5-hour or weekly limit is reached and the account would go on
  with usage credits, the session waits, unless "Use credits at the usage limit" is on in the menu.
- Always use credits: the session never waits at the limit.
- Never use credits; hold at N% (80 by default): the session waits when a limit reaches N%, whatever the
  menu says, and goes on when every limit is under N% again.
Set it on the session's row in the menu, by typing "no credits", "no credits 90", "credits ok" or
"follow the menu" as a message, or with `claude-limit-mode [<session>] follow | credits | hold [N]`.
It lasts for the life of the session: kept by the Remote Control id (cse_...), which a restart, a wake or
a reattach keeps, and by the session id.

PreToolUse: before each tool call the hook checks the limit (one usage read a minute or less, shared by
every session through a cache file). When the session must wait, it denies the tool call with a reason that
tells Claude to say one line and run `claude-limit-wait <session id>` in the foreground, then try the step
again. That command is a link in ~/.local/bin to this file. It shows as a running command, waits with no
model calls until the wait ends, prints why it ended (GO ON), and the session goes on. After 9 minutes it
prints WAIT AGAIN and Claude runs it again, so it stays under the Bash tool's 10-minute limit.

PreToolUse --hold (a second entry, with an 8-day limit): for a session that holds at its own N%, the hook
itself waits, so the whole hold makes no model calls, not even one every 9 minutes. For the session, it
waits before the wait command starts; when the hold ends the command runs and prints GO ON at once. For a
subagent or background agent (they come through the same hooks with the session's id and their own agent
id), it waits before the agent's next tool call, which then runs: an agent can't be counted on to run the
wait command it is told to. Every other call goes through at once.

UserPromptSubmit: a message sent while the session must wait goes through with the same instruction, so
nothing typed is lost. A message of just "use credits" lets that session use usage credits until the limit
resets. A message that is one of the setting phrases changes the session's setting. While a wait runs, it
watches the session's transcript and events for these phrases and acts on them at once.

The other Kit hooks call held() before their own side calls to Claude, so they spend nothing while the
session (or, with no session, the account) must wait.

Every hold, wait, resume and change is logged to ~/Library/Logs/sttark-claude-kit.log with the tag limit.
"""
import atexit, collections, datetime, glob, fcntl, json, os, re, signal, subprocess, sys, time, urllib.error, urllib.request
from contextlib import contextmanager

# STTARK_KIT_DIR and STTARK_LIMIT_TEST are for tests: a copy of the state folder, and a file that stands
# in for the usage read, so a test never touches the real state or the account. With STTARK_LIMIT_TEST the
# shared usage cache is never read or written, so a test session can't show its fake usage to real sessions.
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
TICK = float(os.environ.get('STTARK_LIMIT_TICK') or 10)   # seconds between checks while a session waits
SESSIONS = 'https://api.anthropic.com/v1/code/sessions/'
EVENTS = os.environ.get('STTARK_LIMIT_EVENTS')   # tests: a file that stands in for the session's server events
NAMES = {'session': '5-hour', 'weekly_all': 'weekly'}
DEFAULT_AT = 80  # "no credits" with no number: hold at 80%
HOLD_BUDGET = 8 * 24 * 3600 - 600   # the longest the --hold hook waits, under its 8-day limit in settings
KEEP_DAYS = 30   # a setting whose session hasn't been used for this long is dropped ...
KEEP_ARCHIVED_DAYS = 7   # ... or this long for an archived one (kept a while, in case it is unarchived)

# why a session waits now: the limit's name ("5-hour"), when it resets, its percent, the percent that holds
# (100 for the usage limit itself) and the session's setting ("follow" or "hold")
Hold = collections.namedtuple('Hold', 'name until percent at mode')


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
    gets the last good read meanwhile. None when there's no read at all. With STTARK_LIMIT_TEST: the stand-in
    file itself, with no cache."""
    if TEST:
        try:
            return fetch()
        except (OSError, ValueError):
            return None
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


def pct(p):
    """83 for 83.0, 83.5 for 83.5."""
    p = p or 0
    return int(p) if p == int(p) else round(p, 1)


def wall(u, transcript=None, at=100, credits_only=True, mode='follow'):
    """The Hold of a session whose limits stop it at `at` percent, or None. The limits that count: the 5-hour,
    the weekly, and a model's own weekly limit for a session on that model. When several are at `at` or more,
    the one that resets last (the session waits for all of them). credits_only: only when the account would go
    on with usage credits (the usage limit itself; without credits Claude Code stops by itself)."""
    if not u:
        return None
    if credits_only:
        x = u.get('extra_usage') or {}
        if not x.get('is_enabled') or x.get('spend_limit_reached'):
            return None   # no credits would be spent: Claude Code stops at the limit by itself
    model = None
    hit = []
    for l in u.get('limits') or []:
        p = l.get('percent') or 0
        if p < at:   # is_active marks the window that applies now, not a reached limit
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
        hit.append((stamp(l.get('resets_at')), name, p))
    if not hit:
        return None
    until, name, p = max(hit)   # wait for the last one to reset
    return Hold(name, until, pct(p), at, mode)


def clock(t):
    t = (int(t) + 30) // 60 * 60
    d = datetime.datetime.fromtimestamp(t)
    day = '' if d.date() == datetime.date.today() else d.strftime('%a ')
    return day + d.strftime('%I:%M %p').lstrip('0')


# ---- the per-session setting -------------------------------------------------------------------------------

def matches(k, v, sid, c):
    return bool((sid and (k == sid or v.get('sid') == sid)) or (c and (k == c or v.get('cse') == c)))


def find_mode(s, sid='', c=''):
    """The stored setting of this session (a dict), or None for Follow the menu. Matched by key, sid or cse;
    the newest wins."""
    best = None
    for k, v in (s.get('limit_modes') or {}).items():
        if isinstance(v, dict) and matches(k, v, sid, c):
            if best is None or v.get('set_at', 0) > best.get('set_at', 0):
                best = v
    return best


def mode_of(s, sid='', c=''):
    """('follow', None), ('credits', None) or ('hold', N)."""
    m = find_mode(s, sid, c)
    if not m or m.get('mode') not in ('credits', 'hold'):
        return 'follow', None
    if m['mode'] == 'hold':
        try:
            n = int(m.get('at') or DEFAULT_AT)
        except (TypeError, ValueError):
            n = DEFAULT_AT
        return 'hold', max(1, min(100, n))
    return 'credits', None


def describe(mode, n=None):
    if mode == 'credits':
        return 'always use credits'
    if mode == 'hold':
        return f'never use credits; hold at {n}%'
    return 'follow the menu'


def transcript_of(sid):
    if not sid:
        return None
    for tp in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{glob.escape(sid)}.jsonl')):
        return tp
    return None


def sid_of_transcript(tp):
    b = os.path.basename(tp or '')
    return b[:-6] if b.endswith('.jsonl') else ''


def cse_of(sid, s=None, here=True):
    """The Remote Control id (cse_...) of a session: from this process's environment when it runs in that
    session (here), else from the app's list of sessions and their transcripts."""
    if here:
        env_sid = os.environ.get('CLAUDE_CODE_SESSION_ID', '')
        if not sid or not env_sid or env_sid == sid:
            c = cse()
            if c:
                return c
    if not sid:
        return ''
    s = s if s is not None else peek()
    for k, x in (s.get('sessions') or {}).items():
        if isinstance(x, dict) and sid_of_transcript(x.get('transcript')) == sid:
            return k
    return ''


def sid_of_cse(c, s):
    x = (s.get('sessions') or {}).get(c) or {}
    return sid_of_transcript(x.get('transcript'))


def mtime(p):
    try:
        return os.path.getmtime(p)
    except (OSError, TypeError):
        return 0


def prune(s):
    """Inside the state lock: drop the settings of sessions not used for KEEP_DAYS (KEEP_ARCHIVED_DAYS when
    archived), and "use credits" choices whose reset has passed."""
    now = time.time()
    m = s.get('limit_modes') or {}
    sessions = s.get('sessions') or {}
    for k, v in list(m.items()):
        if not isinstance(v, dict):
            m.pop(k)
            continue
        c = v.get('cse') or (k if k.startswith('cse_') else '')
        x = sessions.get(c) or {}
        tp = x.get('transcript') or transcript_of(v.get('sid'))
        used = max(mtime(tp), v.get('set_at', 0), x.get('at', 0))
        days = KEEP_ARCHIVED_DAYS if (x.get('app') or {}).get('archived') else KEEP_DAYS
        if used < now - days * 86400:
            m.pop(k)
    if 'limit_modes' in s:
        s['limit_modes'] = m
    if 'limit_credits' in s:
        s['limit_credits'] = {k: v for k, v in (s.get('limit_credits') or {}).items() if v > now}


def set_mode(sid, c, mode, n=None, by='command', name=''):
    """Store a session's setting ('follow' removes it). Logs and returns True when it changed."""
    with state() as s:
        before = mode_of(s, sid, c)
        m = s.get('limit_modes') or {}
        for k in [k for k, v in m.items() if isinstance(v, dict) and matches(k, v, sid, c)]:
            m.pop(k)
        if mode in ('credits', 'hold'):
            e = {'mode': mode, 'by': by, 'set_at': time.time()}
            if mode == 'hold':
                e['at'] = max(1, min(100, int(n or DEFAULT_AT)))
            if sid:
                e['sid'] = sid
            if c:
                e['cse'] = c
            t = name or ((s.get('sessions') or {}).get(c) or {}).get('title', '')
            if t:
                e['title'] = t
            m[c or sid] = e
        s['limit_modes'] = m
        prune(s)
        after = mode_of(s, sid, c)
    if after != before:
        log(f'mode   {(sid or c)[:8]} {describe(*after)} ({by})')
        return True
    return False


def credits_until(s, sid):
    """When this session's own "use credits" ends (0 when it has none)."""
    lc = s.get('limit_credits') or {}
    return max([v for k, v in lc.items() if sid and (k == sid or k.startswith(sid + '/'))] or [0])


def cse_if(sid, s):
    """The session's cse, looked up only when some session has a setting of its own (it can take a `ps`)."""
    return cse_of(sid, s) if s.get('limit_modes') else ''


def reached(u, transcript, mode, n):
    """The limit this session's setting stops at, whatever credits were chosen: for the reset time of a
    "use credits"."""
    if mode == 'hold':
        return wall(u, transcript, at=n, credits_only=False, mode='hold')
    return wall(u, transcript)


def hold_for(sid, c, transcript, u, s=None, once=True):
    """The Hold this session must wait for now under its setting, or None. c None: look it up if needed.
    once=False leaves out a "use credits" chosen for this session alone."""
    s = s if s is not None else peek()
    if c is None:
        c = cse_if(sid, s)
    mode, n = mode_of(s, sid, c)
    if mode == 'credits':
        return None
    if once and credits_until(s, sid) > time.time():
        return None
    if mode == 'hold':
        return wall(u, transcript, at=n, credits_only=False, mode='hold')
    if s.get('limit_credits_all'):
        return None
    return wall(u, transcript)


def credits(sid, s=None):
    """True when the person chose usage credits: for every session, or for this one until its reset."""
    s = s if s is not None else peek()
    if s.get('limit_credits_all'):
        return True
    return credits_until(s, sid) > time.time()


def held(sid=None, transcript=None, c=None):
    """True when this session must wait now under its own setting; with no session, when the account is at
    the limit and no one chose credits for every session. The other Kit hooks skip their side calls to Claude
    then."""
    try:
        u = usage()
        if not sid:
            w = wall(u, transcript)
            return bool(w) and not peek().get('limit_credits_all')
        return bool(hold_for(sid, c, transcript, u))
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


def drop(key):
    with state() as s:
        p = s.get('limit_pauses') or {}
        if p.pop(key, None) is not None:
            s['limit_pauses'] = p


# ---- phrases typed in a session ----------------------------------------------------------------------------

PHRASE_HOLD = re.compile(r'(?:no credits|never use credits)(?: at)?(?: (\d{1,3}) ?%?)?')


def phrase(text):
    """The setting asked for when the whole message is one of the phrases: ('once', None) for "use credits",
    ('credits', None), ('follow', None) or ('hold', N). None for any other message."""
    if isinstance(text, list):
        text = ' '.join(b.get('text', '') for b in text if isinstance(b, dict) and b.get('type') == 'text')
    if not isinstance(text, str) or len(text) > 60:
        return None
    t = ' '.join(re.sub(r'[^a-z0-9% ]', ' ', text.lower()).split())
    if t == 'use credits':
        return 'once', None
    if t in ('credits ok', 'always use credits'):
        return 'credits', None
    if t == 'follow the menu':
        return 'follow', None
    m = PHRASE_HOLD.fullmatch(t)
    if m:
        n = int(m.group(1)) if m.group(1) else DEFAULT_AT
        if 1 <= n <= 100:
            return 'hold', n
    return None


def asked_credits(text):
    return phrase(text) == ('once', None)


def queued(tp, pos):
    """(phrase, stopped, new position): the newest setting phrase queued in the transcript after pos, and whether
    the turn was stopped there. Claude Code writes a queue-operation line the moment a message is typed, even
    while a command or a hook holds the turn."""
    try:
        with open(tp, 'rb') as f:
            f.seek(pos)
            chunk = f.read()
    except (OSError, TypeError):
        return None, False, pos
    end = chunk.rfind(b'\n') + 1
    found, stopped = None, False
    for ln in chunk[:end].splitlines():
        if b'Request interrupted by user' in ln:
            stopped = True
        if b'queue-operation' not in ln:
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get('operation') == 'enqueue':
            found = phrase(d.get('content')) or found
    return found, stopped, pos + end


def queued_credits(tp, pos):
    """(found, new position): found is True when "use credits" was queued in the transcript after pos."""
    p, _, pos = queued(tp, pos)
    return p == ('once', None), pos


def org():
    with open(os.path.expanduser('~/.claude.json')) as f:
        return json.load(f)['oauthAccount']['organizationUuid']


def typed(c, since_ms):
    """The newest setting phrase typed in the Claude app after since_ms, or None. Read from the session's events
    on the server, which have every message the app sends, also before Claude Code writes its transcript (a new
    session whose first message waits). Newest events come first."""
    if not c:
        return None
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
        return None
    for e in data.get('data') or []:
        p = e.get('payload') or {}
        if e.get('source') != 'client' or e.get('event_type') != 'user':
            continue
        if (p.get('server_received_wall_ms') or 0) < since_ms:
            continue
        found = phrase((p.get('message') or {}).get('content'))
        if found:
            return found
    return None


def typed_credits(c, since_ms):
    return typed(c, since_ms) == ('once', None)


def apply(p, sid, c, tp, by, cwd=None):
    """Act on a phrase: "use credits" for this session until the limit resets, or a new setting."""
    kind, n = p
    if kind == 'once':
        h = reached(usage(max_age=0), tp, *mode_of(peek(), sid, c))
        until = h.until if h else time.time() + 5 * 3600
        with state() as s:
            s.setdefault('limit_credits', {})[sid] = until
            s['limit_credits'] = {k: v for k, v in s['limit_credits'].items() if v > time.time()}
        log(f'credits {sid[:8]} "use credits" typed, until {clock(until)}')
        return
    s = peek()
    set_mode(sid, c, kind, n, by, title(s, c, cwd or os.getcwd()))


# ---- what Claude is told -------------------------------------------------------------------------------------

def size(tp):
    try:
        return os.path.getsize(tp)
    except (OSError, TypeError):
        return 0


CHUNK = int(os.environ.get('STTARK_LIMIT_CHUNK') or 540)   # the longest one wait command runs, under the Bash tool's 10-minute limit
BIN = os.path.expanduser('~/.local/bin')
WAIT = os.path.join(BIN, 'claude-limit-wait')
MODE = os.path.join(BIN, 'claude-limit-mode')


def link(path, target=None):
    """Point a command in ~/.local/bin at this file (or target). True when it does."""
    target = os.path.realpath(target or __file__)
    try:
        if os.path.realpath(path) != target:
            if os.path.lexists(path):
                os.remove(path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            os.symlink(target, path)
        return True
    except OSError:
        return False


def wait_cmd(sid, agent=''):
    """The command Claude runs to wait, as Claude should type it. An agent's wait carries its agent id, so each
    agent's wait has its own row."""
    key = sid + ('/' + agent if agent else '')
    if not os.environ.get('STTARK_KIT_DIR') and link(WAIT):   # a short name, so the wait reads clearly in the Claude app
        return f'claude-limit-wait {key}'
    return f'python3 "{os.path.realpath(__file__)}" wait {key}'


def line(h):
    if h.mode == 'hold':
        return f'This session holds at {h.at}% usage. I continue at {clock(h.until)}. Type use credits to continue now.'
    return f'Usage limit reached. I continue at {clock(h.until)}. Type use credits to continue now on credits.'


def say(sid, h, agent=''):
    """What Claude is told when the session must wait: one line to the person, then the wait command, in the
    foreground."""
    if h.mode == 'hold':
        head = (f'Sttark Claude Kit: this session is set to never use usage credits and to hold when a usage limit '
                f'reaches {h.at}%. The {h.name} limit is at {h.percent}%; it resets at {clock(h.until)}. ')
    else:
        head = (f'Sttark Claude Kit: the {h.name} usage limit is reached; it resets at {clock(h.until)}. '
                'Usage credits are spent only if the person chooses them. ')
    return (head + 'Do this, and nothing else first: '
            f'1) say exactly this one line: "{line(h)}" '
            f'2) run this Bash command in the foreground with timeout 600000: {wait_cmd(sid, agent)} '
            '3) when it prints "WAIT AGAIN", run the same command again, with no other words. '
            'When it prints "GO ON", go on with the task (retry the step that was stopped, if any). '
            'Keep every reply until then to that one line or less.')


def where(h):
    if h.mode == 'hold':
        return f'at {h.at}%: the {h.name} limit is at {h.percent}%, until {clock(h.until)}'
    return f'at the {h.name} limit until {clock(h.until)}'


def why_go(sid, c, s, h=None):
    """Why a session no longer waits (for GO ON), from the state and the hold it waited for, if any."""
    mode, n = mode_of(s, sid, c)
    cu = credits_until(s, sid)
    if mode == 'credits':
        return 'this session is set to always use usage credits.'
    if cu > time.time():
        return f'usage credits were chosen for this session, until {clock(cu)}.'
    if mode == 'follow' and s.get('limit_credits_all') and (h is None or h.mode == 'follow'):
        return 'usage credits were chosen in the Kit menu for every session.'
    if mode == 'hold':
        if h is not None and h.mode == 'hold' and h.at != n:
            return f'this session now holds at {n}%, and every usage limit is under it.'
        return f'every usage limit is under {n}%.'
    if h is not None and h.mode == 'hold':
        return 'this session now follows the menu, and the usage limit is clear.'
    if h is not None:
        return f'the {h.name} usage limit reset.'
    return 'the usage limit is clear.'


# ---- the wait ------------------------------------------------------------------------------------------------

def hold_loop(sid, agent, tp, c, h, budget, what):
    """Wait while this session must wait, with no model calls: until the hold ends (returns why, for GO ON),
    until `budget` seconds pass (returns None), or until the turn or the process stops (exits).
    Shows as a row in the menu (limit_pauses) while it waits."""
    key = sid + ('/' + agent if agent else '')
    pos = size(tp)
    start_mode = mode_of(peek(), sid, c)
    with state() as s:
        row = {'since': time.time(), 'until': h.until, 'limit': h.name, 'cse': c, 'title': title(s, c, os.getcwd()),
               'pid': os.getpid(), 'what': what, 'sid': sid, 'mode': h.mode, 'at': h.at, 'percent': h.percent}
        if agent:
            row['agent'] = agent
        s.setdefault('limit_pauses', {})[key] = row
    atexit.register(drop, key)
    who = sid[:8] + ('/' + agent[:8] if agent else '')

    def stopped(*_):
        log(f'end    {who} {what} ended: the turn was stopped')
        sys.exit(0)
    for g in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(g, stopped)
    log(f'wait   {who} {where(h)}' + (', with no model calls until it ends' if what == 'hold' else ''))
    started = asked = time.time()
    since_ms = int(started * 1000)
    parent = os.getppid()
    while time.time() - started < budget:
        time.sleep(TICK)
        if os.getppid() != parent:
            log(f'end    {who} {what} ended: the session closed')
            sys.exit(0)
        found, cut, pos = queued(tp, pos)
        if cut and not agent:
            stopped()
        if not found and time.time() - asked >= TICK * 3:   # the server every 30 s
            asked = time.time()
            found = typed(c, since_ms)
        if found:
            since_ms = int(time.time() * 1000)   # the server check skips what the transcript already showed
            apply(found, sid, c, tp, 'typed')
        s = peek()
        u = usage(max_age=TICK) if time.time() >= h.until else usage()
        now = hold_for(sid, c, tp, u, s)
        if not now:
            why = why_go(sid, c, s, h)
            mins = int((time.time() - started) / 60)
            if mode_of(s, sid, c) == start_mode and credits_until(s, sid) <= time.time() and not (
                    h.mode == 'follow' and s.get('limit_credits_all')):
                log(f'resume {who} the {h.name} limit ' + (f'is under {h.at}%' if h.mode == 'hold' else 'reset')
                    + f', after {mins} min')
            else:
                log(f'resume {who} {why.rstrip(".")}, after {mins} min')
            return why
        if (now.name, now.until, now.at, now.mode) != (h.name, h.until, h.at, h.mode):
            with state() as s:
                r = (s.get('limit_pauses') or {}).get(key)
                if r is not None:
                    r.update(until=now.until, limit=now.name, mode=now.mode, at=now.at, percent=now.percent)
        h = now
    return None


def waiting_line(h):
    if h.mode == 'hold':
        return (f'Holding at {h.at}%: the {h.name} limit is at {h.percent}%. It goes on at {clock(h.until)}, when '
                'the limit resets. Type "use credits" to continue now.')
    return (f'Waiting for the {h.name} usage limit to reset at {clock(h.until)}. '
            'Type "use credits" to continue now on credits.')


def wait_main(key):
    """claude-limit-wait <session id>[/<agent id>]: wait in the open until the session may go on.
    Ends after CHUNK seconds so the Bash tool never times out; Claude then runs it again."""
    sid, _, agent = key.partition('/')
    s = peek()
    c, tp = cse_of(sid, s), transcript_of(sid)
    h = hold_for(sid, c, tp, usage(), s)
    if not h:
        print('GO ON: ' + why_go(sid, c, s))
        return
    print(waiting_line(h), flush=True)
    why = hold_loop(sid, agent, tp, c, h, CHUNK, 'wait')
    if why:
        print('GO ON: ' + why)
        return
    h = hold_for(sid, c, tp, usage()) or h
    if h.mode == 'hold':
        print(f'WAIT AGAIN: still holding at {h.at}% until {clock(h.until)}.')
    else:
        print(f'WAIT AGAIN: still at the {h.name} usage limit until {clock(h.until)}.')


def is_wait(cmd):
    return bool(re.search(r'(claude-limit-wait|limit-hook\.py"? wait)\b', cmd or ''))


# ---- the hooks -----------------------------------------------------------------------------------------------

def on_tool(data):
    sid = data.get('session_id', '')
    if data.get('tool_name') == 'Bash' and is_wait((data.get('tool_input') or {}).get('command')):
        return   # the wait itself always runs
    tp = data.get('transcript_path')
    s = peek()
    h = hold_for(sid, cse_if(sid, s), tp, usage(), s)
    if not h:
        return
    agent = data.get('agent_id') or ''
    if agent and h.mode == 'hold':
        return   # the --hold entry holds an agent's tool call itself
    who = sid[:8] + ('/' + agent[:8] if agent else '')
    if h.mode == 'hold':
        log(f'hold   {who} {where(h)} ({data.get("tool_name")})')
    else:
        log(f'stop   {who} {data.get("tool_name")} {where(h)}')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                             'permissionDecisionReason': say(sid, h, agent)}}))


def on_hold(data):
    """--hold, before every tool call, for a session that holds at its own N%: wait here, so the hold makes no
    model calls at all. For the session itself, only its wait command (Claude has said the hold line and runs
    it; when the hold ends the command runs and prints GO ON at once). For a subagent or background agent,
    the tool call itself: an agent may not follow the instruction to run the wait, so it is held before its
    next step and goes on with that step when the hold ends. Prints nothing; anything else exits at once."""
    agent = data.get('agent_id') or ''
    tool = data.get('tool_name')
    waits = tool == 'Bash' and is_wait((data.get('tool_input') or {}).get('command'))
    if not waits and not agent:
        return
    sid = data.get('session_id', '')
    tp = data.get('transcript_path')
    s = peek()
    c = cse_if(sid, s)
    if mode_of(s, sid, c)[0] != 'hold':
        return   # a follow-the-menu wait runs in the command, as before
    h = hold_for(sid, c, tp, usage(), s)
    if not h:
        return
    if not waits:
        log(f'hold   {sid[:8]}/{agent[:8]} {where(h)} ({tool})')
    hold_loop(sid, agent, tp, c, h, HOLD_BUDGET, 'hold')


def on_prompt(data):
    sid = data.get('session_id', '')
    tp = data.get('transcript_path')
    prompt = data.get('prompt')
    s = peek()
    p = phrase(prompt)
    c = cse_of(sid, s) if p else cse_if(sid, s)
    if p == ('once', None):
        apply(p, sid, c, tp, 'typed', data.get('cwd'))
        s = peek()
        h = reached(usage(), tp, *mode_of(s, sid, c))
        note = (f'until the {h.name} limit resets at {clock(h.until)}' if h
                else 'if it would wait in the next 5 hours')
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext':
            f'Sttark Claude Kit: the person typed "use credits". This session now goes on with usage credits {note}. '
            'Say so in one line, then go on with the task you were doing before the pause, if there was one.'}}))
        return
    if p:
        apply(p, sid, c, tp, 'typed', data.get('cwd'))
        s = peek()
        head = (f'Sttark Claude Kit: the person typed "{prompt.strip()}". This session is now set to: '
                f'{describe(*mode_of(s, sid, c))}. ')
        h = hold_for(sid, c, tp, usage(), s)
        if h:
            log(f'message {sid[:8]} {where(h)}: Claude says so and waits')
            ctx = head + 'Say so in one line. Then: ' + say(sid, h) + \
                ' After "GO ON", go on with the task you were doing before, if there was one.'
        else:
            ctx = head + 'Say so in one line, then go on with the task you were doing before, if there was one.'
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}}))
        return
    h = hold_for(sid, c, tp, usage(), s)
    if not h:
        return
    log(f'message {sid[:8]} {where(h)}: Claude says so and waits')
    after = (' After "GO ON", handle that notification.'
             if isinstance(prompt, str) and prompt.startswith('<task-notification>')
             else ' After "GO ON", answer the message the person just sent.')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext':
                      say(sid, h) + after}}))


# ---- claude-limit-mode -----------------------------------------------------------------------------------------

USAGE_TEXT = """usage: claude-limit-mode [<session>] [follow | credits | hold [N]]
       claude-limit-mode --list

Sets what a Claude Code session does at the usage limit (Sttark Claude Kit):
  follow      follow the menu's "Use credits at the usage limit" (the default)
  credits     always use credits at the usage limit
  hold [N]    never use credits; hold when a 5-hour or weekly limit reaches N% (80 if left out)
With no setting, prints the session's setting. <session>: left out or "." for this session, a session id,
a cse_ or session_ id, a unique start of one (6 or more characters), or a session's name."""


class Bad(Exception):
    pass


UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def resolve(who, s):
    """(sid, cse) of the session a person or a script named."""
    if who in ('.', 'this', ''):
        sid = os.environ.get('CLAUDE_CODE_SESSION_ID', '')
        c = cse()
        if not sid and not c:
            raise Bad('not inside a Claude Code session: give the session id or name')
        return sid or sid_of_cse(c, s), c or cse_of(sid, s, here=False)
    if who.startswith('session_'):
        who = 'cse_' + who[len('session_'):]
    sessions = s.get('sessions') or {}
    found = {}   # (sid, cse) pairs, keyed by the cse when there is one, else the sid

    def add(sid, c):
        sid = sid or (sid_of_cse(c, s) if c else '')
        c = c or (cse_of(sid, s, here=False) if sid else '')
        if sid or c:
            found[c or sid] = (sid, c)
    if who.startswith('cse_') and who in sessions:
        add('', who)
    elif UUID.fullmatch(who):
        add(who, '')
    elif who.startswith('cse_') and len(who) > 20:
        add('', who)   # a full cse id the app hasn't listed
    else:
        if len(who) >= 6:
            for k, x in sessions.items():
                t = sid_of_transcript((x or {}).get('transcript')) if isinstance(x, dict) else ''
                if k.startswith(who) or (t and t.startswith(who)):
                    add(t, k)
            for k, v in (s.get('limit_modes') or {}).items():
                if isinstance(v, dict) and any(i and i.startswith(who) for i in (k, v.get('sid'), v.get('cse'))):
                    add(v.get('sid') or (k if UUID.fullmatch(k) else ''),
                        v.get('cse') or (k if k.startswith('cse_') else ''))
            for v in (s.get('limit_pauses') or {}).values():
                if isinstance(v, dict) and (v.get('sid') or '').startswith(who):
                    add(v['sid'], v.get('cse') or '')
            if re.fullmatch(r'[0-9a-f-]{6,36}', who):
                for tp in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{glob.escape(who)}*.jsonl')):
                    add(sid_of_transcript(tp), '')
        if not found:
            for k, x in sessions.items():
                if isinstance(x, dict) and (x.get('title') or '').strip().lower() == who.strip().lower() \
                        and not (x.get('app') or {}).get('archived'):
                    add('', k)
    if not found:
        raise Bad(f'no session matches "{who}"')
    if len(found) > 1:
        raise Bad(f'"{who}" matches {len(found)} sessions: give more of the id')
    return list(found.values())[0]


def name_of(s, sid, c):
    m = find_mode(s, sid, c) or {}
    return (((s.get('sessions') or {}).get(c) or {}).get('title') or m.get('title') or 'Session').strip()


def mode_main(args):
    """claude-limit-mode: read or change a session's setting. Returns the exit code."""
    if args and args[0] in ('-h', '--help', 'help'):
        print(USAGE_TEXT)
        return 0
    s = peek()
    if args[:1] == ['--list']:
        rows = sorted(((v.get('set_at', 0), k, v) for k, v in (s.get('limit_modes') or {}).items()
                       if isinstance(v, dict)), key=lambda r: r[0])
        if not rows:
            print('No session has its own setting: every session follows the menu.')
        for at, k, v in rows:
            mode, n = mode_of({'limit_modes': {k: v}}, v.get('sid', ''), v.get('cse', '') or k)
            when = datetime.datetime.fromtimestamp(at).strftime('%b %d %I:%M %p')
            print(f'{name_of(s, v.get("sid", ""), v.get("cse", ""))} ({(v.get("sid") or k)[:8]}): '
                  f'{describe(mode, n)} (set by {v.get("by", "?")}, {when})')
        return 0
    settings = ('follow', 'credits', 'hold')
    if args and args[0].lower() in settings:
        who, rest = '.', args
    elif args:
        who, rest = args[0], args[1:]
    else:
        who, rest = '.', []
    try:
        sid, c = resolve(who, s)
        what, n = None, None
        if rest:
            what = rest[0].lower()
            if what not in settings:
                raise Bad(f'unknown setting "{rest[0]}": use follow, credits or hold [N]')
            if what == 'hold':
                if len(rest) > 2:
                    raise Bad('hold takes one number')
                try:
                    n = int(rest[1].rstrip('%')) if len(rest) == 2 else DEFAULT_AT
                except ValueError:
                    raise Bad(f'"{rest[1]}" is not a percentage')
                if not 1 <= n <= 100:
                    raise Bad('the percentage must be 1 to 100')
            elif len(rest) > 1:
                raise Bad(f'{what} takes no number')
    except Bad as e:
        print(f'claude-limit-mode: {e}', file=sys.stderr)
        return 2
    if what:
        name = name_of(s, sid, c)
        set_mode(sid, c, what, n, 'command', '' if name == 'Session' else name)
        s = peek()
    print(f'{name_of(s, sid, c)} ({(sid or c)[:8]}): {describe(*mode_of(s, sid, c))}')
    return 0


def main():
    name = os.path.basename(sys.argv[0])
    if name == 'claude-limit-mode':
        sys.exit(mode_main(sys.argv[1:]))
    if len(sys.argv) >= 2 and sys.argv[1] == 'mode':
        sys.exit(mode_main(sys.argv[2:]))
    if (len(sys.argv) >= 3 and sys.argv[1] == 'wait') or name == 'claude-limit-wait':
        return wait_main(sys.argv[-1])
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    try:
        if '--hold' in sys.argv:
            if data.get('hook_event_name') == 'PreToolUse':
                on_hold(data)
        elif data.get('hook_event_name') == 'PreToolUse':
            on_tool(data)
        elif data.get('hook_event_name') == 'UserPromptSubmit':
            on_prompt(data)
    except SystemExit:
        raise
    except Exception as e:   # never stop a session because of this hook
        log(f'error  {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
