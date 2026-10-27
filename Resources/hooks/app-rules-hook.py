#!/usr/bin/python3
"""Claude Code hook: in a session working on a Sttark app, add the Apps chapters of the
Sttark Brand and App Guidelines to the session once. Installed by the Sttark Claude Kit app.

Which sessions (app_kind): the prompt's working folder is in a git repo (a worktree counts)
whose origin is any Sttark repo, or that has no origin yet (a new app), and the repo has
screens: tracked or new files a page is made of (SCREENS). A Sttark repo without screens,
such as a machine's controller, gets nothing until one is added; a repo of anyone else gets
nothing. A folder outside any git repo, and a new repo without screens yet, get one short
line instead (POINTER): read the chapters first if the session builds a Sttark app or page,
and set up a new app with the setup command. The check runs again at every prompt, so a new
app that gains its first page gets the chapters at the next prompt.

UserPromptSubmit, with a part number (1 to PARTS): each part adds its share of the chapters
as additionalContext, the first time in each session. Claude Code saves any hook
text over 10,000 characters to a file and shows only a preview, so the chapters go in
parts of under that, one per hook entry; the entries run side by side.

SessionStart (compact), with --compacted: a compacted session forgets them, so the next
prompt adds them again.

The chapters live on docs.sttark.com, which needs sign-in. Two sources keep the saved copy
current, and the hook uses whichever has the higher revision:

- At a session's first prompt, it reads app-rules.md on Sttark/sttark-docs main with gh
  (4 seconds at most): the five chapters word for word, which that repo's app-rules
  workflow renders from the published chapters twice a day and right after a chapter is
  published. So a newly published revision reaches the next session, not the next day.
  The parts run side by side; the first one checks while the others wait for it, and a
  check in the last 5 minutes counts. If gh cannot read it, the saved copy is used.
- --refresh reads them through Claude Code's Sttark Workrouter connector (docs_read), as
  this Mac's own Claude Code user, and keeps the tool's own output, never a model's
  retyping. The hook never waits for it: it starts one in the background when the saved
  copy is a day old.

With no copy at all, the hook tells Claude to read the chapters itself. Nothing of the
chapters is kept in this repo.

Logged to ~/Library/Logs/sttark-claude-kit.log, lines starting "rules".
"""
import fcntl, glob, json, os, re, shutil, subprocess, sys, time

SUPPORT = os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
DIR = os.path.join(SUPPORT, 'app-rules')
CACHE = os.path.join(DIR, 'chapters.json')
TRIED = os.path.join(DIR, 'refresh.tried')
SEEN = os.path.join(DIR, 'seen')
CHECKED = os.path.join(DIR, 'checked')
LOG = os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
STABLE = os.path.expanduser('~/.local/share/claude/stable/claude')  # the kit's fixed copy, when the server is on
CLAUDE = STABLE if os.access(STABLE, os.X_OK) else os.path.expanduser('~/.local/bin/claude')

ORIGIN = re.compile(r'[:/]Sttark/([A-Za-z0-9_.-]+?)(?:\.git)?/?$', re.I)
# Files a page is made of. node_modules and build output are ignored by git, so they don't count.
SCREENS = ('*.astro', '*.tsx', '*.jsx', '*.vue', '*.svelte', '*.html', '*.css', '*.scss',
           '*.blade.php', '*.twig', '*.erb')
# The setup command for a new app: the page check, the AI review and the agent notes.
SETUP = ("gh api -H 'Accept: application/vnd.github.raw' repos/Sttark/sttark-docs/contents/page-check/setup.mjs"
         " > \"$TMPDIR/sttark-setup.mjs\" && node \"$TMPDIR/sttark-setup.mjs\"")
GUIDE = '/company/sttark-brand-and-app-guidelines/guide'
CHAPTERS = ('building-web-apps', 'look', 'pages-and-behavior', 'sign-in-and-access', 'checks')
TOOL = 'mcp__claude_ai_Sttark_Workrouter__docs_read'
PARTS = 8           # hook entries install-hooks.py adds; room for the chapters to grow
SIZE = 9000         # characters per part, under Claude Code's 10,000
STALE = 24 * 3600   # refresh a copy older than this
RETRY = 3600        # but try at most once an hour
CHECK_EVERY = 300   # a session's first prompt checks sttark-docs main, unless one did this recently
GH = next((p for p in (shutil.which('gh'), '/opt/homebrew/bin/gh', '/usr/local/bin/gh')
           if p and os.access(p, os.X_OK)), None)
MARK = re.compile(r'^<!-- (%s/[a-z-]+), revision (\d+) -->$' % re.escape(GUIDE), re.M)

LEAD = ("These are the rules for Sttark apps (the Apps chapters of the Sttark Brand and App Guidelines on "
        "docs.sttark.com, added by Sttark Claude Kit because this session works in a Sttark app repo). "
        "Follow them for any UI work, and run the Checks chapter's Before you ship list. An app without "
        "scripts/page-check.mjs has no page check yet: when the work is building a new app, or the "
        "person asks, set one up in the repo root with " + SETUP + ".")
POINTER = ("Sttark Claude Kit: if this session builds or changes a web app or page for Sttark, first read the "
           "Apps chapters of the Sttark Brand and App Guidelines with the Sttark Workrouter docs_read tool: "
           + ', '.join(f'{GUIDE}/{n}' for n in CHAPTERS) + ". Set up a new app, once it is a git repo, with "
           + SETUP + " (the page check, the AI review and the agent notes). Otherwise ignore this line.")
# Code a session needs only when it builds that one thing (the logo's SVG, a Chat card's dots):
# left out of what is added, with where to find it, so the chapters fit and stay short.
CODE = re.compile(r'```(?:xml|svg)\n.*?```', re.S)
LEFT_OUT = '(Code left out here; read it in this chapter with docs_read when you need it.)'


def log(line):
    with open(LOG, 'a') as f:
        f.write(time.strftime('%F %T ') + 'rules  ' + line + '\n')


def git(cwd, *args):
    """git's output in cwd, or None when it fails (not a repo, no such setting)."""
    try:
        r = subprocess.run(['git', '-C', cwd, *args], capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def has_screens(cwd):
    """Whether the repo has a file a page is made of, committed or new."""
    for args in (('ls-files', '--'), ('ls-files', '--others', '--exclude-standard', '--')):
        if git(cwd, *args, *SCREENS):
            return True
    return False


def app_kind(cwd):
    """('app', name) for a Sttark app repo, or a new repo with screens; ('pointer', None) for a
    folder outside any repo, or a new repo without screens yet; None otherwise."""
    if git(cwd, 'rev-parse', '--show-toplevel') is None:
        return ('pointer', None)
    url = git(cwd, 'config', '--get', 'remote.origin.url')
    if url:
        m = ORIGIN.search(url)
        return ('app', m.group(1)) if m and has_screens(cwd) else None
    top = git(cwd, 'rev-parse', '--show-toplevel')
    return ('app', os.path.basename(top)) if has_screens(cwd) else ('pointer', None)


def cached():
    try:
        with open(CACHE) as f:
            c = json.load(f)
        if [x['path'] for x in c['chapters']] == [f'{GUIDE}/{n}' for n in CHAPTERS]:
            return c
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def revision(c):
    """The highest chapter revision in a copy (the guide's revision), 0 when unknown."""
    return max([int(x['revision']) for x in (c or {}).get('chapters', []) if str(x['revision']).isdigit()] or [0])


def from_sttark_docs():
    """The chapters from app-rules.md on Sttark/sttark-docs main, or None."""
    if not GH:
        return None
    try:
        r = subprocess.run([GH, 'api', '-H', 'Accept: application/vnd.github.raw',
                            'repos/Sttark/sttark-docs/contents/app-rules.md?ref=main'],
                           capture_output=True, text=True, timeout=4)
    except Exception:
        return None
    if r.returncode:
        return None
    marks = list(MARK.finditer(r.stdout))
    found = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(r.stdout)
        found[m.group(1)] = {'path': m.group(1), 'revision': m.group(2), 'text': r.stdout[m.end():end].strip()}
    paths = [f'{GUIDE}/{n}' for n in CHAPTERS]
    if not all(found.get(p, {}).get('text') for p in paths):
        return None
    return {'fetched': time.time(), 'source': 'Sttark/sttark-docs app-rules.md', 'chapters': [found[p] for p in paths]}


def check_current():
    """At a session's first prompt: if app-rules.md on sttark-docs main is a newer revision than
    the saved copy, save it. The parts call this side by side: the first takes the lock and
    checks, the others wait (5 seconds at most) and then read what it saved."""
    os.makedirs(DIR, exist_ok=True)
    with open(os.path.join(DIR, 'check.lock'), 'w') as lock:
        until = time.time() + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() > until:
                    return
                time.sleep(0.1)
        try:
            if time.time() - os.path.getmtime(CHECKED) < CHECK_EVERY:
                return
        except OSError:
            pass
        open(CHECKED, 'w').close()
        t = time.time()
        new, old = from_sttark_docs(), cached()
        if not new:
            return log('check: could not read app-rules.md on sttark-docs main; using the saved copy')
        if old and revision(old) >= revision(new):
            return
        tmp = CACHE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(new, f)
        os.replace(tmp, CACHE)
        log(f'check: revision {revision(old) or "none"} -> {revision(new)} from sttark-docs main ({time.time() - t:.1f}s)')


def parts(c):
    """The lead line and the chapters, split at paragraph breaks into pieces of at most SIZE characters."""
    text = LEAD + '\n\n' + '\n\n'.join(f'<!-- {x["path"]}, revision {x["revision"]} -->\n'
                                        + CODE.sub(LEFT_OUT, x['text']) for x in c['chapters'])
    out, cur = [], ''
    for para in text.split('\n\n'):
        while len(para) > SIZE:  # a single paragraph longer than a part: cut it at a line break
            cut = para.rfind('\n', 0, SIZE)
            cut = cut if cut > 0 else SIZE
            if cur:
                out.append(cur); cur = ''
            out.append(para[:cut]); para = para[cut:].lstrip('\n')
        if cur and len(cur) + 2 + len(para) > SIZE:
            out.append(cur); cur = ''
        cur = cur + '\n\n' + para if cur else para
    if cur:
        out.append(cur)
    return out


def start_refresh():
    """A refresh in the background, at most once an hour; the hook doesn't wait for it."""
    try:
        if time.time() - os.path.getmtime(TRIED) < RETRY:
            return
    except OSError:
        pass
    os.makedirs(DIR, exist_ok=True)
    open(TRIED, 'w').close()
    subprocess.Popen(['/usr/bin/python3', os.path.abspath(__file__), '--refresh'], cwd=DIR,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def refresh():
    os.makedirs(DIR, exist_ok=True)
    with open(os.path.join(DIR, 'refresh.lock'), 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return  # another refresh is running
        open(TRIED, 'w').close()
        t = time.time()
        prompt = (f'Call {TOOL} once for each of these paths, in this order, and then reply "done":\n'
                  + '\n'.join(f'{GUIDE}/{n}' for n in CHAPTERS))
        try:
            r = subprocess.run([CLAUDE, '-p', '--output-format', 'stream-json', '--verbose', '--model', 'haiku',
                                '--allowedTools', TOOL, '--settings', '{"disableAllHooks":true}'],
                               input=prompt, capture_output=True, text=True, timeout=300, cwd=DIR)
        except Exception as e:
            return log(f'refresh failed: {type(e).__name__}')
        found = {}
        for line in r.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            content = (ev.get('message') or {}).get('content') if isinstance(ev, dict) else None
            for part in content if isinstance(content, list) else []:
                if not isinstance(part, dict) or part.get('type') != 'tool_result':
                    continue
                c = part.get('content')
                text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else str(c or '')
                for n in CHAPTERS:
                    if text.startswith(f'[{GUIDE}/{n} '):
                        found[n] = text
        missing = [n for n in CHAPTERS if n not in found]
        if missing:
            return log(f'refresh failed: could not read {", ".join(missing)} (exit {r.returncode}, {time.time() - t:.0f}s)')
        chapters = []
        for n in CHAPTERS:
            m = re.search(r'revision (\d+)', found[n].split('\n', 1)[0])
            chapters.append({'path': f'{GUIDE}/{n}', 'revision': m.group(1) if m else '?',
                             'text': re.sub(r'^\[[^\n]*\]\n+', '', found[n]).strip()})
        tmp = CACHE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'fetched': time.time(), 'chapters': chapters}, f)
        os.replace(tmp, CACHE)
        log(f'refresh ok: {len(chapters)} chapters, revisions {" ".join(c["revision"] for c in chapters)} '
            f'({time.time() - t:.0f}s)')


def seen_file(sid, part):
    return os.path.join(SEEN, f'{re.sub(r"[^A-Za-z0-9_-]", "_", sid)}.{part}')


def main():
    if '--refresh' in sys.argv:
        return refresh()
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    sid = data.get('session_id') or ''
    if '--compacted' in sys.argv:  # the session forgot them: the next prompt adds them again
        for f in glob.glob(seen_file(sid, '*')):
            os.remove(f)
        return
    try:
        part = int(sys.argv[1])
    except (IndexError, ValueError):
        part = 1
    cwd = data.get('cwd') or os.getcwd()
    if not sid or os.path.exists(seen_file(sid, part)):
        return
    kind = app_kind(cwd)
    if not kind:
        return
    if kind[0] == 'pointer':  # once per session, from the first part; the chapters can still follow
        if part == 1 and not os.path.exists(seen_file(sid, 'pointer')):
            os.makedirs(SEEN, exist_ok=True)
            open(seen_file(sid, 'pointer'), 'w').close()
            log(f'{sid[:12]}… pointer: {cwd}')
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': POINTER}}))
        return
    app = kind[1]
    check_current()
    c = cached()
    if part == 1 and (not c or time.time() - os.path.getmtime(CACHE) > STALE):
        start_refresh()
    if c:
        pieces = parts(c)
        text = pieces[part - 1] if part <= len(pieces) else ''
        if part == PARTS and len(pieces) > PARTS:  # outgrew the hook entries: point at the rest
            text += ('\n\n(The rest of the chapters did not fit. Read them with docs_read: '
                     + ', '.join(x['path'] for x in c['chapters']) + ')')
        if text and len(pieces) > 1:
            text = f'[Sttark app rules, part {part} of {min(len(pieces), PARTS)}]\n\n' + text
    elif part == 1:
        text = (LEAD + ' Read these five chapters now with the Sttark Workrouter docs_read tool, in order: '
                + ', '.join(f'{GUIDE}/{n}' for n in CHAPTERS) + '.')
    else:
        text = ''
    os.makedirs(SEEN, exist_ok=True)
    open(seen_file(sid, part), 'w').close()
    if part == 1:
        log(f'{sid[:12]}… {app}: ' + (f'added {len(parts(c))} parts, revisions '
                                       + ' '.join(x['revision'] for x in c['chapters']) if c
                                       else 'no copy yet, told Claude to read them'))
        for f in glob.glob(os.path.join(SEEN, '*')):  # forget sessions over a week old
            try:
                if time.time() - os.path.getmtime(f) > 7 * 86400:
                    os.remove(f)
            except OSError:
                pass
    if text:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': text}}))


if __name__ == '__main__':
    main()
