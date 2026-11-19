#!/usr/bin/python3
"""The Kit's reply watch: when a session contacted someone (an email or a draft, a web form, a supplier's messenger,
an Asana comment or task, a Google Chat post), an answer on any of those channels brings the session back, also
when the session set no wait for it. wait.py --check runs it every minute; there is nothing to start.

What it watches comes from facts in the session's own records (its transcript and its agents'), with no model: the
addresses and domains it emailed or drafted to, the Gmail threads it drafted or read in, the domains of web forms
it sent through claude-window, the platform of a supplier messenger it sent on, the Asana tasks it commented on or
made, the Chat spaces it posted in, and what its email reply waits name. Only a claude-window or claude-wait that the
shell runs counts, never text that names one (runs()). A session is watched while it has an open wait, and for
WATCH_DAYS after its last turn; a contact older than KEY_DAYS is not watched. A session the person archived that has
no open wait (on the Archived page) is not watched: the watch reads nothing for it and never brings it back
(archived_ids(), not_watched()). Logged once, as "not watched: archived with no wait", or "not told of <n> new
message(s): archived with no wait: ..." when messages for it had come in.

How it reads, for every session at once, in as few reads as it can: a mailbox this Mac signed in to (claude-mail)
with one Gmail search every 5 minutes, at any hour, with no model; the person's own mailbox with no sign-in, and
the Chat spaces, with one Haiku run through Workrouter every 15 minutes from 7 AM to 9 PM (one gmail_search, and
one gchat_search_messages per space). An Asana comment comes as Asana's own notice mail, with the task's id in it.

A new message counts for a session when it is from an address or a domain the session wrote to, in a thread it
used, an Asana notice for its task, or a post in its space; newer than that contact and than the session's watch
(for a session with an open wait, its oldest open wait: so the first read after an update looks back to then); not
from the person; not one the session has already read (its id is in the session's records) or been told about. A
domain match from an automatic sender (no-reply and the like) does not count.

Two kinds of match. A narrow one is a reply in an email thread the session used, a comment on an Asana task it
commented on or made, or a Chat reply in the thread of the session's own post: it always brings the session back,
and it goes to that one session (a task before a thread, then the newest contact). A broad one is mail from an
address, a domain or a form's site the session wrote to, in a new thread, or a post in a Chat space it posted in
that is not in its post's thread: such a channel carries other work too, so before it brings a session back, one
Haiku call (MODEL, no tools, hooks off) reads the session's name, its first prompt, what it sent on that channel and
the new message, and answers YES or NO: is the message about that session's work? Every session with a broad match
is asked, and only those with YES come back. A NO is logged ("skip ... not about this session's work") and shows on
the Events page; a call that fails brings the session back all the same, so nothing is lost. The call waits while
the account is held at the usage limit. The session comes back the way a wait brings it back, with the messages
and one question: does this need action?

THE PERSON'S OWN REPLIES. The same reads also bring the person's own messages (from their address, or their account in
Chat and Asana) in the places a session watches or waits on: an email thread it used, an email reply wait's thread, a
thread the Kit brought it back for (`back`, note_back()); the Chat thread or space it posted in; an Asana task it
commented on or made. A mailbox gets one more search of the same read for them (from the person, by those threads'
subjects, never a draft); Chat posts are in the read already; an Asana task's comments come in the Workrouter run
when it runs (asana_get_task_stories; Asana mails no one about their own comment). A reply in the thread is a match
with no model call; a post elsewhere in a Chat space is checked first, with the same Haiku call as a broad match. For
each match: a message kept in the Kit about that place since the Kit brought the session back for it gets "You
replied <time>" (notify.py mark_replied()); an email reply wait on that thread stays open (it still waits for the
other person) and its row says "You replied <time>" (`replied` on the wait). When the reply came after the session's
last turn, the session is told once, with no alert: a note on its next prompt (effort-hook.py take_replied()), or
brought back with the note at once only when a message kept in the Kit or an email reply wait depends on it. Logged as
"watch  replied ...".

    watch.py --list      what the Kit watches now, for each session (claude-wait --watching runs this)

Logged with lines starting "watch". STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and log;
STTARK_WAIT_DRY=1 reads and decides, prints what it would bring back, and brings nothing back (the Haiku call still
runs). STTARK_WATCH_MODEL is a command that stands in for the Haiku call: the question on its input, the answer on
its output.
"""
import calendar, email.utils, glob, html, importlib.util, json, mmap, os, re, subprocess, sys, time, urllib.parse

HERE = os.path.dirname(os.path.realpath(__file__))
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
DRY = bool(os.environ.get('STTARK_WAIT_DRY'))
FILE = os.path.join(KIT, 'watch.json')
ARCHIVED = os.path.join(KIT, 'archived.json')  # the Archived page's list (effort-hook.py archived())
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
MAX_TASKS = 10      # Asana tasks read in one run, for the person's own comments (asana_get_task_stories)
TASK_DAYS = 7       # an Asana task is read for them while a session touched it in this many days
OWN_SAID = 300      # characters kept of the person's own reply, for the session's note
BACK_MAX = 20       # bring-backs kept for each session (note_back())
WR = 'mcp__claude_ai_Sttark_Workrouter__'
ME = None           # the person's address; tests set it
NARROW = 3          # a match this strong or stronger (a thread, an Asana task, a Chat thread) needs no check
MODEL = 'claude-haiku-5-5'   # the check of a broad match
JUDGE_TIMEOUT = 30  # seconds the check may take
CHECKS_A_MINUTE = 8  # checks in one minute check at most (each takes a few seconds, under the wait lock); the rest wait
BUDGET = [CHECKS_A_MINUTE]
SAID = 1500         # characters kept of what the session sent
STUB = os.environ.get('STTARK_WATCH_MODEL', '')
JUDGE = """You check one new message for a person who runs many Claude Code sessions. Each session does one piece \
of work. The session below once sent a message on a channel (an email address, a company's domain, a web form's \
site, or a Google Chat space or direct message) that also carries other work. Now a new message came on that \
channel. Decide if the new message is about this session's work. Only YES brings the session back.

YES: it answers or follows up on what the session sent, or it is about the same thing (the same item, order, \
quote, ticket, question or project), also in part. A short reply that could answer the session's message (thanks, \
ok, a yes or no, a number, a time) is YES. A receipt, ticket notice or automatic reply for what the session sent \
is YES.
NO: it is clearly about something else: other work, another topic, a newsletter or sales mail, a new question \
that has no link to the session's work.

Answer on one line: YES or NO, then " - " and the reason in 15 words or fewer."""

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
        raw = json.dumps(inp)
        return {'space': ' '.join(re.findall(r'spaces/[A-Za-z0-9_-]+', raw)),
                'threads': re.findall(r'spaces/[A-Za-z0-9_-]+/threads/([A-Za-z0-9_-]+)', raw),
                'text': str(inp.get('messageText') or inp.get('text') or '')[:SAID]}
    out = {k: inp[k] for k in ('to', 'cc', 'bcc', 'task_gid', 'subject') if k in inp}
    if inp.get('body'):
        out['body'] = str(inp['body'])[:SAID]
    return out


def said_of(subject, body):
    """What the session sent, as the check of a broad match reads it: the subject, then the text."""
    s = re.sub(r'\s+', ' ', ('%s: %s' % (subject, body) if subject and body else subject or body or '')).strip()
    return s[:SAID]


def chat_thread(name):
    """The thread of a Chat message from its name: spaces/S/messages/T.M is in thread T, and a reply in it when M is
    not T (a post that starts a thread, and every post in a direct message, is T.T)."""
    m = re.search(r'/messages/([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)$', name or '')
    return (m.group(1), m.group(1) != m.group(2)) if m else ('', False)


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
        said = said_of(r.get('subject') or inp.get('subject') or '', inp.get('body') or '')
        for a in addrs(inp.get('to'), inp.get('cc'), inp.get('bcc'), r.get('to')):
            if a != me_:
                out += mail_keys(a, at, me_, 'draft', own, who=who if a in who.lower() else '')
        if r.get('thread_id'):
            out.append(key('thread', r['thread_id'], at, me_, 'draft', subject=r.get('subject', ''), who=who))
        for k in out:
            if said:
                k['said'] = said
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
        # the post's thread: the one it was sent to, or the one the created message names
        threads = list(inp.get('threads') or []) + [m.group(1) for m in re.finditer(
            r'spaces/[A-Za-z0-9_-]+/(?:threads/|messages/)([A-Za-z0-9_-]+)', text or '')]
        return [key('chat', s, at, '', 'post', said=said_of('', inp.get('text') or ''),
                    threads=list(dict.fromkeys(threads))[:20])
                for s in (inp.get('space') or '').split() if s]
    return []


HEREDOC = re.compile(r"<<-?[ \t]*\\?(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# Words before the command word: assignments go too. timeout and the like take a time (a number) first.
PREFIX = {'sudo', 'env', 'nohup', 'exec', 'command', 'time', 'then', 'do', 'else', 'elif', 'if', 'while', 'until', '!',
          '{', 'caffeinate', 'timeout', 'gtimeout'}
SHELLS = {'sh', 'bash', 'zsh', 'dash'}
OPTION = re.compile(r'-\S*|\d+(?:\.\d+)?[smhd]?')  # an option or a time after a prefix word


def commands(cmd, depth=0):
    """The simple commands the shell runs in a command line: [[word, ...], ...], with the quotes taken off. Also those
    in $( ) and ` `. Never text in quotes, a comment, or the text of a here-document (what a command reads: a file it
    writes, a script it gives to python). A word keeps a $( ) in it as text."""
    out, ws, docs, n, i = [], [], [], len(cmd), 0
    cur = None

    def word():
        nonlocal cur
        if cur is not None:
            ws.append(cur)
        cur = None

    def end():
        word()
        if ws:
            out.append(ws[:])
        del ws[:]

    def sub(j):
        """Where the $( ) or ` ` that starts at j ends, and the commands in it."""
        if cmd[j] == '`':
            k = cmd.find('`', j + 1)
            k = n if k < 0 else k
            return k + 1, (commands(cmd[j + 1:k], depth + 1) if depth < 4 else [])
        k, level, q = j + 2, 1, ''
        while k < n and level:
            ch = cmd[k]
            if q:
                if ch == q:
                    q = ''
                elif ch == '\\' and q == '"':
                    k += 1
            elif ch in '\'"':
                q = ch
            elif ch == '\\':
                k += 1
            elif ch == '(':
                level += 1
            elif ch == ')':
                level -= 1
            k += 1
        return k, (commands(cmd[j + 2:k - 1], depth + 1) if depth < 4 else [])

    while i < n:
        c = cmd[i]
        if c == '\\':
            if cmd[i + 1:i + 2] != '\n':
                cur = (cur or '') + cmd[i + 1:i + 2]
            i += 2
        elif c == "'":
            k = cmd.find("'", i + 1)
            k = n if k < 0 else k
            cur, i = (cur or '') + cmd[i + 1:k], k + 1
        elif c == '"':
            k, text = i + 1, ''
            while k < n and cmd[k] != '"':
                if cmd[k] == '\\' and k + 1 < n:
                    text += '' if cmd[k + 1] == '\n' else cmd[k + 1] if cmd[k + 1] in '"\\$`' else cmd[k:k + 2]
                    k += 2
                elif cmd.startswith('$(', k) or cmd[k] == '`':
                    e, inner = sub(k)
                    out += inner
                    text, k = text + cmd[k:e], e
                else:
                    text, k = text + cmd[k], k + 1
            cur, i = (cur or '') + text, k + 1
        elif cmd.startswith('$(', i) or c == '`':
            e, inner = sub(i)
            out += inner
            cur, i = (cur or '') + cmd[i:e], e
        elif c == '#' and cur is None:
            k = cmd.find('\n', i)
            i = n if k < 0 else k
        elif cmd.startswith('<<<', i):  # a here-string: a word, not a here-document
            cur, i = (cur or '') + '<<<', i + 3
        elif cmd.startswith('<<', i) and HEREDOC.match(cmd, i):
            m = HEREDOC.match(cmd, i)
            word()
            docs.append(m.group(2))
            i = m.end()
        elif c == '\n':
            end()
            i += 1
            for d in docs:  # each here-document's text: the lines up to its end word
                while i < n:
                    k = cmd.find('\n', i)
                    k = n if k < 0 else k
                    line, i = cmd[i:k], k + 1
                    if line.strip() == d:
                        break
            docs = []
        elif c in ' \t\r':
            word()
            i += 1
        elif c in ';&|()':
            end()
            i += 1
        else:
            cur, i = (cur or '') + c, i + 1
    end()
    return out


def runs(cmd, name, depth=0):
    """The arguments of each `name ...` the shell really runs in a command: [[arg, ...], ...]. Also in $( ), ` ` and
    bash -c '...', and by its path (name.sh too) or a variable the command set to its path ("$CW" go ...). A command
    that only names it, in quotes, a comment or a here-document's text (a test, a script, a file it writes), does not
    run it, so its URLs, clicks and addresses are no contact."""
    out, values = [], {}
    for ws in commands(cmd):
        i = 0
        while i < len(ws):
            m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)=', ws[i])
            if m:
                values[m.group(1)] = ws[i][m.end():]
            elif ws[i] not in PREFIX and not (i and ws[i - 1] in PREFIX and OPTION.fullmatch(ws[i])):
                break
            i += 1
        if i >= len(ws):
            continue
        v = re.fullmatch(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?', ws[i])
        prog = os.path.basename(values.get(v.group(1), '') if v else ws[i])
        if prog in (name, name + '.sh'):
            out.append(ws[i + 1:])
        elif prog in SHELLS and depth < 2:
            for j in range(i + 1, len(ws) - 1):
                if ws[j].startswith('-') and not ws[j].startswith('--') and 'c' in ws[j]:
                    out += runs(ws[j + 1], name, depth + 1)
                    break
    return out


def opt(args, name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ''


def wait_facts(cmd, text, at, me_, own):
    """claude-wait commands that set a wait: a 'wait' fact of its kind (the Stop check reads it), and what an email
    reply wait names, which the watch keeps after the wait ends."""
    out = []
    if not re.search(r'Wait [0-9a-f]{6} set:', text or ''):
        return out
    for args in runs(cmd, 'claude-wait'):
        if not args or args[0] not in ('pr', 'at', 'email-reply', 'check-script', 'check-prompt'):
            continue
        out.append(key('wait', args[0], at, how='set'))
        if args[0] != 'email-reply':
            continue
        box = (opt(args, '--mailbox') or me_).lower()
        said = said_of(opt(args, '--what'), opt(args, '--why'))
        n0 = len(out)
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
        for k in out[n0:]:
            if said:
                k['said'] = 'An email reply wait: ' + said
    return out


def window_facts(cmd, text, at, st, me_, own):
    """claude-window commands: the page each is on, and a send on it: a web form that says it got the message, a
    Google Chat post, a mail sent in Gmail, a supplier's messenger."""
    out = []
    cw = runs(cmd, 'claude-window')
    if not cw:
        return out  # the command only names claude-window (a test, a script, a file it writes): no page, no send
    page = st.get('page', '')
    for u in [a[1] for a in cw if len(a) > 1 and a[0] == 'go' and re.match(r'https?://', a[1])]:
        if u != page:
            st.pop('before', None)  # a new page: what it says before a click starts again
            st.pop('said', None)
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
    codes = [a[1] for a in cw if len(a) > 1 and a[0] == 'js']
    # code the shell fills in ("$(cat x.js)", "$J"): the code is elsewhere in the command, often in a file it writes
    js = ' '.join(codes) if not any(re.search(r'\$[({A-Za-z_]|`', c) for c in codes) else cmd
    typed = [a for a in addrs(cmd) if site(a) in own] if js else []
    if typed:
        st['typed'] = [st.get('site', ''), typed[-1]]
    words = prose(js) if js else ''
    if words:
        st['said'] = words  # the text typed on this page, for the send that follows
    said = st.get('said', '')
    clicked = bool(js) and bool(CLICK.search(js)) and bool(SEND.search(js))
    if clicked and h.endswith('chat.google.com') or (clicked and h == 'mail.google.com' and '/chat' in page):
        m = CHAT_SPACE.search(page)
        if m and re.search(r'(?i)send', js):
            out.append(key('chat', 'spaces/' + m.group(1), at, '', 'post', said=said))
            st.pop('said', None)
        return out
    if clicked and h == 'mail.google.com':
        if re.search(r'(?i)\bsend\b', js):
            for a in addrs(cmd):
                if a != me_ and site(a) != 'google.com':
                    out += [dict(k, said=said) if said else k for k in mail_keys(a, at, me_, 'email', own)]
            st.pop('said', None)
        return out
    if clicked and s in MESSENGERS and re.search(r'(?i)send', js):
        out.append(key('domain', s, at, '*', 'messenger', said=said))
        st.pop('said', None)
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
        out.append(key('domain', target, at, box, 'form', said=said and 'A web form: ' + said))
        st.pop('armed', None)
    else:
        armed['n'] = armed.get('n', 4) - 1
        if armed['n'] <= 0:
            st.pop('armed', None)
    return out


CODE = re.compile(r'=>|document\.|querySelector|\bfunction\b|\breturn\b|[{}]|\]\s*\[|getAttribute|innerText|'
                  r'\.click\(|\b(?:const|let|var) \w|\$\(')


def literals(code, depth=0):
    """The text of each string in code: in quotes or back quotes, and again in a string that is code itself (the
    shell's quotes around a page's code)."""
    out, i, n = [], 0, len(code)
    while i < n:
        q = code[i]
        if q not in '"\'`':
            i += 1
            continue
        j, buf = i + 1, []
        while j < n and code[j] != q:
            if code[j] == '\\' and j + 1 < n:
                buf.append({'n': '\n', 't': ' '}.get(code[j + 1], code[j + 1]))
                j += 2
            else:
                buf.append(code[j])
                j += 1
        s = ''.join(buf)
        out.append(s)
        if depth < 2 and CODE.search(s):
            out += literals(s, depth + 1)
        i = j + 1
    return out


def prose(code):
    """The longest text in a page's code that reads as words, not code: what the session typed (a Chat post, a mail,
    a form's message). '' when there is none."""
    best = ''
    for s in literals(code or ''):
        s = re.sub(r'\s+', ' ', s).strip()
        if len(s) > len(best) and len(s) >= 30 and s.count(' ') >= 4 and not CODE.search(s) and \
                sum(c.isalpha() for c in s) >= len(s) / 2:
            best = s
    return best[:SAID]


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
            threads = list(dict.fromkeys((k.get('threads') or []) + (new.get('threads') or [])))[-20:]
            if threads:
                k['threads'] = new['threads'] = threads
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


def archived_ids(state):
    """The sessions the person archived that wait on no one: the Archived page's list (archived.json, which
    effort-hook.py archived() writes from the account's list of sessions: every 15 seconds where this Mac's server
    runs, else every 10 minutes; a session with an open wait is not on it). A session the account's list of open
    sessions (app_list, read each minute) shows, read after that file, is back in the person's list: it is not one."""
    try:
        with open(ARCHIVED) as f:
            a = json.load(f)
    except (OSError, ValueError):
        return set()
    ids = {x.get('cse') for x in a.get('items') or [] if x.get('cse')}
    shown = state.get('app_list') or {}
    if ids and shown.get('at', 0) > a.get('at', 0):
        ids -= {x.get('id') for x in shown.get('sessions') or []}
    return ids


def not_watched(S, cse, title, now):
    """An archived session with no open wait: the person stopped it, and nothing waits, so the watch reads nothing for
    it and brings it back for nothing. Logged once for each time it is archived, when it had something to watch;
    messages it had not yet come back for are dropped, and the log names them. Its entry stays (marked `archived`),
    so a message it was told about never goes to another session, and its watch starts again from the time it is back
    in the person's list."""
    e = S.get(cse)
    if not e or e.get('archived'):
        return
    e['archived'] = now
    title = title or e.get('title') or cse[-6:]
    others = [m for m in e.get('pending') or [] if not m.get('own')]
    if others:
        log('%s "%s" not told of %d new message%s: archived with no wait: %s' % (
            cse[:12], title, len(others), '' if len(others) == 1 else 's',
            '; '.join('%s "%s"' % (m.get('from') or 'Chat', (m.get('subject') or m.get('text') or '')[:60])
                      for m in others[:3])))
    elif [k for k in e.get('keys') or [] if k['k'] != 'wait']:
        log('%s "%s" not watched: archived with no wait' % (cse[:12], title))
    e['pending'] = []


def watched(W, wm, now, me_, own):
    """The sessions the watch covers now, with their keys up to date: {cse: entry}. A session with an open wait,
    or a last turn in the last WATCH_DAYS and not archived (archived_ids()); its records must be on this Mac. One
    that leaves is forgotten."""
    state = wm.peek()
    gone = archived_ids(state)
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
        if not mine and cse in gone:
            not_watched(S, cse, i.get('title'), now)
            continue
        e = S.setdefault(cse, {'start': now, 'files': {}, 'keys': [], 'told': [], 'pending': []})
        if e.pop('archived', None):  # back in the person's list, or archived with a wait: watched from now on
            e['start'] = max(e.get('start', 0), now)
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


def own_queries(threads, since, me_):
    """The searches for the person's own replies in a mailbox's watched threads ({thread id: subject}): from the
    person, by each thread's subject (the match is by the thread's id), MAX_TERMS a search; never a draft."""
    t = list(dict.fromkeys('subject:"%s"' % clean_subject(s) for s in (threads or {}).values() if clean_subject(s)))
    if not me_ or not t:
        return []
    return ['after:%d from:%s -in:drafts {%s}' % (since, me_, ' '.join(t[i:i + MAX_TERMS])) for i in range(0, len(t), MAX_TERMS)]


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
            ident = IDENT.get(t)
            if name == WR + t and (not ident or str(inp.get(ident)) == str(a[ident])) and not err:
                got.setdefault(i, []).append(res)
                break
    return got, why


IDENT = {'gmail_search': 'query', 'gchat_search_messages': 'space_id', 'asana_get_task_stories': 'task_gid'}


def mail_of(e):
    return {'id': e.get('id', ''), 'thread_id': e.get('thread_id', ''), 'from': e.get('from', ''),
            'to': e.get('to', ''), 'subject': e.get('subject', ''), 'at': mail_time(e.get('date')),
            'snippet': (e.get('snippet') or '')[:300], 'gid': asana_gid(e.get('body') or e.get('snippet'))}


def chat_of(space, m):
    return {'id': m.get('name', ''), 'space': space, 'from': m.get('sender', ''), 'text': (m.get('text') or '')[:600],
            'at': stamp(m.get('createTime'))}


def asana_of(gid, c):
    """A comment on an Asana task, from asana_get_task_stories: only the person's own count (own_asana())."""
    return {'id': str(c.get('comment_id') or c.get('gid') or ''), 'task': gid, 'from': c.get('author') or '',
            'text': (c.get('text') or '')[:600], 'at': stamp(c.get('created_at'))}


# --- matching -----------------------------------------------------------------------------------------------------

def mail_match(msg, box, e, me_):
    """(strength, contact time, key) of a session's closest contact for a mail, or None: 4 its Asana task and 3 a
    thread it used (narrow), 2 an address and 1 a domain it wrote to (broad)."""
    a = sender(msg.get('from'))
    if not a or a == me_ or a == box or msg['at'] <= e.get('floor', 0):
        return None
    d = a.split('@')[1]
    best = None
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
            best = (s, k['at'], k)
    return best


def chat_match(msg, e):
    """(strength, contact time, key) of a session's post in a Chat message's space, or None: 3 for a reply in the
    thread of its post (narrow), 1 for any other post in the space (broad)."""
    if msg['at'] <= e.get('floor', 0):
        return None
    thread, reply = chat_thread(msg.get('id'))
    best = None
    for k in e['keys']:
        if k['k'] == 'chat' and k['v'] == msg['space'] and k.get('first', k['at']) < msg['at']:
            s = 3 if reply and thread in (k.get('threads') or []) else 1
            if best is None or (s, k['at']) > best[:2]:
                best = (s, k['at'], k)
    return best


def sessions_for(msg, box, sess, me_):
    """The sessions a message goes to, [(strength, contact time, cse, key)]: the closest narrow match alone (a task
    before a thread, then the newest contact), else every session with a broad match, newest contact first; each
    of those is checked before it comes back."""
    found = []
    for cse, e in sess.items():
        b = chat_match(msg, e) if msg['kind'] == 'chat' else mail_match(msg, box, e, me_)
        if b:
            found.append((b[0], b[1], cse, b[2]))
    narrow = [f for f in found if f[0] >= NARROW]
    if narrow:
        return [max(narrow, key=lambda f: f[:2])]
    return sorted(found, key=lambda f: -f[1])


def learn_post(e, msg):
    """The session's own post came back in a read: keep its thread (a reply in it is narrow) and its text (what the
    check of a broad match reads) on the session's key for that space."""
    thread, _ = chat_thread(msg.get('id'))
    for k in e['keys']:
        if k['k'] == 'chat' and k['v'] == msg.get('space'):
            if thread and thread not in (k.get('threads') or []):
                k['threads'] = ((k.get('threads') or []) + [thread])[-20:]
            if msg.get('text') and msg['at'] >= k.get('said_at', 0):
                k['said'], k['said_at'] = said_of('', msg['text']), msg['at']


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


# --- the person's own replies -------------------------------------------------------------------------------------

def short(subject, n=60):
    """A thread's subject as a note and the log say it: no Re: or Fwd:, no double quotes."""
    s = re.sub(r'(?i)^((re|fwd?|aw|回复|答复|转发)\s*[:：]\s*)+', '', (subject or '').strip())
    return s.replace('"', "'")[:n].strip() or 'no subject'


def watch_places(e, waits, me_):
    """The places a session watches or waits on, where the person's own reply counts: (mail {(mailbox, thread id):
    subject}, chat {space: the threads of its posts}, asana {task gid}). Its email threads (drafted in, read, an email
    reply wait's), the threads the Kit brought it back for (`back`, add_back()) and the threads of its open email reply
    waits; the Chat spaces it posted in; the Asana tasks it commented on or made."""
    mail, chat, asana = {}, {}, set()
    for k in e.get('keys') or []:
        if k['k'] == 'thread' and k.get('box') not in (None, '', '*'):
            mail[(k['box'], k['v'])] = mail.get((k['box'], k['v'])) or k.get('subject') or ''
        elif k['k'] == 'chat':
            chat[k['v']] = list(dict.fromkeys((chat.get(k['v']) or []) + (k.get('threads') or [])))
        elif k['k'] == 'asana':
            asana.add(k['v'])
    for rec in e.get('back') or []:
        for box, tid, subject in rec.get('mail') or []:
            if box and tid:
                mail[(box, tid)] = mail.get((box, tid)) or subject or ''
    for w in waits:
        if w.get('kind') == 'email-reply' and w.get('target'):
            box = (w.get('mailbox') or me_ or '').lower()
            if box:
                mail[(box, w['target'])] = mail.get((box, w['target'])) or w.get('subject') or ''
    return mail, chat, asana


def places_of(m):
    """The places of a message the Kit brings a session back for: its email thread (in its mailbox), its Asana task
    (an Asana notice), its Chat space. A message the session keeps in the Kit in that turn is about them (about())."""
    out = []
    if m['kind'] == 'mail':
        if m.get('thread_id'):
            out.append('mail:%s:%s' % (m.get('box') or '', m['thread_id']))
        if m.get('gid'):
            out.append('asana:' + m['gid'])
    elif m['kind'] == 'chat' and m.get('space'):
        out.append('chat:' + m['space'])
    elif m['kind'] == 'asana' and m.get('task'):
        out.append('asana:' + m['task'])
    return out


def add_back(e, msgs, now, what=''):
    """The Kit brought the session back: for these messages (the reply watch), for a wait (note_back()), or with a note
    of the person's own replies (no messages). Kept on the session as `back` (the last BACK_MAX, KEY_DAYS at most),
    with the places of the messages: a message it keeps in the Kit in that turn is about them (about()), and the
    person's own reply in such an email thread counts (watch_places()). A bring-back with no place is kept too, so a
    message kept in its turn is about nothing older."""
    places = list(dict.fromkeys(p for m in msgs for p in places_of(m)))
    mail = [[m.get('box') or '', m['thread_id'], m.get('subject') or ''] for m in msgs
            if m['kind'] == 'mail' and m.get('thread_id')]
    first = msgs[0] if msgs else {}
    what = what or ('the email thread "%s"' % short(first.get('subject')) if first.get('kind') == 'mail'
                    else 'a Chat space it posted in' if first.get('kind') == 'chat'
                    else 'its Asana task' if first.get('kind') == 'asana' else '')
    e['back'] = [r for r in e.get('back') or [] if now - r.get('at', 0) < KEY_DAYS * 86400][-(BACK_MAX - 1):] + [
        {'at': now, 'places': places, 'mail': mail, 'what': what}]


def note_back(cse, tp, box='', threads=(), subject='', now=None):
    """A wait brought the session back (wait.py): its email thread(s) in `box`, kept as add_back() keeps them; a wait
    with no thread (a pull request, a time) is kept as a bring-back with no place."""
    if not cse:
        return
    now = now or time.time()
    W = peek()
    e = W.setdefault('sessions', {}).setdefault(cse, {'start': now, 'files': {}, 'keys': [], 'told': [], 'pending': []})
    if tp and not e.get('transcript'):
        e['transcript'] = tp
    add_back(e, [{'kind': 'mail', 'box': box, 'thread_id': t, 'subject': subject}
                 for t in dict.fromkeys(threads) if t and box], now, what='' if box and any(threads) else 'a wait')
    save(W)


def tail(tp, size=3000000):
    """The last whole lines of a session's record (bytes)."""
    try:
        with open(tp, 'rb') as f:
            f.seek(0, 2)
            end = f.tell()
            f.seek(max(0, end - size))
            lines = f.read().split(b'\n')
    except OSError:
        return []
    return lines[1:] if end > size else lines


def last_turn(tp):
    """When the session's last turn ended, near enough: the time of the last line of its record that has one. 0 when
    none is found."""
    for raw in reversed(tail(tp, 400000)):
        if b'"timestamp"' not in raw:
            continue
        try:
            x = json.loads(raw)
        except ValueError:
            continue
        t = stamp(x.get('timestamp')) if isinstance(x, dict) else 0
        if t:
            return t
    return 0


def last_prompt(tp):
    """(time, text) of the last prompt in the session's record: the person's, or the Kit's own ("[Sttark Claude Kit]
    ..."); (0, '') when the tail has none."""
    for raw in reversed(tail(tp)):
        if not USER.search(raw, 0, 800) or b'tool_result' in raw:
            continue
        try:
            x = json.loads(raw)
        except ValueError:
            continue
        if isinstance(x, dict) and person_prompt(x):
            c = (x.get('message') or {}).get('content')
            return stamp(x.get('timestamp')), (text_of(c) if isinstance(c, list) else c) or ''
    return 0, ''


def about(cse, now=None):
    """What a message the session keeps in the Kit now is about (notify.py keep_in_kit()): the places of the Kit's
    latest bring-back of it, when its turn now is that bring-back's (its last prompt is the Kit's own, typed within 15
    minutes of it, in the last 6 hours). None otherwise: a turn the person started is about what they asked, and one
    the Kit started for a wait with no thread is about no place."""
    now = now or time.time()
    e = (peek().get('sessions') or {}).get(cse) or {}
    recs = e.get('back') or []
    if not recs or not recs[-1].get('places') or not e.get('transcript'):
        return None
    rec = recs[-1]
    at, text = last_prompt(e['transcript'])
    if not text.lstrip().startswith('[Sttark Claude Kit]') or not rec['at'] - 120 <= at <= rec['at'] + 900 \
            or now - rec['at'] > 6 * 3600:
        return None
    return {'at': rec['at'], 'places': rec['places'], 'what': rec.get('what') or ''}


def done_own(e, mid):
    return mid in (e.get('own') or []) or any(m.get('id') == mid and m.get('own') for m in e.get('pending') or [])


def own_mail(m, box, sess, places):
    """The sessions a mail the person sent is a reply for, [(cse, item)]: each that watches or waits on its thread."""
    out = []
    for cse, e in sess.items():
        key = (box, m.get('thread_id'))
        if key not in places[cse][0] or m['at'] <= e.get('floor', 0) or done_own(e, m['id']):
            continue
        out.append((cse, dict(m, box=box, own=True, place='mail:%s:%s' % key,
                              where='in the email thread "%s"' % short(places[cse][0][key] or m.get('subject')))))
    return out


def own_chat(m, sess, places):
    """The sessions a Chat post of the person's own counts for, [(cse, item)]: each that posted in its space. A reply
    in the thread of the session's post is narrow; any other post in the space is broad: checked first (check_broad())."""
    thread, reply = chat_thread(m.get('id'))
    out = []
    for cse, e in sess.items():
        threads = places[cse][1].get(m['space'])
        if threads is None or m['at'] <= e.get('floor', 0) or done_own(e, m['id']):
            continue
        narrow = reply and thread in threads
        one = dict(m, own=True, place='chat:' + m['space'], why='you posted in this Chat space',
                   where='in the thread of its Chat post' if narrow else 'in a Chat space it posted in')
        if not narrow:
            one.update(broad=True, said=next((k.get('said', '') for k in e['keys'] if k['k'] == 'chat' and k['v'] == m['space']), ''))
        out.append((cse, one))
    return out


def own_asana(m, sess, places):
    """The sessions an Asana comment of the person's own counts for, [(cse, item)]: each that commented on the task
    or made it."""
    return [(cse, dict(m, own=True, place='asana:' + m['task'], where='on its Asana task %s' % m['task']))
            for cse, e in sess.items() if m['task'] in places[cse][2] and m['at'] > e.get('floor', 0) and not done_own(e, m['id'])]


QUOTE = re.compile(r'\s(?:On (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|\d).{0,200}? wrote:|-{2,} ?(?:Original|Forwarded) '
                   r'[Mm]essage|From: \S)')


def own_words(m, n=OWN_SAID):
    """The first lines of the person's own reply: its words up to the quote of the message it answers."""
    t = m.get('text') if m['kind'] in ('chat', 'asana') else m.get('snippet')
    t = re.sub(r'\s+', ' ', html.unescape(t or '')).strip()
    return QUOTE.split(' ' + t)[0].strip()[:n]


def own_line(m):
    """One reply of the person's, for the session's note: where, when, the first lines, and how to read it."""
    how = ''
    if m['kind'] == 'mail':
        how = (' (to read it: claude-mail read %s %s)' % (m['box'], m['id']) if direct_read(m.get('box'))
               else " (to read it: Workrouter's gmail_read_message, message_id %s)" % m['id'])
    elif m['kind'] == 'asana':
        how = ' (the task: https://app.asana.com/0/0/%s)' % m['task']
    return '- %s, %s: "%s"%s' % (m['where'][0].upper() + m['where'][1:],
                                 time.strftime('%a %b %-d %-I:%M %p', time.localtime(m['at'])),
                                 own_words(m) or '(no words)', how)


def own_note(mine, wm, wake=False):
    """The session's note of the person's own replies: where, when and the first lines of each, the message kept in
    the Kit and the wait they touch, and that it marks its item handled with no message to anyone."""
    lines = ['[Sttark Claude Kit] The person replied themselves, after your last turn, in a place this session '
             'watches:'] + [own_line(m) for m in mine[:6]]
    if len(mine) > 6:
        lines.append('- And %d more.' % (len(mine) - 6))
    kept = [k for m in mine for k in m.get('kept') or []]
    if kept:
        lines.append('The Kit marked the message you kept in the Kit app about it as handled, so it shows "You replied '
                     '%s": %s.' % (wm.clock(mine[0]['at']), '; '.join('"%s"' % s for _, s in kept[:3])))
    waits = list(dict.fromkeys(w for m in mine for w, _ in m.get('waits') or []))
    if waits:
        lines.append("Your email reply wait %s stays open: the person's own reply does not end it, so it still waits "
                     "for the other person. Cancel it (claude-wait --cancel <id>) only if their reply is no longer "
                     "needed." % ', '.join(waits))
    lines.append('If an item of yours waited on this reply (a question to the person, a draft for them to send, a '
                 'next step), mark it handled in your notes and your status now. This needs no message: do not send '
                 'claude-notify for it, and do not ask the person about it.' + (
                     ' Then end the turn with one line.' if wake else ''))
    return '\n'.join(lines)


def mark_waits(wm, cse, m, dry=False):
    """The session's open email reply waits on the thread the person replied in: each stays open (its check still
    waits for the other person) and gets `replied` = {at, where, id}, so its row says "You replied <time>". Returns
    [(wait id, first)]: first when it had no reply of the person's before."""
    def fits(w):
        return (w.get('cse') == cse and w.get('kind') == 'email-reply' and w.get('stage') != 'back'
                and w.get('target') and w.get('target') == m.get('thread_id')
                and (w.get('mailbox') or me()).lower() == m.get('box') and m['at'] > (w.get('set_at') or 0)
                and m['at'] > ((w.get('replied') or {}).get('at') or 0))
    if m['kind'] != 'mail' or not any(fits(w) for w in (wm.peek().get('waits') or {}).values()):
        return []
    got = []

    def edit(s):
        for wid, w in (s.get('waits') or {}).items():
            if fits(w):
                got.append((wid, not w.get('replied')))
                if not dry:
                    w['replied'] = {'at': m['at'], 'where': re.sub(r'^(in|on) ', '', m['where']), 'id': m['id']}
    wm.change(edit)
    return got


def prepare_own(wm, cse, e, mine):
    """The Kit's part of the person's own replies, once for each (kept on it, so a retry does none of it twice): the
    session's messages kept in the Kit about that place get "You replied <time>" (notify.py mark_replied()); its email
    reply wait on that thread stays open and gets `replied` (mark_waits()); the session is told only when the reply
    came after its last turn (`tell`), and brought back for it only when such a kept message or wait depends on it
    (`wake`)."""
    end = None
    for m in mine:
        if m.get('done'):
            continue
        try:
            kept = load('notify').mark_replied(m['place'], m['at'], re.sub(r'^(in|on) ', '', m['where']), m['id'],
                                               cse=cse, dry=DRY)
        except Exception as x:
            kept = []
            log('%s could not mark its messages kept in the Kit: %s: %s' % (cse[:12], type(x).__name__, str(x)[:160]))
        try:
            waits = mark_waits(wm, cse, m, dry=DRY)
        except Exception as x:
            waits = []
            log('%s could not mark its waits: %s: %s' % (cse[:12], type(x).__name__, str(x)[:160]))
        if end is None:
            end = last_turn(e['transcript'])
        m.update(done=True, kept=kept, waits=waits, tell=m['at'] > end,
                 wake=m['at'] > end and bool(kept or any(first for _, first in waits)),
                 why_wake='a message kept in the Kit depends on it' if kept else 'its email reply wait depends on it')


def own_log(cse, title, m, wm, then):
    """One line for each reply of the person's (the Events page has a row for each): where, when, the first words,
    and what the Kit did."""
    did = ['its message in the Kit "%s" now shows You replied %s' % (s[:60], wm.clock(m['at'])) for _, s in m.get('kept') or []]
    did += ['its wait %s shows You replied %s and still waits for the other person' % (w, wm.clock(m['at']))
            for w, _ in m.get('waits') or []]
    did.append(then if m.get('tell') else 'not told: it had a turn since your reply')
    log('replied %s "%s" %s, %s: %s | %s' % (cse[:12], title, m['where'], wm.clock(m['at']),
                                            own_words(m, 80).replace('|', '/') or '-', '; '.join(did)))


def queue_note(wm, cse, title, text, mine):
    """A note of the person's own replies for the session's next prompt (effort-hook.py take_replied()), in the
    state file under its lock: `replied` on the session."""
    def edit(s):
        x = s.setdefault('sessions', {}).setdefault(cse, {})
        x['replied'] = (x.get('replied') or [])[-9:] + [{'at': time.time(), 'ids': [m['id'] for m in mine],
                                                          'where': mine[0]['where'], 'title': title, 'text': text}]
    wm.change(edit)


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
    and brings each session back once with what came for it. The person's own replies in a session's places come in
    the same reads (own_queries(), Chat posts, an Asana task's comments) and go to each session that watches the place
    (deliver_one() tells it once)."""
    wm = wm or load('wait')
    now = now or time.time()
    me_ = me()
    own = own_sites(me_)
    W = peek()
    sess = watched(W, wm, now, me_, own)
    waits_of = {}
    for w in (wm.peek().get('waits') or {}).values():
        if w.get('cse') and w.get('stage') != 'back':
            waits_of.setdefault(w['cse'], []).append(w)
    places = {cse: watch_places(e, waits_of.get(cse, []), me_) for cse, e in sess.items()}
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
    mine_box = {}  # the threads of each mailbox where the person's own reply counts: {box: {thread id: subject}}
    for cse in sess:
        for (b, tid), subject in places[cse][0].items():
            t = mine_box.setdefault(b, {})
            t[tid] = t.get(tid) or subject
    cache = {}
    found = []
    model_calls, model_boxes = [], {}
    hour = time.localtime(now).tm_hour
    for box in list(by_box) + [b for b in mine_box if b not in by_box]:
        keys = by_box.get(box) or []
        if not keys and not wm.direct(box) and box != me_:
            continue  # only the person's own replies, in a mailbox this Mac cannot read: nothing to say
        b = boxes.setdefault(box, {})
        floor = min([e['floor'] for e in sess.values() if any(k in e['keys'] for k in keys)] or [now])
        since = int(max(b['read_at'] - OVERLAP, now - BACK_DAYS * 86400) if b.get('read_at') else
                    max(floor, now - BACK_DAYS * 86400))
        qs = queries(keys, since) + own_queries(mine_box.get(box), since, me_)
        if not qs:
            continue
        if wm.direct(box):
            if now - max(b.get('read_at', 0), b.get('tried_at', 0)) < MAIL_EVERY:
                continue
            b['tried_at'] = now
            try:
                msgs = read_direct(box, qs, load('mail'))
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
            for q in qs:
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
    # The person's own comments on an Asana task a session touched: Asana mails no one about their own comment, so the
    # Workrouter run reads the task's latest comments when it runs for the mailbox or Chat (never a run of its own).
    tasks = {}
    for e in sess.values():
        for k in e['keys']:
            if k['k'] == 'asana' and now - k['at'] < TASK_DAYS * 86400:
                tasks[k['v']] = max(tasks.get(k['v'], 0), k['at'])
    asana = W.setdefault('asana', {})
    asince = 0
    if model_calls and tasks:
        asince = asana['read_at'] - OVERLAP if asana.get('read_at') else \
            max(min([e['floor'] for e in sess.values() if any(k['k'] == 'asana' for k in e['keys'])] or [now]),
                now - BACK_DAYS * 86400)
        if not asana.get('me') or now - asana.get('me_at', 0) > 86400:
            model_boxes[len(model_calls)] = 'asana'
            model_calls.append(('asana_whoami', {}))
        for g in sorted(tasks, key=lambda x: -tasks[x])[:MAX_TASKS]:
            model_boxes[len(model_calls)] = 'asana'
            model_calls.append(('asana_get_task_stories', {'task_gid': g, 'limit': 5}))

    def rec_of(target):
        return chat if target.startswith('spaces/') else asana if target == 'asana' else boxes.setdefault(target, {})
    if model_calls and not held():
        for target in set(model_boxes.values()):
            rec_of(target)['tried_at'] = now
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
                elif t == 'gchat_search_messages':
                    found += [(target, dict(chat_of(target, m), kind='chat')) for m in r.get('messages') or []]
                elif t == 'asana_whoami':
                    if r.get('name'):
                        asana.update(me=r['name'], me_at=now)
                else:
                    found += [('', dict(asana_of(a['task_gid'], c), kind='asana')) for c in r.get('comments') or []
                              if isinstance(c, dict) and stamp(c.get('created_at')) > asince]
        for target, ok in ok_boxes.items():
            rec = rec_of(target)
            if ok:
                rec.update(read_at=now, via='model')
                rec.pop('failing', None)
            else:
                fail(rec, target, RuntimeError(why or 'Haiku did not make the call'), now)
    save(W)  # what was read, and when, before anything that could fail: a read is never made again for nothing
    picked, own_picked = {}, {}
    taken = set()  # a message one session got (or was told about) never goes to another
    for x in (W.get('sessions') or {}).values():
        taken.update(x.get('told') or [])
        taken.update(x.get('skipped') or [])
        taken.update(m.get('id') for m in x.get('pending') or [] if not m.get('own'))
    posts = set()  # a session's own posts: their sender is the person in Chat, whose other posts are their own replies
    for box, m in found:
        if m['kind'] == 'chat' and m.get('id'):
            mine = [e for e in sess.values() if any(k['k'] == 'chat' and k['v'] == m['space'] for k in e['keys'])
                    and own_post(e, m, cache)]
            for e in mine:
                learn_post(e, m)
            if mine:
                posts.add(m['id'])
                if m.get('from'):
                    chat['me'] = m['from']

    def own_of(box, m):
        """The sessions the person's own message counts for: [(cse, item)], or None when it is not the person's."""
        if m['kind'] == 'mail':
            return own_mail(m, box, sess, places) if me_ and sender(m.get('from')) == me_ else None
        if m['kind'] == 'chat':
            return own_chat(m, sess, places) if chat.get('me') and m.get('from') == chat['me'] else None
        if asana.get('me') and m.get('from') == asana['me'] and not any(
                own_post(e, m, cache) for e in sess.values()
                if any(k['k'] == 'asana' and k['v'] == m['task'] for k in e['keys'])):
            return own_asana(m, sess, places)  # not a comment a session made, as the person, through Workrouter
        return []
    for box, m in found:
        try:
            if not m.get('id') or not m.get('at') or m['id'] in posts:
                continue  # a session's own post
            mine = own_of(box, m)
            if mine is not None:  # the person's own: to each session that watches the place, and to no one else
                for cse, one in mine:
                    own_picked.setdefault(cse, {})[m['id']] = one
                continue
            if m['id'] in taken:
                continue
            for strength, _, cse, k in sessions_for(m, box, sess, me_):
                if seen(sess[cse], m, cache):
                    continue
                one = dict(m, box=box if m['kind'] == 'mail' else '', why='it is a reply in the thread of your post in '
                           'this Chat space' if k['k'] == 'chat' and strength >= NARROW else why_of(k))
                if strength < NARROW:  # broad: checked before it brings the session back
                    one.update(broad=True, said=k.get('said', ''))
                picked.setdefault(cse, {})[m['id']] = one
            taken.add(m['id'])
        except Exception as x:  # one odd message never stops the others
            log('could not match a message (%s): %s: %s' % (m.get('id', '?'), type(x).__name__, str(x)[:160]))
    for cse, ms in list(picked.items()) + list(own_picked.items()):
        sess[cse].setdefault('pending', []).extend(sorted(ms.values(), key=lambda x: x['at']))
    for box, b in boxes.items():
        n = sum(1 for bx, m in found if bx == box)
        if b.get('read_at') == now and (n or now - b.get('logged_at', 0) >= 3600):
            b['logged_at'] = now
            mine = len({m['id'] for c in own_picked.values() for m in c.values() if m.get('box') == box})
            log('%s read (%s): %d new message%s, %d for a session%s' % (
                box, 'no model' if b.get('via') == 'mail' else 'Haiku through Workrouter', n, '' if n == 1 else 's',
                sum(1 for c in picked.values() for m in c.values() if m.get('box') == box),
                ', %d of your own replies where a session watches' % mine if mine else ''))
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
    BUDGET[0] = CHECKS_A_MINUTE
    for cse, e in sess.items():
        try:
            deliver_one(wm, cse, e, cache, now)
        except Exception as x:
            log('%s could not come back: %s: %s' % (cse[:12], type(x).__name__, str(x)[:160]))
        save(W)


def first_prompt(e):
    """The person's first prompt in the session, read once from the start of its transcript and kept in watch.json."""
    if e.get('first_prompt') is None:
        text = ''
        try:
            with open(e['transcript'], 'rb') as f:
                for i, raw in enumerate(f):
                    if i > 5000:
                        break
                    if not USER.search(raw, 0, 800) or b'tool_result' in raw:
                        continue
                    try:
                        x = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(x, dict) and person_prompt(x):
                        c = (x.get('message') or {}).get('content')
                        text = text_of(c) if isinstance(c, list) else c
                        break
        except OSError:
            return ''
        e['first_prompt'] = re.sub(r'\s+', ' ', NOTE.sub('', text or '')).strip()[:SAID]
    return e['first_prompt']


NOTE = re.compile(r'<(system-reminder|local-command-[a-z-]+|command-[a-z-]+)>.*?</\1>', re.S)


def gist(m, n=80):
    """The first words of a message, for the log and the Events page."""
    t = m.get('text') if m['kind'] == 'chat' else ' '.join(x for x in (m.get('subject'), m.get('snippet')) if x)
    return re.sub(r'\s+', ' ', t or '').strip()[:n]


def question(e, m):
    """What the check of a broad match reads: the session, what it sent on the channel, and the new message."""
    how = re.sub(r'\byour\b', "the session's", re.sub(r'\byou\b', 'the session', m.get('why') or ''))
    if m['kind'] == 'chat':
        new = 'A post in the Google Chat space or direct message, from %s:\n%s' % (
            'the person themselves (the one the session works for)' if m.get('own') else m.get('from') or 'someone',
            m.get('text', ''))
    else:
        new = 'Mail from %s, subject "%s":\n%s' % (m.get('from', ''), m.get('subject', ''), m.get('snippet', ''))
    return '\n'.join([
        'Session name: ' + (e.get('title') or '(none)'),
        "The person's first prompt in the session: " + (first_prompt(e) or '(not on record)'),
        'The channel: %s.' % how,
        'What the session sent on it: ' + (m.get('said') or '(its text is not on record)'),
        '', 'The new message. ' + new, '',
        "Is the new message about this session's work?"])


def ask(text, claude):
    """(about its work, why) from one Haiku call (MODEL, no tools, hooks off, outside any session, as the Kit's other
    checks call); raises with why when there is no clear YES or NO. STTARK_WATCH_MODEL stands in for it in tests."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    cmd = [STUB] if STUB else [claude, '-p', '--model', MODEL, '--effort', 'low', '--no-session-persistence',
                               '--strict-mcp-config', '--tools', '', '--settings', '{"disableAllHooks":true}',
                               '--system-prompt', JUDGE]
    r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=JUDGE_TIMEOUT, env=env, cwd='/tmp')
    out = (r.stdout or '').strip()
    if r.returncode and not out:
        raise RuntimeError('exit %d: %s' % (r.returncode, re.sub(r'\s+', ' ', r.stderr or '').strip()[:160]))
    a = re.match(r'[\W_]*(YES|NO)\b[\s\W]*(.*)', out, re.I | re.S)
    if not a:
        raise RuntimeError('no YES or NO in the answer: %s' % re.sub(r'\s+', ' ', out)[:80])
    return a.group(1).upper() == 'YES', re.sub(r'\s+', ' ', a.group(2)).strip()[:200]


def check_broad(wm, cse, e, title, m):
    """Asks whether a broad match is about the session's work, and keeps the answer on the message (verdict): yes,
    no, or error (the call failed: it comes back all the same, so nothing is lost)."""
    who = 'you in Chat' if m.get('own') else '%s in Chat' % (m.get('from') or 'someone') if m['kind'] == 'chat' \
        else m.get('from') or 'someone'
    try:
        yes, why = ask(question(e, m), getattr(wm, 'CLAUDE', ''))
    except Exception as x:
        m['verdict'] = 'error'
        log('%s "%s" could not check a message (%s: %s); it comes back for it all the same: %s: %s' % (
            cse[:12], title, type(x).__name__, str(x)[:120], who, gist(m)))
        return
    m['verdict'] = 'yes' if yes else 'no'
    if yes:
        log('checked %s "%s" %s: about this session\'s work: %s | %s' % (cse[:12], title, who, gist(m), why))
    else:
        log('skip %s "%s" %s: not about this session\'s work: %s | %s' % (cse[:12], title, who, gist(m), why))


def deliver_one(wm, cse, e, cache, now):
    """One session's new messages: bring it back with them, or keep them for its next minute. The person's own
    replies (`own`) are told once, with no alert: with the messages it comes back for, else a note for its next prompt,
    or a bring-back with the note when a message kept in the Kit or an email reply wait depends on it."""
    pend = [m for m in e.get('pending') or []
            if (m['id'] not in (e.get('own') or []) if m.get('own') else not seen(e, m, cache))]
    e['pending'] = pend
    if not pend:
        return
    title = e.get('title') or cse[-6:]
    todo = [m for m in pend if m.get('broad') and not m.get('verdict')]
    if todo:
        if held():  # the check is a model call: it waits for the usage hold to end, and the messages with it
            if now - e.get('held_said', 0) > 900:
                log('%s "%s" waits for the usage hold to end before the check of %d new message%s'
                    % (cse[:12], title, len(todo), '' if len(todo) == 1 else 's'))
                e['held_said'] = now
            return
        for m in todo:
            if BUDGET[0] <= 0:
                break
            BUDGET[0] -= 1
            check_broad(wm, cse, e, title, m)
        if any(not m.get('verdict') for m in todo):
            return  # more checks than one minute holds: the rest next minute, then the session comes back once
        # skipped, not told: a wait of the session's own still sees the message, and decides for itself
        e['skipped'] = (e.get('skipped', []) + [m['id'] for m in pend if m.get('verdict') == 'no' and not m.get('own')])[-500:]
        e['own'] = (e.get('own', []) + [m['id'] for m in pend if m.get('verdict') == 'no' and m.get('own')])[-500:]
        e['pending'] = pend = [m for m in pend if m.get('verdict') != 'no']
        if not pend:
            return
    others = [m for m in pend if not m.get('own')]
    mine = [m for m in pend if m.get('own')]
    prepare_own(wm, cse, e, mine)
    tell = [m for m in mine if m.get('tell')]
    wake = [m for m in tell if m.get('wake')]

    def own_done(then):
        for m in mine:
            own_log(cse, title, m, wm, then)
        e['own'] = (e.get('own', []) + [m['id'] for m in mine])[-500:]
    if mine and not others and not wake:  # no bring-back: a note for its next prompt, or nothing when it knows
        if tell and DRY:
            print('would note for %s (%s): %d of your own replies' % (title, cse, len(tell)))
        elif tell:
            queue_note(wm, cse, title, own_note(tell, wm), tell)
        own_done('would be noted for its next prompt (dry)' if DRY else 'noted for its next prompt')
        e['pending'] = []
        return
    # A wait brought it back moments ago: it reads its first prompt now, so these wait for that turn to end.
    if any(w.get('cse') == cse and w.get('stage') == 'back' and time.time() - w.get('back_at', 0) < 180
           for w in (wm.peek().get('waits') or {}).values()):
        return
    note = own_note(tell, wm, wake=not others) if tell else ''
    why = ('new messages came in too' if others else wake[0]['why_wake'])
    what = '; '.join('%s "%s"' % (m['from'] or 'Chat', (m.get('subject') or m.get('text') or '')[:60]) for m in others[:3])
    if DRY:
        add_back(e, others, now)
        if others:
            print('would wake %s (%s) with %d new: %s' % (title, cse, len(others), what))
            log('%s "%s" would come back (dry) for %s' % (cse[:12], title, what))
        else:
            print('would wake %s (%s) with a note of %d of your own replies' % (title, cse, len(tell)))
        own_done('would come back (dry) with a note')
        e['told'] = (e.get('told', []) + [m['id'] for m in others])[-500:]
        e['pending'] = []
        return
    w = {'id': 'w' + cse[-5:], 'cse': cse, 'transcript': e['transcript'], 'cwd': e.get('cwd') or '',
         'title': title, 'session_url': e.get('url', ''), 'source': 'new messages'}
    try:
        ok = wm.bring_back(w, '\n\n'.join(x for x in (prompt_for(cse, e, others, wm) if others else '', note) if x))
    except RuntimeError as x:
        if str(x) == 'busy':
            n = len(pend)
            if now - e.get('busy_said', 0) > 900:
                if getattr(x, 'work', False):  # its agents, background commands or Monitors (wait.py hold_for_work())
                    log('%s "%s" has agents or background commands at work; it comes back with %d new message%s when '
                        'they end' % (cse[:12], title, n, '' if n == 1 else 's'))
                else:
                    log('%s "%s" is in a turn; it comes back with %d new message%s when the turn ends'
                        % (cse[:12], title, n, '' if n == 1 else 's'))
                e['busy_said'] = now
            return
        ok = False
        log('%s "%s" could not come back: %s' % (cse[:12], title, str(x)[:160]))
    except Exception as x:
        ok = False
        log('%s "%s" could not come back: %s: %s' % (cse[:12], title, type(x).__name__, str(x)[:160]))
    e['told'] = (e.get('told', []) + [m['id'] for m in others])[-500:]
    e['pending'] = []
    if ok:
        add_back(e, others, now)  # with a note of the person's own replies alone, a bring-back about no place
        if others:
            log('%s "%s" brought back for %d new message%s: %s' % (cse[:12], title, len(others),
                                                                   '' if len(others) == 1 else 's', what))
        own_done('brought back with a note: ' + why)
        return
    if tell:  # it could not come back: the note waits for its next prompt, and nothing alerts
        queue_note(wm, cse, title, own_note(tell, wm), tell)
    own_done('noted for its next prompt')
    if not others:
        return
    try:
        n = load('notify')
        res = n.send('New messages for ' + title, 'New messages came in that may concern the session "%s": '
                     '%s. It could not come back by itself; open it to go on.' % (title, what),
                     title=title, url=e.get('url', ''), cse=cse, source='kit',
                     about={'at': now, 'places': list(dict.fromkeys(p for m in others for p in places_of(m))),
                            'what': 'new messages for it'})
        if res and res[0][0] == n.IN_KIT:  # alerts off (notify.py held()): kept in the Kit app on the session
            log('%s "%s" could not come back; the Kit kept the message in the Kit app (%s)' % (cse[:12], title, res[0][1][1]))
        else:
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
        if e.get('archived'):
            print('%s  %s\n    not watched: archived with no wait, since %s' % (e.get('title') or cse, cse, clock(e['archived'])))
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
