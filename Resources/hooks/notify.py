#!/usr/bin/python3
"""claude-notify: tell the person something through the way they picked under "Reach me by" in the Sttark
Claude Kit menu. A session uses it when something it waited on happens (a timed check fires, a pull request
merges, a reply comes in), since a new turn in one of many sessions is easy to miss.

    claude-notify "<subject>" "<message>" [--link <url>]
    claude-notify --test       a test message through every way picked
    claude-notify --show       the ways picked and their settings

Each message names the session it comes from and links back to it two ways. "Open on phone" is the session's
claude.ai link: a tap on it in Google Chat, Gmail or Messages on a phone opens the session in the Claude app at
once (a page between would need a second tap: Chrome on a phone asks before a page opens an app). "Open on
computer" is the Kit's page https://sttark.github.io/sttark-claude-kit/open (pages/open.html), which opens the
session in the Claude desktop app, else on claude.ai; email and Google Chat don't make a claude:// link
clickable, so it goes through that page. With no page link, one "Open in Claude" link. The ways, set in the menu and kept in
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
within a few seconds. Logged with lines starting "notify". A message that went at least one way is noted in
reach_sent[<cse>] in the state file: for 30 minutes the Kit sends that session no Needs you reminder, on the phone or
the Mac, since this message already told the person (phone/DESIGN.md section 5). STTARK_KIT_DIR and STTARK_KIT_LOG point it at a
test folder and log; STTARK_NOTIFY_DRY=1 does everything except send (the sealed email is checked instead).

KEPT IN THE KIT APP. A message that must not go out is kept, not dropped: held() is the one place that decides
(Reach me by's Alerts switch is off, or no way is checked; a session's own alerts switch adds its reason there), and
keep_in_kit() is the one path that keeps it: kept.json in the Kit's folder (the last 7 days), which the Kit's window
shows on the message's session and the phone gets for the last 24 hours, and a log line "notify <name> kept <id>:
<why> | <subject>" for the Events page. send() takes that path by itself, for claude-notify and the Kit's own
message (wait.py after a wait, watch.py for a reply it could not bring back), so nothing alerts outside the Kit app: no
mail, Chat, text, Mac notice, and no PushNotification step for the session. claude-notify then exits 0 and prints one line that tells
the session the person reads it in the Kit app, so it does not try another way.
"""
import base64, fcntl, importlib.util, json, os, re, subprocess, sys, time, urllib.request, uuid

HERE = os.path.dirname(os.path.realpath(__file__))
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(KIT, 'state.json')
QUEUE = os.path.join(KIT, 'notify-queue')
KEPT = os.path.join(KIT, 'kept.json')
KEPT_DAYS = 7        # a kept message stays this long in the Kit app
KEPT_MAX = 300       # and at most this many, the newest
IN_KIT = 'kit'       # the "way" send() answers with when it kept the message in the Kit app
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
DRY = bool(os.environ.get('STTARK_NOTIFY_DRY'))
REPO = 'Sttark/sttark-claude-kit'
OPENSSL = '/usr/bin/openssl'  # macOS's own, on every Mac
WAYS = ('email', 'push', 'chat', 'text', 'mac')
NAMES = {'email': 'Email', 'push': 'Claude app', 'chat': 'Google Chat', 'text': 'Text message', 'mac': 'Mac notice'}
APP_WAIT = 10  # seconds to wait for the menu bar app to answer
OPEN_PAGE = 'https://sttark.github.io/sttark-claude-kit/open'


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


def alerts_on(state=None):
    """Reach me by's Alerts switch in Settings: on unless the person turned it off ("alerts": false in "reach").
    Off keeps the ways and their address, number and webhook, so on brings them back as they were."""
    r = (state if state is not None else peek()).get('reach') or {}
    return r.get('alerts') is not False


def held(cse='', ways=None, state=None):
    """Why a message for the session `cse` stays in the Kit app instead of going out, or '' when it goes out. The one
    place that decides, for every message the Kit or a session sends (send() asks it first). `ways`: the ways the
    caller would use (None: the ones checked). Reasons, in the words the window, the phone and the log show:
      'alerts are off'                        Reach me by's Alerts switch is off
      'no way is checked under Reach me by'   on, with nothing checked
    A session's own alerts switch adds its reason here, before the check of the ways."""
    st = state if state is not None else peek()
    if not alerts_on(st):
        return 'alerts are off'
    if not [w for w in (ways if ways is not None else settings(st)['ways']) if w in WAYS]:
        return 'no way is checked under Reach me by'
    return ''


def keep_in_kit(subject, body, link='', title='', url='', cse='', why='alerts are off', source='session', now=None):
    """KEPT IN THE KIT APP: the one path for a message that does not go out (see held()). It goes into kept.json in the
    Kit's folder, under its lock, with the session it belongs to, and the window shows it on that session (the Sessions
    page) and the phone on the session's page; entries older than KEPT_DAYS go. `source`: 'session' (claude-notify) or
    'kit' (the Kit's own message: wait.py, watch.py). Logs "notify <name> kept <id>: <why> | <subject>" for the Events
    page; wait.py reads that line as the session's message. Returns the message's id."""
    now = float(now or time.time())
    kid = uuid.uuid4().hex[:12]
    item = {'id': kid, 'at': round(now, 3), 'cse': cse or '', 'title': title or '', 'subject': subject.strip(),
            'body': body.strip(), 'link': link or '', 'url': url or '', 'from': source, 'why': why}
    os.makedirs(KIT, exist_ok=True)
    with open(KEPT + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            items = json.load(open(KEPT)).get('items') or []
        except (OSError, ValueError, AttributeError):
            items = []
        items = [x for x in items if isinstance(x, dict) and (x.get('at') or 0) > now - KEPT_DAYS * 86400]
        items = (items + [item])[-KEPT_MAX:]
        tmp = KEPT + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'items': items}, f, indent=1)
        os.replace(tmp, KEPT)
    log('%s kept %s: %s | %s' % ((title or '-')[:40], kid, why, subject.strip()[:80]))
    return kid


def kept(cse=None, now=None):
    """The messages kept in the Kit app, oldest first; with `cse`, that session's only."""
    now = now or time.time()
    try:
        items = json.load(open(KEPT)).get('items') or []
    except (OSError, ValueError, AttributeError):
        return []
    return [x for x in items if isinstance(x, dict) and (x.get('at') or 0) > now - KEPT_DAYS * 86400
            and (cse is None or x.get('cse') == cse)]


def kept_line(why):
    """The one line claude-notify prints when it kept the message: the session must not try another way."""
    return ('Kept in the Sttark Claude Kit app, on this session (%s): the person reads it there. It went no other way, '
            'and that is done: do not send it another way.' % why)


def mark_sent(cse, now=None):
    """reach_sent[cse] = now in the state file, under its lock as the hooks and the app write it. Entries over a day
    old go."""
    now = int(now or time.time())
    os.makedirs(KIT, exist_ok=True)
    with open(STATE + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            s = json.load(open(STATE))
        except (OSError, ValueError):
            s = {}
        sent = {k: v for k, v in (s.get('reach_sent') or {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > now - 86400}
        sent[cse] = now
        s['reach_sent'] = sent
        tmp = STATE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, STATE)


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
    """(name, link, cse id) of the session this runs in, from the state file or the server; ('', '', '')
    outside one."""
    cse = cse_id()
    if not cse:
        return '', '', ''
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
    return title, url or 'https://claude.ai/code/' + cse, cse


def open_link(cse, url):
    """The "Open in Claude" link: the Kit's page, with the session's ids after the # (never sent to the
    server): the Remote Control id for the desktop app (claude://code/<id>), then the id in its claude.ai link
    for the browser and phones. Without a Remote Control id, the claude.ai link as it is."""
    m = re.fullmatch(r'https://claude\.ai/code/([A-Za-z0-9_]+)/?', url or '')
    web = m.group(1) if m else ''
    if not cse and web.startswith(('cse_', 'session_')):
        cse = web
    if not re.fullmatch(r'(cse|session)_[A-Za-z0-9]+', cse or ''):
        return url or ''
    return OPEN_PAGE + '#' + cse + ('/' + web if web and web != cse else '')


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


def session_links(m):
    """[(words, link)] back to the session: the claude.ai link for a phone and the Kit's page for a computer,
    or one link when there is no page link."""
    page, web = m.get('url') or '', m.get('web') or ''
    if page and web and page != web:
        return [('Open on phone', web), ('Open on computer', page)]
    return [('Open in Claude', page or web)] if (page or web) else []


def html_of(m):
    esc = lambda s: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    parts = ['<p>%s</p>' % esc(p).replace('\n', '<br>') for p in m['body'].split('\n\n') if p.strip()]
    if m.get('link'):
        parts.append('<p><a href="%s">%s</a></p>' % (esc(m['link']), esc(m['link'])))
    links = session_links(m)
    if links:
        btn = ('<a href="%s" style="display:inline-block;margin:0 8px 8px 0;padding:10px 16px;border-radius:6px;'
               'font-weight:600;text-decoration:none;%s">%s</a>')
        parts.append('<p>%s</p><p style="color:#5b6570">From the session %s</p>' % (''.join(
            btn % (esc(u), 'background:#00892f;color:#ffffff;border:1px solid #00892f' if i == 0
                   else 'color:#000000;border:1px solid #000000', esc(w)) for i, (w, u) in enumerate(links)),
            esc(m['title'] or 'Claude Code')))
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
    links = session_links(m)
    if links:
        t += '\n%s · from %s' % (' · '.join('<%s|%s>' % (u, w) for w, u in links), m['title'] or 'the session')
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
    links = session_links(m)
    if links:
        t += '\n\nFrom the session %s.' % (m['title'] or 'Claude Code')
        t += ''.join('\n%s: %s' % (w, u) for w, u in links)
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


def send(subject, body, link='', ways=None, title=None, url=None, cse='', source='session'):
    """`url` is the session's claude.ai link and `cse` its Remote Control id. In the message, 'url' is the
    open_link page link (for a computer), 'web' the claude.ai link (for a phone), and 'cse' the id the Mac
    notice opens directly.
    When held() gives a reason, nothing goes out: keep_in_kit() keeps it, and the answer is one
    [(IN_KIT, (True, <why>))]. `source` names the sender for keep_in_kit(): 'session' (claude-notify) or 'kit' (the
    Kit's own message: wait.py after a wait, watch.py for a reply it could not bring back)."""
    r = settings()
    ways = [w for w in (ways or r['ways']) if w in WAYS]
    if title is None:
        title, url, cse = session()
    why = held(cse, ways)
    if why:
        keep_in_kit(subject, body, link, title or '', url or '', cse or '', why, source)
        return [(IN_KIT, (True, why))]
    m = {'subject': subject.strip(), 'body': body.strip(), 'link': link, 'title': title or '',
         'url': open_link(cse, url), 'web': url or '', 'cse': cse or ''}
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
    if cse and any(results[w][0] for w in ways):
        try:
            mark_sent(cse)
        except OSError as e:
            log('%s reach_sent not noted: %s' % ((title or '-')[:40], e))
    return [(w, results[w]) for w in ways]


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__.split('\n\n')[1])
        return 0
    if args[0] == '--show':
        r = settings()
        print('Alerts: ' + ('on' if alerts_on() else 'off (each message is kept in the Kit app, on its session)'))
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
        if not alerts_on():
            print('Alerts are off under Reach me by in Sttark Claude Kit, so no test was sent.')
            return 0
        if held(''):
            print('Nothing is picked under Reach me by in the Sttark Claude Kit menu, so nothing was sent.')
            return 1
        out = send('Test from Sttark Claude Kit',
                   'This is a test of Reach me by. When something a Claude session waited on happens, '
                   'it comes this way.', link, title=None if os.environ.get('CLAUDE_PID') else '',
                   url=None if os.environ.get('CLAUDE_PID') else '')
    else:
        if len(args) < 2 or not args[0].strip() or not args[1].strip():
            print('Usage: claude-notify "<subject>" "<message>" [--link <url>]', file=sys.stderr)
            return 2
        out = send(args[0], args[1], link)
    if out and out[0][0] == IN_KIT:
        print(kept_line(out[0][1][1]))
        return 0
    bad = 0
    for w, (ok, words) in out:
        print('%s: %s%s' % (NAMES[w], '' if ok else 'NOT SENT: ', words))
        bad += not ok
    return 1 if bad == len(out) else 0


if __name__ == '__main__':
    sys.exit(main())
