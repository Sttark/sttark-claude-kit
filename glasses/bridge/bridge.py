#!/usr/bin/python3
"""Sttark Kit glasses bridge: lets Even Realities G2 glasses (an app in the Even app) see and drive the Claude Code
sessions that run on this Mac. One process, Python standard library only.

    /usr/bin/python3 glasses/bridge/bridge.py [--port 8740] [--host 0.0.0.0]

It serves a small JSON API and a WebSocket on the local network (and the WireGuard VPN) only: every request needs
the bridge's token, and a request from an address outside the private ranges is refused. Prompts and replies go
between this Mac and the glasses only; nothing is sent to any other server but Claude's own API.
README.md beside this file has the API and how each action reaches a session.
"""
import argparse
import base64
import ipaddress
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)

import detail  # noqa: E402
import glance  # noqa: E402
import kitstate  # noqa: E402
import rcapi  # noqa: E402
import stt  # noqa: E402
import web  # noqa: E402
import wsock  # noqa: E402

VERSION = '0.1.0'
HOME = os.path.expanduser('~')
SUPPORT = os.environ.get('G2_SUPPORT_DIR') or os.path.join(HOME, 'Library/Application Support/Sttark Kit Glasses')
TOKEN_FILE = os.path.join(SUPPORT, 'token')
LOG_FILE = os.environ.get('G2_LOG') or os.path.join(HOME, 'Library/Logs/sttark-kit-glasses-bridge.log')
DEFAULT_FOLDER = os.path.join(HOME, 'src')
CLAUDE = os.path.join(HOME, '.local/share/claude/stable/claude')
SESSION_ID = re.compile(r'^(cse|session)_[A-Za-z0-9]{10,64}$')
OLDER_PAGE = 500  # events per read when the last reply is below the newest page (the API takes up to 1000)
OLDER_PAGES = 40  # at most this many reads back for it: 20,000 events
MAX_BODY = 12 * 1024 * 1024  # 6 minutes of 16 kHz 16-bit audio, with room
PRIVATE_EXTRA = [ipaddress.ip_network('100.64.0.0/10')]  # carrier-grade NAT / VPN ranges


def log(msg):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + msg
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except OSError:
        pass


def load_token():
    os.makedirs(SUPPORT, mode=0o700, exist_ok=True)
    os.chmod(SUPPORT, 0o700)
    try:
        with open(TOKEN_FILE) as f:
            t = f.read().strip()
        if len(t) >= 16:
            return t
    except OSError:
        pass
    raw = base64.b32encode(secrets.token_bytes(15)).decode().lower()  # 120 bits, letters and digits only
    t = '-'.join(raw[i:i + 4] for i in range(0, len(raw), 4))
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(t + '\n')
    os.chmod(TOKEN_FILE, 0o600)
    return t


def local_addresses():
    out = []
    try:
        r = subprocess.run(['/sbin/ifconfig'], capture_output=True, text=True, timeout=5).stdout
        iface = ''
        for line in r.splitlines():
            if line and not line[0].isspace():
                iface = line.split(':', 1)[0]
            m = re.match(r'\s+inet (\d+\.\d+\.\d+\.\d+)', line)
            if m and not m.group(1).startswith('127.'):
                out.append((iface, m.group(1)))
    except Exception:
        pass
    return out


def private(addr):
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if getattr(ip, 'ipv4_mapped', None):
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local or any(ip in n for n in PRIVATE_EXTRA)


def label_of(path):
    rel = os.path.relpath(path, HOME)
    return path if rel.startswith('..') else rel


def trusted(folder):
    """Claude Code trusts the folder or one above it (projects[...].hasTrustDialogAccepted in ~/.claude.json): a
    session started there opens with no safety question, which nobody could answer in a hidden screen."""
    try:
        with open(os.path.join(HOME, '.claude.json')) as f:
            projects = json.load(f).get('projects') or {}
    except (OSError, ValueError):
        return False
    p = os.path.realpath(folder)
    while True:
        if (projects.get(p) or {}).get('hasTrustDialogAccepted') is True:
            return True
        up = os.path.dirname(p)
        if up == p or p == HOME:
            return False
        p = up


def title_of(prompt):
    """A new session's name from its first message: the first line, cut at a word to 60 characters."""
    line = next((l.strip() for l in prompt.splitlines() if l.strip()), '')
    line = ' '.join(line.split())
    if len(line) > 60:
        cut = line[:58].rsplit(' ', 1)[0] if ' ' in line[:58] else line[:58]
        line = cut.rstrip(' ,;:.-') + '...'
    return line or 'New session'


class HTTPError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


# -- the live view ----------------------------------------------------------------------------------------------

class Tracker:
    """One session's recent events, kept current from its event stream while a glasses client follows it."""

    def __init__(self, hub, cse):
        self.hub, self.cse = hub, cse
        self.events = []  # newest first
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.watchers = 0
        self.idle_since = None
        threading.Thread(target=self.run, name='track-' + cse[-6:], daemon=True).start()

    def last_seq(self):
        return detail.seq(self.events[0]) if self.events else 0

    def load(self):
        evs, _ = rcapi.events(self.cse, limit=100, desc=True)
        self.events = evs
        self.ready.set()

    def run(self):
        backoff = 2
        while not self.stop.is_set():
            try:
                self.load()
                self.hub.session_changed(self.cse)
                for kind, ev in rcapi.event_stream(self.cse, self.last_seq(), self.stop):
                    if kind != 'event' or detail.seq(ev) <= self.last_seq():
                        continue
                    self.events = ([ev] + self.events)[:300]
                    t = detail.payload(ev).get('type')
                    if t in ('control_request', 'control_response', 'control_cancel_request', 'result'):
                        self.hub.refresh_session(self.cse)  # the session's own state moved: read it now
                    self.hub.session_changed(self.cse)
                    backoff = 2
                self.stop.wait(1)  # the stream ended on its own: open it again
            except Exception as e:  # a dropped stream, a refused login, the network
                if self.stop.is_set():
                    return
                log(f'track  {self.cse} stream: {type(e).__name__}: {str(e)[:160]}; again in {backoff} s')
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 60)


class History:
    """One session's events, every one since its start, slim and oldest first, for its turns (scrolling back on the
    lens). The first read takes all of them, 1000 at a time (a few seconds for a long session); later reads take
    only the events after the newest one held."""

    PAGE = 1000

    def __init__(self, cse):
        self.cse = cse
        self.lock = threading.Lock()
        self.events = []
        self.seq = 0
        self.turns = []
        self.read_at = 0.0
        self.used = time.time()

    def update(self, newest_seen=0):
        """The turns now. Asks the API only when the session may have new events: always after 3 seconds, sooner
        when the session's live stream (`newest_seen`) shows events this history does not have."""
        with self.lock:
            self.used = time.time()
            if self.read_at and time.time() - self.read_at < 3 and newest_seen <= self.seq:
                return self.turns
            started, got = time.time(), 0
            while True:
                evs, nxt = rcapi.events(self.cse, limit=self.PAGE, desc=False, cursor=self.seq or None)
                new = sorted((e for e in evs if detail.seq(e) > self.seq), key=detail.seq)
                if new:
                    self.events += [detail.slim_event(e) for e in new]
                    self.seq = detail.seq(new[-1])
                    got += len(new)
                if len(evs) < self.PAGE or not nxt or not new:
                    break
            self.read_at = time.time()
            if got or not self.turns:
                self.turns = detail.turns(self.events)
            if got > self.PAGE:
                log(f'turns  {self.cse}: read {got} events in {time.time() - started:.1f} s, '
                    f'{len(self.turns)} turns')
            return self.turns


class Hub:
    def __init__(self):
        self.lock = threading.RLock()
        self.kit = kitstate.KitState()
        self.api = {}  # cse -> the API's session record, live (listed) sessions only
        self.env_dirs = {}  # environment id -> folder, this Mac's Remote Control servers
        self.envs_at = 0
        self.rows = []
        self.rows_json = ''
        self.clients = set()
        self.trackers = {}
        self.histories = {}  # cse -> History, while the glasses scroll back in it
        self.sent = {}  # cse -> json of the last detail pushed
        self.partials = {}  # request id -> {question index: label}, for prompts with several questions
        self.older = {}  # cse -> {'events': the events its last reply needs (slim, newest first), 'start': bool}
        self.web = web.Web(rcapi.LOGIN.org())
        self.last_message_at = 0.0
        self.stop = threading.Event()
        self.list_ok_at = 0.0
        self.list_error = ''
        self.cards = glance.Cards(SUPPORT, fetch=self.glance_input, ready=self.glance_ready,
                                  ask=glance_off if os.environ.get('G2_GLANCE_OFF') else glance.ask_haiku,
                                  held=lambda: glance.kit_held(kitstate.KIT),
                                  only=os.environ.get('G2_GLANCE_ONLY', ''), log=log)

    # -- data in
    def envs(self, force=False):
        if force or time.time() - self.envs_at > 600:
            try:
                dirs = {}
                for e in rcapi.environments():
                    c = e.get('config') or {}
                    if c.get('type') == 'bridge' and not e.get('archived_at') and c.get('directory'):
                        dirs[e['id']] = c['directory']
                self.env_dirs = dirs
                self.envs_at = time.time()
            except Exception as e:
                log(f'envs   could not read the environments: {str(e)[:160]}')
        return self.env_dirs

    def put(self, s):
        cse = s.get('id')
        if not cse:
            return
        with self.lock:
            if kitstate.listed(s):
                self.api[cse] = s
            else:
                self.api.pop(cse, None)

    def refresh_session(self, cse):
        try:
            self.put(rcapi.get_session(cse))
        except rcapi.APIError as e:
            if e.status == 404:
                with self.lock:
                    self.api.pop(cse, None)
        except Exception:
            pass
        self.recompute()

    def list_loop(self):
        backoff = 5
        while not self.stop.is_set():
            try:
                sessions, token = rcapi.list_sessions(statuses=('active',), with_token=True)
                with self.lock:
                    self.api = {s['id']: s for s in sessions if kitstate.listed(s)}
                self.list_ok_at, self.list_error = time.time(), ''
                self.envs()
                self.recompute()
                backoff = 5
                started = time.time()
                for kind, s in rcapi.watch(token, self.stop):
                    if kind in ('added', 'changed') and isinstance(s, dict):
                        self.put(s)
                        self.recompute()
                    self.list_ok_at = time.time()
                    if time.time() - started > 300:
                        break  # list again every 5 minutes, so nothing is missed
                if time.time() - started < 30:
                    self.stop.wait(10)  # a watch that ended at once: no burst of list reads
            except rcapi.LoginExpired as e:
                self.list_error = str(e)
                log(f'list   {e}')
                self.stop.wait(60)
            except Exception as e:
                self.list_error = f'{type(e).__name__}: {str(e)[:200]}'
                status = getattr(e, 'status', 0)
                wait = 60 if status == 429 else backoff
                log(f'list   {self.list_error}; again in {wait} s')
                self.stop.wait(wait)
                backoff = min(backoff * 2, 120)

    def kit_loop(self):
        while not self.stop.is_set():
            try:
                if self.kit.reload():
                    self.recompute()
            except Exception as e:
                log(f'kit    {type(e).__name__}: {e}')
            self.stop.wait(1.0)

    def upkeep_loop(self):
        n = 0
        while not self.stop.wait(25):
            n += 1
            for c in list(self.clients):
                c.ping()
            with self.lock:  # stop following sessions nobody has watched for 2 minutes
                for cse, t in list(self.trackers.items()):
                    if t.watchers <= 0 and t.idle_since and time.time() - t.idle_since > 120:
                        t.stop.set()
                        self.trackers.pop(cse, None)
                        self.sent.pop(cse, None)
                for cse in list(self.older):
                    if cse not in self.api and cse not in self.trackers:
                        self.older.pop(cse, None)
                for cse, h in list(self.histories.items()):  # and their history after 15 minutes
                    if time.time() - h.used > 900:
                        self.histories.pop(cse, None)
            if n % 48 == 0 and time.time() - self.last_message_at < 2 * 3600:
                self.web.touch()  # every 20 minutes while messages go out: keep the claude.ai page

    # -- views
    def recompute(self):
        with self.lock:
            rows = [kitstate.summarize(s, self.kit, self.env_dirs) for s in self.api.values()]
            rows = kitstate.ordered(rows)
            shown = set(self.trackers)
            for r in rows:
                s = self.api.get(r['id']) or {}
                rank = 0 if r['id'] in shown else 1 + kitstate.ORDER.get(r['status'], 3)
                self.cards.note(r['id'], r['title'], marker(s), rank)
                r['glance'] = glance.serve(self.cards.card(r['id']), r['status'])
            js = json.dumps(rows, sort_keys=True)
            changed = js != self.rows_json
            self.rows, self.rows_json = rows, js
            followed = list(self.trackers)
        if changed:
            self.broadcast({'type': 'sessions', 'sessions': rows})
        for cse in followed:
            self.session_changed(cse)

    def row(self, cse):
        with self.lock:
            for r in self.rows:
                if r['id'] == cse:
                    return r
        return None

    def session_record(self, cse):
        s = self.api.get(cse)
        if s is None:
            try:
                s = rcapi.get_session(cse)
            except rcapi.APIError as e:
                if e.status in (400, 404):
                    raise HTTPError(404, 'No such session.')
                raise
            if not kitstate.listed(s):
                raise HTTPError(404, 'That session is archived, or its Claude Code no longer runs.')
        return s

    def events_of(self, cse, fresh=False):
        t = self.trackers.get(cse)
        if t and t.ready.is_set() and not fresh:
            return t.events
        evs, _ = rcapi.events(cse, limit=100, desc=True)
        return evs

    def reply_events(self, cse, evs):
        """`evs` (newest first) and the older events that the last reply needs: the newest assistant turn with text,
        back to its start. A session that waits gathers many events with no message in them (each time a Claude app
        or the Kit connects, and when its Claude Code starts again), so that turn is often far below the newest
        page. The older events read are kept (slim), so the next read needs none of them again."""
        if not evs or detail.reply_whole(evs):
            return evs
        with self.lock:
            kept = self.older.get(cse) or {}
        out, start = list(evs), False
        low = detail.seq(out[-1])
        if kept.get('events') and detail.seq(kept['events'][0]) >= low:  # they reach up to these: no gap
            out += [e for e in kept['events'] if detail.seq(e) < low]
            start = kept.get('start', False)
        pages, size = 0, OLDER_PAGE
        while not start and not detail.reply_whole(out):
            if pages >= OLDER_PAGES:
                log(f'reply  {cse}: no whole reply in the newest {len(out)} events')
                start = True
                break
            low = detail.seq(out[-1])
            try:
                page, nxt = rcapi.events(cse, limit=size, desc=True, cursor=low)  # the events before `low`
            except rcapi.APIError as e:
                if e.status == 400 and size > 100:
                    size = 100  # as Claude Code reads them when the API takes no bigger pages
                    continue
                raise
            pages += 1
            out += [detail.slim(e) for e in page if detail.seq(e) < low]
            if not page or not nxt:
                start = True  # the session's first event
        need = out[:detail.reply_start(out)]
        with self.lock:
            self.older[cse] = {'events': [detail.slim(e) for e in need], 'start': start and len(need) == len(out)}
        return out

    def pending_req(self, s, evs):
        """The prompt that waits now: from the events, and only while the session says it waits for the person."""
        if s.get('worker_status') != 'requires_action':
            return None
        req = detail.find_pending(evs)
        if req:
            return req
        pa = (s.get('external_metadata') or {}).get('pending_action') or {}
        rid = pa.get('request_id') or pa.get('suppressed_request_id')
        if rid:
            return {'request_id': rid, 'tool_name': pa.get('tool_name') or '',
                    'display_name': pa.get('display_tool_name') or pa.get('tool_name') or '',
                    'description': pa.get('action_description') or '', 'tool_use_id': pa.get('tool_use_id'),
                    'input': pa.get('input') if isinstance(pa.get('input'), dict) else {}}
        return None

    def detail(self, cse, fresh=False):
        s = self.session_record(cse)
        evs = self.events_of(cse, fresh)
        with self.lock:
            row = kitstate.summarize(s, self.kit, self.env_dirs)
        req = self.pending_req(s, evs)
        out = dict(row)
        evs = self.reply_events(cse, evs)
        md = detail.last_reply_md(evs)
        out['last_reply'] = detail.last_reply(evs)
        out['reply_parts'] = detail.parts(md)
        out['pending'] = detail.view(req, self.partials.get(req['request_id'])) if req else None
        out['has_pending'] = bool(out['pending'])
        out['glance'] = glance.serve(self.cards.for_reply(cse, row['title'], md, out['pending'], marker(s)),
                                     row['status'])
        return out

    def turns(self, cse, before=None, limit=5):
        """Turns of the session, oldest first: the `limit` turns before turn `before` (all of them by default),
        with how many there are and which one the session screen shows now (detail.latest_turn)."""
        self.session_record(cse)
        with self.lock:
            h = self.histories.get(cse)
            if h is None:
                h = self.histories[cse] = History(cse)
            t = self.trackers.get(cse)
        newest = t.last_seq() if t and t.ready.is_set() else 0
        ts = h.update(newest)
        total = len(ts)
        end = total if before is None else max(0, min(before, total))
        return {'turns': ts[max(0, end - limit):end], 'total': total, 'latest': detail.latest_turn(ts)}

    # -- glance cards (glance.py)
    def glance_input(self, cse):
        """What a session's card is made from: its title, its newest reply (Markdown) and the prompt that waits."""
        try:
            s = self.session_record(cse)
        except HTTPError:
            return None
        evs = self.events_of(cse)
        req = self.pending_req(s, evs)
        pending = detail.view(req, self.partials.get(req['request_id'])) if req else None
        with self.lock:
            title = (self.row(cse) or {}).get('title') or s.get('title') or ''
        return title, detail.last_reply_md(self.reply_events(cse, evs)), pending

    def glance_ready(self, cse):
        self.recompute()

    def session_changed(self, cse):
        watchers = [c for c in list(self.clients) if cse in c.subs]
        if not watchers:
            return
        try:
            d = self.detail(cse)
        except Exception as e:
            log(f'detail {cse}: {type(e).__name__}: {str(e)[:160]}')
            return
        js = json.dumps(d, sort_keys=True)
        if self.sent.get(cse) == js:
            return
        self.sent[cse] = js
        for c in watchers:
            c.send({'type': 'session', 'session': d})

    def broadcast(self, msg):
        for c in list(self.clients):
            c.send(msg)

    def follow(self, client, cse):
        """Follow `cse` for `client` now; its detail follows at once, from a thread (the first read can take a
        moment). Following a session twice counts once."""
        with self.lock:
            t = self.trackers.get(cse)
            if t is None or t.stop.is_set():
                t = self.trackers[cse] = Tracker(self, cse)
            if cse not in client.subs:
                client.subs.add(cse)
                t.watchers += 1
            t.idle_since = None
        self.sent.pop(cse, None)

        def push():
            t.ready.wait(10)
            self.session_changed(cse)
        threading.Thread(target=push, name='push-' + cse[-6:], daemon=True).start()

    def live_message(self, client, msg):
        """One message from a glasses client. `subscribe` names the session the client shows now: it replaces
        the one before, and no id (the client is back on its list) follows none. `unsubscribe` stops one."""
        if not isinstance(msg, dict):
            return
        t, sid = msg.get('type'), msg.get('id') or ''
        cse = ('cse_' + sid.split('_', 1)[1]) if isinstance(sid, str) and SESSION_ID.match(sid) else None
        if t == 'subscribe':
            for old in list(client.subs):
                if old != cse:
                    self.unfollow(client, old)
            if cse:
                self.follow(client, cse)
        elif t == 'unsubscribe' and cse:
            self.unfollow(client, cse)
        elif t == 'ping':
            client.send({'type': 'pong'})

    def unfollow(self, client, cse):
        if cse not in client.subs:
            return
        client.subs.discard(cse)
        with self.lock:
            t = self.trackers.get(cse)
            if t:
                t.watchers -= 1
                if t.watchers <= 0:
                    t.idle_since = time.time()

    # -- actions
    def send_message(self, cse, text):
        self.session_record(cse)
        mid = str(uuid.uuid4())
        try:
            self.web.send_message(cse, text, mid)
        except web.WebUnavailable as e:
            raise HTTPError(503, f'The message was not sent: {e}')
        self.last_message_at = time.time()
        log(f'send   {cse}: a message of {len(text)} characters, as the claude.ai sign-in')
        return mid

    def answer(self, cse, option_id):
        s = self.session_record(cse)
        try:
            s = rcapi.get_session(cse)  # its state now, not the list's
            self.put(s)
        except Exception:
            pass
        evs = self.events_of(cse, fresh=True)
        req = self.pending_req(s, evs)
        if not req:
            raise HTTPError(409, 'Nothing waits for an answer in this session now.')
        rid = req['request_id']
        try:
            done, partial, behavior, upd, msg = detail.decide(req, option_id, self.partials.get(rid))
        except detail.BadOption as e:
            raise HTTPError(400, str(e))
        if not done:
            self.partials[rid] = partial
            self.session_changed(cse)
            return {'ok': True, 'done': False, 'pending': detail.view(req, partial)}
        rcapi.answer_tool(cse, rid, behavior, tool_use_id=req.get('tool_use_id'), updated_input=upd, message=msg,
                          tool_name=req.get('tool_name'))
        self.partials.pop(rid, None)
        log(f'answer {cse}: {req.get("tool_name")} {behavior}')
        threading.Thread(target=self.refresh_session, args=(cse,), daemon=True).start()
        return {'ok': True, 'done': True}

    def folders(self):
        cands = [DEFAULT_FOLDER] + list(self.envs().values()) + self.kit.recent_folders()
        out, seen = [], set()
        for p in cands:
            if not p:
                continue
            p = os.path.realpath(os.path.expanduser(p))
            if p in seen or p == HOME or not p.startswith(HOME + '/') or not os.path.isdir(p):
                continue
            if '/.claude/worktrees/' in p or '/Library/' in p[len(HOME):] or '/.' in p[len(HOME):]:
                continue
            seen.add(p)
            out.append({'path': p, 'label': label_of(p)})
            if len(out) >= 15:
                break
        return out

    def create(self, prompt, folder):
        folder = os.path.realpath(os.path.expanduser(folder or DEFAULT_FOLDER))
        if not os.path.isdir(folder):
            raise HTTPError(400, 'That folder is not on this Mac.')
        if folder == HOME or not folder.startswith(HOME + '/'):
            raise HTTPError(400, 'Pick a folder inside your home folder (not the home folder itself).')
        title = title_of(prompt)
        env = next((e for e, d in self.envs(force=True).items() if os.path.realpath(d) == folder), None)
        if env and web_ready(self.web):
            s = rcapi.create_session(env, title, folder)
            cse = s['id']
            self.put(s)
            log(f'start  {cse} on this Mac\'s Remote Control server ({label_of(folder)})')
            try:
                self.web.send_message(cse, prompt, str(uuid.uuid4()))
            except web.WebUnavailable as e:
                raise HTTPError(503, f'The session {cse} started, but its first message was not sent: {e}')
            self.last_message_at = time.time()
            self.recompute()
            return {'id': cse, 'folder': folder, 'started': 'server'}
        if not trusted(folder):
            raise HTTPError(400, 'Claude Code does not trust that folder yet. Start one session there on the Mac '
                                 'first.')
        cse = start_cli(folder, title, prompt)
        log(f'start  {cse} in its own Claude Code ({label_of(folder)})')
        threading.Thread(target=self.refresh_session, args=(cse,), daemon=True).start()
        return {'id': cse, 'folder': folder, 'started': 'cli'}


def marker(s):
    """What changes when anything in a session changes: its last event, and whether it works or asks."""
    return f"{s.get('last_event_at') or s.get('updated_at') or ''}|{s.get('worker_status') or ''}"


def glance_off(system, text):
    raise RuntimeError('G2_GLANCE_OFF is set')


def web_ready(w):
    """claude.ai in Chrome answers now: the server path needs it for the first message."""
    try:
        status, _ = w.call('GET', '/v1/code/sessions?limit=1&statuses=active')
        return status == 200
    except web.WebUnavailable as e:
        log(f'web    not ready: {e}')
        return False


def start_cli(folder, title, prompt):
    """A new session in its own Claude Code with Remote Control, in a hidden screen, as Sttark Claude Kit starts
    one (effort-hook.py start_screen): a clean environment, the person's first message on its command line (typed
    as theirs), and its first turn held 8 seconds so Claude's connectors are in it. Returns its Remote Control id."""
    name = 'g2-' + uuid.uuid4().hex[:8]
    pdir = os.path.join(SUPPORT, 'prompts')
    os.makedirs(pdir, mode=0o700, exist_ok=True)
    pfile = os.path.join(pdir, name + '.txt')
    fd = os.open(pfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(prompt)
    hold = json.dumps({'hooks': {'SessionStart': [{'matcher': 'startup|resume', 'hooks': [
        {'type': 'command', 'command': '/bin/sleep 8', 'timeout': 38}]}]}}, separators=(',', ':'))
    cmd = (f'cd {shlex.quote(folder)} && exec {shlex.quote(CLAUDE)} --remote-control {shlex.quote(title)} '
           f'--permission-mode bypassPermissions --settings {shlex.quote(hold)} "$(cat {shlex.quote(pfile)})"')
    env = {'HOME': HOME, 'USER': os.environ.get('USER', ''), 'LOGNAME': os.environ.get('USER', ''),
           'SHELL': '/bin/zsh', 'TERM': 'xterm-256color', 'LANG': 'en_US.UTF-8',
           'PATH': f'{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'}
    subprocess.run(['/usr/bin/screen', '-dmS', name, '/bin/zsh', '-lc', cmd], env=env, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    copy = os.path.join(pdir, name + '.screen')
    try:
        for _ in range(90):  # its link shows on its screen once Remote Control is on
            time.sleep(1)
            try:
                os.unlink(copy)
            except OSError:
                pass
            subprocess.run(['/usr/bin/screen', '-S', name, '-p', '0', '-X', 'hardcopy', '-h', copy],
                           capture_output=True, timeout=10)
            for _ in range(10):
                if os.path.exists(copy):
                    break
                time.sleep(0.1)
            try:
                with open(copy, errors='replace') as f:
                    m = re.search(r'claude\.ai/code/session_([A-Za-z0-9]+)', f.read())
            except OSError:
                m = None
            if m:
                return 'cse_' + m.group(1)
    finally:
        for p in (copy, pfile):
            try:
                os.unlink(p)
            except OSError:
                pass
    raise HTTPError(504, f'The new session did not connect to Remote Control in 90 seconds (screen {name}).')


# -- HTTP and WebSocket ---------------------------------------------------------------------------------------------

class Client:
    def __init__(self, ws):
        self.ws = ws
        self.subs = set()

    def send(self, msg):
        try:
            self.ws.send_json(msg)
        except wsock.Closed:
            pass

    def ping(self):
        try:
            self.ws.ping()
        except wsock.Closed:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = 'SttarkKitGlassesBridge/' + VERSION
    protocol_version = 'HTTP/1.1'
    hub = None
    token = ''

    def log_message(self, fmt, *args):
        pass  # one line per action instead, from the hub (never a message's words)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Max-Age', '600')

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status, msg):
        self._json({'ok': False, 'error': msg}, status)

    def _authed(self, query):
        h = self.headers.get('Authorization') or ''
        given = h[7:].strip() if h.lower().startswith('bearer ') else (query.get('token') or [''])[0]
        return bool(given) and secrets.compare_digest(given.encode(), self.token.encode())

    def _body(self, limit=1 << 20):
        n = int(self.headers.get('Content-Length') or 0)
        if n > limit:
            raise HTTPError(413, 'Too large.')
        return self.rfile.read(n) if n else b''

    def _json_body(self):
        try:
            d = json.loads(self._body() or b'{}')
        except ValueError:
            raise HTTPError(400, 'The body is not JSON.')
        if not isinstance(d, dict):
            raise HTTPError(400, 'The body must be a JSON object.')
        return d

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        self._route('GET')

    def do_POST(self):
        self._route('POST')

    def _route(self, method):
        if not private(self.client_address[0]):
            self._fail(403, 'This bridge answers on the local network and the VPN only.')
            return
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path.rstrip('/') or '/'
        if not self._authed(q):
            given = self.headers.get('Authorization') or (q.get('token') or [''])[0]
            self._fail(401, 'That token is not this bridge\'s token.' if given else
                       'A token is needed: Authorization: Bearer <token>.')
            return
        try:
            if method == 'GET' and path == '/api/live':
                return self._live()
            self._dispatch(method, path, q)
        except HTTPError as e:
            self._fail(e.status, str(e))
        except rcapi.LoginExpired as e:
            self._fail(503, str(e))
        except rcapi.APIError as e:
            self._fail(502, f'Claude\'s API answered {e.status}: {e.body[:200]}')
        except Exception as e:
            log(f'error  {method} {path}: {type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}')
            self._fail(500, f'{type(e).__name__}: {str(e)[:200]}')

    def _dispatch(self, method, path, q):
        hub = self.hub
        m = re.fullmatch(r'/api/sessions/([^/]+)(?:/(message|answer|turns))?', path)
        if m and not SESSION_ID.match(m.group(1)):
            raise HTTPError(400, 'That is not a session id.')
        cse = ('cse_' + m.group(1).split('_', 1)[1]) if m else None
        if method == 'GET' and path == '/api/health':
            self._json({'ok': True, 'version': VERSION, 'sessions': len(hub.rows),
                        'list_ok_at': hub.list_ok_at or None, 'list_error': hub.list_error or None,
                        'kit': bool(hub.kit.state), 'stt': stt.status() or 'ready',
                        'web': {'chrome': web.Web.chrome_running(), 'last_ok': hub.web.last_ok or None,
                                'last_error': hub.web.last_error or None}})
        elif method == 'GET' and path == '/api/sessions':
            with hub.lock:
                rows = list(hub.rows)
            self._json({'sessions': rows})
        elif method == 'GET' and m and not m.group(2):
            self._json(hub.detail(cse, fresh=True))
        elif method == 'GET' and m and m.group(2) == 'turns':
            def number(name, default, lo, hi):
                v = (q.get(name) or [''])[0]
                if v == '':
                    return default
                if not re.fullmatch(r'\d{1,7}', v) or not lo <= int(v) <= hi:
                    raise HTTPError(400, f'{name} must be a whole number from {lo} to {hi}.')
                return int(v)
            self._json(hub.turns(cse, number('before', None, 0, 9999999), number('limit', 5, 1, 20)))
        elif method == 'POST' and m and m.group(2) == 'message':
            text = (self._json_body().get('text') or '').strip()
            if not text:
                raise HTTPError(400, 'Give the message as {"text": "..."}.')
            if len(text) > 20000:
                raise HTTPError(413, 'The message is over 20000 characters.')
            mid = hub.send_message(cse, text)
            self._json({'ok': True, 'uuid': mid})
        elif method == 'POST' and m and m.group(2) == 'answer':
            option = (self._json_body().get('option_id') or '').strip()
            if not option:
                raise HTTPError(400, 'Give the answer as {"option_id": "..."}.')
            self._json(hub.answer(cse, option))
        elif method == 'POST' and path == '/api/sessions':
            d = self._json_body()
            prompt = (d.get('prompt') or '').strip()
            if not prompt:
                raise HTTPError(400, 'Give the first message as {"prompt": "..."}.')
            self._json(hub.create(prompt, d.get('folder')))
        elif method == 'GET' and path == '/api/folders':
            self._json({'folders': hub.folders()})
        elif method == 'POST' and path == '/api/transcribe':
            pcm = self._body(MAX_BODY)
            try:
                text = stt.transcribe(pcm, (q.get('language') or ['en'])[0])
            except stt.STTUnavailable as e:
                raise HTTPError(503, f'Speech to text is not ready: {e}')
            except ValueError as e:
                raise HTTPError(413, str(e))
            log(f'stt    {len(pcm) / 32000:.1f} s of audio to {len(text)} characters')
            self._json({'text': text})
        else:
            raise HTTPError(404, 'No such endpoint.')

    def _live(self):
        if (self.headers.get('Upgrade') or '').lower() != 'websocket' or not self.headers.get('Sec-WebSocket-Key'):
            raise HTTPError(400, 'This address is a WebSocket.')
        self.send_response(101, 'Switching Protocols')
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', wsock.accept_key(self.headers['Sec-WebSocket-Key']))
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        ws = wsock.WebSocket(self.connection, self.rfile)
        client = Client(ws)
        hub = self.hub
        hub.clients.add(client)
        log(f'live   a client connected from {self.client_address[0]} ({len(hub.clients)} now)')
        try:
            with hub.lock:
                rows = list(hub.rows)
            client.send({'type': 'sessions', 'sessions': rows})
            while True:
                try:
                    msg = json.loads(ws.receive())
                except ValueError:
                    continue
                hub.live_message(client, msg)
        except wsock.Closed:
            pass
        finally:
            hub.clients.discard(client)
            for cse in list(client.subs):
                hub.unfollow(client, cse)
            ws.close()
            log(f'live   a client left ({len(hub.clients)} now)')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser(description='Sttark Kit glasses bridge')
    ap.add_argument('--host', default=os.environ.get('G2_HOST', '0.0.0.0'))
    ap.add_argument('--port', type=int, default=int(os.environ.get('G2_PORT', '8740')))
    ap.add_argument('--print-token', action='store_true', help='print the token and exit')
    a = ap.parse_args()
    token = load_token()
    if a.print_token:
        print(token)
        return
    hub = Hub()
    Handler.hub, Handler.token = hub, token
    srv = Server((a.host, a.port), Handler)
    for target in (hub.list_loop, hub.kit_loop, hub.upkeep_loop):
        threading.Thread(target=target, name=target.__name__, daemon=True).start()
    log(f'Sttark Kit glasses bridge {VERSION} on port {a.port}')
    for iface, ip in local_addresses():
        if private(ip):
            log(f'  http://{ip}:{a.port}   ({iface})')
    log(f'  token: {token}')
    log(f'  (the token is in {TOKEN_FILE})')
    missing = stt.status()
    log('  speech to text: ' + ('ready (whisper.cpp, on this Mac)' if not missing else missing))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        hub.stop.set()


if __name__ == '__main__':
    main()
