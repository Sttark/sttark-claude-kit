#!/usr/bin/python3
"""Claude Code hook: keep sessions out of the person's own Chrome while "Claude window in Chrome" is on.
Installed and kept up to date by the Sttark Claude Kit app.

The effort hook puts a browser rule in front of every prompt, but subagents never see it, and a main session
does not always follow it. This hook stops the steps that open Chrome, or bring it to the front, while the
person types:

PreToolUse (matcher Bash|mcp__claude-in-chrome__.*|mcp__Control_Chrome__.*): it denies
- every Claude in Chrome tool (mcp__claude-in-chrome__*) and every Control Chrome tool (mcp__Control_Chrome__*);
- a Bash command whose command word is `open` with `-a Chrome`, `-a "Google Chrome"`, `-b com.google.Chrome`,
  or an http(s) address;
- `osascript` (AppleScript or JavaScript) that tells "Google Chrome" (or com.google.Chrome) to do something;
- the Chrome program itself (Google Chrome.app/Contents/MacOS/Google Chrome) run without --headless and
  without --user-data-dir, which is the person's own Chrome.
The reason tells Claude to use claude-window (go, url, text, js, done) for signed-in pages in the person's
Chrome, or the built-in browser pane (mcp__Claude_Browser__*) for localhost and public pages.
It lets through claude-window itself, `open <file>`, `open -a Preview`, ps, grep and pkill lines that name
Chrome, and test browsers (Playwright, Puppeteer, Chromium, a headless Chrome or one with its own
--user-data-dir). Text that only mentions such a command (an echo, a heredoc into a file) is let through too.

UserPromptSubmit: when the person asks for Claude in Chrome by name ("use Claude in Chrome", "control chrome",
"in my Chrome", "my own Chrome tab"), the session goes in chrome_ok in the state file, and the hook then lets
every call of that session through, its agents' calls too (they come with the session's id). Claude can't do
this for itself: only a message typed to the session counts.

The hook reads claude_window from the state file on each call and lets everything through when that switch
is off. On any error it lets the call through. Each deny and each opt-in is logged to
~/Library/Logs/sttark-claude-kit.log with the tag browser.
"""
import json, os, re, shlex, sys, time

DIR = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(DIR, 'state.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
KEEP_DAYS = 7      # a chrome_ok entry older than this is dropped
LOCK_WAIT = 5      # seconds to wait for the state file's lock

MCP = ('mcp__claude-in-chrome__', 'mcp__Control_Chrome__')

REASON = ("Sttark Claude Kit stopped this step: it opens or brings forward the person's own Chrome while they type. "
          "For signed-in pages in their Chrome, use the claude-window command: claude-window go <url>, then "
          "claude-window url, text, js '<code>', and claude-window done when you have finished. For localhost and "
          "public pages, use the built-in browser pane (the mcp__Claude_Browser__* tools) if this session has it. "
          "Never open or activate Chrome another way (Claude in Chrome, Control Chrome, open -a Chrome, open <url>, "
          "osascript to Chrome). Only the person can allow Claude in Chrome for this session, by asking for it by "
          "name in a message.")

OPT_IN = re.compile(r"claude[ -]in[ -]chrome|control[ _]chrome|my (own )?chrome (tab|window|session|profile)|in my (own )?chrome",
                    re.I)
NOT_BEFORE = re.compile(r"\b(don'?t|do not|never|not|no|stop|without|instead of|avoid)\b[^.!?\n]{0,25}$", re.I)

CHROME_APP = re.compile(r"^((/[^/]*)*/)?(google )?chrome(\.app)?/?$", re.I)
OSA_CHROME = re.compile(r"""tell\s+application\s+(id\s+)?["'](google chrome|com\.google\.chrome)["']"""
                        r"""|application\s*\(\s*["'](google chrome|com\.google\.chrome)["']\s*\)""", re.I)
CHROME_BIN = 'Google Chrome.app/Contents/MacOS/Google Chrome'
PREFIX = {'sudo', 'env', 'nohup', 'exec', 'command', 'time', 'then', 'do', 'else', 'elif', 'if', 'while', 'until',
          '!', '{', '(', 'caffeinate', 'arch'}
SHELLS = {'sh', 'bash', 'zsh', 'dash'}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'browser ' + line + '\n')
    except OSError:
        pass


def peek():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def who(data):
    w = (data.get('session_id') or '')[:8] or '?'
    a = data.get('agent_id') or ''
    return w + ('/' + a[:8] if a else '')


# ---- Bash: find the command words, outside quotes and heredoc bodies ----

def logical_lines(cmd):
    """The command's lines, each with the text of the heredocs it starts (kept apart, so text written into a file
    is never read as a command, but osascript still sees the script it is fed)."""
    out, lines, i = [], cmd.split('\n'), 0
    while i < len(lines):
        line, body = lines[i], []
        i += 1
        for m in HEREDOC.finditer(line.replace('<<<', '   ')):
            end = m.group(2)
            while i < len(lines) and lines[i].strip() != end:
                body.append(lines[i])
                i += 1
            i += 1
        out.append((line, '\n'.join(body)))
    return out


def segments(line):
    """Split one line into simple commands at ; & | ( ) ` and $( outside quotes."""
    segs, cur, q, i = [], [], '', 0
    while i < len(line):
        ch = line[i]
        if q == "'":
            cur.append(ch)
            if ch == "'":
                q = ''
        elif ch == '\\' and i + 1 < len(line):
            cur.append(line[i:i + 2])
            i += 1
        elif ch == '$' and line[i + 1:i + 2] == '(':
            segs.append(''.join(cur))
            cur = []
            i += 1
        elif ch == '`' or (not q and ch in ';&|()'):
            segs.append(''.join(cur))
            cur = []
        elif q == '"':
            cur.append(ch)
            if ch == '"':
                q = ''
        else:
            if ch in '"\'':
                q = ch
            elif ch == '#' and (not cur or cur[-1] in ' \t'):
                break   # a comment
            cur.append(ch)
        i += 1
    segs.append(''.join(cur))
    return [s.strip() for s in segs if s.strip()]


def words(seg):
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def command_of(ws):
    """The command word and its arguments, past assignments and words like sudo, env, nohup."""
    i = 0
    while i < len(ws):
        w = ws[i]
        if re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', w):
            i += 1
        elif w in PREFIX:
            i += 1
            while w in ('sudo', 'env', 'nohup', 'time', 'caffeinate', 'arch') and i < len(ws) and ws[i].startswith('-'):
                i += 2 if ws[i] in ('-u', '-g', '-C', '-D', '-h', '-p', '-r', '-t', '-U', '-w', '-P') else 1
        else:
            break
    return ws[i:]


def bash_reason(cmd, depth=0):
    """What in the command would open or bring forward the person's Chrome, or ''."""
    for line, body in logical_lines(cmd):
        for seg in segments(line):
            ws = command_of(words(seg))
            if not ws:
                continue
            name = os.path.basename(ws[0])
            args = ws[1:]
            if name == 'open':
                r = open_reason(args)
                if r:
                    return r
            elif name == 'osascript':
                if OSA_CHROME.search(line) or OSA_CHROME.search(body) or OSA_CHROME.search(' '.join(args)):
                    return 'osascript tells Google Chrome'
            elif ws[0].endswith(CHROME_BIN) or ws[0].endswith('Google Chrome.app/Contents/MacOS/Google\\ Chrome'):
                if not any(a.startswith(('--headless', '--user-data-dir', '--version')) for a in args):
                    return "runs the person's Chrome"
            elif name in SHELLS and depth < 2:
                for j, a in enumerate(args[:-1]):
                    if a.startswith('-') and 'c' in a[1:] and not a.startswith('--'):
                        r = bash_reason(args[j + 1], depth + 1)
                        if r:
                            return r
                        break
    return ''


def open_reason(args):
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith('-') and not a.startswith('--') and len(a) > 1:
            flags = a[1:]
            if ('a' in flags or 'b' in flags) and i + 1 < len(args):
                app = args[i + 1]
                if 'a' in flags and CHROME_APP.match(app):
                    return 'open -a Chrome'
                if 'b' in flags and app.lower() == 'com.google.chrome':
                    return 'open -b com.google.Chrome'
                i += 2
                continue
        elif a.startswith('--'):
            pass
        elif re.match(r'^https?://', a, re.I):
            return 'open of a web address'
        i += 1
    return ''


# ---- the hook ----

def allowed(s, data):
    """The person asked for Claude in Chrome in this session (or the session this agent works for)."""
    sid = data.get('session_id') or ''
    e = (s.get('chrome_ok') or {}).get(sid)
    return bool(sid and isinstance(e, dict) and (e.get('at') or 0) > time.time() - KEEP_DAYS * 86400)


def on_tool(data):
    tool = data.get('tool_name') or ''
    if tool == 'Bash':
        cmd = (data.get('tool_input') or {}).get('command') or ''
        low = cmd.lower()
        if not ('open' in low or 'osascript' in low or 'chrome' in low):
            return
    elif not tool.startswith(MCP):
        return
    s = peek()
    if not s.get('claude_window') or allowed(s, data):
        return
    if tool == 'Bash':
        why = bash_reason(cmd)
        if not why:
            return
        what = f'Bash ({why}): {" ".join(cmd.split())[:120]}'
    else:
        what = tool
    log(f'deny   {who(data)} {what}')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                             'permissionDecisionReason': REASON}}))


def asks_for_chrome(prompt):
    p = prompt or ''
    if '<task-notification>' in p or p.lstrip().startswith('<'):
        return False   # an agent's result or a Kit message, not the person's words
    for m in OPT_IN.finditer(p):
        if not NOT_BEFORE.search(p[max(0, m.start() - 40):m.start()]):
            return True
    return False


def on_prompt(data):
    sid = data.get('session_id') or ''
    if not sid or not asks_for_chrome(data.get('prompt')):
        return
    s = peek()
    if not s.get('claude_window'):
        return
    import fcntl
    os.makedirs(DIR, exist_ok=True)
    with open(STATE + '.lock', 'w') as lock:
        end = time.time() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= end:
                    raise
                time.sleep(0.05)
        s = peek()
        old = time.time() - KEEP_DAYS * 86400
        ok = {k: v for k, v in (s.get('chrome_ok') or {}).items() if isinstance(v, dict) and (v.get('at') or 0) > old}
        ok[sid] = {'at': time.time(), 'cwd': data.get('cwd') or ''}
        s['chrome_ok'] = ok
        tmp = STATE + f'.{os.getpid()}.tmp'
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, STATE)
    log(f'allow  {sid[:8]} Claude in Chrome for this session and its agents (typed)')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext':
        "Sttark Claude Kit: the person asked for Claude in Chrome by name, so this session and its agents may "
        "use the Claude in Chrome and Control Chrome tools and open Chrome until the session ends. Use them only "
        "for what the person asked."}}))


def main():
    try:
        data = json.load(sys.stdin)
        event = data.get('hook_event_name')
        if event == 'PreToolUse':
            on_tool(data)
        elif event == 'UserPromptSubmit':
            on_prompt(data)
    except Exception as e:   # never stop a tool call or a message because of this hook
        log(f'error  {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
