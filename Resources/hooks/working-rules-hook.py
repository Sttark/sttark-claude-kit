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

Logged to ~/Library/Logs/sttark-claude-kit.log, lines starting "ste".
"""
import fcntl, json, os, re, subprocess, sys, time

LOG = os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
NOTES = os.path.expanduser('~/Library/Application Support/SttarkClaudeKit/working-notes.json')  # misses per session
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
runs in the background, then come back to the person immediately. When they give several tasks, start one agent \
for each task in the same message, so they run at the same time. Use a fork agent when the task needs the chat \
context. Use a new agent with full instructions when it does not. Give each agent its own git worktree when two \
agents could change the same files. When an agent completes, tell the person in one or two lines what it found \
or did. Keep the chat for direction and decisions. Do the work in the chat only for one lookup or a one-line fix.
- When a prompt holds more than one ask, number the asks. At every end of turn, give a table with each ask \
and its status, each status starting with its icon so the person sees it at a glance: ✅ Done, 🔄 In progress, \
🔴 Needs you (say what you need), ⚪ Dropped (say why). Keep each ask in the table until it is done or the \
person drops it. Nothing may go missing without showing in the table.
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


def log(line):
    with open(LOG, 'a') as f:
        f.write(time.strftime('%F %T ') + 'ste    ' + line + '\n')


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


def prose(text):
    """The reply without its code blocks: what the check reads."""
    return FENCE.sub('', text).strip()


def at_limit():
    """True at the usage limit when no one chose usage credits (limit-hook.py)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'limit', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'limit-hook.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.held()
    except Exception:
        return False


def ask(text):
    """Haiku's list of breaks, or OK. Hooks off and this session's variables dropped, so the check is a plain
    call that never starts another check. Skipped (OK) at the usage limit, so it spends nothing."""
    if at_limit():
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
    t0 = time.time()
    try:
        answer = ask(text)
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
