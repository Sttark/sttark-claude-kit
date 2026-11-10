#!/usr/bin/python3
"""Claude Code hook: the browser lock. Installed by the Sttark Claude Kit app only while the Orchestrator
switch is on ("orchestrator": true in the app's state.json), and it does nothing when the switch is off.

The browser is one shared resource. `claude-window` gives each session its own tab, but all agents of one
session share that tab. This hook lets one browsing agent at a time use it. A second one waits, then is denied.
It makes no model calls.

A browser call is a Bash command that runs `claude-window` (also after the prefixes in shell_commands.py; any subcommand except `done`) or any
`mcp__claude-in-chrome__*` tool, or a Bash command that runs `osascript` with a script that names Chrome (`Google Chrome`
or `Chrome`; also a heredoc script). The holder is the pair (session_id, agent_id), and the main agent (no agent_id)
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
import fcntl, json, os, sys, time
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
AGENTS = {'Agent', 'Task'}


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'browser ' + line + '\n')
    except OSError:
        pass

try:   # the shared command splitter, next to this file; if it cannot be loaded, the hook logs and allows
    import importlib.util
    _spec = importlib.util.spec_from_file_location('shell_commands', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shell_commands.py'))
    SC = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(SC)
    SC_ERR = None
except Exception as _e:
    SC, SC_ERR = None, _e


def commands(cmd):
    return SC.commands(cmd, log)


def strip_prefix(part):
    return SC.strip_prefix(part)


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
        words = strip_prefix(part).split()
        if words and os.path.basename(words[0].strip('"\'')) == 'claude-window':
            out.append(words[1] if len(words) > 1 else '')
    return out


def chrome_script(cmd):
    """True when a Bash command runs osascript with a script that names Chrome (in -e text or in a heredoc)."""
    for part in commands(cmd):
        words = strip_prefix(part).split()
        if words and os.path.basename(words[0].strip('"\'')) == 'osascript':
            if 'chrome' in part.lower() or ('<<' in part and 'chrome' in cmd.lower()):
                return True
    return False


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
        if chrome_script((ti or {}).get('command')):
            return 'use'
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
    if SC is None:
        return log(f'error  shell_commands.py not loaded: {SC_ERR}')
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
