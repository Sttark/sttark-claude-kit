#!/usr/bin/python3
"""Progress check-ins: while a session's work runs a long time (an agent of it still works in the background, or its
own turn still runs), the Kit sends the person one short note every 15 minutes, the way they picked under Reach me
by. wait.py --check runs it every minute, after the waits and the reply watch; there is nothing to start.

What runs, with no model call: each agent of the session that Claude Code has not marked finished (effort-hook.py
running_agents(), the same count as the window's Claude working group: not a foreground agent, and one quiet for 15
minutes only while it waits on a background task of its own), and the session's own turn, as the Kit's minute check
of the session (effort-hook.py track()) or the Claude app's list last saw it. Each piece of work starts at its agent's
first line or at the turn's prompt (turn_at).

When: once the oldest piece of work has run EVERY (15 minutes), and then once each EVERY while any of the session's
work still runs: one message a session, for all its agents. Shorter work gets none, and none comes when the work
ends, since the session tells the person itself.

What: one Haiku call (MODEL, through Claude Code with no tools and hooks off, as the Kit's other side calls) reads
only what the session's record and its agents' records gained since the last check-in (the first one: since each
piece of work started) and writes 2 or 3 short sentences: what got done, what it does next, and what it is stuck on.
The subject is the session's name, the oldest agent's description and how long the work has run; the message
links to the session. No check-in while the session holds at its usage limit. When the call fails, the
message gives what the records show (the steps, and how many failed) instead.

How it goes out: notify.py send(), the ways claude-notify uses, less the Claude app, which only a session can send. A
check-in is not the session's own message: it is not noted in reach_sent (a Needs you reminder still comes), and its
log line starts "checkin", not "notify".

The switch: "checkins" in the state file, false when the person turns Progress check-ins off in Settings (the app
writes it). checkins.json in the Kit's folder keeps, per session, when the last check-in went and where it stopped
reading each record; a session leaves it when its work ends.

    checkin.py --check      the minute check (wait.py --check runs it)
    checkin.py --list       the work that runs now in each session, and when its next check-in is due

Logged with lines starting "checkin". STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and log;
STTARK_CHECKIN_DRY=1 (or STTARK_WAIT_DRY, or STTARK_NOTIFY_DRY) writes each message and prints it, and sends nothing;
with only STTARK_WAIT_DRY or STTARK_NOTIFY_DRY (another part's test run) the note is the step count, with no model call;
STTARK_CHECKIN_MODEL is a command that stands in for the Haiku call (tests): the work on its input, the note on its
output.
"""
import calendar, fcntl, importlib.util, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(KIT, 'state.json')
FILE = os.path.join(KIT, 'checkins.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
DRY = any(os.environ.get(k) for k in ('STTARK_CHECKIN_DRY', 'STTARK_WAIT_DRY', 'STTARK_NOTIFY_DRY'))
STUB = os.environ.get('STTARK_CHECKIN_MODEL', '')
# a test run of another part (a wait's or a message's) makes no model call here: only a check-in's own dry run does
NO_MODEL = bool(os.environ.get('STTARK_WAIT_DRY') or os.environ.get('STTARK_NOTIFY_DRY')) and not os.environ.get('STTARK_CHECKIN_DRY')
EVERY = 900            # seconds: the first check-in at this much work, then one each this long while it runs
ACTIVE = 86400         # a session with no prompt or step of its own for this long is not looked at
FRESH = 180            # the minute check's view of a session's turn counts while it is this new
MODEL = 'claude-haiku-5-5'
TIMEOUT = 60           # seconds the summary may take
DIGEST = 9000          # characters of work the summary reads at most: the start of each part, and its newest steps
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

def new_entries(path, off, since, tail=TAIL):
    """The entries a record gained: from byte `off`, or with no place yet, those from `since` on, read back from the
    end (at most `tail` bytes). A line still being written waits for the next time. (entries, the new place)."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], off or 0
    if off is not None and (size < off or size - off > tail):
        off = None  # written again from the start, or grown more than a summary reads: its newest part, from `since`
    start = off if off is not None else max(0, size - tail)
    try:
        with open(path, 'rb') as f:
            f.seek(start)
            data = f.read(size - start)
    except OSError:
        return [], off or 0
    end = data.rfind(b'\n') + 1
    lines = data[:end].split(b'\n')
    if off is None and start > 0:
        lines = lines[1:]  # the first may start partway through a line
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
    return out, start + end


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


def plain(parts, first):
    """The note with no model: what the records show."""
    steps = sum(p['steps'] for p in parts)
    failed = sum(p['failed'] for p in parts)
    when = 'since it started' if first else 'in the last %d min' % (EVERY // 60)
    if not steps:
        last = next((p['last'] for p in parts if p.get('last')), '')
        return 'It made no new steps %s.%s' % (when, (' Its last step: ' + last + '.') if last else '')
    return 'It made %d step%s %s%s.' % (steps, '' if steps == 1 else 's', when,
                                        ', and %d of them failed' % failed if failed > 1 or (failed and steps > 1)
                                        else ', and it failed' if failed else '')


def subject(work, age):
    """"Build the SDS pages, working 45 min"; "... and 1 more agent, ..."; "Working 45 min" for a turn alone."""
    agents = [w for w in work if w['kind'] == 'agent']
    if not agents:
        return 'Working %s' % words(age)
    s = agents[0]['what'] or 'An agent'
    if len(agents) > 1:
        s += ' and %d more agent%s' % (len(agents) - 1, '' if len(agents) == 2 else 's')
    return '%s, working %s' % (s, words(age))


def parts_of(c, work, title, now):
    """Each piece of work and what it did since the last check-in, with the place each record was read to. Agents
    that finished since the last check-in come too: what they did is part of the work."""
    files, out = c.setdefault('files', {}), []
    first = not c.get('sent')
    seen = set()
    for w in work:
        p = w['path']
        if p in seen:
            continue
        seen.add(p)
        since = w['start'] if first or p not in files else c['sent']
        entries, end = new_entries(p, files.get(p), since)
        lines, steps, failed, _ = digest(entries)
        part = {'path': p, 'end': end, 'lines': lines, 'steps': steps, 'failed': failed}
        if w['kind'] == 'agent':
            part['head'] = 'Agent "%s", at work for %s:' % (w['what'] or 'unnamed', words(now - w['start']))
            part['task'] = brief(p)
        else:
            part['head'] = 'The session itself, its turn at work for %s:' % words(now - w['start'])
        if not steps:
            part['last'] = last_step(p)
        out.append(part)
    for p, off in list(files.items()):
        if p in seen or not p.endswith('.jsonl') or '/subagents/' not in p:
            continue
        entries, end = new_entries(p, off, c.get('sent') or 0)
        lines, steps, failed, _ = digest(entries)
        meta = read_json(p[:-len('.jsonl')] + '.meta.json')
        if lines:
            out.append({'path': p, 'end': end, 'lines': lines, 'steps': steps, 'failed': failed,
                        'head': 'Agent "%s", finished since the last note:' % (meta.get('description') or 'unnamed'),
                        'done': True})
        files.pop(p, None)
    return out


def model_input(title, age, parts, first):
    budget = max(1500, DIGEST // max(1, len(parts)))
    lines = ['Session: %s' % title,
             'It has worked %s. This note covers %s.' % (words(age), 'the time since it started' if first
                                                        else 'the last %d min' % (EVERY // 60)), '']
    for p in parts:
        lines.append(p['head'])
        if p.get('task'):
            lines.append('Its task: ' + p['task'])
        if p['lines']:
            lines.append('What it did (%d steps, %d failed):' % (p['steps'], p['failed']))
            lines += squeeze(p['lines'], budget)
        else:
            lines.append('No new steps.' + (' Its last step: %s.' % p['last'] if p.get('last') else ''))
        lines.append('')
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


def run(now=None):
    now = now or time.time()
    st = read_json(STATE)
    C = read_json(FILE)
    runs = C.setdefault('sessions', {})
    if not on(st):
        if runs:
            save({'sessions': {}})
        return
    e = load('effort-hook')
    found = {}

    def tasks():
        if 'tasks' not in found:
            found['tasks'] = e.open_tasks()
        return found['tasks']
    changed, looked = False, set()
    for cse, x in candidates(st, now):
        looked.add(cse)
        try:
            work = work_of(e, cse, x, st, now, tasks)
        except Exception as w:
            log('%s could not read its work: %s: %s' % (cse, type(w).__name__, str(w)[:160]))
            continue
        # the name, in quotes in the log lines (the Events page finds the session by it)
        title = (x.get('title') or (x.get('app') or {}).get('title') or 'Session ' + cse[-6:]).strip().replace('"', "'")
        c = runs.get(cse)
        if not work:
            if c is not None:  # the work ended: no message, the session tells the person itself
                if c.get('n'):
                    log('%s "%s" work ended after %s; %d check-in%s sent' % (
                        cse, title, words(now - c.get('start', now)), c['n'], '' if c['n'] == 1 else 's'))
                runs.pop(cse)
                changed = True
            continue
        if c is None:
            c = runs[cse] = {'start': work[0]['start'], 'sent': 0, 'n': 0, 'files': {}}
            changed = True
        c['start'] = min(c['start'], work[0]['start'])
        age = now - work[0]['start']
        if age < EVERY or now - c['sent'] < EVERY:
            continue
        changed = True
        try:
            if send(c, cse, x, st, title, work, age, now):
                continue
        except Exception as w:
            log('%s "%s" error: %s: %s' % (cse, title, type(w).__name__, str(w)[:200]))
            c['sent'] = now  # tried: the next one in EVERY, not each minute
    for cse in [k for k in runs if k not in looked]:  # archived, quiet for a day, or gone from the state file
        runs.pop(cse)
        changed = True
    if changed:
        save(C)


def send(c, cse, x, st, title, work, age, now):
    """One check-in for the session. Returns True when it was not due after all (a hold, or no way to send)."""
    n = load('notify')
    if DRY:
        n.DRY = True
    ways = ways_for(n, st)
    if not ways:
        picked = n.settings(st)['ways']
        once(c, 'app' if picked else 'none', '%s "%s" not sent: %s' % (
            cse, title, 'Reach me by has only the Claude app, which only a session can send' if picked
            else 'no way is checked under Reach me by'))
        return True
    tp = x.get('transcript') or ''
    try:
        held = load('limit-hook').held(os.path.basename(tp)[:-len('.jsonl')], tp, cse)
    except Exception:
        held = False
    if held:  # its work waits, and a summary would spend usage at the limit
        once(c, 'held', '%s "%s" skipped: it holds at the usage limit' % (cse, title))
        return True
    c.pop('said', None)
    first = not c.get('sent')
    parts = parts_of(c, work, title, now)
    subj = subject(work, age)
    why = ''
    if any(p['lines'] for p in parts):
        try:
            body = summary(model_input(title, age, parts, first))
        except Exception as w:
            why = one_line(str(w), 120) or type(w).__name__
            body = plain(parts, first)
    else:
        body = plain(parts, first)  # nothing new to read: no model call
    url = x.get('url') or (x.get('app') or {}).get('url') or ''
    # the subject starts with the session's name in every way (Google Chat and a text show only the subject first);
    # the log line, under the session's name already, keeps the rest
    res = n.send('%s: %s' % (title, subj), body, ways=ways, title=title, url=url, cse=cse, quiet=True)
    for p in parts:
        if not p.get('done'):
            c['files'][p['path']] = p['end']
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
    return False


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
        c = runs.get(cse) or {}
        age = now - work[0]['start']
        due = max(work[0]['start'] + EVERY, (c.get('sent') or 0) + EVERY)
        print('%s (%s): working %s; %s' % (x.get('title') or cse, cse, words(age),
                                         'next check-in in %s' % words(due - now) if due > now else 'a check-in is due now'))
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
