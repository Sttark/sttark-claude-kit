#!/usr/bin/python3
"""Claude Code UserPromptSubmit hook, turned on with "Name sessions automatically" in the Sttark Claude Kit menu.

Gives each session a short handle for its project or area, like "Order Page" or "Label Printer", instead of
the long description Claude generates. On each prompt, if the session has no custom name yet (Claude Code
passes the name in `session_title` once one is set, by you or by this hook), a quick side call reads the
prompt and the conversation so far and picks a handle. It reuses one of your existing handles when the
session belongs to the same area. If it can't tell yet what the session is about, it waits for a later
prompt. Once a session has a name, this never changes it.

Every handle it sees on a named session is remembered, so new names follow your own. Decisions go to the
same log as the effort checks, ~/Library/Logs/sttark-claude-kit.log.
"""
import importlib.util, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('effort', os.path.join(HERE, 'effort-hook.py'))
effort = importlib.util.module_from_spec(spec)
spec.loader.exec_module(effort)

NAMER = """You name Claude Code sessions. The name is the topic in the person's day that the session \
belongs to: the bucket they'd file it under, shared by every session on that topic. 1 to 3 words, like a \
folder name. Think of their day as a handful of ongoing topics (a website, a machine, a building, a project, a \
person they manage, a hobby) and pick the one this session is part of. Never name the task, part, symptom or \
question inside the topic: a broken comment link on the docs site is "Docs", not "Comment Highlight"; a code \
question about the warehouse's walkways is "Warehouse", not "Warehouse Egress"; a reply about someone's \
promotion is that person's name or "Team", not "Reply to Manager". Keep names, product names and acronyms as they \
are written.

If the session belongs to the topic of one of the person's existing names, use that name exactly as written. \
Never reuse a name just because nothing else fits; make a new one in the same style instead.

If the conversation doesn't yet show what the session is about (a greeting, a bare "yes", a question with \
no subject), answer WAIT.

Answer with the handle alone on one line, or WAIT."""


RECHECK_EVERY = (3, 6, 12)  # prompts after which a name this hook chose is looked at again; then every 12th

RENAMER = NAMER.replace("If the conversation doesn't yet show", "The session already has a name this tool chose \
earlier. Sessions drift: the first message may have been about something the session soon left behind. Read \
what the session is mostly about now. If the current name still fits, answer KEEP. If not, answer the new \
name.\n\nIf the conversation doesn't yet show") + " Or KEEP."


def known_handles(state):
    return state.get('handles', [])


def push(sid, name):
    """Claude Code keeps the name on this Mac, and the Claude app sets its own automatic title a few seconds
    after the first prompt, which replaces it there. So set the name on the server too, after that title lands,
    and once more in case it lands late."""
    for wait in (15, 45):
        time.sleep(wait)
        try:
            if effort.sse().session(sid).get('title') != name:
                effort.sse().rename(sid, name)
                effort.log(f'name   {sid[4:12]} set "{name}" in the Claude app')
        except Exception as e:
            effort.log(f'name   {sid[4:12]} could not set "{name}" in the Claude app: {e!r}')
            return
    effort.fetch_title(sid)


def main():
    if len(sys.argv) == 4 and sys.argv[1] == '--push':
        push(sys.argv[2], sys.argv[3])
        return
    if os.environ.get('EFFORT_JUDGE'):
        return
    data = json.load(sys.stdin)
    title = (data.get('session_title') or '').strip()
    sid = effort.session_id()
    mine = effort.peek().get('auto_names', {}).get(sid) if sid else None
    if title and title == mine:
        # A name this hook chose: look again now and then, in case the session moved to another topic.
        with effort.state() as s:
            n = s.setdefault('name_prompts', {}).get(sid, 0) + 1
            s['name_prompts'][sid] = n
        if n in RECHECK_EVERY or (n > 12 and n % 12 == 0):
            return rename(data, sid, title)
        return
    if title:
        # Named already: remember the handle so new names can reuse it, and leave the session alone.
        with effort.state() as s:
            h = s.setdefault('handles', [])
            # only short names are handles; a long one is Claude's own description, or a message used as a name
            if title not in h and len(title.split()) <= 4 and len(title) <= 40 and title not in s.get('auto_names', {}).values():
                h.insert(0, title)
                del h[60:]
                effort.log(f'name   {data.get("session_id", "")[:8]} has "{title}", remembered as a handle')
        return
    name_it(data, sid)


def ask_model(system, ask):
    import subprocess
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    r = subprocess.run([effort.CLAUDE, '-p', '--model', effort.model(), '--effort', 'low',
                        '--no-session-persistence', '--strict-mcp-config', '--tools', '',
                        '--settings', '{"disableAllHooks":true}', '--system-prompt', system, ask],
                       capture_output=True, text=True, timeout=25, env=env, cwd='/tmp')
    return (r.stdout.strip().splitlines() or [''])[0].strip().strip('"').strip()


def first_prompts(path, n=2):
    out = []
    try:
        for line in open(path):
            e = json.loads(line)
            if e.get('type') == 'user' and not e.get('isMeta'):
                t = effort.clean(effort.text_of((e.get('message') or {}).get('content')))
                if t and not t.startswith('<'):
                    out.append(t[:400])
                    if len(out) >= n:
                        break
    except (OSError, ValueError):
        pass
    return out


def rename(data, sid, current):
    prompt = effort.clean(data.get('prompt'))
    handles = [h for h in known_handles(effort.peek()) if h != current]
    start = first_prompts(data.get('transcript_path', ''))
    context = effort.recent(data.get('transcript_path', ''), prompt, turns=10)
    ask = (f'Current name: {current}\n\nThe person\'s other names: {", ".join(handles) or "(none)"}\n\n'
           f'How the session started:\n' + '\n'.join('- ' + p for p in start) +
           f'\n\nRecent conversation:\n{context or "(none)"}\n\nLatest message:\n{prompt[:2000]}\n\nKEEP or new name?')
    t0 = time.time()
    try:
        name = ask_model(RENAMER, ask)
    except Exception as e:
        effort.log(f'name   {sid[4:12]} recheck failed: {e!r}')
        return
    if not name or name.upper() in ('KEEP', 'WAIT') or len(name) > 40 or name == current:
        effort.log(f'name   {sid[4:12]} keeps "{current}" ({time.time() - t0:.1f}s)')
        return
    effort.log(f'name   {sid[4:12]} "{current}" -> "{name}": the session moved on ({time.time() - t0:.1f}s)')
    apply(sid, name)


def apply(sid, name):
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'sessionTitle': name}}))
    if not sid:
        return
    import subprocess
    with effort.state() as s:
        s['sessions'].setdefault(sid, {}).update(title=name, title_at=time.time())
        s.setdefault('auto_names', {})[sid] = name
    subprocess.Popen([sys.executable, os.path.abspath(__file__), '--push', sid, name],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def name_it(data, sid):
    prompt = effort.clean(data.get('prompt'))
    if not prompt:
        effort.log(f'name   {data.get("session_id", "")[:8]} wait: only automatic notes, nothing from the person yet')
        return
    handles = known_handles(effort.peek())
    context = effort.recent(data.get('transcript_path', ''), prompt)
    ask = (f'The person\'s existing handles: {", ".join(handles) if handles else "(none yet)"}\n\n'
           f'Conversation so far:\n{context or "(none)"}\n\nLatest message:\n{prompt[:3000]}\n\nName?')
    t0 = time.time()
    try:
        name = ask_model(NAMER, ask)
    except Exception as e:
        effort.log(f'name   {data.get("session_id", "")[:8]} failed: {e!r}')
        return
    snippet = re.sub(r'\s+', ' ', prompt)[:60]
    if not name or name.upper() == 'WAIT' or len(name) > 40:
        effort.log(f'name   {data.get("session_id", "")[:8]} wait ({time.time() - t0:.1f}s) | {snippet}')
        return
    effort.log(f'name   {data.get("session_id", "")[:8]} -> "{name}" ({time.time() - t0:.1f}s) | {snippet}')
    apply(sid, name)


if __name__ == '__main__':
    main()
