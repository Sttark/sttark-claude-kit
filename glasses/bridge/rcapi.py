"""The Claude Remote Control API, as the Claude app uses it, with this Mac's Claude Code login.

Python standard library only. The calls are the ones the Claude app (claude.ai/code, the phone and desktop apps)
makes to steer a session that runs on this Mac:

- GET  /v1/code/sessions                       the session list
- GET  /v1/code/sessions/{id}                  one session
- GET  /v1/code/sessions/{id}/events           its history (newest first with sort_order=desc)
- POST /v1/code/sessions/{id}/events           a user message, or the answer to a question or permission
- POST /v1/code/sessions                       a new session in a Remote Control environment (this Mac's server)
- GET  /v1/environments                        the environments (which one is this Mac's server for a folder)
- GET  /v1/code/sessions/watch                 a stream of changes to the list

The one header that matters: `anthropic-client-platform: web_claude_ai`. The API writes it into each message as
`client_platform`, and Claude Code (2.1.220 and later) starts a turn for a user message only when that value is one
of the Claude apps (ios, android, web_claude_ai, desktop_app). Any other value makes the message a "peer" message
from another session, which Claude Code holds and never acts on.

The login is read from the Keychain item Claude Code keeps ("Claude Code-credentials"), as the Kit's own scripts
read it. This module never refreshes the token: a refresh token works once, and Claude Code itself refreshes and
saves it. When the saved token has expired, the call says so (LoginExpired); the next read after a Claude Code
session refreshes it works again.
"""
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.environ.get('G2_API_BASE', 'https://api.anthropic.com')
CLIENT_PLATFORM = 'web_claude_ai'
ENV_BETA = 'environments-2025-11-01'
USER_AGENT = 'sttark-kit-glasses-bridge/0.1'


class APIError(Exception):
    def __init__(self, status, body):
        super().__init__(f'HTTP {status}: {body[:300]}')
        self.status = status
        self.body = body


class LoginExpired(Exception):
    pass


class Login:
    """The Claude Code login from the Keychain, read again when it is old or refused."""

    def __init__(self):
        self._lock = threading.Lock()
        self._token = None
        self._expires = 0.0
        self._read_at = 0.0
        self._org = None

    def _read(self):
        raw = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w'],
                             capture_output=True, text=True, timeout=15).stdout
        oauth = json.loads(raw)['claudeAiOauth']
        self._token = oauth['accessToken']
        self._expires = (oauth.get('expiresAt') or 0) / 1000.0
        self._read_at = time.time()

    def token(self, force=False):
        with self._lock:
            # read again every 5 minutes, near the end of its life, and when the API refused it
            if force or not self._token or time.time() - self._read_at > 300 or time.time() > self._expires - 60:
                self._read()
            if time.time() > self._expires:
                raise LoginExpired('The Claude Code login on this Mac has expired. It renews the next time a '
                                   'Claude Code session talks to Claude; try again in a minute.')
            return self._token

    def org(self):
        if self._org is None:
            with open(os.path.expanduser('~/.claude.json')) as f:
                self._org = (json.load(f).get('oauthAccount') or {}).get('organizationUuid') or ''
        return self._org


LOGIN = Login()


def headers(beta=None, accept=None):
    h = {'Authorization': 'Bearer ' + LOGIN.token(), 'Content-Type': 'application/json',
         'anthropic-version': '2023-06-01', 'anthropic-client-platform': CLIENT_PLATFORM, 'User-Agent': USER_AGENT}
    if LOGIN.org():
        h['x-organization-uuid'] = LOGIN.org()
    if beta:
        h['anthropic-beta'] = beta
    if accept:
        h['Accept'] = accept
    return h


def call(method, path, body=None, beta=None, timeout=20, ok=(200, 201)):
    """One API call; JSON in and out. Reads the login again and retries once when the API refuses it (401)."""
    url = BASE + path
    data = None if body is None else json.dumps(body).encode()
    for attempt in (0, 1):
        req = urllib.request.Request(url, data=data, method=method, headers=headers(beta))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode('utf-8', 'replace')
                if resp.status not in ok:
                    raise APIError(resp.status, text)
                return json.loads(text) if text.strip() else None
        except urllib.error.HTTPError as e:
            text = e.read().decode('utf-8', 'replace')
            if e.code == 401 and attempt == 0:
                LOGIN.token(force=True)
                continue
            if e.code in ok:
                return json.loads(text) if text.strip() else None
            raise APIError(e.code, text)
    raise APIError(401, 'login refused')


def unwrap(d):
    if isinstance(d, dict):
        for k in ('response_shape', 'session'):
            if isinstance(d.get(k), dict):
                return d[k]
    return d


# -- sessions -------------------------------------------------------------------------------------------------------

def list_sessions(statuses=('active',), limit=100, pages=3, with_token=False):
    """The account's sessions, newest first. with_token: also the first page's resume token, for watch()."""
    out, cursor, token = [], '', None
    for i in range(pages):
        q = [('limit', str(limit))] + [('statuses', s) for s in statuses]
        if cursor:
            q.append(('cursor', cursor))
        d = call('GET', '/v1/code/sessions?' + urllib.parse.urlencode(q))
        if i == 0:
            token = d.get('resume_token')
        out += d.get('data') or []
        cursor = d.get('next_cursor')
        if not cursor:
            break
    return (out, token) if with_token else out


def get_session(cse):
    return unwrap(call('GET', '/v1/code/sessions/' + urllib.parse.quote(cse)))


def events(cse, limit=100, desc=True, cursor=None):
    """One page of the session's events: newest first with desc. Returns (events, next_cursor)."""
    q = {'limit': str(limit), 'sort_order': 'desc' if desc else 'asc'}
    if cursor:
        q['cursor'] = str(cursor)
    d = call('GET', f'/v1/code/sessions/{urllib.parse.quote(cse)}/events?' + urllib.parse.urlencode(q))
    return d.get('data') or [], d.get('next_cursor')


def send_events(cse, payloads):
    wrapped = []
    for p in payloads:
        if 'uuid' not in p:
            p = dict(p, uuid=str(uuid.uuid4()))
        wrapped.append({'payload': p})
    return call('POST', f'/v1/code/sessions/{urllib.parse.quote(cse)}/events',
                {'session_id': cse, 'events': wrapped})


def user_message(cse, text, message_uuid=None):
    """The message the Claude app sends when the person types in the session."""
    return {'type': 'user', 'uuid': message_uuid or str(uuid.uuid4()), 'session_id': cse,
            'parent_tool_use_id': None, 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}}


def send_message(cse, text):
    return send_events(cse, [user_message(cse, text)])


def answer_tool(cse, request_id, behavior, tool_use_id=None, updated_input=None, message=None, tool_name=None):
    """Answer a worker's can_use_tool prompt: allow (with updatedInput) or deny (with a message for Claude)."""
    decision = {'behavior': behavior}
    if behavior == 'allow':
        if updated_input is not None:
            decision['updatedInput'] = updated_input
        if tool_use_id:
            decision['toolUseID'] = tool_use_id
        if tool_name:
            decision['tool_name'] = tool_name
    else:
        decision['message'] = message or 'The person said no.'
    resp = {'subtype': 'success', 'request_id': request_id, 'response': decision}
    if tool_use_id:
        resp['tool_use_id'] = tool_use_id
    return send_events(cse, [{'type': 'control_response', 'response': resp}])


def environments():
    d = call('GET', '/v1/environments', beta=ENV_BETA)
    return d.get('data') or []


def bridge_environment(folder):
    """This Mac's Remote Control server for `folder`: the newest active bridge environment with that directory."""
    want = os.path.realpath(os.path.expanduser(folder))
    mine = [e for e in environments() if (e.get('config') or {}).get('type') == 'bridge' and not e.get('archived_at')
            and e.get('state', 'active') == 'active'
            and os.path.realpath((e.get('config') or {}).get('directory') or '/nonexistent') == want]
    return max(mine, key=lambda e: e.get('updated_at') or '') if mine else None


def create_session(environment_id, title, cwd, model=None, permission_mode=None, tags=None):
    """A new session on a Remote Control environment, the body Claude Code's own `claude remote-control` sends
    (createBridgeSession, v1alpha2 on /v1/code/sessions). The server that serves the environment starts it.
    The first message goes after, with send_message(), as the Claude app does it."""
    evs = []
    if permission_mode:
        evs.append({'payload': {'type': 'control_request', 'request_id': f'set-mode-{uuid.uuid4()}',
                                'request': {'subtype': 'set_permission_mode', 'mode': permission_mode}}})
    body = {'title': title, 'environment_id': environment_id, 'events': evs,
            'config': {'sources': [], 'outcomes': [], 'cwd': cwd, **({'model': model} if model else {})}}
    if tags:
        body['tags'] = list(tags)
    return unwrap(call('POST', '/v1/code/sessions', body))


# -- streams (server-sent events) -----------------------------------------------------------------------------------

def _sse(path, last_id, stop, timeout=60):
    """Yield (event, id, data) frames, and ('keepalive', '', '') for each heartbeat, until `stop` is set or the
    stream ends. The server sends a heartbeat about every 15 s, so a read that waits `timeout` seconds means it is
    dead (socket.timeout). Raises APIError on an HTTP error."""
    h = headers(accept='text/event-stream')
    if last_id:
        h['Last-Event-ID'] = str(last_id)
    req = urllib.request.Request(BASE + path, headers=h)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            LOGIN.token(force=True)
        raise APIError(e.code, e.read().decode('utf-8', 'replace'))
    event, data, eid = '', [], ''
    with resp:
        while not stop.is_set():
            line = resp.readline()
            if not line:
                return
            line = line.decode('utf-8', 'replace').rstrip('\r\n')
            if not line:
                if event or data:
                    yield event or 'message', eid, '\n'.join(data)
                event, data, eid = '', [], ''
                continue
            if line.startswith(':'):
                yield 'keepalive', '', ''
                continue
            k, _, v = line.partition(':')
            v = v[1:] if v.startswith(' ') else v
            if k == 'event':
                event = v
            elif k == 'data':
                data.append(v)
            elif k == 'id':
                eid = v


def watch(resume_token, stop):
    """Changes to the session list (GET /v1/code/sessions/watch): ('added'|'changed', session), ('sync', token)
    and ('keepalive', None). Raises APIError (410: the token is too old; list again)."""
    for event, eid, data in _sse('/v1/code/sessions/watch?exclude_tags=-', resume_token, stop):
        if event in ('added', 'changed'):
            try:
                yield event, json.loads(data)
            except ValueError:
                pass
        elif event == 'sync':
            yield 'sync', eid
        elif event == 'keepalive':
            yield 'keepalive', None


def event_stream(cse, after_seq, stop):
    """A session's new events after sequence number `after_seq` (GET .../events/stream): ('event', envelope) for
    each stored event, ('keepalive', None) for each heartbeat."""
    path = f'/v1/code/sessions/{urllib.parse.quote(cse)}/events/stream?from_sequence_num={int(after_seq)}'
    for event, eid, data in _sse(path, after_seq, stop):
        if event == 'client_event':
            try:
                yield 'event', json.loads(data)
            except ValueError:
                pass
        elif event == 'keepalive':
            yield 'keepalive', None
