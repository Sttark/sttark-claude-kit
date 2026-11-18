#!/usr/bin/python3
"""Tests claude-notify's Alerts switch and the "kept in the Kit app" path on copies: a temporary Kit folder and log,
STTARK_NOTIFY_DRY so nothing is sent. With Reach me by's alerts off, or nothing checked, no way is tried (no mail, no
Chat, no queue job for a Mac notice or a text, no PushNotification step), the message is kept in kept.json on its
session, the log says so, and claude-notify exits 0 with one line. The Kit's own message after a wait (wait.py) takes
the same path.
Run from the repo root: /usr/bin/python3 tools/notify-test.py"""
import importlib.util, json, os, subprocess, sys, tempfile

HOOKS = os.path.abspath('Resources/hooks')
d = tempfile.mkdtemp(prefix='kit-notify-')
LOG = os.path.join(d, 'log')
CSE = 'cse_01TestSession'
env = dict(os.environ, STTARK_KIT_DIR=d, STTARK_KIT_LOG=LOG, STTARK_NOTIFY_DRY='1', STTARK_WAIT_DRY='',
           CLAUDE_CODE_BRIDGE_SESSION_ID=CSE)
os.environ.update(STTARK_KIT_DIR=d, STTARK_KIT_LOG=LOG, STTARK_NOTIFY_DRY='1')


def state(reach):
    # the session's own alerts turned on by hand (each session starts off; tools/alerts-test.py tests that switch)
    json.dump({'reach': reach, 'sessions': {CSE: {'title': 'Order page', 'url': 'https://claude.ai/code/session_01Test'}},
               'alerts': {CSE: {'on': True, 'by': 'window', 'title': 'Order page'}}},
              open(os.path.join(d, 'state.json'), 'w'))


def notify(*a):
    r = subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'notify.py')] + list(a), capture_output=True, text=True, env=env)
    return r.returncode, (r.stdout + r.stderr).strip()


def kept():
    try:
        return json.load(open(os.path.join(d, 'kept.json')))['items']
    except OSError:
        return []


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_') + '_t', os.path.join(HOOKS, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


every = {'email': 'a@sttark.com', 'phone': '+1 864 555 0100', 'chat': 'https://chat.googleapis.com/v1/spaces/x'}

# on: it goes the ways checked, and nothing is kept
state(dict(every, ways=['email', 'chat']))
code, out = notify('PR merged', 'It merged. Nothing needed from you.')
assert code == 0 and 'would mail a@sttark.com' in out and 'would post' in out, out
assert not kept(), 'a message that went out is not kept'

# off: nothing goes out by any way, the push step too; it is kept on its session, with one line and exit 0
open(LOG, 'w').close()
state(dict(every, ways=['email', 'push', 'chat', 'text', 'mac'], alerts=False))
code, out = notify('PR merged', 'It merged.\n\nNothing needed from you.', '--link', 'https://github.com/x/y/pull/1')
assert code == 0, out
assert len(out.splitlines()) == 1 and out.startswith('Kept in the Sttark Claude Kit app') and 'alerts are off' in out, out
assert 'PushNotification' not in out and 'would' not in out, out
assert not os.path.exists(os.path.join(d, 'notify-queue')), 'no job for the app: no Mac notice, no text'
k = kept()
assert len(k) == 1 and k[0]['cse'] == CSE and k[0]['title'] == 'Order page' and k[0]['subject'] == 'PR merged', k
assert k[0]['body'] == 'It merged.\n\nNothing needed from you.' and k[0]['link'].endswith('/pull/1'), k
assert k[0]['from'] == 'session' and k[0]['why'] == 'alerts are off', k
lines = open(LOG).read().splitlines()
assert any(' notify Order page kept %s: alerts are off | PR merged' % k[0]['id'] in l for l in lines), lines
assert not any(' email ' in l or ' chat ' in l for l in lines if ' notify ' in l), lines
assert json.load(open(os.path.join(d, 'state.json'))).get('reach_sent') is None, 'not told, so no reach_sent'

# off keeps the ways and their settings: --show says so; --test sends nothing
code, out = notify('--show')
assert 'Alerts: off' in out and 'Email, Claude app, Google Chat, Text message, Mac notice' in out and 'a@sttark.com' in out, out
code, out = notify('--test')
assert code == 0 and 'no test was sent' in out, out
assert len(kept()) == 1, 'a test is never kept'

# on with nothing checked: kept too, with that reason
state(dict(every, ways=[]))
code, out = notify('Reply came', 'New Star replied.')
assert code == 0 and 'no way is checked under Reach me by' in out, out
assert kept()[-1]['why'] == 'no way is checked under Reach me by'

# the Kit's own message after a wait takes the same path
state(dict(every, ways=['email', 'mac'], alerts=False))
w = load('wait')
res = w.fallback({'id': 'w1', 'cse': CSE, 'title': 'Order page', 'what': 'mail from newstar.example', 'why': 'Mon 9 AM',
                  'kind': 'email-reply', 'target': 't', 'by': 1763000000, 'session_url': 'https://claude.ai/code/session_01Test'},
                 'New Star replied', False)
assert res == [('kit', (True, 'alerts are off'))] and w.sent_words(res) == 'kept one in the Kit app (alerts are off)', res
assert kept()[-1]['from'] == 'kit' and kept()[-1]['subject'] == 'mail from newstar.example', kept()[-1]
assert w.notified_since({'title': 'Order page'}, 0), 'a kept message counts as the session telling the person'

# held(): the one place that decides
n = load('notify')
ON = {CSE: {'on': True}}
assert n.held(CSE, ['email'], {'reach': {'alerts': False}, 'alerts': ON}) == 'alerts are off'
assert n.held(CSE, ['email'], {'reach': {}, 'alerts': ON}) == ''
assert n.held(CSE, [], {'reach': {}, 'alerts': ON}) == 'no way is checked under Reach me by'
assert n.held(CSE, ['email'], {'reach': {}}) == "this session's alerts are off", 'each session starts off'
assert n.held('', ['email'], {'reach': {}}) == '', 'no session: no switch'
assert n.alerts_on({}) and n.alerts_on({'reach': {'alerts': True}}) and not n.alerts_on({'reach': {'alerts': False}})

# old entries go
items = kept()
items[0]['at'] = 1700000000
json.dump({'items': items}, open(os.path.join(d, 'kept.json'), 'w'))
n.keep_in_kit('x', 'y', cse=CSE)
assert len(kept()) == len(items), 'the one older than 7 days went'
print('ok')
