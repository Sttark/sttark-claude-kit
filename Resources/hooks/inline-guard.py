#!/usr/bin/python3
"""Claude Code hook: the inline guard. Installed by the Sttark Claude Kit app only while the Orchestrator
switch is on ("orchestrator": true in the app's state.json), and it does nothing when the switch is off.

With the orchestrator, the main agent does small things itself and gives real work to subagents. This hook
stops the main agent from doing a worker's job. It makes no model calls. A hook call from a subagent (its
input has an agent_id) is always let through.

PreToolUse:
- Lookups (Read, Grep, Glob, Bash, WebFetch, WebSearch, and MCP read tools): 2 per item. The 3rd is denied.
  Only calls that were let through count. The count starts again when the person sends a prompt
  (UserPromptSubmit) and when the main agent starts an agent (the Agent or Task tool).
- Long Bash runs (builds, test suites, installs: LONG_RUNS below) are denied, also as the 1st call.
- Edit, Write, MultiEdit, NotebookEdit: let through for the day log, the orchestrator state files and NEXT
  files, and for a fix of 3 lines or less. Anything bigger is denied.
PostToolUse: a lookup result over 8,000 characters adds a note to Claude's context. It does not block.

Counts are kept per session in state.json under "guard", under the lock the app and the other hooks use.
Every deny and every note is logged to ~/Library/Logs/sttark-claude-kit.log, with lines starting `guard`.
STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and a test log.
"""
import difflib, fcntl, json, os, re, sys, time
from contextlib import contextmanager

DIR = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(DIR, 'state.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')

MAX_LOOKUPS = 2      # lookups per item; the next one is denied
MAX_LINES = 3        # the biggest fix the main agent makes itself
BIG_RESULT = 8000    # characters: a lookup result bigger than this gets a note
KEEP = 86400         # seconds a session's count is kept

LOOKUPS = {'Read', 'Grep', 'Glob', 'Bash', 'WebFetch', 'WebSearch'}
MCP_READ = ('read', 'get', 'list', 'search', 'query', 'fetch', 'find')
EDITS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
AGENTS = {'Agent', 'Task'}
ALLOWED_DIRS = [os.path.join(DIR, 'daylog'), os.path.join(DIR, 'orchestrator', 'state')]

# Long Bash runs: builds, test suites, installs. Each pattern is matched at the start of one command in the
# line (split at ; && || | and new lines, after VAR=value, sudo, time, env, nohup). Add a pattern here.
LONG_RUNS = [
    r'(npm|pnpm|yarn|bun)\s+(run\s+)?(install|i|ci|add|test|build)\b',
    r'npx\s+(jest|vitest|playwright|tsc)\b',
    r'(python3?\s+-m\s+)?pytest\b',
    r'python3?\s+-m\s+(unittest|pip\s+install)\b',
    r'pip3?\s+install\b',
    r'swift\s+(build|test)\b',
    r'xcodebuild\b',
    r'make\b',
    r'cargo\s+(build|test)\b',
    r'go\s+(build|test)\b',
    r'brew\s+(install|upgrade)\b',
    r'(\./)?gradlew?\b',
    r'mvn\b',
    r'((ba|z)?sh\s+)?\S*\b(build|install)\.sh\b',
]
LONG_RE = re.compile(r'(?:' + '|'.join(LONG_RUNS) + r')')
PREFIX_RE = re.compile(r'^(?:(?:\w+=\S*|sudo|time|env|nohup|exec)\s+)*')

DENY_LOOKUP = 'Delegate this. Write a brief and start an agent.'
DENY_EDIT = 'Delegate to implementer.'
DENY_LONG = 'Delegate to implementer or ops.'
NOTE_BIG = 'That lookup was too big for inline. Delegate the next one.'


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'guard  ' + line + '\n')
    except OSError:
        pass


@contextmanager
def state():
    """The app's shared state file, under the same lock the app and the other hooks use."""
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


def switch_on():
    try:
        return json.load(open(STATE)).get('orchestrator') is True
    except (OSError, ValueError, AttributeError):
        return False


def is_lookup(tool):
    if tool in LOOKUPS:
        return True
    if tool.startswith('mcp__') and not tool.startswith('mcp__ccd_'):
        return tool.rsplit('__', 1)[-1].lower().startswith(MCP_READ)
    return False


def long_run(cmd):
    """The part of a Bash command that is a long run, or None."""
    for part in re.split(r'&&|\|\||[;|\n]', cmd or ''):
        part = PREFIX_RE.sub('', part.strip().lstrip('('))
        if LONG_RE.match(part):
            return part[:60]
    return None


def lines(text):
    return len((text or '').splitlines())


def changed(old, new):
    """The lines a fix changes: the larger of the lines taken out and the lines put in."""
    a, b = (old or '').splitlines(), (new or '').splitlines()
    out = put = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != 'equal':
            out += i2 - i1
            put += j2 - j1
    return max(out, put)


def allowed_path(path):
    if not path:
        return False
    p = os.path.realpath(os.path.expanduser(path))
    if os.path.basename(p).lower().startswith('next'):
        return True
    for d in ALLOWED_DIRS:
        d = os.path.realpath(d)
        if p == d or p.startswith(d + os.sep):
            return True
    return False


def edit_size(tool, ti):
    """The lines an edit changes, or None when it is let through whatever its size."""
    path = ti.get('file_path') or ti.get('notebook_path')
    if allowed_path(path):
        return None
    if tool == 'Edit':
        return changed(ti.get('old_string'), ti.get('new_string'))
    if tool == 'MultiEdit':
        return sum(changed(e.get('old_string'), e.get('new_string')) for e in ti.get('edits') or [])
    if tool == 'NotebookEdit':
        return lines(ti.get('new_source'))
    # Write: a new file of a few lines only. Writing over a file is not a small fix.
    if path and os.path.exists(os.path.expanduser(path)):
        return max(lines(ti.get('content')), MAX_LINES + 1)
    return lines(ti.get('content'))


def deny(reason):
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                             'permissionDecisionReason': reason}}))


def reset(sid):
    with state() as s:
        g = {k: v for k, v in (s.get('guard') or {}).items() if time.time() - v.get('at', 0) < KEEP}
        if sid:
            g.pop(sid, None)
        if g:
            s['guard'] = g
        else:
            s.pop('guard', None)


def on_tool(data):
    sid, tool = data.get('session_id', ''), data.get('tool_name') or ''
    ti = data.get('tool_input') or {}
    if tool in AGENTS:
        return reset(sid)
    if tool in EDITS:
        n = edit_size(tool, ti)
        if n is not None and n > MAX_LINES:
            log(f'deny   {sid[:8]} {tool} {n} lines: {ti.get("file_path") or ti.get("notebook_path")}')
            deny(DENY_EDIT)
        return
    if tool == 'Bash':
        run = long_run(ti.get('command'))
        if run:
            log(f'deny   {sid[:8]} Bash long run: {run}')
            return deny(DENY_LONG)
    if not is_lookup(tool):
        return
    with state() as s:
        g = {k: v for k, v in (s.get('guard') or {}).items() if time.time() - v.get('at', 0) < KEEP}
        n = (g.get(sid) or {}).get('n', 0)
        if n < MAX_LOOKUPS:
            g[sid] = {'n': n + 1, 'at': time.time()}
        s['guard'] = g
    if n >= MAX_LOOKUPS:
        log(f'deny   {sid[:8]} {tool}: lookup {n + 1}, over {MAX_LOOKUPS} for this item')
        deny(DENY_LOOKUP)


def on_result(data):
    tool = data.get('tool_name') or ''
    if not is_lookup(tool):
        return
    r = data.get('tool_response')
    size = len(r) if isinstance(r, str) else len(json.dumps(r, ensure_ascii=False))
    if size <= BIG_RESULT:
        return
    log(f'big    {data.get("session_id", "")[:8]} {tool}: {size} characters')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': NOTE_BIG}}))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict) or data.get('agent_id') or not switch_on():
        return
    try:
        event = data.get('hook_event_name')
        if event == 'PreToolUse':
            on_tool(data)
        elif event == 'PostToolUse':
            on_result(data)
        elif event == 'UserPromptSubmit':
            reset(data.get('session_id', ''))
    except Exception as e:   # never stop a session because of this hook
        log(f'error  {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
