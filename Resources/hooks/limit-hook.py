#!/usr/bin/python3
"""Claude Code hook: pause at the usage limit instead of spending usage credits, and hold a session at a
usage percentage of its own. Installed and kept up to date by the Sttark Claude Kit app.

Each session has one of three settings (limit_modes in the app's state file):
- Follow the menu (the default): when the 5-hour or weekly limit is reached and the account would go on
  with usage credits, the session waits, unless "Use credits at the usage limit" is on in the menu.
- Always use credits: the session never waits at the limit.
- Never use credits; hold at N% (80 by default): the session waits when a limit reaches N%, whatever the
  menu says, and goes on when every limit is under N% again. It makes no model call on usage credits.
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

--hold (a second PreToolUse entry and a second UserPromptSubmit entry, each with an 8-day limit), for a
session that holds at its own N%: the hook itself waits, so the hold makes no model calls at all, not even
one every 9 minutes. It holds
- the session's wait command (Claude has said the hold line and runs it; when the hold ends the command
  runs and prints GO ON at once);
- a subagent's or background agent's tool call (they come through the same hooks with the session's id and
  their own agent id): an agent can't be counted on to run the wait command it is told to;
- while the account would charge usage credits for any reply (a limit at 100% with credits on), the
  session's own tool call and a message sent to it, with no reply at all; they go on when the hold ends.
Everything else goes through at once. For a call or message the plain hook leaves to it, --hold writes its
answer in a claim file (deciding, then holding or free); with no answer in 3 seconds (a session that never
loaded the --hold entry) the plain hook does what it did before: it stops the call with the instruction.

UserPromptSubmit: a message sent while the session must wait goes through with the same instruction, so
nothing typed is lost. A message of just "use credits" sets that session to Always use credits, as the menu
does. A message that is one of the setting phrases changes the session's setting. While a wait runs, it
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
HOLDS = os.path.join(DIR, 'holds')   # --hold's claim files, and one lock per session for the server check
TEST = os.environ.get('STTARK_LIMIT_TEST')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
URL = os.environ.get('STTARK_LIMIT_URL') or 'https://api.anthropic.com/api/oauth/usage'   # tests: a stand-in server
FRESH = 120      # seconds a usage read is good for (Claude Code reads the same usage endpoint with the same
                 # login in every session, so the Kit's own reads stay few)
FRESH_SLOW = 300  # ... for CALM after a failed read, so a shared rate limit is not hit again and again
FRESH_NEAR = 15  # ... when a limit is at 90% or more, so the pause starts soon after the limit
BACKOFF = 120    # seconds to wait after a failed usage read, doubling each time ...
BACKOFF_MAX = 900  # ... up to 15 minutes
CALM = 1800      # a good read keeps the count of failed reads until this long after the last one, so a server that
                 # allows a read only now and then backs the reads off instead of failing every few minutes
FENCE = 3600     # older copies of this script back off while `retry_at` is ahead; every write keeps it this far ahead,
                 # so a wait loop still running old code never reads the usage endpoint again (it uses the cache)
STALE = 600      # a wait loop that isn't the reader reads the endpoint itself only when the cache is this old
TICK = float(os.environ.get('STTARK_LIMIT_TICK') or 10)   # seconds between checks while a session waits
SESSIONS = 'https://api.anthropic.com/v1/code/sessions/'
EVENTS = os.environ.get('STTARK_LIMIT_EVENTS')   # tests: a file that stands in for the session's server events
NAMES = {'session': '5-hour', 'weekly_all': 'weekly'}
DEFAULT_AT = 80  # "no credits" with no number: hold at 80%
KEEP_DAYS = 30   # a setting whose session hasn't been used for this long is dropped ...
KEEP_ARCHIVED_DAYS = 7   # ... or this long for an archived one (kept a while, in case it is unarchived)
CLAIM_WAIT = float(os.environ.get('STTARK_LIMIT_CLAIM_WAIT') or 3)   # seconds the plain hook waits for --hold's answer ...
DECIDE_MAX = 20  # ... and at most this long once --hold has said it is deciding
READ_WAIT = 5    # seconds a hold decision waits for a usage read another process is making
LOCK_WAIT = 20   # seconds to wait for the state file's lock before giving up
RUN_TIMEOUT = 10  # seconds a command (security, ps) may take

# why a session waits now: the limit's name ("5-hour"), when it resets, its percent, the percent that holds
# (100 for the usage limit itself), the session's setting ("follow" or "hold"), and the highest percent among
# the limits at or over that point
Hold = collections.namedtuple('Hold', 'name until percent at mode top')


def log(line):
    with open(LOG, 'a') as f:
        f.write(time.strftime('%F %T ') + 'limit  ' + line + '\n')


def take(f, secs=0):
    """Lock the open file f, trying for up to secs seconds. True when it is locked."""
    end = time.time() + secs
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if time.time() >= end:
                return False
            time.sleep(0.05)


@contextmanager
def state():
    """The app's shared state file, under the same lock the app and the effort hook use."""
    os.makedirs(DIR, exist_ok=True)
    with open(STATE + '.lock', 'w') as lock:
        if not take(lock, LOCK_WAIT):
            raise TimeoutError(f'the state file stayed locked for {LOCK_WAIT} s')
        try:
            s = json.load(open(STATE))
        except (OSError, ValueError):
            s = {}
        yield s
        tmp = STATE + f'.{os.getpid()}.tmp'
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
                         capture_output=True, text=True, check=True, timeout=RUN_TIMEOUT).stdout
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


def calm(c, now=None):
    """The failed-read count and time a good read keeps: both until CALM after the last failure."""
    now = time.time() if now is None else now
    f = c.get('failed_at', 0)
    return {'fails': c.get('fails', 0), 'failed_at': f} if f and now - f < CALM else {}


def good_for(c, u, max_age):
    """How long the cached read is good for: max_age when given, else a minute (15 seconds near a limit, unless a
    read failed in the last CALM: then FRESH_SLOW, so frequent reads don't bring the next 429)."""
    if max_age is not None:
        return max_age
    return FRESH_SLOW if calm(c) else fresh_for(u)


def usage(max_age=None, wait=0):
    """The latest usage read, from the cache when it's no older than max_age (by default a minute, 15 seconds
    near a limit). One process reads at a time; the others use the cache, or, with `wait`, wait up to that
    many seconds for the read in progress (so the two hooks of one tool call decide on the same read). After a
    failed read (a 429, say) no process reads again until the back-off ends (Retry-After, or 2 min doubling to
    15 min), and every caller gets the last good read meanwhile. None when there's no read at all. With
    STTARK_LIMIT_TEST: the stand-in file itself, with no cache."""
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
    if u and time.time() - c.get('at', 0) < good_for(c, u, max_age):
        return u
    if time.time() < c.get('next_read', 0):
        return u   # backing off after a failed read: keep the last good one
    os.makedirs(DIR, exist_ok=True)
    with open(USAGE + '.lock', 'w') as lock:
        if not take(lock, wait):
            return u   # another session is reading it now
        try:   # read the cache again under the lock: another process may have just read or backed off
            c = json.load(open(USAGE))
        except (OSError, ValueError):
            pass
        u = c.get('usage')
        if time.time() < c.get('next_read', 0) or (
                u and time.time() - c.get('at', 0) < good_for(c, u, max_age)):
            return u
        try:
            u = fetch()
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
                urllib.error.URLError) as e:
            fails = c.get('fails', 0) + 1
            after = 0
            if isinstance(e, urllib.error.HTTPError):
                try:
                    after = int(e.headers.get('Retry-After') or 0)
                except (TypeError, ValueError):
                    after = 0
            wait_s = max(after, min(BACKOFF * 2 ** (fails - 1), BACKOFF_MAX))
            c.update(fails=fails, failed_at=time.time(), next_read=time.time() + wait_s)
            if fails == 1 or wait_s >= BACKOFF_MAX:
                log(f'usage read failed: {e}; next read in {wait_s // 60 or 1} min, '
                    + ('using the last read' if u else 'no read yet'))
            put(c)
            return u
        put({'at': time.time(), 'usage': u, **calm(c)})
        return u


def put(c):
    c = {**c, 'retry_at': time.time() + FENCE}   # the fence for older copies; this copy reads next_read
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
    return Hold(name, until, pct(p), at, mode, pct(max(x[2] for x in hit)))


def billable(u, transcript=None):
    """True when the account would charge usage credits for a reply now: a limit that counts for this
    session is at 100% or more, with credits on and their spend limit not reached."""
    return wall(u, transcript) is not None


def clock(t):
    t = (int(t) + 30) // 60 * 60
    d = datetime.datetime.fromtimestamp(t)
    day = '' if d.date() == datetime.date.today() else d.strftime('%a ')
    return day + d.strftime('%I:%M %p').lstrip('0')


def short(sid, c=''):
    """A session's id in log lines: the first 8 characters of its session id; for a session known only by its
    Remote Control id, the 8 characters after cse_. The menu writes the same."""
    if sid:
        return sid[:8]
    c = c or ''
    return c[4:12] if c.startswith('cse_') else (c[:8] or '?')


def who(sid, c='', agent=''):
    return short(sid, c) + ('/' + agent[:8] if agent else '')


# ---- the per-session setting -------------------------------------------------------------------------------

def matches(k, v, sid, c):
    return bool((sid and (k == sid or v.get('sid') == sid)) or (c and (k == c or v.get('cse') == c)))


def find_mode(s, sid='', c=''):
    """The stored setting of this session (a dict), or None for Follow the menu. Matched by key, sid or cse;
    the newest wins."""
    best = None
    for k, v in (s.get('limit_modes') or {}).items():
        if isinstance(v, dict) and matches(k, v, sid, c):
            if best is None or (v.get('set_at') or 0) > (best.get('set_at') or 0):
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


def session_cse(sid, s):
    """The cse needed to find this session's setting. Every session's hooks run this, so it stays cheap: '' when
    no setting can need it (none at all, or one names this session id); else from the app's list of sessions (it
    has each Remote Control session's transcript) or the environment; a `ps` only when some setting names no
    session id (set in the menu before the session's transcript was known)."""
    m = s.get('limit_modes') or {}
    if not m:
        return ''
    if sid and any(isinstance(v, dict) and (k == sid or v.get('sid') == sid) for k, v in m.items()):
        return ''
    c = cse_of(sid, s, here=False) if sid else ''
    if c:
        return c
    b = os.environ.get('CLAUDE_CODE_BRIDGE_SESSION_ID', '')
    if b and os.environ.get('CLAUDE_CODE_SESSION_ID', sid) in (sid, ''):
        return 'cse_' + b.split('_', 1)[1] if b.startswith('session_') else b
    if any(isinstance(v, dict) and not v.get('sid') for v in m.values()):
        return cse_of(sid, s)
    return ''


def mtime(p):
    try:
        return os.path.getmtime(p)
    except (OSError, TypeError):
        return 0


def prune(s):
    """Inside the state lock: drop the settings of sessions not used for KEEP_DAYS (KEEP_ARCHIVED_DAYS when
    archived), and the old one-time "use credits" entries."""
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
        used = max(mtime(tp), v.get('set_at') or 0, x.get('at') or 0)
        days = KEEP_ARCHIVED_DAYS if (x.get('app') or {}).get('archived') else KEEP_DAYS
        if used < now - days * 86400:
            m.pop(k)
    if 'limit_modes' in s:
        s['limit_modes'] = m
    drop_old_credits(s)


def drop_old_credits(s):
    """Inside the state lock: the one-time "use credits" (limit_credits) is gone; a session's own setting is the one
    control, so an entry left from an older Kit is dropped and logged once."""
    old = s.pop('limit_credits', None)
    if old:
        log(f'credits dropped the old one-time "use credits" of {len(old)} session(s): each session\'s setting decides')


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
        log(f'mode   {short(sid, c)} {describe(*after)} ({by})')
        return True
    return False


def hold_for(sid, c, transcript, u, s=None):
    """The Hold this session must wait for now under its setting, or None. c None: look it up if needed. The
    session's own setting is the only thing that decides for it; nothing else overrides it."""
    s = s if s is not None else peek()
    if c is None:
        c = session_cse(sid, s)
    mode, n = mode_of(s, sid, c)
    if mode == 'credits':
        return None
    if mode == 'hold':
        return wall(u, transcript, at=n, credits_only=False, mode='hold')
    if s.get('limit_credits_all'):
        return None
    return wall(u, transcript)


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
        try:
            args = subprocess.run(['ps', '-ww', '-o', 'args=', '-p', pid], capture_output=True, text=True,
                                  timeout=RUN_TIMEOUT).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ''
        m = re.search(r'--session-id[= ](cse_\w+)', args)
        if m:
            return m.group(1)
    return ''


def title(s, c, cwd):
    t = ((s.get('sessions') or {}).get(c) or {}).get('title', '').strip() if c else ''
    return t or os.path.basename(cwd or '') or 'Session'


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def others(p, key, sid, agent):
    """The other live holding rows of this session (agent ''), or of this one agent of it."""
    return [k for k, v in p.items() if k != key and isinstance(v, dict)
            and (v.get('sid') or k.split('/')[0]) == sid and (v.get('agent') or '') == agent and alive(v.get('pid'))]


def drop(key, sid=None, agent=''):
    """Remove one holding row. True when no other live row of the same session (or agent) is left."""
    with state() as s:
        p = s.get('limit_pauses') or {}
        p.pop(key, None)
        s['limit_pauses'] = p
        return sid is None or not others(p, key, sid, agent)


# ---- phrases typed in a session ----------------------------------------------------------------------------

PHRASE_HOLD = re.compile(r'(?:no credits|never use credits)(?: at)?(?: (\d{1,3}) ?%?)?')


def phrase(text):
    """The setting asked for when the whole message is one of the phrases: ('credits', None) (also for "use
    credits", which sets Always use credits, as the menu does), ('follow', None) or ('hold', N). None for any other
    message."""
    if isinstance(text, list):
        text = ' '.join(b.get('text', '') for b in text if isinstance(b, dict) and b.get('type') == 'text')
    if not isinstance(text, str) or len(text) > 60:
        return None
    t = ' '.join(re.sub(r'[^a-z0-9% ]', ' ', text.lower()).split())
    if t in ('use credits', 'credits ok', 'always use credits'):
        return 'credits', None
    if t == 'follow the menu':
        return 'follow', None
    m = PHRASE_HOLD.fullmatch(t)
    if m:
        n = int(m.group(1)) if m.group(1) else DEFAULT_AT
        if 1 <= n <= 100:
            return 'hold', n
    return None


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
            if os.environ.get('STTARK_LIMIT_POLLS'):   # tests: note which process checked
                with open(os.environ['STTARK_LIMIT_POLLS'], 'a') as f:
                    f.write(f'{os.getpid()}\n')
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


def apply(p, sid, c, tp, by, cwd=None):
    """Act on a phrase: a new setting for the session ("use credits" sets Always use credits). Every hook and every
    holding process of the session may act on the same phrase: a change is made and logged once."""
    kind, n = p
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
        return (f'This session holds at {h.at}% usage. I continue at {clock(h.until)}. '
                'Type use credits to set it to Always use credits and continue now.')
    return (f'Usage limit reached. I continue at {clock(h.until)}. '
            'Type use credits to set this session to Always use credits and continue now.')


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
    if mode == 'credits':
        return 'this session is set to always use usage credits.'
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


# ---- claims: --hold tells the plain hook it holds a call or a message ----------------------------------------

def claim_file(key):
    return os.path.join(HOLDS, re.sub(r'[^A-Za-z0-9_.-]', '_', key) + '.claim')


def claim(key, what):
    """--hold's answer for a call or message the plain hook may leave to it: 'deciding' at once, then 'holding'
    or 'free'. The plain hook removes it once it has read the answer; any left over are cleared here, at most
    every 10 minutes: an hour after the answer, or once the holding process is gone."""
    os.makedirs(HOLDS, exist_ok=True)
    p = claim_file(key)
    mark = os.path.join(HOLDS, 'cleared')
    if what == 'deciding' and time.time() - mtime(mark) > 600:
        open(mark, 'w').close()
        now = time.time()
        for f in glob.glob(os.path.join(HOLDS, '*.claim')):
            try:
                kind, pid = (open(f).read().split() + ['', ''])[:2]
                age = now - os.path.getmtime(f)
                if (age > 3600 and (kind != 'holding' or not alive(pid))) or age > 9 * 86400:
                    os.remove(f)
            except (OSError, ValueError):
                pass
    tmp = p + f'.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        f.write(f'{what} {os.getpid()}')
    os.replace(tmp, p)


def unclaim(key):
    try:
        os.remove(claim_file(key))
    except OSError:
        pass


def held_by_hook(key):
    """For the plain hook: True when --hold says it holds this call or message ('holding'). False when it says
    'free', and when it never answers within CLAIM_WAIT: the session runs without the --hold entry (it did not
    load it), so the plain hook stops the call itself, as it did before."""
    if not key:
        return False
    p = claim_file(key)
    start = time.time()
    while True:
        try:
            kind = open(p).read().split(' ')[0]
        except OSError:
            kind = ''
        if kind in ('holding', 'free'):
            unclaim(key)   # read: no one needs it now
            return kind == 'holding'
        waited = time.time() - start
        if (not kind and waited >= CLAIM_WAIT) or waited >= DECIDE_MAX:
            return False
        time.sleep(0.05)


def prompt_key(data):
    return 'prompt-' + data['prompt_id'] if data.get('prompt_id') else ''


def cached():
    """The last usage read in the cache, with no read of the endpoint."""
    if TEST:
        return usage()
    try:
        return json.load(open(USAGE)).get('usage')
    except (OSError, ValueError):
        return None


def cache_age():
    try:
        return time.time() - json.load(open(USAGE)).get('at', 0)
    except (OSError, ValueError):
        return float('inf')


def script_stamp():
    """This script's real path and its (size, mtime) now."""
    me = os.path.realpath(__file__)
    try:
        st = os.stat(me)
        return me, (st.st_size, st.st_mtime)
    except OSError:
        return me, None


def reexec(me, record):
    """Run the new copy of this script in this same process, so a wait that started before a Kit update goes on
    in the new code with no gap: same process id, so Claude Code still waits on it, and its row and claim stay.
    Only when the new copy compiles; else keep waiting in the old code."""
    try:
        compile(open(me).read(), me, 'exec')
    except (OSError, SyntaxError, ValueError):
        return
    path = os.path.join(HOLDS, f'resume-{os.getpid()}.json')
    with open(path, 'w') as f:
        json.dump(record, f)
    log(f'reload {record["sid"][:8]} {record["what"]}: the Kit updated, the wait goes on in the new code')
    sys.stdout.flush()
    sys.stderr.flush()
    os.environ['STTARK_HOLD_RESUME'] = path
    os.execv(sys.executable, [sys.executable, me] + sys.argv[1:])


def resume_main(path):
    """After reexec: go on with the wait the old code was in, then finish as it would have."""
    try:
        r = json.load(open(path))
    except (OSError, ValueError):
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    os.environ.pop('STTARK_HOLD_RESUME', None)
    h = Hold(*r['h'])
    if r['what'] == 'hold':
        key = r['key'].split('/', 1)[1] if '/' in r['key'] else ''
        if key and not key.startswith('wait-'):
            atexit.register(unclaim, key)
        hold_loop(r['sid'], r['agent'], r['tp'], r['c'], h, r['budget'], r['what'], r['key'], r['note'], resume=r)
        return True
    left = None if r['budget'] is None else max(1, r['budget'] - (time.time() - r['started']))
    why = hold_loop(r['sid'], r['agent'], r['tp'], r['c'], h, left, r['what'], r['key'], r['note'], resume=r)
    wait_end(r['sid'], r['c'], r['tp'], h, why)
    return True


# ---- the wait ------------------------------------------------------------------------------------------------

def hold_loop(sid, agent, tp, c, h, budget, what, key, note='', resume=None):
    """Wait while this session must wait, with no model calls: until the hold ends (returns why, for GO ON),
    until `budget` seconds pass (returns None; budget None: no limit but the hook's own), or until the turn or
    the process stops (exits). Shows as a row in the menu (limit_pauses, under `key`) while it waits. Of the
    rows of one session (or one of its agents) that hold at once, the first logs the hold and the last the
    resume. `note` (the tool, or "message") adds a hold line before the wait line."""
    if os.getppid() == 1:
        sys.exit(0)   # its Claude Code process is already gone
    w = who(sid, c, agent)
    r = resume or {}
    pos = r.get('pos', size(tp))
    start_mode = tuple(r['start_mode']) if r.get('start_mode') else mode_of(peek(), sid, c)
    with state() as s:
        p = s.setdefault('limit_pauses', {})
        first = not r and not others(p, key, sid, agent)
        row = {'since': time.time(), 'until': h.until, 'limit': h.name, 'cse': c, 'title': title(s, c, os.getcwd()),
               'pid': os.getpid(), 'what': what, 'sid': sid, 'mode': h.mode, 'at': h.at, 'percent': h.top}
        if agent:
            row['agent'] = agent
        if r and key in p:
            p[key]['pid'] = os.getpid()
        else:
            p[key] = row
    gone = []

    def leave():
        """Drop this row, once. True when it was the last of its session (or agent)."""
        if gone:
            return False
        gone.append(1)
        try:
            return drop(key, sid, agent)
        except Exception:
            return False
    atexit.register(leave)

    def stopped(*_):
        if leave():
            log(f'end    {w} {what} ended: the turn was stopped')
        sys.exit(0)
    for g in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(g, stopped)
    if first:
        if note:
            log(f'hold   {w} {where(h)} ({note})')
        log(f'wait   {w} {where(h)}' + (', with no model calls until it ends' if what == 'hold' else ''))
    started = r.get('started', time.time())
    asked = time.time()
    since_ms = r.get('since_ms', int(started * 1000))
    parent = os.getppid()
    os.makedirs(HOLDS, exist_ok=True)
    polls = open(os.path.join(HOLDS, re.sub(r'[^A-Za-z0-9_.-]', '_', sid or c or 'none') + '.poll'), 'w')
    poller = False
    reads = open(USAGE + '.reader', 'w')   # one wait loop on the Mac reads usage; the others use its cache
    reader = False
    me, born = script_stamp()
    while budget is None or time.time() - started < budget:
        time.sleep(TICK)
        if script_stamp()[1] != born:   # the Kit updated this script: go on waiting in the new code
            reexec(me, {'sid': sid, 'agent': agent, 'tp': tp, 'c': c, 'h': list(h), 'budget': budget, 'what': what,
                        'key': key, 'note': note, 'pos': pos, 'started': started, 'since_ms': since_ms,
                        'start_mode': list(start_mode)})
        if os.getppid() != parent or os.getppid() == 1:
            if leave():
                log(f'end    {w} {what} ended: the session closed')
            sys.exit(0)
        found, cut, pos = queued(tp, pos)
        if cut and not agent:
            stopped()
        if not found and c and time.time() - asked >= TICK * 3:   # the server every 30 s, by one process per session
            asked = time.time()
            poller = poller or take(polls)
            if poller:
                found = typed(c, since_ms)
        if found:
            since_ms = int(time.time() * 1000)   # the server check skips what the transcript already showed
            apply(found, sid, c, tp, 'typed')
        s = peek()
        reader = reader or take(reads)
        if reader or cache_age() >= STALE:
            u = usage(max_age=TICK) if time.time() >= h.until else usage()
        else:
            u = cached()
        now = hold_for(sid, c, tp, u, s)
        if not now:
            why = why_go(sid, c, s, h)
            mins = int((time.time() - started) / 60)
            if leave():
                if mode_of(s, sid, c) == start_mode and not (
                        h.mode == 'follow' and s.get('limit_credits_all')):
                    log(f'resume {w} the {h.name} limit ' + (f'is under {h.at}%' if h.mode == 'hold' else 'reset')
                        + f', after {mins} min')
                else:
                    log(f'resume {w} {why.rstrip(".")}, after {mins} min')
            return why
        if (now.name, now.until, now.at, now.mode) != (h.name, h.until, h.at, h.mode):
            with state() as s:
                r = (s.get('limit_pauses') or {}).get(key)
                if r is not None:
                    r.update(until=now.until, limit=now.name, mode=now.mode, at=now.at, percent=now.top)
        h = now
    return None


def waiting_line(h):
    if h.mode == 'hold':
        return (f'Holding at {h.at}%: the {h.name} limit is at {h.percent}%. It goes on at {clock(h.until)}, when '
                'the limit resets. Type "use credits" to set it to Always use credits and continue now.')
    return (f'Waiting for the {h.name} usage limit to reset at {clock(h.until)}. '
            'Type "use credits" to set this session to Always use credits and continue now.')


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
    why = hold_loop(sid, agent, tp, c, h, CHUNK, 'wait', key)
    wait_end(sid, c, tp, h, why)


def wait_end(sid, c, tp, h, why):
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


# claude-limit-mode by itself, with plain or quoted words: a held session may run it to change its own setting
MODE_CMD = re.compile(r'\s*(?:[\w./~-]*/)?(?:claude-limit-mode|(?:/usr/bin/)?python3 +"?[\w./~ -]*limit-hook\.py"? +mode)'
                      r'(?: +(?:"[^"`$\\]*"|\'[^\']*\'|[\w.%:@/-]+))*(?: +2>&1)?\s*')


def is_mode_cmd(cmd):
    return bool(cmd) and MODE_CMD.fullmatch(cmd) is not None


# ---- the hooks -----------------------------------------------------------------------------------------------

def on_tool(data):
    sid = data.get('session_id', '')
    tool = data.get('tool_name')
    cmd = (data.get('tool_input') or {}).get('command') if tool == 'Bash' else None
    if cmd and (is_wait(cmd) or is_mode_cmd(cmd)):
        return   # the wait itself, and a change of the setting, always run
    tp = data.get('transcript_path')
    s = peek()
    c = session_cse(sid, s)
    hold_mode = mode_of(s, sid, c)[0] == 'hold'
    u = usage(wait=READ_WAIT) if hold_mode else usage()
    h = hold_for(sid, c, tp, u, s)
    if not h:
        return
    agent = data.get('agent_id') or ''
    if h.mode == 'hold' and (agent or billable(u, tp)) and held_by_hook(data.get('tool_use_id')):
        return   # the --hold entry holds this call, with no reply
    w = who(sid, c, agent)
    if h.mode == 'hold':
        log(f'hold   {w} {where(h)} ({tool})')
    else:
        log(f'stop   {w} {tool} {where(h)}')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                             'permissionDecisionReason': say(sid, h, agent)}}))


def on_hold(data):
    """--hold, before every tool call and every message, for a session that holds at its own N%: wait here, so
    the hold makes no model calls at all. It holds the session's wait command (Claude has said the hold line and
    runs it; when the hold ends the command runs and prints GO ON at once), an agent's tool call (an agent may
    not follow the instruction to run the wait), and, while the account would charge usage credits for any
    reply, the session's own tool call and a message sent to it (no reply at all). Prints nothing; anything
    else exits at once."""
    event = data.get('hook_event_name')
    sid = data.get('session_id', '')
    agent = data.get('agent_id') or ''
    tp = data.get('transcript_path')
    waits = False
    s = peek()
    if event == 'UserPromptSubmit':
        key, note = prompt_key(data), 'message'
        p = phrase(data.get('prompt'))
        if p:   # a setting phrase counts first, also one that starts a hold (the plain hook makes the same change)
            apply(p, sid, cse_of(sid, s), tp, 'typed', data.get('cwd'))
            s = peek()
    else:
        tool = data.get('tool_name')
        cmd = (data.get('tool_input') or {}).get('command') if tool == 'Bash' else None
        if cmd and is_mode_cmd(cmd):
            return
        waits = bool(cmd) and is_wait(cmd)
        key, note = data.get('tool_use_id') or '', tool
    if not s.get('limit_modes'):
        return   # no session has a setting of its own
    c = session_cse(sid, s)
    if mode_of(s, sid, c)[0] != 'hold':
        return   # follow the menu, and always use credits: the plain hook does it all
    if not waits and not key:
        return   # no id to tell the plain hook by: it does what it did before
    if not waits:
        claim(key, 'deciding')
    try:
        u = usage(wait=READ_WAIT)
        h = hold_for(sid, c, tp, u, s)
        silent = bool(h) and not waits and not agent and h.mode == 'hold' and billable(u, tp)
        if not h or h.mode != 'hold' or not (waits or agent or silent):
            if not waits:
                claim(key, 'free')
            return
        if not waits:
            claim(key, 'holding')
            atexit.register(unclaim, key)
    except BaseException:
        if not waits:
            claim(key, 'free')
        raise
    if waits:
        note = ''   # the plain hook logged the hold when it stopped the step
    elif silent:
        note += '; no reply: one now would use credits'
    hold_loop(sid, agent, tp, c or cse_of(sid, s), h, None, 'hold', sid + '/' + (key or f'wait-{os.getpid()}'), note)


def on_prompt(data):
    sid = data.get('session_id', '')
    tp = data.get('transcript_path')
    prompt = data.get('prompt')
    s = peek()
    p = phrase(prompt)
    c = cse_of(sid, s) if p else session_cse(sid, s)
    if p:
        apply(p, sid, c, tp, 'typed', data.get('cwd'))
        s = peek()
    hold_mode = mode_of(s, sid, c)[0] == 'hold'
    u = usage(wait=READ_WAIT) if hold_mode else usage()
    h = hold_for(sid, c, tp, u, s)
    quiet = bool(h) and h.mode == 'hold' and billable(u, tp) and held_by_hook(prompt_key(data))
    if p:
        said = prompt if isinstance(prompt, str) else ' '.join(
            b.get('text', '') for b in prompt if isinstance(b, dict) and b.get('type') == 'text')
        head = (f'Sttark Claude Kit: the person typed "{said.strip()}". '
                + f'This session is now set to: {describe(*mode_of(s, sid, c))}. '
                + ('(In the Sttark Claude Kit window, this session\'s At the usage limit menu shows it; '
                   'picking another item there undoes it.) ' if p[0] == 'credits' else ''))
        if h and not quiet:
            log(f'message {short(sid, c)} {where(h)}: Claude says so and waits')
            ctx = head + 'Say so in one line. Then: ' + say(sid, h) + \
                ' After "GO ON", go on with the task you were doing before, if there was one.'
        else:   # going on now, or held in the --hold entry until the hold ends
            ctx = head + 'Say so in one line, then go on with the task you were doing before, if there was one.'
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}}))
        return
    if not h or quiet:
        return   # nothing to say, or the --hold entry holds the message until the hold ends
    log(f'message {short(sid, c)} {where(h)}: Claude says so and waits')
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
a cse_ or session_ id, a unique start of one (6 or more characters), or a session's full name."""


class Bad(Exception):
    pass


UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def known(s, sid='', c=''):
    """True when this Mac has seen the session: its transcript, the app's list of sessions, a setting or a hold."""
    if sid and transcript_of(sid):
        return True
    for k, x in (s.get('sessions') or {}).items():
        if isinstance(x, dict) and ((c and k == c) or (sid and sid_of_transcript(x.get('transcript')) == sid)):
            return True
    if find_mode(s, sid, c):
        return True
    return any(isinstance(v, dict) and ((sid and (v.get('sid') or k.split('/')[0]) == sid) or (c and v.get('cse') == c))
               for k, v in (s.get('limit_pauses') or {}).items())


def resolve(who_, s):
    """(sid, cse) of the session a person or a script named."""
    if who_ in ('.', 'this', ''):
        sid = os.environ.get('CLAUDE_CODE_SESSION_ID', '')
        c = cse()
        if not sid and not c:
            raise Bad('not inside a Claude Code session: give the session id or name')
        return sid or sid_of_cse(c, s), c or cse_of(sid, s, here=False)
    if who_.startswith('session_'):
        who_ = 'cse_' + who_[len('session_'):]
    sessions = s.get('sessions') or {}
    found = {}   # (sid, cse) pairs, keyed by the cse when there is one, else the sid

    def add(sid, c):
        sid = sid or (sid_of_cse(c, s) if c else '')
        c = c or (cse_of(sid, s, here=False) if sid else '')
        if sid or c:
            found[c or sid] = (sid, c)
    if who_.startswith('cse_') and who_ in sessions:
        add('', who_)
    elif UUID.fullmatch(who_):
        if not known(s, sid=who_):
            raise Bad(f'no session {who_} on this Mac')
        add(who_, '')
    elif who_.startswith('cse_') and len(who_) > 20:
        if not known(s, c=who_):
            raise Bad(f'no session {who_} on this Mac')
        add('', who_)   # a full cse id with a setting or a hold, that the app hasn't listed
    else:
        if len(who_) >= 6:
            for k, x in sessions.items():
                t = sid_of_transcript((x or {}).get('transcript')) if isinstance(x, dict) else ''
                if k.startswith(who_) or (t and t.startswith(who_)):
                    add(t, k)
            for k, v in (s.get('limit_modes') or {}).items():
                if isinstance(v, dict) and any(i and i.startswith(who_) for i in (k, v.get('sid'), v.get('cse'))):
                    add(v.get('sid') or (k if UUID.fullmatch(k) else ''),
                        v.get('cse') or (k if k.startswith('cse_') else ''))
            for v in (s.get('limit_pauses') or {}).values():
                if isinstance(v, dict) and (v.get('sid') or '').startswith(who_):
                    add(v['sid'], v.get('cse') or '')
            if re.fullmatch(r'[0-9a-f-]{6,36}', who_):
                for tp in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{glob.escape(who_)}*.jsonl')):
                    add(sid_of_transcript(tp), '')
        if not found:
            for k, x in sessions.items():
                if isinstance(x, dict) and (x.get('title') or '').strip().lower() == who_.strip().lower() \
                        and not (x.get('app') or {}).get('archived'):
                    add('', k)
    if not found:
        raise Bad(f'no session matches "{who_}"')
    if len(found) > 1:
        raise Bad(f'"{who_}" matches {len(found)} sessions: give more of the id')
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
        rows = sorted(((v.get('set_at') or 0, k, v) for k, v in (s.get('limit_modes') or {}).items()
                       if isinstance(v, dict)), key=lambda r: r[0])
        if not rows:
            print('No session has its own setting: every session follows the menu.')
        for at, k, v in rows:
            c = v.get('cse') or (k if k.startswith('cse_') else '')
            mode, n = mode_of({'limit_modes': {k: v}}, v.get('sid', ''), c or k)
            when = datetime.datetime.fromtimestamp(at).strftime('%b %d %I:%M %p')
            print(f'{name_of(s, v.get("sid", ""), c)} ({short(v.get("sid", ""), c or k)}): '
                  f'{describe(mode, n)} (set by {v.get("by", "?")}, {when})')
        return 0
    settings = ('follow', 'credits', 'hold')
    if args and args[0].lower() in settings:
        who_, rest = '.', args
    elif args:
        who_, rest = args[0], args[1:]
    else:
        who_, rest = '.', []
    try:
        sid, c = resolve(who_, s)
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
    print(f'{name_of(s, sid, c)} ({short(sid, c)}): {describe(*mode_of(s, sid, c))}')
    return 0


def main():
    if os.environ.get('STTARK_HOLD_RESUME') and resume_main(os.environ['STTARK_HOLD_RESUME']):
        return
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
            if data.get('hook_event_name') in ('PreToolUse', 'UserPromptSubmit'):
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
