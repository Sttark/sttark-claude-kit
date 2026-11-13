#!/usr/bin/python3
"""claude-wait: a session that waits on someone else hands the wait to Sttark Claude Kit, so the person can archive
the session. The Kit watches the wait with no model calls, and when the thing happens, or when the deadline comes and
it hasn't, brings the session back: it unarchives it on the same link with a prompt saying what happened, and the
session goes on and tells the person through Reach me by (claude-notify).

    claude-wait pr <owner/repo#n> merged|closed --by <deadline> --why "<deadline and reason, one line>"
    claude-wait at <time> --why "<what to check then, one line>"
    claude-wait email-reply <Gmail thread id> [--from <sender or domain>] --by <deadline> --why "<...>"
    claude-wait check-script <path> --every <10m|2h> --by <deadline> --why "<...>"   (exit 0 = it happened; free)
    claude-wait check-prompt "<yes/no question>" --every <30m> --by <deadline> --why "<...>"   (a Haiku call)
    --what "<what you watch for, in the person's words>"  (any wait; e.g. "New Star's reply about the laminator")
    claude-wait --list                 open waits, every session
    claude-wait --cancel <id>          drop a wait
    claude-wait --now <id>             bring its session back now
    claude-wait --check                the app's check, every minute

A time or deadline: 2026-11-16 17:00 (or ISO), 17:00 (today, or tomorrow once past), +90m, +4h, +2d, or
"3 weekdays" (the same clock time, Saturdays and Sundays skipped). The session picks the deadline; there is none
by default.

Waits are "waits" in the shared state file, keyed by a short id, with the session's link (cse_...), its saved
conversation and its folder, so they outlast archiving, a Mac restart and an app restart.
Bringing a session back: an active session with no turn running is archived first (that ends its process), then
started on its own the way the keep check starts an unarchived chat (effort-hook.py point_at and a kit- screen),
with the prompt as its first message, typed locally so Claude Code runs it; a prompt posted through the server
would be held. It is then one of the keep check's chats on their own (keep.alone). A session that can't come back
(no link, or its conversation isn't on this Mac) gets the message straight from the Kit instead.
Logged with lines starting "wait". STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and log;
STTARK_WAIT_DRY=1 checks and decides but brings nothing back and sends nothing.
"""
import datetime as dt, fcntl, importlib.util, json, os, re, subprocess, sys, time, uuid

HERE = os.path.dirname(os.path.realpath(__file__))
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(KIT, 'state.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
DRY = bool(os.environ.get('STTARK_WAIT_DRY'))
PR_EVERY = 300      # seconds between reads of one pull request
RETRY = 600         # seconds before trying again to bring back a session that didn't come back
FALLBACK = 900      # seconds after bringing a session back with no claude-notify from it: the Kit sends a message


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'wait   ' + line + '\n')
    except OSError:
        pass


def change(edit):
    """Read and change the shared state under its lock, as the hooks and the app do."""
    os.makedirs(KIT, exist_ok=True)
    with open(STATE + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            s = json.load(open(STATE))
        except (OSError, ValueError):
            s = {}
        out = edit(s)
        tmp = STATE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, STATE)
        return out


def peek():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {}


# --- times -------------------------------------------------------------------------------------------------

def weekdays_after(start, n):
    d = start
    while n > 0:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def when(text, now=None):
    """A time the person or session wrote, as a Unix time; ValueError when it can't be read."""
    now = now or dt.datetime.now()
    t = text.strip().lower()
    m = re.fullmatch(r'\+(\d+)\s*(m|min|h|d)', t)
    if m:
        n, u = int(m.group(1)), m.group(2)
        return (now + dt.timedelta(minutes=n if u.startswith('m') else 0, hours=n if u == 'h' else 0,
                                   days=n if u == 'd' else 0)).timestamp()
    m = re.fullmatch(r'(\d+)\s+(?:business |work )?weekdays?', t)
    if m:
        return weekdays_after(now, int(m.group(1))).timestamp()
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', t)
    if m:
        d = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        return (d if d > now else d + dt.timedelta(days=1)).timestamp()
    for f in ('%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return dt.datetime.strptime(text.strip()[:19], f).timestamp()
        except ValueError:
            pass
    try:
        return dt.datetime.fromisoformat(text.strip()).timestamp()
    except ValueError:
        raise ValueError('a time like 2026-11-16 17:00, 17:00, +4h, +2d or "3 weekdays"')


def clock(ts):
    d = dt.datetime.fromtimestamp(ts)
    today = dt.date.today()
    hm = d.strftime('%-I:%M %p')
    if d.date() == today:
        return hm
    if d.date() == today + dt.timedelta(days=1):
        return 'tomorrow ' + hm
    if 0 < (d.date() - today).days < 7:
        return d.strftime('%a ') + hm
    return d.strftime('%b %-d ') + hm


# --- the session -------------------------------------------------------------------------------------------

def this_session():
    """{'cse', 'sid', 'transcript', 'cwd', 'title', 'url'} of the session this runs in."""
    n = load('notify')
    cse = n.cse_id()
    sid = os.environ.get('CLAUDE_CODE_SESSION_ID', '')
    x = (peek().get('sessions') or {}).get(cse) or {}
    tp = x.get('transcript') or ''
    if not os.path.exists(tp) and sid:
        base = os.path.expanduser('~/.claude/projects')
        for d in os.listdir(base) if os.path.isdir(base) else []:
            p = os.path.join(base, d, sid + '.jsonl')
            if os.path.exists(p):
                tp = p
                break
    title, url = n.session()[:2] if cse else ('', '')
    return {'cse': cse, 'sid': sid, 'transcript': tp, 'cwd': os.getcwd(), 'title': title, 'url': url}


# --- checks: each says whether its thing happened, and what happened -----------------------------------------

def gh():
    return load('notify').gh()


def check_pr(w):
    """(happened, words) for a pull request wait, with gh; no model call."""
    repo, num = w['target'].split('#')
    out = subprocess.run([gh(), 'pr', 'view', num, '-R', repo, '--json', 'state,mergedAt,mergedBy,closedAt,url,title'],
                         capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise RuntimeError('gh: ' + (out.stderr or out.stdout).strip()[:160])
    p = json.loads(out.stdout)
    w['url'] = p.get('url') or w.get('url', '')
    who = ((p.get('mergedBy') or {}).get('login') or '')
    if w['want'] == 'merged' and p.get('state') == 'MERGED':
        return True, 'pull request %s "%s" was merged%s' % (w['target'], p.get('title', ''), ' by ' + who if who else '')
    if p.get('state') == 'CLOSED':
        return True, 'pull request %s "%s" was closed without a merge' % (w['target'], p.get('title', ''))
    if w['want'] == 'closed' and p.get('state') == 'MERGED':
        return True, 'pull request %s was merged' % w['target']
    return False, ''


STABLE = os.path.expanduser('~/.local/share/claude/stable/claude')
CLAUDE = STABLE if os.access(STABLE, os.X_OK) else os.path.expanduser('~/.local/bin/claude')
WR = 'mcp__claude_ai_Sttark_Workrouter__'
READ_TOOLS = [WR + t for t in ('gmail_search', 'gmail_read_message', 'asana_get_task', 'asana_get_task_stories',
                               'asana_search_tasks', 'asana_list_section_tasks', 'gchat_search_messages',
                               'gchat_list_spaces', 'calendar_list_events', 'docs_read', 'docs_search', 'drive_search',
                               'drive_list_folder', 'run_query', 'get_database_schema', 'inventory_search',
                               'inventory_get', 'helpscout_search', 'helpscout_get_conversation', 'meetings_search',
                               'org_structure', 'business_days')] + ['WebFetch', 'WebSearch']


def haiku(prompt, tools, timeout=180):
    """A Haiku run with only `tools` allowed and hooks off: (its final text, the text of each result of `tools`, why).
    Run as the person, through Claude Code's connectors. `why` says, in a few words, why the run gave no usable
    result: the Workrouter connector did not load (a Claude outage, or its sign-in), the tool answered an error, or
    the model did not call it. A caller that finds no answer in the results raises it, so the log and the window say."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    os.makedirs(os.path.join(KIT, 'wait-checks'), exist_ok=True)
    r = subprocess.run([CLAUDE, '-p', '--output-format', 'stream-json', '--verbose', '--model', 'haiku',
                        '--no-session-persistence', '--allowedTools', ','.join(tools),
                        '--settings', '{"disableAllHooks":true}'],
                       input=prompt, capture_output=True, text=True, timeout=timeout, env=env,
                       cwd=os.path.join(KIT, 'wait-checks'))
    final, results, errors, called, init = '', [], [], {}, None
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get('type') == 'system' and ev.get('subtype') == 'init':
            init = ev
        if ev.get('type') == 'result':
            final = ev.get('result') or ''
        for part in ((ev.get('message') or {}).get('content') or []) if isinstance(ev.get('message'), dict) else []:
            if not isinstance(part, dict):
                continue
            if part.get('type') == 'tool_use':
                called[part.get('id')] = part.get('name', '')
            elif part.get('type') == 'tool_result' and called.get(part.get('tool_use_id')) in tools:
                c = part.get('content')
                text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else str(c or '')
                (errors if part.get('is_error') else results).append(text)
    if r.returncode and not results and not final:
        raise RuntimeError('claude -p exit %d: %s' % (r.returncode, (r.stderr or r.stdout).strip()[:160]))
    why = ''
    wr = [t for t in tools if t.startswith(WR)]
    if wr and init is not None:
        server = [m for m in init.get('mcp_servers') or [] if m.get('name') == 'claude.ai Sttark Workrouter']
        status = server[0].get('status', '') if server else 'not listed'
        if status != 'connected':
            why = 'the Workrouter connector did not load in the check (%s): a Claude outage or its sign-in' % status
        elif not any(t in (init.get('tools') or []) for t in wr):
            why = 'the Workrouter connector loaded without %s' % wr[0][len(WR):]
    if not why and errors:
        why = '%s answered an error: %s' % (wr[0][len(WR):] if wr else 'the tool', re.sub(r'\s+', ' ', errors[0])[:140])
    if not why and not any(n in tools for n in called.values()):
        why = 'Haiku did not call %s; it said: %s' % (wr[0][len(WR):] if wr else 'the tool', re.sub(r'\s+', ' ', final)[:120] or 'nothing')
    if not why and init is None:
        why = 'claude -p gave no output: %s' % (r.stderr or '').strip()[:140]
    return final, results, why


def model_due(w, now):
    """Whether a check that costs a model call may run now: between 7 AM and 9 PM, never while the session or the
    account is held at the usage limit, and less often as the wait gets older: its own interval (10 minutes when it
    has none) for 3 hours, then at least 30 minutes, then after a day at least an hour. A check whose last run failed
    runs again after 10 minutes."""
    if not 7 <= dt.datetime.fromtimestamp(now).hour < 21:
        return False
    age = now - w.get('set_at', now)
    gap = max(w.get('every') or 600, 0 if age < 3 * 3600 else 1800 if age < 86400 else 3600)
    if w.get('failing'):
        gap = min(gap, 600)  # a check that failed tries again in 10 minutes, not at its slower pace
    if now - w.get('read_at', 0) < gap:
        return False
    try:
        if load('limit-hook').held(w.get('sid') or None, w.get('transcript') or None):
            return False
    except Exception:
        pass
    return True


def me():
    try:
        return (json.load(open(os.path.expanduser('~/.claude.json'))).get('oauthAccount') or {}).get('emailAddress', '').lower()
    except (OSError, ValueError):
        return ''


def check_email_reply(w):
    """(happened, words) for an email reply wait: one Haiku run that calls Workrouter's gmail_search once. The
    answer comes from the tool's own result, never from the model's words: a message in the thread (or from the
    sender given with --from) that is newer than the wait and not from the person."""
    if not w.get('subject') and not w.get('from'):
        # the thread id is its first message's id: read it once for the subject to search by
        _, res, why = haiku('Call %sgmail_read_message exactly once with message_id %s and max_chars 100, then reply "done".'
                            % (WR, json.dumps(w['target'])), [WR + 'gmail_read_message'], timeout=120)
        for t in res:
            try:
                w['subject'] = re.sub(r'^((re|fwd?|aw):\s*)+', '', json.loads(t).get('subject') or '', flags=re.I)
            except (ValueError, AttributeError):
                pass
        if not w.get('subject'):
            raise RuntimeError('could not read the thread %s: %s' % (w['target'], why or 'no subject in the answer'))
    q = 'after:%d' % int(w['set_at']) + (' from:%s' % w['from'] if w.get('from') else
                                          ' -from:me subject:(%s)' % re.sub(r'[^\w\s]', ' ', w['subject']).strip()[:120])
    _, results, why = haiku('Call %sgmail_search exactly once with query %s and max_results 20, then reply "done".'
                            % (WR, json.dumps(q)), [WR + 'gmail_search'], timeout=120)
    found, n = None, 0
    for t in results:
        try:
            emails = json.loads(t).get('emails') or []
        except (ValueError, AttributeError):
            continue
        found = found or []
        n += len(emails)
        for e in emails:
            sender = (e.get('from') or '').lower()
            if me() and me() in sender:
                continue
            if e.get('thread_id') == w['target'] or (w.get('from') and w['from'].lower() in sender):
                found.append(e)
    if found is None:
        raise RuntimeError(why or 'gmail_search answered: %s' % re.sub(r'\s+', ' ', ' '.join(results))[:140])
    if not found:
        return False, 'no reply yet' + (' (%d new message%s, none a reply)' % (n, '' if n == 1 else 's') if n else '')
    e = found[0]
    return True, '%s replied: "%s" (%s)' % (e.get('from', 'someone'), e.get('subject', ''), (e.get('snippet') or '')[:160])


def check_prompt(w):
    """(happened, words) for a check-prompt wait: one Haiku run with read-only Workrouter tools and the web, which
    ends with YES or NO."""
    final, _, why = haiku('You check one thing for a work session that waits on it. Use the tools to find out, read '
                     'only, and change nothing. The question: %s\n\nEnd with one line that is exactly YES or NO, '
                     'then one line with what you found.' % w['target'], READ_TOOLS)
    lines = [l.strip() for l in final.strip().splitlines() if l.strip()]
    yes = [i for i, l in enumerate(lines) if l.upper().rstrip('.') in ('YES', 'NO')]
    if not yes:
        raise RuntimeError(why or 'no YES or NO in the answer: %s' % re.sub(r'\s+', ' ', final)[:120])
    i = yes[-1]
    yes = lines[i].upper().startswith('YES')
    return yes, ' '.join(lines[i + 1:i + 2]) or ('the check said yes' if yes else '')


def check_script(w):
    """(happened, words) for a check-script wait: the session's own script, run with no model call; exit 0 means it
    happened, and its first line of output says what."""
    path = w['script']
    with open(path) as f:
        first = f.readline()
    cmd = [path] if first.startswith('#!') else ['/bin/zsh', path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=w.get('cwd') or KIT)
    if r.returncode == 0:
        return True, (r.stdout.strip().splitlines() or ['the check script says it happened'])[0][:200]
    return False, ''


CHECKS = {'pr': check_pr, 'email-reply': check_email_reply, 'check-prompt': check_prompt,
          'check-script': check_script, 'at': lambda w: (False, '')}


# --- bringing a session back -------------------------------------------------------------------------------

def prompt_for(w, what, late):
    lines = ['[Sttark Claude Kit] A wait you handed to the Kit has ended. ' + what + '.',
             'The wait: %s. Set %s; deadline %s. Your note: %s' % (describe(w), clock(w['set_at']),
                                                                   clock(w['by']) if w.get('by') else 'none', w.get('why', ''))]
    if late:
        lines.append('The deadline came and it has not happened. Find out first whether it happened some other way '
                     '(read the thread or the pull request). If it still has not: get the next step ready so one word '
                     'from the person does it (for an email, a follow-up draft, written by the rules for that '
                     'recipient), and ask in one line, for example "New Star has still not replied about the '
                     'laminator quote. Should I send the follow-up now?" Do not send anything before they answer.')
    others = [x for k, x in (peek().get('waits') or {}).items()
              if k != w['id'] and w.get('cse') and x.get('cse') == w['cse'] and x.get('stage') != 'back']
    if others:
        lines.append('Your other waits with the Kit stay open: %s. Cancel one you no longer need with claude-wait '
                     '--cancel <id>.' % '; '.join('%s (id %s, deadline %s)' % (describe(x), x['id'], clock(x['by']) if x.get('by') else 'none')
                                                   for x in others))
    lines.append('Go on with the work as far as you can. Then send the person one message with claude-notify that '
                 'stands alone: what happened, what this session is for, what is done, what it waits on now (with '
                 'links, such as a pull request and its state), what it does next, and what the person must do, or '
                 '"Nothing needed from you." If it waits on someone again, hand that wait to the Kit with claude-wait.')
    return '\n'.join(lines)


def describe(w):
    if w.get('what'):
        return w['what']
    if w['kind'] == 'pr':
        return 'pull request %s %s' % (w['target'], w['want'])
    if w['kind'] == 'email-reply':
        return 'a reply on email thread %s' % w['target']
    if w['kind'] == 'check-prompt':
        return 'yes to: %s' % w['target']
    if w['kind'] == 'check-script':
        return 'the check script %s' % os.path.basename(w['script'])
    return 'the time %s' % clock(w['at'])


def bring_back(w, prompt):
    """Unarchive the session on its own link with `prompt` as its first message. True when it started."""
    e = load('effort-hook')
    cse, tp = w.get('cse'), w.get('transcript')
    if not cse or not tp or not os.path.exists(tp):
        return False
    d = e.sse().session(cse)
    if d.get('status') == 'active':
        if d.get('worker_status') == 'running' or d.get('status_bucket') == 'working':
            raise RuntimeError('busy')  # a turn runs now; the next check tries again
        e.api('POST', 'https://api.anthropic.com/v1/code/sessions/%s/archive' % cse, {})
        for _ in range(20):  # archiving ends its process
            time.sleep(1)
            if ('--session-id ' + cse) not in e.processes() and ('--resume ' + os.path.basename(tp)[:-6]) not in e.processes():
                break
    cid = os.path.basename(tp)[:-len('.jsonl')]
    with open(os.path.join(KIT, 'keep.lock'), 'w') as lock:  # the keep check starts chats too: one at a time
        fcntl.flock(lock, fcntl.LOCK_EX)
        subprocess.run(['/usr/bin/screen', '-S', 'kit-' + cid[:8], '-X', 'quit'], capture_output=True)
        e.point_at(tp, cse, e.waiting_since_reply(e.chat_events(cse))[0])
        home = os.path.expanduser('~')
        stable = home + '/.local/share/claude/stable/claude'
        claude = stable if os.access(stable, os.X_OK) else home + '/.local/bin/claude'
        env = {'HOME': home, 'USER': os.environ.get('USER', ''), 'LOGNAME': os.environ.get('USER', ''),
               'SHELL': '/bin/zsh', 'TERM': 'xterm-256color', 'LANG': 'en_US.UTF-8',
               'PATH': f'{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'}
        pf = os.path.join(KIT, 'wait-prompts')
        os.makedirs(pf, exist_ok=True)
        pfile = os.path.join(pf, w['id'] + '.txt')
        with open(pfile, 'w') as f:
            f.write(prompt)
        cwd = w.get('cwd') or home
        subprocess.run(['/usr/bin/screen', '-dmS', 'kit-' + cid[:8], '/bin/zsh', '-lc',
                        f"cd '{cwd}' && exec '{claude}' --resume {cid} --remote-control --permission-mode "
                        f"bypassPermissions \"$(cat '{pfile}')\""], env=env)
        now = time.time()

        def alone(s):
            k = s.setdefault('keep', {})
            k.setdefault('alone', {})[cse] = {'transcript': tp, 'title': w.get('title', ''), 'at': now}
        change(alone)
    return True


def fallback(w, what, late):
    """The Kit's own message, when the session couldn't come back or didn't tell the person."""
    n = load('notify')
    body = what[0].upper() + what[1:] + '.'
    if late:
        body += ' The deadline (%s) passed. What do you want to do?' % clock(w['by'])
    body += ' The session waited for this: %s.' % (w.get('why') or describe(w))
    if w.get('stage') == 'back':
        body += ' It is back in your list; open it to go on.'
    else:
        body += ' It could not come back by itself; open it to go on.'
    return n.send(('No answer: ' if late else '') + describe(w), body, w.get('url', ''),
                  title=w.get('title', ''), url=w.get('session_url', ''), cse=w.get('cse', ''))


def notified_since(w, since):
    """Whether the session sent a claude-notify message after `since`: its log lines carry the session's name."""
    try:
        with open(LOG) as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400000))
            lines = f.read().splitlines()
    except OSError:
        return False
    stamp = time.strftime('%F %T', time.localtime(since))
    name = (w.get('title') or '-')[:40]
    return any(l[:19] >= stamp and (' notify ' + name + ' ') in l for l in lines)


def check(only=None):
    """Every minute, from the app. No model calls: gh for pull requests and the clock."""
    lock = open(os.path.join(KIT, 'wait.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    now = time.time()
    for wid, w in list((peek().get('waits') or {}).items()):
        if only and wid != only:
            continue
        upd, drop = {}, set()

        def save(s, wid=wid, upd=upd, drop=drop):
            x = (s.get('waits') or {}).get(wid)
            if x is not None:
                x.update(upd)
                for k in drop:
                    x.pop(k, None)
        if w.get('stage') == 'back':  # brought back: the session should have told the person
            if now - w.get('back_at', 0) > FALLBACK:
                if not notified_since(w, w['back_at']) and not DRY:
                    fallback(w, w.get('what', ''), w.get('late', False))
                    log('%s %s "%s" sent no message after coming back; the Kit sent one' % (wid, w.get('cse', '')[:12], w.get('title', '')))
                change(lambda s: (s.get('waits') or {}).pop(wid, None))
            continue
        if now - w.get('tried_at', 0) < RETRY and w.get('tried_at'):
            continue
        happened, what, late = False, '', False
        if only:
            happened, what = True, 'The person asked to bring it back now'
        elif w['kind'] == 'at':
            happened, what = now >= w['at'], 'The time you set came (%s)' % clock(w['at'])
        elif (model_due(w, now) if w['kind'] in ('email-reply', 'check-prompt') else
              now - w.get('read_at', 0) >= (PR_EVERY if w['kind'] == 'pr' else w.get('every') or 600)):
            model = w['kind'] in ('email-reply', 'check-prompt')
            try:
                happened, what = CHECKS[w['kind']](w)
                if w.get('failing'):
                    log('%s check works again (it failed since %s)' % (wid, clock(w.get('failing_since') or now)))
                    drop.update(('failing', 'failing_since', 'failures'))
                if model:  # each model check says its answer, so the log shows the checks run
                    log('%s checked: %s%s' % (wid, 'YES' if happened else 'NO', ', ' + what if what and not happened else ''))
                if not happened:
                    what = ''
            except Exception as e:
                why = str(e)[:200] or type(e).__name__
                upd.update(failing=why, failing_since=w.get('failing_since') or now, failures=w.get('failures', 0) + 1)
                log('%s check failed (%s since %s): %s' % (wid, 'once' if upd['failures'] == 1 else '%d times' % upd['failures'],
                                                         clock(upd['failing_since']), why))
            upd['read_at'] = now
            upd['url'] = w.get('url', '')
            if w.get('subject'):
                upd['subject'] = w['subject']
        if not happened and w.get('by') and now >= w['by']:
            happened, late = True, True
            what = 'The deadline came: %s has not happened' % describe(w)
        if not happened:
            if upd or drop:
                change(save)
            continue
        log('%s %s "%s" %s%s' % (wid, w.get('cse', '')[:12], w.get('title', ''), what, ' (deadline)' if late else ''))
        if DRY:
            print('would bring back %s: %s' % (wid, what))
            continue
        try:
            ok = bring_back(w, prompt_for(w, what, late))
        except RuntimeError as e:
            if str(e) == 'busy':
                log('%s its session is in a turn; trying again in a minute' % wid)
                continue
            ok = False
            log('%s could not bring it back: %s' % (wid, str(e)[:160]))
        except Exception as e:
            ok = False
            log('%s could not bring it back: %s: %s' % (wid, type(e).__name__, str(e)[:160]))
        if ok:
            log('%s brought "%s" back on its own link with what happened' % (wid, w.get('title', '')))
            upd.update(stage='back', back_at=time.time(), what=what, late=late)
            change(save)
        else:
            w['stage'] = 'out'
            fallback(w, what, late)
            log('%s sent the message from the Kit; the session did not come back' % wid)
            change(lambda s: (s.get('waits') or {}).pop(wid, None))


# --- the command -------------------------------------------------------------------------------------------

def opt(args, name):
    if name in args:
        i = args.index(name)
        v = args[i + 1] if i + 1 < len(args) else ''
        del args[i:i + 2]
        return v
    return None


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__.split('\n\n')[1])
        return 0
    if args[0] == '--check':
        check()
        return 0
    if args[0] == '--list':
        ws = peek().get('waits') or {}
        for wid, w in sorted(ws.items(), key=lambda x: x[1].get('by') or x[1].get('at') or 0):
            print('%s  %s  %s  by %s  (%s)%s' % (wid, w.get('title') or '-', describe(w),
                                                clock(w['by']) if w.get('by') else '-', w.get('why', ''),
                                                '  CHECK FAILING since %s: %s' % (clock(w.get('failing_since') or 0), w['failing'])
                                                if w.get('failing') else ''))
        print('' if ws else 'No open waits.', end='')
        return 0
    if args[0] in ('--cancel', '--now'):
        wid = args[1] if len(args) > 1 else ''
        if wid not in (peek().get('waits') or {}):
            print('No wait %s. claude-wait --list shows them.' % wid, file=sys.stderr)
            return 1
        if args[0] == '--cancel':
            change(lambda s: s['waits'].pop(wid, None))
            log('%s cancelled' % wid)
            print('Cancelled.')
        else:
            check(only=wid)
        return 0
    by, why, what = opt(args, '--by'), opt(args, '--why'), opt(args, '--what')
    sender, every = opt(args, '--from'), opt(args, '--every')
    kind = args[0]
    try:
        if kind == 'pr' and len(args) >= 3 and re.fullmatch(r'[\w.-]+/[\w.-]+#\d+', args[1]) and args[2] in ('merged', 'closed'):
            w = {'kind': 'pr', 'target': args[1], 'want': args[2]}
        elif kind == 'email-reply' and len(args) >= 2:
            w = {'kind': 'email-reply', 'target': args[1]}
            if sender:
                w['from'] = sender
        elif kind == 'check-prompt' and len(args) >= 2:
            w = {'kind': 'check-prompt', 'target': ' '.join(args[1:])}
        elif kind == 'check-script' and len(args) >= 2 and os.path.isfile(args[1]):
            w = {'kind': 'check-script', 'source': os.path.abspath(args[1])}
        elif kind == 'at' and len(args) >= 2:
            w = {'kind': 'at', 'at': when(' '.join(args[1:]))}
            by = by or None
        else:
            print('Usage: claude-wait check-script <path> --every <interval> --by <deadline> --why "<one line>"\n'
                  '       claude-wait check-prompt "<yes/no question>" --every <interval> --by <deadline> --why "<one line>"\n'
                  '       claude-wait pr <owner/repo#n> merged|closed --by <deadline> --why "<one line>"\n'
                  '       claude-wait at <time> --why "<one line>"\n'
                  '       claude-wait email-reply <thread id> --by <deadline> --why "<one line>"', file=sys.stderr)
            return 2
        if kind != 'at' and not by:
            print('--by is needed: pick the deadline from who you wait on, how urgent the work is and how long they '
                  'usually take.', file=sys.stderr)
            return 2
        if not (why or '').strip():
            print('--why is needed: one line with the deadline and the reason for it.', file=sys.stderr)
            return 2
        w['by'] = when(by) if by else None
        if every:
            m = re.fullmatch(r'(\d+)\s*(m|min|h)', every.strip().lower())
            if not m:
                raise ValueError('--every like 10m or 2h')
            w['every'] = int(m.group(1)) * (3600 if m.group(2) == 'h' else 60)
        if w['kind'] == 'check-prompt':
            w['every'] = max(w.get('every') or 1800, 600)  # a model call: every 10 minutes at most
        elif w['kind'] == 'check-script':
            w['every'] = max(w.get('every') or 600, 60)
    except ValueError as e:
        print('Not a time: %s' % e, file=sys.stderr)
        return 2
    me = this_session()
    wid = uuid.uuid4().hex[:6]
    if (what or '').strip():
        w['what'] = what.strip()
    w.update(id=wid, why=why.strip(), set_at=time.time(), cse=me['cse'], sid=me['sid'], transcript=me['transcript'],
             cwd=me['cwd'], title=me['title'], session_url=me['url'])
    if w['kind'] == 'pr':
        w['url'] = 'https://github.com/%s/pull/%s' % tuple(w['target'].split('#'))
    if w['kind'] == 'check-script':  # the Kit keeps its own copy, so the wait outlasts the session's files
        d = os.path.join(KIT, 'wait-scripts')
        os.makedirs(d, exist_ok=True)
        w['script'] = os.path.join(d, wid + (os.path.splitext(w['source'])[1] or '.sh'))
        with open(w['source']) as src, open(w['script'], 'w') as dst:
            dst.write(src.read())
        os.chmod(w['script'], 0o755)
    change(lambda s: s.setdefault('waits', {}).__setitem__(wid, w))
    log('%s %s "%s" set: %s, by %s | %s' % (wid, me['cse'][:12], me['title'], describe(w),
                                           clock(w['by']) if w.get('by') else '-', w['why']))
    print('Wait %s set: %s%s. The Kit watches it now; it shows in the Kit menu under "sessions wait on someone '
          'else".' % (wid, describe(w), ', deadline ' + clock(w['by']) if w.get('by') else ''))
    if not me['cse']:
        print('This session has no Claude app link, so it can\'t come back by itself: the person gets the message.')
    else:
        print('End your turn with one handoff line for the person, for example: "I am watching for %s. If none by %s, '
              'I bring this session back and ask if we follow up. You can archive this session."'
              % (describe(w), clock(w['by']) if w.get('by') else clock(w.get('at') or time.time())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
