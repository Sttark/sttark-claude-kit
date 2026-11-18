#!/usr/bin/python3
"""Tests One session for the same work (Resources/hooks/same-work.py) on copies: a test Kit folder and log
(STTARK_KIT_DIR, STTARK_KIT_LOG), a test ~/.claude with made-up conversations and live-session records
(STTARK_CLAUDE_DIR), a stand-in usage read (STTARK_LIMIT_TEST), a stand-in for the Haiku call (STTARK_SAME_MODEL) and
a stand-in for wait.py's bring_back(), so nothing is started, typed or sent and no model is called. It checks:
- a first prompt that is the work of an open session: the context that has Claude ask, with the exact question, the
  header and both options, the open session named by its name and age; the log line; the prompt kept for the answer;
- only the first prompt: a session's second prompt, a session already looked at, and a long conversation stop early;
- nothing at all for the Kit's own prompts, task notices, commands, the switch off, a session with no Remote Control
  link, a prompt with a picture, one word, and a session held at the usage limit;
- what Haiku reads: the open sessions with their names, folders, first and latest prompts; never the session itself,
  an archived one, one whose conversation is not on this Mac, one in another repository, or one open in a terminal;
- Haiku's NONE, a number out of range, an answer it can't read, and a failed call: nothing asked, a log line each;
- the answer: Send to delivers the person's prompt word for word through bring_back() to that session's link and has
  Claude reply with one line and the link; Keep here goes on and never asks again; another question is left alone;
- a session in a turn: the prompt waits, and wait.py's minute check sends it when the turn ends; a prompt that can't
  go after 7 days is dropped with a log line;
- install-hooks.py adds the two entries and takes them out with --remove, on a temporary home folder;
- the whole hook as Claude Code runs it, JSON in and out, with STTARK_SAME_DRY (nothing sent).
Run from the repo root: /usr/bin/python3 tools/same-work-test.py"""
import importlib.util, json, os, stat, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, 'Resources', 'hooks')
d = os.path.realpath(tempfile.mkdtemp(prefix='kit-same-'))
KIT, LOG, CLAUDE = os.path.join(d, 'kit'), os.path.join(d, 'log'), os.path.join(d, 'claude')
for p in (KIT, os.path.join(CLAUDE, 'projects', 'p'), os.path.join(CLAUDE, 'sessions')):
    os.makedirs(p)
USAGE = os.path.join(d, 'usage.json')
json.dump({'extra_usage': {'is_enabled': False}, 'limits': []}, open(USAGE, 'w'))
STUB, STUB_IN = os.path.join(d, 'model'), os.path.join(d, 'model-in.txt')
with open(STUB, 'w') as f:
    f.write('#!/bin/sh\ncat > "$STUB_IN"\n[ -n "$STUB_SLEEP" ] && sleep "$STUB_SLEEP"\necho "$STUB_ANSWER"\nexit "${STUB_EXIT:-0}"\n')
os.chmod(STUB, os.stat(STUB).st_mode | stat.S_IEXEC)
for k in ('CLAUDE_PID', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_BRIDGE_SESSION_ID', 'STTARK_SAME_DRY', 'STTARK_WAIT_DRY',
          'EFFORT_JUDGE', 'STTARK_ARCHIVED_TEST'):
    os.environ.pop(k, None)
os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_CLAUDE_DIR=CLAUDE, STTARK_LIMIT_TEST=USAGE,
                  STTARK_SAME_MODEL=STUB, STUB_IN=STUB_IN, STUB_ANSWER='NONE - nothing alike')
fails = 0
NOW = time.time()


def check(what, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what)
    fails += not ok


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HOOKS, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def log():
    try:
        return open(LOG).read()
    except OSError:
        return ''


def line(**kv):
    return json.dumps(kv, separators=(',', ':')) + '\n'


def prompt_line(text, cwd, extra=None):
    x = {'type': 'user', 'message': {'role': 'user', 'content': text}, 'cwd': cwd, 'isSidechain': False,
         'timestamp': '2026-11-18T10:00:00.000Z'}
    x.update(extra or {})
    return line(**x)


def reply_line(text, cwd):
    return line(type='assistant', message={'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}, cwd=cwd)


def conversation(name, cwd, prompts, pad=0):
    """A made-up saved conversation: the person's prompts, Claude's replies, a tool result, an agent's line."""
    p = os.path.join(CLAUDE, 'projects', 'p', name + '.jsonl')
    with open(p, 'w') as f:
        f.write(line(type='custom-title', customTitle=name))
        for i, t in enumerate(prompts):
            f.write(prompt_line(t, cwd))
            f.write(reply_line('Done step %d.' % i, cwd))
            f.write(line(type='user', message={'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'x', 'content': 'ok'}]},
                         cwd=cwd, toolUseResult={'stdout': 'ok'}))
            f.write(line(type='user', isSidechain=True, message={'role': 'user', 'content': 'an agent brief'}, cwd=cwd))
            f.write('x' * pad + '\n' if pad else '')
    return p


# folders: two repositories, a worktree of one, and the folder that holds them
SRC = os.path.join(d, 'src')
for r in ('order-site', 'press-board'):
    os.makedirs(os.path.join(SRC, r, '.git', 'worktrees', 'agent-x'))
TREE = os.path.join(SRC, 'order-site', '.claude', 'worktrees', 'agent-x')
os.makedirs(TREE)
open(os.path.join(TREE, '.git'), 'w').write('gitdir: %s\n' % os.path.join(SRC, 'order-site', '.git', 'worktrees', 'agent-x'))

ORDER = conversation('aaaa1111-order', os.path.join(SRC, 'order-site'),
                     ['Build the order form for the web shop', 'Add a field for the PO number', 'Fix the color of the submit button'])
PRESS = conversation('bbbb2222-press', os.path.join(SRC, 'press-board'), ['Make a job board for Press 2'])
DOCK = conversation('cccc3333-dock', SRC, ['The dock door 3 motor trips its breaker'])
OLD = conversation('dddd4444-old', SRC, ['Quote for the core supplier'])
os.makedirs(os.path.join(d, 'elsewhere'))
# the dock door session runs now in a terminal (a live process that is not the server's), so the Kit can't type in it
json.dump({'pid': os.getpid(), 'sessionId': 'cccc3333-dock', 'entrypoint': 'cli', 'kind': 'interactive'},
          open(os.path.join(CLAUDE, 'sessions', '%d.json' % os.getpid()), 'w'))
# the order page runs in the server (sdk-cli): the Kit can send to it
json.dump({'pid': os.getppid(), 'sessionId': 'aaaa1111-order', 'entrypoint': 'sdk-cli', 'kind': 'interactive'},
          open(os.path.join(CLAUDE, 'sessions', '%d.json' % os.getppid()), 'w'))


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(t))


def state(**extra):
    s = {'sessions': {
        'cse_01OrderPage': {'title': 'Order page', 'transcript': ORDER, 'reason': 'Multi-file UI change',
                            'url': 'https://claude.ai/code/session_01OrderPage', 'at': NOW - 600},
        'cse_01PressBoard': {'title': 'Press 2 job board', 'transcript': PRESS, 'at': NOW - 3600},
        'cse_01DockDoor': {'title': 'Dock door repair', 'transcript': DOCK, 'at': NOW - 60},
        'cse_01Archived': {'title': 'Core supplier quote', 'transcript': OLD, 'at': NOW - 86400},
        'cse_01Cloud': {'title': 'Cloud work', 'transcript': '/nowhere/eeee.jsonl', 'at': NOW - 60}},
        'app_list': {'at': NOW, 'sessions': [
            {'id': 'cse_01NewOne', 'title': '', 'bucket': 'working', 'last': iso(NOW)},
            {'id': 'cse_01OrderPage', 'title': 'Order page', 'bucket': 'idle', 'last': iso(NOW - 600)},
            {'id': 'cse_01PressBoard', 'title': 'Press 2 job board', 'bucket': 'idle', 'last': iso(NOW - 3600)},
            {'id': 'cse_01DockDoor', 'title': 'Dock door repair', 'bucket': 'idle', 'last': iso(NOW - 60)},
            {'id': 'cse_01Cloud', 'title': 'Cloud work', 'bucket': 'idle', 'last': iso(NOW - 60)}]}}
    s.update(extra)
    json.dump(s, open(os.path.join(KIT, 'state.json'), 'w'))


state()
os.environ['CLAUDE_CODE_BRIDGE_SESSION_ID'] = 'session_01NewOne'
m = load('same-work')
FIRST = 'Add a coupon code field to the order form'
n_new = [0]


def new_session(prompt=FIRST, cwd=SRC, lines=None):
    """A new session's hook input; its conversation holds `lines` (none yet: the file does not exist)."""
    n_new[0] += 1
    sid = 'ffff%04d-new' % n_new[0]
    tp = os.path.join(CLAUDE, 'projects', 'p', sid + '.jsonl')
    if lines is not None:
        open(tp, 'w').write(''.join(lines))
    return {'session_id': sid, 'transcript_path': tp, 'cwd': cwd, 'hook_event_name': 'UserPromptSubmit', 'prompt': prompt}


def ask(data, answer=None):
    if answer is not None:
        os.environ['STUB_ANSWER'] = answer
    try:
        os.unlink(STUB_IN)
    except OSError:
        pass
    return m.on_prompt(data)


def model_in():
    try:
        return open(STUB_IN).read()
    except OSError:
        return None


# --- a match --------------------------------------------------------------------------------------------------------
data = new_session()
out = ask(data, '1 - the same order site and its order form')
ctx = ((out or {}).get('hookSpecificOutput') or {}).get('additionalContext', '')
check('a first prompt that is the work of an open session gets context for Claude: %r' % ctx[:100],
      out and out['hookSpecificOutput']['hookEventName'] == 'UserPromptSubmit' and ctx.startswith('[Sttark Claude Kit] Same work'))
check('the context names the question word for word, with the open session\'s name and age',
      'question: "This looks like the same work as “Order page”, a session that started just now. Where do you want this prompt?"' in ctx)
check('one question, header "Same work", two options in order: Send to Order page, then Keep here',
      'header: "Same work"' in ctx and 'multiSelect: false' in ctx and ctx.index('label: "Send to Order page"') < ctx.index('label: "Keep here"')
      and 'as if you typed it there' in ctx)
check('Claude asks before anything else, and the link of the open session is in the context',
      'Your first step, before any other tool and before any text: call the AskUserQuestion tool' in ctx
      and 'https://claude.ai/code/session_01OrderPage' in ctx)
seen = model_in() or ''
check('Haiku reads the prompt and the open sessions with their names, folders, first and latest prompts',
      FIRST in seen and '"Order page"' in seen and 'repository order-site' in seen
      and 'It started with: "Build the order form for the web shop"' in seen
      and '"Fix the color of the submit button"' in seen and 'Multi-file UI change' in seen and '"Press 2 job board"' in seen)
check('never the session itself, an archived one, one not on this Mac, or one open in a terminal',
      'Core supplier quote' not in seen and 'Cloud work' not in seen and 'Dock door repair' not in seen
      and seen.count('\n1. ') == 1 and '\n3. ' not in seen)
check('the new session\'s folder holds many repositories, and Haiku is told so', 'not one repository' in seen)
check('the match is in the log, with the open session, its age, the reason and the prompt',
      'same   cse_01NewOne asks: same work as cse_01OrderPage "Order page", started just now (' in log()
      and '- the same order site and its order form | Add a coupon code field to the order form' in log())
rec = json.load(open(os.path.join(KIT, 'same-work.json')))
a = rec['asked'].get(data['session_id']) or {}
check('the question is kept for the answer, with the prompt word for word on this Mac',
      a.get('target', {}).get('cse') == 'cse_01OrderPage' and open(a.get('prompt_file', '/none')).read() == FIRST
      and data['session_id'] in rec['checked'])
check('the same session is never looked at again', ask(dict(data, prompt='And make it red')) is None and model_in() is None)

# --- only the first prompt -------------------------------------------------------------------------------------------
second = new_session('Now the coupon list page', lines=[prompt_line('Add a coupon code field', SRC), reply_line('Done.', SRC)])
check('a second prompt is never checked', ask(second, '1 - same') is None and model_in() is None)
saved = new_session(FIRST, lines=[line(type='queue-operation', operation='enqueue', content=FIRST), prompt_line(FIRST, SRC)])
check('a first prompt already saved in its conversation still counts as the first', ask(saved, '1 - same') is not None)
big = conversation('9999big-long', SRC, ['Start of a long one', 'More'] + ['next %d' % i for i in range(400)], pad=20000)
t0 = time.time()
r = m.first_look(big, 'Something new')
check('a long conversation stops at its first prompt: %.3f s' % (time.time() - t0), r == (False, False) and time.time() - t0 < 0.2)

# --- never asked ---------------------------------------------------------------------------------------------------
for what, x in [('the Kit\'s own prompt', new_session('[Sttark Claude Kit] A wait you handed to the Kit has ended.')),
                ('a task notice', new_session('<task-notification>agent done</task-notification>')),
                ('a command', new_session('/model haiku'))]:
    check(what + ': nothing, no model call', ask(x, '1 - same') is None and model_in() is None)
state(same_work=False)
check('the switch off (same_work false in the state): nothing, no model call', ask(new_session(), '1 - same') is None and model_in() is None)
state()
os.environ.pop('CLAUDE_CODE_BRIDGE_SESSION_ID')
check('a session with no Remote Control link: nothing', ask(new_session(), '1 - same') is None and model_in() is None)
os.environ['CLAUDE_CODE_BRIDGE_SESSION_ID'] = 'session_01NewOne'
pic = new_session(FIRST, lines=[line(type='queue-operation', operation='enqueue')])
check('a prompt that came with a picture (queued with no words): nothing, and a log line',
      ask(pic, '1 - same') is None and model_in() is None and 'not checked: its first prompt has a picture or a file' in log())
pic2 = new_session(FIRST, lines=[prompt_line([{'type': 'image', 'source': {}}, {'type': 'text', 'text': FIRST}], SRC, {'imagePasteIds': [1]})])
check('a saved prompt with a picture: nothing', ask(pic2, '1 - same') is None and model_in() is None)
check('one word: nothing, and a log line', ask(new_session('hello'), '1 - same') is None and model_in() is None
      and 'not checked: its first prompt is one word' in log())
held = os.path.join(d, 'held.json')
json.dump({'extra_usage': {'is_enabled': True}, 'limits': [{'kind': 'session', 'percent': 100,
                                                             'resets_at': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(NOW + 3600))}]},
          open(held, 'w'))
os.environ['STTARK_LIMIT_TEST'] = held
check('at the usage limit: nothing, no model call, and a log line', ask(new_session(), '1 - same') is None and model_in() is None
      and 'not checked: skipped at the usage limit' in log())
os.environ['STTARK_LIMIT_TEST'] = USAGE

# --- the repository, and what Haiku says -----------------------------------------------------------------------------------
x = new_session('Add the coupon field', cwd=TREE)
ask(x, 'NONE - x')
seen = model_in() or ''
check('in a worktree of the order site: the order page only, not the press board in another repository',
      '"Order page"' in seen and 'Press 2 job board' not in seen and 'repository order-site' in seen.split('Open sessions:')[0])
x = new_session('Show the jobs of Press 2', cwd=os.path.join(SRC, 'press-board'))
ask(x, 'NONE - x')
check('in the press board repository: the press board only', 'Press 2 job board' in (model_in() or '') and 'Order page' not in (model_in() or ''))
check('Haiku says NONE: nothing asked, a log line with the reason',
      ask(new_session(), 'NONE - a new topic') is None and 'no match among 2 open session(s)' in log() and '- a new topic |' in log())
check('a number out of range: nothing asked, a log line', ask(new_session(), '7 - same') is None and 'an answer it could not read' in log())
check('an answer it can\'t read: nothing asked', ask(new_session(), 'Maybe the first one') is None)
os.environ.update(STUB_EXIT='1', STUB_ANSWER='')
check('a failed call: nothing asked, and a log line', ask(new_session()) is None and 'check failed: RuntimeError: exit 1' in log())
os.environ.pop('STUB_EXIT')
state(app_list={'at': NOW, 'sessions': [{'id': 'cse_01DockDoor', 'title': 'Dock door repair', 'last': iso(NOW)}]})
check('only a session open in a terminal: no model call, and the log says why',
      ask(new_session(), '1 - same') is None and model_in() is None and 'open in the Claude desktop app or a terminal' in log())
state(app_list={'at': NOW - 7200, 'sessions': []})
archived = os.path.join(d, 'list.json')
json.dump({'sessions': [{'id': 'cse_01OrderPage', 'title': 'Order page', 'status': 'active', 'last_event_at': iso(NOW)}]}, open(archived, 'w'))
os.environ['STTARK_ARCHIVED_TEST'] = archived
check('an old list of the Claude app\'s sessions is read again first', ask(new_session(), '1 - same') is not None
      and json.load(open(os.path.join(KIT, 'state.json')))['app_list']['sessions'][0]['id'] == 'cse_01OrderPage')
os.environ.pop('STTARK_ARCHIVED_TEST')
state()

# --- the answer ----------------------------------------------------------------------------------------------------------
sent = []


def fake_bring_back(w, prompt):
    sent.append((w, prompt))
    return True


m.bring_back = fake_bring_back
q = a['question']


def answer(sid, v, question=q):
    return m.on_answer({'session_id': sid, 'hook_event_name': 'PostToolUse', 'tool_name': 'AskUserQuestion',
                        'tool_input': {'questions': [{'question': question}]},
                        'tool_response': {'questions': [{'question': question}], 'answers': {question: v}}})


check('another question in the same session is left alone', answer(data['session_id'], 'Blue', 'Which color?') is None and not sent)
out = answer(data['session_id'], 'Send to Order page')
ctx = ((out or {}).get('hookSpecificOutput') or {}).get('additionalContext', '')
check('Send to: the person\'s prompt goes word for word to that session through bring_back()',
      len(sent) == 1 and sent[0][1] == FIRST and sent[0][0]['cse'] == 'cse_01OrderPage' and sent[0][0]['transcript'] == ORDER
      and sent[0][0]['cwd'] == os.path.join(SRC, 'order-site'))
check('Claude replies with one line and the link, and does nothing else: %r' % ctx[-80:],
      'Reply with this one line and nothing else, and do no other work in this session:\nSent to “Order page”: '
      'https://claude.ai/code/session_01OrderPage' in ctx and out['hookSpecificOutput']['hookEventName'] == 'PostToolUse')
check('the send is in the log, under the open session', 'same   cse_01OrderPage "Order page" got the first prompt of cse_01NewOne: the person chose Send to' in log())
check('a second answer to the same question does nothing', answer(data['session_id'], 'Send to Order page') is None and len(sent) == 1)
check('nothing in the session is archived: bring_back() is the only start, and nothing else is called', len(sent) == 1)

keep = new_session()
ask(keep, '1 - same')
out = answer(keep['session_id'], 'Keep here', m.read()['asked'][keep['session_id']]['question'])
ctx = ((out or {}).get('hookSpecificOutput') or {}).get('additionalContext', '')
check('Keep here: Claude goes on with the prompt, nothing is sent, and the log says so',
      'Go on with their first prompt now' in ctx and len(sent) == 1
      and 'cse_01NewOne keeps its first prompt here: the person chose Keep here, not "Order page"' in log())
check('Keep here: never asked again', ask(dict(keep, prompt='More on that'), '1 - same') is None and model_in() is None)
other = new_session()
ask(other, '1 - same')
check('an answer in the person\'s own words sends nothing', answer(other['session_id'], 'Not sure yet', m.read()['asked'][other['session_id']]['question']) is None
      and len(sent) == 1 and 'answered the same work question in its own words' in log())
text = new_session()
ask(text, '1 - same')
qt = m.read()['asked'][text['session_id']]['question']
out = m.on_answer({'session_id': text['session_id'], 'hook_event_name': 'PostToolUse', 'tool_name': 'AskUserQuestion',
                   'tool_response': 'Your questions have been answered: "%s"="Send to Order page". You can now continue.' % qt})
check('an answer that comes back as text is read too', out is not None and len(sent) == 2)

# --- a session in a turn: the prompt waits for it ----------------------------------------------------------------------------
busy = new_session('Add a coupon code field to the cart page too')
ask(busy, '1 - same')


def busy_bring_back(w, prompt):
    raise RuntimeError('busy')


m.bring_back = busy_bring_back
out = answer(busy['session_id'], 'Send to Order page', m.read()['asked'][busy['session_id']]['question'])
ctx = ((out or {}).get('hookSpecificOutput') or {}).get('additionalContext', '')
check('in a turn: the prompt waits, and Claude says it runs when the turn ends',
      busy['session_id'] in m.read()['queue'] and 'It runs there when its current turn ends: https://claude.ai/code/session_01OrderPage' in ctx
      and 'gets the first prompt of cse_01NewOne when its turn ends' in log())
check('the minute check while it still works: the prompt waits', m.deliver() == 0 and busy['session_id'] in m.read()['queue'])
m.bring_back = fake_bring_back
check('the minute check after the turn: the prompt goes, word for word, and leaves the queue',
      m.deliver() == 1 and sent[-1][1] == 'Add a coupon code field to the cart page too' and not m.read()['queue']
      and '"Order page" got the first prompt of cse_01NewOne, which waited ' in log())


def failed_bring_back(w, prompt):
    raise RuntimeError('its copy in the server did not stop')


late = new_session('Coupon codes in the order emails')
ask(late, '1 - same')
m.bring_back = failed_bring_back
out = answer(late['session_id'], 'Send to Order page', m.read()['asked'][late['session_id']]['question'])
ctx = ((out or {}).get('hookSpecificOutput') or {}).get('additionalContext', '')
check('a start that fails: the prompt waits, Claude says so, the log says why',
      late['session_id'] in m.read()['queue'] and 'It runs there as soon as the Kit can start it' in ctx
      and 'it could not start now: its copy in the server did not stop' in log())
before = log().count('could not start for the first prompt')
m.deliver()
m.deliver()
check('the same reason is logged once, not each minute', log().count('could not start for the first prompt') == before)
with m.record() as r:
    r['queue'][late['session_id']]['at'] = NOW - 8 * 86400 + 60
    r['asked'][late['session_id']]['at'] = NOW
check('a prompt that could not go in 7 days is dropped, with a log line', m.deliver(now=NOW + 120) == 0 and not m.read()['queue']
      and 'never got the first prompt of cse_01NewOne: its copy in the server did not stop; dropped after 7 days' in log())

# --- wait.py's minute check sends what waits ---------------------------------------------------------------------------------
w = load('wait')


class NoWatch(object):
    @staticmethod
    def check(_):
        pass


real = w.load
w.load = lambda name: NoWatch if name == 'watch' else real(name)
with m.record() as r:
    r['queue']['gggg0001-new'] = {'at': time.time(), 'from_sid': 'gggg0001-new', 'from_cse': 'cse_01NewTwo',
                                  'prompt_file': a['prompt_file'], 'target': a['target'], 'tries': 1}
os.environ['STTARK_SAME_DRY'] = '1'
w.check()
os.environ.pop('STTARK_SAME_DRY')
check('wait.py\'s minute check sends a prompt that waits (dry here: nothing sent)', not m.read()['queue']
      and 'got the first prompt of cse_01NewTwo, which waited under a minute (dry: nothing sent)' in log())

# --- the whole hook, as Claude Code runs it ------------------------------------------------------------------------------------
env = dict(os.environ, STTARK_SAME_DRY='1', STUB_ANSWER='1 - same order site')
x = new_session()
r = subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'same-work.py')], input=json.dumps(x), capture_output=True,
                   text=True, env=env, timeout=60)
got = json.loads(r.stdout or '{}')
check('the hook prints one JSON with the context, exit 0: %r' % r.stdout[:80],
      r.returncode == 0 and 'AskUserQuestion' in got.get('hookSpecificOutput', {}).get('additionalContext', ''))
qx = m.read()['asked'][x['session_id']]['question']
r = subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'same-work.py')], capture_output=True, text=True, env=env, timeout=60,
                   input=json.dumps({'session_id': x['session_id'], 'hook_event_name': 'PostToolUse', 'tool_name': 'AskUserQuestion',
                                     'tool_response': {'answers': {qx: 'Send to Order page'}}}))
said = json.loads(r.stdout or '{}').get('hookSpecificOutput', {}).get('additionalContext', '')
check('the answer through the hook, dry: Claude gets the one line, nothing is sent',
      r.returncode == 0 and 'Sent to “Order page”: https://claude.ai/code/session_01OrderPage' in said
      and '(dry: nothing sent)' in log())
r = subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'same-work.py')], input='not json', capture_output=True, text=True,
                   env=env, timeout=60)
check('input it can\'t read: no output, exit 0, a log line', r.returncode == 0 and not r.stdout and 'same   error: ' in log())
r = subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'same-work.py'), '--list'], capture_output=True, text=True, env=env, timeout=60)
check('--list says what was asked and how it was answered', 'same work as "Order page"; answered: send' in r.stdout)

# --- install-hooks.py ------------------------------------------------------------------------------------------------------------
home = os.path.join(d, 'home')
os.makedirs(os.path.join(home, '.claude'))
env = dict(os.environ, HOME=home)
subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'install-hooks.py')], env=env, capture_output=True, timeout=60)
s = json.load(open(os.path.join(home, '.claude', 'settings.json')))
ups = [h for g in s['hooks']['UserPromptSubmit'] for h in g['hooks'] if 'same-work.py' in h['command']]
posts = [(g.get('matcher'), h) for g in s['hooks']['PostToolUse'] for h in g['hooks'] if 'same-work.py' in h['command']]
check('install-hooks.py adds the prompt entry (30 s) and the AskUserQuestion answer entry (90 s)',
      len(ups) == 1 and ups[0]['timeout'] == 30 and len(posts) == 1 and posts[0][0] == 'AskUserQuestion' and posts[0][1]['timeout'] == 90)
st = json.loads(subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'install-hooks.py'), '--status'], env=env, capture_output=True,
                               text=True, timeout=60).stdout)
check('--status says it is in', st.get('same_work') is True)
subprocess.run(['/usr/bin/python3', os.path.join(HOOKS, 'install-hooks.py'), '--remove'], env=env, capture_output=True, timeout=60)
s = json.load(open(os.path.join(home, '.claude', 'settings.json')))
check('--remove takes both out', 'same-work.py' not in json.dumps(s))

print('\n%s' % ('all passed' if not fails else '%d failed' % fails))
sys.exit(1 if fails else 0)
