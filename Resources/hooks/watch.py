#!/usr/bin/python3
"""The Kit's reply watch: when a session contacted someone (an email or a draft, a web form, a supplier's messenger,
an Asana comment or task, a Google Chat post), an answer on any of those channels brings the session back, also
when the session set no wait for it. wait.py --check runs it every minute; there is nothing to start.

What it watches comes from facts in the session's own records (its transcript and its agents'), with no model: the
addresses and domains it emailed or drafted to, the Gmail threads it drafted or read in, the domains of web forms
it sent through claude-window, the platform of a supplier messenger it sent on, the Asana tasks it commented on or
made, the Chat spaces it posted in, and what its email reply waits name. A session is watched while it has an open
wait, and for WATCH_DAYS after its last turn; a contact older than KEY_DAYS is not watched.

How it reads, for every session at once, in as few reads as it can: a mailbox this Mac signed in to (claude-mail)
with one Gmail search every 5 minutes, at any hour, with no model; the person's own mailbox with no sign-in, and
the Chat spaces, with one Haiku run through Workrouter every 15 minutes from 7 AM to 9 PM (one gmail_search, and
one gchat_search_messages per space). An Asana comment comes as Asana's own notice mail, with the task's id in it.

A new message counts for a session when it is from an address or a domain the session wrote to, in a thread it
used, an Asana notice for its task, or a post in its space; newer than that contact and than the session's watch
(for a session with an open wait, its oldest open wait: so the first read after an update looks back to then); not
from the person; not one the session has already read (its id is in the session's records) or been told about. One
message goes to one session: the closest match (a task or a thread before an address, an address before a domain),
then the newest contact. A domain match from an automatic sender (no-reply and the like) does not count. The
session comes back the way a wait brings it back, with the messages and one question: does this need action?

    watch.py --list      what the Kit watches now, for each session (claude-wait --watching runs this)

Logged with lines starting "watch". STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and log;
STTARK_WAIT_DRY=1 reads and decides, prints what it would bring back, and brings nothing back.
"""
import calendar, email.utils, glob, html, importlib.util, json, mmap, os, re, shlex, sys, time, urllib.parse

HERE = os.path.dirname(os.path.realpath(__file__))
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
DRY = bool(os.environ.get('STTARK_WAIT_DRY'))
FILE = os.path.join(KIT, 'watch.json')
# A reply comes within a work week: in the waits sessions set, a company's support desk took 5 days, a supplier in
# China answers overnight plus a day, a person who travels takes a week. 7 days after the last turn covers a full work week and
# its weekend; a session quiet for longer is more likely to wake for mail about something else.
WATCH_DAYS = 7
KEY_DAYS = 30       # a contact older than this is not watched
READ_DAYS = 3       # a thread the session only read counts this long: a read is often research, not a contact
BACK_DAYS = 7       # the first read of a mailbox looks back at most this far
MAIL_EVERY = 300    # a mailbox this Mac reads itself: free, at any hour
MODEL_EVERY = 900   # the one Haiku run through Workrouter: the person's own mailbox with no sign-in, and Chat
OVERLAP = 120       # seconds each read looks back past the last one, for mail that lands late
MAX_TERMS = 30      # terms in one Gmail search; more go in another search of the same read
MAX_SPACES = 10     # Chat spaces read in one run
WR = 'mcp__claude_ai_Sttark_Workrouter__'
ME = None           # the person's address; tests set it

# --- small helpers ----------------------------------------------------------------------------------------------

def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'watch  ' + line + '\n')
    except OSError:
        pass


def peek():
    try:
        return json.load(open(FILE))
    except (OSError, ValueError):
        return {}


def save(W):
    os.makedirs(KIT, exist_ok=True)
    tmp = FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(W, f)
    os.replace(tmp, FILE)


def me():
    if ME is not None:
        return ME
    try:
        return (json.load(open(os.path.expanduser('~/.claude.json'))).get('oauthAccount') or {}).get('emailAddress', '').lower()
    except (OSError, ValueError):
        return ''


def stamp(text):
    """A transcript's ISO time (2026-11-17T18:40:12.508Z) as a Unix time; 0 when there is none."""
    if not isinstance(text, str):
        return 0
    try:
        return calendar.timegm(time.strptime(text[:19], '%Y-%m-%dT%H:%M:%S'))
    except ValueError:
        return 0


def mail_time(text):
    try:
        return email.utils.parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, IndexError, AttributeError):
        return 0


def clock(ts):
    return time.strftime('%a %-I:%M %p', time.localtime(ts)) if ts else '-'


def loads(text):
    try:
        x = json.loads(text)
        return x if isinstance(x, dict) else {}
    except (TypeError, ValueError):
        return {}


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text')
    return ''


ADDR = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def addrs(*values):
    out = []
    for v in values:
        if isinstance(v, list):
            v = ','.join(str(x) for x in v)
        for a in ADDR.findall(v if isinstance(v, str) else ''):
            a = a.lower().strip(".'")
            if a not in out:
                out.append(a)
    return out


def sender(text):
    a = addrs(text)
    return a[0] if a else ''


# Mail from these domains is a person's own mailbox: only the exact address counts, never the domain.
FREE = {'gmail.com', 'googlemail.com', 'yahoo.com', 'ymail.com', 'hotmail.com', 'outlook.com', 'live.com', 'msn.com',
        'icloud.com', 'me.com', 'mac.com', 'aol.com', 'qq.com', 'foxmail.com', '163.com', '126.com', 'yeah.net',
        'sina.com', 'sina.cn', 'sohu.com', 'aliyun.com', '139.com', 'protonmail.com', 'proton.me', 'gmx.com',
        'gmx.net', 'mail.com', 'zoho.com', 'yandex.com', 'yandex.ru', 'comcast.net', 'att.net', 'sbcglobal.net',
        'verizon.net', 'bellsouth.net', 'charter.net', 'spectrum.net', 'cox.net', 'hey.com', 'fastmail.com'}
SECOND = {'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'com.au', 'net.au', 'org.au', 'com.cn', 'net.cn', 'org.cn', 'gov.cn',
          'com.hk', 'com.tw', 'co.jp', 'co.kr', 'com.br', 'com.mx', 'co.in', 'co.nz', 'com.sg', 'com.my', 'co.za'}
# Sites where a click is never a contact to watch: the person's own tools, sign-ins, and the Kit's own pages.
NOT_SITES = {'google.com', 'googleusercontent.com', 'gstatic.com', 'youtube.com', 'asana.com', 'github.com',
             'githubusercontent.com', 'claude.ai', 'claude.com', 'anthropic.com', 'apple.com', 'icloud.com',
             'microsoft.com', 'microsoftonline.com', 'live.com', 'office.com', 'dashlane.com', 'onshape.com'}
# Form services a site puts its contact form on: the answer comes from the site, not from them.
FORM_HOSTS = {'jotform.com', 'jotform.us', 'typeform.com', 'formstack.com', 'wufoo.com', 'cognitoforms.com',
              'hsforms.com', 'hsforms.net', 'hubspot.com', 'formsite.com', '123formbuilder.com', 'surveymonkey.com',
              'paperform.co', 'tally.so', 'formspree.io', 'zohopublic.com', 'forms.office.com', 'wix.com',
              'squarespace.com', 'getform.io', 'formsubmit.co', 'netlify.com', 'smartsheet.com', 'airtable.com'}
# Supplier messengers: the Kit cannot read the messenger itself (it needs the browser). What the platform mails the
# account (a new message, an order the supplier updated, an action required) counts; its sales mail does not.
MESSENGERS = {'alibaba.com', 'made-in-china.com', '1688.com', 'globalsources.com', 'dhgate.com', 'aliexpress.com'}
NOTICE = re.compile(r'(?i)new message|replied|reply|inquir|enquir|quotation|sent you|updated by the supplier|'
                    r'action required|回复|消息|询盘')
# Senders that never answer anyone: a domain match from one does not count. A no-reply sender does, since ticket
# systems and portals send their answers from one ("You have a new message regarding Ticket #2147").
AUTO = re.compile(r'(?i)^(?:mailer-daemon|postmaster|bounces?|newsletters?|marketing|promo(?:tions?)?|deals|offers|'
                  r'news|e?mail-?news)(?:[._+-].*)?$')


def site(host):
    """The registered domain of a host or an address's domain: www.utility.example -> utility.example."""
    host = (host or '').lower().strip().strip('.')
    if '@' in host:
        host = host.split('@', 1)[1]
    if not host or host == 'localhost' or host.endswith('.local') or re.fullmatch(r'[\d.]+|\[?[0-9a-f:]+\]?', host):
        return ''
    parts = host.split('.')
    if len(parts) < 2:
        return ''
    n = 3 if len(parts) >= 3 and '.'.join(parts[-2:]) in SECOND else 2
    return '.'.join(parts[-n:])


def host_of(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


def own_sites(me_):
    out = {site(me_)} if me_ else set()
    try:
        out |= {site(b) for b in load('mail').boxes()}
    except Exception:
        pass
    return {x for x in out if x}


def key(k, v, at, box='', how='', **more):
    """A fact: `first` is when the session first made it (a message counts only after that), `at` the newest time
    (a contact is forgotten KEY_DAYS after it)."""
    d = {'k': k, 'v': v, 'at': at, 'first': at, 'box': box, 'how': how}
    d.update({a: b for a, b in more.items() if b})
    return d


def mail_keys(a, at, box, how, own, who=''):
    """An address the session wrote to: the address, and its domain unless it is a free mailbox. A colleague (the
    person's own domain) gets neither: they write about many things, so only a reply in the same thread counts."""
    if not a or a == box or site(a) in own:
        return []
    out = [key('addr', a, at, box, how, who=who)]
    d = site(a)
    if d and a.split('@')[1] not in FREE and d not in FREE and d not in own:
        out.append(key('domain', d, at, box, how, who=who))
    return out


# --- facts from a session's records -------------------------------------------------------------------------------

MARKS = (b'gmail_create_draft', b'gmail_update_draft', b'gmail_read_message', b'asana_add_comment',
         b'asana_create_task', b'claude-window', b'claude-wait', b'Google_Chat__send_message')
CWD = re.compile(rb'"cwd":\s*"((?:[^"\\]|\\.)*)"')
USER = re.compile(rb'"type":\s*"user"')
CLICK = re.compile(r'\.click\(|requestSubmit|\.submit\(|dispatchEvent\(\s*new\s+(?:Mouse|Pointer|Keyboard)Event')
SEND = re.compile(r'(?i)submit|send|\bpost\b|reply|comment|contact|inquir|enquir|request')
NOT_FORM = re.compile(r'(?i)password|passcode|\bsign[ -]?in\b|\blog[ -]?in\b|verification code|one-time|two-factor|'
                      r'2-step|checkout|check out|place (?:your )?order|add to cart|card number|\bwire\b|payment')
DONE = re.compile(r"(?i)thank(?:s| you)(?: so much)?,? (?:for (?:contacting|reaching out|getting in touch|your "
                  r"(?:message|inquiry|enquiry|request|submission|question|interest|feedback|email|note))|we(?:'ve| "
                  r"have) (?:received|got))|(?:message|inquiry|enquiry|request|submission|form|question|ticket|note|"
                  r"email)(?: has been| was|'s been| is) (?:sent|received|submitted|delivered)|(?:we(?:'ll| will)|"
                  r"someone will|(?:a|our) (?:customer service )?(?:representative|team|staff)(?: member)? will) "
                  r"(?:get back|be in touch|contact you|respond|reply|reach out)|ticket (?:number|#|no\.?)")
URL_LINE = re.compile(r'^https?://\S+$')
CHAT_SPACE = re.compile(r'(?:/room/|/dm/|#chat/space/|#chat/dm/|/app/chat/|/chat/space/)([A-Za-z0-9_-]{6,})')


def interesting(b):
    name = b.get('name') or ''
    if name == 'Bash':
        c = (b.get('input') or {}).get('command') or ''
        return 'claude-window' in c or 'claude-wait' in c
    tool = name.split('__')[-1]
    return tool in ('gmail_create_draft', 'gmail_update_draft', 'gmail_read_message', 'asana_add_comment',
                    'asana_create_task') or (tool == 'send_message' and 'Google_Chat' in name)


def keep_input(name, inp):
    """What a tool's input needs to keep while its result is not in yet (it may wait in watch.json)."""
    if name == 'Bash':
        return {'command': (inp.get('command') or '')[:20000]}
    if 'Google_Chat' in name:
        return {'space': ' '.join(re.findall(r'spaces/[A-Za-z0-9_-]+', json.dumps(inp)))}
    return {k: inp[k] for k in ('to', 'cc', 'bcc', 'task_gid') if k in inp}


def scan_lines(lines, st, me_, own):
    """The facts in transcript lines (bytes, each ending in a newline). st is the file's scan state, changed in
    place: the tool calls whose results are not in yet, the page the browser is on, the folder."""
    out = []
    uses = st.setdefault('uses', {})
    for raw in lines:
        if b'"api-request-blob"' in raw[:300]:
            continue  # a copy of what went to the model
        m = CWD.search(raw, 0, 4000)
        if m:
            st['cwd'] = m.group(1).decode('utf-8', 'replace')
        use = b'"tool_use"' in raw and any(x in raw for x in MARKS)
        res = bool(uses) and b'"tool_result"' in raw and any(i.encode() in raw for i in uses)
        if not (use or res):
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        msg = e.get('message')
        ts = stamp(e.get('timestamp'))
        for b in (msg.get('content') or []) if isinstance(msg, dict) and isinstance(msg.get('content'), list) else []:
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'tool_use' and interesting(b):
                uses[b.get('id', '')] = [b.get('name', ''), keep_input(b.get('name', ''), b.get('input') or {}), ts]
            elif b.get('type') == 'tool_result' and b.get('tool_use_id') in uses:
                name, inp, t0 = uses.pop(b['tool_use_id'])
                try:
                    out += facts(name, inp, text_of(b.get('content')), bool(b.get('is_error')), ts or t0, st, me_, own)
                except Exception as x:  # one odd line never stops the watch
                    log('could not read a step (%s): %s: %s' % (name, type(x).__name__, str(x)[:160]))
    for i in [i for i, u in uses.items() if time.time() - (u[2] or 0) > 86400]:
        uses.pop(i)  # its result never came: the session stopped there
    return out


def scan(path, st, me_, own):
    """The new facts of one transcript file since its last scan (st['off']); a line still being written waits."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size < st.get('off', 0):
        st.clear()  # the file was written again from the start
    off = st.get('off', 0)
    if size == off:
        return []
    lines = []
    with open(path, 'rb') as f:
        f.seek(off)
        for raw in f:
            if not raw.endswith(b'\n'):
                break
            off += len(raw)
            lines.append(raw)
            if len(lines) >= 2000:
                break
    out = scan_lines(lines, st, me_, own)
    st['off'] = off
    if off < size and len(lines) >= 2000:
        out += scan(path, st, me_, own)
    return out


def facts(name, inp, text, err, at, st, me_, own):
    tool = name.split('__')[-1]
    if name == 'Bash':
        cmd = inp.get('command') or ''
        out = []
        if 'claude-wait' in cmd:
            out += wait_facts(cmd, text, at, me_, own)
        if 'claude-window' in cmd:
            out += window_facts(cmd, text, at, st, me_, own)
        return out
    if err:
        return []
    if tool in ('gmail_create_draft', 'gmail_update_draft'):
        r = loads(text)
        if not r.get('draft_id'):
            return []
        out = []
        who = r.get('to') or inp.get('to') or ''
        for a in addrs(inp.get('to'), inp.get('cc'), inp.get('bcc'), r.get('to')):
            if a != me_:
                out += mail_keys(a, at, me_, 'draft', own, who=who if a in who.lower() else '')
        if r.get('thread_id'):
            out.append(key('thread', r['thread_id'], at, me_, 'draft', subject=r.get('subject', ''), who=who))
        return out
    if tool == 'gmail_read_message':
        r = loads(text)
        sent = mail_time(r.get('date'))
        if r.get('thread_id') and (not sent or at - sent < 14 * 86400):  # an old message is research, not a talk
            return [key('thread', r['thread_id'], at, me_, 'read', subject=r.get('subject', ''), who=r.get('from', ''))]
        return []
    if tool == 'asana_add_comment':
        g = str(inp.get('task_gid') or '')
        return [key('asana', g, at, me_, 'comment')] if g.isdigit() and 'comment_added' in text else []
    if tool == 'asana_create_task':
        t = loads(text).get('task') or {}
        return [key('asana', str(t['gid']), at, me_, 'task', who=t.get('name', ''))] if t.get('gid') else []
    if tool == 'send_message' and 'Google_Chat' in name:
        return [key('chat', s, at, '', 'post') for s in (inp.get('space') or '').split() if s]
    return []


def tokens(cmd):
    """A shell command's words, with ; && || | & and each unquoted line end as words of their own. A line that ends in
    a backslash goes on, and a quoted word keeps its line ends. None when it does not parse (a here-document)."""
    try:
        lex = shlex.shlex(cmd.replace('\\\n', ' '), posix=True, punctuation_chars=';&|\n')
        lex.whitespace = ' \t\r'
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return None


def segments(cmd, word):
    """The arguments of each `word ...` command in a shell command: [[arg, ...], ...]. A command that does not parse
    whole is read line by line."""
    toks = tokens(cmd)
    if toks is None:
        toks = []
        for line in cmd.splitlines():
            if word in line:
                toks += (tokens(line) or []) + ['\n']
    out = []
    for i, t in enumerate(toks):
        if t.endswith(word):
            args = []
            for x in toks[i + 1:]:
                if x and not x.strip(';&|\n'):  # a separator (an empty quoted word is not one)
                    break
                args.append(x)
            out.append(args)
    return out


def opt(args, name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ''


def wait_facts(cmd, text, at, me_, own):
    """claude-wait commands that set a wait: a 'wait' fact of its kind (the Stop check reads it), and what an email
    reply wait names, which the watch keeps after the wait ends."""
    out = []
    if not re.search(r'Wait [0-9a-f]{6} set:', text or ''):
        return out
    for args in segments(cmd, 'claude-wait'):
        if not args or args[0] not in ('pr', 'at', 'email-reply', 'check-script', 'check-prompt'):
            continue
        out.append(key('wait', args[0], at, how='set'))
        if args[0] != 'email-reply':
            continue
        box = (opt(args, '--mailbox') or me_).lower()
        pos, skip = [], False
        for x in args[1:]:
            if skip:
                skip = False
            elif x.startswith('--'):
                skip = True
            else:
                pos.append(x)
        if pos and re.fullmatch(r'[0-9a-f]{12,20}', pos[0]):
            out.append(key('thread', pos[0], at, box, 'wait'))
        terms = [opt(args, '--from')] + [a or b for a, b in re.findall(r'(?i)from:\(([^()]*)\)|from:([^\s()]+)',
                                                                       opt(args, '--query'))]
        for t in terms:
            for x in re.split(r'\s+(?:OR\s+)?|[{},]', t or ''):
                x = x.strip().lower()
                if '@' in x:
                    out += mail_keys(sender(x), at, box, 'wait', own)
                elif '.' in x and site(x) and site(x) not in own and site(x) not in FREE:
                    out.append(key('domain', site(x), at, box, 'wait'))
    return out


def window_facts(cmd, text, at, st, me_, own):
    """claude-window commands: the page each is on, and a send on it: a web form that says it got the message, a
    Google Chat post, a mail sent in Gmail, a supplier's messenger."""
    out = []
    page = st.get('page', '')
    for u in re.findall(r'claude-window\s+go\s+["\']?(https?://[^\s"\']+)', cmd):
        if u != page:
            st.pop('before', None)  # a new page: what it says before a click starts again
        page = u
        note_site(st, u)
    for line in (text or '').splitlines():
        line = line.strip()
        # the address `go` and `url` print: on the same site (a redirect, the page after a send) or a form service,
        # never a link the page's text shows
        if URL_LINE.match(line) and (not page or site(host_of(line)) in (site(host_of(page)),) or
                                     site(host_of(line)) in FORM_HOSTS):
            page = line
            note_site(st, line)
    for p in re.findall(r'parentURL=([^&"\s]+)', text or ''):
        note_site(st, urllib.parse.unquote(p))
    st['page'] = page
    h = host_of(page)
    s = site(h)
    codes = [a[1] for a in segments(cmd, 'claude-window') if len(a) > 1 and a[0] == 'js']
    js = ' '.join(codes) if codes and '$(' not in ''.join(codes) else (cmd if 'claude-window js' in cmd else '')
    typed = [a for a in addrs(cmd) if site(a) in own] if js else []
    if typed:
        st['typed'] = [st.get('site', ''), typed[-1]]
    clicked = bool(js) and bool(CLICK.search(js)) and bool(SEND.search(js))
    if clicked and h.endswith('chat.google.com') or (clicked and h == 'mail.google.com' and '/chat' in page):
        m = CHAT_SPACE.search(page)
        if m and re.search(r'(?i)send', js):
            out.append(key('chat', 'spaces/' + m.group(1), at, '', 'post'))
        return out
    if clicked and h == 'mail.google.com':
        if re.search(r'(?i)\bsend\b', js):
            for a in addrs(cmd):
                if a != me_ and site(a) != 'google.com':
                    out += mail_keys(a, at, me_, 'email', own)
        return out
    if clicked and s in MESSENGERS and re.search(r'(?i)send', js):
        out.append(key('domain', s, at, '*', 'messenger'))
        return out
    done = {m.group(0).lower() for m in DONE.finditer(text or '')}
    armed = st.get('armed')
    if clicked and not NOT_FORM.search(cmd) and s and s not in own and s not in NOT_SITES:
        armed = st['armed'] = {'n': 4}
    if not armed:
        st['before'] = sorted(set(st.get('before') or []) | done)[-20:]  # what the page said before any click
        return out
    target = st.get('site', '') if s in FORM_HOSTS or not s else s
    if done - set(st.get('before') or []) and target and target not in own and target not in NOT_SITES:
        t = st.get('typed') or ['', '']
        box = t[1] if t[1] and t[0] in ('', target) else me_
        out.append(key('domain', target, at, box, 'form'))
        st.pop('armed', None)
    else:
        armed['n'] = armed.get('n', 4) - 1
        if armed['n'] <= 0:
            st.pop('armed', None)
    return out


def note_site(st, url):
    """The last site the browser was on that is not a form service: a form service's answer comes from it."""
    s = site(host_of(url))
    if s and s not in FORM_HOSTS and s not in NOT_SITES and 'google.' not in host_of(url):
        if s != st.get('site'):
            st.pop('typed', None)
        st['site'] = s


# --- the sessions it watches ---------------------------------------------------------------------------------------

def merge(keys, new):
    """Adds a fact to a session's keys: one per kind, value and mailbox, with its newest time."""
    for k in keys:
        if k['k'] == new['k'] and k['v'] == new['v'] and k.get('box') == new.get('box'):
            first = min(k.get('first', k['at']), new.get('first', new['at']))
            if new['at'] >= k['at']:
                how = k['how'] if new['how'] == 'read' and k['how'] != 'read' else new['how']  # a read never weakens it
                k.update(new)
                k['how'] = how
            k['first'] = first
            return
    keys.append(new)


def files_of(tp):
    return [tp] + sorted(glob.glob(os.path.join(tp[:-len('.jsonl')], 'subagents', '*.jsonl')))


def refresh(e, tp, now, me_, own):
    """Reads what a session's records gained since the last time, and keeps its keys up to date. Each file's scan
    state is kept by its name in the session's folder ('' for the transcript itself)."""
    for p in files_of(tp):
        st = e['files'].setdefault('' if p == tp else os.path.basename(p), {})
        for f in scan(p, st, me_, own):
            if f['k'] != 'wait':
                merge(e['keys'], f)
        if p == tp and st.get('cwd'):
            e['cwd'] = st['cwd']
    e['keys'] = [k for k in e['keys'] if now - k['at'] < (READ_DAYS if k['how'] == 'read' else KEY_DAYS) * 86400]


def watched(W, wm, now, me_, own):
    """The sessions the watch covers now, with their keys up to date: {cse: entry}. A session with an open wait,
    or a last turn in the last WATCH_DAYS; its records must be on this Mac. One that leaves is forgotten."""
    state = wm.peek()
    waits = [w for w in (state.get('waits') or {}).values() if w.get('cse') and w.get('stage') != 'back']
    info = {}
    for cse, x in (state.get('sessions') or {}).items():
        if x.get('transcript'):
            info[cse] = {'transcript': x['transcript'], 'title': x.get('title') or '', 'url': x.get('url') or ''}
    for w in waits:
        i = info.setdefault(w['cse'], {})
        for a, b in (('transcript', 'transcript'), ('title', 'title'), ('url', 'session_url')):
            if w.get(b) and not i.get(a):
                i[a] = w[b]
    S = W.setdefault('sessions', {})
    out = {}
    for cse, i in info.items():
        tp = i.get('transcript') or ''
        mine = [w for w in waits if w['cse'] == cse]
        try:
            last = os.path.getmtime(tp)
        except OSError:
            S.pop(cse, None)
            continue
        if not mine and now - last > WATCH_DAYS * 86400:
            S.pop(cse, None)
            continue
        e = S.setdefault(cse, {'start': now, 'files': {}, 'keys': [], 'told': [], 'pending': []})
        if e.get('transcript') != tp:
            e['files'] = {}
        e.update(transcript=tp, title=i.get('title') or e.get('title', ''), url=i.get('url') or e.get('url', ''),
                 last=last)
        try:
            refresh(e, tp, now, me_, own)
        except Exception as x:  # one session's odd record never stops the watch of the others
            if now - e.get('failed_said', 0) >= 3600:
                log('%s "%s" records could not be read: %s: %s' % (cse[:12], e.get('title', ''), type(x).__name__,
                                                                    str(x)[:160]))
                e['failed_said'] = now
        for w in mine:  # a thread that only a wait names: the subject the wait's check read, to search by
            for k in e['keys']:
                if k['k'] == 'thread' and k['v'] == w.get('target') and w.get('subject') and not k.get('subject'):
                    k['subject'] = w['subject']
        e['floor'] = min([e['start']] + [w.get('set_at') or now for w in mine])
        out[cse] = e
    for cse in [c for c in S if c not in out and c not in info]:
        S.pop(cse)
    return out


# --- reading ------------------------------------------------------------------------------------------------------

def clean_subject(s):
    s = re.sub(r'(?i)^((re|fwd?|aw|回复|答复|转发)\s*[:：]\s*)+', '', (s or '').strip())
    s = re.sub(r'[\\"(){}\[\]:<>]', ' ', s)
    words = s.split()[:8]
    return ' '.join(words)


def terms_for(keys):
    """Gmail search terms for a mailbox's keys: from: for addresses and domains (a messenger's too), subject: for a
    thread (the match is by its id; the subject finds it), and Asana's notices when a task is watched."""
    t = []
    domains = {k['v'] for k in keys if k['k'] == 'domain'}
    for k in keys:
        if k['k'] == 'addr' and site(k['v']) in domains:
            continue  # its domain's term finds it
        if k['k'] in ('addr', 'domain'):
            x = 'from:' + k['v']
        elif k['k'] == 'thread' and clean_subject(k.get('subject')):
            x = 'subject:"%s"' % clean_subject(k['subject'])
        elif k['k'] == 'asana':
            x = 'from:no-reply@asana.com'
        else:
            continue
        if x not in t:
            t.append(x)
    return t


def queries(keys, since):
    """The searches for a mailbox: its terms, MAX_TERMS a search; Asana's notices in a search of their own, since
    they come for every task the person follows and would crowd the others out of a page."""
    t = [x for x in terms_for(keys) if x != 'from:no-reply@asana.com']
    out = ['after:%d -from:me {%s}' % (since, ' '.join(t[i:i + MAX_TERMS])) for i in range(0, len(t), MAX_TERMS)]
    if any(k['k'] == 'asana' for k in keys):
        out.append('after:%d from:no-reply@asana.com' % since)
    return out


GID = re.compile(r'app\.asana\.com/\S*?/task/(\d+)|app\.asana\.com/0/\d+/(\d+)')


def asana_gid(text):
    m = GID.search(text or '')
    return (m.group(1) or m.group(2)) if m else ''


PAGES = 5           # pages of a search read at most (100 messages each with no model, 20 through Workrouter: 10)


def read_direct(box, qs, mail):
    """Every message that matches the searches, from a mailbox this Mac reads itself (claude-mail): no model."""
    out = {}
    for q in qs:
        got = mail.search(box, q, 100, PAGES)
        if len(got) >= 100 * PAGES:
            log('%s: a search found more than %d messages; the older ones are not read' % (box, len(got)))
        for x in got:
            if 'asana.com' in sender(x['from']):
                try:
                    x['gid'] = asana_gid(mail.read(box, x['id']).get('text'))
                except Exception:
                    x['gid'] = ''
            out[x['id']] = x
    return list(out.values())


def run_model(calls, wm):
    """One Haiku run through Workrouter that makes the calls [(tool, args)], each once (a gmail_search may page):
    ({call index: [result text, ...]}, why). A call that did not run has no entry."""
    tools = sorted({WR + t for t, _ in calls})
    lines = ['Make each of these tool calls exactly once, with exactly these arguments. Make no other call. When a '
             'gmail_search result has a next_page_token, call gmail_search again with the same arguments and '
             'page_token set to it, at most %d more times for that search. Then reply "done".' % (PAGES * 2 - 1)]
    for i, (t, a) in enumerate(calls, 1):
        lines.append('%d. %s%s %s' % (i, WR, t, json.dumps(a, ensure_ascii=False)))
    final, made, why = wm.haiku_calls('\n'.join(lines), tools, timeout=240)
    got = {}
    for name, inp, res, err in made:
        for i, (t, a) in enumerate(calls):
            ident = 'query' if t == 'gmail_search' else 'space_id'
            if name == WR + t and inp.get(ident) == a[ident] and not err:
                got.setdefault(i, []).append(res)
                break
    return got, why


def mail_of(e):
    return {'id': e.get('id', ''), 'thread_id': e.get('thread_id', ''), 'from': e.get('from', ''),
            'to': e.get('to', ''), 'subject': e.get('subject', ''), 'at': mail_time(e.get('date')),
            'snippet': (e.get('snippet') or '')[:300], 'gid': asana_gid(e.get('body') or e.get('snippet'))}


def chat_of(space, m):
    return {'id': m.get('name', ''), 'space': space, 'from': m.get('sender', ''), 'text': (m.get('text') or '')[:600],
            'at': stamp(m.get('createTime'))}


# --- matching -----------------------------------------------------------------------------------------------------

def best_session(msg, box, sess, me_):
    """(strength, contact time, cse, key) of the session a message belongs to, or None."""
    a = sender(msg.get('from'))
    if not a or a == me_ or a == box:
        return None
    d = a.split('@')[1]
    best = None
    for cse, e in sess.items():
        if msg['at'] <= e.get('floor', 0):
            continue
        for k in e['keys']:
            if k.get('first', k['at']) >= msg['at'] or (k.get('box') not in (box, '*')):
                continue
            s = 0
            if k['k'] == 'asana':
                s = 4 if msg.get('gid') and msg['gid'] == k['v'] else 0
            elif k['k'] == 'thread':
                s = 3 if msg.get('thread_id') == k['v'] and not (k['how'] == 'read' and AUTO.match(a.split('@')[0])) else 0
            elif k['k'] == 'addr':
                s = 2 if a == k['v'] else 0
            elif k['k'] == 'domain' and (d == k['v'] or d.endswith('.' + k['v'])):
                if k['how'] == 'messenger':
                    s = 1 if NOTICE.search(msg.get('subject') or '') else 0
                else:
                    s = 0 if AUTO.match(a.split('@')[0]) else 1
            if s and (best is None or (s, k['at']) > best[:2]):
                best = (s, k['at'], cse, k)
    return best


def best_chat(msg, sess):
    best = None
    for cse, e in sess.items():
        if msg['at'] <= e.get('floor', 0):
            continue
        for k in e['keys']:
            if k['k'] == 'chat' and k['v'] == msg['space'] and k.get('first', k['at']) < msg['at'] and \
                    (best is None or k['at'] > best[1]):
                best = (3, k['at'], cse, k)
    return best


def seen(e, msg, cache):
    """Whether the session has the message in its records already: it read it (its id, or a Chat post's name, is
    there), or was told; or the start of a mail's text is there (a wait's prompt quoted it, or the session read it
    in the browser, where no id shows)."""
    if msg['id'] in (e.get('told') or []):
        return True
    needles = [msg['id'].encode()] if msg['id'] else []
    snip = re.sub(r'\s+', ' ', msg.get('snippet') or '').strip()
    for t in {snip, html.unescape(snip)} if msg.get('kind') == 'mail' else ():
        t = t[:50].strip()
        if len(t) >= 40:
            needles += [json.dumps(t, ensure_ascii=a)[1:-1].encode('utf-8') for a in (False, True)]
    return found_in(e, list(dict.fromkeys(needles)), cache)


def own_post(e, msg, cache):
    """Whether a Chat post is one the session wrote itself (sent in the browser, so it comes back as the person's):
    its text is in the session's records. Only a long text counts, so a short answer ("Sounds good") never does."""
    first = re.sub(r'\s+', ' ', msg.get('text') or '').strip()[:40]
    if len(first) < 30 or '"' in first or '\\' in first:
        return False
    return found_in(e, list({json.dumps(first, ensure_ascii=a)[1:-1].encode('utf-8') for a in (False, True)}), cache)


def found_in(e, needles, cache):
    """Whether any of the byte strings is in the session's records (its transcript and its agents')."""
    for n in needles:
        for p in files_of(e['transcript']):
            k = (p, n)
            if k not in cache:
                cache[k] = False
                try:
                    with open(p, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        cache[k] = mm.find(n) >= 0
                except (OSError, ValueError):
                    pass
            if cache[k]:
                return True
    return False


def why_of(k):
    who = k.get('who') or k['v']
    return {('addr', 'draft'): 'you drafted mail to %s' % who, ('addr', 'email'): 'you sent mail to %s' % who,
            ('addr', 'wait'): 'your email reply wait names %s' % who,
            ('domain', 'draft'): 'you drafted mail to %s' % who, ('domain', 'email'): 'you sent mail to %s' % k['v'],
            ('domain', 'form'): 'you sent a web form on %s' % k['v'],
            ('domain', 'messenger'): 'you sent a message on %s' % k['v'],
            ('domain', 'wait'): 'your email reply wait names %s' % k['v'],
            ('thread', 'draft'): 'it is in a thread you drafted in', ('thread', 'read'): 'it is in a thread you read',
            ('thread', 'wait'): 'it is in the thread of your email reply wait',
            ('asana', 'comment'): 'you commented on this Asana task', ('asana', 'task'): 'you made this Asana task',
            ('chat', 'post'): 'you posted in this Chat space'}.get((k['k'], k['how']), 'you contacted %s' % k['v'])


# --- the check ----------------------------------------------------------------------------------------------------

def told(cse):
    """Message ids the Kit already brought the session back for (the watch or a wait): a wait skips them."""
    return set(((peek().get('sessions') or {}).get(cse) or {}).get('told') or [])


def mark_told(cse, ids):
    """A wait brought the session back with these messages: the watch never brings it back for them again."""
    ids = [i for i in ids if i]
    if not cse or not ids:
        return
    W = peek()
    e = W.setdefault('sessions', {}).setdefault(cse, {'start': time.time(), 'files': {}, 'keys': [], 'told': [],
                                                       'pending': []})
    e['told'] = (e.get('told', []) + [i for i in ids if i not in e.get('told', [])])[-500:]
    e['pending'] = [m for m in e.get('pending', []) if m['id'] not in ids]
    save(W)


def check(wm=None, now=None):
    """The minute check, after the waits: reads what each due mailbox and space got, matches it to the sessions,
    and brings each session back once with what came for it."""
    wm = wm or load('wait')
    now = now or time.time()
    me_ = me()
    own = own_sites(me_)
    W = peek()
    sess = watched(W, wm, now, me_, own)
    boxes = W.setdefault('boxes', {})
    by_box = {}
    every_box = [me_] + [x for x in direct_boxes(wm) if x != me_]   # where a platform's notice can land
    for cse, e in sess.items():
        for k in e['keys']:
            if k['k'] == 'chat':
                continue
            for b in ([k['box']] if k.get('box') not in ('', '*') else every_box):
                if b:
                    by_box.setdefault(b, []).append(k)
    cache = {}
    found = []
    model_calls, model_boxes = [], {}
    hour = time.localtime(now).tm_hour
    for box, keys in by_box.items():
        b = boxes.setdefault(box, {})
        floor = min([e['floor'] for e in sess.values() if any(k in e['keys'] for k in keys)] or [now])
        since = int(max(b['read_at'] - OVERLAP, now - BACK_DAYS * 86400) if b.get('read_at') else
                    max(floor, now - BACK_DAYS * 86400))
        if wm.direct(box):
            if now - max(b.get('read_at', 0), b.get('tried_at', 0)) < MAIL_EVERY:
                continue
            b['tried_at'] = now
            try:
                msgs = read_direct(box, queries(keys, since), load('mail'))
            except Exception as x:
                fail(b, box, x, now)
                continue
            b.update(read_at=now, via='mail')
            b.pop('failing', None)
            found += [(box, dict(m, kind='mail')) for m in msgs]
        elif box == me_:
            # a Haiku run: every MODEL_EVERY from 7 AM to 9 PM; one that failed tries again after 10 minutes
            if now - b.get('read_at', 0) < MODEL_EVERY or now - b.get('tried_at', 0) < 600 or not 7 <= hour < 21:
                continue
            for q in queries(keys, since):
                model_boxes[len(model_calls)] = box
                model_calls.append(('gmail_search', {'query': q, 'max_results': 20, 'include_body': True,
                                                     'body_chars': 300}))
        elif now - b.get('said_at', 0) > 86400:
            b['said_at'] = now
            log('%s: the Kit cannot read this mailbox, so replies to it wait for the deadlines. To read it: '
                'claude-mail sign-in %s' % (box, box))
    newest = {}
    for e in sess.values():
        for k in e['keys']:
            if k['k'] == 'chat':
                newest[k['v']] = max(newest.get(k['v'], 0), k['at'])
    spaces = sorted(newest, key=lambda x: -newest[x])[:MAX_SPACES]  # the spaces posted in last, if there are many
    chat = W.setdefault('chat', {})
    if spaces and now - chat.get('read_at', 0) >= MODEL_EVERY and now - chat.get('tried_at', 0) >= 600 and 7 <= hour < 21:
        csince = chat.get('read_at', 0) - OVERLAP if chat.get('read_at') else \
            min([e['floor'] for e in sess.values() if any(k['k'] == 'chat' for k in e['keys'])] or [now])
        iso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(max(csince, now - BACK_DAYS * 86400)))
        for s in spaces:
            model_boxes[len(model_calls)] = s
            model_calls.append(('gchat_search_messages', {'space_id': s, 'filter': 'createTime > "%s"' % iso}))
    if model_calls and not held():
        for target in set(model_boxes.values()):
            (chat if target.startswith('spaces/') else boxes.setdefault(target, {}))['tried_at'] = now
        try:
            got, why = run_model(model_calls, wm)
        except Exception as x:
            got, why = {}, '%s: %s' % (type(x).__name__, str(x)[:160])
        ok_boxes = {}
        for i, (t, a) in enumerate(model_calls):
            target = model_boxes[i]
            ok_boxes.setdefault(target, True)
            if i not in got:
                ok_boxes[target] = False
                continue
            if t == 'gmail_search' and got[i] and loads(got[i][-1]).get('next_page_token'):
                log('%s: a search found more than %d messages; the older ones are not read' % (target, 20 * len(got[i])))
            for text in got[i]:
                r = loads(text)
                if t == 'gmail_search':
                    found += [(target, dict(mail_of(e), kind='mail')) for e in r.get('emails') or []]
                else:
                    found += [(target, dict(chat_of(target, m), kind='chat')) for m in r.get('messages') or []]
        for target, ok in ok_boxes.items():
            rec = boxes.setdefault(target, {}) if not target.startswith('spaces/') else chat
            if ok:
                rec.update(read_at=now, via='model')
                rec.pop('failing', None)
            else:
                fail(rec, target, RuntimeError(why or 'Haiku did not make the call'), now)
    save(W)  # what was read, and when, before anything that could fail: a read is never made again for nothing
    picked = {}
    taken = set()  # a message one session got (or was told about) never goes to another
    for x in (W.get('sessions') or {}).values():
        taken.update(x.get('told') or [])
        taken.update(m.get('id') for m in x.get('pending') or [])
    for box, m in found:
        try:
            if not m.get('id') or not m.get('at') or m['id'] in taken:
                continue
            if m['kind'] == 'chat' and chat.get('me') and m.get('from') == chat['me']:
                continue  # the person's own post
            b = best_chat(m, sess) if m['kind'] == 'chat' else best_session(m, box, sess, me_)
            if not b:
                continue
            e = sess[b[2]]
            if m['kind'] == 'chat' and own_post(e, m, cache):
                if m.get('from'):
                    chat['me'] = m['from']  # its sender is the person: their other posts never count either
                continue
            if seen(e, m, cache):
                continue
            taken.add(m['id'])
            m.update(box=box if m['kind'] == 'mail' else '', why=why_of(b[3]))
            picked.setdefault(b[2], {})[m['id']] = m
        except Exception as x:  # one odd message never stops the others
            log('could not match a message (%s): %s: %s' % (m.get('id', '?'), type(x).__name__, str(x)[:160]))
    for cse, ms in picked.items():
        sess[cse].setdefault('pending', []).extend(sorted(ms.values(), key=lambda x: x['at']))
    for box, b in boxes.items():
        n = sum(1 for bx, m in found if bx == box)
        if b.get('read_at') == now and (n or now - b.get('logged_at', 0) >= 3600):
            b['logged_at'] = now
            log('%s read (%s): %d new message%s, %d for a session' % (
                box, 'no model' if b.get('via') == 'mail' else 'Haiku through Workrouter', n, '' if n == 1 else 's',
                sum(1 for c in picked.values() for m in c.values() if m.get('box') == box)))
    save(W)
    deliver(W, wm, sess, cache, now)
    save(W)
    return picked


def direct_boxes(wm):
    try:
        return [b for b in load('mail').boxes() if wm.direct(b)]
    except Exception:
        return []


def held():
    try:
        return load('limit-hook').held(None, None)
    except Exception:
        return False


def fail(rec, target, x, now):
    why = str(x)[:200] or type(x).__name__
    if rec.get('failing') != why or now - rec.get('failed_said', 0) >= 3600:
        log('%s read failed: %s' % (target, why))
        rec['failed_said'] = now
    rec['failing'] = why
    rec.setdefault('failing_since', now)


def line_of(m):
    when = time.strftime('%a %b %-d %-I:%M %p', time.localtime(m['at']))
    if m['kind'] == 'chat':
        return '- A post in Google Chat space %s, %s: "%s". It counts because %s. Read the space with Workrouter\'s ' \
               'gchat_search_messages.' % (m['space'], when, re.sub(r'\s+', ' ', m.get('text', ''))[:300], m['why'])
    how = ('claude-mail read %s %s' % (m['box'], m['id']) if direct_read(m.get('box'))
           else "Workrouter's gmail_read_message with message_id %s" % m['id'])
    task = ' Asana task: https://app.asana.com/0/0/%s.' % m['gid'] if m.get('gid') else ''
    return '- Mail to %s from %s, %s: "%s" (%s). It counts because %s.%s Read it in full: %s.' % (
        m['box'], m['from'], when, m.get('subject', ''), re.sub(r'\s+', ' ', m.get('snippet', ''))[:240], m['why'],
        task, how)


def direct_read(box):
    try:
        return bool(box) and load('mail').can_read(box)
    except Exception:
        return False


def prompt_for(cse, e, msgs, wm):
    lines = ['[Sttark Claude Kit] New messages came in that may concern this session. The Kit watches the people, '
             'threads, sites, Asana tasks and Chat spaces that this session contacted, and these match:']
    lines += [line_of(m) for m in msgs[:6]]
    if len(msgs) > 6:
        lines.append('- And %d more like them.' % (len(msgs) - 6))
    waits = [w for w in (wm.peek().get('waits') or {}).values() if w.get('cse') == cse and w.get('stage') != 'back']
    lines.append('Read each one in full and decide if it needs action. If it does, go on with the work as far as you '
                 'can, then send the person one message with claude-notify that stands alone: what came in, what you '
                 'did, and what they must do. If it does not (a receipt, an automatic reply, or a thing you already '
                 'did), do nothing more: end the turn with one line that says why, with no claude-notify.')
    if waits:
        lines.append('Your waits with the Kit: %s. If a message answers one, cancel it (claude-wait --cancel <id>) or '
                     'set the next wait.' % '; '.join('%s (id %s, deadline %s)' % (
                         wm.describe(w), w['id'], wm.clock(w['by']) if w.get('by') else 'none') for w in waits))
    else:
        lines.append('You have no wait with the Kit. If you wait on someone again, hand it to the Kit with claude-wait.')
    return '\n'.join(lines)


def deliver(W, wm, sess, cache, now):
    """Brings each session with new messages back once, with all of them. A session in a turn is tried again the
    next minute; one that read them by itself meanwhile is not brought back. What each one got is saved at once,
    so a failure with the next never brings it back twice."""
    for cse, e in sess.items():
        try:
            deliver_one(wm, cse, e, cache, now)
        except Exception as x:
            log('%s could not come back: %s: %s' % (cse[:12], type(x).__name__, str(x)[:160]))
        save(W)


def deliver_one(wm, cse, e, cache, now):
    """One session's new messages: bring it back with them, or keep them for its next minute."""
    pend = [m for m in e.get('pending') or [] if not seen(e, m, cache)]
    e['pending'] = pend
    if not pend:
        return
    # A wait brought it back moments ago: it reads its first prompt now, so these wait for that turn to end.
    if any(w.get('cse') == cse and w.get('stage') == 'back' and time.time() - w.get('back_at', 0) < 180
           for w in (wm.peek().get('waits') or {}).values()):
        return
    title = e.get('title') or cse[-6:]
    what = '; '.join('%s "%s"' % (m['from'] or 'Chat', (m.get('subject') or m.get('text') or '')[:60]) for m in pend[:3])
    if DRY:
        print('would wake %s (%s) with %d new: %s' % (title, cse, len(pend), what))
        log('%s "%s" would come back (dry) for %s' % (cse[:12], title, what))
        e['told'] = (e.get('told', []) + [m['id'] for m in pend])[-500:]
        e['pending'] = []
        return
    w = {'id': 'w' + cse[-5:], 'cse': cse, 'transcript': e['transcript'], 'cwd': e.get('cwd') or '',
         'title': title, 'session_url': e.get('url', '')}
    try:
        ok = wm.bring_back(w, prompt_for(cse, e, pend, wm))
    except RuntimeError as x:
        if str(x) == 'busy':
            if now - e.get('busy_said', 0) > 900:
                log('%s "%s" is in a turn; it comes back with %d new message%s when the turn ends'
                    % (cse[:12], title, len(pend), '' if len(pend) == 1 else 's'))
                e['busy_said'] = now
            return
        ok = False
        log('%s "%s" could not come back: %s' % (cse[:12], title, str(x)[:160]))
    except Exception as x:
        ok = False
        log('%s "%s" could not come back: %s: %s' % (cse[:12], title, type(x).__name__, str(x)[:160]))
    e['told'] = (e.get('told', []) + [m['id'] for m in pend])[-500:]
    e['pending'] = []
    if ok:
        log('%s "%s" brought back for %d new message%s: %s' % (cse[:12], title, len(pend),
                                                               '' if len(pend) == 1 else 's', what))
        return
    try:
        load('notify').send('New messages for ' + title, 'New messages came in that may concern the session "%s": '
                            '%s. It could not come back by itself; open it to go on.' % (title, what),
                            title=title, url=e.get('url', ''), cse=cse)
        log('%s "%s" could not come back; the Kit sent you the message' % (cse[:12], title))
    except Exception as x:
        log('%s "%s" message failed: %s' % (cse[:12], title, str(x)[:160]))


# --- the Stop check: a contact with no reply wait -------------------------------------------------------------

def person_prompt(e):
    if e.get('type') != 'user' or e.get('isMeta') or e.get('isSidechain'):
        return False
    c = (e.get('message') or {}).get('content')
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c):
            return False
        c = text_of(c)
    return isinstance(c, str) and bool(c.strip()) and not c.lstrip().startswith('<task-notification>')


def turn_facts(tp, me_=None, own=None):
    """The facts of the work since the person's last message (its agents' too): (facts, the time it started)."""
    me_ = me() if me_ is None else me_
    own = own_sites(me_) if own is None else own
    try:
        with open(tp, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 6000000))
            lines = f.read().split(b'\n')
    except OSError:
        return [], 0
    start, begin = 0, 0
    for i in range(len(lines) - 1, -1, -1):
        raw = lines[i]
        if not USER.search(raw, 0, 800) or b'tool_result' in raw:
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if isinstance(e, dict) and person_prompt(e):
            start, begin = stamp(e.get('timestamp')), i + 1
            break
    if not start:  # no message of the person in the tail: the work since the tail's first time
        for raw in lines[1:]:
            m = re.search(rb'"timestamp":\s*"([^"]+)"', raw[:4000])
            if m:
                start = stamp(m.group(1).decode('utf-8', 'replace'))
                break
    if not start:
        return [], 0
    out = scan_lines([l + b'\n' for l in lines[begin:] if l], {}, me_, own)
    for p in files_of(tp)[1:]:
        try:
            if os.path.getmtime(p) < start:
                continue
        except OSError:
            continue
        out += [k for k in scan(p, {}, me_, own) if k['at'] >= start]
    return out, start


def covered(k, waits):
    """Whether an open email reply wait of the session watches this contact."""
    for w in waits:
        if w.get('kind') != 'email-reply':
            continue
        text = ' '.join((w.get('target') or '', w.get('from') or '', w.get('query') or '')).lower()
        if k['v'].lower() in text or (k['k'] == 'addr' and site(k['v']) in text):
            return True
    return False


def missing_wait(tp, sid, waits_state):
    """For the Stop check: the contacts this turn made where the answer comes as a message, with no wait for it:
    a mail, a draft or a web form with no wait but a time (and no open email reply wait that names it), or a
    supplier's messenger with no wait at all (the Kit cannot read the messenger, so a time to look is right)."""
    facts, _ = turn_facts(tp)
    reply = any(f['k'] == 'wait' and f['v'] != 'at' for f in facts)
    timed = any(f['k'] == 'wait' for f in facts)
    contacts = [f for f in facts if f['k'] in ('addr', 'domain') and (
        (f['how'] in ('draft', 'email', 'form') and not reply) or (f['how'] == 'messenger' and not timed))]
    if not contacts:
        return []
    mine = [w for w in waits_state.values() if w.get('stage') != 'back' and
            (w.get('sid') == sid or (tp and w.get('transcript') == tp))]
    out = []
    for f in contacts:
        if covered(f, mine):
            continue
        if f['k'] == 'addr' and any(g['k'] == 'domain' and g['v'] == site(f['v']) for g in contacts):
            continue  # the domain names it
        if f not in out:
            out.append(f)
    return out


def wait_hint(contacts):
    """The claude-wait command for the first contact, for the session's note."""
    f = contacts[0]
    if f['how'] == 'messenger':
        return 'claude-wait at <time> --why "<line>" to look at the %s messenger with claude-window' % f['v']
    mail = [c for c in contacts if c['how'] != 'messenger']
    q = 'from:(%s)' % ' OR '.join(sorted({c['v'] for c in mail if c['k'] == 'domain'} or {mail[0]['v']}))
    box = f.get('box') or ''
    return 'claude-wait email-reply --query "%s"%s --by <deadline> --why "<line>"' % (
        q, ' --mailbox %s' % box if box and box != me() and box != '*' else '')


# --- the command --------------------------------------------------------------------------------------------------

def listing():
    W = peek()
    S = W.get('sessions') or {}
    now = time.time()
    shown = 0
    for cse, e in sorted(S.items(), key=lambda x: -(x[1].get('last') or 0)):
        keys = [k for k in e.get('keys') or [] if k['k'] != 'wait']
        if not keys:
            continue
        shown += 1
        print('%s  %s' % (e.get('title') or cse, cse))
        for k in sorted(keys, key=lambda k: -k['at'])[:25]:
            print('    %-6s %-40s %s, %s%s' % (k['k'], k['v'][:40], k['how'], time.strftime('%b %-d %-I:%M %p', time.localtime(k['at'])),
                                       ' (%s)' % k['box'] if k.get('box') and k['box'] not in ('*', me()) else ''))
        if e.get('pending'):
            print('    waiting to come back with %d new message%s' % (len(e['pending']), '' if len(e['pending']) == 1 else 's'))
    for box, b in sorted((W.get('boxes') or {}).items()):
        print('%s: read %s%s%s' % (box, clock(b.get('read_at')), ' with no model' if b.get('via') == 'mail' else
                                   ' with Haiku through Workrouter' if b.get('via') == 'model' else '',
                                   ', FAILING since %s: %s' % (clock(b.get('failing_since')), b['failing'])
                                   if b.get('failing') else ''))
    if (W.get('chat') or {}).get('read_at'):
        print('Google Chat spaces: read %s' % clock(W['chat']['read_at']))
    if not shown:
        print('No session has a contact to watch.')
    elif me() and not direct_read(me()):
        print('Your own mailbox is read with one Haiku run every %d minutes from 7 AM to 9 PM. To read it with no model, '
              'every %d minutes at any hour: claude-mail sign-in %s' % (MODEL_EVERY // 60, MAIL_EVERY // 60, me()))
    return 0


if __name__ == '__main__':
    if sys.argv[1:2] == ['--check']:
        check()
        sys.exit(0)
    if sys.argv[1:2] == ['--list']:
        sys.exit(listing())
    print(__doc__.split('\n\n')[0])
