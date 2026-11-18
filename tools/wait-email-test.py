#!/usr/bin/python3
"""Tests the email-reply check of wait.py on copies, with a stand-in for `claude -p` (no model call, no mail read):
- a tool that answers an error is the reason, also when the start of the run lists no claude.ai connector (run from
  the Kit, they load after it);
- a thread started from a draft (its first message has another id, so gmail_read_message answers 404) finds its
  subject in the person's own messages in the thread, and the check then searches for replies by that subject;
- a connector listed as failed, with no call, is still said to be the reason."""
import importlib.util, json, os, stat, sys, tempfile

d = tempfile.mkdtemp()
# STTARK_MAIL_KEYS: an empty stand-in for the Keychain, so a Mac that reads its own mailbox (claude-mail sign-in) tests
# the Workrouter check too, and never reads its real sign-in
open(d + '/keys.json', 'w').write('{}')
os.environ.update(STTARK_KIT_DIR=d + '/kit', STTARK_KIT_LOG=d + '/log', STTARK_MAIL_KEYS=d + '/keys.json')
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('wait', os.path.join(here, '../Resources/hooks/wait.py'))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
fails = 0


def check(what, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what)
    fails += not ok


# The stand-in prints a run as stream-json: the init (servers from $FAKE_SERVERS), then per prompt a tool call and
# its answer from the answers file, and keeps each prompt it was given.
fake = d + '/claude'
open(fake, 'w').write('''#!/usr/bin/python3
import json, os, sys
p = sys.stdin.read()
open(os.environ['FAKE_DIR'] + '/prompts', 'a').write(p + '\\n')
servers = json.loads(os.environ.get('FAKE_SERVERS') or '[]')
print(json.dumps({'type': 'system', 'subtype': 'init', 'mcp_servers': servers, 'tools': []}))
answers = json.load(open(os.environ['FAKE_DIR'] + '/answers.json'))
for key, (name, text, err) in answers.items():
    if key in p:
        print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': name}]}}))
        print(json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'is_error': err,
                                                                  'content': [{'type': 'text', 'text': text}]}]}}))
        break
print(json.dumps({'type': 'result', 'result': 'done'}))
''')
os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
w.CLAUDE = fake
os.environ['FAKE_DIR'] = d
WR = w.WR
DB = [{'name': 'sttark-production-database', 'status': 'failed'}]   # as a run from the Kit lists them


def answers(a, servers=DB):
    json.dump(a, open(d + '/answers.json', 'w'))
    os.environ['FAKE_SERVERS'] = json.dumps(servers)
    open(d + '/prompts', 'w').close()


nf = '{"error":"Failed to read email: {\\n \\"error\\": {\\n \\"code\\": 404,\\n \\"message\\": \\"Requested entity was not found.\\"'
mine = {'emails': [{'id': 'm2', 'thread_id': 'other', 'from': 'Me <me@x.com>', 'subject': 'Other'},
                   {'id': 'm1', 'thread_id': 'draft1', 'from': 'Me <me@x.com>', 'subject': 'Re: Wire request: JetFly balance'}]}

# 1. The error of the tool is the reason, though the init lists no Workrouter connector.
answers({'gmail_read_message': (WR + 'gmail_read_message', nf, True)})
_, res, why = w.haiku('Call %sgmail_read_message ...' % WR, [WR + 'gmail_read_message'])
check('a tool error is the reason, not the connector (not listed at the start): ' + why[:60],
      why.startswith('gmail_read_message answered an error') and 'did not load' not in why)

# 2. A thread started from a draft: the read answers 404, the search of the person's own messages gives the subject.
answers({'gmail_read_message': (WR + 'gmail_read_message', nf, True),
         'from:me after:': (WR + 'gmail_search', json.dumps(mine), False),
         'subject:(': (WR + 'gmail_search', json.dumps({'emails': []}), False)})
wt = {'kind': 'email-reply', 'target': 'draft1', 'set_at': 1763300000}
ok, what = w.check_email_reply(wt)
prompts = open(d + '/prompts').read()
check('the subject comes from the person\'s message in the thread, without "Re:": ' + wt.get('subject', ''),
      wt.get('subject') == 'Wire request: JetFly balance')
check('the person\'s messages are searched from 2 days before the wait', 'from:me after:%d' % (1763300000 - 2 * 86400) in prompts)
check('then the replies are searched by that subject', 'subject:(Wire request  JetFly balance)' in prompts and ok is False)

# 3. No message of the person in the thread: the check fails with the read's reason.
answers({'gmail_read_message': (WR + 'gmail_read_message', nf, True),
         'from:me after:': (WR + 'gmail_search', json.dumps({'emails': []}), False)})
try:
    w.check_email_reply({'kind': 'email-reply', 'target': 'gone', 'set_at': 1763300000})
    check('a thread that is not found fails', False)
except RuntimeError as e:
    check('a thread that is not found fails with the read\'s reason: ' + str(e)[:70],
          str(e).startswith('could not read the thread gone: gmail_read_message answered an error'))

# 4. A connector listed as failed, and no call: the connector is the reason.
answers({}, servers=DB + [{'name': 'claude.ai Sttark Workrouter', 'status': 'needs-auth'}])
_, _, why = w.haiku('Call %sgmail_search ...' % WR, [WR + 'gmail_search'])
check('a connector listed as not loaded is the reason: ' + why[:60], why.startswith('the Workrouter connector did not load in the check (needs-auth)'))
answers({})
_, _, why = w.haiku('Call %sgmail_search ...' % WR, [WR + 'gmail_search'])
check('no call and no connector listed: Haiku did not call it', why.startswith('Haiku did not call gmail_search'))

print('FAILED' if fails else 'all passed')
sys.exit(1 if fails else 0)
