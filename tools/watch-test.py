#!/usr/bin/python3
"""Tests the reply watch (Resources/hooks/watch.py) on copies: a test folder and log (STTARK_KIT_DIR, STTARK_KIT_LOG),
made-up sessions and transcripts, a JSON file for the Keychain (STTARK_MAIL_KEYS), a stand-in for Google on this Mac
(STTARK_MAIL_GOOGLE) and a stand-in for `claude -p` (no model call, no real mailbox, no session is started):
- the facts from a session's records: a draft's addresses, domain and thread, a web form an agent sent (on a form
  service, so the site that holds it counts), an Asana comment, a Chat post, an email reply wait; and what is no
  contact: a sign-in, an order, a read of an old message; a new line read once, a line still being written later;
- a mailbox this Mac reads (no model): the form's answer, a ticket system's notice and a reply in the draft's thread
  bring the session back, once, with one prompt; a newsletter from that domain, mail older than the contact or the
  watch, and a message the session already read do not; one message goes to one session (a thread before a domain,
  then the newest); a colleague's address counts only in its thread;
- the first read after an update looks back to a session's oldest open wait (the backfill), not further;
- the person's own mailbox with no sign-in: one Haiku run for every session (stand-in), an Asana notice and a Chat
  post; a run that skips a call fails the read and tries the same window again;
- delivery: a session in a turn is tried again; one that read the message by itself is not brought back; one the
  Kit started moments ago (a wait brought it back) waits for that turn; a wait never ends on a message the watch
  brought the session back for, and the watch skips one a wait ended on;
- narrow and broad matches, with a stand-in for the Haiku check (STTARK_WATCH_MODEL): a reply in a draft's thread, a
  comment on an Asana task and a Chat reply in the thread of the session's post come back with no check; a post in a
  direct message or a room, mail from the same sender in a new thread, from the domain and from a form's site are
  checked, and only a YES comes back; a NO is logged and sends nothing; two sessions are each asked; a check that
  fails comes back all the same; the check waits at a usage hold, and holds 8 checks a minute; the check reads the
  session's name, its first prompt, the text it typed and sent, and the new message;
- the Stop check: a web form or a draft with only a time wait is noted, with the command to set; a reply wait is not;
- only a command the shell runs counts: claude-window or claude-wait named in a here-document (an agent that edits a
  test), in quotes or in a commit message is no contact and no wait; one run by a variable set to its path, with
  code from a file the same command writes, is.
Run from the repo root: /usr/bin/python3 tools/watch-test.py"""
import base64, contextlib, importlib.util, io, json, os, re, stat, sys, tempfile, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, 'Resources', 'hooks')
d = tempfile.mkdtemp(prefix='kit-watch-')
ME = 'person@sample.example'
fails = 0


def check(what, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what)
    fails += not ok


NOW = time.time()
T0 = NOW - 6 * 3600


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(t))


def rfc(t):
    return time.strftime('%a, %d %b %Y %H:%M:%S +0000', time.gmtime(t))


# --- made-up mail, served by a stand-in for Google (direct reads) and for claude -p (Workrouter) --------------------
MAIL = []


def mail(mid, tid, sender, subject, at, snippet='', body=''):
    MAIL.append({'id': mid, 'thread_id': tid, 'from': sender, 'to': ME, 'subject': subject, 'at': int(at),
                 'snippet': snippet or subject, 'body': body or snippet or subject})


def search(q, box):
    """What Gmail answers for a watch search: after:, -from:me and the {...} group of from: and subject: terms."""
    after = int(re.search(r'after:(\d+)', q).group(1))
    group = re.search(r'\{(.*)\}', q)
    src = group.group(1) if group else q.replace('-from:me', '')
    terms = [(k, v.strip('()')) for k, v in re.findall(r'(from|subject):("[^"]*"|\S+)', src)]
    out = []
    for m in sorted(MAIL, key=lambda m: -m['at']):
        if m['at'] <= after or box in m['from'].lower():
            continue
        if terms and not any((k == 'from' and v.lower() in m['from'].lower()) or
                             (k == 'subject' and v.strip('"').lower() in m['subject'].lower()) for k, v in terms):
            continue
        out.append(m)
    return out


g = {'queries': []}


class Google(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.answer({'access_token': 'at-1', 'expires_in': 3599})

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        base = '/gmail/v1/users/me/messages'
        if u.path == base:
            g['queries'].append(q['q'])
            hits, start, n = search(q['q'], ME), int(q.get('pageToken') or 0), int(q.get('maxResults') or 100)
            body = {'messages': [{'id': m['id'], 'threadId': m['thread_id']} for m in hits[start:start + n]]}
            if start + n < len(hits):
                body['nextPageToken'] = str(start + n)
            return self.answer(body)
        m = [x for x in MAIL if u.path == base + '/' + x['id']][0]
        headers = [{'name': 'From', 'value': m['from']}, {'name': 'To', 'value': ME}, {'name': 'Subject', 'value': m['subject']},
                   {'name': 'Date', 'value': rfc(m['at'])}]
        body = {'id': m['id'], 'threadId': m['thread_id'], 'internalDate': str(m['at'] * 1000), 'snippet': m['snippet'],
                'payload': {'headers': headers, 'mimeType': 'text/plain',
                            'body': {'data': base64.urlsafe_b64encode(m['body'].encode()).decode()}}}
        self.answer(body)


server = HTTPServer(('127.0.0.1', 0), Google)
threading.Thread(target=server.serve_forever, daemon=True).start()
KIT = os.path.join(d, 'kit')
os.makedirs(KIT)
KEYS = os.path.join(d, 'keys.json')
os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=os.path.join(d, 'log'), STTARK_MAIL_KEYS=KEYS,
                  STTARK_MAIL_GOOGLE='http://127.0.0.1:%d' % server.server_address[1], STTARK_WAIT_DRY='1')


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HOOKS, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


watch, wait = load('watch'), load('wait')
watch.ME = ME
wait.me = lambda: ME
watch.held = lambda: False

fake = os.path.join(d, 'claude')
open(fake, 'w').write('''#!/usr/bin/python3
import json, os, re, sys
p = sys.stdin.read()
open(os.environ['FAKE_DIR'] + '/prompts', 'a').write(p + '\\n')
answers = json.load(open(os.environ['FAKE_DIR'] + '/answers.json'))
print(json.dumps({'type': 'system', 'subtype': 'init', 'mcp_servers': [], 'tools': []}))
for n, line in enumerate(re.findall(r'^\\d+\\. (\\S+) (\\{.*\\})$', p, re.M)):
    name, args = line[0], json.loads(line[1])
    key = args.get('query') or args.get('space_id')
    if os.environ.get('FAKE_SKIP') and os.environ['FAKE_SKIP'] in name:
        continue
    print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't%d' % n, 'name': name, 'input': args}]}}))
    print(json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't%d' % n, 'is_error': False,
                                                              'content': [{'type': 'text', 'text': json.dumps(answers.get(key[:40], {}))}]}]}}))
print(json.dumps({'type': 'result', 'result': 'done'}))
''')
os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
wait.CLAUDE = fake
os.environ['FAKE_DIR'] = d
json.dump({}, open(os.path.join(d, 'answers.json'), 'w'))
# a stand-in for the Haiku check of a broad match: each rule [session name, words in the new message, answer], the
# first that fits; YES when none does. FAIL exits 1, as a call that fails.
judge = os.path.join(d, 'judge')
open(judge, 'w').write('''#!/usr/bin/python3
import json, os, sys
q = sys.stdin.read()
open(os.environ['FAKE_DIR'] + '/asked', 'a').write(q + '\\n=====\\n')
name = q.split('\\n')[0]
new = q.split('The new message.')[-1]
for who, words, answer in json.load(open(os.environ['FAKE_DIR'] + '/judge.json')):
    if who in name and words in new:
        if answer == 'FAIL':
            sys.exit(1)
        print(answer)
        sys.exit(0)
print('YES - it answers the session')
''')
os.chmod(judge, os.stat(judge).st_mode | stat.S_IEXEC)
watch.STUB = judge
json.dump([], open(os.path.join(d, 'judge.json'), 'w'))

def fresh():
    """A watch with no state yet, as on the first check after an update."""
    if os.path.exists(watch.FILE):
        os.remove(watch.FILE)


# --- made-up sessions: their records -------------------------------------------------------------------------------
n = [0]


def use(name, inp, at, result, err=False):
    n[0] += 1
    i = 'toolu_%04d' % n[0]
    return [{'type': 'assistant', 'timestamp': iso(at), 'cwd': '/tmp/site', 'message': {'content': [
                {'type': 'tool_use', 'id': i, 'name': name, 'input': inp}]}},
            {'type': 'user', 'timestamp': iso(at), 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': i, 'is_error': err, 'content': [{'type': 'text', 'text': result}]}]}}]


def person(text, at):
    return [{'type': 'user', 'timestamp': iso(at), 'message': {'role': 'user', 'content': text}}]


def write(path, lines, mode='w'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in lines))


WR = 'mcp__claude_ai_Sttark_Workrouter__'
PROJ = os.path.join(d, 'projects')
TP1 = os.path.join(PROJ, 'site.jsonl')
draft = use(WR + 'gmail_create_draft', {'to': 'Alex <alex@kingsample.example>', 'cc': 'pat@banksample.example, friend@gmail.com',
                                         'subject': 'Closing', 'body': 'Alex, ...'}, T0 + 60,
            json.dumps({'draft_id': 'r-1', 'message_id': 'm-own1', 'thread_id': 'thr1alex0000001', 'to': 'Alex <alex@kingsample.example>',
                        'subject': 'Closing for Unit 4'}))
team = use(WR + 'gmail_create_draft', {'to': 'Pat <pat@sample.example>'}, T0 + 65,
           json.dumps({'draft_id': 'r-3', 'thread_id': 'thrteam0000001', 'to': 'Pat <pat@sample.example>', 'subject': 'Wire request'}))
old_read = use(WR + 'gmail_read_message', {'message_id': 'oldmsg'}, T0 + 70,
               json.dumps({'id': 'oldmsg', 'thread_id': 'throld00000001', 'from': 'Shop <orders@shop.example>',
                           'subject': 'Your order', 'date': rfc(T0 - 400 * 86400)}))
new_read = use(WR + 'gmail_read_message', {'message_id': 'newmsg'}, T0 + 80,
               json.dumps({'id': 'newmsg', 'thread_id': 'thrread0000001', 'from': 'Kim <kim@agentsample.example>',
                           'subject': 'Offer on the lot', 'date': rfc(T0 - 3600)}))
comment = use(WR + 'asana_add_comment', {'task_gid': '1200000000000001', 'text': 'Can you check the survey?'}, T0 + 90,
              '{"comment_added":true}')
chat = use('mcp__claude_ai_Google_Chat__send_message', {'space': 'spaces/AAAAtest01', 'text': 'Is the press ready – for the new die?'},
           T0 + 100, '{"name":"spaces/AAAAtest01/messages/m1"}')
only_at = use('Bash', {'command': 'claude-wait at "+2d" --why "Thu 5 PM: check for the utility reply"'}, T0 + 400,
              'Wait aaa111 set: the time Thu 5:00 PM. The Kit watches it now.')
write(TP1, person('Buy the site', T0) + draft + team + old_read + new_read + comment + chat)
# its agent sends the utility's contact form (on a form service), signs in to a bank, and places an order
AG = os.path.join(PROJ, 'site', 'subagents', 'agent-form1.jsonl')
write(AG, person('Ask the utility about water', T0 + 200)
      + use('Bash', {'command': 'claude-window go https://www.utilitysample.example/contact/ ; claude-window text | head'},
            T0 + 210, 'Contact - Utility\nhttps://www.utilitysample.example/contact/\nAccount Login | Pay My Bill')
      + use('Bash', {'command': 'claude-window js \'JSON.stringify([...document.querySelectorAll("iframe")].map(i=>i.src))\''},
            T0 + 215, '["https://form.jotform.com/123?isIframeEmbed=1&parentURL=https%3A%2F%2Fwww.utilitysample.example%2Fcontact%2F"]')
      + use('Bash', {'command': 'claude-window go "https://form.jotform.com/123"; claude-window js \'set("input_4","%s")\'' % ME},
            T0 + 220, 'Contact Us\nhttps://form.jotform.com/123\n["%s"]' % ME)
      + use('Bash', {'command': 'claude-window js \'const b=[...document.querySelectorAll("button")].find(b=>/submit/i.test(b.textContent)); b.click()\'; sleep 6; claude-window url; claude-window text | head -30'},
            T0 + 230, 'clicked\nThank You\nhttps://submit.jotform.com/123\nThank You for your inquiry! Your submission has been received and a representative will contact you soon.')
      + use('Bash', {'command': 'claude-window go https://www.banksample.example/login; claude-window js \'document.querySelector("#password").value="x"; document.querySelector("button[type=submit]").click()\''},
            T0 + 240, 'Bank\nhttps://www.banksample.example/login\nThank you for contacting us')
      + use('Bash', {'command': 'claude-window go https://www.shopsample.example/cart; claude-window js \'document.querySelector("#place-order").click(); "submit"\''},
            T0 + 250, 'Shop\nhttps://www.shopsample.example/done\nThank you for your order. Order number 12345.')
      + use('Bash', {'command': 'claude-window go "https://message.alibaba.com/message/messenger.htm"; claude-window js \'document.querySelector("[aria-label=Send]").click(); "sent"\''},
            T0 + 260, 'Messenger\nhttps://message.alibaba.com/message/messenger.htm\nsent')
      + use('Bash', {'command': 'claude-window go "https://mail.google.com/mail/u/0/#inbox?compose=new"; claude-window js \'to.value="quotes@vendorsample.example"; [...document.querySelectorAll("div[role=button]")].find(b=>/^Send/.test(b.dataset.tooltip)).click()\''},
            T0 + 270, 'Gmail\nhttps://mail.google.com/mail/u/0/#inbox\nok'))
# a second session that emailed someone at the utility earlier
TP2 = os.path.join(PROJ, 'water.jsonl')
write(TP2, person('Ask about water', T0 - 3000)
      + use(WR + 'gmail_create_draft', {'to': 'ops@utilitysample.example', 'subject': 'Water'}, T0 - 2900,
            json.dumps({'draft_id': 'r-2', 'thread_id': 'thrwater000001', 'to': 'ops@utilitysample.example', 'subject': 'Water'})))
CSE1, CSE2 = 'cse_01SitePurchase00001', 'cse_01WaterQuestion0002'
state = {'sessions': {CSE1: {'transcript': TP1, 'title': 'Site purchase', 'url': 'https://claude.ai/code/session_01Site'},
                      CSE2: {'transcript': TP2, 'title': 'Water question'}},
         'waits': {'aaa111': {'id': 'aaa111', 'kind': 'at', 'at': NOW + 2 * 86400, 'cse': CSE1, 'transcript': TP1,
                              'set_at': T0 + 400, 'title': 'Site purchase', 'why': 'Thu 5 PM'}}}
json.dump(state, open(os.path.join(KIT, 'state.json'), 'w'))

# --- the facts --------------------------------------------------------------------------------------------------------
own = watch.own_sites(ME)
e1 = {'files': {}, 'keys': []}
watch.refresh(e1, TP1, NOW, ME, own)
keys = {(k['k'], k['v']): k for k in e1['keys']}
check('a draft: each address, the domains that are not free mail, and the thread with its subject',
      ('addr', 'alex@kingsample.example') in keys and ('domain', 'kingsample.example') in keys
      and ('domain', 'banksample.example') in keys and ('addr', 'friend@gmail.com') in keys
      and ('domain', 'gmail.com') not in keys and keys[('thread', 'thr1alex0000001')].get('subject') == 'Closing for Unit 4')
check('a web form an agent sent on a form service: the site that holds it, in the mailbox it gave',
      keys.get(('domain', 'utilitysample.example'), {}).get('how') == 'form'
      and keys[('domain', 'utilitysample.example')]['box'] == ME and ('domain', 'jotform.com') not in keys)
check('a colleague (the person\'s own domain): only the thread, not the address or the domain',
      ('thread', 'thrteam0000001') in keys and ('addr', 'pat@sample.example') not in keys and ('domain', 'sample.example') not in keys)
check('a message on a supplier\'s messenger: the platform, in any mailbox the Kit reads; a mail sent in Gmail: its address',
      keys.get(('domain', 'alibaba.com'), {}).get('how') == 'messenger' and keys[('domain', 'alibaba.com')]['box'] == '*'
      and keys.get(('addr', 'quotes@vendorsample.example'), {}).get('how') == 'email')
check('a sign-in and an order are no contact', ('domain', 'shopsample.example') not in keys
      and keys.get(('domain', 'banksample.example'), {}).get('how') == 'draft')
check('a read of a recent message is a thread; of an old one, nothing',
      keys.get(('thread', 'thrread0000001'), {}).get('how') == 'read' and ('thread', 'throld00000001') not in keys)
check('an Asana comment and a Chat post', ('asana', '1200000000000001') in keys and ('chat', 'spaces/AAAAtest01') in keys)
check('the folder the session runs in', e1.get('cwd') == '/tmp/site')
size = len(e1['keys'])
write(TP1, only_at, 'a')
late = use(WR + 'asana_add_comment', {'task_gid': '1200000000000099'}, T0 + 500, '{"comment_added":true}')
with open(TP1, 'a') as f:
    f.write(json.dumps(late[0]))
watch.refresh(e1, TP1, NOW, ME, own)
check('a new line is read once; a line still being written waits', len(e1['keys']) == size
      and ('asana', '1200000000000099') not in {(k['k'], k['v']) for k in e1['keys']})
with open(TP1, 'a') as f:
    f.write('\n' + json.dumps(late[1]) + '\n')
watch.refresh(e1, TP1, NOW, ME, own)
check('then the whole line is read', ('asana', '1200000000000099') in {(k['k'], k['v']) for k in e1['keys']})
wf = watch.wait_facts('claude-wait email-reply 1a1e60af2112d6ff --from alex@kingsample.example --by "+1d" --why "x"; '
                      'claude-wait email-reply --query "from:(water.example OR ops@pipes.example)" --by +2d --why "y"',
                      'Wait abc123 set: a reply\nWait def456 set: new mail', T0, ME, own)
wf2 = watch.wait_facts('claude-wait email-reply 1a1e60af2112d6ff --from sam@contsample.example \\\n  --by "+1d" --why "two\nlines"',
                       'Wait abc124 set: a reply', T0, ME, own)
check('a claude-wait that goes on over lines', ('addr', 'sam@contsample.example') in {(k['k'], k['v']) for k in wf2})
check('an email reply wait: its thread, its sender and the domains of its search',
      {('thread', '1a1e60af2112d6ff'), ('addr', 'alex@kingsample.example'), ('domain', 'water.example'),
       ('domain', 'pipes.example'), ('wait', 'email-reply')} <= {(k['k'], k['v']) for k in wf})

AG2 = os.path.join(PROJ, 'site', 'subagents', 'agent-cookie.jsonl')
write(AG2, person('Look at the shop', T0 + 280)
      + use('Bash', {'command': 'claude-window go https://www.shopx.example/contact-us; claude-window text | head -40'}, T0 + 281,
            'Contact\nhttps://www.shopx.example/contact-us\nThank you for contacting us! Our team will contact you soon.\nhttps://www.linkedin.com/company/shopx')
      + use('Bash', {'command': 'claude-window js \'document.querySelector("#accept").click(); "ok"\''}, T0 + 282, 'ok')
      + use('Bash', {'command': 'claude-window js \'document.querySelector("button[type=submit]").click()\'; claude-window text | head'}, T0 + 283,
            'Thank you for contacting us! Our team will contact you soon.\nhttps://www.linkedin.com/company/shopx'))
e3 = {'files': {}, 'keys': []}
watch.refresh(e3, TP1, NOW, ME, own)
k3 = {(k['k'], k['v']) for k in e3['keys']}
check('no form from a contact page\'s own words before the click, a cookie button, or a link in the page\'s text',
      ('domain', 'shopx.example') not in k3 and ('domain', 'linkedin.com') not in k3 and ('domain', 'utilitysample.example') in k3)

# --- a mailbox this Mac reads itself: no model ------------------------------------------------------------------------
json.dump({ME: '1//rt'}, open(KEYS, 'w'))
mail('m-ack', 'thrack', 'Helpdesk <help@utilitysample.example>', '[Ticket 1] Contact Us', T0 + 450, 'We received a request')
mail('m-ans', 'thrans', 'Sam <help@utilitysample.example>', '[Ticket 1] Contact Us', NOW - 600, 'We do not serve water to this address')
mail('m-auto', 'thrauto', 'Utility News <newsletter@utilitysample.example>', 'Save water this winter', NOW - 500, 'Tips')
mail('m-ticket', 'thrticket', 'donotreply@utilitysample.example', 'You have a new message regarding Ticket #1', NOW - 450, 'Log in to read it')
mail('m-alex', 'thr1alex0000001', 'Alex <alex@kingsample.example>', 'Re: Closing for Unit 4', NOW - 400, 'Yes, we can close on 12/14')
mail('m-team', 'thrteam0000001', 'Pat <pat@sample.example>', 'Re: Wire request', NOW - 350, 'Sent today')
mail('m-team2', 'throther', 'Pat <pat@sample.example>', 'Lunch?', NOW - 340, 'Pizza at noon')
mail('m-ali', 'thrali', 'Alibaba <credit@notice.alibaba.com>', 'Your order has been updated by the supplier (321)', NOW - 420, 'Order')
mail('m-ali2', 'thrali2', 'Alibaba <service@alibaba.com>', 'Factory-direct machines, made for you', NOW - 410, 'Sale')
mail('m-early', 'threarly', 'Pat <pat@banksample.example>', 'Rates', T0 - 7200, 'Old mail from before the draft')
mail('m-quoted', 'thrquoted', 'Sam <help@utilitysample.example>', 'Re: meter', NOW - 200,
     'We checked the meter, and the water line is ready to connect today. Call us to set a time.')
write(TP1, person('[Sttark Claude Kit] A wait you handed to the Kit has ended. Sam replied: "Re: meter" (We checked the meter, '
                  'and the water line is ready to connect today. Call us to set a time.)', T0 + 470), 'a')
# the session already read the ticket mail: its id is in its records
write(TP1, use(WR + 'gmail_search', {'query': 'from:utilitysample.example'}, T0 + 460, json.dumps({'emails': [{'id': 'm-ack'}]})), 'a')
out = io.StringIO()
with contextlib.redirect_stdout(out):
    picked = watch.check(wait, NOW)
said = out.getvalue()
check('the form\'s answer, a ticket notice from a no-reply sender, and the reply in the draft\'s thread bring the '
      'session back, with one prompt', set(picked.get(CSE1, {})) == {'m-ans', 'm-ticket', 'm-alex', 'm-team', 'm-ali'}
      and said.count('would wake Site purchase') == 1)
check('a newsletter from the domain, mail before the watch, mail it already read (by id, or quoted in a wait\'s '
      'prompt), a colleague\'s mail in another thread, or a messenger platform\'s sales mail: nothing',
      not any(x in json.dumps(picked) for x in ('m-auto', 'm-early', 'm-ack', 'm-quoted', 'm-team2', 'm-ali2')))
check('the read: one search for the mailbox with every session\'s terms, after the oldest open wait, and one for '
      'Asana\'s notices', len(g['queries']) == 2 and 'from:utilitysample.example' in g['queries'][0]
      and 'from:kingsample.example' in g['queries'][0] and 'subject:"Closing for Unit 4"' in g['queries'][0]
      and 'after:%d' % (T0 + 400) in g['queries'][0] and g['queries'][1] == 'after:%d from:no-reply@asana.com' % (T0 + 400))
W = watch.peek()
check('the floor: the oldest open wait for a session with one, the watch\'s start for one with none',
      W['sessions'][CSE1]['floor'] == T0 + 400 and W['sessions'][CSE2]['floor'] == NOW)
check('read again within 5 minutes: nothing', not watch.check(wait, NOW + 60))
mail('m-alex2', 'thr1alex0000001', 'Alex <alex@kingsample.example>', 'Re: Closing for Unit 4', NOW + 200, 'And the survey')
mail('m-water', 'thrwater000001', 'Ops <ops@utilitysample.example>', 'Re: Water', NOW + 210, 'About your water')
with contextlib.redirect_stdout(io.StringIO()):
    picked = watch.check(wait, NOW + 301)
check('the next read: only what is new, and never a message twice', set(picked.get(CSE1, {})) == {'m-alex2'}
      and 'after:%d' % (NOW - watch.OVERLAP) in g['queries'][-1])
check('one message, one session: a reply in a thread goes to the session of that thread, not to the newer form',
      set(picked.get(CSE2, {})) == {'m-water'})
mail('m-dup', 'thrwater000001', 'Ops <ops@utilitysample.example>', 'Re: Water', NOW + 250, 'Same mail')
watch.mark_told(CSE1, ['m-dup'])
with contextlib.redirect_stdout(io.StringIO()):
    picked = watch.check(wait, NOW + 700)
check('a message one session got never goes to another', 'm-dup' not in json.dumps(picked))
for i in range(130):
    mail('m-bulk%03d' % i, 'thrbulk%d' % i, 'News <news@bulksample.example>', 'Deal %d' % i, NOW - 5000 + i, 'x')
check('a search reads more than one page', len(load('mail').search(ME, 'after:0 -from:me {from:bulksample.example}', 100, 5)) == 130)
MAIL[:] = [m for m in MAIL if not m['id'].startswith('m-bulk')]
p = watch.prompt_for(CSE1, W['sessions'][CSE1], [dict(MAIL[1], kind='mail', box=ME, why='you sent a web form on utilitysample.example')], wait)
check('the prompt: what came, why it counts, how to read it, the question, and the open waits',
      p.startswith('[Sttark Claude Kit] New messages came in that may concern this session') and 'claude-mail read %s m-ans' % ME in p
      and 'you sent a web form on utilitysample.example' in p and 'decide if it needs action' in p and 'aaa111' in p)

# --- the person's own mailbox with no sign-in: one Haiku run for all sessions ---------------------------------------
json.dump({}, open(KEYS, 'w'))
wait._direct.clear()

fresh()
MAIL[:] = []
mail('m-ans', 'thrans', 'Sam <help@utilitysample.example>', '[Ticket 1] Contact Us', NOW - 600, 'We do not serve water to this address')
mail('m-asana', 'thrasana', 'Wil via Asana <no-reply@asana.com>', 'New comment on: Survey', NOW - 500,
     body='Wil added a comment\r\nReply in Asana: https://app.asana.com/1/31841170284884/task/1200000000000001/comment/9')
mail('m-asana2', 'thrasana2', 'Wil via Asana <no-reply@asana.com>', 'New comment on: Other', NOW - 450,
     body='Reply in Asana: https://app.asana.com/1/31841170284884/task/1299999999999999/comment/9')
NOON = NOW if 7 <= time.localtime(NOW).tm_hour < 21 else NOW - (time.localtime(NOW).tm_hour - 12) * 3600


def answers(skip=''):
    """The stand-in's answer to each call it gets, by the start of its query or its space."""
    a = {}
    for line in open(os.path.join(d, 'want')).read().splitlines():
        args = json.loads(line)
        if 'query' in args:
            box = ME
            a[args['query'][:40]] = {'emails': [{'id': m['id'], 'thread_id': m['thread_id'], 'from': m['from'], 'to': ME,
                                                 'subject': m['subject'], 'date': rfc(m['at']), 'snippet': m['snippet'],
                                                 'body': m['body'][:300]} for m in search(args['query'], box)]}
        else:
            a[args['space_id'][:40]] = {'messages': [
                {'name': 'spaces/AAAAtest01/messages/m9', 'sender': 'users/1', 'text': 'Yes, the press is ready now.', 'createTime': iso(NOW - 300)},
                {'name': 'spaces/AAAAtest01/messages/m8', 'sender': 'users/2', 'text': 'Is the press ready – for the new die?', 'createTime': iso(NOW - 350)},
                {'name': 'spaces/AAAAtest01/messages/m7', 'sender': 'users/2', 'text': 'Ok, thanks!', 'createTime': iso(NOW - 340)},
                {'name': 'spaces/AAAAtest01/messages/m6', 'sender': 'users/3', 'text': 'Ok, thanks!', 'createTime': iso(NOW - 330)}]}
    json.dump(a, open(os.path.join(d, 'answers.json'), 'w'))
    os.environ['FAKE_SKIP'] = skip


# the calls the watch will ask for: worked out the same way, so the stand-in can answer them
W0 = {}
sess = watch.watched(W0, wait, NOON, ME, own)
ks = [k for e in sess.values() for k in e['keys'] if k['k'] != 'chat']
since = int(max(min(e['floor'] for e in sess.values()), NOON - watch.BACK_DAYS * 86400))
with open(os.path.join(d, 'want'), 'w') as f:
    for q in watch.queries(ks, since):
        f.write(json.dumps({'query': q}) + '\n')
    f.write(json.dumps({'space_id': 'spaces/AAAAtest01'}) + '\n')
answers()
open(os.path.join(d, 'prompts'), 'w').close()
fresh()
with contextlib.redirect_stdout(io.StringIO()):
    picked = watch.check(wait, NOON)
prompts = open(os.path.join(d, 'prompts')).read()
check('one Haiku run for every session: gmail_search with include_body, and one gchat_search_messages per space',
      prompts.count('Make each of these tool calls') == 1 and prompts.count('gmail_search {') == len(watch.queries(ks, since))
      and '"include_body": true' in prompts and 'gchat_search_messages {"space_id": "spaces/AAAAtest01"' in prompts)
check('the form\'s answer through Workrouter, an Asana notice for its task (the id in the notice), a Chat reply',
      {'m-ans', 'm-asana', 'spaces/AAAAtest01/messages/m9'} <= set(picked.get(CSE1, {})))
check('an Asana notice for another task, the session\'s own Chat post (with a non-ASCII dash), and the person\'s '
      'other posts: nothing', 'm-asana2' not in json.dumps(picked) and 'messages/m8' not in json.dumps(picked)
      and 'messages/m7' not in json.dumps(picked))
check('a short reply from someone else counts, also when the same words are in the records',
      'spaces/AAAAtest01/messages/m6' in picked.get(CSE1, {}))
W = watch.peek()
check('the read is recorded as through Workrouter', W['boxes'][ME].get('via') == 'model' and W['chat'].get('read_at') == NOON)
fresh()
answers(skip='gmail_search')
with contextlib.redirect_stdout(io.StringIO()):
    picked = watch.check(wait, NOON)
W = watch.peek()
check('a run that skips a call: the read fails, says why, and its window is read again next time',
      not W['boxes'][ME].get('read_at') and W['boxes'][ME].get('failing') and 'read failed' in open(os.environ['STTARK_KIT_LOG']).read())
runs = open(os.path.join(d, 'prompts')).read().count('Make each of these tool calls')
watch.check(wait, NOON + 60)
again = open(os.path.join(d, 'prompts')).read().count('Make each of these tool calls')
watch.check(wait, NOON + 601)
check('a failed read is tried again after 10 minutes, not each minute',
      again == runs and open(os.path.join(d, 'prompts')).read().count('Make each of these tool calls') == runs + 1)
fresh()
check('the hours: no Haiku run at night', watch.check(wait, NOON - time.localtime(NOON).tm_hour * 3600 + 3 * 3600) == {})

# --- delivery -----------------------------------------------------------------------------------------------------------
os.environ.pop('STTARK_WAIT_DRY')
watch.DRY = False
json.dump({ME: '1//rt'}, open(KEYS, 'w'))
wait._direct.clear()
fresh()
TA = NOON + 1000
calls = []


def busy(w, prompt):
    calls.append(w['cse'])
    raise RuntimeError('busy')


wait.bring_back = busy
watch.check(wait, TA)
mail('m-d1', 'thrd1', 'Sam <help@utilitysample.example>', 'Re: [Ticket 1]', TA + 100, 'One more thing')
mail('m-d2', 'thrwater000001', 'Ops <ops@utilitysample.example>', 'Re: Water', TA + 100, 'Water is on')
del calls[:]
# m-d1 is a broad match for both sessions (the form's site, and the domain of the other's draft): each is asked
json.dump([['Water question', 'One more thing', 'NO - it is about the site form, not the water question']],
          open(os.path.join(d, 'judge.json'), 'w'))
watch.check(wait, TA + 301)
W = watch.peek()
check('a session in a turn: its messages wait, and it is tried again each minute', set(calls) == {CSE1, CSE2}
      and {'m-ans', 'm-d1'} <= {m['id'] for m in W['sessions'][CSE1]['pending']})
brought = []
wait.bring_back = lambda w, prompt: brought.append((w['cse'], prompt)) or True
write(TP2, use(WR + 'gmail_read_message', {'message_id': 'm-d2'}, TA + 200, json.dumps({'id': 'm-d2'})), 'a')
watch.check(wait, TA + 362)
W = watch.peek()
check('then it comes back once with all of them; one that read its message by itself meanwhile does not',
      [c for c, _ in brought] == [CSE1] and not W['sessions'][CSE1]['pending'] and 'm-d1' in W['sessions'][CSE1]['told']
      and not W['sessions'][CSE2].get('pending') and 'm-d1' in brought[0][1] and 'm-ans' in brought[0][1])
check('the log says who came back and why', 'brought back for' in open(os.environ['STTARK_KIT_LOG']).read())
st = json.load(open(os.path.join(KIT, 'state.json')))
st.setdefault('keep', {}).setdefault('alone', {})[CSE1] = {'transcript': TP1, 'title': 'Site purchase', 'at': time.time()}
json.dump(st, open(os.path.join(KIT, 'state.json'), 'w'))
try:
    load('wait').bring_back({'id': 'x', 'cse': CSE1, 'transcript': TP1}, 'hello')
    check('a session the Kit started moments ago is not started again (its first prompt runs)', False)
except RuntimeError as x:
    check('a session the Kit started moments ago is not started again (its first prompt runs)', str(x) == 'busy')
st['keep']['alone'].pop(CSE1)
st['waits']['back1'] = {'id': 'back1', 'kind': 'email-reply', 'cse': CSE2, 'stage': 'back', 'back_at': time.time(), 'transcript': TP2}
json.dump(st, open(os.path.join(KIT, 'state.json'), 'w'))
W = watch.peek()
W['sessions'][CSE2]['pending'] = [dict(MAIL[-1], id='m-d3', kind='mail', box=ME, why='test')]
watch.save(W)
del brought[:]
watch.check(wait, TA + 400)
check('nor one a wait brought back moments ago: its messages wait for that turn', brought == []
      and [m['id'] for m in watch.peek()['sessions'][CSE2]['pending']] == ['m-d3'])
st['waits'].pop('back1')
json.dump(st, open(os.path.join(KIT, 'state.json'), 'w'))
q = {'kind': 'email-reply', 'id': 'bbb222', 'cse': CSE1, 'target': '', 'query': 'from:(help@utilitysample.example)',
     'set_at': TA, 'by': TA + 86400}
wait._direct.clear()
happened, what = wait.check_email_reply(q)
check('a wait never ends on a message the watch brought the session back for', not happened)
q2 = dict(q, id='ccc333', cse=CSE2, query='from:(utilitysample.example)')
happened, what = wait.check_email_reply(q2)
check('a wait that ends keeps every message it found, for the watch to skip', happened and set(q2.get('found_ids') or []) >= {'m-d2', 'm-d1'})
watch.mark_told(CSE2, ['m-new'])
check('and the watch skips a message a wait brought its session back for', 'm-new' in watch.told(CSE2))
check('a message a check said is about other work is not told: a wait of the session still sees it',
      'm-d1' in (watch.peek()['sessions'][CSE2].get('skipped') or []) and 'm-d1' not in watch.told(CSE2)
      and "skip %s \"Water question\" Sam <help@utilitysample.example>: not about this session's work: Re: [Ticket 1] One more thing"
      % CSE2[:12] in open(os.environ['STTARK_KIT_LOG']).read())

# --- narrow and broad matches: a broad one is checked (a stand-in for Haiku) before it brings a session back ----------
lt = time.localtime(NOW)
TB = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, 12, 0, 0, 0, 0, -1))  # noon tomorrow: Chat is read then
ROOM, DM = 'spaces/ROOMtest01', 'spaces/DMtest0001'
TPA, TPB, TPC = (os.path.join(PROJ, x + '.jsonl') for x in ('chairs', 'die', 'laminator'))
TPD, TPE, TPF = (os.path.join(PROJ, x + '.jsonl') for x in ('ink', 'install', 'glue'))
# A: posts in a direct message from the browser; the text is typed from a file the command writes
write(TPA, person('Find 12 matching chairs on casters for the meeting room', T0)
      + use('Bash', {'command': 'claude-window go "https://mail.google.com/chat/u/0/#chat/dm/DMtest0001"'}, T0 + 10,
            'Chat\nhttps://mail.google.com/chat/u/0/#chat/dm/DMtest0001')
      + use('Bash', {'command': "cat > /tmp/t.js <<'EOF'\n(()=>{const t=\"Our meeting room chairs creak, so I found 12 "
                                "matching chairs on casters. Which do you like?\";\nconst e=document.querySelector("
                                "\"[contenteditable=true]\"); e.focus(); document.execCommand(\"insertText\",false,t); "
                                "return e.innerText})()\nEOF\nclaude-window js \"$(cat /tmp/t.js)\""}, T0 + 20, 'ok')
      + use('Bash', {'command': 'claude-window js \'(()=>{[...document.querySelectorAll("button")].find(b=>b.getAttribute('
                                '"aria-label")==="Send message").click(); return "sent"})()\''}, T0 + 30, 'sent'))
# B: posts in a room with the Chat connector; the created message names its thread
write(TPB, person('Ask the press team to check the die for job 4417', T0)
      + use('mcp__claude_ai_Google_Chat__send_message', {'conversationId': ROOM, 'messageText':
            'Can someone check the die for job 4417 before the press run?'}, T0 + 10,
            json.dumps({'messageId': ROOM + '/messages/t5.t5', 'threadId': ROOM + '/threads/t5'})))
# C and E: drafts to the same supplier, one to the rep, one to the installs desk
write(TPC, person('Get a quote for the 13 inch laminator', T0) + use(WR + 'gmail_create_draft', {
    'to': 'rep@suppliersample.example', 'subject': 'Laminator quote', 'body': 'Please quote the 13 inch laminator.'}, T0 + 10,
    json.dumps({'draft_id': 'r-l', 'thread_id': 'thrlam01', 'to': 'rep@suppliersample.example', 'subject': 'Laminator quote'})))
write(TPE, person('Book the laminator install', T0) + use(WR + 'gmail_create_draft', {
    'to': 'installs@suppliersample.example', 'subject': 'Install date'}, T0 + 20,
    json.dumps({'draft_id': 'r-i', 'thread_id': 'thrinst01', 'to': 'installs@suppliersample.example', 'subject': 'Install date'})))
# D: a web form on a site (the utility's form, made the ink maker's) and an Asana comment
write(TPD, person('Ask the ink maker about the white ink', T0) + [
    json.loads(l) for l in open(AG).read().replace('utilitysample', 'inksample').splitlines()[1:9]]
    + use(WR + 'asana_add_comment', {'task_gid': '1300000000000001'}, T0 + 300, '{"comment_added":true}'))
# F: a draft whose check fails
write(TPF, person('Order glue', T0) + use(WR + 'gmail_create_draft', {'to': 'orders@gluesample.example', 'subject': 'Glue'},
                                          T0 + 10, json.dumps({'draft_id': 'r-g', 'thread_id': 'thrglue01', 'to': 'orders@gluesample.example'})))
CA, CB, CC, CD, CE, CF = ('cse_01BroadTest%07d' % i for i in range(6))
names = {CA: ('Meeting room chairs', TPA), CB: ('Die check', TPB), CC: ('Laminator quote', TPC), CD: ('Ink question', TPD),
         CE: ('Laminator install', TPE), CF: ('Glue order', TPF)}
json.dump({'sessions': {c: {'transcript': tp, 'title': t} for c, (t, tp) in names.items()},
           'waits': {'w%d' % i: {'id': 'w%d' % i, 'kind': 'at', 'at': TB + 86400, 'cse': c, 'transcript': names[c][1],
                                 'set_at': TB - 7200, 'title': names[c][0]} for i, c in enumerate(names)}},
          open(os.path.join(KIT, 'state.json'), 'w'))
fresh()
MAIL[:] = []
mail('m-l1', 'thrlam01', 'Rep <rep@suppliersample.example>', 'Re: Laminator quote', TB - 3000, 'Here is the quote')
mail('m-l2', 'thrhol', 'Rep <rep@suppliersample.example>', 'Holiday hours', TB - 2900, 'We close for the holiday')
mail('m-l3', 'thrrev', 'Sales <sales@suppliersample.example>', 'Your laminator quote, revised', TB - 2800, 'New price')
mail('m-f1', 'thrink', 'Help <help@inksample.example>', 'Your question', TB - 2700, 'About the white ink: it ships Monday')
mail('m-a1', 'thrasn', 'Wil via Asana <no-reply@asana.com>', 'New comment on: White ink', TB - 2600,
     body='Reply in Asana: https://app.asana.com/1/31841170284884/task/1300000000000001/comment/9')
mail('m-g1', 'thrglue2', 'Orders <orders@gluesample.example>', 'Order shipped', TB - 2500, 'Your glue shipped')


def post(space, mid, sender, text, at):
    return {'name': '%s/messages/%s' % (space, mid), 'sender': sender, 'text': text, 'createTime': iso(at)}


json.dump({DM: {'messages': [
    post(DM, 'c0.c0', 'Person Sample', 'Our meeting room chairs creak, so I found 12 matching chairs on casters. Which do you like?', TB - 5000),
    post(DM, 'c1.c1', 'Jo Sample', 'I think 12 is right, and the mesh ones look good.', TB - 2000),
    post(DM, 'c2.c2', 'Jo Sample', 'Two other things for the building: the front windows are cloudy, and the lobby lights are out.', TB - 1900)]},
    ROOM: {'messages': [
    post(ROOM, 't5.r1', 'Lee Sample', 'Checked it, it is fine.', TB - 1800),
    post(ROOM, 't6.t6', 'Lee Sample', 'Lunch is here.', TB - 1700)]}}, open(os.path.join(d, 'answers.json'), 'w'))
os.environ['FAKE_SKIP'] = ''
json.dump([['Meeting room chairs', 'windows', 'NO - it is about the windows and the lights, not the chairs'],
           ['Die check', 'Lunch', 'NO - lunch, not the die'],
           ['Laminator', 'Holiday hours', 'NO - a notice about hours'],
           ['Laminator install', 'revised', 'NO - about the quote, not the install'],
           ['Glue order', '', 'FAIL']], open(os.path.join(d, 'judge.json'), 'w'))
open(os.path.join(d, 'asked'), 'w').close()
brought = []
wait.bring_back = lambda w, prompt: brought.append((w['cse'], prompt)) or True
logpos = os.path.getsize(os.environ['STTARK_KIT_LOG'])
watch.CHECKS_A_MINUTE = 20  # this read has 9 checks; the cap of one minute is tested below
watch.check(wait, TB)
asked = open(os.path.join(d, 'asked')).read()
logged = open(os.environ['STTARK_KIT_LOG']).read()[logpos:]
back = {c: p for c, p in brought}


def came(cse, *ids):
    """Brought back with these messages (a Chat post's id is its name's end)."""
    told = watch.told(cse)
    return cse in back and all(any(t == i or t.endswith('/' + i) for t in told) for i in ids)


check('narrow: a reply in the draft\'s thread, an Asana comment on its task and a Chat reply in its post\'s thread '
      'bring the session back with no check', came(CC, 'm-l1') and came(CD, 'm-a1') and came(CB, 't5.r1')
      and 'Here is the quote' not in asked and 'White ink' not in asked and 'Checked it' not in asked)
check('the Chat reply in the thread counts as a reply in the thread of its post',
      'a reply in the thread of your post' in back.get(CB, ''))
check('broad, a direct message: the reply about the chairs is asked about and brings it back; the post about the '
      'windows does not', came(CA, 'c1.c1') and not came(CA, 'c2.c2') and 'cloudy' not in back.get(CA, '')
      and 'the mesh ones' in asked)
check('the check reads the session\'s name, its first prompt, what it sent and the new message',
      'Session name: Meeting room chairs' in asked and 'Find 12 matching chairs on casters for the meeting room' in asked
      and 'What the session sent on it: Our meeting room chairs creak, so I found 12 matching chairs' in asked
      and 'the front windows are cloudy' in asked)
check('a session\'s own post is no new message, and teaches the watch its text and thread',
      'c0.c0' not in json.dumps(watch.peek()['sessions'][CA].get('skipped')) and 'Which do you like' not in back.get(CA, '')
      and [k.get('threads') for k in watch.peek()['sessions'][CA]['keys'] if k['k'] == 'chat'] == [['c0']])
check('broad, a room: a new post outside the thread is asked about and skipped', CB in back and 'Lunch' not in back[CB]
      and 'Lunch is here' in asked)
check('broad, mail from the same sender in a new thread, and from a form\'s site: asked about',
      'Holiday hours' in asked and came(CD, 'm-f1') and 'About the white ink' in asked and 'Holiday hours' not in back.get(CC, ''))
check('two sessions match one message: each is asked, and only the one with YES comes back',
      asked.count('Your laminator quote, revised') == 2 and came(CC, 'm-l3') and CE not in back)
check('a NO: no bring-back, no message, one log line with the first words, for the Events page',
      "skip %s \"Meeting room chairs\" Jo Sample in Chat: not about this session's work: Two other things for the building"
      % CA[:12] in logged and 'it is about the windows and the lights' in logged and 'message failed' not in logged
      and 'sent you the message' not in logged)
check('a check that fails brings the session back all the same, and says so', came(CF, 'm-g1')
      and '"Glue order" could not check a message' in logged)
del brought[:]
mail('m-l4', 'thrl4', 'Rep <rep@suppliersample.example>', 'The laminator ships Friday', TB + 400, 'Ships Friday')
watch.held = lambda: True
watch.check(wait, TB + 600)
held_log = open(os.environ['STTARK_KIT_LOG']).read()[logpos:]
check('at the usage hold the check waits, and the message with it', brought == [] and 'ships Friday' not in
      open(os.path.join(d, 'asked')).read() and '"Laminator quote" waits for the usage hold to end' in held_log)
watch.held = lambda: False
watch.check(wait, TB + 660)
check('then it is checked once for each session it matches, and they come back', sorted(c for c, _ in brought) == [CC, CE]
      and open(os.path.join(d, 'asked')).read().count('ships Friday') == 2)
del brought[:]
mail('m-g2', 'thrg2', 'Orders <orders@gluesample.example>', 'Glue invoice', TB + 700, 'Invoice 1')
mail('m-g3', 'thrg3', 'Orders <orders@gluesample.example>', 'Glue tracking', TB + 710, 'Tracking 2')
json.dump([['Glue order', 'Glue', 'YES - the glue order']], open(os.path.join(d, 'judge.json'), 'w'))
watch.CHECKS_A_MINUTE = 1
watch.check(wait, TB + 960)
first = list(brought)
watch.check(wait, TB + 1020)
watch.CHECKS_A_MINUTE = 20
check('more checks than a minute holds: the rest wait for the next minute, then the session comes back once with all',
      first == [] and [c for c, _ in brought] == [CF] and 'Glue invoice' in brought[0][1] and 'Glue tracking' in brought[0][1])

# --- the Stop check ---------------------------------------------------------------------------------------------------
TP3 = os.path.join(PROJ, 'stop.jsonl')
write(TP3, person('Ask the utility', NOW - 100))
os.makedirs(os.path.join(PROJ, 'stop', 'subagents'))
with open(os.path.join(PROJ, 'stop', 'subagents', 'agent-x.jsonl'), 'w') as f:
    f.write(open(AG).read().replace(iso(T0 + 230), iso(NOW - 50)).replace(iso(T0 + 220), iso(NOW - 60)).replace(
        iso(T0 + 215), iso(NOW - 70)).replace(iso(T0 + 210), iso(NOW - 80)))
write(TP3, use('Bash', {'command': 'claude-wait at "+2d" --why "Thu: check"'}, NOW - 40, 'Wait ccc333 set: the time Thu 5:00 PM.'), 'a')
miss = watch.missing_wait(TP3, 'sid-3', {})
check('the Stop check: a web form with only a time wait is noted, with the command to set',
      [m['v'] for m in miss] == ['utilitysample.example']
      and watch.wait_hint(miss).startswith('claude-wait email-reply --query "from:(utilitysample.example)"'))
write(TP3, use('Bash', {'command': 'claude-wait email-reply --query "from:(utilitysample.example)" --by +2d --why "x"'},
               NOW - 30, 'Wait ddd444 set: new mail that matches'), 'a')
check('a reply wait in the same work: no note', watch.missing_wait(TP3, 'sid-3', {}) == [])
TP4 = os.path.join(PROJ, 'draft.jsonl')
write(TP4, person('Write to Alex', NOW - 100) + use(WR + 'gmail_create_draft', {'to': 'alex@kingsample.example'}, NOW - 90,
                                                 json.dumps({'draft_id': 'r-9', 'thread_id': 'thr9', 'to': 'alex@kingsample.example'})))
check('a draft with no wait is noted', [m['v'] for m in watch.missing_wait(TP4, 'sid-4', {})] == ['kingsample.example'])
check('unless an open email reply wait already names it', watch.missing_wait(TP4, 'sid-4', {'x': {
    'kind': 'email-reply', 'sid': 'sid-4', 'from': 'alex@kingsample.example', 'target': ''}}) == [])
TP5 = os.path.join(PROJ, 'msgr.jsonl')
write(TP5, person('Ask the supplier', NOW - 100) + use('Bash', {'command': 'claude-window go "https://message.alibaba.com/message/messenger.htm"; claude-window js \'document.querySelector("[aria-label=Send]").click()\''},
                                                    NOW - 90, 'Messenger\nhttps://message.alibaba.com/message/messenger.htm\nok'))
miss = watch.missing_wait(TP5, 'sid-5', {})
check('a supplier messenger with no wait is noted, with a time to look at it',
      [m['v'] for m in miss] == ['alibaba.com'] and watch.wait_hint(miss).startswith('claude-wait at <time>'))
write(TP5, use('Bash', {'command': 'claude-wait at "+12h" --why "look at the messenger"'}, NOW - 80, 'Wait eee555 set: the time'), 'a')
check('and a time wait is enough for it', watch.missing_wait(TP5, 'sid-5', {}) == [])
rules = load('working-rules-hook')
rules.NOTES = os.path.join(KIT, 'working-notes.json')
rules.reply_wait_check({'session_id': 'sid-4', 'transcript_path': TP4})
note = json.load(open(rules.NOTES)).get('sid-4', [''])[0]
check('the working rules\' Stop check notes it for the next prompt, with no model call',
      'kingsample.example' in note and 'claude-wait email-reply' in note)
rules.reply_wait_check({'session_id': 'sid-4', 'transcript_path': TP4})
check('once: the next end of turn of the same work adds no second note', len(json.load(open(rules.NOTES))['sid-4']) == 1)

# --- only what the shell runs: text that names claude-window or claude-wait is no contact and no wait -----------------
SEND = ('claude-window go "https://message.alibaba.com/message/messenger.htm"; '
        'claude-window js \'document.querySelector("[aria-label=Send]").click(); "sent"\'')
TP6 = os.path.join(PROJ, 'kitwork.jsonl')
write(TP6, person('Make the watch better', NOW - 100))
write(os.path.join(PROJ, 'kitwork', 'subagents', 'agent-k.jsonl'), person('Add a test', NOW - 95)
      + use('Bash', {'command': "cd kit && python3 - <<'EOF'\ns = open('tools/t.py').read()\ns += %r\n"
                                "open('tools/t.py', 'w').write(s)\nEOF\npython3 tools/t.py" % SEND}, NOW - 90, 'all passed')
      + use('Bash', {'command': 'echo "%s" >> notes.txt; git commit -qm \'Test: %s\'; grep -n "claude-window go" tools/t.py'
                                % (SEND.replace('"', '\\"'), SEND.replace("'", '')), 'cwd': '/tmp'}, NOW - 85,
            '12: ' + SEND + '\nhttps://message.alibaba.com/message/messenger.htm')
      + use('Bash', {'command': "cd kit && python3 - <<'EOF'\ns = open('wait.py').read().replace('claude-wait at <time>', "
                                "'claude-wait at <time> --why <line>')\nEOF\npython3 tools/wait-test.py"}, NOW - 80,
            'Wait abc123 set: the time Thu 5:00 PM.\nall passed'))
e6 = {'files': {}, 'keys': []}
watch.refresh(e6, TP6, NOW, ME, own)
check('an agent that only writes claude-window into a test, an echo or a commit message: no contact for the watch',
      e6['keys'] == [])
check('nor for the Stop check, and a test that prints "Wait ... set" is no wait',
      watch.turn_facts(TP6, ME, own)[0] == [] and watch.missing_wait(TP6, 'sid-6', {}) == [])
rules.reply_wait_check({'session_id': 'sid-6', 'transcript_path': TP6})
check('so the working rules\' Stop check notes nothing', 'sid-6' not in json.load(open(rules.NOTES)))
TP7 = os.path.join(PROJ, 'msgr2.jsonl')
write(TP7, person('Ask the supplier', NOW - 100) + use('Bash', {'command': (
    'CW="$HOME/Library/Application Support/SttarkClaudeKit/hooks/claude-window.sh"; "$CW" go '
    '"https://message.alibaba.com/message/messenger.htm" >/dev/null\ncat > /tmp/send.js <<\'EOF\'\n'
    'document.querySelector("[aria-label=Send]").click(); "sent"\nEOF\ntimeout 60 "$CW" js "$(cat /tmp/send.js)"')},
    NOW - 90, 'sent'))
check('a real send by a variable set to claude-window\'s path, with its code in a file the command writes, counts',
      [m['v'] for m in watch.missing_wait(TP7, 'sid-7', {})] == ['alibaba.com'])
print('%d failed' % fails if fails else 'all passed')
sys.exit(1 if fails else 0)
