#!/usr/bin/python3
"""Tests each session's own alerts switch in the hooks, on copies: a test folder and log (STTARK_KIT_DIR,
STTARK_KIT_LOG), notify.py dry (STTARK_NOTIFY_DRY: nothing is sent) and nothing brought back. A session whose alerts
are off takes the one path for a message that does not go out, notify.py held() and keep_in_kit(), with its own reason:
- claude-notify in that session: no way at all, exit 0, the kept line that tells the session the person reads it in
  the Kit app, the message in kept.json on that session with its reason, a "kept" line in the log, no reach_sent; the
  same command in a session whose alerts are on goes as before; a session_ id counts as its cse_ id; Reach me by's own
  Alerts switch off still gives its own reason first;
- wait.py: the Kit's own message when a session that came back sent none (FALLBACK), and when it could not come back,
  is kept on the session, and its log line says so; a kept message from the session counts as its message, so no
  FALLBACK follows;
- the reply watch's message for a session that could not come back is kept, and its log line says so.
(Progress check-ins never alert: they show only in the Kit app, so the switch has nothing to stop there.)
Run from the repo root: /usr/bin/python3 tools/alerts-test.py"""
import importlib.util, json, os, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, 'Resources', 'hooks')
d = tempfile.mkdtemp(prefix='kit-alerts-')
KIT, LOG = os.path.join(d, 'kit'), os.path.join(d, 'log')
os.makedirs(KIT)
os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_NOTIFY_DRY='1')
for k in ('STTARK_WAIT_DRY', 'CLAUDE_PID', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_BRIDGE_SESSION_ID'):
    os.environ.pop(k, None)
fails = 0
NOW = time.time()
WHY = "this session's alerts are off"


def check(what, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what)
    fails += not ok


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HOOKS, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def state():
    return json.load(open(os.path.join(KIT, 'state.json')))


def write(s):
    json.dump(s, open(os.path.join(KIT, 'state.json'), 'w'))


def log():
    try:
        return open(LOG).read()
    except OSError:
        return ''


def notify(*args, session=None):
    env = dict(os.environ)
    if session:
        env['CLAUDE_CODE_BRIDGE_SESSION_ID'] = session
    r = subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'notify.py')] + list(args), capture_output=True, text=True,
                       env=env, timeout=60)
    return r.returncode, r.stdout + r.stderr


write({'sessions': {'cse_01OrderPage': {'title': 'Order page', 'url': 'https://claude.ai/code/session_01OrderPage', 'at': NOW},
                    'cse_01PowderWatch': {'title': 'Powder watch', 'url': 'https://claude.ai/code/session_01PowderWatch', 'at': NOW}},
       'reach': {'ways': ['email', 'chat'], 'email': 'name@sttark.com', 'chat': 'https://chat.googleapis.com/v1/spaces/sample'},
       'alerts_off': {'cse_01PowderWatch': {'at': NOW - 60, 'by': 'window', 'title': 'Powder watch'}}})
n = load('notify')

# --- claude-notify ------------------------------------------------------------------------------------------------
code, out = notify('Snow report', '14 in fell overnight.', session='session_01PowderWatch')
check('its alerts off: claude-notify sends no way, exits 0 and prints the kept line with its reason: %r' % out,
      code == 0 and out.strip() == n.kept_line(WHY))
kept = n.kept('cse_01PowderWatch')
check('its alerts off: the message is kept on the session, with its words and its reason',
      len(kept) == 1 and kept[0]['subject'] == 'Snow report' and kept[0]['body'] == '14 in fell overnight.'
      and kept[0]['why'] == WHY and kept[0]['from'] == 'session')
check('its alerts off: one "kept" line under the session\'s name, with its reason and subject, and no line for a way',
      'notify Powder watch kept %s: %s | Snow report' % (kept[0]['id'] if kept else '?', WHY) in log()
      and ' email ok' not in log() and ' chat ok' not in log())
check('its alerts off: no reach_sent, so nothing says the person was told', 'reach_sent' not in state())
code, out = notify('Order page', 'The login works.', session='session_01OrderPage')
check('alerts on: the same command goes the ways picked, as before', code == 0 and 'Email: would mail name@sttark.com' in out
      and 'Google Chat: would post' in out and 'cse_01OrderPage' in (state().get('reach_sent') or {}))
check('alerts_off reads a session_ id as its cse_ id, and an empty id as on',
      n.alerts_off('session_01PowderWatch') and n.alerts_off('cse_01PowderWatch') and not n.alerts_off('cse_01OrderPage')
      and not n.alerts_off(''))
check('held(): its own reason; none for a session with alerts on; none for no session',
      n.held('cse_01PowderWatch') == WHY and n.held('cse_01OrderPage') == '' and n.held('') == '')
s = state()
s['reach']['alerts'] = False
check('held(): Reach me by\'s Alerts off comes first, for every session', n.held('cse_01PowderWatch', state=s) == 'alerts are off'
      and n.held('cse_01OrderPage', state=s) == 'alerts are off')
direct = n.send('Snow report', 'It reads the snow report.', title='Powder watch',
                url='https://claude.ai/code/session_01PowderWatch', cse='cse_01PowderWatch')
check('send() itself, with the session given: kept, no way: %r' % direct,
      direct == [(n.IN_KIT, (True, WHY))] and len(n.kept('cse_01PowderWatch')) == 2)

# --- wait.py: the Kit's own message ------------------------------------------------------------------------------------
w = load('wait')


class NoWatch(object):
    @staticmethod
    def check(_):
        pass

    @staticmethod
    def mark_told(*_):
        pass


real_load = w.load
w.load = lambda name: NoWatch if name == 'watch' else real_load(name)


def back(wid, cse, title, back_at):
    return {'id': wid, 'kind': 'at', 'at': NOW - 3600, 'cse': cse, 'title': title, 'why': 'The first big storm',
            'what': '12 in of new snow', 'set_at': NOW - 86400, 'stage': 'back', 'back_at': back_at,
            'session_url': 'https://claude.ai/code/session_' + cse[4:]}


s = state()
s['sessions']['cse_01SnowPlan'] = {'title': 'Snow plan', 'url': 'https://claude.ai/code/session_01SnowPlan', 'at': NOW}
s['alerts_off']['cse_01SnowPlan'] = {'at': NOW, 'by': 'phone', 'title': 'Snow plan'}
# Powder watch came back before its kept claude-notify above; Snow plan came back 15 minutes ago and said nothing
s['waits'] = {'p1': back('p1', 'cse_01PowderWatch', 'Powder watch', NOW - 1000),
              'p2': back('p2', 'cse_01SnowPlan', 'Snow plan', time.time() - w.FALLBACK - 5)}
write(s)
check('a kept claude-notify after it came back counts as the session\'s message', w.notified_since(state()['waits']['p1'], NOW - 1000))
check('a session that came back and said nothing has not told the person', not w.notified_since(state()['waits']['p2'], NOW - w.FALLBACK - 5))
mark = len(log())
w.check()
after = log()[mark:]
check('no FALLBACK for the session that sent its message (kept): the wait just ends',
      'p1' not in (state().get('waits') or {}) and 'Powder watch' not in after)
snow = n.kept('cse_01SnowPlan')
check('FALLBACK for the session that said nothing, whose alerts are off: kept on it as the Kit\'s, and the wait line says so: %r' % after,
      len(snow) == 1 and snow[0]['from'] == 'kit' and snow[0]['why'] == WHY
      and ('p2 cse_01SnowPl "Snow plan" sent no message after coming back; the Kit kept one in the Kit app (%s)' % WHY) in after
      and 'p2' not in (state().get('waits') or {}))
res = w.fallback({'id': 'p3', 'kind': 'at', 'at': NOW, 'cse': 'cse_01OrderPage', 'title': 'Order page', 'why': 'x'},
                 'The time you set came', False)
check('wait.py fallback() for a session with alerts on: it goes the ways (dry), not kept', res and res[0][0] != n.IN_KIT)

# --- the reply watch's message for a session that could not come back ---------------------------------------------------
wt = load('watch')
wt.seen = lambda e, m, cache: False


class Back(object):
    @staticmethod
    def peek():
        return {}

    @staticmethod
    def bring_back(w, prompt):
        return False


e = {'pending': [{'id': 'm1', 'kind': 'mail', 'from': 'snow.example', 'subject': 'Storm total', 'snippet': '14 in'}],
     'transcript': '/nonexistent.jsonl', 'title': 'Powder watch', 'url': 'https://claude.ai/code/session_01PowderWatch'}
wt.deliver_one(Back, 'cse_01PowderWatch', e, {}, time.time())
check('the reply watch: it could not come back, so the Kit kept the message on the session',
      ('could not come back; the Kit kept the message in the Kit app (%s)' % WHY) in log()
      and n.kept('cse_01PowderWatch')[-1]['subject'] == 'New messages for Powder watch')

print('all passed' if not fails else '%d failed' % fails)
sys.exit(1 if fails else 0)
