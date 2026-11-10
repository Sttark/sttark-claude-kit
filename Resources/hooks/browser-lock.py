#!/usr/bin/python3
"""Claude Code hook: the browser lock. Installed by the Sttark Claude Kit app only while the Orchestrator
switch is on ("orchestrator": true in the app's state.json), and it does nothing when the switch is off.

The browser is one shared resource. `claude-window` gives each session its own tab, but all agents of one
session share that tab. This hook lets one browsing agent at a time use it. A second one waits, then is denied.
It makes no model calls.

A browser call is a Bash command that runs `claude-window` (also after timeout, time, env, nohup, exec, sudo or VAR=x; any subcommand except `done`) or any
`mcp__claude-in-chrome__*` tool. The holder is the pair (session_id, agent_id), and the main agent (no agent_id)
is the holder "main".

PreToolUse:
- No holder, a holder idle for more than IDLE seconds, or the same holder: take or refresh the lock, allow.
- Another holder: wait, checking every POLL seconds, up to WAIT seconds. If it is still held, deny.
- The main agent starting an agent (the Agent or Task tool) frees the main agent's hold, so the new agent can browse.
- `claude-window done` by the holder frees the lock. By anyone else it changes nothing.
SubagentStop: an agent that holds the lock frees it, so a finished agent never keeps the browser.

The lock is kept per session in state.json under "browser", under the lock the app and the other hooks use.
Any error is logged and the call is let through. STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder;
STTARK_BROWSER_IDLE, STTARK_BROWSER_WAIT and STTARK_BROWSER_POLL change the times (tests use them).
"""
import fcntl, json, os, re, shlex, sys, time
from contextlib import contextmanager

DIR = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(DIR, 'state.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')


def num(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


IDLE = num('STTARK_BROWSER_IDLE', 300)   # seconds without a browser call before another agent may take the lock
WAIT = num('STTARK_BROWSER_WAIT', 50)    # seconds a second agent waits before it is denied (hook timeout must be more)
POLL = num('STTARK_BROWSER_POLL', 2)     # seconds between checks while waiting
KEEP = 86400                             # seconds an entry is kept

MCP_PREFIX = 'mcp__claude-in-chrome__'
PREFIX_RE = re.compile(r'^(?:(?:\w+=\S*|sudo(?:\s+-\S+)*|time|env(?:\s+-\S+)*|nohup|exec|command|g?timeout\s+(?:-\S+\s+(?:(?=\d\S*\s+\d)\S+\s+)?)*\d\S*)\s+)*')
AGENTS = {'Agent', 'Task'}


SHELLS = {'bash', 'sh', 'zsh'}
NOTED = []   # one parse line per hook run
NESTED_RE = re.compile(r'\$\(([^()]*)\)|`([^`]*)`')


def commands(cmd, depth=0):
    """The commands in a Bash command line, as strings. Splits at ; & | and new lines, and at ( ) and backticks
    (which open a nested command), but not inside quotes ('...', "...", $'...'). A nested command in double
    quotes ($(...) or backticks) and the text after `bash -c`, `sh -c` or `zsh -c` are split too.
    (The same function is in browser-lock.py and inline-guard.py.)"""
    if not isinstance(cmd, str) or depth > 4:
        return []
    out, buf, quote, i, n = [], [], None, 0, len(cmd)

    def end():
        seg = ''.join(buf).strip()
        buf.clear()
        if seg:
            out.append(seg)
    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == '\\' and quote != "'" and i + 1 < n:
                buf.append(cmd[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c == '\\' and i + 1 < n:
            buf.append(c + cmd[i + 1])
            i += 1
        elif c == "'" or c == '"':
            quote = c
            buf.append(c)
        elif c == '$' and cmd[i + 1:i + 2] == "'":
            quote = "'"
            buf.append("$'")
            i += 1
        elif c in ';|\n(`)' or (c == '&' and cmd[i - 1:i] not in ('>', '<') and cmd[i + 1:i + 2] != '>'):
            end()
        else:
            buf.append(c)
        i += 1
    end()
    if quote and depth == 0 and not NOTED:   # an open quote: the command is not split, and the call is let through
        NOTED.append(1)
        log(f'parse  unbalanced quote: {cmd[:60]!r}')
    more = []
    for seg in out:
        for m in NESTED_RE.finditer(seg):
            more += commands(m.group(1) or m.group(2), depth + 1)
        try:
            words = shlex.split(seg)
        except ValueError:
            continue
        while words and (re.match(r'^\w+=', words[0]) or words[0] in ('sudo', 'env', 'nohup', 'exec', 'time', 'command')
                         or (words[0].startswith('-') and len(words) > 1)):
            words = words[1:]
        if words and os.path.basename(words[0]) in SHELLS:
            for k, w in enumerate(words[1:-1], 1):
                if re.match(r'^-\w*c$', w):
                    more += commands(words[k + 1], depth + 1)
                    break
    return out + more


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'browser ' + line + '\n')
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


def window_calls(cmd):
    """The subcommands of every claude-window run in a Bash command ('' when it has none)."""
    out = []
    for part in commands(cmd):
        words = PREFIX_RE.sub('', part.strip()).split()
        if words and os.path.basename(words[0].strip('"\'')) == 'claude-window':
            out.append(words[1] if len(words) > 1 else '')
    return out


def kind(tool, ti):
    """'use' for a browser call, 'done' for a claude-window done, None for anything else."""
    if tool in AGENTS:
        return 'spawn'
    if tool.startswith(MCP_PREFIX):
        return 'use'
    if tool == 'Bash':
        subs = window_calls((ti or {}).get('command'))
        if subs:
            return 'done' if all(x == 'done' for x in subs) else 'use'
    return None


def holder_of(data):
    return data.get('agent_id') or 'main'


def label(atype, who):
    return f'{atype} {who[:8]}' if who != 'main' else 'main'


def try_take(sid, who, atype):
    """One check under the lock. Returns (True, None) when the caller has the lock, else (False, the holder)."""
    now = time.time()
    with state() as s:
        b = {k: v for k, v in (s.get('browser') or {}).items()
             if isinstance(v, dict) and now - v.get('at', 0) < KEEP}
        cur = b.get(sid)
        if cur and cur.get('holder') != who and now - cur.get('at', 0) <= IDLE:
            s['browser'] = b
            return False, dict(cur)
        if cur and cur.get('holder') != who:
            log(f'free   {sid[:8]} {label(cur.get("agent_type"), cur.get("holder"))} idle {int(now - cur.get("at", 0))} s')
        same = bool(cur) and cur.get('holder') == who
        if not same:
            log(f'take   {sid[:8]} {label(atype, who)}')
        b[sid] = {'holder': who, 'agent_type': atype, 'at': now,
                  'since': cur.get('since', cur.get('at', now)) if same else now}
        s['browser'] = b
    return True, None


def free(sid, who, why):
    with state() as s:
        b = s.get('browser') or {}
        cur = b.get(sid)
        if isinstance(cur, dict) and cur.get('holder') == who:
            del b[sid]
            s['browser'] = b
            log(f'free   {sid[:8]} {label(cur.get("agent_type"), who)} {why}')


def on_tool(data):
    sid, tool = data.get('session_id', ''), data.get('tool_name') or ''
    k = kind(tool, data.get('tool_input'))
    if not k:
        return
    who, atype = holder_of(data), data.get('agent_type') or ('main' if not data.get('agent_id') else 'agent')
    if k == 'done':
        return free(sid, who, 'done')
    if k == 'spawn':   # the main thread starts an agent: it lets go, so the new agent can browse at once
        return free(sid, 'main', 'main started an agent') if not data.get('agent_id') else None
    start, waited = time.time(), False
    while True:
        ok, cur = try_take(sid, who, atype)
        if ok:
            return
        if not waited:
            log(f'wait   {sid[:8]} {label(atype, who)} for {label(cur.get("agent_type"), cur.get("holder"))}')
            waited = True
        if time.time() - start + POLL > WAIT:
            break
        time.sleep(POLL)
    since = int(time.time() - cur.get('since', cur.get('at', time.time())))
    log(f'deny   {sid[:8]} {label(atype, who)}: held by {label(cur.get("agent_type"), cur.get("holder"))}, holding since {since} s')
    reason = (f'The browser is in use by another agent ({label(cur.get("agent_type"), cur.get("holder"))}, '
              f'holding since {since} s). '
              'Wait for it to finish, then try again. Only one browsing agent at a time.')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                             'permissionDecisionReason': reason}}))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict) or not switch_on():
        return
    try:
        event = data.get('hook_event_name')
        if event == 'PreToolUse':
            on_tool(data)
        elif event == 'SubagentStop' and data.get('agent_id'):
            free(data.get('session_id', ''), data['agent_id'], 'agent stopped')
    except Exception as e:   # never stop a session because of this hook
        log(f'error  {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
