#!/usr/bin/python3
"""Claude Code UserPromptSubmit hook, on with the Orchestrator switch ("orchestrator": true in the kit's
state.json). Tells the main agent when it is time to rotate the session: write the state file and the Open
snapshot, then /clear. No model calls.

Two signals:
- Context: the latest main-thread assistant message in the transcript gives the tokens in the window
  (input + cache read + cache creation). The window is 1,000,000 when the model name has [1m] or the usage
  is already over 200,000, else 200,000 (STTARK_CONTEXT_WINDOW overrides).
- Topic: the name hook (name-hook.py) renames a session it named when the work moves to another topic. The new
  name arrives as `session_title`; a change from the last name seen here, to a name the name hook chose
  (state.json "auto_names"), is a rename.

Says it at 60% or more (and at each 10 percent step after) and once per rename; "Rotation now" from 80%.
Last-seen name and last step said are kept per session in state.json under "rotation", under the same lock.
Log lines start with `rotate` (STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and log).
Any error is logged and the hook says nothing; it never blocks a prompt.
"""
import fcntl, json, os, sys, time
from contextlib import contextmanager

DIR = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(DIR, 'state.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
KEEP = 86400
TAIL = 4_000_000   # bytes of the transcript's end that are read


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + line + '\n')
    except OSError:
        pass


@contextmanager
def state():
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


def usage(path):
    """(tokens in the window, model) from the latest main-thread assistant message, or None."""
    with open(path, 'rb') as f:
        f.seek(max(0, os.path.getsize(path) - TAIL))
        lines = f.read().decode('utf-8', 'replace').splitlines()
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        m = e.get('message') if isinstance(e, dict) else None
        if (e.get('type') != 'assistant' or e.get('isSidechain') or not isinstance(m, dict)
                or not isinstance(m.get('usage'), dict) or m.get('model') == '<synthetic>'):
            continue
        u = m['usage']
        n = sum(int(u.get(k) or 0) for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
        return n, str(m.get('model') or '')
    return None


def window(tokens, model):
    try:
        return int(os.environ['STTARK_CONTEXT_WINDOW'])
    except (KeyError, ValueError):
        pass
    return 1_000_000 if '[1m]' in model.lower() or tokens > 200_000 else 200_000


def saved_note(cwd):
    """Says that questions and findings are saved automatically, and where the state file is."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import daylog
        sp = daylog.state_path(daylog.repo_of(cwd or None))
    except Exception:
        sp = os.path.join(DIR, 'orchestrator', 'state', '<repo>.md')
    return (f' Questions you asked the person and agent findings are saved automatically (next to the state file, '
            f'in {sp[:-3]}.pending.md, full agent reports in {sp[:-3]}/findings/); the state file is {sp}.')


def message(pct, moved, cwd=None):
    now = pct >= 80
    text = (f'{"Rotation now" if now else "Rotation"} (Sttark orchestrator): context {pct}% used'
            f'{", and the session moved to a new topic" if moved else ""}. '
            'At the next clean stopping point (no running agents, no validator verdict without a day log entry), '
            "write this repo's state file and the Open snapshot (`claude-daylog open --repo <repo> --item ...`), "
            'then tell the person to run /clear. After /clear the state and Open items are restored.')
    text += saved_note(cwd)
    if now:
        text += ' Do it at the first clean stopping point; do not start new work first.'
    return text


def main():
    data = json.load(sys.stdin)
    try:
        if json.load(open(STATE)).get('orchestrator') is not True:
            return
    except (OSError, ValueError):
        return
    sid = data.get('session_id') or ''
    if not sid:
        return
    title = (data.get('session_title') or '').strip()
    try:
        u = usage(data.get('transcript_path') or '')
    except FileNotFoundError:
        u = None   # first prompt of a session: no transcript yet
    pct = 0
    if u:
        pct = int(u[0] * 100 / window(*u))
    step = pct // 10 * 10 if pct >= 60 else 0
    fire = False
    moved = False
    with state() as s:
        r = s.setdefault('rotation', {})
        for k in [k for k, v in r.items() if time.time() - (v or {}).get('at', 0) > KEEP]:
            del r[k]
        x = r.setdefault(sid, {})
        old = x.get('name', '')
        if old and title and title != old and title in (s.get('auto_names') or {}).values():
            moved = True
        if title:
            x['name'] = title
        said = x.get('said', 0)
        if step > said:
            fire = True
        x['said'] = step if step < said or fire else said   # context shrank (compaction): count again from there
        fire = fire or moved
        x['at'] = time.time()
    if fire:
        log(f'rotate {sid[:8]} context {pct}%{", renamed" if moved else ""}: told the agent')
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                                 'additionalContext': message(pct, moved, data.get('cwd'))}}))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f'rotate error: {e!r}')
