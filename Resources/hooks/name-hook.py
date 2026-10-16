#!/usr/bin/python3
"""Claude Code UserPromptSubmit hook, turned on with "Name sessions automatically" in the Sttark Effort menu.

Gives each session a short handle for its project or area, like "Order Page" or "Label Printer", instead of
the long description Claude generates. On each prompt, if the session has no custom name yet (Claude Code
passes the name in `session_title` once one is set, by you or by this hook), a quick side call reads the
prompt and the conversation so far and picks a handle. It reuses one of your existing handles when the
session belongs to the same area. If it can't tell yet what the session is about, it waits for a later
prompt. Once a session has a name, this never changes it.

Every handle it sees on a named session is remembered, so new names follow your own. Decisions go to the
same log as the effort checks, ~/Library/Logs/claude-effort-hook.log.
"""
import importlib.util, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('effort', os.path.join(HERE, 'effort-hook.py'))
effort = importlib.util.module_from_spec(spec)
spec.loader.exec_module(effort)

NAMER = """You name Claude Code sessions. A name is a short handle for the project or area the session \
belongs to, the way a person labels a folder: 1 to 3 words, Title Case for words, names and acronyms kept as \
they are. Examples of the style: "Order Page", "Label Printer", "HVAC", "Q3 Budget", "Hiring". \
Not a description of the task: "Hiring", not "Draft interview questions for the welder role".

If the session clearly belongs to the area of one of the person's existing handles, use that handle exactly \
as written. Never reuse a handle just because nothing else fits; make a new one in the same style instead.

If the conversation doesn't yet show what the session is about (a greeting, a bare "yes", a question with \
no subject), answer WAIT.

Answer with the handle alone on one line, or WAIT."""


def known_handles(state):
    return state.get('handles', [])


def main():
    if os.environ.get('EFFORT_JUDGE'):
        return
    data = json.load(sys.stdin)
    title = (data.get('session_title') or '').strip()
    if title:
        # Named already: remember the handle so new names can reuse it, and leave the session alone.
        with effort.state() as s:
            h = s.setdefault('handles', [])
            if title not in h:
                h.insert(0, title)
                del h[60:]
                effort.log(f'name   {data.get("session_id", "")[:8]} has "{title}", remembered as a handle')
        return
    prompt = effort.clean(data.get('prompt'))
    if not prompt:
        effort.log(f'name   {data.get("session_id", "")[:8]} wait: only automatic notes, nothing from the person yet')
        return
    handles = known_handles(effort.peek())
    context = effort.recent(data.get('transcript_path', ''), prompt)
    ask = (f'The person\'s existing handles: {", ".join(handles) if handles else "(none yet)"}\n\n'
           f'Conversation so far:\n{context or "(none)"}\n\nLatest message:\n{prompt[:3000]}\n\nName?')
    t0 = time.time()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    import subprocess
    try:
        r = subprocess.run([effort.CLAUDE, '-p', '--model', effort.model(), '--effort', 'low',
                            '--no-session-persistence', '--strict-mcp-config', '--tools', '',
                            '--settings', '{"disableAllHooks":true}', '--system-prompt', NAMER, ask],
                           capture_output=True, text=True, timeout=25, env=env, cwd='/tmp')
        name = (r.stdout.strip().splitlines() or [''])[0].strip().strip('"').strip()
    except Exception as e:
        effort.log(f'name   {data.get("session_id", "")[:8]} failed: {e!r}')
        return
    snippet = re.sub(r'\s+', ' ', prompt)[:60]
    if not name or name.upper() == 'WAIT' or len(name) > 40:
        effort.log(f'name   {data.get("session_id", "")[:8]} wait ({time.time() - t0:.1f}s) | {snippet}')
        return
    effort.log(f'name   {data.get("session_id", "")[:8]} -> "{name}" ({time.time() - t0:.1f}s) | {snippet}')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'sessionTitle': name}}))


if __name__ == '__main__':
    main()
