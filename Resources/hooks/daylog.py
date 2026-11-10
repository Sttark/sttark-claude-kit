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

One section per repo (the basename of `git rev-parse --show-toplevel` of the working folder; `General` outside
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
- SessionStart with source `clear`: adds this repo's state file and today's Open items to the context.
  Other sources: nothing.

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
    if data.get('agent_type') != 'validator':
        return
    v = parse_verdict(report_texts(data))
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
    if data.get('source') != 'clear':
        return
    repo = repo_of(data.get('cwd'))
    parts = []
    try:
        st = open(state_path(repo)).read().strip()
        if st:
            parts.append('State file (%s):\n%s' % (state_path(repo), st))
    except OSError:
        pass
    opens = load()[1].get(repo, {}).get('Open', [])
    if opens:
        parts.append("Today's open items (%s):\n%s" % (repo, '\n'.join('- ' + x for x in opens)))
    if not parts:
        return log('restore %s: nothing to restore' % repo)
    text = 'Restored after /clear (Sttark orchestrator):\n' + '\n\n'.join(parts)
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': text}}))
    log('restore %s: state %s, %d open items' % (repo, 'yes' if len(parts) and parts[0].startswith('State') else 'no',
                                                 len(opens)))


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
            on_stop(data)
        elif event == 'SessionStart':
            on_session_start(data)
    except Exception as e:   # never stop a session because of this hook
        log('error %s: %s, allowed' % (type(e).__name__, str(e)[:160]))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--hook':
        hook()
    else:
        sys.exit(cli(sys.argv[1:]))
