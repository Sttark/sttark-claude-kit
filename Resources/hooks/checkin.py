#!/usr/bin/python3
"""Progress check-ins: while a session's work runs a long time (an agent of it still works in the background, or its
own turn still runs), the Kit sends the person one short note every 15 minutes, the way they picked under Reach me
by. wait.py --check starts it every minute, after the waits and the reply watch; there is nothing else to start.

What runs, with no model call: each agent of the session that Claude Code has not marked finished (effort-hook.py
running_agents(), the same count as the window's Claude working group: not a foreground agent unless its turn runs,
and one quiet for 15 minutes only while it waits on a background task of its own), and the session's own turn, as the
Kit's minute check of the session (effort-hook.py track()) or the Claude app's list last saw it.

A run of work: from when the check first sees work in the session until it sees none for GAP (5 minutes), so a minute
the check missed (a late read of the session, a hold) does not end it. It starts at the oldest piece of work when the
check sees the session for the first time (the Kit just came on), else when the check sees the work.

When: one message a session, for all its work, once the person has heard nothing for EVERY (15 minutes) while the
run goes on: EVERY after the later of the run's start, the person's last prompt in the session (asked_at, from the
effort hook) and the last check-in. A turn alone counts only after it has run TURN_MIN, so the short turn in which
the session reports its agents' results brings no note. None for shorter work, and none when the work ends: the
session tells the person itself.

What: one Haiku call (MODEL, through Claude Code with no tools and hooks off, as the Kit's other side calls) reads
only what the session's record and its agents' records gained since the last check-in (the first one: since the run
started), the agents that ran between two check-ins too, and writes 2 or 3 short sentences: what got done, what it
does next, and what it is stuck on. The subject is the session's name, the oldest agent's description and how long
the run has gone on; the message links to the session. No check-in while the session holds at its usage limit. With
no new step, no call; when the call fails, the note gives the steps and how many failed.

How it goes out: notify.py send(), the ways claude-notify uses, less the Claude app, which only a session can send. A
check-in is not the session's own message: it is not noted in reach_sent (a Needs you reminder still comes), and its
log line starts "checkin", not "notify".

The switch: "checkins" in the state file, false when the person turns Progress check-ins off in Settings (the app
writes it). checkins.json in the Kit's folder keeps, per session in the last day, its run, its last check-in and where
it stopped reading each record.

    checkin.py --check      the minute check (wait.py --check starts it in a process of its own)
    checkin.py --list       the work that runs now in each session, and when its next check-in is due

Logged with lines starting "checkin". A test never sends and never calls the model: STTARK_KIT_DIR (a test folder)
or STTARK_CHECKIN_DRY, STTARK_WAIT_DRY or STTARK_NOTIFY_DRY writes each message, prints it and sends nothing, in this
process, and saves nothing; only STTARK_CHECKIN_DRY calls the model then (a dry run on real records).
STTARK_CHECKIN_MODEL is a command that stands in for the Haiku call: the work on its input, the note on its output.
STTARK_KIT_LOG points the log at a test file.
"""
import calendar, fcntl, importlib.util, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(KIT, 'state.json')
FILE = os.path.join(KIT, 'checkins.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
DRY = any(os.environ.get(k) for k in ('STTARK_KIT_DIR', 'STTARK_CHECKIN_DRY', 'STTARK_WAIT_DRY', 'STTARK_NOTIFY_DRY'))
STUB = os.environ.get('STTARK_CHECKIN_MODEL', '')
NO_MODEL = DRY and not os.environ.get('STTARK_CHECKIN_DRY')  # another part's test run: no model call
EVERY = 900            # seconds the person hears nothing while work runs before a check-in
GAP = 300              # seconds with no work that end a run
TURN_MIN = 300         # a turn with no agent counts once it has run this long
ACTIVE = 86400         # a session with no prompt or step of its own for this long is not looked at
FRESH = 180            # the minute check's view of a session's turn counts while it is this new
MODEL = 'claude-haiku-5-5'
TIMEOUT = 60           # seconds the summary may take
DIGEST = 9000          # characters of work the summary reads at most: the start of each part, and its newest steps
PARTS = 8              # pieces of work the summary reads at most, the oldest first
TAIL = 4 * 1024 * 1024  # bytes read back from the end of a record the check-ins have no place in yet
STABLE = os.path.expanduser('~/.local/share/claude/stable/claude')  # the Kit's fixed copy, when the server is on
CLAUDE = STABLE if os.access(STABLE, os.X_OK) else os.path.expanduser('~/.local/bin/claude')

ASK = """You write a short progress note for a person. One of their Claude Code sessions has worked for a long \
time, often through agents that run in the background, and the person has heard nothing. You get what the session \
and its agents did since the last note: the task of each, its steps (the tool calls, and the ones that failed) and \
what it wrote.

Write 2 or 3 short sentences, 50 words at most in all, each with its subject ("It", "The agent"):
1. What got done since the last note, in the person's terms (a page, a test, a pull request, a document, an email), \
not the names of tools. When more than one agent works, say in a few words what each did.
2. What it does next, starting with "Next it".
3. Only when the steps show it: what it is stuck on (the same step fails again and again, it waits on something, it \
goes in circles). Never guess a problem.

Use ASD-STE100 Simplified Technical English: approved words, active voice, simple present or past tense, no words \
that end in -ing as nouns, sentences of 20 words or fewer. No em-dashes, no double hyphens, no lists, no headings, \
no greeting, no file paths, no ids. Write only the note.

Example: It finished the remove button and opened pull request 294, and its checks pass. Next it adds the photo \
upload to the page."""

NOTE = re.compile(r'<(system-reminder|local-command-[a-z-]+|command-[a-z-]+)>.*?</\1>', re.S)


# --- small helpers ----------------------------------------------------------------------------------------------

def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'checkin ' + line + '\n')
    except OSError:
        pass


def read_json(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(C):
    os.makedirs(KIT, exist_ok=True)
    tmp = FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(C, f)
    os.replace(tmp, FILE)


def stamp(ts):
    """A record's timestamp (2026-11-17T21:58:50.694Z, UTC) as a Unix time, or None."""
    try:
        return calendar.timegm(time.strptime(str(ts)[:19], '%Y-%m-%dT%H:%M:%S'))
    except ValueError:
        return None


def words(secs):
    """45 min, 1 hr, 1 hr 30 min."""
    m = max(1, int(round(secs / 60.0)))
    if m < 60:
        return '%d min' % m
    return '%d hr' % (m // 60) + (' %d min' % (m % 60) if m % 60 else '')


def one_line(s, n):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text')
    return ''


# --- what runs ----------------------------------------------------------------------------------------------------

def in_turn(cse, x, st, now):
    """Whether the session's own turn runs now: the Claude app's list when it is newer than the Kit's minute check of
    the session, else that check (as the window's Claude working group decides). Neither counts once it is old."""
    app = x.get('app') or {}
    lst = st.get('app_list') or {}
    item = next((c for c in lst.get('sessions') or [] if c.get('id') == cse), None)
    if item is not None and lst.get('at', 0) > app.get('checked', 0) and now - lst.get('at', 0) < FRESH:
        return item.get('bucket') == 'working'
    return now - app.get('checked', 0) < FRESH and bool(app.get('working'))


def work_of(e, cse, x, st, now, tasks):
    """What the session runs now: [{'kind': 'agent' or 'turn', 'path', 'what', 'start'}], the oldest first. `tasks`
    gives the open background tasks of the Mac, and is called only when an unfinished agent is quiet for long. While
    the turn runs, an agent it waits on (a foreground one) is work too: what it does is what the turn does."""
    tp = x.get('transcript') or ''
    turn = in_turn(cse, x, st, now)
    out = []
    for a in e.running_agents(tp, lambda: tasks().get(os.path.basename(tp)[:-len('.jsonl')], set()), now, foreground=turn):
        out.append({'kind': 'agent', 'path': a['path'], 'what': a['what'], 'start': a['start']})
    if turn:
        out.append({'kind': 'turn', 'path': tp, 'what': '', 'start': min(x.get('turn_at') or now, now)})
    return sorted(out, key=lambda w: w['start'])


def candidates(st, now):
    """The sessions to look at: in the state file with a record, not archived, with a prompt or a step of its own in
    the last day."""
    for cse, x in (st.get('sessions') or {}).items():
        tp = x.get('transcript') or ''
        if not tp.endswith('.jsonl') or (x.get('app') or {}).get('archived'):
            continue
        if max(x.get('at') or 0, x.get('turn_at') or 0) < now - ACTIVE:
            continue
        yield cse, x


# --- what it did ----------------------------------------------------------------------------------------------------

def new_entries(path, place, since, tail=TAIL):
    """The entries a record gained: from `place` ([byte, file id]), or with no place, those from `since` on, read back
    from the end (at most `tail` bytes). With no place also when the file is another one now, shorter (written again)
    or grown more than `tail`. A line still being written waits for the next time. (entries, the new place)."""
    try:
        st = os.stat(path)
    except OSError:
        return [], place
    size, off = st.st_size, None
    if place and len(place) == 2 and place[1] == st.st_ino and place[0] <= size and size - place[0] <= tail:
        off = place[0]
    start = off if off is not None else max(0, size - tail)
    try:
        with open(path, 'rb') as f:
            whole = True
            if off is None and start > 0:  # the first line is whole only when the byte before it ends a line
                f.seek(start - 1)
                whole = f.read(1) == b'\n'
            f.seek(start)
            data = f.read(size - start)
    except OSError:
        return [], place
    end = data.rfind(b'\n') + 1
    lines = data[:end].split(b'\n')
    if not whole:
        lines = lines[1:]
    out = []
    for raw in lines:
        if not raw.strip() or b'"api-request-blob"' in raw[:300]:
            continue
        try:
            x = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(x, dict):
            continue
        if off is None:
            t = stamp(x.get('timestamp'))
            if t is None or t < since - 2:  # a line's time is cut to the second; its file can be a moment younger
                continue
        out.append(x)
    return out, [start + end, st.st_ino]


def step(name, inp):
    """A tool call in a few words, for the summary."""
    inp = inp if isinstance(inp, dict) else {}
    if name == 'Bash':
        return 'ran: ' + one_line(inp.get('description') or inp.get('command') or '', 140)
    if name in ('Read', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        verb = {'Read': 'read', 'Write': 'wrote'}.get(name, 'edited')
        return '%s %s' % (verb, os.path.basename(str(inp.get('file_path') or inp.get('notebook_path') or '')))
    if name in ('Grep', 'Glob'):
        return 'searched the files for ' + one_line(str(inp.get('pattern') or ''), 80)
    if name in ('Agent', 'Task'):
        return 'started an agent: ' + one_line(str(inp.get('description') or ''), 100)
    if name == 'TodoWrite':
        todos = [t for t in inp.get('todos') or [] if isinstance(t, dict)]
        now_ = [str(t.get('activeForm') or t.get('content') or '') for t in todos if t.get('status') == 'in_progress']
        left = [str(t.get('content') or '') for t in todos if t.get('status') == 'pending']
        return 'its to-do list: now %s; next %s' % (one_line('; '.join(now_), 140) or 'nothing',
                                                     one_line('; '.join(left[:4]), 180) or 'nothing')
    if name == 'WebFetch':
        return 'read the page ' + one_line(str(inp.get('url') or ''), 100)
    if name == 'WebSearch':
        return 'searched the web for ' + one_line(str(inp.get('query') or ''), 100)
    short = name.split('__')[-1] if name.startswith('mcp__') else name
    return '%s %s' % (short, one_line(json.dumps(inp, ensure_ascii=False), 100))


def notification(text):
    """A task notification in a few words: which agent or command stopped, and the start of what it said."""
    s = re.search(r'<summary>(.*?)</summary>', text, re.S)
    r = re.search(r'<result>(.*?)</result>', text, re.S)
    return one_line((s.group(1) if s else 'A background task stopped') + (': ' + r.group(1) if r else ''), 300)


def digest(entries):
    """(lines of the work, steps, failed steps, the last step) from a record's new entries."""
    out, steps, failed, calls, last = [], 0, 0, {}, ''
    for x in entries:
        msg = x.get('message') if isinstance(x.get('message'), dict) else {}
        content = msg.get('content')
        if x.get('type') == 'assistant' and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'tool_use':
                    steps += 1
                    last = step(str(b.get('name') or ''), b.get('input'))
                    calls[b.get('id')] = len(out)
                    out.append('- ' + last)
                elif b.get('type') == 'text' and NOTE.sub('', b.get('text') or '').strip():
                    out.append('- It wrote: ' + one_line(NOTE.sub('', b['text']), 400))
        elif x.get('type') == 'user' and not x.get('isMeta'):
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('is_error'):
                        failed += 1
                        why = one_line(text_of(b.get('content')) if isinstance(b.get('content'), list)
                                       else str(b.get('content') or ''), 160)
                        i = calls.get(b.get('tool_use_id'))
                        if i is not None:
                            out[i] += ' (it failed: %s)' % why
                        else:
                            out.append('- A step failed: ' + why)
                    elif isinstance(b, dict) and b.get('type') == 'text' and not x.get('isSidechain'):
                        t = NOTE.sub('', b.get('text') or '').strip()
                        if t:
                            out.append('- A message to it: ' + one_line(t, 300))
            elif isinstance(content, str) and not (x.get('isSidechain') and x.get('parentUuid') is None):
                t = NOTE.sub('', content).strip()  # (an agent's first message is its task, which the summary has)
                if t.startswith('<task-notification>'):
                    out.append('- ' + notification(t))
                elif t:
                    out.append('- A message to it: ' + one_line(t, 300))
    return out, steps, failed, last


def brief(path):
    """An agent's task: the start of the first message in its record."""
    try:
        with open(path, 'rb') as f:
            x = json.loads(f.readline(1 << 20))
        return one_line(NOTE.sub('', text_of((x.get('message') or {}).get('content'))), 600)
    except (OSError, ValueError, AttributeError):
        return ''


def last_step(path):
    """The newest tool call in a record, in a few words: what a quiet agent waits on."""
    entries, _ = new_entries(path, None, 0, tail=256 * 1024)
    for x in reversed(entries):
        msg = x.get('message') if isinstance(x.get('message'), dict) else {}
        for b in reversed(msg.get('content') if isinstance(msg.get('content'), list) else []):
            if isinstance(b, dict) and b.get('type') == 'tool_use':
                return step(str(b.get('name') or ''), b.get('input'))
    return ''


def squeeze(lines, budget):
    """The lines in at most `budget` characters: the first few, then the newest, which say most about what is next."""
    if sum(len(l) + 1 for l in lines) <= budget:
        return lines
    head, tail, used = [], [], 0
    for l in lines:
        if used + len(l) + 1 > budget // 5:
            break
        head.append(l)
        used += len(l) + 1
    for l in reversed(lines[len(head):]):
        if used + len(l) + 1 > budget:
            break
        tail.append(l)
        used += len(l) + 1
    return head + ['- [... %d more steps and notes ...]' % (len(lines) - len(head) - len(tail))] + tail[::-1]


# --- the note -------------------------------------------------------------------------------------------------------

def tidy(text):
    """The note as it goes out: no em-dashes or double hyphens, no list marks, one paragraph, at most 3 sentences."""
    t = re.sub(r'\s*—\s*|\s+(?:--|–)\s+', ', ', text or '')
    t = re.sub(r'(?m)^\s*(?:[-*•]|\d+[.)])\s+', '', t)
    t = re.sub(r'\s+', ' ', t).strip().strip('"').strip()
    parts = re.split(r'(?<=[.!?])\s+', t)
    return ' '.join(parts[:3])[:700].strip()


def summary(text):
    """The note from Haiku (MODEL), or raises with why. No tools, hooks off, run outside the session, as the Kit's
    other side calls; STTARK_CHECKIN_MODEL stands in for it in tests."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    if NO_MODEL and not STUB:
        raise RuntimeError('a test run of another part: no model call')
    cmd = [STUB] if STUB else [CLAUDE, '-p', '--model', MODEL, '--effort', 'low', '--no-session-persistence',
                               '--strict-mcp-config', '--tools', '', '--settings', '{"disableAllHooks":true}',
                               '--system-prompt', ASK]
    r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=TIMEOUT, env=env, cwd='/tmp')
    if r.returncode:
        raise RuntimeError('exit %d: %s' % (r.returncode, one_line(r.stderr or r.stdout, 160)))
    note = tidy(r.stdout)
    if len(note) < 20:
        raise RuntimeError('no usable answer: %s' % one_line(r.stdout, 80))
    return note


def plain(parts, window):
    """The note with no model: what the records show."""
    steps = sum(p['steps'] for p in parts)
    failed = sum(p['failed'] for p in parts)
    if not steps:
        last = next((p['last'] for p in parts if p.get('last')), '')
        return 'It made no new steps %s.%s' % (window, (' Its last step: ' + last + '.') if last else '')
    return 'It made %d step%s %s%s.' % (steps, '' if steps == 1 else 's', window,
                                        ', and %d of them failed' % failed if failed > 1 or (failed and steps > 1)
                                        else ', and it failed' if failed else '')


def subject(work, age):
    """"Build the SDS pages, working 45 min"; "... and 1 more agent, ..."; "Working 45 min" for a turn alone. The
    session's name goes in front of it when it is sent."""
    agents = [w for w in work if w['kind'] == 'agent']
    if not agents:
        return 'Working %s' % words(age)
    s = agents[0]['what'] or 'An agent'
    if len(agents) > 1:
        s += ' and %d more agent%s' % (len(agents) - 1, '' if len(agents) == 2 else 's')
    return '%s, working %s' % (s, words(age))


def parts_of(c, x, work, now):
    """Each piece of work and what it did since the last check-in (the first of a run: since the run started), with
    the place each record was read to. Agents that stopped since the last check-in come too, also one that started
    and stopped between two check-ins: what they did is part of the work."""
    files, out, seen = c.setdefault('files', {}), [], set()
    floor = c['start'] - 120 if not c.get('n') else max(c['start'] - 120, (c.get('sent') or 0) - 120)
    for w in work:
        p = w['path']
        if p in seen:
            continue
        seen.add(p)
        entries, place = new_entries(p, files.get(p), max(w['start'], floor))
        lines, steps, failed, _ = digest(entries)
        part = {'path': p, 'place': place, 'lines': lines, 'steps': steps, 'failed': failed}
        if w['kind'] == 'agent':
            part['head'] = 'Agent "%s", at work for %s:' % (w['what'] or 'unnamed', words(now - max(w['start'], c['start'])))
            part['task'] = brief(p)
        else:
            part['head'] = 'The session itself, its turn at work for %s:' % words(now - w['start'])
        if not steps:
            part['last'] = last_step(p)
        out.append(part)
    tp = x.get('transcript') or ''
    sub = os.path.join(tp[:-len('.jsonl')], 'subagents')
    try:
        names = [n for n in os.listdir(sub) if n.endswith('.jsonl')]
    except OSError:
        names = []
    for n in names:
        p = os.path.join(sub, n)
        if p in seen:
            continue
        try:
            changed = os.path.getmtime(p)
        except OSError:
            continue
        if p not in files and changed < floor:
            continue
        entries, _ = new_entries(p, files.get(p), floor)
        lines, steps, failed, _ = digest(entries)
        files.pop(p, None)
        if lines:
            meta = read_json(p[:-len('.jsonl')] + '.meta.json')
            out.append({'path': p, 'lines': lines, 'steps': steps, 'failed': failed, 'done': True,
                        'head': 'Agent "%s", stopped since the last note:' % (meta.get('description') or 'unnamed')})
    return out


def model_input(title, age, parts, window):
    shown = parts[:PARTS]
    budget = DIGEST // max(1, len(shown))
    lines = ['Session: %s' % title, 'It has worked %s. This note covers %s.' % (words(age), window), '']
    for p in shown:
        lines.append(p['head'])
        if p.get('task'):
            lines.append('Its task: ' + p['task'][:400])
        if p['lines']:
            lines.append('What it did (%d steps, %d failed):' % (p['steps'], p['failed']))
            lines += squeeze(p['lines'], budget)
        else:
            lines.append('No new steps.' + (' Its last step: %s.' % p['last'] if p.get('last') else ''))
        lines.append('')
    if len(parts) > len(shown):
        lines.append('%d more agents work too.' % (len(parts) - len(shown)))
    return '\n'.join(lines)


# --- the minute check -------------------------------------------------------------------------------------------------

def on(st):
    return st.get('checkins', True) is not False


def ways_for(n, st):
    """The ways a check-in goes: the person's Reach me by ways, less the Claude app, which only a session can send."""
    return [w for w in n.settings(st)['ways'] if w in n.WAYS and w != 'push']


def once(c, why, line):
    """Logs a reason not to send once for each run of work."""
    if c.get('said') != why:
        c['said'] = why
        log(line)


def start():
    """From wait.py --check: the check in a process of its own, so its summaries never hold up the next minute's
    waits. A test runs it in this process, so it can read what it prints."""
    if DRY:
        return check()
    subprocess.Popen([sys.executable, os.path.abspath(__file__), '--check'], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, cwd=KIT)


def check(now=None):
    """Every minute, after the waits: one check-in for each session whose work is due."""
    os.makedirs(KIT, exist_ok=True)
    lock = open(os.path.join(KIT, 'checkin.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # the last minute's check still runs (a summary takes a few seconds)
    try:
        run(now)
    except Exception as x:  # never stops the minute check
        log('error: %s: %s' % (type(x).__name__, str(x)[:200]))
    finally:
        lock.close()


def end_run(c):
    """A run of work ended: no message; the record keeps only when the last check-in went."""
    for k in ('start', 'idle', 'n', 'files', 'said'):
        c.pop(k, None)


def run(now=None):
    now = now or time.time()
    st = read_json(STATE)
    if not on(st):
        return  # the records stay, so turning it on again sends no note sooner than one was due
    C = read_json(FILE)
    runs, errors = C.setdefault('sessions', {}), C.setdefault('errors', {})
    e = load('effort-hook')
    found = {}

    def tasks():
        if 'tasks' not in found:
            found['tasks'] = e.open_tasks()
        return found['tasks']
    looked = set()
    for cse, x in candidates(st, now):
        looked.add(cse)
        try:
            work = work_of(e, cse, x, st, now, tasks)
            errors.pop(cse, None)
        except Exception as w:
            why = '%s: %s' % (type(w).__name__, str(w)[:160])
            if errors.get(cse) != why:
                log('%s could not read its work: %s' % (cse, why))
            errors[cse] = why
            continue
        # the name, in quotes in the log lines (the Events page finds the session by it)
        title = (x.get('title') or (x.get('app') or {}).get('title') or 'Session ' + cse[-6:]).strip().replace('"', "'")
        c = runs.get(cse)
        if not work:
            if c and c.get('start'):
                if not c.get('idle'):
                    c['idle'] = now  # a minute with no work: the run goes on unless none comes back for GAP
                elif now - c['idle'] >= GAP:
                    if c.get('n'):
                        log('%s "%s" work ended after %s; %d check-in%s sent' % (
                            cse, title, words(c['idle'] - c['start']), c['n'], '' if c['n'] == 1 else 's'))
                    end_run(c)
            continue
        if c is None:  # seen for the first time: the run started with its oldest piece of work
            c = runs[cse] = {'start': work[0]['start']}
        elif not c.get('start'):  # new work after a run ended: it starts now (an agent that is continued keeps its old birth time)
            c['start'] = min(now, max(work[0]['start'], now - 120))
        c.pop('idle', None)
        if not due(c, x, work, now):
            continue
        try:
            send(c, cse, x, st, title, work, now)
        except Exception as w:
            log('%s "%s" error: %s: %s' % (cse, title, type(w).__name__, str(w)[:200]))
            c['sent'] = now  # tried: the next one in EVERY, not each minute
    for cse in [k for k in runs if k not in looked]:  # archived, quiet for a day, or gone from the state file
        runs.pop(cse)
    for cse in [k for k in errors if k not in looked]:
        errors.pop(cse)
    if not DRY:
        save(C)


def quiet_since(c, x):
    """Since when the person has heard nothing: the later of the run's start, their last prompt in the session and the
    last check-in."""
    return max(c['start'], x.get('asked_at') or 0, c.get('sent') or 0)


def due(c, x, work, now):
    """A check-in is due: the person has heard nothing for EVERY, and the work is an agent, or a turn that has run
    TURN_MIN (not the short turn in which the session reports what its agents did)."""
    if now - quiet_since(c, x) < EVERY:
        return False
    return any(w['kind'] == 'agent' or now - w['start'] >= TURN_MIN for w in work)


def send(c, cse, x, st, title, work, now):
    """One check-in for the session, unless it holds at its usage limit or no way can send one (each logged once
    for each run of work)."""
    n = load('notify')
    if DRY:
        n.DRY = True
    ways = ways_for(n, st)
    if not ways:
        picked = n.settings(st)['ways']
        once(c, 'app' if picked else 'none', '%s "%s" not sent: %s' % (
            cse, title, 'Reach me by has only the Claude app, which only a session can send' if picked
            else 'no way is checked under Reach me by'))
        return
    tp = x.get('transcript') or ''
    try:
        held = load('limit-hook').held(os.path.basename(tp)[:-len('.jsonl')], tp, cse)
    except Exception:
        held = False
    if held:  # its work waits, and a summary would spend usage at the limit
        once(c, 'held', '%s "%s" skipped: it holds at the usage limit' % (cse, title))
        return
    c.pop('said', None)
    age = now - c['start']
    window = ('since it started' if not c.get('n') else 'in the last %s' % words(now - quiet_since(c, x)))
    parts = parts_of(c, x, work, now)
    subj = subject(work, age)
    why = ''
    if any(p['lines'] for p in parts):
        try:
            body = summary(model_input(title, age, parts, window))
        except Exception as w:
            why = one_line(str(w), 120) or type(w).__name__
            body = plain(parts, window)
    else:
        body = plain(parts, window)  # nothing new to read: no model call
    url = x.get('url') or (x.get('app') or {}).get('url') or ''
    # the subject starts with the session's name in every way (Google Chat and a text show only the subject first);
    # the log line, under the session's name already, keeps the rest
    res = n.send('%s: %s' % (title, subj), body, ways=ways, title=title, url=url, cse=cse, quiet=True)
    for p in parts:
        if not p.get('done'):
            c['files'][p['path']] = p['place']
    c['sent'], c['n'] = now, c.get('n', 0) + 1
    # the line: <session> "<name>" <status> | <subject> | <note>; the status is "sent by <ways>", then "; not by <way>
    # (<why>)" and "; no summary (<why>)" when they apply (the Events page reads it this way)
    clean = lambda s: one_line(s, 400).replace(' | ', ' / ').replace('; ', ', ')
    name = lambda w: n.NAMES.get(w, w)
    ok = [name(w) for w, (good, _) in res if good]
    if DRY:
        status = ['would send (dry)']
        print('would send for %s "%s": %s\n%s' % (cse, title, subj, body))
    elif ok:
        status = ['sent by ' + ', '.join(ok)] + ['not by %s (%s)' % (name(w), clean(said)[:160]) for w, (good, said) in res if not good]
    else:
        status = ['not sent (%s)' % ', '.join('%s: %s' % (name(w), clean(said)[:160]) for w, (_, said) in res)]
    if why:
        status.append('no summary (%s)' % clean(why)[:160])
    log('%s "%s" %s | %s | %s' % (cse, title, '; '.join(status), clean(subj), clean(body)))


def listing(now=None):
    """--list: the work that runs now in each session, and when its next check-in is due. Reads only."""
    now = now or time.time()
    st = read_json(STATE)
    runs = read_json(FILE).get('sessions') or {}
    e = load('effort-hook')
    found = {}

    def tasks():
        if 'tasks' not in found:
            found['tasks'] = e.open_tasks()
        return found['tasks']
    print('Progress check-ins are %s.' % ('on' if on(st) else 'off (Settings > Reach me by)'))
    shown = 0
    for cse, x in candidates(st, now):
        work = work_of(e, cse, x, st, now, tasks)
        if not work:
            continue
        shown += 1
        c = dict(runs.get(cse) or {})
        c['start'] = c.get('start') or work[0]['start']
        at = quiet_since(c, x) + EVERY
        print('%s (%s): working %s; %s' % (x.get('title') or cse, cse, words(now - c['start']),
                                         'next check-in in %s' % words(at - now) if at > now else
                                         'a check-in is due now' if due(c, x, work, now) else
                                         'no check-in while only a short turn runs'))
        for w in work:
            print('  - %s, %s' % ('the turn' if w['kind'] == 'turn' else 'agent "%s"' % (w['what'] or 'unnamed'), words(now - w['start'])))
    if not shown:
        print('No session has work that runs now.')


def main():
    args = sys.argv[1:]
    if args == ['--check']:
        check()
        return 0
    if args == ['--list']:
        listing()
        return 0
    print(__doc__.split('\n\n')[-2])
    return 2


if __name__ == '__main__':
    sys.exit(main())
