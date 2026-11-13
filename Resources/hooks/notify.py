#!/usr/bin/python3
"""claude-notify: tell the person something through the way they picked under "Reach me by" in the Sttark
Claude Kit menu. A session uses it when something it waited on happens (a timed check fires, a pull request
merges, a reply comes in), since a new turn in one of many sessions is easy to miss.

    claude-notify "<subject>" "<message>" [--link <url>]
    claude-notify --test       a test message through every way picked
    claude-notify --show       the ways picked and their settings

Each message names the session it comes from and links back to it. The ways, set in the menu and kept in
"reach" in the shared state file:

  email  Mail from alerts@sttark.com to the person's @sttark.com address, sent by the notify workflow in
         Sttark/sttark-claude-kit (`gh workflow run`), which holds the mail key. The message is sealed with
         notify-key.pem, so none of it shows in that public repo. Arrives in about a minute.
  push   A push from the Claude app. Only the session can send it (its PushNotification tool), so this
         prints the step for the session to take.
  chat   A Google Chat message, posted to the webhook of a space the person made for it.
  text   A text from Messages on this Mac to the phone number set; the menu bar app sends it.
  mac    A notice on this Mac; the menu bar app shows it, and a click opens the session.

The app's part (text, mac) goes through notify-queue/ in the Application Support folder: the app answers
within a few seconds. Logged with lines starting "notify". STTARK_KIT_DIR and STTARK_KIT_LOG point it at a
test folder and log; STTARK_NOTIFY_DRY=1 does everything except send (the sealed email is checked instead).
"""
import base64, fcntl, importlib.util, json, os, re, subprocess, sys, time, urllib.request, uuid

HERE = os.path.dirname(os.path.realpath(__file__))
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(KIT, 'state.json')
QUEUE = os.path.join(KIT, 'notify-queue')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
DRY = bool(os.environ.get('STTARK_NOTIFY_DRY'))
REPO = 'Sttark/sttark-claude-kit'
OPENSSL = '/usr/bin/openssl'  # macOS's own, on every Mac
WAYS = ('email', 'push', 'chat', 'text', 'mac')
NAMES = {'email': 'Email', 'push': 'Claude app', 'chat': 'Google Chat', 'text': 'Text message', 'mac': 'Mac notice'}
APP_WAIT = 10  # seconds to wait for the menu bar app to answer


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'notify ' + line + '\n')
    except OSError:
        pass


def peek():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {}


def login_email():
    """The address of the Claude Code login: the default for Email until the person sets one."""
    try:
        return json.load(open(os.path.expanduser('~/.claude.json'))).get('oauthAccount', {}).get('emailAddress') or ''
    except (OSError, ValueError):
        return ''


def settings(state=None):
    """The person's choice: {'ways': [...], 'email': ..., 'phone': ..., 'chat': ...}. With nothing chosen yet,
    Email to the Claude login's address when it is a Sttark one, else a notice on this Mac."""
    r = dict((state if state is not None else peek()).get('reach') or {})
    r['email'] = r.get('email') or login_email()
    if not isinstance(r.get('ways'), list):
        r['ways'] = ['email'] if r['email'].lower().endswith('@sttark.com') else ['mac']
    return r


# --- the session -------------------------------------------------------------------------------------------

def cse_id():
    """This session's claude.ai id (cse_...), as the effort hook finds it."""
    b = os.environ.get('CLAUDE_CODE_BRIDGE_SESSION_ID', '')
    if b:
        return 'cse_' + b.split('_', 1)[1] if b.startswith('session_') else b
    # the Claude Code process a `claude rc` server starts with --session-id; the command runs under its shell
    pid = os.environ.get('CLAUDE_PID') or str(os.getppid())
    for _ in range(6):
        if not pid or pid in ('0', '1'):
            break
        out = subprocess.run(['ps', '-ww', '-o', 'ppid=,args=', '-p', pid], capture_output=True, text=True).stdout
        m = re.search(r'--session-id[= ](cse_\w+)', out)
        if m:
            return m.group(1)
        pid = out.split()[0] if out.split() else ''
    sid = os.environ.get('CLAUDE_CODE_SESSION_ID', '')
    for cse, x in (peek().get('sessions') or {}).items():
        if sid and os.path.basename(x.get('transcript') or '').startswith(sid):
            return cse
    return ''


def session():
    """(name, link) of the session this runs in, from the state file or the server; ('', '') outside one."""
    cse = cse_id()
    if not cse:
        return '', ''
    x = (peek().get('sessions') or {}).get(cse) or {}
    title, url = x.get('title') or '', x.get('url') or ''
    if not (title and url):
        try:
            spec = importlib.util.spec_from_file_location('sse', os.path.join(HERE, 'set-session-effort.py'))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            d = m.session(cse)
            title, url = title or d.get('title') or '', url or d.get('session_url') or ''
        except Exception:
            pass
    return title, url or 'https://claude.ai/code/' + cse


# --- the ways ----------------------------------------------------------------------------------------------

def seal(obj):
    """The message for the notify workflow, sealed with its public key: an AES key and IV sealed with RSA-OAEP,
    then the message in AES-256-CBC, both in base64, joined by a dot."""
    key, iv = os.urandom(32), os.urandom(16)
    sealed = subprocess.run([OPENSSL, 'rsautl', '-encrypt', '-oaep', '-pubin', '-inkey',
                             os.path.join(HERE, 'notify-key.pem')], input=key + iv, capture_output=True, check=True).stdout
    body = subprocess.run([OPENSSL, 'enc', '-aes-256-cbc', '-K', key.hex(), '-iv', iv.hex()],
                          input=json.dumps(obj).encode(), capture_output=True, check=True).stdout
    return base64.b64encode(sealed).decode() + '.' + base64.b64encode(body).decode()


def gh():
    for p in ('/opt/homebrew/bin/gh', '/usr/local/bin/gh', os.path.expanduser('~/.local/bin/gh')):
        if os.access(p, os.X_OK):
            return p
    return 'gh'


def html_of(m):
    esc = lambda s: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    parts = ['<p>%s</p>' % esc(p).replace('\n', '<br>') for p in m['body'].split('\n\n') if p.strip()]
    if m.get('link'):
        parts.append('<p><a href="%s">%s</a></p>' % (esc(m['link']), esc(m['link'])))
    if m.get('url'):
        parts.append('<p style="color:#5b6570">From the session <a href="%s">%s</a></p>'
                     % (esc(m['url']), esc(m['title'] or 'Claude Code')))
    return '<div style="font-family:Helvetica Neue,Arial,sans-serif;font-size:16px;line-height:1.5">%s</div>' % ''.join(parts)


def email(m, r):
    to = (r.get('email') or '').strip()
    if not to.lower().endswith('@sttark.com'):
        return False, 'needs a @sttark.com address: set it under Reach me by in the menu'
    subject = (m['title'] + ': ' if m['title'] else '') + m['subject']
    p = seal({'to': to, 'subject': subject, 'text': text_of(m), 'html': html_of(m)})
    if DRY:
        return True, 'would mail %s (sealed, %d characters)' % (to, len(p))
    out = subprocess.run([gh(), 'workflow', 'run', 'notify.yml', '-R', REPO, '-f', 'p=' + p],
                         capture_output=True, text=True, timeout=60)
    if out.returncode:
        return False, 'gh could not start the mail: ' + (out.stderr or out.stdout).strip()[:200]
    return True, 'sent to %s; it arrives in about a minute' % to


def push(m, r):
    line = (m['title'] + ': ' if m['title'] else '') + m['subject']
    return True, ('THE SESSION SENDS THIS ONE: call the PushNotification tool now (load it first with ToolSearch '
                  '"select:PushNotification" when it is not loaded) with message: ' + json.dumps(line[:190]))


def chat(m, r):
    hook = (r.get('chat') or '').strip()
    if not hook.startswith('https://chat.googleapis.com/'):
        return False, 'needs a Google Chat webhook: set it under Reach me by in the menu'
    t = '*%s*\n%s' % (m['subject'], m['body'])
    if m.get('link'):
        t += '\n<%s|Open the result>' % m['link']
    if m.get('url'):
        t += '\nFrom <%s|%s>' % (m['url'], m['title'] or 'the session')
    if DRY:
        return True, 'would post %d characters to the webhook' % len(t)
    req = urllib.request.Request(hook, data=json.dumps({'text': t}).encode(),
                                 headers={'Content-Type': 'application/json; charset=UTF-8'})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        return False, 'the webhook did not take it: %s' % str(e)[:160]
    return True, 'posted'


def text_of(m):
    t = m['subject'] + '\n\n' + m['body']
    if m.get('link'):
        t += '\n\n' + m['link']
    if m.get('url'):
        t += '\n\nFrom the session %s: %s' % (m['title'] or 'Claude Code', m['url'])
    return t


def by_app(ways, m, r):
    """Text and Mac notice: the menu bar app sends them (it holds macOS's permissions for notices and for
    Messages). Returns {way: (ok, words)}."""
    if DRY:
        return {w: (True, 'would ask the menu bar app') for w in ways}
    os.makedirs(QUEUE, exist_ok=True)
    nid = uuid.uuid4().hex[:12]
    job = dict(m, ways=ways, phone=r.get('phone') or '', text=text_of(m))
    tmp = os.path.join(QUEUE, nid + '.tmp')
    with open(tmp, 'w') as f:
        json.dump(job, f)
    os.replace(tmp, os.path.join(QUEUE, nid + '.json'))
    done = os.path.join(QUEUE, nid + '.done')
    for _ in range(APP_WAIT * 4):
        if os.path.exists(done):
            try:
                ans = json.load(open(done))
            finally:
                os.remove(done)
            return {w: (bool(ans.get(w, {}).get('ok')), ans.get(w, {}).get('words', '')) for w in ways}
        time.sleep(0.25)
    try:
        os.remove(os.path.join(QUEUE, nid + '.json'))
    except OSError:
        pass
    res = {w: (False, 'the Sttark Claude Kit app is not running') for w in ways}
    if 'mac' in ways:  # a plain notice still shows without the app
        subprocess.run(['osascript', '-e', 'display notification %s with title %s'
                        % (json.dumps(m['body'][:200]), json.dumps(m['subject'][:80]))], capture_output=True)
        res['mac'] = (True, 'shown without the app')
    return res


def send(subject, body, link='', ways=None, title=None, url=None):
    r = settings()
    ways = [w for w in (ways or r['ways']) if w in WAYS]
    if title is None:
        title, url = session()
    m = {'subject': subject.strip(), 'body': body.strip(), 'link': link, 'title': title or '', 'url': url or ''}
    results = {}
    for w in ways:
        if w in ('text', 'mac'):
            continue
        try:
            results[w] = globals()[w](m, r)
        except Exception as e:
            results[w] = (False, '%s: %s' % (type(e).__name__, str(e)[:160]))
    app = [w for w in ways if w in ('text', 'mac')]
    if app:
        results.update(by_app(app, m, r))
    for w in ways:
        ok, words = results[w]
        log('%s %s %s: %s | %s' % ((title or '-')[:40], w, 'ok' if ok else 'failed', words[:120], subject[:80]))
    return [(w, results[w]) for w in ways]


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__.split('\n\n')[1])
        return 0
    if args[0] == '--show':
        r = settings()
        print('Reach me by: ' + (', '.join(NAMES[w] for w in r['ways'] if w in NAMES) or 'nothing picked'))
        print('Email: %s\nText message: %s\nGoogle Chat: %s' % (r.get('email') or '(not set)', r.get('phone') or '(not set)',
                                                                'set' if r.get('chat') else '(not set)'))
        return 0
    link = ''
    if '--link' in args:
        i = args.index('--link')
        link = args[i + 1] if i + 1 < len(args) else ''
        del args[i:i + 2]
    if args[0] == '--test':
        out = send('Test from Sttark Claude Kit',
                   'This is a test of Reach me by. When something a Claude session waited on happens, '
                   'it comes this way.', link, title=None if os.environ.get('CLAUDE_PID') else '',
                   url=None if os.environ.get('CLAUDE_PID') else '')
    else:
        if len(args) < 2 or not args[0].strip() or not args[1].strip():
            print('Usage: claude-notify "<subject>" "<message>" [--link <url>]', file=sys.stderr)
            return 2
        out = send(args[0], args[1], link)
    if not out:
        print('Nothing is picked under Reach me by in the Sttark Claude Kit menu, so nothing was sent.')
        return 1
    bad = 0
    for w, (ok, words) in out:
        print('%s: %s%s' % (NAMES[w], '' if ok else 'NOT SENT: ', words))
        bad += not ok
    return 1 if bad == len(out) else 0


if __name__ == '__main__':
    sys.exit(main())
