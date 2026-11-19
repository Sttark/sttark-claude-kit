#!/usr/bin/python3
"""Check-ins in the session: a timer that each session keeps itself, with Claude Code's own CronCreate tool, while its
work runs in the background. Every 15 minutes, while the session's turn is idle, Claude Code puts the timer's prompt
("[Sttark Claude Kit] Check-in: ...") into the session's own chat, and the session answers it in one or two lines. The
prompt goes in from inside the session's own Claude Code, so it reaches every session on this Mac: the server's copy,
the Claude desktop app's, a terminal's and the Kit's own. Nothing outside the session types or posts anything.

One hook, at two events (install-hooks.py adds it on every launch; it reads the switch itself on each call):

- PostToolUse, for Agent (Task), Bash, CronCreate and CronDelete. When the session itself (not one of its agents)
  starts an agent in the background (the result says async_launched) or sends a Bash command to the background (the
  result has a backgroundTaskId), and the session has no check-in timer, the hook asks it, as additionalContext, to
  set one now: CronCreate with a recurring cron every 15 minutes, the first one about 15 minutes from now and never
  on the :00 or :30 mark, durable false (the timer ends with the session's Claude Code), and PROMPT word for word.
  It asks one copy of the session once (ASK_AGAIN), so agents started together get one ask, and a session that
  could not set one is not asked at each agent. The CronCreate call itself, with a prompt that starts with MARK,
  records the timer (its job id) for the session; a second one gets a note to delete it; CronDelete of that id
  clears it.
- UserPromptSubmit. When the timer's prompt starts a turn, the hook gives the session what the Kit sees runs in it
  (effort-hook.py running_work(), with no model: each agent with its task, age and last step, each background
  command, and the Kit's own note from the progress check-ins while it is fresh), so the session's line or two tell
  real progress with no tool call. When nothing runs, it tells the session to delete the timer (CronDelete with its
  id) and reply in one line. On any other prompt (the person's, or the notice that an agent ended) while a timer is
  set and nothing runs, it tells the session to delete it in that turn.
- The timer ends itself: its prompt tells the session to delete it when no agent or background command of its own
  still runs, and the working rules say so too. CronCreate also ends a recurring job after 7 days, and a job made
  with durable false ends with the Claude Code process.

A timer counts as set while the Claude Code process that set it (CLAUDE_PID, which Claude Code gives its hooks)
still runs as this session (its ~/.claude/sessions/<pid>.json, when there is one, names the same conversation), and
for 7 days at most. So a session that moves to another copy (the server takes it over, the Kit starts it again)
gets a new timer at its next background work.

Kept in checkin-timers.json in the Kit's folder, per conversation id (the hook's session_id): the job, the process,
when it was set, the last ask and the last check-in. Logged as "checkin <session> "<name>" timer ..." lines, which
the Events page shows.

The switch: "checkins_chat" in the state file, false when the person turns Check-ins in the session off in Settings
> Sessions. Off, the hook asks for no timer, and a timer that is still set gets a note to delete it.

No hook here makes a model call. A test points STTARK_KIT_DIR, STTARK_KIT_LOG and STTARK_CLAUDE_DIR at copies
(tools/checkin-timer-test.py); STTARK_TIMER_CRON gives the cron in place of every 15 minutes (a live test: "* * * * *").
"""
import fcntl, importlib.util, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(KIT, 'state.json')
FILE = os.path.join(KIT, 'checkin-timers.json')
CHECKINS = os.path.join(KIT, 'checkins.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
CLAUDE_DIR = os.environ.get('STTARK_CLAUDE_DIR') or os.path.expanduser('~/.claude')

MARK = '[Sttark Claude Kit] Check-in:'  # the start of the timer's prompt (the working rules' word for it)
EVERY = 15             # minutes between two check-ins
ASK_AGAIN = 7200       # seconds before the Kit asks the same copy of a session again, when it set no timer
LIFE = 7 * 86400       # a recurring CronCreate job ends itself after 7 days
KEEP = 8 * 86400       # seconds a record with no timer stays in the file
NOTE_FRESH = 1200      # seconds the Kit's own progress note on the work counts as news for the session
AGENT_TOOLS = ('Agent', 'Task')
LIST_MAX = 6           # pieces of work named at most in the context

PROMPT = (MARK + ' Tell me in one or two lines how your work in the background goes. Use no tools and start no new '
          'work. When none of it still runs, delete this timer with CronDelete.')  # short: the person sees it each time
REPLY = ('Reply with only one or two short lines on the progress, in the person\'s terms, with no status table. Use no '
         'tools but CronDelete, send no claude-notify, ask nothing, and start no new work.')


# --- small helpers ----------------------------------------------------------------------------------------------

def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'checkin ' + line + '\n')
    except OSError:
        pass


def read_json(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def one_line(s, n):
    s = re.sub(r'\s+', ' ', str(s or '')).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def words(secs):
    """45 min, 1 hr, 1 hr 30 min."""
    m = max(1, int(round(secs / 60.0)))
    if m < 60:
        return '%d min' % m
    return '%d hr' % (m // 60) + (' %d min' % (m % 60) if m % 60 else '')


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def chat_on(st):
    return st.get('checkins_chat', True) is not False


class Timers(object):
    """checkin-timers.json, read and written under a lock: hooks of agents started together run at the same time."""

    def __enter__(self):
        os.makedirs(KIT, exist_ok=True)
        self.lock = open(FILE + '.lock', 'w')
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.data = read_json(FILE)
        self.before = json.dumps(self.data, sort_keys=True)
        return self.data

    def __exit__(self, *exc):
        try:
            if exc[0] is None and json.dumps(self.data, sort_keys=True) != self.before:
                tmp = FILE + '.tmp'
                with open(tmp, 'w') as f:
                    json.dump(self.data, f)
                os.replace(tmp, FILE)
        finally:
            self.lock.close()
        return False


def prune(T, now):
    """Records with no timer that set, asked or saw nothing for KEEP go."""
    for sid in list(T):
        r = T[sid] if isinstance(T[sid], dict) else {}
        if not r.get('job') and now - max(r.get('asked_at') or 0, r.get('ended_at') or 0, r.get('fired_at') or 0) > KEEP:
            T.pop(sid)


def claude_pid():
    try:
        return int(os.environ.get('CLAUDE_PID') or os.getppid())
    except ValueError:
        return os.getppid()


def alive(pid, sid):
    """The Claude Code process `pid` still runs as conversation `sid`."""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    rec = read_json(os.path.join(CLAUDE_DIR, 'sessions', '%d.json' % int(pid)))
    return not rec.get('sessionId') or rec.get('sessionId') == sid


def live(r, sid, now):
    """The record's timer is still set: its process runs as this session, and it is not past CronCreate's 7 days."""
    return bool(r.get('job')) and now - (r.get('set_at') or 0) < LIFE and alive(r.get('pid'), sid)


def one_shot(pid):
    """Claude Code runs for one prompt and ends (claude -p, not a server's copy or an app's): a timer never comes."""
    try:
        args = subprocess.run(['/bin/ps', '-ww', '-o', 'args=', '-p', str(pid)], capture_output=True, text=True,
                              timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    a = ' ' + args.strip() + ' '
    return bool(re.search(r' (-p|--print) ', a)) and '--sdk-url' not in a and 'stream-json' not in a


def session_of(sid):
    """(cse or the conversation id, the session's name) for log lines, from the Kit's state file."""
    st = read_json(STATE)
    for cse, x in (st.get('sessions') or {}).items():
        if isinstance(x, dict) and sid and os.path.basename(x.get('transcript') or '').startswith(sid):
            title = (x.get('title') or (x.get('app') or {}).get('title') or 'Session ' + cse[-6:]).strip()
            return cse, title.replace('"', "'")
    return sid or 'unknown', 'Session ' + (sid or '')[:8]


def say(sid, what, detail=''):
    cse, title = session_of(sid)
    log('%s "%s" timer %s%s' % (cse, title, what, ' | ' + one_line(detail, 300).replace(' | ', ' / ') if detail else ''))


def cron_for(now):
    """Every 15 minutes, the first one about 15 minutes from now: a match of minute m only comes again 15 minutes
    later. Never minute 0 or 30, which every scheduled job on the fleet picks."""
    if os.environ.get('STTARK_TIMER_CRON'):
        return os.environ['STTARK_TIMER_CRON']
    m = (time.localtime(now).tm_min - 1) % EVERY
    if m == 0:
        m = 1
    return '%d,%d,%d,%d * * * *' % (m, m + 15, m + 30, m + 45)


def out(event, text):
    print(json.dumps({'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}}))


# --- PostToolUse ----------------------------------------------------------------------------------------------------

def started_background(data):
    """What the session's own tool call sent to the background, in a few words, or ''."""
    tool = data.get('tool_name') or ''
    inp = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
    res = data.get('tool_response')
    if tool in AGENT_TOOLS:
        if inp.get('run_in_background') is False:
            return ''
        if isinstance(res, dict) and res.get('status') == 'async_launched':
            return 'agent "%s"' % one_line(inp.get('description') or res.get('description') or 'unnamed', 60)
        return ''
    if tool == 'Bash':
        if isinstance(res, dict) and res.get('backgroundTaskId'):
            return 'background command "%s"' % one_line(inp.get('description') or inp.get('command') or 'unnamed', 60)
    return ''


def job_id(res):
    if isinstance(res, dict):
        for k in ('id', 'jobId', 'job_id'):
            if res.get(k):
                return str(res[k])
        res = json.dumps(res)
    m = re.search(r'(?:job|task) (\S+?)[ .(]', str(res or ''))
    return m.group(1) if m else ''


def ask_text(cron):
    return ('[Sttark Claude Kit] Work of this session now runs in the background, and the session has no check-in '
            'timer. Before this turn ends, set one: call CronCreate one time (if it is not loaded, load it first with '
            'ToolSearch "select:CronCreate,CronDelete"), with cron "%s", recurring true, durable false, and this '
            'prompt, word for word:\n%s\nKeep the job id that it gives. Set no second timer. While your turn is idle, '
            'the timer puts that prompt in this chat every %d minutes, and the person reads your short answer. When '
            'no agent or background command of yours still runs, call CronDelete with that id. If this work is only a '
            'server or a watch that does not stop by itself, set no timer. Say nothing about the timer in your reply.'
            % (cron, PROMPT, EVERY))


def on_tool(data, now):
    if data.get('agent_id'):
        return  # an agent's own step: the session keeps the timer, and an agent has no CronCreate
    sid = data.get('session_id') or ''
    tool = data.get('tool_name') or ''
    inp = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
    if not sid:
        return
    if tool == 'CronCreate':
        if not str(inp.get('prompt') or '').startswith(MARK):
            return
        job = job_id(data.get('tool_response'))
        if not job:
            return
        pid = claude_pid()
        with Timers() as T:
            r = T.setdefault(sid, {})
            if live(r, sid, now) and r.get('job') != job:
                old = r['job']
                second = True
            else:
                second = False
                r.update(job=job, pid=pid, set_at=now, cron=str(inp.get('cron') or ''))
                r.pop('ended_at', None)
        if second:
            say(sid, 'second %s' % job, 'asked to delete it, as timer %s is set' % old)
            out('PostToolUse', '[Sttark Claude Kit] This session already has a check-in timer, job %s. Call CronDelete '
                               'with id "%s" now, so only one timer runs.' % (old, job))
        else:
            say(sid, 'set %s' % job, 'every %d min (%s)' % (EVERY, inp.get('cron') or ''))
        return
    if tool == 'CronDelete':
        job = str(inp.get('id') or '')
        with Timers() as T:
            r = T.get(sid) or {}
            if not job or r.get('job') != job:
                return
            r.update(job='', ended_at=now)
        say(sid, 'ended %s' % job)
        return
    what = started_background(data)
    if not what:
        return
    if not chat_on(read_json(STATE)):
        return
    pid = claude_pid()
    with Timers() as T:
        prune(T, now)
        r = T.setdefault(sid, {})
        if live(r, sid, now):
            return
        if r.get('asked_pid') == pid and now - (r.get('asked_at') or 0) < ASK_AGAIN \
                and (r.get('asked_at') or 0) > (r.get('ended_at') or 0):
            return  # asked this copy already, and it set no timer since: agents started together, or it could not
        if one_shot(pid):
            return
        cron = cron_for(now)
        r.update(asked_at=now, asked_pid=pid, job='')
    say(sid, 'asked', '%s started, every %d min (%s)' % (what, EVERY, cron))
    out('PostToolUse', ask_text(cron))


# --- UserPromptSubmit -----------------------------------------------------------------------------------------------

def running(tp, now):
    """What runs in the session now, as the Kit counts it (effort-hook.py running_work()): its agents and its
    background commands. A Monitor only watches, and tells the session itself. 'quiet': the agents the count leaves
    out though Claude Code never marked them finished and no notice says they ended (quiet for 15 minutes with no
    background task of their own: dead, or in a long command), so the Kit is not sure that nothing runs."""
    e = load('effort-hook')
    w = e.running_work(tp, now)
    out = {'agents': w.get('agents') or [], 'commands': w.get('commands') or [], 'quiet': 0}
    sub = os.path.join(tp[:-len('.jsonl')], 'subagents') if tp.endswith('.jsonl') else ''
    try:
        metas = [n for n in os.listdir(sub) if n.endswith('.meta.json')] if sub else []
    except OSError:
        metas = []
    counted = {a.get('id') for a in out['agents']}
    ended = None
    for n in metas:
        aid = n[len('agent-'):-len('.meta.json')] if n.startswith('agent-') else n[:-len('.meta.json')]
        m = read_json(os.path.join(sub, n))
        if aid in counted or m.get('finished') or m.get('requestShape') == 'foreground':
            continue
        if ended is None:
            ended = e.ended_tasks(tp)
        if aid not in ended:
            out['quiet'] += 1
    return out


def unsure(work):
    """How firm the note to delete the timer is: the records say every agent ended, or some went quiet."""
    if work['quiet']:
        return ('%d agent%s went quiet for 15 minutes, with no notice that %s ended. If none of your agents or '
                'background commands still runs,' % (work['quiet'], '' if work['quiet'] == 1 else 's',
                                                     'it' if work['quiet'] == 1 else 'they'))
    return 'Each agent and background command you started has ended, so'


def work_lines(work, now):
    lines = []
    for a in work['agents'][:LIST_MAX]:
        line = '- Agent "%s" (%s), %s' % (one_line(a.get('what') or 'unnamed', 80), a.get('id'), words(now - (a.get('start') or now)))
        if a.get('last'):
            line += '; its last step: %s' % one_line(a['last'], 120)
        lines.append(line)
    for c in work['commands'][:LIST_MAX]:
        lines.append('- Background command "%s" (%s), %s%s' % (
            one_line(c.get('what') or 'unnamed', 80), c.get('id'), words(now - (c.get('start') or now)),
            ', started by agent %s' % c['by'] if c.get('by') else ''))
    more = len(work['agents']) + len(work['commands']) - len(lines)
    if more > 0:
        lines.append('- and %d more' % more)
    return lines


def kit_note(sid, now):
    """The Kit's own progress note on the session's work (checkin.py), while it is fresh: (the note, its age) or None."""
    cse, _ = session_of(sid)
    c = (read_json(CHECKINS).get('sessions') or {}).get(cse) or {}
    if c.get('note') and now - (c.get('note_at') or 0) < NOTE_FRESH:
        return one_line(c['note'], 600), now - c['note_at']
    return None


def counts(work):
    a, c = len(work['agents']), len(work['commands'])
    parts = (['%d agent%s' % (a, '' if a == 1 else 's')] if a else []) + \
            (['%d background command%s' % (c, '' if c == 1 else 's')] if c else [])
    return ', '.join(parts) or 'nothing'


def on_prompt(data, now):
    sid = data.get('session_id') or ''
    prompt = (data.get('prompt') or '').lstrip()
    checkin = prompt.startswith(MARK)
    T = read_json(FILE)
    r = T.get(sid) if isinstance(T.get(sid), dict) else {}
    set_now = live(r, sid, now)
    if not checkin and not set_now:
        return
    job = r.get('job') if set_now else ''
    pid = claude_pid()
    if checkin:
        with Timers() as T2:
            x = T2.setdefault(sid, {})
            x['fired_at'] = now
            if x.get('job') and x.get('pid') != pid:
                x['job'] = ''  # an older copy's timer: this check-in came from one the Kit did not see set
            job = x.get('job') if live(x, sid, now) else ''
    the_id = ('id "%s"' % job) if job else 'the id of your check-in timer (CronList shows it)'
    if not chat_on(read_json(STATE)):
        say(sid, 'check-in %s' % (job or '?') if checkin else 'reminder %s' % job, 'check-ins in the session are off: asked to delete it')
        out('UserPromptSubmit', '[Sttark Claude Kit] Check-ins in the session are off in the Kit\'s Settings. Call '
                                'CronDelete with %s in this turn%s.' % (
                                    the_id, ', and reply only: Check-ins stopped.' if checkin else
                                    ', and say nothing about it in your reply'))
        return
    tp = data.get('transcript_path') or ''
    try:
        work = running(tp, now)
    except Exception as w:  # the session answers from what it knows
        say(sid, 'check-in %s' % (job or '?') if checkin else 'reminder %s' % job,
            'could not read its work: %s: %s' % (type(w).__name__, one_line(str(w), 120)))
        return
    busy = work['agents'] or work['commands']
    if not checkin:
        if busy:
            return
        say(sid, 'reminder %s' % job, 'no work runs: asked to delete it')
        out('UserPromptSubmit', '[Sttark Claude Kit] Your check-in timer (job %s) is still set, but no agent or '
                                'background command of this session runs now, as the Kit reads the records. %s call '
                                'CronDelete with id "%s" in this turn. Say nothing about it in your reply.'
                                % (job, unsure(work), job))
        return
    if not busy:
        say(sid, 'check-in %s' % (job or '?'), 'no work runs: asked to delete it')
        out('UserPromptSubmit', '[Sttark Claude Kit] This is your check-in timer. No agent or background command of '
                                'this session runs now, as the Kit reads the records. %s call CronDelete with %s now, '
                                'then reply in one line that the work is done. Use no other tool. %s'
                                % (unsure(work), the_id, '' if not work['quiet'] else 'Else: ' + REPLY))
        return
    lines = ['[Sttark Claude Kit] This is your check-in timer. ' + REPLY + ' What runs in this session now, as the Kit '
             'sees it, for your answer with no tool call:'] + work_lines(work, now)
    note = kit_note(sid, now)
    if note:
        lines.append('The Kit\'s own note on this work, %s ago: %s' % (words(note[1]), note[0]))
    if job:
        lines.append('Your check-in timer is job %s.' % job)
    say(sid, 'check-in %s' % (job or '?'), counts(work))
    out('UserPromptSubmit', '\n'.join(lines))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    now = time.time()
    try:
        if data.get('hook_event_name') == 'PostToolUse':
            on_tool(data, now)
        elif data.get('hook_event_name') == 'UserPromptSubmit':
            on_prompt(data, now)
    except Exception as x:  # never stops a tool call or a prompt
        log('timer error: %s: %s' % (type(x).__name__, one_line(str(x), 200)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
