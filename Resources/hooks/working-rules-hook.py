#!/usr/bin/python3
"""Claude Code hooks for "Sttark working rules" in the Sttark Claude Kit menu: how Claude works for
people at Sttark, in every session, on unless the switch is turned off.

UserPromptSubmit (no argument): puts the rules below in front of every prompt, as the profile hook does
with a person's own instructions. No model call; it costs nothing per prompt. The rules are the text
in RULES here: to change them, change this file and open a pull request.

Stop (--check, runs in the background): the last rule says replies are written in ASD-STE100 Simplified
Technical English. A rule in the context is a request; this is the check. When Claude finishes a reply, the
reply's prose goes to a quick side call (Haiku, with hooks off) that names the words and sentences that
clearly break STE, or answers OK. The check never sends a reply back: a reply the person has already seen
can't be changed, so a send-back only shows a second copy of it. A miss is saved for the session instead
and goes in front of the session's next prompt, so the next reply uses the approved words. Replies with no
prose (code only, or under a few words) are not checked. Any failure (no Claude Code, a slow answer, an
unreadable one) is logged and nothing is saved.

The same Stop hook also checks the manager rule, with no model call: when the work since the person's last
message made more than 8 tool calls in the chat and started no agent, a note goes in front of the next prompt.
And the status icon check, with no model call: a status table cell in the reply with more than one of
✅ 🔄 🔴 ⚪ gets a note in front of the next prompt.

Logged to ~/Library/Logs/sttark-claude-kit.log, lines starting "ste" (the reply check), "agents" (the
manager check) and "icons" (the status icon check).
"""
import fcntl, json, os, re, subprocess, sys, time

# STTARK_KIT_DIR and STTARK_KIT_LOG are for tests: a copy of the state folder and of the log.
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
NOTES = os.path.join(os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit'),
                     'working-notes.json')  # misses per session
MANAGER_MAX = 8     # tool calls a turn may make in the chat with no agent before the manager check notes it
AGENT_TOOLS = ('Agent', 'Task', 'SendMessage', 'Workflow')  # starting or steering an agent
STABLE = os.path.expanduser('~/.local/share/claude/stable/claude')  # the kit's fixed copy, when the server is on
CLAUDE = STABLE if os.access(STABLE, os.X_OK) else os.path.expanduser('~/.local/bin/claude')
MODEL = 'haiku'     # Claude Code's alias for the newest Haiku: fast and cheap, enough for a word check
TIMEOUT = 45        # seconds the check may take; the hook entry allows 60
MIN_PROSE = 40      # characters of prose below which a reply is not checked

LEAD = 'Sttark working rules (from Sttark Claude Kit): how Claude works for people at Sttark.'

RULES = """\
- Visuals are better than text. A diagram is a real image, never text art.
- Answer the person's questions first. Then keep working unless they say otherwise.
- A question is not an instruction. Do not infer one from it.
- Before building, give the plan in two lines plus a step count. If the work grows past that step count, stop \
and check in. Giving the plan is not asking: give it and start in the same turn.
- Do not ask for a go when the next step is clear and can be undone. Do it, then tell the person. Ask only \
before a step that deletes, sends, publishes or spends money, or when two ways lead to different work and the \
choice is the person's. Never end a turn with an offer such as "say the word" or "give me the go" for work you \
already recommend.
- Shortest reply that fully answers. One sentence is fine. Cut preamble, pleasantries, restating the question, \
recaps of what you just did, closing offers, "let me know if". Never end with commentary on the work.
- Give a warning only when it changes what the person does. Put it first, not at the end.
- When the person gives an example, treat it as one instance of a pattern. Fix every instance.
- Don't know it? Search. Don't guess.
- Run the tool, show the result, then comment. No narration mid-task.
- Work like a manager, not a worker. Give each task that takes more than a few tool calls to a subagent that \
runs in the background, then come back to the person immediately. Reading, research, design and checks are tasks \
too: start the agent before your third tool call on that work, not after the work has grown. When they give several tasks, start one agent \
for each task in the same message, so they run at the same time. Use a fork agent when the task needs the chat \
context. Use a new agent with full instructions when it does not. Give each agent its own git worktree when two \
agents could change the same files. When an agent completes, tell the person in one or two lines what it found \
or did. Keep the chat for direction and decisions. Do the work in the chat only for one lookup or a one-line fix.
- When a prompt holds more than one ask, number the asks. At every end of turn, give a table with each ask \
and its status, each status starting with its icon so the person sees it at a glance: ✅ Done, 🔄 In progress, \
🔴 Needs you (say what you need), ⚪ Dropped (say why). Keep each ask in the table until it is done or the \
person drops it. Nothing may go missing without showing in the table. Each row shows exactly one status icon, \
never two in one cell (not "🔄 In progress. Then 🔴 you select"). When one part of an ask is in progress and \
one part needs the person, show the icon of the state that matters now and say the other part in words, or \
split the ask into two rows.
- Waits on others: before you end a turn that waits on someone or something outside the session (a pull request \
someone else merges, a reply to an email, a check at a set time), hand the wait to Sttark Claude Kit with \
claude-wait (claude-wait pr <owner/repo#n> merged --by <deadline> --what "<what you watch for>" --why "<line>"; \
claude-wait email-reply <thread id> [--from <sender>] --by ... ; claude-wait at <time> --why ...; claude-wait \
check-script <path> --every 10m --by ... for anything a small script can check with no model, such as an API value, a \
page that changes or a tracking number, where exit 0 means it happened; claude-wait check-prompt "<yes/no question>" \
--every 1h --by ... only when nothing free works, since each check is a Haiku call). Prefer pr, at and check-script. \
Do the same when the person asks \
"let me know when they reply", "tell me when it merges" or the like, and when they ask "has X replied?" or "how long \
has it been?" about something no wait covers yet. The Kit watches it with no model calls and brings the session \
back when it happens, or at the deadline when it has not. You pick the deadline with judgment; there is no \
default. Weigh who you wait on and how fast they usually are (look at their past replies or merge times when that \
is cheap), how urgent the work is, and weekends. For example: a teammate who merges within hours, on work that \
blocks the line, gets the end of today; a supplier in China who answers overnight gets their next morning plus a \
day; a Friday request waits until Monday afternoon. Put the deadline and its reason in --why, in one line \
("Monday 5 PM: the reviewer merges within a day, and Friday is short"). End the turn with one handoff line, such \
as: "I am watching for New Star's reply. If none by Mon 11/16 9 AM, I bring this session back and ask if we follow \
up. You can archive this session."
- When the Kit brings a session back (a prompt that starts "[Sttark Claude Kit] A wait you handed to the Kit has \
ended"), go on with the work, then send the person one message with claude-notify "<subject>" "<message>" \
[--link <url>]. It goes the way they picked under Reach me by. If its output tells you to call the \
PushNotification tool, do that too. The message must stand alone, so the person never needs to open the \
session: in a few short sentences, what happened, what the session is for, what is done, what it waits on now \
(with links, such as a pull request and its state), what it does next, and what the person must do, or "Nothing \
needed from you." Example: "Your reporter works again (v6, last report 5 min ago). Fix PR Sttark/workrouter#889 \
adds a retry for the 'fetch failed' error (v7); CI passes; open, waiting for a merge and deploy. After deploy, \
each person on v2 reinstalls once. Nothing needed from you." A reply to the person in a live chat stays in the \
session: no claude-notify.
- Repo work: pull latest from remote before you work, and read the project docs before you change anything. The \
projects have history.
- UI and layout: function over form. Usability is king. See it rendered before calling it done.
- Asana tasks: give the full URL, https://app.asana.com/0/0/[task_gid].
- No em-dashes or double hyphens in prose. Code, CLI flags and file syntax are exempt.
- End of turn: where we stand, what is left, what you need from the person. If nothing is left and nothing is \
needed, one line.
- Write replies in ASD-STE100 Simplified Technical English. Before you send a reply, check each word against the \
STE dictionary. Replace each word that is not approved."""

CHECK = """You check a reply for ASD-STE100 Simplified Technical English. The rules that matter:
- Only approved words, each with its one approved meaning. Common words that are not approved: caveat, utilize, \
leverage, ensure, in order to, prior to, robust, seamless, facilitate, implement (as "do"), perform (use "do"), \
commence, terminate (use "stop"), subsequently, approximately (use "about" with care), obtain (use "get"), \
require (use "need"), additional (use "more"), currently (use "now").
- Sentences of 20 words or fewer in instructions and 25 or fewer in descriptions.
- Active voice, present tense. No -ing nouns (use "the test" not "the testing"). No slang.
- Allowed as they are: technical names, product and place names, people's names, quoted terms, code, commands, \
file names, URLs and anything in backticks or a code block. Skip those.

Lean toward OK: name only clear breaks, the kind an STE editor marks on first read. A borderline word is fine.

Also look at how the reply ends. A second rule: Claude does not ask for a go before a step that is clear and \
can be undone. A reply that ends by asking permission for such a step ("say the word and I will build it", \
"give me the go", "want me to...?", "shall I...?") breaks it. It is fine to ask before a step that deletes, \
sends, publishes or spends money, or when two ways lead to different work and the choice is the person's. \
Lean toward OK here too.

Answer with the single word OK, or a list of at most 8 items, one per line, each "word or phrase: the approved \
word to use" or "sentence too long: its first five words...". When the ending asks for a go, add one line \
that is exactly: ASKS FOR A GO. Nothing else."""
GO = 'Your last reply asked for a go it did not need. Do not ask for a go: do the work, then report.'

NOTE = re.compile(r'<(system-reminder|command-[a-z-]+|local-command-[a-z-]+)>.*?</\1>', re.S)
FENCE = re.compile(r'```.*?```', re.S)


def log(line, tag='ste    '):
    with open(LOG, 'a') as f:
        f.write(time.strftime('%F %T ') + tag + line + '\n')


def cli_missing(sid):
    """True when there is no Claude Code to call. Logs one line an hour, not one per reply."""
    if os.access(CLAUDE, os.X_OK):
        return False
    mark = os.path.join(os.path.dirname(NOTES), 'no-claude-code.ste')
    try:
        if time.time() - os.path.getmtime(mark) < 3600:
            return True
    except OSError:
        pass
    os.makedirs(os.path.dirname(mark), exist_ok=True)
    open(mark, 'w').close()
    log('%s skipped: no Claude Code at ~/.local/bin/claude (menu: Install Claude Code)' % sid)
    return True


def notes(change):
    """Read and change the saved misses under a lock: {session id: [note, ...]}. Returns what change returns."""
    os.makedirs(os.path.dirname(NOTES), exist_ok=True)
    with open(NOTES, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            all_ = json.loads(f.read() or '{}')
        except ValueError:
            all_ = {}
        out = change(all_)
        f.seek(0)
        f.truncate()
        f.write(json.dumps(all_))
        return out


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content
                         if isinstance(b, dict) and b.get('type') == 'text')
    return ''


def last_reply(path):
    """Claude's final reply of the turn: the assistant text after the last user entry (a prompt or a
    tool result), in order, from the session transcript."""
    try:
        with open(path) as f:
            lines = f.readlines()[-400:]
    except OSError:
        return ''
    parts = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('type') == 'user':
            break
        if e.get('type') == 'assistant':
            t = text_of((e.get('message') or {}).get('content'))
            if t.strip():
                parts.append(t)
    return NOTE.sub('', '\n'.join(reversed(parts))).strip()


def is_prompt(e):
    """A turn start: a message from the person or a task notification, not a tool result or a meta line."""
    if e.get('type') != 'user' or e.get('isMeta') or e.get('isSidechain'):
        return False
    c = (e.get('message') or {}).get('content')
    if isinstance(c, list):
        return any(isinstance(b, dict) and b.get('type') == 'text' for b in c) and not any(
            isinstance(b, dict) and b.get('type') == 'tool_result' for b in c)
    return isinstance(c, str)


def is_person(e):
    return is_prompt(e) and not text_of((e.get('message') or {}).get('content')).lstrip().startswith(
        '<task-notification>')


def chat_calls(path):
    """(tool calls the session made itself since the person's last message, of them made before the turn that
    just ended, whether any of them started or steered an agent). Subagent lines (sidechain) don't count."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4000000))
            lines = f.read().decode('utf-8', 'replace').splitlines()
    except (OSError, TypeError):
        return 0, 0, False
    calls, before, agent = 0, 0, False
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('isSidechain'):
            continue
        if is_person(e):
            calls, before, agent = 0, 0, False
        elif is_prompt(e):  # a task notification starts a new turn of the same piece of work
            before = calls
        elif e.get('type') == 'assistant':
            for b in (e.get('message') or {}).get('content') or []:
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    calls += 1
                    agent = agent or b.get('name') in AGENT_TOOLS
    return calls, before, agent


ICONS = ('✅', '🔄', '🔴', '⚪')


def icon_check(data):
    """No model call: a status table row with more than one status icon in one cell gets a note in front of
    the session's next prompt."""
    full = data.get('session_id') or ''
    if not full:
        return
    bad = [c.strip() for line in prose(last_reply(data.get('transcript_path') or '')).splitlines()
           if line.strip().startswith('|') for c in line.strip().strip('|').split('|')
           if sum(c.count(i) for i in ICONS) > 1]
    if not bad:
        return
    notes(lambda a: a.__setitem__(full, (a.get(full, []) + [
        'Your last status table had a cell with more than one status icon (%s). Show exactly one icon per row: '
        'the state that matters now, with the other part in words, or split the ask into two rows.'
        % bad[0][:80]])[-3:]))
    log('%s status cell with more than one icon: noted for the next prompt' % full[:8], 'icons  ')


def manager_check(data):
    """No model call: a turn that made more than MANAGER_MAX tool calls in the chat with no agent gets a note
    in front of the session's next prompt. Noted once, in the turn that passed the count."""
    full = data.get('session_id') or ''
    calls, before, agent = chat_calls(data.get('transcript_path') or '')
    if agent or calls <= MANAGER_MAX or before > MANAGER_MAX or not full:
        return
    notes(lambda a: a.__setitem__(full, (a.get(full, []) + [
        'This work made %d tool calls in the chat and started no agent. Give work of more than a few tool calls '
        'to a background agent, and keep the chat for the person.' % calls])[-3:]))
    log('%s %d tool calls in the chat, no agent: noted for the next prompt' % (full[:8], calls), 'agents ')


def prose(text):
    """The reply without its code blocks: what the check reads."""
    return FENCE.sub('', text).strip()


def at_limit(sid=None, transcript=None):
    """True when this session must wait under its usage setting (limit-hook.py); with no session, at the
    usage limit when no one chose usage credits."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'limit', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'limit-hook.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.held(sid, transcript)
    except Exception:
        return False


def ask(text, sid=None, transcript=None):
    """Haiku's list of breaks, or OK. Hooks off and this session's variables dropped, so the check is a plain
    call that never starts another check. Skipped (OK) while the session waits at its usage limit or its own
    hold, so it spends nothing."""
    if at_limit(sid, transcript):
        return 'OK'
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['STE_JUDGE'] = '1'
    t = text if len(text) <= 6000 else text[:3000] + '\n[...]\n' + text[-3000:]
    r = subprocess.run(
        [CLAUDE, '-p', '--model', MODEL, '--effort', 'low', '--no-session-persistence', '--strict-mcp-config',
         '--tools', '', '--settings', '{"disableAllHooks":true}', '--system-prompt', CHECK,
         'Reply to check:\n\n' + t],
        capture_output=True, text=True, timeout=TIMEOUT, env=env, cwd='/tmp')
    if r.returncode:
        raise RuntimeError('exit %d %s' % (r.returncode, (r.stderr or r.stdout).strip()[:120]))
    return r.stdout.strip()


def check(data):
    full = data.get('session_id') or ''
    sid = full[:8]
    if data.get('stop_hook_active'):
        return  # another hook sent this reply back; its rewrite isn't checked again
    text = prose(last_reply(data.get('transcript_path') or ''))
    if len(text) < MIN_PROSE:
        return
    if cli_missing(sid):
        return
    t0 = time.time()
    try:
        answer = ask(text, full or None, data.get('transcript_path'))
    except Exception as e:
        return log('%s error %s: %s' % (sid, type(e).__name__, str(e)[:160]))
    secs = time.time() - t0
    if not answer:
        return log('%s error empty answer (%.1fs)' % (sid, secs))
    if answer.strip().upper().rstrip('.') == 'OK':
        return log('%s ok (%.1fs)' % (sid, secs))
    lines = [l.strip(' -*') for l in answer.splitlines() if l.strip()]
    asks = any(l.upper().rstrip('.') == 'ASKS FOR A GO' for l in lines)
    items = [l for l in lines if l.upper().rstrip('.') not in ('ASKS FOR A GO', 'OK')][:8]
    if (not items and not asks) or len(answer) > 1200:  # not the list asked for: let the reply through
        return log('%s error unreadable answer %r (%.1fs)' % (sid, answer[:80], secs))
    note = []
    if items:
        note.append('Your last reply had words that are not STE: ' + '; '.join(items)
                    + '. Use the approved words from now on.')
    if asks:
        note.append(GO)
    if full:
        notes(lambda a: a.__setitem__(full, (a.get(full, []) + [' '.join(note)])[-3:]))
    log('%s noted for the next prompt (%.1fs): %s'
        % (sid, secs, '; '.join(items + (['asks for a go'] if asks else []))))


def pending(data):
    """The saved misses for this session, cleared as they are read."""
    full = data.get('session_id') or ''
    return notes(lambda a: a.pop(full, [])) if full else []


def main():
    if os.environ.get('STE_JUDGE') or os.environ.get('EFFORT_JUDGE'):
        return
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if '--check' in sys.argv:
        try:
            manager_check(data)
        except Exception as e:
            log('%s error manager check %s: %s' % ((data.get('session_id') or '')[:8], type(e).__name__, e), 'agents ')
        try:
            icon_check(data)
        except Exception as e:
            log('%s error icon check %s: %s' % ((data.get('session_id') or '')[:8], type(e).__name__, e), 'icons  ')
        return check(data)
    text = LEAD + '\n\n' + RULES
    try:
        missed = pending(data)
    except OSError:
        missed = []
    if missed:
        text += '\n\nFrom the check of your last reply: ' + ' '.join(missed)
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': text}}))


if __name__ == '__main__':
    main()
