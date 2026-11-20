#!/usr/bin/python3
"""Tests the Archived page's list (effort-hook.py --archived) and claude-wait --unarchive on copies: a temporary
Kit folder and log, a temporary ~/.claude with made-up conversations, a stand-in for Claude's list of sessions
(STTARK_ARCHIVED_TEST) and STTARK_WAIT_DRY, so nothing is read from Claude, started or unarchived.
Checks which archived sessions are listed (their conversation on this Mac, found from the Kit's record or a
bridge-session line; no Kit wait; no scheduled run; a conversation that moved shows once), the order, the folder,
what it was doing, the link, that the rev stays the same when nothing changed, and each --unarchive result.
Run from the repo root: /usr/bin/python3 tools/archived-test.py"""
import json, os, subprocess, sys, tempfile, time

ROOT = os.getcwd()
HOOK = os.path.join(ROOT, 'Resources/hooks/effort-hook.py')
WAIT = os.path.join(ROOT, 'Resources/hooks/wait.py')
tmp = tempfile.mkdtemp(prefix='kit-archived-')
kit, claude = os.path.join(tmp, 'kit'), os.path.join(tmp, 'claude')
proj = os.path.join(claude, 'projects', '-Users-test-src')
os.makedirs(kit)
os.makedirs(proj)
LIST = os.path.join(tmp, 'sessions.json')
ENV = dict(os.environ, STTARK_KIT_DIR=kit, STTARK_KIT_LOG=os.path.join(tmp, 'kit.log'), STTARK_CLAUDE_DIR=claude,
           STTARK_ARCHIVED_TEST=LIST, STTARK_WAIT_DRY='1')
fails = []


def check(what, ok):
    print(('ok    ' if ok else 'FAIL  ') + what)
    if not ok:
        fails.append(what)


def conv(name, cwd, links=()):
    p = os.path.join(proj, name + '.jsonl')
    with open(p, 'w') as f:
        f.write(json.dumps({'type': 'user', 'cwd': cwd, 'sessionId': name, 'message': {'content': 'hello'}}) + '\n')
        for i, link in enumerate(links):  # Claude Code's own lines are compact; the Kit's have spaces
            line = {'type': 'bridge-session', 'sessionId': name, 'bridgeSessionId': link, 'lastSequenceNum': 0}
            f.write((json.dumps(line, separators=(',', ':')) if i % 2 == 0 else json.dumps(line)) + '\n')
    return p


def chat(cse, status, minutes_ago, title, doing='', **kv):
    t = time.strftime('%Y-%m-%dT%H:%M:%S.000000Z', time.gmtime(time.time() - minutes_ago * 60))
    c = {'id': cse, 'status': status, 'title': title, 'last_event_at': t, 'updated_at': t, 'created_at': t,
         'environment_kind': 'bridge', 'tags': [], 'external_metadata': {'post_turn_summary': {'recent_action': doing}}}
    c.update(kv)
    return c


def run(script, *a):
    r = subprocess.run(['/usr/bin/python3', script] + list(a), capture_output=True, text=True, env=ENV)
    return r.returncode, (r.stdout + r.stderr).strip()


def listing():
    with open(os.path.join(kit, 'archived.json')) as f:
        return json.load(f)


a = conv('aaaa1111', '/Users/test/src/order-page')
conv('cccc3333', '/Users/test/src/labels', links=['cse_C'])
conv('mmmm5555', '/Users/test/src/moved', links=['cse_M', 'cse_N'])
w = conv('wwww7777', '/Users/test/src/supplier')
state = {
    'sessions': {'cse_A': {'title': 'Order page', 'transcript': a},
                 'cse_B': {'title': 'Gone file', 'transcript': os.path.join(proj, 'nothere.jsonl')}},
    'waits': {'w1': {'id': 'w1', 'cse': 'cse_W', 'transcript': w, 'title': 'Supplier reply', 'kind': 'at', 'at': time.time() + 3600}},
}
json.dump(state, open(os.path.join(kit, 'state.json'), 'w'))
json.dump({'sessions': [
    chat('cse_A', 'archived', 30, 'Order page', doing='Opened the pull request for the login fix.'),
    chat('cse_B', 'archived', 20, 'Gone file'),
    chat('cse_C', 'archived', 10, 'Label sizes', doing='Waits for the new label stock.'),
    chat('cse_W', 'archived', 5, 'Supplier reply'),
    chat('cse_S', 'archived', 4, 'Nightly report', trigger_id='trig_1'),
    chat('cse_R', 'archived', 3, 'Routine run', tags=['routine:daily']),
    chat('cse_M', 'archived', 40, 'Old link'),
    chat('cse_N', 'active', 1, 'New link'),
    chat('cse_O', 'active', 2, 'Open one'),
    chat('cse_X', 'archived', 50, 'Cloud one', environment_kind='anthropic_cloud'),
]}, open(LIST, 'w'))

code, out = run(HOOK, '--archived')
check('--archived runs: ' + out, code == 0)
got = listing()
ids = [x['cse'] for x in got['items']]
check('lists only archived sessions with their conversation here, no wait, no scheduled run, no moved link: %s' % ids,
      ids == ['cse_C', 'cse_A'])
item = {x['cse']: x for x in got['items']}
check('found from the Kit\'s record, with its folder', item['cse_A']['transcript'] == a and item['cse_A']['folder'] == '/Users/test/src/order-page')
check('found from a bridge-session line', item['cse_C']['transcript'].endswith('cccc3333.jsonl') and item['cse_C']['folder'] == '/Users/test/src/labels')
check('what it was doing', item['cse_A']['doing'] == 'Opened the pull request for the login fix.')
check('its link and time', item['cse_A']['url'] == 'https://claude.ai/code/session_A' and item['cse_A']['archived_at'] > 0)
check('the file has at, rev and items', set(got) == {'at', 'rev', 'items'} and len(got['rev']) == 16)
rev, at = got['rev'], got['at']
run(HOOK, '--archived')
check('nothing changed: the same rev, and no new write within a minute', listing()['rev'] == rev and listing()['at'] == at)

code, out = run(WAIT, '--unarchive', 'cse_O')
check('--unarchive of a session that is not archived: gone (%d) %s' % (code, out), code == 3 and out == 'It is not archived now. It is in your list.')
code, out = run(WAIT, '--unarchive', 'cse_B', '--by', 'phone')
check('--unarchive of one with no conversation here: not here (%d) %s' % (code, out),
      code == 2 and out == 'Its conversation is not on this Mac, so this Mac cannot bring it back.')
code, out = run(WAIT, '--unarchive', 'cse_A')
check('--unarchive of a listed one, dry: would bring it back (%d) %s' % (code, out), code == 0 and 'would bring cse_A back' in out)
os.remove(item['cse_C']['transcript'])
code, out = run(WAIT, '--unarchive', 'cse_C')
check('its conversation was deleted since the list: not here, and it leaves the list (%d)' % code,
      code == 2 and [x['cse'] for x in listing()['items']] == ['cse_A'] and listing()['rev'] != rev)
before = listing()
before['items'][0]['doing'] = 'Something else now.'
before['items'][0]['transcript'] = '/elsewhere/a.jsonl'
import importlib.util
spec = importlib.util.spec_from_file_location('e', HOOK)
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
check('the rev is the phone\'s view: what it was doing and the paths do not change it, the folder\'s name does',
      e.archived_rev(before['items']) == listing()['rev']
      and e.archived_rev([dict(before['items'][0], folder='/Users/test/src/other')]) != listing()['rev'])
code, out = run(WAIT, '--unarchive', 'cse_Z')
check('a session whose status can\'t be read is not started (%d)' % code, code == 1 and 'did not answer' in out)
code, out = run(WAIT, '--unarchive', 'nonsense')
check('a bad id is refused', code == 4 and 'Usage' in out)
log = open(os.path.join(tmp, 'kit.log')).read()
check('each refusal is logged as a wait line', log.count('wait   cse_') == 4 and '(phone)' in log and 'not archived now' in log)

code, out = run(WAIT, '--unarchive', 'cse_W')
check('--unarchive of an archived one that waits, not in the list: its wait gives the conversation (%d) %s' % (code, out),
      code == 0 and 'would bring cse_W back from ' + w in out)
check('its wait stays open', 'w1' in json.load(open(os.path.join(kit, 'state.json')))['waits'])

state['sessions']['cse_W'] = {'title': 'Supplier reply', 'transcript': w}  # its hooks recorded it too
json.dump(dict(state, waits={}), open(os.path.join(kit, 'state.json'), 'w'))
run(HOOK, '--archived')
check('a wait that ends: the session shows in the list again', 'cse_W' in [x['cse'] for x in listing()['items']])

print('ok' if not fails else '%d failed' % len(fails))
sys.exit(1 if fails else 0)
