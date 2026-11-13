#!/usr/bin/python3
"""Move a Claude Code session that runs only on this Mac onto Remote Control, with its whole conversation.

A session started in Terminal, or under "This computer" in the Claude desktop app, without Remote Control
lives only on this Mac: the phone, the Claude app's list and the Kit can't reach it. Moving it starts its saved
conversation again with `claude --resume <conversation> --remote-control`, which gives it a link of its own,
uploads its conversation there, and keeps working in the same folder with the same files. The Kit keeps it
running after that, as it keeps the sessions it starts on their own (keep() in effort-hook.py), so it comes back
on the same link after a restart. Archive it in the Claude app to stop it for good.

  migrate.py --scan            every minute, from the app: list the sessions that run only on this Mac (in
                               local-sessions.json, for the window) and move the ones waiting to move
  migrate.py <session> [--yes] move one; `claude-migrate` is a link to this script
  migrate.py --list            print the sessions that run only on this Mac
  migrate.py --finish <id>     (by itself, in the background) move a session once its reply ends

<session> is the conversation id, a unique start of it (6 characters or more), or the session's name.
A session that is open (in Terminal or in the desktop app) runs in one place only, so moving it closes it there:
that needs --yes. One that is in a reply moves when the reply ends. A session can move itself: run in it, the
command moves it when its current reply ends.

Exit codes: 0 moved (or moves when its reply ends, or is on Remote Control already), 1 failed, 2 no such session,
4 open: run again with --yes to close it there and move it.

Test variables: STTARK_KIT_DIR and STTARK_KIT_LOG (as the other hooks), STTARK_CLAUDE_DIR (in place of ~/.claude),
STTARK_DESKTOP_SESSIONS (the desktop app's session records), STTARK_MIGRATE_DRY=1 (decide and log, but start,
stop and rename nothing; the new link is made up).
"""
import calendar, fcntl, glob, importlib.util, json, os, re, shlex, signal, subprocess, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))  # claude-migrate is a link to this file
spec = importlib.util.spec_from_file_location('effort', os.path.join(HERE, 'effort-hook.py'))
effort = importlib.util.module_from_spec(spec)
spec.loader.exec_module(effort)

KIT = os.path.dirname(effort.STATE)
LOCAL = os.path.join(KIT, 'local-sessions.json')
CLAUDE_DIR = os.environ.get('STTARK_CLAUDE_DIR') or os.path.expanduser('~/.claude')
DESKTOP = os.environ.get('STTARK_DESKTOP_SESSIONS') or os.path.expanduser('~/Library/Application Support/Claude/claude-code-sessions')
DRY = bool(os.environ.get('STTARK_MIGRATE_DRY'))
DAYS = 7  # how far back a session that runs only on this Mac still shows
ENTRYPOINTS = {'cli': 'terminal', 'claude-desktop': 'desktop'}  # sessions a person started; `claude -p` runs are left out
PENDING_DAYS = 1  # a move that waits for a reply to end is dropped after this


def log(line):
    effort.log('migrate ' + line)


def short(sid):
    return sid[:8]


# MARK: what runs where

def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def live():
    """The Claude Code sessions running on this Mac now, from the files Claude Code keeps for each one in
    ~/.claude/sessions: {conversation id: {pid, status ('idle' or 'busy'), entrypoint, bridge}}."""
    out = {}
    for f in glob.glob(os.path.join(CLAUDE_DIR, 'sessions', '*.json')):
        try:
            d = json.load(open(f))
            pid = int(d.get('pid') or 0)
        except (OSError, ValueError, TypeError):
            continue
        sid = d.get('sessionId') or ''
        if not sid or not pid or not alive(pid):
            continue
        out[sid] = {'pid': pid, 'status': d.get('status') or 'idle', 'entrypoint': d.get('entrypoint') or '',
                    'bridge': d.get('bridgeSessionId') or ''}
    return out


def desktop_records():
    """The Claude desktop app's own records of its "This computer" sessions, by conversation id."""
    out = {}
    for f in glob.glob(os.path.join(DESKTOP, '**', 'local_*.json'), recursive=True):
        try:
            d = json.load(open(f))
        except (OSError, ValueError):
            continue
        if d.get('cliSessionId'):
            out[d['cliSessionId']] = d
    return out


def last_match(pattern, data):
    m = None
    for m in re.finditer(pattern, data):
        pass
    if not m:
        return ''
    try:
        return json.loads(b'"' + m.group(1) + b'"')
    except ValueError:
        return m.group(1).decode('utf-8', 'replace')


def first_user(data):
    """The first message a person typed in the conversation, and the entrypoint it came from."""
    for line in data.split(b'\n'):
        if b'"type":"user"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get('isSidechain') or d.get('isMeta'):
            continue
        c = (d.get('message') or {}).get('content')
        text = c if isinstance(c, str) else ' '.join(x.get('text', '') for x in c or [] if isinstance(x, dict) and x.get('type') == 'text')
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>[^<]*</[^>]+>', ' ', text)).strip()
        if text:
            return text, d.get('entrypoint') or ''
    return '', ''


def describe(path, data, desk=None):
    """What the window shows for one conversation, or None when it isn't one a person started."""
    head = data[:262144]
    text, entry = first_user(head)
    if entry not in ENTRYPOINTS or not text:
        return None
    sid = os.path.basename(path)[:-len('.jsonl')]
    title = (last_match(rb'"customTitle":"((?:[^"\\]|\\.)*)"', data) or (desk or {}).get('title')
             or last_match(rb'"aiTitle":"((?:[^"\\]|\\.)*)"', data) or (text[:60] + ('…' if len(text) > 60 else '')))
    stamp = last_match(rb'"timestamp":"([^"]+)"', data)
    try:  # the transcript's times are UTC
        last = calendar.timegm(time.strptime(stamp[:19], '%Y-%m-%dT%H:%M:%S'))
    except (ValueError, TypeError):
        last = os.path.getmtime(path)
    return {'id': sid, 'title': title.strip(), 'transcript': path,
            'cwd': last_match(rb'"cwd":"((?:[^"\\]|\\.)*)"', data) or os.path.expanduser('~'),
            'model': last_match(rb'"model":"(claude-[^"]+)"', data),
            'where': ENTRYPOINTS[entry], 'last': last}


def scan(days=DAYS):
    """The conversations a person started in Terminal or the desktop app in the last `days` that have no
    Remote Control link, newest first."""
    now, desk, running = time.time(), desktop_records(), live()
    out = []
    for path in glob.glob(os.path.join(CLAUDE_DIR, 'projects', '*', '*.jsonl')):
        try:
            if now - os.path.getmtime(path) > days * 86400:
                continue
            with open(path, 'rb') as f:
                head = f.read(262144)
                if not re.search(rb'"entrypoint":"(cli|claude-desktop)"', head):
                    continue
                data = head + f.read()
        except OSError:
            continue
        if b'"bridge-session"' in data:
            continue
        sid = os.path.basename(path)[:-len('.jsonl')]
        d = desk.get(sid)
        if d and (d.get('isArchived') or d.get('bridgeSessionIds')):
            continue
        r = running.get(sid)
        if r and r['bridge']:
            continue
        x = describe(path, data, d)
        if not x:
            continue
        if r:
            x.update(pid=r['pid'], busy=r['status'] != 'idle')
        out.append(x)
    return sorted(out, key=lambda x: x['last'], reverse=True)


def find(key):
    """The conversation `key` names: an id, a unique start of one (6 or more characters), or a name."""
    key = key.strip()
    rows = scan()
    for x in rows:
        if x['id'] == key:
            return x
    starts = [x for x in rows if len(key) >= 6 and x['id'].startswith(key)]
    if len(starts) == 1:
        return starts[0]
    named = [x for x in rows if x['title'].lower() == key.lower()]
    if len(named) == 1:
        return named[0]
    # an older one, or one on Remote Control already: by its id only
    for path in glob.glob(os.path.join(CLAUDE_DIR, 'projects', '*', key + '.jsonl')):
        with open(path, 'rb') as f:
            data = f.read()
        x = describe(path, data, desktop_records().get(key)) or {'id': key, 'title': 'Session ' + key[:6], 'transcript': path,
                                                               'cwd': os.path.expanduser('~'), 'model': '', 'where': 'terminal', 'last': os.path.getmtime(path)}
        r = live().get(key)
        if r:
            x.update(pid=r['pid'], busy=r['status'] != 'idle')
        return x
    return None


# MARK: the move

def links(transcript):
    """The Remote Control links Claude Code recorded in a conversation, oldest first."""
    try:
        with open(transcript) as f:
            return [json.loads(l).get('bridgeSessionId') for l in f if '"type":"bridge-session"' in l]
    except OSError:
        return []


def screen_text(name):
    path = os.path.join(KIT, f'.migrate-{name}.txt')
    try:
        subprocess.run(['/usr/bin/screen', '-S', name, '-p', '0', '-X', 'hardcopy', path], timeout=10)
        for _ in range(10):
            time.sleep(0.2)
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    t = f.read().decode('utf-8', 'replace')
                if t.strip():
                    return t
        return ''
    except Exception:
        return ''
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def launch(x):
    """Start the conversation with Remote Control in a screen named as keep() names the sessions it starts on
    their own (kit-<first 8 of the id>), in a clean environment so nothing from the app or another session leaks
    in (that turns transcript saving off). Returns the screen's name."""
    cid = x['id']
    name = 'kit-' + cid[:8]
    subprocess.run(['/usr/bin/screen', '-S', name, '-X', 'quit'], capture_output=True)
    stable = os.path.expanduser('~/.local/share/claude/stable/claude')
    claude = stable if os.access(stable, os.X_OK) else effort.CLAUDE
    home = os.path.expanduser('~')
    env = {'HOME': home, 'USER': os.environ.get('USER', ''), 'LOGNAME': os.environ.get('USER', ''),
           'SHELL': '/bin/zsh', 'TERM': 'xterm-256color', 'LANG': 'en_US.UTF-8',
           'PATH': f'{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'}
    cwd = x['cwd'] if os.path.isdir(x['cwd']) else home
    cmd = (f"cd {shlex.quote(cwd)} && exec {shlex.quote(claude)} --resume {cid} --remote-control "
           f"--permission-mode bypassPermissions" + (f" --model {shlex.quote(x['model'])}" if x.get('model') else ''))
    subprocess.run(['/usr/bin/screen', '-dmS', name, '/bin/zsh', '-lc', cmd], env=env, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # the app reads this command's output to its end
    return name


def wait_link(x, name, before, wait=90):
    """The new link, once Claude Code records it. Claude Code first asks whether to trust a folder it hasn't
    been trusted in; the session already ran there, so the Kit answers yes."""
    trusted = False
    for i in range(wait // 2):
        ids = links(x['transcript'])
        if len(ids) > before and ids[-1]:
            return ids[-1]
        if not trusted and i % 2 == 1 and 'trust this folder' in screen_text(name):
            subprocess.run(['/usr/bin/screen', '-S', name, '-p', '0', '-X', 'stuff', '\x1b[B'])
            time.sleep(0.5)
            subprocess.run(['/usr/bin/screen', '-S', name, '-p', '0', '-X', 'stuff', '\r'])
            trusted = True
        time.sleep(2)
    return ''


def close(pid):
    """Close a session where it's open now, as quitting it there would. True once it has quit."""
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    for _ in range(30):
        time.sleep(0.5)
        if not alive(pid):
            return True
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    time.sleep(1)
    return not alive(pid)


def register(x, new):
    """Keep it running from now on, as keep() keeps the sessions it starts on their own: started again on the
    same link after a restart (`own`: no wake through the server first, since the server doesn't run it)."""
    lock = open(os.path.join(KIT, 'keep.lock'), 'w')
    fcntl.flock(lock, fcntl.LOCK_EX)  # keep() writes `keep` whole when it's done; wait for it
    try:
        with effort.state() as s:
            k = s.setdefault('keep', {})
            k.setdefault('alone', {})[new] = {'transcript': x['transcript'], 'title': x['title'], 'at': time.time(),
                                              'own': True, 'model': x.get('model') or ''}
            s['sessions'].setdefault(new, {}).update(title=x['title'], title_at=time.time(), transcript=x['transcript'],
                                                     at=time.time(), migrated=x['id'])
            (s.get('migrate_pending') or {}).pop(x['id'], None)
    finally:
        lock.close()


def rename(new, title):
    """The new link's title in the Claude app: the session's own name, not its first message."""
    if DRY or not title:
        return
    for wait in (3, 15):
        time.sleep(wait)
        try:
            if effort.sse().session(new).get('title') != title:
                effort.sse().rename(new, title)
        except Exception as e:
            log(f'{new[4:12]} could not set "{title}" in the Claude app: {e!r}'[:300])
            return


def move(x, by):
    """Move one conversation now. Returns (exit code, what happened)."""
    lock = open(os.path.join(KIT, 'migrate.lock'), 'w')
    fcntl.flock(lock, fcntl.LOCK_EX)  # one move at a time, so a session never starts twice
    try:
        ids = links(x['transcript'])
        if ids:
            return 0, f'"{x["title"]}" is on Remote Control already.'
        r = live().get(x['id'])
        closed = ''
        if r:
            if r['bridge']:
                return 0, f'"{x["title"]}" is on Remote Control already.'
            if not DRY and not close(r['pid']):
                log(f'{short(x["id"])} "{x["title"]}" could not be closed where it runs (process {r["pid"]})')
                return 1, f'"{x["title"]}" did not close where it runs, so it did not move. Quit it there, then move it again.'
            closed = '; closed it in ' + ('the desktop app' if x['where'] == 'desktop' else 'Terminal')
        if DRY:
            new = 'cse_dry' + x['id'].replace('-', '')[:20]
        else:
            name = launch(x)
            new = wait_link(x, name, len(ids))
            if not new:
                subprocess.run(['/usr/bin/screen', '-S', name, '-X', 'quit'], capture_output=True)
                log(f'{short(x["id"])} "{x["title"]}" did not get a Remote Control link in 90 s ({by})')
                return 1, f'"{x["title"]}" did not get a Remote Control link. It stays on this Mac only; try again.'
        register(x, new)
        log(f'{short(x["id"])} "{x["title"]}" moved to Remote Control as {new}{closed} ({by})')
        rename(new, x['title'])
        return 0, f'"{x["title"]}" moved to Remote Control. It shows in the Claude app and on your phone, with its whole conversation.'
    finally:
        lock.close()


def queue(x, by):
    """Move it when its reply ends: the session's own command, or a move asked while it was in a reply."""
    with effort.state() as s:
        s.setdefault('migrate_pending', {})[x['id']] = {'at': time.time(), 'by': by, 'title': x['title']}
    log(f'{short(x["id"])} "{x["title"]}" moves when its reply ends ({by})')
    if not DRY:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), '--finish', x['id']], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, cwd=KIT)


def pending():
    return (effort.peek().get('migrate_pending') or {})


def finish(sid, wait=6 * 3600):
    """In the background: once the session's reply ends (or it quits), move it."""
    t0 = time.time()
    while time.time() - t0 < wait:
        if sid not in pending():
            return
        r = live().get(sid)
        if not r or r['status'] == 'idle':
            time.sleep(2)  # let it write the end of the reply
            r = live().get(sid)
            if not r or r['status'] == 'idle':
                x = find(sid)
                if x:
                    move(x, pending().get(sid, {}).get('by', 'queued'))
                drop(sid)
                return
        time.sleep(2)


def drop(sid):
    with effort.state() as s:
        (s.get('migrate_pending') or {}).pop(sid, None)


def do_scan():
    now = time.time()
    for sid, p in list(pending().items()):  # a move whose background wait was lost (a restart)
        if now - p.get('at', 0) > PENDING_DAYS * 86400:
            drop(sid)
            continue
        r = live().get(sid)
        if r and r['status'] != 'idle':
            continue
        x = find(sid)
        if x:
            move(x, p.get('by', 'queued'))
        drop(sid)
    rows = scan()
    waiting = pending()
    for x in rows:
        x['pending'] = x['id'] in waiting
    tmp = LOCAL + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'at': now, 'sessions': rows}, f, indent=1)
    os.replace(tmp, LOCAL)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__.strip())
        return 0
    if args[0] == '--scan':
        do_scan()
        return 0
    if args[0] == '--finish' and len(args) > 1:
        finish(args[1])
        return 0
    if args[0] == '--list':
        rows = scan()
        if not rows:
            print(f'No session runs only on this Mac (the last {DAYS} days).')
        for x in rows:
            state = ' · open, Claude working' if x.get('busy') else ' · open' if x.get('pid') else ''
            print(f"{x['id']}  {x['title']}  ({'desktop app' if x['where'] == 'desktop' else 'Terminal'}{state}; "
                  f"last active {time.strftime('%b %-d %-I:%M %p', time.localtime(x['last']))})")
        return 0
    yes = '--yes' in args
    by = 'window' if '--window' in args else 'command'
    keys = [a for a in args if not a.startswith('--')]
    if not keys:
        print('Name a session: its id, a start of it, or its name. See --list.')
        return 2
    x = find(keys[0])
    if not x:
        print(f'No session "{keys[0]}" on this Mac. See claude-migrate --list.')
        return 2
    if links(x['transcript']):
        print(f'"{x["title"]}" is on Remote Control already.')
        return 0
    itself = os.environ.get('CLAUDE_CODE_SESSION_ID') == x['id']
    if itself or x.get('busy'):
        if not itself and not yes:
            print(f'"{x["title"]}" is open, and Claude is in a reply. Run again with --yes: it moves when the reply ends, '
                  f'and closes where it runs now.')
            return 4
        queue(x, 'the session itself' if itself else by)
        print(f'"{x["title"]}" moves to Remote Control when this reply ends. It closes here then, and opens in the Claude '
              f'app and on your phone, with its whole conversation.')
        return 0
    if x.get('pid') and not yes:
        where = 'the Claude desktop app' if x['where'] == 'desktop' else 'Terminal'
        print(f'"{x["title"]}" is open in {where}. Run again with --yes to close it there and move it.')
        return 4
    code, words = move(x, by)
    print(words)
    return code


if __name__ == '__main__':
    sys.exit(main())
