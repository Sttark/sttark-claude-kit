#!/usr/bin/python3
"""Tests claude-mail (Resources/hooks/mail.py) and the email reply waits that read a mailbox directly (wait.py), on
copies: a test folder and log (STTARK_KIT_DIR, STTARK_KIT_LOG), a JSON file for the Keychain (STTARK_MAIL_KEYS) and
a stand-in for Google on this Mac (STTARK_MAIL_GOOGLE): no real sign-in, mailbox or Keychain item is touched.
- the sign-in: the link asks for read-only access with PKCE and the address as its hint, and its answer comes back
  to this Mac; a wrong account keeps nothing and the same link works again; the right one keeps the refresh token
  and lists the mailbox;
- search and read: the search goes to Gmail as given; the plain text of a message, else the text of its HTML;
- a wait on a shared mailbox: --query or a thread, only mail newer than the wait and not from the mailbox or the
  person, at any hour every 5 minutes; the prompt says how to read the message; a sign-in that Google refuses, or
  none on this Mac, is the failing check's reason;
- the command: --mailbox and --query set the wait and say how the Kit reads it; a bad address is refused.
Run from the repo root: /usr/bin/python3 tools/mail-test.py"""
import base64, hashlib, importlib.util, json, os, re, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, 'Resources', 'hooks')
d = tempfile.mkdtemp(prefix='kit-mail-')
BOX, ME = 'team@sample.example', 'person@sample.example'
fails = 0


def check(what, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what)
    fails += not ok


# --- the stand-in for Google: sign-in, tokens and a small mailbox --------------------------------------------------
g = {'codes': {}, 'refresh': {}, 'revoked': set(), 'profile': BOX, 'queries': [], 'auth': [], 'n': 0}
T0 = int(time.time()) - 3600


def msg(mid, tid, sender, subject, at, text=None, html=None):
    parts = []
    if text is not None:
        parts.append({'mimeType': 'text/plain', 'body': {'data': base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')}})
    if html is not None:
        parts.append({'mimeType': 'text/html', 'body': {'data': base64.urlsafe_b64encode(html.encode()).decode()}})
    return {'id': mid, 'threadId': tid, 'internalDate': str(at * 1000), 'snippet': subject + ' &amp; more',
            'payload': {'mimeType': 'multipart/alternative', 'parts': parts,
                        'headers': [{'name': 'From', 'value': sender}, {'name': 'To', 'value': BOX},
                                    {'name': 'Subject', 'value': subject}, {'name': 'Date', 'value': 'a date'},
                                    {'name': 'Cc', 'value': 'copy@sample.example'}]}}


MAILBOX = [msg('m1', 't1', 'Old Sender <old@supplier.example>', 'Shipment S123 booked', T0 - 600, text='old'),
           msg('m2', 't1', 'Team <%s>' % BOX, 'Re: Shipment S123 booked', T0 + 60, text='ours'),
           msg('m3', 't1', 'Person <%s>' % ME, 'Re: Shipment S123 booked', T0 + 120, text='the person'),
           msg('m4', 't1', 'Dana <dana@supplier.example>', 'Re: Shipment S123 booked', T0 + 300,
               html='<p>Released <b>today</b></p><br>Dana<style>p{}</style>')]


class Google(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, code, body, headers=()):
        raw = json.dumps(body).encode()
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == '/o/oauth2/v2/auth':   # the browser: Google's page answers with a code for the redirect
            g['auth'].append(q)
            g['n'] += 1
            code = 'code-%d' % g['n']
            g['codes'][code] = q
            return self.answer(302, {}, [('Location', q['redirect_uri'] + '?' + urllib.parse.urlencode(
                {'state': q['state'], 'code': code}))])
        if not (self.headers.get('Authorization') or '').startswith('Bearer at-'):
            return self.answer(401, {'error': {'code': 401, 'message': 'no token', 'status': 'UNAUTHENTICATED'}})
        base = '/gmail/v1/users/me'
        if u.path == base + '/profile':
            return self.answer(200, {'emailAddress': g['profile']})
        if u.path == base + '/messages':
            g['queries'].append(q['q'])
            after = int((re.search(r'after:(\d+)', q['q']) or [0, 0])[1])
            hits = sorted((m for m in MAILBOX if int(m['internalDate']) // 1000 > after), key=lambda m: -int(m['internalDate']))
            return self.answer(200, {'messages': [{'id': m['id'], 'threadId': m['threadId']} for m in hits]})
        m = re.fullmatch(base + r'/(messages|threads)/([\w-]+)', u.path)
        if m and m.group(1) == 'messages':
            one = [x for x in MAILBOX if x['id'] == m.group(2)]
            return self.answer(200, one[0]) if one else self.answer(404, {'error': {'code': 404, 'message': 'Not Found'}})
        if m:
            ms = [x for x in MAILBOX if x['threadId'] == m.group(2)]
            return self.answer(200, {'id': m.group(2), 'messages': ms}) if ms else \
                self.answer(404, {'error': {'code': 404, 'message': 'Requested entity was not found.', 'status': 'NOT_FOUND'}})
        self.answer(404, {})

    def do_POST(self):
        form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode()).items()}
        if self.path == '/revoke':
            g['revoked'].add(form.get('token'))
            return self.answer(200, {})
        if form.get('grant_type') == 'authorization_code':
            ask = g['codes'].pop(form.get('code'), None)
            ok = ask and ask['redirect_uri'] == form.get('redirect_uri') and ask['code_challenge'] == base64.urlsafe_b64encode(
                hashlib.sha256(form.get('code_verifier', '').encode()).digest()).decode().rstrip('=')
            if not ok:
                return self.answer(400, {'error': 'invalid_grant', 'error_description': 'Bad code or verifier'})
            rt = '1//rt-%d' % g['n']
            g['refresh'][rt] = g['profile']
            return self.answer(200, {'access_token': 'at-%d' % g['n'], 'refresh_token': rt, 'expires_in': 3599})
        if form.get('grant_type') == 'refresh_token':
            if form.get('refresh_token') not in g['refresh'] or form['refresh_token'] in g['revoked']:
                return self.answer(400, {'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'})
            return self.answer(200, {'access_token': 'at-r', 'expires_in': 3599})
        self.answer(400, {'error': 'unsupported_grant_type'})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a):
        return None


server = HTTPServer(('127.0.0.1', 0), Google)
threading.Thread(target=server.serve_forever, daemon=True).start()
KEYS = os.path.join(d, 'keys.json')
os.environ.update(STTARK_KIT_DIR=os.path.join(d, 'kit'), STTARK_KIT_LOG=os.path.join(d, 'log'), STTARK_MAIL_KEYS=KEYS,
                  STTARK_MAIL_GOOGLE='http://127.0.0.1:%d' % server.server_address[1], STTARK_WAIT_DRY='1')
os.makedirs(os.environ['STTARK_KIT_DIR'])
json.dump({}, open(os.path.join(os.environ['STTARK_KIT_DIR'], 'state.json'), 'w'))
MAIL = os.path.join(HOOKS, 'mail.py')


def browse(link):
    """What a browser does with the link: Google's answer, then the page this Mac shows."""
    loc = urllib.request.build_opener(NoRedirect)
    try:
        loc.open(link)
    except urllib.error.HTTPError as e:
        back = e.headers['Location']
    return urllib.request.urlopen(back, timeout=10).read().decode()


# --- the sign-in ----------------------------------------------------------------------------------------------------
p = subprocess.Popen(['/usr/bin/python3', MAIL, 'sign-in', BOX.upper(), '--wait'], stdout=subprocess.PIPE, text=True)
p.stdout.readline()
link = p.stdout.readline().strip()
ask = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(link).query))
check('the link: read only, offline, PKCE S256, the address as its hint, an answer to this Mac',
      ask['scope'] == 'https://www.googleapis.com/auth/gmail.readonly' and ask['access_type'] == 'offline'
      and ask['code_challenge_method'] == 'S256' and ask['login_hint'] == BOX
      and re.fullmatch(r'http://127\.0\.0\.1:\d+/', ask['redirect_uri']) and len(ask['state']) > 16)
g['profile'] = 'other@sample.example'
page = browse(link)
check('a wrong account: says so, keeps nothing, takes the token back',
      'Wrong account' in page and not os.path.exists(KEYS) and '1//rt-1' in g['revoked'])
g['profile'] = BOX
page = browse(link)
out = p.communicate(timeout=20)[0]
keys = json.load(open(KEYS))
check('the same link again, the right account: signed in, the token kept, the mailbox listed',
      'Signed in' in page and 'Signed in: this Mac reads %s now.' % BOX in out and keys.get(BOX) == '1//rt-2'
      and BOX in json.load(open(os.path.join(os.environ['STTARK_KIT_DIR'], 'mail.json')))['mailboxes'])
check('the sign-in is logged', 'mail   %s signed in' % BOX in open(os.environ['STTARK_KIT_LOG']).read())
r = subprocess.run(['/usr/bin/python3', MAIL, 'list'], capture_output=True, text=True)
check('list shows it', r.stdout.startswith(BOX + '  signed in '))

# --- search and read ------------------------------------------------------------------------------------------------
r = subprocess.run(['/usr/bin/python3', MAIL, 'search', BOX, 'from:(supplier.example)', 'S123', '--max', '5'],
                   capture_output=True, text=True)
lines = [json.loads(x) for x in r.stdout.splitlines()]
check('search: the query as given, newest first, a snippet with no HTML entities',
      g['queries'][-1] == 'from:(supplier.example) S123' and [x['id'] for x in lines] == ['m4', 'm3', 'm2', 'm1']
      and lines[0]['snippet'] == 'Re: Shipment S123 booked & more' and lines[0]['at'] == T0 + 300)
r = subprocess.run(['/usr/bin/python3', MAIL, 'read', BOX, 'm4'], capture_output=True, text=True)
m4 = json.loads(r.stdout)
check('read: the text of the HTML when there is no plain part, and the copy line',
      m4['text'] == 'Released today\n\nDana' and m4['cc'] == 'copy@sample.example')
r = subprocess.run(['/usr/bin/python3', MAIL, 'read', BOX, 'm1'], capture_output=True, text=True)
check('read: the plain part', json.loads(r.stdout)['text'] == 'old')
r = subprocess.run(['/usr/bin/python3', MAIL, 'search', 'nobody@sample.example', 'x'], capture_output=True, text=True)
check('a mailbox with no sign-in: says what to run', r.returncode == 1 and 'claude-mail sign-in nobody@sample.example' in r.stderr)

# --- waits that read the mailbox directly ---------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location('wait', os.path.join(HOOKS, 'wait.py'))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
w.me = lambda: ME
base = {'kind': 'email-reply', 'id': 'aaaaaa', 'set_at': T0, 'by': time.time() + 86400, 'why': 'test', 'title': 'Test',
        'mailbox': BOX, 'cse': '', 'transcript': ''}
q = dict(base, target='', query='S123')
happened, what = w.check_email_reply(q)
check('a --query wait: the newest message after the wait, not from the mailbox or the person',
      happened and what.startswith('Dana <dana@supplier.example> wrote to %s: "Re: Shipment S123 booked"' % BOX)
      and q['via'] == 'mail' and q['found']['id'] == 'm4')
check('its search: the query, after the wait, not from the mailbox', g['queries'][-1] == '(S123) after:%d -from:me' % T0)
check('the prompt says how to read it', 'claude-mail read %s m4 prints the message' % BOX in w.prompt_for(q, what, False))
t = dict(base, target='t1')
happened, what = w.check_email_reply(t)
check('a thread wait: the reply in the thread', happened and t['found']['id'] == 'm4' and t['subject'] == 'Shipment S123 booked')
MAILBOX.pop()
happened, what = w.check_email_reply(dict(base, target='t1'))
check('no new mail from others: not yet', not happened and what == 'no new mail yet')
try:
    w.check_email_reply(dict(base, target='nothread'))
    check('a thread the mailbox does not have: a clear reason', False)
except RuntimeError as e:
    check('a thread the mailbox does not have: a clear reason', 'has no thread nothread' in str(e))
now = time.time()
check('read at any hour every 5 minutes, no model', w.due(dict(q, read_at=now - 301), now) and not w.due(dict(q, read_at=now - 200), now))
json.dump({'waits': {'aaaaaa': dict(q, id='aaaaaa')}}, open(os.path.join(os.environ['STTARK_KIT_DIR'], 'state.json'), 'w'))
MAILBOX.append(msg('m5', 't2', 'Clearit <ops@broker.example>', 'IOR active for S123', int(time.time()) - 5, text='done'))
w._direct.clear()
res = w.check()
log = open(os.environ['STTARK_KIT_LOG']).read()
check('the minute check: a found message ends the wait (dry: nothing brought back)',
      res == 'dry' and 'aaaaaa checked %s: YES' % BOX in log and 'IOR active for S123' in log)

# a sign-in Google no longer takes, and none at all
g['revoked'].add('1//rt-2')
try:
    w.check_email_reply(dict(q))
    check('a refused sign-in: says to sign in again', False)
except Exception as e:
    check('a refused sign-in: says to sign in again', 'Sign in again: claude-mail sign-in %s' % BOX in str(e))
w._direct.clear()
other = dict(base, mailbox='shared@sample.example', target='', query='x')
try:
    w.check_email_reply(other)
    check('no sign-in on this Mac: the reason says what to run', False)
except RuntimeError as e:
    check('no sign-in on this Mac: the reason says what to run',
          'cannot read shared@sample.example yet' in str(e) and other['via'] == 'sign-in')
check('a mailbox with no sign-in is tried every 10 minutes, at any hour',
      w.due(dict(other, read_at=now - 601), now) and not w.due(dict(other, read_at=now - 400), now))

# --- the command ----------------------------------------------------------------------------------------------------
g['revoked'].discard('1//rt-2')
json.dump({}, open(os.path.join(os.environ['STTARK_KIT_DIR'], 'state.json'), 'w'))
WAIT = os.path.join(HOOKS, 'wait.py')
r = subprocess.run(['/usr/bin/python3', WAIT, 'email-reply', '--query', 'from:(supplier.example) S123', '--mailbox', BOX,
                    '--by', '+1d', '--why', 'one'], capture_output=True, text=True)
s = json.load(open(os.path.join(os.environ['STTARK_KIT_DIR'], 'state.json')))['waits']
x = list(s.values())[0] if s else {}
check('--query and --mailbox: set, read directly, and said so',
      r.returncode == 0 and x.get('mailbox') == BOX and x.get('query') == 'from:(supplier.example) S123'
      and x.get('target') == '' and x.get('via') == 'mail' and 'reads %s itself every 5 minutes' % BOX in r.stdout
      and 'new mail in %s that matches: from:(supplier.example) S123' % BOX in r.stdout)
r = subprocess.run(['/usr/bin/python3', WAIT, 'email-reply', '--query', 'x', '--mailbox', 'shared@sample.example',
                    '--by', '+1d', '--why', 'two'], capture_output=True, text=True)
check('a mailbox with no sign-in: set, and says how to sign in',
      r.returncode == 0 and 'claude-mail sign-in shared@sample.example' in r.stdout)
r = subprocess.run(['/usr/bin/python3', WAIT, 'email-reply', '--query', 'x', '--mailbox', 'not an address',
                    '--by', '+1d', '--why', 'three'], capture_output=True, text=True)
check('a bad address is refused', r.returncode == 2 and 'not an email address' in r.stderr)
r = subprocess.run(['/usr/bin/python3', MAIL, 'sign-out', BOX], capture_output=True, text=True)
check('sign-out: the token taken back and forgotten', r.returncode == 0 and '1//rt-2' in g['revoked']
      and BOX not in json.load(open(KEYS)) and BOX not in json.load(open(os.path.join(os.environ['STTARK_KIT_DIR'], 'mail.json')))['mailboxes'])
print('%d failed' % fails if fails else 'ok')
sys.exit(1 if fails else 0)
