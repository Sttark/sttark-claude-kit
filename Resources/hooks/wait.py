#!/usr/bin/python3
"""claude-wait: a session that waits on someone else hands the wait to Sttark Claude Kit, so the person can archive
the session. The Kit watches the wait with no model calls, and when the thing happens, or when the deadline comes and
it hasn't, brings the session back: it unarchives it on the same link with a prompt saying what happened, and the
session goes on and tells the person through Reach me by (claude-notify).

    claude-wait pr <owner/repo#n> merged|closed --by <deadline> --why "<deadline and reason, one line>"
    claude-wait at <time> --why "<what to check then, one line>"
    claude-wait email-reply <Gmail thread id> [--from <sender or domain>] [--mailbox <address>] --by <deadline> --why "<...>"
    claude-wait email-reply --query "<Gmail search>" [--mailbox <address>] --by <deadline> --why "<...>"
                                       any new message that matches the search. --mailbox watches a mailbox other
                                       than your own, such as a shared team address; this Mac reads it after one
                                       sign-in (claude-mail sign-in <address>), with no model call.
    claude-wait check-script <path> --every <10m|2h> --by <deadline> --why "<...>"   (exit 0 = it happened; free)
    claude-wait check-prompt "<yes/no question>" --every <30m> --by <deadline> --why "<...>"   (a Haiku call)
    --what "<what you watch for, in the person's words>"  (any wait; e.g. "New Star's reply about the laminator")
    claude-wait --list                 open waits, every session
    claude-wait --watching             what the Kit watches for replies with no wait: each session's contacts (the
                                       people, threads, sites, Asana tasks and Chat spaces it wrote to), watch.py
    claude-wait --cancel <id> [--by window|phone]
                                       drop a wait
    claude-wait --now <id> [--by window|phone]
                                       bring its session back now
    claude-wait --check                the app's check, every minute
    claude-wait --unarchive <cse_id> [--by window|phone]
                                       bring an archived session back on its link, with no first message (the
                                       window's Archived page, the phone)
    --cancel, --now and --unarchive exit with the phone's result names: 0 ok, 1 not_now, 2 not_here, 3 gone,
    4 bad. Their --by says who asked, the Kit window or the phone, for the log (KitActions in the app).

A time or deadline: 2026-11-16 17:00 (or ISO), 17:00 (today, or tomorrow once past), +90m, +4h, +2d, or
"3 weekdays" (the same clock time, Saturdays and Sundays skipped). The session picks the deadline; there is none
by default.

Waits are "waits" in the shared state file, keyed by a short id, with the session's link (cse_...), its saved
conversation and its folder, so they outlast archiving, a Mac restart and an app restart.
Bringing a session back: the copy that runs it now, in the server or the Kit, is ended first with SIGKILL
(effort-hook.py end_copy()), which leaves the session as it is: the Kit never archives one. Then it is started on its
own the way the keep check starts an unarchived chat (effort-hook.py point_at and a kit- screen), with the prompt as
its first message, typed locally so Claude Code runs it; a prompt posted through the server would be held. It is then
one of the keep check's chats on their own (keep.alone). While its turn runs, or its agents, background commands or
Monitors (they would end with that copy), the bring-back waits and tries again each minute; after HOLD_MAX it goes on,
and its message tells the session what stopped. A session that can't come back (no link, or its conversation isn't on
this Mac) gets the message straight from the Kit instead.
After the waits, each minute, the reply watch (watch.py) brings a session back when an answer comes from someone
it contacted, also when it set no wait for it; a wait never ends on a message the watch already brought it for.
An email reply wait never ends on the person's own message either: when the person replies in its thread themselves,
the reply watch puts `replied` on the wait ({at, where, id}: its row says "You replied <time>"), and it still waits for
the other person. A wait that brings its session back notes its thread for the watch (watch.py note_back()).
Then a prompt the person sent from a new session to an open one that does the same work (same-work.py) goes to that
session, when it waited for the session's turn to end; bring_back() is its start too.
Then each prompt bring_back() typed into its copy, that the copy ended before the session answered it, goes again
(redeliver()): bring_back() keeps each prompt it types in (`typed` in the state file, effort-hook.py) until the session
answers it. After 3 tries, or when the session was archived, the Kit tells the person instead, with the prompt's text.
Then, with the wait lock free and in a process of their own, the progress check-ins (checkin.py) tell the person how
a session's long work goes.
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
                    # (kept in the Kit app instead when alerts are off: notify.py held())
MAIL_EVERY = 300    # seconds between reads of a mailbox the Kit reads directly (claude-mail): free, at any hour
STARTING = 120      # seconds after the Kit starts a session in which it is not started again: its first prompt runs
HOLD_MAX = 7200     # seconds a bring-back waits at most for a session's agents, background commands and Monitors
                    # (DESIGN-DECISIONS.md): longer than 95% of background agents ran in one Mac's records


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
    final, calls, why = haiku_calls(prompt, tools, timeout)
    return final, [res for _, _, res, err in calls if not err], why


def haiku_calls(prompt, tools, timeout=180):
    """The same run as haiku(), with each call of `tools` it made: (final text, [(tool, its input, its result's text,
    whether that was an error)], why). The reply watch (watch.py) makes all its reads in one such run."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    os.makedirs(os.path.join(KIT, 'wait-checks'), exist_ok=True)
    r = subprocess.run([CLAUDE, '-p', '--output-format', 'stream-json', '--verbose', '--model', 'haiku',
                        '--no-session-persistence', '--allowedTools', ','.join(tools),
                        '--settings', '{"disableAllHooks":true}'],
                       input=prompt, capture_output=True, text=True, timeout=timeout, env=env,
                       cwd=os.path.join(KIT, 'wait-checks'))
    final, calls, called, init = '', [], {}, None
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
                called[part.get('id')] = (part.get('name', ''), part.get('input') or {})
            elif part.get('type') == 'tool_result' and (called.get(part.get('tool_use_id')) or ('',))[0] in tools:
                c = part.get('content')
                text = ''.join(x.get('text', '') for x in c if isinstance(x, dict)) if isinstance(c, list) else str(c or '')
                name, inp = called[part.get('tool_use_id')]
                calls.append((name, inp, text, bool(part.get('is_error'))))
    results = [c for c in calls if not c[3]]
    errors = [c[2] for c in calls if c[3]]
    if r.returncode and not results and not final:
        raise RuntimeError('claude -p exit %d: %s' % (r.returncode, (r.stderr or r.stdout).strip()[:160]))
    why = ''
    wr = [t for t in tools if t.startswith(WR)]
    if errors:   # the tool ran, so its connector loaded: its own error says why
        why = '%s answered an error: %s' % (wr[0][len(WR):] if wr else 'the tool', re.sub(r'\s+', ' ', errors[0])[:140])
    elif not any(n in tools for n, _ in called.values()):
        # The start of the run lists only the connectors that loaded by then: run from the Kit, claude.ai connectors
        # load after it and are not listed, yet the tool works. Only a connector listed as not loaded explains it.
        server = [m for m in (init or {}).get('mcp_servers') or [] if m.get('name') == 'claude.ai Sttark Workrouter']
        status = server[0].get('status', '') if server else ''
        if init is None:
            why = 'claude -p gave no output: %s' % (r.stderr or '').strip()[:140]
        elif wr and status and status not in ('connected', 'pending'):
            why = 'the Workrouter connector did not load in the check (%s): a Claude outage or its sign-in' % status
        else:
            why = 'Haiku did not call %s; it said: %s' % (wr[0][len(WR):] if wr else 'the tool', re.sub(r'\s+', ' ', final)[:120] or 'nothing')
    return final, calls, why


def due(w, now):
    """Whether the wait's check runs now. An email reply on a mailbox this Mac reads itself costs nothing: every
    MAIL_EVERY seconds (or its own --every), at any hour, as does one on a shared mailbox it can't read yet, which
    fails until the sign-in. A check that costs a model call: model_due(). A pull request: every PR_EVERY; a check
    script: at its own interval."""
    if w['kind'] == 'email-reply' and (direct(mailbox(w)) or w.get('mailbox')):
        return now - w.get('read_at', 0) >= max(w.get('every') or 0, MAIL_EVERY if direct(mailbox(w)) else 600)
    if w['kind'] in ('email-reply', 'check-prompt'):
        return model_due(w, now)
    return now - w.get('read_at', 0) >= (PR_EVERY if w['kind'] == 'pr' else w.get('every') or 600)


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


def mailbox(w):
    """The mailbox an email reply wait watches: its --mailbox, else the person's own (their Claude login's address)."""
    return w.get('mailbox') or me()


_direct = {}


def direct(box):
    """Whether this Mac reads the mailbox itself (a claude-mail sign-in for it), with no model call."""
    if box not in _direct:
        try:
            _direct[box] = load('mail').can_read(box)
        except Exception:
            _direct[box] = False
    return _direct[box]


def check_mailbox(w, box):
    """(happened, words) for an email reply wait on a mailbox this Mac reads itself (mail.py, the Gmail API): a
    message in the thread, from the sender given with --from, or that matches --query, newer than the wait and not
    from the mailbox or the person. No model call."""
    m = load('mail')
    since = int(w['set_at'])
    new = {}
    if w.get('target'):
        try:
            msgs = m.thread(box, w['target'])
        except m.GoogleError as e:
            if e.code != 404 or w.get('from') or w.get('query'):
                raise
            raise RuntimeError('%s has no thread %s: give one of its own thread ids (claude-mail search %s '
                               '"<Gmail search>" shows them)' % (box, w['target'], box))
        if msgs and not w.get('subject'):
            w['subject'] = re.sub(r'^((re|fwd?|aw):\s*)+', '', msgs[0]['subject'], flags=re.I)
        new.update((x['id'], x) for x in msgs)
    if w.get('from') or w.get('query'):
        q = ' '.join(x for x in ('from:(%s)' % w['from'] if w.get('from') else '',
                                 '(%s)' % w['query'] if w.get('query') else '', 'after:%d' % since, '-from:me') if x)
        new.update((x['id'], x) for x in m.search(box, q, 20))
    skip = [a for a in (box, me()) if a]
    old = told(w)
    found = sorted((x for x in new.values() if x['at'] >= since and not any(a in x['from'].lower() for a in skip)
                    and x['id'] not in old), key=lambda x: -x['at'])
    if not found:
        return False, 'no new mail yet'
    e = found[0]
    w['found'] = {'id': e['id'], 'thread_id': e['thread_id']}
    w['found_ids'] = [x['id'] for x in found]
    return True, '%s wrote%s: "%s" (%s)%s' % (e['from'] or 'someone', ' to ' + box if w.get('mailbox') else '',
                                             e['subject'], e['snippet'][:160],
                                             ', and %d more new' % (len(found) - 1) if len(found) > 1 else '')


def check_email_reply(w):
    """(happened, words) for an email reply wait. A mailbox this Mac reads itself (claude-mail sign-in) is read
    directly, with no model call (check_mailbox). Else, for the person's own mailbox: one Haiku run that calls
    Workrouter's gmail_search once. The answer comes from the tool's own result, never from the model's words: a
    message in the thread (or from the sender given with --from, or that matches --query) that is newer than the wait
    and not from the person."""
    box = mailbox(w)
    if direct(box):
        w['via'] = 'mail'
        return check_mailbox(w, box)
    if w.get('mailbox'):
        w['via'] = 'sign-in'
        raise RuntimeError('this Mac cannot read %s yet. Sign in to it once on this Mac: claude-mail sign-in %s '
                           'prints the link' % (box, box))
    w['via'] = 'model'
    if not w.get('subject') and not w.get('from') and not w.get('query'):
        # the thread id is its first message's id: read it once for the subject to search by
        _, res, why = haiku('Call %sgmail_read_message exactly once with message_id %s and max_chars 100, then reply "done".'
                            % (WR, json.dumps(w['target'])), [WR + 'gmail_read_message'], timeout=120)
        for t in res:
            try:
                w['subject'] = re.sub(r'^((re|fwd?|aw):\s*)+', '', json.loads(t).get('subject') or '', flags=re.I)
            except (ValueError, AttributeError):
                pass
        if not w.get('subject'):
            # A thread started from a draft keeps the draft's id, and its first message got a new id when it was sent
            # (gmail_read_message answers 404): find the subject in the person's own messages in the thread instead.
            _, res, why2 = haiku('Call %sgmail_search exactly once with query %s and max_results 20, then reply "done".'
                                 % (WR, json.dumps('from:me after:%d' % (int(w['set_at']) - 2 * 86400))),
                                 [WR + 'gmail_search'], timeout=120)
            for t in res:
                try:
                    e = next((e for e in json.loads(t).get('emails') or []
                              if e.get('thread_id') == w['target'] and e.get('subject')), None)
                except (ValueError, AttributeError):
                    e = None
                if e:
                    w['subject'] = re.sub(r'^((re|fwd?|aw):\s*)+', '', e['subject'], flags=re.I)
            if not w.get('subject'):
                raise RuntimeError('could not read the thread %s: %s' % (w['target'], why or why2 or 'no subject in the answer'))
    q = 'after:%d' % int(w['set_at']) + (' (%s) -from:me' % w['query'] if w.get('query') else
                                          ' from:%s' % w['from'] if w.get('from') else
                                          ' -from:me subject:(%s)' % re.sub(r'[^\w\s]', ' ', w['subject']).strip()[:120])
    _, results, why = haiku('Call %sgmail_search exactly once with query %s and max_results 20, then reply "done".'
                            % (WR, json.dumps(q)), [WR + 'gmail_search'], timeout=120)
    found, n, old = None, 0, told(w)
    for t in results:
        try:
            emails = json.loads(t).get('emails') or []
        except (ValueError, AttributeError):
            continue
        found = found or []
        n += len(emails)
        for e in emails:
            sender = (e.get('from') or '').lower()
            if (me() and me() in sender) or e.get('id') in old:
                continue
            if w.get('query') or e.get('thread_id') == w['target'] or (w.get('from') and w['from'].lower() in sender):
                found.append(e)
    if found is None:
        raise RuntimeError(why or 'gmail_search answered: %s' % re.sub(r'\s+', ' ', ' '.join(results))[:140])
    if not found:
        return False, 'no reply yet' + (' (%d new message%s, none a reply)' % (n, '' if n == 1 else 's') if n else '')
    e = found[0]
    w['found'] = {'id': e.get('id', ''), 'thread_id': e.get('thread_id', '')}
    w['found_ids'] = [x.get('id', '') for x in found]
    return True, '%s replied: "%s" (%s)' % (e.get('from', 'someone'), e.get('subject', ''), (e.get('snippet') or '')[:160])


def told(w):
    """The messages the Kit already brought this wait's session back for (watch.py): a wait never ends on one."""
    try:
        return load('watch').told(w.get('cse') or '')
    except Exception:
        return set()


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
    if w['kind'] == 'email-reply' and (w.get('mailbox') or w.get('via') == 'mail'):
        box, f = mailbox(w), w.get('found') or {}
        lines.append('The Kit reads %s itself: %sclaude-mail search %s "<Gmail search>" finds more.'
                     % (box, 'claude-mail read %s %s prints the message; ' % (box, f['id']) if f.get('id') else '', box))
    elif w['kind'] == 'email-reply' and (w.get('found') or {}).get('id'):
        lines.append("Read the message in full with Workrouter's gmail_read_message, message_id %s." % w['found']['id'])
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
        where = ' in %s' % w['mailbox'] if w.get('mailbox') else ''
        if w.get('query'):
            return 'new mail%s that matches: %s' % (where, w['query'])
        if not w.get('target'):
            return 'mail from %s%s' % (w.get('from', ''), where)
        return 'a reply on email thread %s%s' % (w['target'], where)
    if w['kind'] == 'check-prompt':
        return 'yes to: %s' % w['target']
    if w['kind'] == 'check-script':
        return 'the check script %s' % os.path.basename(w['script'])
    return 'the time %s' % clock(w['at'])


def busy(work=False):
    """The session can't come back yet: its turn runs, or (`work`) its agents, background commands or Monitors."""
    err = RuntimeError('busy')
    err.work = work
    return err


def hold_for_work(e, w, cse, tp):
    """Before a bring-back ends the session's copy: the work that would end with it (effort-hook.py copy_work(): the
    agents, background commands and Monitors of every copy that runs the session now). While some runs the bring-back
    waits: busy(work=True), so the next minute tries again, with a `work defer` line when the wait starts and when the
    work changes. After HOLD_MAX it goes on, and the work is returned: it ends with the copy, and the bring-back's
    message tells the session which (bring_back()). None when nothing runs."""
    try:
        work, _ = e.copy_work(tp, cse)
    except Exception as x:  # what runs can't be read: the minute check's view of the session decides, as before
        log('%s could not read what runs in its session: %s: %s' % (w.get('id', ''), type(x).__name__, str(x)[:160]))
        app = ((peek().get('sessions') or {}).get(cse) or {}).get('app') or {}
        if app.get('background') and time.time() - app.get('checked', 0) < 180:
            raise busy(work=True)
        return None
    ids, now, title = e.work_ids(work), time.time(), w.get('title', '')
    rec = (peek().get('work_wait') or {}).get(cse)
    held = rec if rec and now - rec.get('at', 0) < 600 else None  # a wait the minute check still saw: the same one

    def drop(s):
        (s.get('work_wait') or {}).pop(cse, None)
    if not ids:
        if held:
            e.log(f'work   done {cse} "{title}" bring-back waited {max(1, round((now - held["since"]) / 60))} min; '
                  'its work ended')
        if rec:
            change(drop)
        return None
    since = held['since'] if held else now
    if now - since >= HOLD_MAX:
        return work
    if not held or held.get('ids') != ids:
        e.log(f'work   defer {cse} "{title}" bring-back waits: {e.work_words(work)}; it tries again each minute, '
              f'at most {HOLD_MAX // 3600} hours')
    change(lambda s: s.setdefault('work_wait', {}).__setitem__(cse, {'since': since, 'at': now, 'ids': ids}))
    raise busy(work=True)


def bring_back(w, prompt=None):
    """Start the session in a Kit copy on its own link (unarchiving it when it is archived), with its whole
    conversation and `prompt` as its first message; with no prompt it waits for the person. True when it started.
    The window's Archived page brings a session back with this too (archived.py --back), so there is one way to do it.
    The Kit never archives a session (only the person does): a copy that runs it now, in the server or the Kit, is
    ended with end_copy(), which leaves the chat as it is. Not while a turn runs, or the session's agents, background
    commands or Monitors, which would end with it (hold_for_work()): RuntimeError('busy'), and the caller tries again.
    The message also tells the session what the Kit ended in it before (a handover, the Mac shut down), once."""
    e = load('effort-hook')
    cse, tp = w.get('cse'), w.get('transcript')
    if not cse or not tp or not os.path.exists(tp):
        return False
    started = ((((peek().get('keep') or {}).get('alone') or {}).get(cse)) or {}).get('at', 0)
    if 0 <= time.time() - started < STARTING:
        raise busy()  # the Kit started it moments ago (a wait, the reply watch): its first prompt may not run yet
    d = e.sse().session(cse)
    ended, why = None, 'bring-back'
    if d.get('status') == 'active':
        if d.get('worker_status') == 'running' or d.get('status_bucket') == 'working':
            raise busy()  # a turn runs now (ending its copy would end it); the next check tries again
        ended = hold_for_work(e, w, cse, tp)  # its agents, background commands and Monitors: it waits for them
        if not e.end_server_copy(cse):  # the copy started below must be its one copy, or the keep check ends that one
            raise RuntimeError('its copy in the server did not stop')
    else:  # archived: the person stopped it; a copy of the Kit's that still runs (keep() ends it in 2 minutes) ends now
        work = e.copy_work(tp, cse, 'kit')[0]
        if e.work_ids(work):
            ended, why = work, 'archived'
    pending = e.pending_stopped(cse) if prompt else []  # work the Kit ended before (a handover): the session hears now
    replied = [r for r in (e.pending_replied(cse) if prompt else []) if r not in prompt]  # the person's own replies
    told = pending + replied + ([e.stopped_notice(ended, why, time.time(), '%d hours' % (HOLD_MAX // 3600))] if prompt and ended else [])
    again = list(w.get('again') or [])  # redeliver(): the prompts this message types in again
    if prompt:  # a prompt typed in before that had no answer goes with this one (redeliver() would send it next)
        for r in [r for r in e.typed_list(cse) if r.get('lost') and r.get('id') not in again
                  and (r.get('tries') or 1) < e.TYPED_TRIES and r['lost'].get('why') != 'archived']:
            text = again_text(e, r)
            if text:
                told.append(text)
                again.append(r['id'])
    if told:
        prompt = '\n\n'.join([prompt] + told)
    level, reason = pick_level(e, cse, tp, prompt) if prompt else ('', '')
    cid = os.path.basename(tp)[:-len('.jsonl')]
    with open(os.path.join(KIT, 'keep.lock'), 'w') as lock:  # the keep check starts chats too: one at a time
        fcntl.flock(lock, fcntl.LOCK_EX)
        e.quit_screen('kit-' + cid[:8])  # every copy: `screen -S <name>` acts on none when two have the name
        e.point_at(tp, cse, e.waiting_since_reply(e.chat_events(cse))[0])
        pfile = ''
        if prompt:
            pf = os.path.join(KIT, 'wait-prompts')
            os.makedirs(pf, exist_ok=True)
            pfile = os.path.join(pf, w['id'] + '.txt')
            with open(pfile, 'w') as f:
                f.write(prompt)
        # in its folder, marked trusted first, as every start; at the level picked for the prompt (pick_level())
        e.start_screen(cid, w.get('cwd') or '', first=pfile, **({'effort': level} if level else {}))
        now = time.time()

        def alone(s):
            k = s.setdefault('keep', {})
            k.setdefault('alone', {})[cse] = {'transcript': tp, 'title': w.get('title', ''), 'at': now}
            (s.get('work_wait') or {}).pop(cse, None)
        change(alone)
    if prompt:
        typed_in(e, w, cse, tp, prompt, now, level, reason, again)
    if ended:
        e.note_stopped(cse, w.get('title', ''), ended, why, in_message=bool(prompt))
    if pending:
        e.take_stopped(cse, "in the Kit's message", only=pending)
    if replied:
        e.take_replied(cse, "in the Kit's message", only=replied)
    return True


def pick_level(e, cse, tp, prompt):
    """The effort level for the prompt bring_back() types in, from the effort hook's own check (effort-hook.py judge(),
    with the same question as at a prompt), so the copy starts at that level (--effort) and the hook sends no change
    through the server while the copy answers it (effort-hook.py typed_waits()). (level, reason); ('', '') when Auto
    effort is off, at the usage limit, or when the check fails: the copy then starts at Claude Code's own level. A
    session on Manual starts at its own level. STTARK_WAIT_LEVEL stands in for the check in tests, and a test folder
    (STTARK_KIT_DIR) never calls the model."""
    stub = os.environ.get('STTARK_WAIT_LEVEL')
    if stub is not None:
        return (stub, 'a test level') if stub in e.LEVELS else ('', '')
    if os.environ.get('STTARK_KIT_DIR'):
        return '', ''
    st = peek()
    x = (st.get('sessions') or {}).get(cse) or {}
    if x.get('manual'):
        return (x.get('level'), 'the session is on Manual') if x.get('level') in e.LEVELS else ('', '')
    if st.get('paused'):
        return '', ''
    try:  # the session's own usage setting decides whether the check waits, as at its prompts
        e.limit_for(os.path.basename(tp)[:-len('.jsonl')], tp, cse)
        level, answer = e.judge(f'Recent conversation:\n{e.recent(tp, prompt) or "(none)"}\n\n'
                                f'Current effort: {x.get("level") or "unknown"}\n\n'
                                f'Latest user message:\n{prompt[:4000]}\n\nEffort level?')
    except Exception as err:
        e.log(f'error  {cse} judge failed before the Kit typed a prompt in: {err!r}'[:300])
        return '', ''
    return (level, answer.split(' - ', 1)[-1]) if level else ('', '')


def typed_in(e, w, cse, tp, prompt, now, level, reason, again):
    """bring_back() typed `prompt` into its copy: it goes in `typed` in the state file until the session answers it
    (effort-hook.py confirm_typed()), with its text in typed/<id>.txt in the Kit's folder. The prompts in `again`
    (typed in before, and lost: redeliver()) count one more try each; a message that only types those in again
    (w['again']) adds no new one."""
    url = w.get('session_url') or 'https://claude.ai/code/session_' + cse.split('_', 1)[-1]
    source = w.get('source') or ('a wait' if w.get('kind') else 'the Kit')

    def edit(rs):
        for r in rs:
            if r.get('id') in again:
                r.update(at=now, tries=(r.get('tries') or 1) + 1, level=level, reason=reason)
                for k in ('lost', 'taken', 'seen', 'waits_said', 'fail_said'):
                    r.pop(k, None)
        if not w.get('again'):
            rid = uuid.uuid4().hex[:10]
            folder = os.path.join(KIT, 'typed')
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, rid + '.txt')
            with open(path, 'w') as f:
                f.write(prompt)
            rs.append({'id': rid, 'file': path, 'needle': e.needle_of(prompt), 'at': now, 'first_at': now, 'tries': 1,
                       'source': source, 'title': w.get('title', ''), 'transcript': tp, 'cwd': w.get('cwd') or '',
                       'level': level, 'reason': reason, 'url': url})
        return rs
    e.typed_edit(cse, edit)


def again_text(e, r):
    """A prompt the Kit types in again: a line that says why, then the prompt as it went the first time. '' when its
    text is gone."""
    try:
        with open(r['file']) as f:
            text = f.read()
    except (OSError, KeyError):
        return ''
    why = e.TYPED_WHY.get((r.get('lost') or {}).get('why'), e.TYPED_WHY['stopped'])
    return ('[Sttark Claude Kit] The Kit sends this prompt again. It went in at %s, but the copy of this session that '
            'received it ended before it answered. Why: %s. That copy may have done some of its steps, so check what '
            'changed before you do a step again. The prompt follows.\n\n%s' % (e.hm(r.get('first_at') or r.get('at', 0)), why, text))


def tell_typed(e, cse, r, reason):
    """The Kit tells the person that a prompt it typed in did not go in, with its text: its own message through Reach me
    by (notify.py send(), which keeps it in the Kit app on the session when it can't go out), and a `prompt failed`
    line, which the Events page shows as a problem."""
    try:
        with open(r['file']) as f:
            text = f.read()
    except (OSError, KeyError):
        text = r.get('needle') or ''
    title, first = r.get('title') or 'a session', e.hm(r.get('first_at') or r.get('at', 0))
    body = ('The Kit typed this prompt into “%s” at %s, but it did not go in. Why: %s. Open the session and send it '
            'again if you still need it. The prompt: “%s”' % (title, first, reason, text.strip()[:1500] + ('…' if len(text.strip()) > 1500 else '')))
    res = load('notify').send('A prompt did not go in: %s' % title, body, '', title=title, url=r.get('url', ''),
                              cse=cse, source='kit')
    kept = bool(res) and res[0][0] == load('notify').IN_KIT
    e.log(f'prompt failed {cse} "{title}" the prompt the Kit typed in at {first} ({r.get("source") or "the Kit"}) did '
          f'not go in: {reason}; the Kit ' + ('kept a message with its text in the Kit app (%s)' % res[0][1][1] if kept
                                              else 'sent you a message with its text')
          + f' | {e.needle_of(text)[:80]}')


def redeliver(now=None):
    """The minute check, after the prompts that wait for their session (same-work.py deliver()): each prompt the Kit
    typed into its own copy of a session, that the copy ended before it answered (effort-hook.py lose_typed()), goes
    again through bring_back(), to the copy that runs the session next, with a line that says why (again_text()).
    At most TYPED_TRIES tries in all; after that, or when the session was archived, its conversation is not on this
    Mac, or a day passed, the Kit tells the person instead, with its text (tell_typed()). Returns how many went again."""
    e = load('effort-hook')
    now, went = now or time.time(), 0
    for cse, recs in list((peek().get('typed') or {}).items()):
        lost = [r for r in recs if isinstance(r, dict) and r.get('lost')]
        if not lost:
            continue
        out = []
        for r in lost:
            why = (r.get('lost') or {}).get('why')
            if why == 'archived':
                out.append((r, 'the session was archived before it answered it'))
            elif not os.path.exists(r.get('file') or ''):
                out.append((r, 'its text is not on this Mac any more'))
            elif (r.get('tries') or 1) >= e.TYPED_TRIES:
                out.append((r, 'the session did not answer it after %d tries (%s)' % (r.get('tries') or 1, e.TYPED_WHY.get(why, why))))
            elif now - (r.get('first_at') or now) > e.TYPED_MAX:
                out.append((r, 'the session did not answer it in a day'))
        for r, reason in out:
            tell_typed(e, cse, r, reason)
        gone = {r['id'] for r, _ in out}
        if gone:
            e.typed_edit(cse, lambda rs: [x for x in rs if x.get('id') not in gone])
        rest = [r for r in lost if r['id'] not in gone]
        if not rest:
            continue
        first, title = rest[0], rest[0].get('title') or ''
        if DRY:
            print('would type in again for %s: %d prompt(s)' % (title or cse, len(rest)))
            continue
        w = {'id': 'again-' + cse[-6:], 'cse': cse, 'transcript': first.get('transcript'), 'cwd': first.get('cwd') or '',
             'title': title, 'source': first.get('source'), 'session_url': first.get('url', ''),
             'again': [r['id'] for r in rest]}
        try:
            ok = bring_back(w, '\n\n'.join(again_text(e, r) for r in rest))
        except RuntimeError as x:
            if str(x) == 'busy':
                quiet = [r for r in rest if not r.get('waits_said')]
                for r in quiet:
                    e.log(f'prompt waits  {cse} "{title}" the prompt the Kit typed in at {e.hm(r.get("first_at") or r["at"])} '
                          f'({r.get("source") or "the Kit"}) goes again when '
                          + ('its agents and background commands end' if getattr(x, 'work', False) else 'its turn ends'))
                if quiet:
                    ids = {r['id'] for r in quiet}
                    e.typed_edit(cse, lambda rs: [dict(x, waits_said=True) if x.get('id') in ids else x for x in rs])
                continue
            ok, err = None, str(x)[:160]
        except Exception as x:
            ok, err = None, '%s: %s' % (type(x).__name__, str(x)[:140])
        if ok is None:  # it could not start now: the next minute tries again, and a day at most (TYPED_MAX)
            if not first.get('fail_said'):
                e.log(f'prompt waits  {cse} "{title}" the Kit could not start it to type a prompt in again: {err}; '
                      'it tries again each minute')
                e.typed_edit(cse, lambda rs: [dict(x, fail_said=True) if x.get('id') == first['id'] else x for x in rs])
            continue
        if not ok:  # its conversation is not on this Mac
            for r in rest:
                tell_typed(e, cse, r, 'its conversation is not on this Mac')
            ids = {r['id'] for r in rest}
            e.typed_edit(cse, lambda rs: [x for x in rs if x.get('id') not in ids])
            continue
        went += len(rest)
        for r in rest:
            e.log(f'prompt again  {cse} "{title}" typed in again the prompt from {e.hm(r.get("first_at") or r["at"])} '
                  f'({r.get("source") or "the Kit"}), try {(r.get("tries") or 1) + 1} of {e.TYPED_TRIES} | '
                  f'{e.needle_of(r.get("needle"))[:80]}')
    return went


BACK_WAIT = 45  # seconds to wait for the Claude app to show an unarchived session back


def unarchive(cse, by='window'):
    """An archived session back in the person's list, on its own link with its whole conversation and no first
    message: the Kit window's Archived page (or the phone) asks for it. The facts come from archived.json, which
    effort-hook.py archived() writes; the start is bring_back(), as for a wait. Prints one line; returns the exit code:
    0 ok, 1 not_now (Claude did not answer, the start failed, or the Claude app does not show it back yet), 2 not_here,
    3 gone (phone/DESIGN.md, section 13).
    STTARK_ARCHIVED_TEST (a JSON file {"sessions": [...]}) stands in for the session's status; STTARK_WAIT_DRY starts
    nothing."""
    e = load('effort-hook')
    try:
        listing = json.load(open(e.ARCHIVED))
    except (OSError, ValueError):
        listing = {}
    items = listing.get('items') or []
    item = next((x for x in items if x.get('cse') == cse), None)
    test = os.environ.get('STTARK_ARCHIVED_TEST')

    def status():
        try:
            if test:
                return next((c for c in json.load(open(test)).get('sessions') or [] if c.get('id') == cse), {})
            return e.sse().session(cse)
        except Exception:
            return {}

    def drop():
        e.write_archived([x for x in items if x.get('cse') != cse], force=True)
    d = status()
    title = (item or {}).get('title') or (d.get('title') or '').strip() or 'Session ' + cse[-6:]
    if not d:  # unknown: never start one that may be running (bring_back ends the copy of an active session first)
        print('Claude did not answer, so the Kit did not bring it back. Try again in a minute.')
        log('%s "%s" not brought back from the archive (%s): its status could not be read' % (cse, title, by))
        return 1
    if d.get('status') != 'archived':
        print('It is not archived now. It is in your list.')
        log('%s "%s" not brought back from the archive (%s): it is not archived now' % (cse, title, by))
        drop()
        return 3
    if not item or not os.path.exists(item.get('transcript') or ''):
        print('Its conversation is not on this Mac, so this Mac cannot bring it back.')
        log('%s "%s" not brought back from the archive (%s): its conversation is not on this Mac' % (cse, title, by))
        drop()
        return 2
    w = {'id': cse[-6:], 'cse': cse, 'transcript': item['transcript'], 'cwd': item.get('folder') or '', 'title': title}
    if DRY:
        print('would bring %s back from %s' % (cse, item['transcript']))
        return 0
    try:
        started = bring_back(w, None)
    except Exception as x:
        why = str(x)[:160] or type(x).__name__
        print('It did not come back: %s.' % why)
        log('%s "%s" could not come back from the archive (%s): %s' % (cse, title, by, why))
        return 1
    if not started:
        print('Its conversation is not on this Mac, so this Mac cannot bring it back.')
        drop()
        return 2
    for _ in range(BACK_WAIT // 3):  # Claude Code unarchives the link when it reattaches it
        time.sleep(3)
        if status().get('status') == 'active':
            break
    else:
        print('The Kit started it again, but the Claude app does not show it back yet. Look again in a minute.')
        log('%s "%s" started from the archive (%s), but it was not back after %d s' % (cse, title, by, BACK_WAIT))
        return 1
    log('%s "%s" brought back from the archive (%s)' % (cse, title, by))
    drop()
    try:
        e.app_list()  # the Sessions page lists it at once
    except Exception:
        pass
    print('It is back in your list, on the same link, with its whole conversation.')
    return 0


def threads(w):
    """The email threads of an email reply wait: the one it waits on, and the one its reply came in."""
    if w.get('kind') != 'email-reply':
        return []
    return [t for t in dict.fromkeys([w.get('target'), (w.get('found') or {}).get('thread_id')]) if t]


def fallback(w, what, late):
    """The Kit's own message, when the session couldn't come back or didn't tell the person. Kept in the Kit, it is
    about the wait's email thread, so the person's own reply there marks it handled (watch.py)."""
    th = threads(w)
    about = {'at': w.get('back_at') or time.time(), 'places': ['mail:%s:%s' % (mailbox(w), t) for t in th],
             'what': describe(w)} if th else None
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
                  title=w.get('title', ''), url=w.get('session_url', ''), cse=w.get('cse', ''), source='kit', about=about)


def sent_words(res):
    """How the Kit's own message went, for the log: "sent one", or "kept one in the Kit app (alerts are off)"."""
    if res and res[0][0] == load('notify').IN_KIT:
        return 'kept one in the Kit app (%s)' % res[0][1][1]
    return 'sent one'


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


def live(waits, state=None):
    """The waits, each with its session's name as it is now: a wait keeps the name from when it was set, and the
    session may be renamed since (by the person, or by the name hook)."""
    names = {c: (x.get('title') or '').strip() for c, x in ((state or peek()).get('sessions') or {}).items()}
    for w in waits.values():
        if names.get(w.get('cse') or ''):
            w['title'] = names[w['cse']]
    return waits


def check(only=None, by=None):
    """Every minute, from the app. No model calls: gh for pull requests and the clock.
    With `only` (claude-wait --now <id>), that one wait ends now; `by` (window or phone) goes in its log line. Returns
    what became of it: 'brought', 'sent' (the Kit sent the message itself), 'dry', 'busy' (its session is in a turn),
    'working' (its agents, background commands or Monitors run: it comes back when they end), 'back' (it already
    ended), 'locked' (the minute check runs now) or None (no such wait)."""
    lock = open(os.path.join(KIT, 'wait.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 'locked'
    now = time.time()
    result = None
    for wid, w in list(live(peek().get('waits') or {}).items()):
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
                    res = fallback(w, w.get('what', ''), w.get('late', False))
                    log('%s %s "%s" sent no message after coming back; the Kit %s' % (wid, w.get('cse', '')[:12], w.get('title', ''), sent_words(res)))
                change(lambda s: (s.get('waits') or {}).pop(wid, None))
            result = 'back'
            continue
        if now - w.get('tried_at', 0) < RETRY and w.get('tried_at'):
            continue
        happened, what, late = False, '', False
        if only:
            happened, what = True, 'The person asked to bring it back now'
        elif w.get('ready'):  # it happened, and its session was in a turn: bring it back now, with no new check
            happened, what, late = True, w['ready'].get('what', ''), w['ready'].get('late', False)
            w['found'], w['found_ids'] = w['ready'].get('found') or {}, w['ready'].get('found_ids') or []
        elif w['kind'] == 'at':
            happened, what = now >= w['at'], 'The time you set came (%s)' % clock(w['at'])
        elif due(w, now):
            try:
                happened, what = CHECKS[w['kind']](w)
                if w.get('failing'):
                    log('%s check works again (it failed since %s)' % (wid, clock(w.get('failing_since') or now)))
                    drop.update(('failing', 'failing_since', 'failures'))
                if w.get('via') == 'mail':  # a free read every 5 minutes: its first answer, a change, then hourly
                    if happened or what != w.get('said') or now - w.get('said_at', 0) >= 3600:
                        log('%s checked %s: %s%s' % (wid, mailbox(w), 'YES' if happened else 'NO',
                                                     ', ' + what if what and not happened else ''))
                        upd.update(said=what, said_at=now)
                elif w['kind'] in ('email-reply', 'check-prompt'):  # each model check says its answer
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
            if w.get('via'):
                upd['via'] = w['via']
        if not happened and w.get('by') and now >= w['by']:
            happened, late = True, True
            what = 'The deadline came: %s has not happened' % describe(w)
        if not happened:
            if upd or drop:
                change(save)
            continue
        log('%s %s "%s" %s%s%s' % (wid, w.get('cse', '')[:12], w.get('title', ''), what, ' (deadline)' if late else '',
                                   ' (%s)' % by if only and by else ''))
        if DRY:
            print('would bring back %s: %s' % (wid, what))
            result = 'dry'
            continue
        try:
            ok = bring_back(w, prompt_for(w, what, late))
        except RuntimeError as e:
            if str(e) == 'busy':
                working = getattr(e, 'work', False)  # its agents, background commands or Monitors run (not a turn)
                if not w.get('ready'):
                    log('%s %s; %s' % (wid, 'its session\'s agents or background commands still run' if working else
                                            'its session is in a turn',
                                       'it comes back when they end%s' % (' (%s)' % by if by else '') if working and only
                                       else 'the wait stays open%s' % (' (%s)' % by if by else '') if only
                                       else 'trying again in a minute'))
                # what it found, kept: the next minute brings it back with no new check (no model call). Bring it back
                # now also comes back that way once the work ends; at a turn it leaves the wait as it was
                if not only or working:
                    upd['ready'] = {'what': what, 'late': late, 'found': w.get('found') or {},
                                    'found_ids': w.get('found_ids') or []}
                    change(save)
                result = 'working' if working else 'busy'
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
            result = 'brought'
            try:  # its thread, if it has one: a message the session keeps now is about it, and the person's reply counts
                load('watch').note_back(w.get('cse'), w.get('transcript'), mailbox(w) if threads(w) else '', threads(w),
                                        w.get('subject', ''))
            except Exception as e:
                log('%s could not note its bring-back for the reply watch: %s: %s' % (wid, type(e).__name__, str(e)[:160]))
        else:
            w['stage'] = 'out'
            res = fallback(w, what, late)
            log('%s %s the message from the Kit; the session did not come back' % (
                wid, 'kept' if sent_words(res).startswith('kept') else 'sent'))
            change(lambda s: (s.get('waits') or {}).pop(wid, None))
            result = 'sent'
        ids = w.get('found_ids') or [(w.get('found') or {}).get('id')]
        if any(ids):  # the reply watch never brings it back, or messages the person, for the same messages
            try:
                load('watch').mark_told(w.get('cse'), ids)
            except Exception:
                pass
    if not only:
        try:  # the reply watch: answers that no wait names (watch.py), in the same minute and under the same lock
            load('watch').check(Self())
        except Exception as e:
            log('the reply watch failed: %s: %s' % (type(e).__name__, str(e)[:200]))
        try:  # a prompt the person sent from a new session to an open one that does the same work (same-work.py),
            # which waits for that session's turn to end
            load('same-work').deliver()
        except Exception as e:
            log('the same work prompts failed: %s: %s' % (type(e).__name__, str(e)[:200]))
        try:  # a prompt the Kit typed into its copy of a session, that the copy ended before it answered: again
            redeliver()
        except Exception as e:
            log('the prompts to type in again failed: %s: %s' % (type(e).__name__, str(e)[:200]))
        lock.close()  # free for Bring it back now (--now) while the progress check-ins start (checkins())
    return result


def checkins():
    """After the minute check, also when it failed: the progress check-ins (checkin.py), in a process of their own,
    so their summaries never hold up the next minute's waits."""
    try:
        load('checkin').start()
    except Exception as e:
        log('the progress check-ins failed: %s: %s' % (type(e).__name__, str(e)[:200]))


class Self(object):
    """This module as the reply watch sees it, so a test that replaces a function here (bring_back) reaches it too."""
    def __getattr__(self, name):
        return globals()[name]


# --- the command -------------------------------------------------------------------------------------------

def opt(args, name):
    if name in args:
        i = args.index(name)
        v = args[i + 1] if i + 1 < len(args) else ''
        del args[i:i + 2]
        return v
    return None


def order(item):
    """The one order of waits, as the window's (Waits.before in Sources/Reach.swift): deadline (none last), then when
    it was set, then the session's name, then the wait's id. The state keeps waits in a dictionary, so every key is
    needed: with fewer, two waits with the same deadline change places from one read to the next."""
    wid, w = item
    inf = float('inf')
    return (w.get('by') or w.get('at') or inf, w.get('set_at') or inf, w.get('title') or 'A session', wid)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__.split('\n\n')[1])
        return 0
    if args[0] == '--check':
        try:
            check()
        finally:
            checkins()
        return 0
    if args[0] == '--watching':
        return load('watch').listing()
    if args[0] == '--list':
        ws = live(peek().get('waits') or {})
        for wid, w in sorted(ws.items(), key=order):
            print('%s  %s  %s  by %s  (%s)%s' % (wid, w.get('title') or '-', describe(w),
                                                clock(w['by']) if w.get('by') else '-', w.get('why', ''),
                                                '  CHECK FAILING since %s: %s' % (clock(w.get('failing_since') or 0), w['failing'])
                                                if w.get('failing') else ''))
        print('' if ws else 'No open waits.', end='')
        return 0
    if args[0] == '--unarchive':
        by = opt(args, '--by') or 'window'
        cse = args[1] if len(args) > 1 else ''
        if not re.fullmatch(r'(cse|session)_[A-Za-z0-9]+', cse) or by not in ('window', 'phone'):
            print('Usage: claude-wait --unarchive <cse_id> [--by window|phone]', file=sys.stderr)
            return 4
        return unarchive('cse_' + cse.split('_', 1)[1], by)
    if args[0] in ('--cancel', '--now'):
        by = opt(args, '--by')
        if by is not None and by not in ('window', 'phone'):
            print('Usage: claude-wait %s <id> [--by window|phone]' % args[0], file=sys.stderr)
            return 4
        wid = args[1] if len(args) > 1 else ''
        if wid not in (peek().get('waits') or {}):
            print('No wait %s. claude-wait --list shows them.' % wid, file=sys.stderr)
            return 3
        if args[0] == '--cancel':
            change(lambda s: s['waits'].pop(wid, None))
            log('%s cancelled%s' % (wid, ' (%s)' % by if by else ''))
            print('Cancelled.')
            return 0
        r = check(only=wid, by=by)
        if r == 'locked':
            print('The Kit is checking its waits now. Try again in a minute.')
            return 1
        if r == 'busy':
            print('Its session is in a turn now. Try again when the turn ends.')
            return 1
        if r == 'working':
            print('Its agents or background commands still run, so the Kit brings it back when they end (at most '
                  '%d hours from now).' % (HOLD_MAX // 3600))
            return 1
        if r in ('back', None):
            print('That wait already ended. Nothing was changed.')
            return 3
        if r == 'brought':
            print('It is back in your list. It tells you where it stands.')
        elif r == 'sent':
            print('It could not come back by itself, so the Kit sent you the message.')
        return 0
    by, why, what = opt(args, '--by'), opt(args, '--why'), opt(args, '--what')
    sender, every = opt(args, '--from'), opt(args, '--every')
    box, query = opt(args, '--mailbox'), opt(args, '--query')
    kind = args[0]
    try:
        if kind == 'pr' and len(args) >= 3 and re.fullmatch(r'[\w.-]+/[\w.-]+#\d+', args[1]) and args[2] in ('merged', 'closed'):
            w = {'kind': 'pr', 'target': args[1], 'want': args[2]}
        elif kind == 'email-reply' and (len(args) >= 2 or (query or '').strip() or sender):
            w = {'kind': 'email-reply', 'target': args[1] if len(args) >= 2 else ''}
            if sender:
                w['from'] = sender
            if (query or '').strip():
                w['query'] = query.strip()
            if box is not None:
                try:
                    box = load('mail').address(box)
                except ValueError as e:
                    print('--mailbox: %s' % e, file=sys.stderr)
                    return 2
                if box != me():
                    w['mailbox'] = box
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
                  '       claude-wait email-reply <thread id> [--from <sender>] [--mailbox <address>] --by <deadline> --why "<one line>"\n'
                  '       claude-wait email-reply --query "<Gmail search>" [--mailbox <address>] --by <deadline> --why "<one line>"',
                  file=sys.stderr)
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
    ses = this_session()
    wid = uuid.uuid4().hex[:6]
    if (what or '').strip():
        w['what'] = what.strip()
    w.update(id=wid, why=why.strip(), set_at=time.time(), cse=ses['cse'], sid=ses['sid'], transcript=ses['transcript'],
             cwd=ses['cwd'], title=ses['title'], session_url=ses['url'])
    if w['kind'] == 'pr':
        w['url'] = 'https://github.com/%s/pull/%s' % tuple(w['target'].split('#'))
    if w['kind'] == 'check-script':  # the Kit keeps its own copy, so the wait outlasts the session's files
        d = os.path.join(KIT, 'wait-scripts')
        os.makedirs(d, exist_ok=True)
        w['script'] = os.path.join(d, wid + (os.path.splitext(w['source'])[1] or '.sh'))
        with open(w['source']) as src, open(w['script'], 'w') as dst:
            dst.write(src.read())
        os.chmod(w['script'], 0o755)
    if w['kind'] == 'email-reply':
        w['via'] = 'mail' if direct(mailbox(w)) else 'sign-in' if w.get('mailbox') else 'model'
    change(lambda s: s.setdefault('waits', {}).__setitem__(wid, w))
    log('%s %s "%s" set: %s, by %s | %s' % (wid, ses['cse'][:12], ses['title'], describe(w),
                                           clock(w['by']) if w.get('by') else '-', w['why']))
    print('Wait %s set: %s%s. The Kit watches it now; it shows in the Kit menu under "sessions wait on someone '
          'else".' % (wid, describe(w), ', deadline ' + clock(w['by']) if w.get('by') else ''))
    if w.get('via') == 'mail':
        print('The Kit reads %s itself every %d minutes, at any hour, with no model call.' % (mailbox(w), MAIL_EVERY // 60))
    elif w.get('via') == 'sign-in':
        print('This Mac cannot read %s yet, so the check fails until someone who can open that mailbox signs in once '
              'on this Mac: run claude-mail sign-in %s and give the person the link it prints, to open on this Mac '
              '(select %s, click Allow). The deadline still brings this session back.' % ((w['mailbox'],) * 3))
    if not ses['cse']:
        print('This session has no Claude app link, so it can\'t come back by itself: the person gets the message.')
    else:
        print('End your turn with one handoff line for the person, for example: "I am watching for %s. If none by %s, '
              'I bring this session back and ask if we follow up. You can archive this session."'
              % (describe(w), clock(w['by']) if w.get('by') else clock(w.get('at') or time.time())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
