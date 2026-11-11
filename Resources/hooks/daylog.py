#!/usr/bin/python3
"""The orchestrator's day log and state file: a command (the app links it as `claude-daylog` in ~/.local/bin
while the Orchestrator switch is on) and three Claude Code hooks (`daylog.py --hook`, added by install-hooks.py
only while the switch is on). No model calls. Python 3.9, no third-party imports.

KIT is STTARK_KIT_DIR or ~/Library/Application Support/SttarkClaudeKit.

Day log: KIT/daylog/YYYY-MM-DD.md, one file per local day (it ends at local midnight). Format:

    # Day log 2026-11-09
    asana-synced: no

    ## <repo>
    ### Done
    - 14:32 | Fix label count rounding | bug | PASS | evidence: 48 tests, page-check ok | pr: <url> | asana: none
    ### Kicked back
    - 13:10 | Bin search filter | feature | FAIL | gap: empty query returns all bins | retry: yes
    ### Decisions
    - 14:05 | Label counts round down | why: printer feeds whole labels only | by: you
    ### Dropped
    - 11:40 | Dark mode toggle | why: not needed now | by: you
    ### Open
    - Bulk edit for bins | feature | state: grilling round 2

    ## General  (only when it has a line)

One section per repo (the basename of `git rev-parse --show-toplevel` of the working folder, or the main repo's folder name in a worktree; `General` outside
a repo; General is written last). Subsections come in the order above and exist only when they have a line. A
new day's file starts with the Open items of the most recent earlier file, per repo (missing days are skipped).
Every write takes a lock (`<file>.lock`), because two sessions can write the same day.

Commands (exit 0 with one line; errors go to stderr with exit 1; --repo defaults to the working folder's repo):
  claude-daylog add --repo R --kind done|kicked|decision|dropped --text "<fields after the time>"
  claude-daylog open --repo R --item "<item | kind | state: ...>" [--item ...]    (replaces that repo's Open list)
  claude-daylog path [--create]                    today's file (--create makes it, with carried-forward Open items)
  claude-daylog show [--repo R] [--open]           the file, one repo's section, or only that repo's Open items
                                                   (--open without --repo uses the working folder's repo)
  claude-daylog state-path --repo R                KIT/orchestrator/state/<repo>.md

State file (one per repo, KIT/orchestrator/state/<repo>.md): the orchestrator overwrites it, never appends, with
its Write tool at checkpoints. Template:

    # Orchestrator state: <repo>
    updated: <YYYY-MM-DD HH:MM>
    branch: <branch>
    worktrees: <path (branch), ...  or none>
    running agents: <agent | item | started HH:MM, ...  or none>
    next command: <the next thing to run or start>
    current item: <item | kind | state>

Hooks (`daylog.py --hook`, event from the input; each does nothing while the switch is off):
- SubagentStop (matcher validator): reads the validator's report (last_assistant_message and the
  SubagentHandback message in its transcript) and parses its LAST line
  `VERDICT: PASS|FAIL | <item> | <evidence or gap>`. It adds {item, verdict, evidence, repo, at} to state.json
  daylog_pending[<session>], under the shared lock. No verdict line: logged, nothing else.
- Stop: for this session's pending items, looks in today's file under that repo's Done (PASS) or Kicked back
  (FAIL) for a line whose item field (the first field after the time) matches, ignoring case and spaces. Found:
  dropped from pending. Missing: blocks the turn and gives the claude-daylog command to run. An item blocks at
  most 2 times (stop_hook_active still checks and counts); after that it is logged and dropped. Any error: allow.
- SessionStart (startup, clear, compact, resume): adds the pending questions and findings (capture, see README item 27). Source `clear` also adds this repo's state file and today's Open items.
  With nothing to restore it says nothing.

Logged to ~/Library/Logs/sttark-claude-kit.log, with lines starting `daylog`. STTARK_KIT_DIR and STTARK_KIT_LOG
point it at a test folder and a test log; STTARK_DAYLOG_DATE (YYYY-MM-DD) sets today's date (tests use it).
"""
import argparse, fcntl, json, os, re, shlex, subprocess, sys, time
from contextlib import contextmanager

DIR = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(DIR, 'state.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
DAYLOG = os.path.join(DIR, 'daylog')
STATE_FILES = os.path.join(DIR, 'orchestrator', 'state')

# ---- The rules. Change them here. ----
KINDS = {'done': 'Done', 'kicked': 'Kicked back', 'decision': 'Decisions', 'dropped': 'Dropped'}
SUBS = ['Done', 'Kicked back', 'Decisions', 'Dropped', 'Open']   # the order in the file
GENERAL = 'General'
MAX_BLOCKS = 2        # times the Stop hook blocks for one item
KEEP = 172800         # seconds a pending item is kept
VERDICT_RE = re.compile(r'^VERDICT:\s*(PASS|FAIL)\s*\|\s*(.*?)\s*(?:\|\s*(.*?))?\s*$')
DAY_FILE_RE = re.compile(r'^\d{4}-\d\d-\d\d\.md$')


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'daylog ' + line + '\n')
    except OSError:
        pass


class Fail(Exception):
    pass


# ---- repo and paths ----

def repo_of(cwd=None):
    try:
        r = subprocess.run(['git', '-C', cwd or os.getcwd(), 'rev-parse', '--show-toplevel'],
                           capture_output=True, text=True, timeout=3)
        top = r.stdout.strip()
        if r.returncode == 0 and top:
            # a worktree uses the main repo's name: its common git folder is <main>/.git
            c = subprocess.run(['git', '-C', cwd or os.getcwd(), 'rev-parse', '--git-common-dir'],
                               capture_output=True, text=True, timeout=3)
            common = os.path.realpath(os.path.join(cwd or os.getcwd(), c.stdout.strip())) if c.returncode == 0 and c.stdout.strip() else ''
            if os.path.basename(common) == '.git':
                return os.path.basename(os.path.dirname(common))
            return os.path.basename(top)
    except Exception:
        pass
    return GENERAL


def today():
    return os.environ.get('STTARK_DAYLOG_DATE') or time.strftime('%Y-%m-%d')


def day_path(day=None):
    return os.path.join(DAYLOG, (day or today()) + '.md')


def state_path(repo):
    safe = re.sub(r'[/\\:\x00]', '_', repo).strip('.') or GENERAL
    return os.path.join(STATE_FILES, safe + '.md')


# ---- the file ----

def parse(text):
    """(asana-synced value, {repo: {subsection: [line text]}}) from a day log file."""
    asana, repos, repo, sub = 'no', {}, None, None
    for ln in text.splitlines():
        if ln.startswith('asana-synced:'):
            asana = ln.split(':', 1)[1].strip() or 'no'
        elif ln.startswith('## '):
            repo, sub = ln[3:].strip(), None
            repos.setdefault(repo, {})
        elif ln.startswith('### ') and repo is not None:
            sub = ln[4:].strip()
        elif ln.startswith('- ') and repo is not None and sub:
            repos[repo].setdefault(sub, []).append(ln[2:])
    return asana, repos


def render(day, asana, repos):
    names = sorted((r for r in repos if any(repos[r].get(s) for s in SUBS)), key=lambda r: (r == GENERAL, ))
    out = ['# Day log ' + day, 'asana-synced: ' + asana]
    for r in names:
        out.append('')
        out.append('## ' + r)
        for s in SUBS:
            if repos[r].get(s):
                out.append('### ' + s)
                out += ['- ' + x for x in repos[r][s]]
    return '\n'.join(out) + '\n'


def earlier_open(day):
    """{repo: Open lines} of the most recent day log before `day`."""
    try:
        files = sorted(f for f in os.listdir(DAYLOG) if DAY_FILE_RE.match(f) and f[:-3] < day)
    except OSError:
        return {}
    if not files:
        return {}
    try:
        _, repos = parse(open(os.path.join(DAYLOG, files[-1])).read())
    except OSError:
        return {}
    return {r: {'Open': list(s['Open'])} for r, s in repos.items() if s.get('Open')}


def load(day=None):
    """(asana, repos) for a day: the file, or a new day with the earlier Open items carried forward."""
    day = day or today()
    try:
        return parse(open(day_path(day)).read())
    except OSError:
        return 'no', earlier_open(day)


@contextmanager
def locked_day(day=None):
    """The day's (asana, repos) under the file lock; written back on exit."""
    day = day or today()
    os.makedirs(DAYLOG, exist_ok=True)
    path = day_path(day)
    with open(path + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        model = list(load(day))
        yield model
        tmp = '%s.tmp%d' % (path, os.getpid())
        with open(tmp, 'w') as f:
            f.write(render(day, model[0], model[1]))
        os.replace(tmp, path)


def one_line(s):
    return ' '.join(str(s).split())


def item_field(line):
    """The item of a Done or Kicked back line: the first field after the time."""
    parts = [p.strip() for p in line.split('|')]
    return parts[1] if len(parts) > 1 else ''


# ---- commands ----

def cmd_add(a):
    text = one_line(a.text)
    if not text:
        raise Fail('--text is empty')
    repo = a.repo or repo_of()
    with locked_day() as (m):
        m[1].setdefault(repo, {}).setdefault(KINDS[a.kind], []).append('%s | %s' % (time.strftime('%H:%M'), text))
    log('add %s %s: %s' % (repo, a.kind, text[:80]))
    print('Added to %s, %s: %s' % (repo, KINDS[a.kind], day_path()))


def cmd_open(a):
    repo = a.repo or repo_of()
    items = [one_line(i) for i in a.item or [] if one_line(i)]
    with locked_day() as m:
        m[1].setdefault(repo, {})['Open'] = items
    log('open %s: %d items' % (repo, len(items)))
    print('Open list for %s replaced, %d items: %s' % (repo, len(items), day_path()))


def cmd_path(a):
    if a.create:
        with locked_day():
            pass
    print(day_path())


def section(day, repos, repo, only_open):
    if only_open:
        return ''.join('- %s\n' % x for x in repos.get(repo, {}).get('Open', []))
    if repo is None:
        return render(day, 'no', repos)
    one = {repo: repos.get(repo, {})}
    return render(day, 'no', one).split('\n', 2)[2].lstrip('\n')


def cmd_show(a):
    day = today()
    asana, repos = load(day)
    if a.open:
        out = section(day, repos, a.repo or repo_of(), True)
        print(out.rstrip('\n') or 'No open items.')
    elif a.repo:
        out = section(day, repos, a.repo, False)
        print(out.rstrip('\n') or 'Nothing logged for %s today.' % a.repo)
    else:
        print(render(day, asana, repos).rstrip('\n'))


def cmd_state_path(a):
    os.makedirs(STATE_FILES, exist_ok=True)
    print(state_path(a.repo or repo_of()))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write('claude-daylog: %s\n' % message)
        sys.exit(1)


def cli(argv):
    p = Parser(prog='claude-daylog', description="The orchestrator's day log.")
    sub = p.add_subparsers(dest='cmd')
    sub.required = True
    s = sub.add_parser('add')
    s.add_argument('--repo')
    s.add_argument('--kind', required=True, choices=sorted(KINDS))
    s.add_argument('--text', required=True)
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser('open')
    s.add_argument('--repo')
    s.add_argument('--item', action='append')
    s.set_defaults(fn=cmd_open)
    s = sub.add_parser('path')
    s.add_argument('--create', action='store_true')
    s.set_defaults(fn=cmd_path)
    s = sub.add_parser('show')
    s.add_argument('--repo')
    s.add_argument('--open', action='store_true')
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser('state-path')
    s.add_argument('--repo')
    s.set_defaults(fn=cmd_state_path)
    a = p.parse_args(argv)
    try:
        a.fn(a)
    except Fail as e:
        sys.stderr.write('claude-daylog: %s\n' % e)
        return 1
    except OSError as e:
        sys.stderr.write('claude-daylog: %s\n' % e)
        return 1
    return 0


# ---- hooks ----

@contextmanager
def kit_state():
    """The app's shared state file, under the same lock the app and the other hooks use."""
    os.makedirs(DIR, exist_ok=True)
    with open(STATE + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            s = json.load(open(STATE))
        except (OSError, ValueError):
            s = {}
        if not isinstance(s, dict):
            s = {}
        yield s
        tmp = STATE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, STATE)


def switch_on():
    try:
        return json.load(open(STATE)).get('orchestrator') is True
    except (OSError, ValueError, AttributeError):
        return False


def report_texts(data):
    """The report candidates, best first: a SubagentHandback message (latest first), last_assistant_message,
    the last assistant text of the transcript."""
    handbacks, last_text = [], ''
    tp = data.get('agent_transcript_path')
    if tp:
        try:
            for line in open(os.path.expanduser(tp)):
                try:
                    msg = json.loads(line).get('message') or {}
                except ValueError:
                    continue
                content = msg.get('content')
                if msg.get('role') != 'assistant' or not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get('type') == 'tool_use' and b.get('name') == 'SubagentHandback' \
                            and (b.get('input') or {}).get('message'):
                        handbacks.append(str((b['input'])['message']))
                    elif b.get('type') == 'text' and b.get('text'):
                        last_text = b['text']
        except OSError:
            pass
    out = handbacks[::-1]
    if isinstance(data.get('last_assistant_message'), str):
        out.append(data['last_assistant_message'])
    if last_text:
        out.append(last_text)
    return out


def parse_verdict(texts):
    """(verdict, item, evidence) from the last non-empty line of the first report that ends in one, or None."""
    for t in texts:
        lines = [l.strip().strip('`*').strip() for l in t.splitlines() if l.strip()]
        m = VERDICT_RE.match(lines[-1]) if lines else None
        if m and m.group(2):
            return m.group(1), one_line(m.group(2)), one_line(m.group(3) or '')
    return None


def on_subagent_stop(data):
    if not data.get('agent_type'):
        return   # internal agents (prompt suggestions, /btw) have no type
    texts = report_texts(data)
    v = parse_verdict(texts) if data.get('agent_type') == 'validator' else None
    try:
        report = next((t for t in texts if t.strip()), '')
        if report:
            save_finding(data, report, v)
    except Exception as e:
        log('error capture finding %s: %s' % (type(e).__name__, str(e)[:160]))
    if data.get('agent_type') != 'validator':
        return
    sid = data.get('session_id', '')
    if not v:
        return log('verdict %s: no VERDICT line in the validator report, nothing recorded' % sid[:8])
    verdict, item, evidence = v
    repo = repo_of(data.get('cwd'))
    now = time.time()
    with kit_state() as s:
        pend = {k: [e for e in v2 if isinstance(e, dict) and now - e.get('at', 0) < KEEP]
                for k, v2 in (s.get('daylog_pending') or {}).items() if isinstance(v2, list)}
        mine = [e for e in pend.get(sid, []) if not (e.get('item', '').strip().lower() == item.lower()
                                                     and e.get('repo') == repo)]
        mine.append({'item': item, 'verdict': verdict, 'evidence': evidence, 'repo': repo, 'at': now})
        pend[sid] = mine
        s['daylog_pending'] = {k: v2 for k, v2 in pend.items() if v2}
    log('verdict %s: %s %s (%s)' % (sid[:8], verdict, item[:60], repo))


def written(entry):
    """True when today's file has the entry's item under its repo's Done (PASS) or Kicked back (FAIL)."""
    _, repos = load()
    lines = (repos.get(entry.get('repo'), {}).get('Done' if entry.get('verdict') == 'PASS' else 'Kicked back')) or []
    want = str(entry.get('item', '')).strip().lower()
    return any(item_field(l).lower() == want for l in lines)


def command_for(e):
    item, ev = e['item'], (e.get('evidence') or '...')[:200]
    pass_ = e['verdict'] == 'PASS'
    label = 'evidence' if pass_ else 'gap'
    if not ev.lower().startswith(label + ':'):
        ev = '%s: %s' % (label, ev)
    text = '%s | task | %s | %s' % (item, 'PASS' if pass_ else 'FAIL', ev)
    return 'Write the day log entry for %s: claude-daylog add --repo %s --kind %s --text %s' % (
        item, shlex.quote(e['repo']), 'done' if pass_ else 'kicked', shlex.quote(text))


def on_stop(data):
    sid = data.get('session_id', '')
    reasons = []
    with kit_state() as s:
        pend = s.get('daylog_pending') or {}
        if not isinstance(pend.get(sid), list) or not pend[sid]:
            return
        keep = []
        for e in pend[sid]:
            if written(e):
                log('stop %s: %s is in the day log' % (sid[:8], e.get('item', '')[:60]))
            elif e.get('blocks', 0) >= MAX_BLOCKS:
                log('stop %s: gave up on %s after %d blocks' % (sid[:8], e.get('item', '')[:60], MAX_BLOCKS))
            else:
                e['blocks'] = e.get('blocks', 0) + 1
                keep.append(e)
                reasons.append(command_for(e))
        if keep:
            pend[sid] = keep
        else:
            pend.pop(sid, None)
        if pend:
            s['daylog_pending'] = pend
        else:
            s.pop('daylog_pending', None)
    if reasons:
        log('block %s: %d items' % (sid[:8], len(reasons)))
        print(json.dumps({'decision': 'block', 'reason': '\n'.join(reasons)}))


def on_session_start(data):
    """Sources startup, clear, compact and resume: the pending items and findings. Source clear also: the
    state file and today's Open items."""
    repo = repo_of(data.get('cwd'))
    clear = data.get('source') == 'clear'
    parts, opens, has_state = [], [], False
    block = restore_block(repo)
    if block:
        parts.append(block)
    if clear:
        try:
            st = open(state_path(repo)).read().strip()
            if st:
                has_state = True
                parts.append('State file (%s):\n%s' % (state_path(repo), st))
        except OSError:
            pass
        opens = load()[1].get(repo, {}).get('Open', [])
        if opens:
            parts.append("Today's open items (%s):\n%s" % (repo, '\n'.join('- ' + x for x in opens)))
    if not parts:
        return log('restore %s: nothing to restore' % repo)
    text = ('Restored after /clear' if clear else 'Restored at session start (%s)' % data.get('source')) \
        + ' (Sttark orchestrator):\n' + '\n\n'.join(parts)
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': text}}))
    log('restore %s: state %s, %d open items, pending %s' % (repo, 'yes' if has_state else 'no', len(opens),
                                                             'yes' if block else 'no'))


# ---- capture: questions and findings saved by hooks, restored after /clear ----
# Kept in KIT/orchestrator/state/<repo>.pending.md (next to the state file, which the orchestrator overwrites
# with its Write tool and so would wipe a section kept inside it). Older entries go to <repo>.archive.md.
PENDING, FINDINGS = 'Pending with Cole', 'Findings'
SECTIONS = (PENDING, FINDINGS)
KEEP_ENTRIES = 20     # entries kept per section; older ones move to the archive file
INJECT_CAP = 4000     # characters of pending items and findings injected at SessionStart
EXCERPT_LINES = 15
PROMPT_CHARS = 300
NEED_RE = re.compile(r'what i need from you', re.I)
NOTHING_RE = re.compile(r'^(nothing|none|no action|n/a)\b', re.I)
KEEP_FINDINGS = 50    # files kept in findings/
KEEP_ARCHIVE = 500    # entries kept in the archive file
# A prompt that contains one of these did not come from the person typing (or is a slash command): it resolves nothing.
NOT_TYPED = ['<task-notification>', '<agent-message', 'Another Claude session sent a message', '[SYSTEM NOTIFICATION',
             '<side-sessions-event>', '<ci-monitor-event>', '<scheduled-task', '<command-name>']


def typed(prompt):
    """True when the prompt is something the person typed: not empty, not a slash command, no machine marker."""
    t = str(prompt or '').strip()
    return bool(t) and not t.startswith('/') and not any(m in t for m in NOT_TYPED)


def pending_path(repo):
    return state_path(repo)[:-3] + '.pending.md'


def archive_path(repo):
    return state_path(repo)[:-3] + '.archive.md'


def stamp():
    return '%s %s' % (today(), time.strftime('%H:%M'))


def read_sections(path):
    secs, sec = {s: [] for s in SECTIONS}, None
    try:
        text = open(path).read()
    except OSError:
        return secs
    for ln in text.splitlines():
        if ln.startswith('## ') and ln[3:].strip() in secs:
            sec = ln[3:].strip()
        elif sec and ln.startswith('- ['):
            secs[sec].append(ln)
        elif sec and secs[sec] and ln.startswith('  '):
            secs[sec][-1] += '\n' + ln
    return secs


def trim_archive(path, new):
    """Append entries to the archive file and keep the newest KEEP_ARCHIVE."""
    try:
        text = open(path).read()
    except OSError:
        text = ''
    blocks, cur = [], None
    for ln in (text + ('\n'.join(new) + '\n')).splitlines():
        if re.match(r'^\((%s)\)$' % '|'.join(map(re.escape, SECTIONS)), ln):
            cur = [ln]
            blocks.append(cur)
        elif cur is not None:
            cur.append(ln)
    with open(path, 'w') as f:
        f.write(''.join('\n'.join(b) + '\n' for b in blocks[-KEEP_ARCHIVE:]))


@contextmanager
def locked_pending(repo):
    """The repo's sections ({section: [entry text]}) under a lock; trimmed and written back on exit."""
    path = pending_path(repo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        secs = read_sections(path)
        yield secs
        old = []
        for k in SECTIONS:
            if len(secs[k]) > KEEP_ENTRIES:
                old += ['(%s)\n%s' % (k, e) for e in secs[k][:-KEEP_ENTRIES]]
                secs[k] = secs[k][-KEEP_ENTRIES:]
        if old:
            trim_archive(archive_path(repo), old)
        out = ['# Pending with Cole and findings: ' + repo]
        for k in SECTIONS:
            out += ['', '## ' + k] + secs[k]
        tmp = '%s.tmp%d' % (path, os.getpid())
        with open(tmp, 'w') as f:
            f.write('\n'.join(out) + '\n')
        os.replace(tmp, path)


def entry(head, *body):
    """One entry: a head line, then indented lines (any line of `body` may hold several lines)."""
    lines = []
    for b in body:
        lines += str(b).splitlines() or ['']
    return '- [%s] %s' % (stamp(), head) + ''.join('\n  ' + l for l in lines)


def is_open(e):
    return 'status: unanswered' in e.split('\n', 1)[0]


def string_answers(resp, qtexts):
    """{question: answer} from text like `The user answered: "Q1"="A1", "Q2"="A2". Read the answers ...`. Each known
    question is found as `"<question>"="`; its answer runs to the start of the next question's `", "<q>"="`, or for the
    last one to the final `". ` (or the closing `"` / `".` at the end), so commas and quotes in an answer stay."""
    marks = []
    for q in qtexts:
        i = resp.find('"%s"="' % q)
        if q and i >= 0:
            marks.append((i, q, i + len(q) + 4))
    marks.sort()
    out = {}
    for n, (i, q, start) in enumerate(marks):
        if n + 1 < len(marks):
            end = marks[n + 1][0]
            a = resp[start:end].rstrip()
            a = re.sub(r'",?\s*$', '', a) if a.endswith(('",', '"')) else a
        else:
            rest = resp[start:]
            j = rest.rfind('". ')
            if j < 0:
                j = rest.rfind('"', 0, len(rest) - (1 if rest.endswith('.') else 0)) if rest.rstrip().endswith(('"', '".')) else len(rest)
            a = rest[:j] if j >= 0 else rest
        a = a.strip()
        if a:
            out[q] = a
    return out


def answers_of(resp, questions):
    """{question: answer} from an AskUserQuestion tool_response. The shape is not documented: a dict with
    `answers` ({question: answer}) is read first, then text with "question"="answer" pairs."""
    out = {}
    if isinstance(resp, dict):
        a = resp.get('answers')
        if isinstance(a, dict):
            out = {str(k): (', '.join(map(str, v)) if isinstance(v, list) else str(v)) for k, v in a.items() if v not in ('', None, [])}
        elif isinstance(a, list):
            for i, v in enumerate(a):
                if v not in ('', None) and i < len(questions):
                    out[questions[i].get('question', '')] = str(v)
    elif isinstance(resp, str):
        out = string_answers(resp, [str(q.get('question', '')) for q in questions])
    return out


def on_ask(data):
    ti = data.get('tool_input')
    qs = [q for q in (ti.get('questions') if isinstance(ti, dict) else None) or [] if isinstance(q, dict)]
    if not qs:
        return
    # PostToolUseFailure (rejected, Esc) has no answer
    ans = {} if data.get('hook_event_name') == 'PostToolUseFailure' else answers_of(data.get('tool_response'), qs)
    repo = repo_of(data.get('cwd'))
    with locked_pending(repo) as secs:
        for q in qs:
            text = str(q.get('question', ''))
            opts = '; '.join((str(o.get('label', '')) + (' (%s)' % o['description'] if o.get('description') else ''))
                             if isinstance(o, dict) else str(o) for o in q.get('options') or [])
            a = ans.get(text)
            secs[PENDING].append(entry('asked (AskUserQuestion) | status: ' + ('answered' if a else 'unanswered'),
                                       'question: ' + text, 'options: ' + (opts or 'none'),
                                       'answer: ' + (a if a else 'unanswered')))
    log('capture %s: %d questions, %d answered' % (repo, len(qs), len(ans)))


def safe_name(s):
    return re.sub(r'[^A-Za-z0-9._-]', '_', str(s)) or 'agent'


def excerpt(report, verdict):
    lines = [l.rstrip() for l in report.splitlines() if l.strip()]
    if verdict:
        items = [l for l in lines if re.match(r'\s*([-*]|\d+[.)])\s', l)]
        vl = [l for l in lines if l.strip().strip('`*').startswith('VERDICT:')]
        return (vl[-1:] + items)[:EXCERPT_LINES]
    return lines[:EXCERPT_LINES]


def save_finding(data, report, verdict):
    repo = repo_of(data.get('cwd'))
    agent = data.get('agent_type') or 'agent'
    item = verdict[1] if verdict else str(data.get('description') or '').strip() or \
        next((l.strip() for l in report.splitlines() if l.strip()), '')[:80]
    d = os.path.join(STATE_FILES, safe_name(repo if repo != GENERAL else GENERAL), 'findings')
    os.makedirs(d, exist_ok=True)
    base = '%s-%s' % (time.strftime('%Y%m%d-%H%M%S'), safe_name(agent))
    path, n = os.path.join(d, base + '.md'), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(d, '%s-%d.md' % (base, n))
    with open(path, 'w') as f:
        f.write('# %s | %s | %s\n\n%s\n' % (agent, item, stamp(), report))
    for old in sorted(os.listdir(d))[:-KEEP_FINDINGS]:
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    with locked_pending(repo) as secs:
        secs[FINDINGS].append(entry('%s | item: %s | full report: %s' % (agent, one_line(item), path),
                                    *(excerpt(report, verdict) or ['(empty report)'])))
    log('capture %s: finding from %s saved to %s' % (repo, agent, path))


def norm(t):
    return ' '.join(str(t).lower().split())


def question_text(msg):
    """The part of an assistant message that asks the person something, or ''. Ignored: fenced code, headings,
    table rows, blockquotes, inline-code-only lines, and a "What I need from you" that says nothing is needed."""
    lines, fence, keep = msg.rstrip().splitlines(), False, []
    for l in lines:
        st = l.strip()
        if st.startswith('```') or st.startswith('~~~'):
            fence = not fence
            continue
        if fence:
            continue
        keep.append(l)
    for i, l in enumerate(keep):
        if NEED_RE.search(l) and not l.strip().startswith(('|', '>')):
            rest = NEED_RE.split(l, 1)[1].strip(' :-*#\t')
            j = i + 1
            while not rest and j < len(keep):
                rest = keep[j].strip(' :-*#\t•')
                j += 1
            if NOTHING_RE.match(rest):
                continue
            return '\n'.join(keep[i:])[:1500]
    qs = []
    for l in keep:
        st = l.strip()
        if st.startswith(('#', '|', '>')) or re.fullmatch(r'`[^`]*`[*_.]*', st):
            continue
        if st.rstrip('*_`)"\'').endswith('?'):
            qs.append(st)
    return '\n'.join(qs)[:1500]


def user_text(msg):
    """The typed text of a transcript user message, or None for tool results and machine messages."""
    c = msg.get('content')
    if isinstance(c, list):
        c = '\n'.join(b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text')
    return c if isinstance(c, str) and typed(c) else None


def last_assistant_text(data):
    """The last assistant text of this turn: last_assistant_message, else the assistant text after the last typed
    user message in the transcript ('' when the turn has none)."""
    m = data.get('last_assistant_message')
    if isinstance(m, str) and m.strip():
        return m
    last = ''
    try:
        for line in open(os.path.expanduser(data.get('transcript_path'))):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            msg = e.get('message') if isinstance(e, dict) else None
            if not isinstance(msg, dict) or e.get('isSidechain'):
                continue
            if msg.get('role') == 'user':
                if user_text(msg) is not None:
                    last = ''
                continue
            if msg.get('role') != 'assistant':
                continue
            c = msg.get('content')
            texts = [b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text'] \
                if isinstance(c, list) else ([c] if isinstance(c, str) else [])
            if any(t.strip() for t in texts):
                last = '\n'.join(t for t in texts if t.strip())
    except (OSError, TypeError):
        pass
    return last


def capture_stop(data):
    if data.get('agent_id'):
        return
    q = question_text(last_assistant_text(data))
    if not q:
        return
    repo = repo_of(data.get('cwd'))
    with locked_pending(repo) as secs:
        asked = [norm(l.split(':', 1)[1]) for e in secs[PENDING] if is_open(e) and 'AskUserQuestion' in e.split('\n', 1)[0]
                 for l in e.splitlines() if l.startswith('  question:')]
        lines = q.splitlines()
        kept = [l for l in lines if not any(len(norm(l)) > 8 and (norm(l) in a or a in norm(l)) for a in asked if a)]
        if not any('?' in l or not NEED_RE.search(l) for l in kept if l.strip()):
            return   # everything was already asked with AskUserQuestion
        q = '\n'.join(kept)
        if any(is_open(e) and e.split('\n')[1:] == ['  ' + l for l in q.splitlines()] for e in secs[PENDING]):
            return
        secs[PENDING].append(entry('asked in plain text | status: unanswered', q))
    log('capture %s: plain-text question saved' % repo)


def resolve_prompt(data):
    """A typed prompt answers the open questions: plain-text ones and unanswered AskUserQuestion ones."""
    prompt = one_line(data.get('prompt') or '')[:PROMPT_CHARS]
    if not typed(data.get('prompt')) or not prompt:
        return
    repo = repo_of(data.get('cwd'))
    try:
        if 'status: unanswered' not in open(pending_path(repo)).read():
            return   # nothing open: no lock, no rewrite
    except OSError:
        return
    with locked_pending(repo) as secs:
        n, at = 0, time.strftime('%H:%M')
        for i, e in enumerate(secs[PENDING]):
            head, _, rest = e.partition('\n')
            if is_open(e):
                head = head.replace('status: unanswered', 'status: answered in prompt at %s' % at)
                if 'AskUserQuestion' in head:
                    rest = rest.replace('  answer: unanswered', '  answer (in prompt at %s, first %d chars): %s' % (at, PROMPT_CHARS, prompt))
                    secs[PENDING][i] = head + '\n' + rest
                else:
                    secs[PENDING][i] = head + '\n' + rest + '\n  answer (first %d chars of the prompt): %s' % (PROMPT_CHARS, prompt)
                n += 1
    if n:
        log('capture %s: %d questions marked answered' % (repo, n))


def restore_block(repo):
    """The pending items (unanswered first) and the last 5 findings pointers, capped at INJECT_CAP characters."""
    secs = read_sections(pending_path(repo))
    items = [e for e in secs[PENDING] if is_open(e)] + [e for e in secs[PENDING] if not is_open(e)][::-1]
    finds = [e.split('\n', 1)[0] for e in secs[FINDINGS][-5:]][::-1]
    if not items and not finds:
        return ''
    head = ['Pending with Cole (saved automatically; %s). Raise unanswered items before new work.' % pending_path(repo)]
    out, used = list(head), len(head[0])
    for e in items:
        if used + len(e) + 1 > INJECT_CAP - 600:   # leave room for the findings pointers
            e = e[:max(0, INJECT_CAP - 600 - used - 1)].rstrip()
            if len(e) < 80:
                out.append('(more entries in %s)' % pending_path(repo))
                break
            e += ' ...'
        out.append(e)
        used += len(e) + 1
    if finds:
        out.append('Latest findings (full reports are files):')
        out += finds
    return '\n'.join(out)[:INJECT_CAP]


def hook():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict) or not switch_on():
        return
    try:
        event = data.get('hook_event_name')
        if event == 'SubagentStop':
            on_subagent_stop(data)
        elif event == 'Stop':
            try:
                capture_stop(data)
            except Exception as e:
                log('error capture stop %s: %s' % (type(e).__name__, str(e)[:160]))
            on_stop(data)
        elif event in ('PostToolUse', 'PostToolUseFailure'):
            if data.get('tool_name') == 'AskUserQuestion':
                on_ask(data)
        elif event == 'UserPromptSubmit':
            resolve_prompt(data)
        elif event == 'SessionStart':
            on_session_start(data)
    except Exception as e:   # never stop a session because of this hook
        log('error %s: %s, allowed' % (type(e).__name__, str(e)[:160]))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--hook':
        hook()
    else:
        sys.exit(cli(sys.argv[1:]))
