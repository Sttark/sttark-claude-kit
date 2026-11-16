#!/usr/bin/python3
"""Usage by session: how much of the person's Claude Code use each session took, from the records on this Mac.

Reads each session's record, ~/.claude/projects/<folder>/<id>.jsonl, and its agents' records,
<id>/subagents/agent-*.jsonl, and writes usage/by-session.json in the Kit's folder for the window's Usage page and
the phone's Usage tab. A page open is fast because the reading is incremental: usage/scan-cache.json keeps, for each
record file, its size, time and how far it was read, and what it held, so a later scan reads only the lines added
since (a file that got shorter or was replaced is read again from the start).

Each reply counts once (Claude Code writes a reply once for each of its parts, and a resumed or forked session's
record copies earlier replies: the copy in the session's own record wins, then the older file). Its tokens (input,
output, 5-minute and 1-hour cache writes, cache reads, web searches) count at its model's API price (PRICES), because
the usage limit also counts a larger model as more use; a share is a session's part of the person's use in a period,
never a percent of the limit, which Anthropic gives only as a total.

It also adds up how long Claude was at work in each record (its active time: the model writing and the tools it
runs, never a wait: for the person, for the usage limit, for an agent, for a check, for a sleep or a poll), and the
kind of that work from the tool calls (software, design, browser and admin, or small and mixed), so the Usage page can
say what the same work would take people. The method and where its factors come from: docs/human-work.md.

Who a record belongs to:
  - a session with a Remote Control link (the record's newest bridge-session line, or the Kit's own record of it);
    its agents' records, and the records of runs started in its scratchpad folder, count as its agents;
  - a session with no link, by its own id ("On this Mac only");
  - the Kit's own runs (its wait checks and rules refresh), and runs in temporary folders, one row each.
Names come from the Claude app's list, the Kit's state and its archived list, then the record's own title lines;
never from a prompt or a reply. Nothing is sent anywhere: the Kit sends the phone only names, ids and numbers.

  usage-scan.py              scan, write by-session.json, print one line of what it did
  usage-scan.py --if-older N scan only when by-session.json is more than N seconds old
  usage-scan.py --prices     list each model in the kept data, its tokens and whether PRICES has it; exit 1 when
                             one with tokens has no price (tools/usage-scan-test.py runs it)
STTARK_KIT_DIR, STTARK_KIT_LOG and STTARK_CLAUDE_DIR point it at test folders and a test log. STTARK_USAGE_KIND, a
command, stands in for the Haiku call that names the kind of a session the tool calls leave unclear (tests).
"""
import calendar, fcntl, json, os, re, subprocess, sys, time

KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
CLAUDE_DIR = os.environ.get('STTARK_CLAUDE_DIR') or os.path.expanduser('~/.claude')
PROJECTS = os.path.join(CLAUDE_DIR, 'projects')
DIR = os.path.join(KIT, 'usage')   # a folder of its own: the app's watch on the Kit's folder does not see these writes
OUT = os.path.join(DIR, 'by-session.json')
CACHE = os.path.join(DIR, 'scan-cache.json')
LOCK = os.path.join(DIR, 'scan.lock')
KEEP_DAYS = 45          # replies older than this are not kept; Custom periods start at the oldest day kept
VERSION = 2             # of the cache: a new one reads every file again

# API prices, dollars per million tokens: input, output, 5-minute cache write, 1-hour cache write, cache read.
# The one table of prices. A model in the records with no row here counts at its family's newest price and is
# listed under "unpriced" in by-session.json; tools/usage-scan-test.py fails while one is in recent data.
PRICES = {
    'claude-fable-5-2':  (8.00, 40.00, 10.00, 16.00, 0.20),
    'claude-mythos-5-2': (8.00, 40.00, 10.00, 16.00, 0.20),
    'claude-fable-5-1':  (10.00, 50.00, 12.50, 20.00, 0.25),
    'claude-mythos-5-1': (10.00, 50.00, 12.50, 20.00, 0.25),
    'claude-fable-5':    (10.00, 50.00, 12.50, 20.00, 1.00),
    'claude-mythos-5':   (10.00, 50.00, 12.50, 20.00, 1.00),
    'claude-opus-5-5':   (4.00, 20.00, 5.00, 8.00, 0.20),
    'claude-opus-5':     (5.00, 25.00, 6.25, 10.00, 0.50),
    'claude-opus-4-8':   (5.00, 25.00, 6.25, 10.00, 0.50),
    'claude-opus-4-7':   (5.00, 25.00, 6.25, 10.00, 0.50),
    'claude-opus-4-6':   (5.00, 25.00, 6.25, 10.00, 0.50),
    'claude-sonnet-5-5': (2.00, 10.00, 2.50, 4.00, 0.10),
    'claude-sonnet-5':   (2.00, 10.00, 2.50, 4.00, 0.20),
    'claude-sonnet-4-6': (3.00, 15.00, 3.75, 6.00, 0.30),
    'claude-haiku-5-5':  (0.10, 0.50, 0.125, 0.20, 0.01),
    'claude-haiku-4-5':  (1.00, 5.00, 1.25, 2.00, 0.10),
}
# A prompt over this many tokens costs more on these models.
LONG = {'claude-haiku-5-5': (100000, (0.50, 2.50, 0.625, 1.00, 0.05))}
FAST = 2.0              # fast mode costs twice the standard price
WEB_SEARCH = 0.01       # dollars for each web search
FAMILY = [('fable', 'claude-fable-5-2'), ('mythos', 'claude-mythos-5-2'), ('opus', 'claude-opus-5-5'),
          ('sonnet', 'claude-sonnet-5-5'), ('haiku', 'claude-haiku-5-5')]

# Kinds of work, and their factors: the hours of a person's work that one hour of Claude at work equals. The one place
# they are set; the Usage page and the phone take them from by-session.json. Where the numbers come from, and how
# the active time and the kind are found: docs/human-work.md.
WORK = [('software', 'Software', 12.0),             # writes, tests and ships code
        ('design', 'Design', 5.0),                  # CAD, drawings, renders, 3D models, plan sheets
        ('admin', 'Browser and admin', 2.5),        # the browser, forms, orders, email, office tools
        ('small', 'Small or mixed', 2.0)]           # short questions and quick fixes, or no clear kind
SMALL = 3600            # seconds: a session with less active time than this and no clear kind is small
STABLE = os.path.expanduser('~/.local/share/claude/stable/claude')   # the Kit's fixed copy of Claude Code
CLAUDE = STABLE if os.access(STABLE, os.X_OK) else os.path.expanduser('~/.local/bin/claude')

UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
SCRATCH = re.compile('-(' + UUID + ')-scratchpad(?:-|$)')   # a folder in a session's own scratchpad
TEMP = re.compile(r'^-(private-|var-folders-|tmp-|tmp$)')       # /private/tmp, /private/var/folders, /tmp
KIT_FOLDER = '-Library-Application-Support-SttarkClaudeKit'      # the Kit's own runs (wait checks, the rules refresh)
DATED = re.compile(r'-\d{8}$')
RUNS = 5                # more unnamed sessions with no link than this in one folder make one row


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'usage  ' + line + '\n')
    except OSError:
        pass


def model_id(m):
    """claude-opus-5-5 from claude-opus-5-5[1m], us.anthropic.claude-opus-5-5, claude-haiku-4-5-20251001."""
    m = (m or '').strip().lower()
    m = m.split('[', 1)[0]
    if '.claude-' in m:
        m = 'claude-' + m.split('.claude-', 1)[1]
    m = re.sub(r'-v\d+(:\d+)?$', '', m)
    return DATED.sub('', m)


def price_of(model):
    """(prices, priced): the model's row, else its family's newest row."""
    if model in PRICES:
        return PRICES[model], True
    for word, stand_in in FAMILY:
        if word in model:
            return PRICES[stand_in], False
    return PRICES['claude-opus-5-5'], False


def model_name(model):
    """Opus 5.5 from claude-opus-5-5."""
    m = re.match(r'claude-([a-z]+)-(\d+(?:-\d+)*)$', model)
    if not m:
        return model or 'Unknown model'
    return m.group(1).capitalize() + ' ' + m.group(2).replace('-', '.')


def value(row):
    """Dollars at API prices for one reply: row = [ts, model, in, out, c5m, c1h, cr, searches, fast, side]."""
    p, _ = price_of(row[1])
    long = LONG.get(row[1])
    if long and row[2] + row[4] + row[5] + row[6] > long[0]:
        p = long[1]
    usd = (row[2] * p[0] + row[3] * p[1] + row[4] * p[2] + row[5] * p[3] + row[6] * p[4]) / 1e6
    return usd * (FAST if row[8] else 1) + row[7] * WEB_SEARCH


def iso(ts):
    """Unix time of '2026-11-16T14:43:10.123Z'; None when it is not one."""
    try:
        return calendar.timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19]), 0, 0, 0))
    except (TypeError, ValueError, IndexError):
        return None


def iso_ms(ts):
    """iso() with the part of a second: 1794842590.123."""
    t = iso(ts)
    if t is not None and ts[19:20] == '.':
        try:
            t += float('0' + ts[19:23])
        except ValueError:
            pass
    return t


def num(x):
    return x if isinstance(x, int) and x > 0 else 0


# ---------- active time: how long Claude was at work, waits left out ----------
# A record's active time is the model's time (from what it answered, or the last hook before its request, to each
# part of its reply) and the tools' time (from a tool call to its result), for one reply at a time: the parts of one
# reply that overlap (tools that run at once) count once. Never active: the time between a finished turn and the
# person's next prompt, hooks and other notes in between, and every wait below. The method: docs/human-work.md.

CAP = 300.0         # seconds: the most one model part or one tool run counts, unless the model says it thought longer
QUICK_CAP = 60.0    # these tools never take longer; more is a hold or a permission prompt
QUICK = {'Read', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit', 'Glob', 'Grep', 'LS', 'TodoWrite', 'ToolSearch', 'Skill',
         'SendUserFile', 'EnterWorktree', 'ExitWorktree'}
# Tools whose run is a wait, never work: the person answers a question or approves a plan, an agent works (its own
# record counts its time), a monitor or a timer waits for something to happen, another session is asked.
WAIT_TOOLS = {'AskUserQuestion', 'ExitPlanMode', 'EnterPlanMode', 'Agent', 'Task', 'SendMessage', 'TaskOutput',
              'BashOutput', 'AgentOutputTool', 'KillShell', 'TaskStop', 'Monitor', 'ScheduleWakeup', 'Workflow', 'Sleep',
              'ListAgents', 'CronCreate', 'CronList', 'CronDelete', 'RemoteTrigger', 'PushNotification'}
WAIT_PREFIX = ('mcp__claude-code-remote__',)
# A shell command that waits: the Kit's waits (claude-limit-wait at the usage limit, claude-wait), a watch on a pull
# request's checks or a run, a followed log, a poll loop (until or while, with a sleep), or sleeps of 20 seconds or more.
WAIT_CMD = re.compile(r'(?:^|[;&|(\n]\s*)(?:claude-limit-wait|claude-wait)\b|\bgh\s+(?:run\s+watch|pr\s+checks\b[^\n|;&]*--watch)|'
                      r'(?<![\w-])tail\s+-[a-zA-Z]*[fF]\b')
POLL = re.compile(r'(?<![\w-])(?:until|while)\b[^\n]*?(?:;|\n)\s*do\b[\s\S]{0,600}?(?<![\w-])sleep\b')
SLEEP = re.compile(r'(?<![\w-])sleep\s+(\d+(?:\.\d+)?)\s*([smh]?)\b')
LONG_SLEEP = 20.0

# Kinds of work, from the tool calls. A letter and a weight per call: S software (tests, builds, pull requests and
# CI), s a weak software sign (a code edit, a commit: design work also edits scripts and commits), D design (CAD
# files and tools, drawing and render scripts), d a weak design sign (looking at an image), A browser and admin
# (the Claude window in Chrome, browser tools, email drafts, Asana and other office tools).
CODE = re.compile(r'\.(py|swift|ts|tsx|js|mjs|cjs|jsx|astro|vue|svelte|go|rs|rb|java|kt|kts|c|cc|cpp|cxx|h|hpp|m|mm|'
                  r'sh|zsh|bash|css|scss|less|html|sql|ya?ml|toml|gradle|cs|php|lua|ex|exs|erl|dart|scala|tf|plist|'
                  r'proto|graphql|prisma)$', re.I)
CAD = re.compile(r'\.(scad|stl|step|stp|dxf|dwg|obj|glb|gltf|3mf|f3d|fcstd|blend|skp|ifc|iges|igs|3dm)\b', re.I)
CAD_TOOLS = ('onshape', 'openscad', 'cadquery', 'build123d', 'trimesh', 'ezdxf', 'blender', 'freecad', 'matterport', 'sketchup')
DRAW = re.compile(r'(?:python3?|node|venv/bin/python)\s+\S*(?:draw|render|plan|elev|sheet|scene|model|site|floor|cad|'
                  r'house|front|persp)\w*\.(?:py|m?js)\b', re.I)
TESTS = re.compile(r'(?<![\w-])gh\s+(?:pr|run|release|workflow)\b|\b(?:npm|pnpm|yarn)\s+(?:test|ci|run\s+(?:build|test|check|lint|'
                   r'typecheck)\S*)|\bnpx\s+(?:vitest|tsc|eslint|playwright|astro\s+check)\b|\bvitest\b|\bpytest\b|'
                   r'\bpython3?\s+-m\s+unittest\b|\bswift\s+(?:build|test)\b|\bswiftc\b|\bxcodebuild\b|\./build\.sh\b|'
                   r'\bcargo\s+(?:build|test)\b|\bgo\s+(?:build|test)\b|(?:^|[;&|(]\s*)make(?:\s|$)|\btools/[\w-]+-test\b|'
                   r'\b[\w-]+[_-]test\.(?:py|sh|swift)\b')
TEST_WORDS = ('gh ', 'npm', 'pnpm', 'yarn', 'npx', 'vitest', 'pytest', 'unittest', 'swift', 'xcodebuild', 'build.sh',
              'cargo', 'go ', 'make', 'test')   # TESTS can match only with one of these in the command
COMMIT = re.compile(r'(?<![\w-])git\s+(?:commit|push)\b')
BROWSER_CMD = re.compile(r'(?<![\w-])claude-window\b')
ADMIN_TOOL = re.compile(r'chrome|playwright|browser|computer-use|computer_use|gmail|_draft|asana_(?:create|update|add|move)|'
                        r'calendar_create|send_message|helpscout_create|cms_edit|discount_code|inventory_take|alibaba', re.I)
DESIGN_TOOL = re.compile(r'onshape|figma|canva', re.I)
IMAGE = re.compile(r'\.(png|jpe?g|webp|gif|svg|pdf|tiff?|heic)$', re.I)


def bash_wait(cmd):
    """(waits, seconds of short sleeps in it) for a shell command. Only its first 4,000 characters are read: a longer
    command is a script written in place, and its own words say nothing of the command."""
    if not isinstance(cmd, str):
        return False, 0.0
    cmd = cmd[:4000]
    if ('claude-' in cmd or 'watch' in cmd or 'tail' in cmd) and WAIT_CMD.search(cmd):
        return True, 0.0
    if 'sleep' not in cmd:
        return False, 0.0
    if ('until' in cmd or 'while' in cmd) and POLL.search(cmd):
        return True, 0.0
    s = sum(float(n) * {'': 1, 's': 1, 'm': 60, 'h': 3600}[u] for n, u in SLEEP.findall(cmd))
    return s >= LONG_SLEEP, s


def signs(name, inp):
    """{letter: weight} for one tool call (see the kinds above)."""
    out = {}
    if name == 'Read':
        if IMAGE.search(str(inp.get('file_path') or '')):
            out['d'] = 1
    elif name in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        p = str(inp.get('file_path') or inp.get('notebook_path') or '')
        if CAD.search(p):
            out['D'] = 3
        elif CODE.search(p):
            out['s'] = 1
    elif name == 'Bash':
        c = str(inp.get('command') or '')[:4000]
        if 'claude-window' in c and BROWSER_CMD.search(c):
            out['A'] = 2
        low = c.lower()
        if CAD.search(c) or any(w in low for w in CAD_TOOLS):
            out['D'] = 3
        elif ('python' in c or 'node' in c) and DRAW.search(c):
            out['D'] = 2
        if any(w in c for w in TEST_WORDS) and TESTS.search(c):
            out['S'] = 3
        elif 'git' in c and COMMIT.search(c):
            out['s'] = 1
    elif name.startswith('mcp__'):
        if DESIGN_TOOL.search(name):
            out['D'] = 3
        elif ADMIN_TOOL.search(name):
            out['A'] = 2
    return out


def person_prompt(d, c):
    """A prompt the person typed, or one the Kit sends when it brings a session back: it starts a turn."""
    if d.get('isMeta') or d.get('isCompactSummary'):
        return False
    o = d.get('origin')
    o = o.get('kind') if isinstance(o, dict) else o
    if o not in (None, 'human'):
        return False
    if isinstance(c, str):
        return not c.startswith('<')
    return isinstance(c, list) and any(isinstance(b, dict) and b.get('type') == 'text' for b in c) \
        and not any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c)


def cut_holds(s, e, holds):
    """[s, e) without the times the Kit held this session or agent at the usage limit."""
    parts = [(s, e)]
    for hs, he in holds:
        if hs >= e:
            break
        nxt = []
        for a, b in parts:
            if he <= a or hs >= b:
                nxt.append((a, b))
                continue
            if a < hs:
                nxt.append((a, hs))
            if he < b:
                nxt.append((he, b))
        parts = nxt
    return parts


def union(iv):
    tot, cs, ce = 0.0, None, None
    for s, e in sorted(iv):
        if cs is None or s > ce:
            if cs is not None:
                tot += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    return tot + (ce - cs if cs is not None else 0.0)


def sig_text(sg):
    return ''.join('%s%d' % (k, sg[k]) for k in sorted(sg))


def close_reply(e):
    """The reply being read: its active time and signs into e['a'] (again as its tools finish)."""
    o = e['st'].get('o')
    if o:
        e['a'][o[0]] = [round(o[1], 1), round(union(o[2]), 1), o[4], sig_text(o[3])]


def add_time(e, mid, s, t, cap, holds):
    """A model part or a tool run of reply `mid`, from s to t: without the Kit's holds, at most `cap` seconds."""
    if t <= s:
        return
    o = e['st'].get('o')
    for a, b in cut_holds(s, t, holds):
        b = min(b, a + cap)
        if o and o[0] == mid:
            o[2].append([round(a, 2), round(b, 2)])
        elif mid in e['a']:
            e['a'][mid][1] = round(e['a'][mid][1] + b - a, 1)   # a late result of an earlier reply


def read_active(d, t, e, holds):
    """One line of a record, for its active time. `t` is the line's time."""
    st = e['st']
    ty = d.get('type')
    m = d.get('message') if isinstance(d.get('message'), dict) else {}
    if ty == 'assistant':
        mid = m.get('id') or d.get('uuid')
        if not isinstance(mid, str):
            return
        start = st.get('f') if st.get('f') is not None else t
        if st.get('r') is not None:
            start = max(start, min(t, st['r']))   # an API error's retry wait
        o = st.get('o')
        if not o or o[0] != mid:
            close_reply(e)
            o = st['o'] = [mid, t, [], {}, st.get('n', 0)]
        content = m.get('content') if isinstance(m.get('content'), list) else []
        calls = []   # (tool_use, wait, seconds of short sleeps)
        for b in content:
            if isinstance(b, dict) and b.get('type') == 'tool_use':
                name = b.get('name') or ''
                inp = b.get('input') if isinstance(b.get('input'), dict) else {}
                if name in WAIT_TOOLS or name.startswith(WAIT_PREFIX):
                    calls.append((b, True, 0.0))
                else:
                    calls.append((b,) + (bash_wait(inp.get('command')) if name == 'Bash' else (False, 0.0)))
        only_wait = calls and len(calls) == len(content) and all(c[1] for c in calls)
        synthetic = str(m.get('model') or '').startswith('<') or d.get('isApiErrorMessage')
        if not synthetic and not (st.get('w') and only_wait):   # not an error note, not the next turn of a wait loop
            took = sum(d[k] / 1000 for k in ('thinkingDurationMs', 'toolInputStreamMs')
                       if isinstance(d.get(k), (int, float)) and d[k] > 0)
            add_time(e, mid, start, t, max(CAP, took + 30), holds)
        for b, wait, minus in calls:
            name = b.get('name') or ''
            inp = b.get('input') if isinstance(b.get('input'), dict) else {}
            if isinstance(b.get('id'), str):
                st.setdefault('tu', {})[b['id']] = [t, mid, 1 if wait else 0, minus, QUICK_CAP if name in QUICK else CAP]
            for k, v in signs(name, inp).items():
                o[3][k] = o[3].get(k, 0) + v
        st['f'], st['r'], st['w'] = t, None, 0
    elif ty == 'user':
        c = m.get('content')
        results = [b for b in c if isinstance(b, dict) and b.get('type') == 'tool_result'] if isinstance(c, list) else []
        pd = d.get('permissionDecision') if isinstance(d.get('permissionDecision'), dict) else {}
        person = str(pd.get('source') or '').startswith('user')   # the person answered a permission prompt
        waited = False
        for b in results:
            tu = (st.get('tu') or {}).pop(b.get('tool_use_id'), None)
            if not tu:
                continue
            if tu[2] or person:
                waited = True
                continue
            add_time(e, tu[1], tu[0], max(tu[0], t - tu[3]), tu[4], holds)
        if results:
            st['w'] = 1 if waited else 0
        elif not e['agent'] and person_prompt(d, c):
            st['n'] = st.get('n', 0) + 1
            st['w'] = 0
        st['f'] = t if st.get('f') is None else max(st['f'], t)
        st['r'] = None
    elif ty in FEEDS:
        # hooks' notes, system lines and the request itself: the next request starts after them (a prompt the Kit
        # holds at the usage limit gets its hooks' notes when the hold ends), but they never make the time before
        # them active
        if ty == 'system' and d.get('subtype') == 'api_error' and isinstance(d.get('retryInMs'), (int, float)):
            st['r'] = t + d['retryInMs'] / 1000
        feed(e, t)


FEEDS = {'attachment', 'system', 'api-request', 'api-request-shape'}


def feed(e, t):
    st = e['st']
    st['f'] = t if st.get('f') is None else max(st['f'], t)


def hold_key(e):
    """How the Kit's log names this record: the session's first 8, and an agent's first 8 after a slash."""
    if e['agent']:
        a = e['agent'][6:] if e['agent'].startswith('agent-') else e['agent']
        return e['sid'][:8] + '/' + a[:8]
    return e['sid'][:8]


HOLD_LINE = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) limit  (hold|resume) +([0-9a-f]{8}(?:/[0-9a-z]{8})?) (.*)$')


def read_holds(cache):
    """The Kit's holds at the usage limit that make no reply (the hook itself waits, so the held tool call or message
    takes as long as the hold): from the Kit log's hold line to its resume line, for each session and agent. Only what
    the log gained since the last scan is read; the holds stay in the cache after the log drops its old lines."""
    h = cache.setdefault('holds', {})
    lg = cache.setdefault('log', {'ino': 0, 'off': 0, 'open': {}})
    try:
        st = os.stat(LOG)
    except OSError:
        return h
    if st.st_ino != lg.get('ino') or st.st_size < lg.get('off', 0):
        lg.update(ino=st.st_ino, off=0)
    if st.st_size == lg['off']:
        return h
    with open(LOG, 'rb') as f:
        f.seek(lg['off'])
        data = f.read()
    end = data.rfind(b'\n') + 1
    lg['off'] += end
    for line in data[:end].decode('utf-8', 'replace').split('\n'):
        if ' limit  ' not in line:
            continue
        x = HOLD_LINE.match(line)
        if not x:
            continue
        t = time.mktime(time.strptime(x.group(1), '%Y-%m-%d %H:%M:%S'))
        what, key = x.group(2), x.group(3)
        if what == 'hold':
            lg['open'].setdefault(key, t)
            continue
        s = lg['open'].pop(key, None)
        after = re.search(r'after (\d+) min', x.group(4))
        if s is None and after:
            s = t - int(after.group(1)) * 60
        if s is not None:
            w = [round(s), round(t + 1)]   # the log's times are whole seconds; the held call was made just before
            if w not in h.setdefault(key, []):
                h[key].append(w)
                h[key].sort()
    cut = time.time() - KEEP_DAYS * 86400
    for key in list(h):
        h[key] = [w for w in h[key] if w[1] >= cut]
        if not h[key]:
            del h[key]
    return h


# ---------- reading one record ----------

def read_lines(path, entry, start, holds=()):
    """Reads `path` from byte `start` to its last whole line into `entry`; returns the bytes read. A line still being
    written waits for the next scan. Reads 4 MB at a time, so a large record never fills the memory."""
    used, carry = 0, b''
    cut = time.time() - KEEP_DAYS * 86400
    with open(path, 'rb') as f:
        f.seek(start)
        while True:
            block = f.read(4 << 20)
            if not block:
                break
            block = carry + block
            end = block.rfind(b'\n') + 1
            if end <= 0:
                carry = block
                continue
            for line in block[:end].split(b'\n'):
                if line:
                    read_line(line, entry, holds, cut)
            used += end
            carry = block[end:]
    return used


SKIP = (b'{"type":"queue-operation"', b'{"type":"api-request-blob"', b'{"type":"file-history', b'{"type":"pr-link"',
        b'{"type":"last-prompt"')   # lines with nothing for the scan
TIMESTAMP = re.compile(rb'"timestamp":"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)"')


def read_line(line, entry, holds=(), cut=0):
    """One line of a record: a reply's usage, the session's link, a title, and its time for the active time."""
    if line.startswith(SKIP):
        return
    if (line.startswith(b'{"type":"attachment"') or line.startswith(b'{"type":"api-request')) and 'st' in entry:
        # only its time counts, and these lines can be large: no need to parse them. An attachment's own time is
        # its last "timestamp" (after the attachment itself); a request's is near its start.
        i = line.rfind(b'"timestamp":"') if line[10:20] == b'attachment' else line.find(b'"timestamp":"', 0, 400)
        x = TIMESTAMP.match(line, i) if i >= 0 else None
        t = iso_ms(x.group(1).decode()) if x else None
        if t is not None and t >= cut:
            feed(entry, t)
        return
    named = len(line) < 8192 and (b'"bridge-session"' in line or b'"custom-title"' in line or b'"ai-title"' in line
                                  or b'"agent-name"' in line)
    if not named and b'"timestamp"' not in line:
        return
    try:
        d = json.loads(line)
    except ValueError:
        return
    if not isinstance(d, dict):
        return
    ts = d.get('timestamp')
    if isinstance(ts, str) and 'st' in entry:
        t = iso_ms(ts)
        if t is not None and t >= cut:
            read_active(d, t, entry, holds)
    if d.get('type') == 'assistant' and b'"usage"' in line:
        m = d.get('message') if isinstance(d.get('message'), dict) else {}
        u = m.get('usage')
        mid = m.get('id')
        ts = iso(ts)
        if not isinstance(u, dict) or not mid or ts is None or ts < cut:
            return
        model = model_id(m.get('model'))
        if not model or model.startswith('<'):
            return   # Claude Code's own notes, such as <synthetic>, use no tokens
        cc = u.get('cache_creation') if isinstance(u.get('cache_creation'), dict) else {}
        c1h, c5m = num(cc.get('ephemeral_1h_input_tokens')), num(cc.get('ephemeral_5m_input_tokens'))
        written = num(u.get('cache_creation_input_tokens'))
        if c1h + c5m < written:   # no split given: the rest counts as 5-minute writes
            c5m += written - c1h - c5m
        tools = u.get('server_tool_use') if isinstance(u.get('server_tool_use'), dict) else {}
        row = [ts, model, num(u.get('input_tokens')), num(u.get('output_tokens')), c5m, c1h,
               num(u.get('cache_read_input_tokens')), num(tools.get('web_search_requests')),
               1 if u.get('speed') == 'fast' else 0, 1 if d.get('isSidechain') else 0]
        old = entry['m'].get(mid)
        if old is None or row[3] >= old[3]:   # each part repeats the reply's usage; the last has its whole output
            entry['m'][mid] = row
        if not entry['agent'] and isinstance(d.get('cwd'), str) and d['cwd']:
            entry['folder'] = os.path.basename(d['cwd'].rstrip('/'))[:80]   # its own name only: never the path
    elif named:
        t = d.get('type')
        if t == 'bridge-session' and isinstance(d.get('bridgeSessionId'), str):
            entry['cse'] = d['bridgeSessionId']
        elif t == 'custom-title' and isinstance(d.get('customTitle'), str) and d['customTitle'].strip():
            entry['title'] = d['customTitle'].strip()[:200]
        elif t == 'ai-title' and isinstance(d.get('aiTitle'), str) and d['aiTitle'].strip():
            entry['ai'] = d['aiTitle'].strip()[:200]
        elif t == 'agent-name' and isinstance(d.get('agentName'), str) and d['agentName'].strip():
            entry['aname'] = d['agentName'].strip()[:200]


def head_of(path):
    try:
        with open(path, 'rb') as f:
            return f.read(64).hex()
    except OSError:
        return ''


def record_files():
    """(path, project folder, session id, agent name or None) for each record changed in the kept days."""
    out = []
    cut = time.time() - KEEP_DAYS * 86400
    try:
        projects = os.listdir(PROJECTS)
    except OSError:
        return out
    for proj in projects:
        pdir = os.path.join(PROJECTS, proj)
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for n in names:
            p = os.path.join(pdir, n)
            if n.endswith('.jsonl'):
                out.append((p, proj, n[:-6], None))
            elif re.match(UUID + '$', n):
                sub = os.path.join(p, 'subagents')
                try:
                    agents = os.listdir(sub)
                except OSError:
                    continue
                for a in agents:
                    if a.endswith('.jsonl'):
                        out.append((os.path.join(sub, a), proj, n, a[:-6]))
    kept = []
    for x in out:
        try:
            st = os.stat(x[0])
        except OSError:
            continue
        if st.st_mtime >= cut:
            kept.append(x + (st,))
    return kept


def scan(cache):
    """Brings the cache up to date with the records on disk; returns (files, files read, bytes read)."""
    files = cache.setdefault('files', {})
    holds = read_holds(cache)
    seen, read, nbytes = set(), 0, 0
    cut = time.time() - KEEP_DAYS * 86400
    for path, proj, sid, agent, st in record_files():
        seen.add(path)
        e = files.get(path)
        if e and e['size'] == st.st_size and e['mtime'] == st.st_mtime and e['ino'] == st.st_ino:
            continue
        start = 0
        if e and e['ino'] == st.st_ino and st.st_size >= e['off'] and e['off'] > 0 and e['head'] == head_of(path):
            start = e['off']   # the same file, longer: read only what was added
        else:
            e = {'proj': proj, 'sid': sid, 'agent': agent, 'birth': getattr(st, 'st_birthtime', st.st_mtime),
                 'head': '', 'off': 0, 'm': {}, 'a': {}, 'st': {}}
            files[path] = e
        try:
            got = read_lines(path, e, start, holds.get(hold_key(e), ()))
        except OSError:
            continue
        close_reply(e)   # the reply being read counts now; its tools that finish later are added to it
        tu = e['st'].get('tu') or {}
        for k in [k for k, v in tu.items() if v[0] < time.time() - 9 * 86400]:
            del tu[k]   # a tool call that never got a result (the turn was stopped); a hold lasts 8 days at most
        for k in [k for k, v in e['a'].items() if v[0] < cut]:
            del e['a'][k]
        e.update(size=st.st_size, mtime=st.st_mtime, ino=st.st_ino, off=start + got)
        if not e['head']:
            e['head'] = head_of(path)
        read += 1
        nbytes += got
    for gone in set(files) - seen:
        files.pop(gone)
    return len(seen), read, nbytes


# ---------- whose use it is ----------

def kit_names():
    """(names by link, link by session id, links in the Claude app's list) from the Kit's state and archived list.
    The Claude app's own title wins: it is the name the person sees."""
    def load(name):
        try:
            with open(os.path.join(KIT, name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    s, arch = load('state.json'), load('archived.json')
    names, link_of = {}, {}
    stem = lambda p: os.path.splitext(os.path.basename(p))[0] if isinstance(p, str) and p else None

    def note(cse, title, transcript):
        if not isinstance(cse, str) or not cse:
            return
        if isinstance(title, str) and title.strip():
            names[cse] = title.strip()
        sid = stem(transcript)
        if sid:
            link_of.setdefault(sid, cse)

    for x in arch.get('items') or []:
        note(x.get('cse'), x.get('title'), x.get('transcript'))
    for w in (s.get('waits') or {}).values() if isinstance(s.get('waits'), dict) else []:
        note(w.get('cse'), w.get('title'), w.get('transcript'))
    for cse, x in ((s.get('keep') or {}).get('alone') or {}).items():
        note(cse, x.get('title'), x.get('transcript'))
    for cse, x in (s.get('sessions') or {}).items():
        note(cse, x.get('title'), x.get('transcript'))
    for x in (s.get('app_list') or {}).get('sessions') or []:
        note(x.get('id'), x.get('title'), None)
    return names, link_of


def group(e, link_of, main_of, runs):
    """(key, kind, part) of one record: part is 'own' or 'agents'. kind is session (it has a Remote Control link),
    local (no link), runs (many unnamed sessions of one folder with no link, one row), kit or temp."""
    proj, sid = e['proj'], e['sid']
    part = 'agents' if e['agent'] else 'own'
    main = main_of.get(sid) if e['agent'] else e
    cse = (main or {}).get('cse') or link_of.get(sid)
    if cse:
        return 'cse:' + cse, 'session', part
    m = SCRATCH.search(proj)
    if m and m.group(1) != sid:
        # a run started in another session's scratchpad folder: one of that session's agents
        parent = m.group(1)
        pcse = (main_of.get(parent) or {}).get('cse') or link_of.get(parent)
        return ('cse:' + pcse, 'session', 'agents') if pcse else ('sid:' + parent, 'local', 'agents')
    if KIT_FOLDER in proj:
        return 'kit', 'kit', part
    if TEMP.match(proj):
        return 'temp', 'temp', part
    if sid in runs:
        return 'runs:' + runs[sid], 'runs', part
    return 'sid:' + sid, 'local', part


def titled(e):
    return e.get('title') or e.get('ai') or e.get('aname')


def build(cache):
    """by-session.json from the cache."""
    files = cache['files']
    names, link_of = kit_names()
    main_of = {e['sid']: e for e in files.values() if not e['agent']}
    # each reply once: the copy in a session's own record, then the oldest file
    owner = {}
    for path, e in files.items():
        rank = (1 if e['agent'] else 0, e['birth'], path)
        for mids in (e['m'], e.get('a') or {}):
            for mid in mids:
                o = owner.get(mid)
                if o is None or rank < o[0]:
                    owner[mid] = (rank, path)
    # sessions with no link and no name, many in one folder (another app's runs, say): one row for the folder
    unnamed = {}
    for e in files.values():
        if not e['agent'] and not e.get('cse') and not link_of.get(e['sid']) and not titled(e) and e['m'] \
                and not SCRATCH.search(e['proj']) and KIT_FOLDER not in e['proj'] and not TEMP.match(e['proj']):
            unnamed.setdefault(e.get('folder') or e['proj'].rsplit('-', 1)[-1] or 'a folder', []).append(e['sid'])
    runs = {sid: folder for folder, sids in unnamed.items() if len(sids) > RUNS for sid in sids}
    keys, sessions = {}, []
    days, models = {}, {}
    rows, agents, unpriced, last, titles = {}, {}, {}, {}, {}
    units = {}   # session -> {(record, turn): [active seconds, {sign: weight}, {day: seconds}]}
    cut = time.time() - KEEP_DAYS * 86400
    for path, e in files.items():
        key, kind, part = group(e, link_of, main_of, runs)
        if not e['agent'] and titled(e) and (key not in titles or e['mtime'] > titles[key][0]):
            titles[key] = (e['mtime'], titled(e))
        s, first = None, None
        for mid, r in e['m'].items():
            if owner[mid][1] != path or r[0] < cut:
                continue
            if s is None:
                if key not in keys:
                    keys[key] = len(sessions)
                    sessions.append({'key': key, 'kind': kind})
                s = keys[key]
            d = days.setdefault(time.strftime('%Y-%m-%d', time.localtime(r[0])), len(days))
            m = models.setdefault(r[1], len(models))
            if not price_of(r[1])[1]:
                unpriced[r[1]] = unpriced.get(r[1], 0) + sum(r[2:7])
            usd, tok = value(r), sum(r[2:7])
            a = rows.setdefault((s, d, m), [0.0, 0.0, 0, 0])
            if part == 'agents' or r[9]:
                a[1] += usd
                a[3] += tok
            else:
                a[0] += usd
                a[2] += tok
            last[s] = max(last.get(s, 0), r[0])
            first = r[0] if first is None else min(first, r[0])
        if first is not None and part == 'agents':
            d = days[time.strftime('%Y-%m-%d', time.localtime(first))]
            agents[(s, d)] = agents.get((s, d), 0) + 1
        for mid, (t0, secs, turn, sig) in (e.get('a') or {}).items():
            if secs <= 0 or t0 < cut or owner[mid][1] != path:
                continue
            if key not in keys:
                keys[key] = len(sessions)
                sessions.append({'key': key, 'kind': kind})
            u = units.setdefault(keys[key], {}).setdefault((path, 0 if e['agent'] else turn), [0.0, {}, {}])
            u[0] += secs
            for k, n in re.findall(r'([A-Za-z])(\d+)', sig):
                u[1][k] = u[1].get(k, 0) + int(n)
            d = days.setdefault(time.strftime('%Y-%m-%d', time.localtime(t0)), len(days))
            u[2][d] = u[2].get(d, 0.0) + secs
            last[keys[key]] = max(last.get(keys[key], 0), t0)
    # the days, from the oldest one with use to today, in this Mac's time zone
    today = time.strftime('%Y-%m-%d')
    span = []
    if days:
        t = calendar.timegm(time.strptime(min(days), '%Y-%m-%d'))
        while len(span) <= KEEP_DAYS + 2:
            day = time.strftime('%Y-%m-%d', time.gmtime(t))
            span.append(day)
            if day >= today:
                break
            t += 86400
    at = {day: i for i, day in enumerate(span)}
    remap = {old: at.get(day, -1) for day, old in days.items()}
    for x in sessions:
        k = x['key']
        x['last'] = round(last.get(keys[k], 0))
        x['cse'] = k[4:] if k.startswith('cse:') else None
        own = (titles.get(k) or (0, ''))[1]
        if x['cse']:
            x['title'] = names.get(x['cse']) or own or 'Session ' + x['cse'][-6:]
        elif k.startswith('sid:'):
            x['title'] = own or 'Unnamed session'
        elif k.startswith('runs:'):
            x['title'] = 'Runs with no name in ' + k[5:]
        elif k == 'kit':
            x['title'] = 'Sttark Claude Kit checks'
        else:
            x['title'] = 'Runs in temporary folders'
    work = kinds_of_work(cache, units, sessions)
    return {
        'v': 1,
        'at': time.time(),
        'keep_days': KEEP_DAYS,
        'days': span,
        'models': [{'id': m, 'name': model_name(m), 'priced': price_of(m)[1]} for m in sorted(models, key=models.get)],
        'sessions': sessions,
        # [session, day, model, own dollars, agents' dollars, own tokens, agents' tokens]
        'rows': [[s, remap[d], m, round(v[0], 6), round(v[1], 6), v[2], v[3]] for (s, d, m), v in sorted(rows.items()) if remap[d] >= 0],
        # [session, day, agents started that day]
        'agents': [[s, remap[d], n] for (s, d), n in sorted(agents.items()) if remap[d] >= 0],
        'unpriced': unpriced,
        # the kinds of work and their factors: human hours for each hour Claude was at work
        'kinds': [{'id': k, 'name': n, 'x': x} for k, n, x in WORK],
        # [session, day, kind, seconds Claude was at work]
        'work': [[s, remap[d], k, round(v)] for (s, d, k), v in sorted(work.items()) if remap[d] >= 0 and v >= 1],
    }


# ---------- the kind of work ----------

def unit_kind(sg):
    """The kind of one unit of work (an agent's record, or one turn of a session's own record) from its signs, or None
    when they do not say. Tests, builds and pull requests make it software, even with browser checks or drawings in
    it; else the browser and office tools make it admin, and CAD, drawing scripts and images design."""
    if sg.get('S', 0) >= 3:
        return 'software'
    a, big, small = sg.get('A', 0), sg.get('D', 0), sg.get('d', 0)
    if a >= 2 and a >= big:
        return 'admin'
    if big + small >= 3:
        return 'design'
    if sg.get('s', 0) >= 3:
        return 'software'
    return None


def kinds_of_work(cache, units, sessions):
    """{(session, day, kind): active seconds}. Each unit counts as its own kind. A unit whose signs do not say takes its
    session's main kind, the one with at least half of its active time. With no main kind, a session under an hour is
    small; for a longer one, one Haiku call names its kind (kept until it gains another hour of work), else small."""
    idx = {k: i for i, (k, _, _) in enumerate(WORK)}
    asked = cache.setdefault('kinds', {})
    out, asks = {}, 0
    for s, us in units.items():
        total = sum(u[0] for u in us.values())
        kinds = {unit: unit_kind(u[1]) for unit, u in us.items()}
        by = {}
        for unit, u in us.items():
            if kinds[unit]:
                by[kinds[unit]] = by.get(kinds[unit], 0) + u[0]
        main = max(by, key=by.get) if by else None
        if main and by[main] < total / 2:
            main = None
        if not main and total >= SMALL:
            key = sessions[s]['key']
            a = asked.get(key)
            if a and total < a[1] + SMALL and (a[0] or a[2] > time.time() - 6 * 3600):
                main = a[0] if a[0] in idx and a[0] != 'small' else None
            elif asks < 1:
                asks += 1
                k = ask_kind(sessions[s], [unit[0] for unit in us])
                asked[key] = [k, round(total), round(time.time())]
                main = k if k in idx and k != 'small' else None
        for unit, u in us.items():
            k = idx[kinds[unit] or main or 'small']
            for d, v in u[2].items():
                out[(s, d, k)] = out.get((s, d, k), 0.0) + v
    for key in [k for k, a in asked.items() if a[2] < time.time() - KEEP_DAYS * 86400]:
        del asked[key]
    return out


KIND_ASK = ('You sort one Claude Code session by the kind of work it did, for an estimate of how long the same work '
            'takes people. Reply with one word: software (it writes, tests and ships code), design (CAD, drawings, '
            'renders, 3D models, plans), admin (browser work, forms, orders, email, office tools), or mixed.')


def limit_reached():
    """True while the 5-hour or a weekly usage limit is at 100% (the Kit's last read of it)."""
    try:
        with open(os.path.join(KIT, 'usage.json')) as f:
            u = json.load(f).get('usage') or {}
    except (OSError, ValueError, AttributeError):
        return False
    return any(isinstance(v, dict) and isinstance(v.get('utilization'), (int, float)) and v['utilization'] >= 100
               for v in u.values())


def ask_kind(session, paths):
    """Haiku's word for the kind of a session whose tool calls leave it unclear: 'software', 'design', 'admin', 'small'
    (mixed), or None when the call fails or a usage limit is reached. It gets a short account of the tool calls: the
    session's name, how often it used each tool, the kinds of files it changed and the first word of its commands.
    Never a prompt, a reply, a path or a file's content."""
    if limit_reached():
        return None
    tools, exts, cmds = {}, {}, {}
    for p in paths:
        try:
            f = open(p, 'rb')
        except OSError:
            continue
        with f:
            for line in f:
                if b'"tool_use"' not in line or b'"assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                m = d.get('message') if isinstance(d, dict) and isinstance(d.get('message'), dict) else {}
                for b in m.get('content') if isinstance(m.get('content'), list) else []:
                    if not isinstance(b, dict) or b.get('type') != 'tool_use':
                        continue
                    n = str(b.get('name') or '')[:60]
                    tools[n] = tools.get(n, 0) + 1
                    i = b.get('input') if isinstance(b.get('input'), dict) else {}
                    fp = i.get('file_path')
                    if n in ('Edit', 'Write', 'MultiEdit') and isinstance(fp, str) and os.path.splitext(fp)[1]:
                        x = os.path.splitext(fp)[1].lower()[:10]
                        exts[x] = exts.get(x, 0) + 1
                    if isinstance(i.get('command'), str):
                        for part in re.split(r'&&|;|\|\||\n', i['command']):
                            w = os.path.basename(part.strip().split(' ', 1)[0])
                            if re.match(r'^[A-Za-z][\w.+-]{0,39}$', w) and w not in ('cd', 'echo', 'export', 'then', 'fi', 'do', 'done'):
                                cmds[w] = cmds.get(w, 0) + 1
    top = lambda c: ', '.join('%s %d' % kv for kv in sorted(c.items(), key=lambda kv: -kv[1])[:15]) or 'none'
    text = ('Session name: %s\nTool calls: %s\nFiles it changed, by type: %s\nCommands it ran: %s'
            % ((session.get('title') or 'unnamed')[:120], top(tools), top(exts), top(cmds)))
    stub = os.environ.get('STTARK_USAGE_KIND')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    cmd = [stub, text] if stub else [CLAUDE, '-p', '--model', 'haiku', '--effort', 'low', '--no-session-persistence',
                                     '--strict-mcp-config', '--tools', '', '--settings', '{"disableAllHooks":true}',
                                     '--system-prompt', KIND_ASK, text]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45, env=env, cwd='/tmp')
    except (OSError, subprocess.SubprocessError) as e:
        log('kind of "%s": the Haiku call failed: %s' % ((session.get('title') or '')[:60], str(e)[:120]))
        return None
    words = re.findall(r'[a-z]+', (r.stdout or '').lower())
    k = {'software': 'software', 'design': 'design', 'admin': 'admin', 'mixed': 'small'}.get(words[0] if words else '')
    log('kind of "%s": %s (Haiku)' % ((session.get('title') or '')[:60], k or 'no answer: ' + (r.stdout or r.stderr or '')[:80].strip()))
    return k


def write_json(path, data, compact=False):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, separators=(',', ':') if compact else None)
    os.replace(tmp, path)


def load_cache():
    try:
        with open(CACHE) as f:
            c = json.load(f)
        if c.get('v') == VERSION and c.get('keep') == KEEP_DAYS:
            return c
    except (OSError, ValueError):
        pass
    return {'v': VERSION, 'keep': KEEP_DAYS, 'files': {}}


def run():
    t0 = time.time()
    os.makedirs(DIR, exist_ok=True)
    with open(LOCK, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)   # one scan at a time; a second caller then finds a fresh result
        cache = load_cache()
        first = not cache['files']
        n, read, nbytes = scan(cache)
        out = build(cache)
        out['scan'] = {'files': n, 'read': read, 'bytes': nbytes, 'seconds': round(time.time() - t0, 2)}
        told = cache.setdefault('told', {})
        for m in sorted(out['unpriced']):
            if told.get(m) != time.strftime('%F'):   # once a day for each model
                log("no price for %s in usage-scan.py's PRICES: it counts at its family's price" % m)
                told[m] = time.strftime('%F')
                read += 1
        if read or not os.path.exists(CACHE):
            write_json(CACHE, cache, compact=True)
        write_json(OUT, out, compact=True)
    if first:
        log('first scan: %d records, %.0f MB, %.1f s' % (n, nbytes / 1e6, time.time() - t0))
    print('%d records, %d read (%d bytes), %d sessions, %.2f s' % (n, out['scan']['read'], nbytes, len(out['sessions']), time.time() - t0))
    return out


def prices():
    """Each model in the kept data, its tokens, and whether PRICES has it. Exit 1 when one with tokens has none."""
    out = run()
    tok = {}
    for r in out['rows']:
        m = out['models'][r[2]]
        tok[m['id']] = tok.get(m['id'], 0) + r[5] + r[6]
    missing = [m['id'] for m in out['models'] if not m['priced'] and tok.get(m['id'], 0) > 0]
    for m in out['models']:
        print('%-28s %16d tokens  %s' % (m['id'], tok.get(m['id'], 0), 'priced' if m['priced'] else 'NO PRICE'))
    if missing:
        print('no price for: ' + ', '.join(missing))
        sys.exit(1)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['--prices']:
        prices()
    elif a[:1] == ['--if-older']:
        try:
            with open(OUT) as f:
                at = json.load(f).get('at', 0)
        except (OSError, ValueError):
            at = 0
        if time.time() - at > float(a[1] if len(a) > 1 else 60):
            run()
    else:
        run()
