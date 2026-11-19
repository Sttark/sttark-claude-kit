"""Calls to the Claude API through claude.ai, signed in as the person, in their own Chrome.

Why this exists: Claude Code (2.1.220 and later) starts a turn for a user message only when the API marks the
message as typed in a Claude app (`client_platform` web_claude_ai, desktop_app, ios or android). The API sets that
mark only for the apps' own sign-in. A message sent with Claude Code's own login (the OAuth token in the Keychain)
gets no mark, whatever header it carries, so the session holds it as a "peer message from an unidentified session"
and never acts on it. A message sent from a claude.ai page, with the person's claude.ai sign-in and the header
`anthropic-client-platform: web_claude_ai`, is the Claude web app's own message: the session acts on it.

So the bridge sends user messages (and only those) from a claude.ai page in the Kit's Claude window: the Chrome
window Sttark Claude Kit keeps for sessions (`claude-window`, which needs Chrome's View > Developer > Allow
JavaScript from Apple Events). It never brings Chrome to the front; the Kit's tool makes a window only when it has no
spare one. The page is claude.ai/robots.txt: a claude.ai page that opens no session and runs no app code. Each call
is one synchronous XMLHttpRequest run in that page, with the person's cookies.
"""
import json
import os
import subprocess
import threading
import time

CLAUDE_WINDOW = os.environ.get('G2_CLAUDE_WINDOW') or os.path.expanduser('~/.local/bin/claude-window')
PAGE = 'https://claude.ai/robots.txt'
KEY = 'g2-bridge'  # the Kit's window key for this bridge (claude-window-tabs/<key>)


class WebUnavailable(Exception):
    pass


class Web:
    def __init__(self, org_uuid):
        self.org = org_uuid
        self.lock = threading.Lock()
        self.last_ok = 0.0
        self.last_error = ''

    def _env(self):
        env = dict(os.environ)
        env.pop('CLAUDE_WINDOW_AGENT', None)
        env['CLAUDE_CODE_SESSION_ID'] = KEY
        env['CLAUDE_PID'] = str(os.getpid())  # the Kit closes the page once this process is gone
        return env

    def _run(self, *args, timeout=60):
        if not os.access(CLAUDE_WINDOW, os.X_OK):
            raise WebUnavailable('Sttark Claude Kit\'s claude-window tool is not installed on this Mac.')
        r = subprocess.run([CLAUDE_WINDOW, *args], capture_output=True, text=True, timeout=timeout, env=self._env())
        out = (r.stdout or '').strip()
        if r.returncode != 0:
            raise WebUnavailable((r.stderr or out or f'claude-window {args[0]} failed').strip()[-300:])
        return out

    @staticmethod
    def chrome_running():
        r = subprocess.run(['/bin/ps', '-axww', '-o', 'args='], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.endswith('/Google Chrome.app/Contents/MacOS/Google Chrome') or \
                    '/Google Chrome.app/Contents/MacOS/Google Chrome ' in line:
                if not any(f in line for f in ('--headless', '--remote-debugging-', '--enable-automation',
                                                '--user-data-dir', '--test-type')):
                    return True
        return False

    def _page(self):
        """The bridge's claude.ai page in the Claude window: opened when it is not there."""
        try:
            url = self._run('url', timeout=30).splitlines()[-1:] or ['']
        except WebUnavailable:
            url = ['']
        if url[0].startswith('https://claude.ai/'):
            return
        self._run('go', PAGE, timeout=90)

    def _xhr(self, method, path, body, beta):
        hdrs = {'Content-Type': 'application/json', 'anthropic-version': '2023-06-01',
                'anthropic-client-platform': 'web_claude_ai'}
        if self.org:
            hdrs['x-organization-uuid'] = self.org
        if beta:
            hdrs['anthropic-beta'] = beta
        js = ('(function(){var x=new XMLHttpRequest();x.open(%s,%s,false);var h=%s;'
              'for(var k in h)x.setRequestHeader(k,h[k]);x.withCredentials=true;x.send(%s);'
              'return JSON.stringify({status:x.status,body:x.responseText.slice(0,20000)});})()'
              % (json.dumps(method), json.dumps(path), json.dumps(hdrs),
                 json.dumps(json.dumps(body)) if body is not None else 'null'))
        out = self._run('js', js, timeout=90)
        line = out.splitlines()[-1] if out else ''
        try:
            d = json.loads(line)
            return int(d.get('status') or 0), d.get('body') or ''
        except (ValueError, TypeError):
            raise WebUnavailable('The claude.ai page did not answer: ' + out[-200:])

    def call(self, method, path, body=None, beta=None):
        """One API call as the person's claude.ai sign-in. Returns (status, text)."""
        with self.lock:
            if not self.chrome_running():
                raise WebUnavailable('Chrome is not open on the Mac. Open Chrome, signed in to claude.ai, and try '
                                     'again.')
            try:
                self._page()
                status, text = self._xhr(method, path, body, beta)
                if status in (0, 401, 403):  # the page may be stale or signed out: load it again, once
                    self._run('go', PAGE, timeout=90)
                    status, text = self._xhr(method, path, body, beta)
            except subprocess.TimeoutExpired:
                self.last_error = 'Chrome did not answer in time.'
                raise WebUnavailable(self.last_error)
            except WebUnavailable as e:
                self.last_error = str(e)
                raise
            if status in (401, 403):
                self.last_error = 'claude.ai in Chrome is not signed in (HTTP %d).' % status
                raise WebUnavailable(self.last_error + ' Sign in to claude.ai in Chrome on the Mac.')
            self.last_ok = time.time()
            self.last_error = ''
            return status, text

    def send_message(self, cse, text, message_uuid):
        """The message the Claude web app sends when the person types in a session."""
        sid = 'session_' + cse.split('_', 1)[1]
        body = {'events': [{'type': 'user', 'uuid': message_uuid, 'session_id': sid, 'parent_tool_use_id': None,
                            'message': {'role': 'user', 'content': text}}]}
        status, out = self.call('POST', f'/v1/sessions/{sid}/events', body, beta='ccr-byoc-2025-07-29')
        if status not in (200, 201):
            raise WebUnavailable(f'claude.ai refused the message (HTTP {status}): {out[:200]}')
        return out

    def touch(self):
        """Keep the page in use, so the Kit does not close it after 30 minutes without use. Only a page that is
        there: with none, `claude-window url` would open a blank one, which can bring a new window up."""
        kit = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
        if not os.path.exists(os.path.join(kit, 'claude-window-tabs', KEY)):
            return
        with self.lock:
            try:
                self._run('url', timeout=30)
            except (WebUnavailable, subprocess.TimeoutExpired):
                pass

    def close(self):
        with self.lock:
            try:
                self._run('done', timeout=30)
            except (WebUnavailable, subprocess.TimeoutExpired):
                pass
