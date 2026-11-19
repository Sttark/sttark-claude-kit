"""What Sttark Claude Kit knows about each session, read from its state files (read only), and the one status line
per session the glasses show.

The Kit's hooks and app keep, in ~/Library/Application Support/SttarkClaudeKit:
- state.json: per session (by Remote Control id) its saved conversation (`transcript`) and, every minute, `app`:
  whether Claude works, whether the finished reply needs the person and why (the Kit's own judgment), and what still
  runs after the turn (`background`); the open waits handed to the Kit (`waits`); the sessions held at the usage
  limit (`limit_pauses`).
- checkins.json: the latest progress check-in of work that runs 15 minutes or more.

The groups follow the Kit window's Sessions page (Sources/Inbox.swift): held at the usage limit, needs you, Claude
working, waiting on someone else, idle. The glasses have four: a held session is "waiting". The live part comes
from the Claude API's own session record, which changes the moment a turn starts or asks something; the Kit's
judgment of a finished reply comes from its minute check.
"""
import json
import os
import re
import threading
import time

KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
HOME = os.path.expanduser('~')


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def clock(ts):
    """A Unix time as the person reads it: 4:40 PM today, else Thu 4:40 PM."""
    t = time.localtime(ts)
    now = time.localtime()
    hm = time.strftime('%I:%M %p', t).lstrip('0')
    if t.tm_yday == now.tm_yday and t.tm_year == now.tm_year:
        return hm
    return time.strftime('%a ', t) + hm


_CWD = re.compile(r'"cwd": ?"((?:[^"\\]|\\.)*)"')


def transcript_folder(path):
    """The last cwd a saved conversation names: its last 64 KB, else its last 256 KB, else its first 256 KB."""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            for start, length in ((max(size - 65536, 0), 65536), (max(size - 262144, 0), 262144), (0, 262144)):
                f.seek(start)
                text = f.read(length).decode('utf-8', 'replace')
                m = list(_CWD.finditer(text))
                if m:
                    try:
                        return json.loads('"' + m[-1].group(1) + '"')
                    except ValueError:
                        return ''
    except OSError:
        pass
    return ''


class KitState:
    def __init__(self, folder=KIT):
        self.folder = folder
        self.lock = threading.Lock()
        self.state = {}
        self.checkins = {}
        self._mtimes = (None, None)
        self._folders = {}  # transcript path -> (mtime, cwd)

    def _mtime(self, name):
        try:
            return os.stat(os.path.join(self.folder, name)).st_mtime
        except OSError:
            return None

    def reload(self):
        """Read the files again when they changed. True when they did."""
        m = (self._mtime('state.json'), self._mtime('checkins.json'))
        if m == self._mtimes:
            return False
        state, checkins = self.state, self.checkins
        try:
            with open(os.path.join(self.folder, 'state.json')) as f:
                state = json.load(f)
        except (OSError, ValueError):
            pass  # a write in progress: the next look reads it
        try:
            with open(os.path.join(self.folder, 'checkins.json')) as f:
                checkins = json.load(f)
        except (OSError, ValueError):
            checkins = {}
        with self.lock:
            self.state, self.checkins, self._mtimes = state, checkins, m
        return True

    def record(self, cse):
        return (self.state.get('sessions') or {}).get(cse) or {}

    def waits_for(self, cse):
        ws = [w for w in (self.state.get('waits') or {}).values() if isinstance(w, dict) and w.get('cse') == cse]
        return sorted(ws, key=lambda w: (_num(w.get('by')) or 9e12, str(w.get('id'))))

    def hold_for(self, cse):
        for key, x in (self.state.get('limit_pauses') or {}).items():
            if not isinstance(x, dict) or x.get('cse') != cse:
                continue
            pid = int(_num(x.get('pid')) or 0)
            if pid <= 0:
                continue
            try:
                os.kill(pid, 0)
            except OSError:
                continue
            return x
        return None

    def checkin(self, cse):
        if self.state.get('checkins') is False:
            return None
        c = (self.checkins.get('sessions') or {}).get(cse) or {}
        text = (c.get('note') or '').strip()
        at, start = _num(c.get('note_at')), _num(c.get('start'))
        if text and at and start and at >= start:
            return text
        return None

    def background(self, cse):
        """What still runs after the turn (agents, background commands), as the Kit's minute check last saw it."""
        a = self.record(cse).get('app') or {}
        b, checked = a.get('background'), _num(a.get('checked'))
        if not isinstance(b, dict) or not checked or time.time() - checked > 180:
            return None
        agents, bash = int(_num(b.get('agents')) or 0), int(_num(b.get('bash')) or 0)
        if agents + bash <= 0:
            return None
        ag = '1 agent' if agents == 1 else f'{agents} agents'
        bg = '1 background command' if bash == 1 else f'{bash} background commands'
        head = f'{ag} and {bg} working' if agents and bash else (f'{ag} working' if agents else bg)
        what = (b.get('what') or '').strip()
        return head + (' · ' + what if what else '')

    def folder_of(self, cse):
        tp = self.record(cse).get('transcript') or ''
        if tp.endswith('.jsonl'):
            try:
                m = os.path.getmtime(tp)
            except OSError:
                m = None
            if m is not None:
                cached = self._folders.get(tp)
                if cached and cached[0] == m:
                    return cached[1]
                cwd = transcript_folder(tp)
                self._folders[tp] = (m, cwd)
                if cwd:
                    return cwd
        for w in self.waits_for(cse):
            if w.get('cwd'):
                return w['cwd']
        return ''

    def recent_folders(self, limit=40):
        """Folders of the sessions the Kit saw, newest first."""
        rows = []
        for cse, x in (self.state.get('sessions') or {}).items():
            if isinstance(x, dict) and (x.get('transcript') or '').endswith('.jsonl'):
                rows.append((_num(x.get('at')) or 0, cse))
        rows.sort(reverse=True)
        out = []
        for _, cse in rows[:limit]:
            f = self.folder_of(cse)
            if f and f not in out:
                out.append(f)
        for w in (self.state.get('waits') or {}).values():
            if isinstance(w, dict) and w.get('cwd') and w['cwd'] not in out:
                out.append(w['cwd'])
        return out


# -- one session's line -------------------------------------------------------------------------------------------

ORDER = {'needs_you': 0, 'working': 1, 'waiting': 2, 'idle': 3}


def listed(s):
    """A live session: one the Claude app lists (not archived, not a run of a scheduled task, as the Kit's
    effort-hook.py app_list), and that something can still run. A session on this Mac's Remote Control server is
    started again when a message comes (and the Kit keeps those running), so it counts while it is disconnected;
    a session of its own (no environment) whose Claude Code has ended does not."""
    tags = s.get('tags') or []
    if s.get('status') == 'archived' or s.get('trigger_id') or any(str(t).startswith('routine') for t in tags):
        return False
    return bool(s.get('environment_id')) or s.get('connection_status') != 'disconnected'


def pending_words(pa):
    """One line for a prompt that waits for the person, from the session's pending_action."""
    if not isinstance(pa, dict):
        return None
    tool = pa.get('tool_name') or ''
    inp = pa.get('input') if isinstance(pa.get('input'), dict) else {}
    if tool == 'AskUserQuestion':
        qs = inp.get('questions') or []
        q = (qs[0].get('question') if qs and isinstance(qs[0], dict) else '') or pa.get('action_description') or ''
        return 'Question: ' + q.strip() if q else 'A question for you'
    if tool == 'ExitPlanMode':
        return 'A plan waits for your approval'
    name = pa.get('display_tool_name') or tool or 'a tool'
    desc = (pa.get('action_description') or '').strip()
    return f'Permission: {name}' + (f' · {desc}' if desc and desc != name else '')


def summarize(s, kit, env_dirs=None):
    """The glasses' line for one session: the API's session record `s` with what the Kit knows."""
    cse = s.get('id') or ''
    x = kit.record(cse)
    a = x.get('app') or {}
    em = s.get('external_metadata') or {}
    pts = em.get('post_turn_summary') or {}
    title = (s.get('title') or x.get('title') or '').strip() or 'Session ' + cse[-6:]
    worker = s.get('worker_status') or ''
    has_pending = worker == 'requires_action'
    in_turn = worker == 'running'
    bg = None if in_turn else kit.background(cse)
    working = in_turn or bool(bg)
    hold = kit.hold_for(cse)
    waits = kit.waits_for(cse)
    unread = bool(s.get('unread'))
    kit_needs = bool(a.get('needs')) and (a.get('last_event_at') or '') == (s.get('last_event_at') or '')
    asks = (pts.get('needs_action') or '').strip()
    why = None
    if hold:
        status = 'waiting'
        until = _num(hold.get('until'))
        limit = hold.get('limit') or 'usage'
        why = f'Held at the {limit} limit' + (f' until {clock(until)}' if until else '')
    elif has_pending or (not working and unread and (kit_needs or asks)):
        status = 'needs_you'
        why = (pending_words(em.get('pending_action')) if has_pending else None) \
            or (a.get('why') if kit_needs else None) or asks or 'Waiting on your answer or permission'
    elif working:
        status = 'working'
        why = bg
    elif waits:
        status = 'waiting'
        w = waits[0]
        what = (w.get('what') or w.get('subject') or '').strip()
        if not what:
            kind = w.get('kind') or ''
            what = {'email-reply': 'An email reply', 'pr': 'A pull request', 'at': 'A set time'}.get(kind, 'A check')
        frm = (w.get('from') or '').strip()
        why = what + (f' · from {frm}' if frm else '') + (f' (+{len(waits) - 1} more)' if len(waits) > 1 else '')
    else:
        status = 'idle'
    line = None
    if status == 'working':
        line = kit.checkin(cse) or em.get('task_summary') or pts.get('status_detail')
    else:
        line = pts.get('status_detail') or em.get('task_summary')
    folder = kit.folder_of(cse) or (env_dirs or {}).get(s.get('environment_id') or '') or None
    return {
        'id': cse,
        'title': title,
        'folder': folder,
        'status': status,
        'why': (why or None) and str(why)[:300],
        'status_line': (line or None) and str(line)[:300],
        'updated_at': s.get('last_event_at') or s.get('updated_at') or s.get('created_at'),
        'has_pending': has_pending,
        # extra fields (the contract allows more): where the session is and what it runs on
        'url': s.get('session_url') or a.get('url') or ('https://claude.ai/code/session_' + cse.split('_', 1)[-1]),
        'connected': s.get('connection_status') == 'connected',
        'unread': unread,
        'effort': em.get('effort_level') or None,
    }


def ordered(rows):
    """Needs you first, then working, waiting, idle; the newest first in each (two stable sorts)."""
    rows = sorted(rows, key=lambda r: (r.get('updated_at') or '', r['id']), reverse=True)
    return sorted(rows, key=lambda r: ORDER.get(r['status'], 9))
