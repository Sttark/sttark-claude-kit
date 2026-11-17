#!/usr/bin/python3
"""claude-mail: Sttark Claude Kit reads a Gmail mailbox directly, with the Gmail API and no model call: your own, or
a shared one that you can sign in to, such as a team address. claude-wait email-reply checks with it.

    claude-mail sign-in <address> [--wait]
                         once per mailbox on each Mac: prints a Google link to open on this Mac. Select <address>
                         there and click Allow; the Kit then reads it. The link works for 30 minutes. --wait
                         waits for the answer and says how it went.
    claude-mail list     the mailboxes this Mac can read
    claude-mail search <address> "<Gmail search>" [--max <n>]
                         the matching messages, newest first, one JSON object a line: id, thread_id, from, to,
                         subject, date, at (Unix time), snippet
    claude-mail read <address> <message id>
                         one message as JSON: id, thread_id, from, to, cc, subject, date, at, text
    claude-mail sign-out <address>
                         forget the mailbox on this Mac

Read only: the sign-in asks Google for gmail.readonly, through the Kit's own OAuth client (a Desktop app client in
Sttark's Google Cloud project sttark-claude-kit, whose audience is Internal, so only accounts of the organization can
sign in to it). Its refresh token goes in the login Keychain, as the generic password "Sttark Claude Kit mail" with
the mailbox's address as its account; mail.json in the Kit's folder lists the mailboxes, with no secret in it. The
link sends Google's answer to http://127.0.0.1:<port>/ on this Mac, where a background copy of this command waits
for 30 minutes.
Logged with lines starting "mail". STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and log;
STTARK_MAIL_KEYS (a JSON file) stands in for the Keychain, and STTARK_MAIL_GOOGLE (an http://127.0.0.1:<port>
address) for Google's sign-in, token and Gmail addresses.
"""
import base64, hashlib, html, json, os, re, secrets, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
INDEX = os.path.join(KIT, 'mail.json')
KEYS = os.environ.get('STTARK_MAIL_KEYS')
GOOGLE = (os.environ.get('STTARK_MAIL_GOOGLE') or '').rstrip('/')
AUTH_URL = (GOOGLE or 'https://accounts.google.com') + '/o/oauth2/v2/auth'
TOKEN_URL = (GOOGLE or 'https://oauth2.googleapis.com') + '/token'
REVOKE_URL = (GOOGLE or 'https://oauth2.googleapis.com') + '/revoke'
API = (GOOGLE or 'https://gmail.googleapis.com') + '/gmail/v1/users/me'
SERVICE = 'Sttark Claude Kit mail'
SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
HERE = os.path.dirname(os.path.realpath(__file__))
# A Desktop app client is a public client (RFC 8252): its id and its secret go out in the app.
CLIENT_ID = '373613882673-mkbri5u9bsqg9pt2rcojohjepcq6dmvk.apps.googleusercontent.com'
LISTEN = 1800   # seconds the sign-in link works
ADDRESS = re.compile(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$')


def client():
    """The OAuth client's id and secret, as Google wants them in each token request. The secret stays out of this
    public repo's files: the release build writes mail-client.py beside this file from the repo secret
    GOOGLE_MAIL_CLIENT_SECRET, so a build made without it can't sign in or read mail."""
    form = {'client_id': CLIENT_ID}
    try:
        with open(os.path.join(HERE, 'mail-client.py')) as f:
            form['client_secret'] = re.search(r"SECRET = '([\w-]+)'", f.read()).group(1)
    except (OSError, AttributeError):
        if not GOOGLE:
            raise RuntimeError('this copy of the Kit has no mail client secret (mail-client.py); a release has it')
    return form


class SignIn(Exception):
    """This Mac has no working sign-in for the mailbox; the words say what to run."""


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'mail   ' + line + '\n')
    except OSError:
        pass


def address(text):
    a = (text or '').strip().lower()
    if not ADDRESS.match(a):
        raise ValueError('not an email address: %s' % (text or '(none)'))
    return a


# --- the refresh tokens: the Keychain, and mail.json beside it --------------------------------------------------

def _keys():
    try:
        return json.load(open(KEYS))
    except (OSError, ValueError):
        return {}


def token(box):
    """The mailbox's refresh token, or ''."""
    if KEYS:
        return _keys().get(box, '')
    try:
        r = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', SERVICE, '-a', box, '-w'],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ''
    return r.stdout.strip() if r.returncode == 0 else ''


def save_token(box, value):
    if not re.fullmatch(r'[\w./-]+', value or ''):
        raise RuntimeError('Google gave a refresh token the Kit does not know how to keep')
    if KEYS:
        k = _keys()
        k[box] = value
        with open(KEYS, 'w') as f:
            json.dump(k, f)
    else:
        # through standard input (security -i), so the token is never on a command line that ps shows
        cmd = 'add-generic-password -U -s "%s" -a "%s" -l "%s" -w "%s"\n' % (SERVICE, box, SERVICE, value)
        subprocess.run(['/usr/bin/security', '-i'], input=cmd, capture_output=True, text=True, timeout=10)
        if token(box) != value:
            raise RuntimeError('the Keychain did not keep the sign-in')
    index(box, {'at': int(time.time())})


def drop_token(box):
    if KEYS:
        k = _keys()
        k.pop(box, None)
        with open(KEYS, 'w') as f:
            json.dump(k, f)
    else:
        subprocess.run(['/usr/bin/security', 'delete-generic-password', '-s', SERVICE, '-a', box],
                       capture_output=True, text=True, timeout=10)
    index(box, None)


def boxes():
    try:
        return json.load(open(INDEX)).get('mailboxes') or {}
    except (OSError, ValueError):
        return {}


def index(box, entry):
    os.makedirs(KIT, exist_ok=True)
    all_ = boxes()
    if entry is None:
        all_.pop(box, None)
    else:
        all_[box] = entry
    tmp = INDEX + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'mailboxes': all_}, f, indent=1)
    os.replace(tmp, INDEX)


def can_read(box):
    """Whether this Mac has a sign-in for the mailbox (it may still have been taken back at Google)."""
    return bool(box) and bool(token(box))


# --- Google -------------------------------------------------------------------------------------------------------

def call(url, form=None, bearer=None, timeout=30):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode() if form is not None else None)
    if bearer:
        req.add_header('Authorization', 'Bearer ' + bearer)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or '{}')
        except ValueError:
            body = {}
        err = body.get('error')
        why = (err.get('message') if isinstance(err, dict) else
               ' '.join(x for x in (err, body.get('error_description')) if x)) or e.reason
        raise GoogleError(e.code, err.get('status') if isinstance(err, dict) else err, str(why))


class GoogleError(RuntimeError):
    def __init__(self, code, kind, why):
        RuntimeError.__init__(self, 'Google answered %s: %s' % (code, why))
        self.code, self.kind = code, kind or ''


_access = {}


def access(box):
    """An access token for the mailbox, from its refresh token; SignIn when there is none or Google refuses it."""
    if box in _access and _access[box][1] > time.time() + 60:
        return _access[box][0]
    rt = token(box)
    if not rt:
        raise SignIn('this Mac cannot read %s yet. Sign in once: claude-mail sign-in %s' % (box, box))
    try:
        d = call(TOKEN_URL, dict(client(), refresh_token=rt, grant_type='refresh_token'))
    except GoogleError as e:
        if e.kind in ('invalid_grant', 'unauthorized_client'):
            raise SignIn('Google no longer accepts the sign-in for %s (its password changed, or the access was '
                         'taken back). Sign in again: claude-mail sign-in %s' % (box, box))
        raise
    _access[box] = (d['access_token'], time.time() + int(d.get('expires_in') or 3600))
    return d['access_token']


def brief(m):
    h = {x.get('name', '').lower(): x.get('value', '') for x in (m.get('payload') or {}).get('headers') or []}
    return {'id': m.get('id', ''), 'thread_id': m.get('threadId', ''), 'from': h.get('from', ''), 'to': h.get('to', ''),
            'subject': h.get('subject', ''), 'date': h.get('date', ''), 'at': int(m.get('internalDate') or 0) // 1000,
            'snippet': html.unescape(m.get('snippet') or '')}


HEADERS = '&'.join('metadataHeaders=' + n for n in ('From', 'To', 'Subject', 'Date'))


def search(box, q, n=20, pages=1):
    """The messages that match a Gmail search, newest first, each as brief() says: n a page, up to `pages` pages."""
    t = access(box)
    out, token = [], None
    for _ in range(max(1, pages)):
        ask = {'q': q, 'maxResults': max(1, min(n, 100))}
        if token:
            ask['pageToken'] = token
        found = call(API + '/messages?' + urllib.parse.urlencode(ask), bearer=t)
        out += [brief(call(API + '/messages/%s?format=metadata&%s' % (urllib.parse.quote(m['id']), HEADERS), bearer=t))
                for m in found.get('messages') or []]
        token = found.get('nextPageToken')
        if not token:
            break
    return out


def thread(box, tid):
    """The messages of one thread of the mailbox, oldest first."""
    t = access(box)
    d = call(API + '/threads/%s?format=metadata&%s' % (urllib.parse.quote(tid), HEADERS), bearer=t)
    return [brief(m) for m in d.get('messages') or []]


def read(box, mid):
    """One message, with its plain text (from its HTML when it has no plain part)."""
    m = call(API + '/messages/%s?format=full' % urllib.parse.quote(mid), bearer=access(box))
    out = brief(m)
    out['cc'] = next((x.get('value', '') for x in (m.get('payload') or {}).get('headers') or []
                      if x.get('name', '').lower() == 'cc'), '')
    plain, rich = [], []

    def walk(p):
        data = (p.get('body') or {}).get('data')
        if data and not p.get('filename'):
            text = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode('utf-8', 'replace')
            (plain if p.get('mimeType') == 'text/plain' else rich if p.get('mimeType') == 'text/html' else []).append(text)
        for q in p.get('parts') or []:
            walk(q)
    walk(m.get('payload') or {})
    if plain:
        out['text'] = '\n'.join(plain)
    else:
        t = re.sub(r'(?is)<(script|style)\b.*?</\1>', '', '\n'.join(rich))
        t = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h\d)>', '\n', t)
        out['text'] = html.unescape(re.sub(r'<[^>]+>', '', t))
    out['text'] = re.sub(r'\n{3,}', '\n\n', out['text']).strip()
    return out


# --- the sign-in --------------------------------------------------------------------------------------------------

def b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


PAGE = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<title>Sttark Claude Kit</title><body style="font:16px -apple-system,Helvetica,sans-serif;margin:48px auto;'
        'max-width:560px;padding:0 16px;color:#111;background:#fff"><h1 style="font-size:20px">%s</h1><p>%s</p>')


def listen(box, verifier, state, life=LISTEN):
    """The background copy: waits on 127.0.0.1 for Google's answer to the link, then keeps the sign-in."""
    done = []

    class Answer(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def page(self, title, words):
            body = (PAGE % (html.escape(title), html.escape(words))).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get('state', [''])[0] != state:
                self.send_response(404)
                self.end_headers()
                return
            if 'error' in q or 'code' not in q:
                why = q.get('error', ['no answer'])[0]
                self.page('Not signed in', 'Google said: %s. Nothing was kept. To try again, run claude-mail sign-in '
                                           '%s and open the new link.' % (why, box))
                log('%s sign-in stopped: Google said %s' % (box, why))
                done.append(False)
                return
            try:
                t = call(TOKEN_URL, dict(client(), code=q['code'][0], redirect_uri=redirect,
                                         grant_type='authorization_code', code_verifier=verifier))
                who = (call(API + '/profile', bearer=t['access_token']).get('emailAddress') or '').lower()
                if who != box:
                    try:
                        call(REVOKE_URL, {'token': t.get('refresh_token') or t['access_token']})
                    except Exception:
                        pass
                    self.page('Wrong account', 'You selected %s, not %s, so nothing was kept. Open the same link '
                                               'again and select %s.' % (who or 'another account', box, box))
                    log('%s sign-in: %s was selected instead; nothing kept' % (box, who or 'another account'))
                    return
                if not t.get('refresh_token'):
                    raise RuntimeError('Google gave no refresh token')
                save_token(box, t['refresh_token'])
            except Exception as e:
                self.page('Not signed in', 'The Kit could not finish: %s. Run claude-mail sign-in %s again.'
                          % (str(e)[:200], box))
                log('%s sign-in failed: %s' % (box, str(e)[:200]))
                done.append(False)
                return
            self.page('Signed in', 'Sttark Claude Kit on this Mac can now read %s. You can close this tab.' % box)
            log('%s signed in: this Mac reads it now (read only)' % box)
            done.append(True)

    server = HTTPServer(('127.0.0.1', 0), Answer)
    redirect = 'http://127.0.0.1:%d/' % server.server_address[1]
    print(server.server_address[1], flush=True)
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    server.timeout = 5
    end = time.time() + life
    while not done and time.time() < end:
        server.handle_request()
    server.server_close()
    if not done:
        log('%s sign-in link ended after %d minutes with no answer' % (box, life // 60))


def sign_in(box, wait=False):
    verifier = b64(secrets.token_bytes(48))
    state = b64(secrets.token_bytes(16))
    started = int(time.time())   # mail.json keeps whole seconds
    p = subprocess.Popen([sys.executable, os.path.realpath(__file__), '--listen', box], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True, text=True)
    p.stdin.write(json.dumps({'verifier': verifier, 'state': state}) + '\n')
    p.stdin.close()
    port = p.stdout.readline().strip()
    p.stdout.close()
    if not port.isdigit():
        print('The Kit could not start the sign-in on this Mac.', file=sys.stderr)
        return 1
    link = AUTH_URL + '?' + urllib.parse.urlencode({
        'client_id': CLIENT_ID, 'redirect_uri': 'http://127.0.0.1:%s/' % port, 'response_type': 'code',
        'scope': SCOPE, 'access_type': 'offline', 'prompt': 'consent', 'login_hint': box, 'state': state,
        'code_challenge': b64(hashlib.sha256(verifier.encode()).digest()), 'code_challenge_method': 'S256'})
    log('%s sign-in link made; it works for %d minutes' % (box, LISTEN // 60))
    print('Open this link in a browser on this Mac, select %s and click Allow. The Kit then reads that mailbox, '
          'read only. The link works for %d minutes.\n%s' % (box, LISTEN // 60, link), flush=True)
    if not wait:
        return 0
    while p.poll() is None:
        time.sleep(1)
    if (boxes().get(box) or {}).get('at', 0) >= started:
        print('Signed in: this Mac reads %s now.' % box)
        return 0
    print('Not signed in. The log says why: grep "mail   %s" %s' % (box, LOG))
    return 1


# --- the command --------------------------------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help', 'help'):
        print(__doc__.split('\n\n')[1])
        return 0
    cmd = args[0]
    try:
        if cmd == '--listen' and len(args) == 2:
            secret = json.loads(sys.stdin.readline())
            listen(address(args[1]), secret['verifier'], secret['state'])
            return 0
        if cmd == 'list':
            all_ = boxes()
            for box in sorted(all_):
                print('%s  signed in %s%s' % (box, time.strftime('%Y-%m-%d %H:%M', time.localtime(all_[box].get('at', 0))),
                                             '' if can_read(box) else '  (no sign-in in the Keychain)'))
            if not all_:
                print('No mailboxes. Sign in to one: claude-mail sign-in <address>')
            return 0
        if cmd == 'sign-in' and len(args) >= 2:
            return sign_in(address(args[1]), '--wait' in args)
        if cmd == 'sign-out' and len(args) == 2:
            box = address(args[1])
            rt = token(box)
            if rt:
                try:
                    call(REVOKE_URL, {'token': rt})
                except Exception:
                    pass
            drop_token(box)
            log('%s signed out on this Mac' % box)
            print('This Mac no longer reads %s.' % box)
            return 0
        if cmd == 'search' and len(args) >= 3:
            n = 20
            if '--max' in args:
                i = args.index('--max')
                n = int(args[i + 1])
                del args[i:i + 2]
            for m in search(address(args[1]), ' '.join(args[2:]), n):
                print(json.dumps(m, ensure_ascii=False))
            return 0
        if cmd == 'read' and len(args) == 3:
            print(json.dumps(read(address(args[1]), args[2]), ensure_ascii=False, indent=1))
            return 0
    except (SignIn, ValueError, RuntimeError, OSError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print('Usage: claude-mail sign-in <address> | list | search <address> "<Gmail search>" | read <address> <id> | '
          'sign-out <address>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
