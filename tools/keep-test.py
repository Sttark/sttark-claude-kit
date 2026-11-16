#!/usr/bin/python3
"""Tests keep() in Resources/hooks/effort-hook.py while the Kit's own server is not connected (--server-down), and
the quit of every copy of a chat's kit- screen, on copies: a temp state folder and log, stand-ins for the process list,
the Claude app's list of sessions, each session's events and the send to the server, and real screens with test names
that run `sleep`. No model is called, no session is changed and no real screen is touched. Prints each case; exits 1
if any fails.
Run: /usr/bin/python3 tools/keep-test.py"""
import importlib.util, json, os, shutil, subprocess, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.normpath(os.path.join(HERE, '../Resources/hooks/effort-hook.py'))
T = tempfile.mkdtemp(prefix='keep-test-')
KIT, LOG = os.path.join(T, 'kit'), os.path.join(T, 'log')
os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG)
os.makedirs(KIT)
spec = importlib.util.spec_from_file_location('eh', HOOK)
eh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eh)

failed = []


def check(name, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + name + ('' if ok else f'  -- {detail}'))
    if not ok:
        failed.append(name)


ENV = 'env_01TESTserver'
A, B = 'cse_01TESTstoppedTwice', 'cse_01TESTstoppedOnce'
chats = [{'id': A, 'title': 'Order page', 'status': 'active', 'environment_id': ENV, 'environment_kind': 'bridge'},
         {'id': B, 'title': 'Label printer', 'status': 'active', 'environment_id': ENV, 'environment_kind': 'bridge'}]
sent, moved = [], []
# a `claude rc` process is there (stuck at a question, say) and runs no session
eh.processes = lambda: '/Users/x/.local/share/claude/stable/claude rc --permission-mode bypassPermissions\n'
eh.all_chats = lambda pages=5: chats
eh.chat_events = lambda sid, pages=5: []
eh.send = lambda sid, level: (sent.append(sid) or (200, 'ok', 'rid'))
eh.move = lambda c, seq: (moved.append(c['id']) or None)
eh.archived = lambda chats: None


def state(keep):
    with open(eh.STATE, 'w') as f:
        json.dump({'sessions': {}, 'keep': keep}, f)


def log_lines():
    try:
        return open(LOG).read().splitlines()
    except OSError:
        return []


# A was woken twice with no result, so the next check would start it on its own; B is due its first wake
woke = {A: {'at': 0, 'tries': 2}}
state({'envs': [ENV], 'woke': woke, 'alone': {}})
eh.keep(server_down=True)
check('server down: no session is woken through it', sent == [], sent)
check('server down: none is started on its own (a second copy once it is back)', moved == [], moved)
held = [l for l in log_lines() if 'the server is not connected' in l]
check('it says so in the log, once', len(held) == 1 and '2 session(s) on it wait until it connects' in held[0], held)
check('the wakes so far are kept for when it connects', eh.peek().get('keep', {}).get('woke') == woke, eh.peek().get('keep'))
eh.keep(server_down=True)
check('a second check while it is down says nothing more', len([l for l in log_lines() if 'the server is not connected' in l]) == 1)

eh.keep(server_down=False)
check('connected: the stopped session is woken', sent == [B], sent)
check('connected: the one woken twice with no result starts on its own, as before', moved == [A], moved)
check('connected: the hold is over', 'held' not in eh.peek().get('keep', {}), eh.peek().get('keep'))
eh.keep(server_down=True)
check('down again: it says so again', len([l for l in log_lines() if 'the server is not connected' in l]) == 2)

# Two screens with one name: `screen -S <name>` acts on neither, so a second copy of a chat could never be quit by name.
# quit_screen() quits each by its full id.
name = f'kit-test{os.getpid()}'
for _ in range(2):
    subprocess.run(['/usr/bin/screen', '-dmS', name, '/bin/sleep', '300'])
time.sleep(0.5)
check('two screens with one name', len(eh.screen_ids(name)) == 2, eh.screen_ids(name))
r = subprocess.run(['/usr/bin/screen', '-S', name, '-X', 'quit'], capture_output=True, text=True)
check('screen -S <name> quits neither of them', len(eh.screen_ids(name)) == 2 and 'several suitable screens' in r.stdout + r.stderr, r.stdout)
eh.quit_screen(name)
time.sleep(0.5)
check('quit_screen() quits both', eh.screen_ids(name) == [], eh.screen_ids(name))
check('a name that only starts the same is not one of them', eh.screen_ids('kit-test') == [] or all(
    s.split('.', 1)[1] == 'kit-test' for s in eh.screen_ids('kit-test')))

shutil.rmtree(T, ignore_errors=True)
print(f'\n{len(failed)} failed' if failed else '\nall passed')
raise SystemExit(1 if failed else 0)
