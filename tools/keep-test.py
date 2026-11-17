#!/usr/bin/python3
"""Tests keep() in Resources/hooks/effort-hook.py while the Kit's own server is not connected (--server-down), and
the quit of every copy of a chat's kit- screen, on copies: a temp state folder and log, stand-ins for the process list,
the Claude app's list of sessions, each session's events and the send to the server, and real screens with test names
that run `sleep`. No model is called, no session is changed and no real screen is touched. Prints each case; exits 1
if any fails.
Also that the Kit never makes Claude Code archive a chat: quit_screen() and halt_copies() end a stand-in `claude`
(a small program built here, that writes a file when its terminal closes or it gets a hang-up, SIGTERM or SIGINT,
as Claude Code archives then) with SIGKILL, so it writes nothing; and keep() leaves a chat archived when it was
archived while halted.
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
eh.move = lambda c, seq, why='': (moved.append(c['id']) or None)
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

# The Kit never makes Claude Code archive a chat. Claude Code archives a Remote Control chat when it ends on its own:
# its terminal closes (a screen that quits), a hang-up, SIGTERM (what the system sends as the Mac shuts down) or
# SIGINT. The stand-in `claude` writes a file then, so a file means "archived". Screen runs it under `login`.
src = os.path.join(T, 'claude.c')
with open(src, 'w') as f:
    f.write('#include <signal.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <unistd.h>\n'
            'static const char *mark;\n'
            'static void bye(int s) { FILE *f = fopen(mark, "w"); if (f) { fprintf(f, "%d", s); fclose(f); } _exit(0); }\n'
            'int main(int c, char **v) { char b[64]; mark = v[1]; signal(SIGHUP, bye); signal(SIGTERM, bye);'
            ' signal(SIGINT, bye); while (read(0, b, sizeof b) > 0) ; bye(0); }\n')
fake = os.path.join(T, 'bin', 'claude')
os.makedirs(os.path.dirname(fake))
if subprocess.run(['/usr/bin/cc', '-o', fake, src], capture_output=True).returncode:
    print('skip  the stand-in claude could not be built (no C compiler)')
else:
    def copy(name, mark, nested=False):
        cmd = f'{fake} {mark}' + ('; true' if nested else '')  # nested: under a shell that did not exec it
        subprocess.run(['/usr/bin/screen', '-dmS', name, '/bin/zsh', '-c', cmd if nested else 'exec ' + cmd])
    def up(mark):
        return mark in subprocess.run(['ps', '-axww', '-o', 'command='], capture_output=True, text=True).stdout

    m0 = os.path.join(T, 'old-way')
    copy(name + 'x', m0)
    time.sleep(0.7)
    subprocess.run(['/usr/bin/screen', '-S', eh.screen_ids(name + 'x')[0], '-X', 'quit'])
    time.sleep(0.7)
    check('the old way (screen quit: a hang-up) makes the stand-in archive', os.path.exists(m0))

    m1, m2 = os.path.join(T, 'quit-1'), os.path.join(T, 'quit-2')
    copy(name, m1)
    copy(name, m2, nested=True)
    time.sleep(0.7)
    check('two stand-in copies run', up(m1) and up(m2) and len(eh.screen_ids(name)) == 2)
    eh.quit_screen(name)
    time.sleep(0.7)
    check('quit_screen() ends both copies', not up(m1) and not up(m2) and eh.screen_ids(name) == [])
    check('quit_screen() makes neither archive (SIGKILL; also under a shell)', not os.path.exists(m1) and not os.path.exists(m2))

    # the Mac shuts down: halt_copies() ends every copy first, and marks the ones keep() runs
    # A chat's copy runs in screen kit-<first 8 of its conversation id>; real ids are hex, so kit-t... is only ours.
    C, D = 'cse_01TESThalted', 'cse_01TESTnotRunning'
    pre = 'kit-t' + str(os.getpid() % 1000).zfill(3)
    tdir = os.path.join(T, 'projects')
    os.makedirs(tdir)
    tp = os.path.join(tdir, pre[4:] + 'halt-0000.jsonl')  # its screen: kit-t<3 digits>halt
    other = os.path.join(tdir, '0ddba11e-0000-4000-8000-000000000000.jsonl')
    for f in (tp, other):
        open(f, 'w').close()
    m3 = os.path.join(T, 'halt')
    copy(pre + 'halt', m3)
    time.sleep(0.7)
    state({'envs': [ENV], 'woke': {}, 'alone': {C: {'transcript': tp, 'title': 'Halted', 'at': 1},
                                                D: {'transcript': other, 'title': 'Not running', 'at': 1, 'tries': eh.KEEP_MOVE}}})
    eh.halt_copies(prefix=pre)
    time.sleep(0.7)
    check('halt_copies() ends the copy', not up(m3) and eh.screen_ids(pre + 'halt') == [])
    check('halt_copies() makes it archive nothing', not os.path.exists(m3))
    k = eh.peek().get('keep', {}).get('alone', {})
    check('halt_copies() marks the copy it ended, not one that was not running', bool(k.get(C, {}).get('halted')) and not k.get(D, {}).get('halted'), k)
    check('halt_copies() logs it', any(' halt ' in f' {l} ' for l in log_lines()))
    starts = []
    eh.start_alone = lambda transcript, model='': starts.append(transcript)
    eh.point_at = lambda *a: None
    eh.processes = lambda: '/Users/x/.local/share/claude/stable/claude rc --permission-mode bypassPermissions\n'
    chats[:] = [{'id': C, 'title': 'Halted', 'status': 'archived'}, {'id': D, 'title': 'Not running', 'status': 'archived'}]
    eh.keep(server_down=False)
    check('keep() starts nothing for a while after the halt (the Mac shuts down)', starts == [] and C in eh.peek()['keep']['alone'], starts)
    os.utime(os.path.join(KIT, 'halt'), (time.time() - eh.KEEP_HALT - 1,) * 2)
    eh.keep(server_down=False)
    k = eh.peek().get('keep', {}).get('alone', {})
    check('archived while halted: the person did it, so keep() leaves it archived', C not in k and k.get(D) is not None and tp not in starts, k)
    check('archived after a copy ended another way: keep() starts it again (its own end may have archived it)', starts == [other], starts)
    check('it logs that it left the halted one archived', any('while it was stopped; left it so' in l for l in log_lines()))

shutil.rmtree(T, ignore_errors=True)
print(f'\n{len(failed)} failed' if failed else '\nall passed')
raise SystemExit(1 if failed else 0)
