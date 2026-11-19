#!/usr/bin/python3
"""Tests the progress check-ins in the session's chat (Resources/hooks/checkin.py in_chat()) on copies: a test Kit
folder and log (STTARK_KIT_DIR, STTARK_KIT_LOG), a test ~/.claude (STTARK_CLAUDE_DIR, STTARK_CLAUDE_JSON) with made-up
records, a stand-in for the Haiku call (STTARK_CHECKIN_MODEL), and a stand-in `claude`, a small program built here: in
a real screen with a test name, as the Kit runs its own copy of a session, it reads keys as Claude Code does (raw),
shows them, keeps a log of each read, and at Enter writes the prompt in the session's record, marks its copy busy in
its record of the copy, answers and marks it idle again; with no terminal (the server's copy, the desktop app's, a
terminal's) it only waits. No session, screen or server of this Mac is touched, no model is called, and nothing is
typed anywhere but into this test's own screens.
- the hard rule: a check-in typed in never ends, restarts or stops the copy or its work: after each one the same
  process runs in the same screen, its agent still works, and the keys it got are the text, then Enter alone, with no
  other key;
- what goes in: "[Sttark Claude Kit] Check-in: <the note>", on one line, with no control character, no "@" that starts
  a word, no backslash at the end, at most 790 characters; only a note Haiku wrote;
- when: the session's turn is idle (the minute check, and Claude Code's own record of the copy) and its agents work in
  the background; not while the turn runs or the session waits on the person; not while the last one has no answer,
  until the person writes; not again into a copy where one did not go in; not in the 2 minutes after the Kit started
  the copy; not in vim mode; not with the working rules off; with the switch off, nothing, and no chat words in the
  log; the next summary leaves the check-in typed into the chat out;
- where: only the Kit's own copy in its kit- screen; the server's copy, the desktop app's, a terminal's (claude --resume
  outside the Kit's screen), two copies of the Kit's, and no copy get none, each with why in the log;
- the log line: "in the chat", "not in the chat: <why>"; a test run (STTARK_CHECKIN_DRY) types nothing ("would go in
  the chat"); checkin.py --list says where a check-in would go;
- the effort hook gives a check-in no model call and keeps its level; the working rules have the rule for it.
Run from the repo root: /usr/bin/python3 tools/checkin-chat-test.py"""
import importlib.util, json, os, re, shutil, signal, stat, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, 'Resources', 'hooks')
T = tempfile.mkdtemp(prefix='kit-chat-')
KIT, LOG, CLAUDE = os.path.join(T, 'Application Support'), os.path.join(T, 'log'), os.path.join(T, 'claude')  # a space, as the Kit's own folder has
FLAGS, KEYS = os.path.join(T, 'flags'), os.path.join(T, 'keys')
for p in (KIT, os.path.join(CLAUDE, 'sessions'), FLAGS):
    os.makedirs(p)
CLAUDE_JSON = os.path.join(T, 'claude.json')
json.dump({'editorMode': 'normal'}, open(CLAUDE_JSON, 'w'))
fails = 0


def check(what, ok, detail=''):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what + ('' if ok else '  -- %s' % (detail,)))
    fails += not ok


# --- a stand-in for the Haiku call: the next answer the test set, else a note on the label work ---------------------
HAIKU = os.path.join(T, 'haiku')
open(HAIKU, 'w').write('''#!/usr/bin/python3
import json, os, sys
sys.stdin.read()
if os.path.exists(os.environ['FAKE_DIR'] + '/fail'):
    print('overloaded', file=sys.stderr)
    sys.exit(1)
q = os.environ['FAKE_DIR'] + '/answers'
try:
    answers = json.load(open(q))
except (OSError, ValueError):
    answers = []
if answers:
    json.dump(answers[1:], open(q, 'w'))
    print(answers[0])
else:
    print('The label agent finished the barcode check and opened pull request 318. Next it adds the print test.')
''')
os.chmod(HAIKU, os.stat(HAIKU).st_mode | stat.S_IEXEC)
USAGE = os.path.join(T, 'usage.json')   # a stand-in for the usage read: nothing of this Mac's
json.dump({'extra_usage': {'is_enabled': False}, 'limits': []}, open(USAGE, 'w'))
os.environ.update(STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_CLAUDE_DIR=CLAUDE, STTARK_CLAUDE_JSON=CLAUDE_JSON,
                  STTARK_CHECKIN_MODEL=HAIKU, FAKE_DIR=T, STTARK_LIMIT_TEST=USAGE)
for k in ('STTARK_CHECKIN_DRY', 'STTARK_WAIT_DRY', 'STTARK_NOTIFY_DRY', 'CLAUDE_CODE_BRIDGE_SESSION_ID', 'CLAUDE_PID'):
    os.environ.pop(k, None)

# --- the stand-in claude --------------------------------------------------------------------------------------------
FAKE_C = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
static const char *env(const char *k) { const char *v = getenv(k); return v ? v : ""; }
static int flag(const char *name) {   /* a file the test makes: "deaf" (Enter does nothing), "silent" (no answer) */
    char p[1024]; snprintf(p, sizeof p, "%s/%s", env("FAKE_FLAGS"), name); return access(p, F_OK) == 0;
}
static double now(void) { struct timeval tv; gettimeofday(&tv, 0); return tv.tv_sec + tv.tv_usec / 1e6; }
static void stamp(char *out) {
    struct timeval tv; struct tm t; gettimeofday(&tv, 0); gmtime_r(&tv.tv_sec, &t);
    strftime(out, 32, "%Y-%m-%dT%H:%M:%S", &t); sprintf(out + strlen(out), ".%03dZ", (int)(tv.tv_usec / 1000));
}
static void status(const char *s) {   /* Claude Code's own record of the copy: ~/.claude/sessions/<pid>.json */
    char p[1024], tmp[1100];
    snprintf(p, sizeof p, "%s/sessions/%d.json", env("FAKE_CLAUDE_DIR"), (int)getpid());
    snprintf(tmp, sizeof tmp, "%s.tmp", p);
    FILE *f = fopen(tmp, "w"); if (!f) return;
    fprintf(f, "{\"pid\": %d, \"sessionId\": \"%s\", \"status\": \"%s\", \"entrypoint\": \"cli\", \"kind\": \"interactive\"}",
            (int)getpid(), env("FAKE_CID"), s);
    fclose(f); rename(tmp, p);
}
static void entry(const char *type, const char *text) {   /* a line of the session's record */
    char t[40]; FILE *f = fopen(env("FAKE_TRANSCRIPT"), "a"); if (!f) return; stamp(t);
    fprintf(f, "{\"type\":\"%s\",\"timestamp\":\"%s\",\"entrypoint\":\"cli\",\"message\":{\"role\":\"%s\",\"content\":\"", type, t, type);
    for (const unsigned char *c = (const unsigned char *)text; *c; c++) {
        if (*c == '"' || *c == '\\') fputc('\\', f);
        if (*c < 32) fprintf(f, "\\u%04x", *c); else fputc(*c, f);
    }
    fprintf(f, "\"}}\n"); fclose(f);
}
int main(void) {
    struct termios t; static char line[65536]; char chunk[4096]; size_t n = 0;
    if (tcgetattr(0, &t) != 0) { for (;;) pause(); }   /* no terminal: it only waits */
    status("idle");
    cfmakeraw(&t); tcsetattr(0, TCSANOW, &t);
    write(1, "> ", 2);
    for (;;) {
        ssize_t r = read(0, chunk, sizeof chunk);
        if (r <= 0) break;
        FILE *k = fopen(env("FAKE_KEYS"), "a");
        if (k) { fprintf(k, "%.3f %zd ", now(), r); for (ssize_t i = 0; i < r; i++) fprintf(k, "%02x", (unsigned char)chunk[i]); fputc('\n', k); fclose(k); }
        for (ssize_t i = 0; i < r; i++) {
            if (chunk[i] == '\r') {
                if (flag("deaf") || n == 0) continue;
                line[n] = 0; status("busy"); entry("user", line); write(1, "\r\n", 2);
                sleep(1);
                if (!flag("silent")) entry("assistant", "The barcode check is done, in pull request 318. The print test is next.");
                status("idle"); n = 0; write(1, "> ", 2);
            } else if (n < sizeof line - 1) { line[n++] = chunk[i]; write(1, chunk + i, 1); }
        }
    }
    return 0;
}
'''
FAKE = os.path.join(T, 'bin', 'claude')
os.makedirs(os.path.dirname(FAKE))
open(os.path.join(T, 'claude.c'), 'w').write(FAKE_C)
if subprocess.run(['/usr/bin/cc', '-o', FAKE, os.path.join(T, 'claude.c')], capture_output=True).returncode:
    print('skip  the stand-in claude could not be built (no C compiler), so nothing can be typed into one')
    sys.exit(0)

PID = os.getpid() % 1000
PROCS, SCREENS = [], []


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HOOKS, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


c = load('checkin')
c.DRY = c.NO_MODEL = False   # a test folder makes it dry; here the records are this test's own, and it types into its screens
c.START_WAIT = 3             # a copy that takes no Enter fails sooner


class Limit(object):
    @staticmethod
    def held(sid=None, transcript=None, cse=None):
        return False


real_load = c.load
c.load = lambda name: Limit if name == 'limit-hook' else real_load(name)
eh = load('effort-hook')


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S.', time.gmtime(t)) + '%03dZ' % int((t % 1) * 1000)


def write(path, entries, mode='a'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        for x in entries:
            f.write(json.dumps(x, separators=(',', ':')) + '\n')


def step(desc, at):
    i = 'toolu_%d' % int(at * 1000)
    return [{'type': 'assistant', 'timestamp': iso(at), 'isSidechain': True, 'message': {'content': [
                {'type': 'tool_use', 'id': i, 'name': 'Bash', 'input': {'command': 'x', 'description': desc}}]}},
            {'type': 'user', 'timestamp': iso(at), 'isSidechain': True, 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': i, 'content': 'ok'}]}}]


def session(n, title):
    """A made-up session: its record, and an agent of it that works in the background."""
    now = time.time()
    cid = 't%03dcc%02d-0000-4000-8000-%012d' % (PID, n, n)   # kit-t<3 digits>cc<2 digits>: only this test's screens
    tp = os.path.join(CLAUDE, 'projects', '-sample-src', cid + '.jsonl')
    write(tp, [{'type': 'user', 'timestamp': iso(now - 3600), 'message': {'role': 'user', 'content': 'Make the bottle labels'}}], 'w')
    agent = os.path.join(tp[:-len('.jsonl')], 'subagents', 'agent-a%02d.jsonl' % n)
    write(agent, [{'type': 'user', 'timestamp': iso(now - 1200), 'isSidechain': True, 'parentUuid': None,
                   'message': {'role': 'user', 'content': 'Check the barcodes on the bottle labels.'}}] + step('Read the label files', now - 1100), 'w')
    json.dump({'agentType': 'general-purpose', 'description': 'Barcode check', 'requestShape': 'background'},
              open(agent[:-len('.jsonl')] + '.meta.json', 'w'))
    os.utime(agent, (now - 1200, now - 1200))   # macOS moves a file's birth time back with it: the agent started then
    return {'n': n, 'cid': cid, 'cse': 'cse_01TESTchat%04d' % n, 'tp': tp, 'title': title, 'agent': agent,
            'asked': now - 30 * 60}


def kit_copy(s):
    """The Kit's own copy of a session: the stand-in claude --resume <cid> in screen kit-<first 8>, as start_screen()
    runs it."""
    name = 'kit-' + s['cid'][:8]
    env = dict(os.environ, FAKE_CLAUDE_DIR=CLAUDE, FAKE_CID=s['cid'], FAKE_TRANSCRIPT=s['tp'], FAKE_KEYS=KEYS + s['cid'][:8],
               FAKE_FLAGS=FLAGS, TERM='xterm-256color', LANG='en_US.UTF-8')
    subprocess.run(['/usr/bin/screen', '-dmS', name, FAKE, '--resume', s['cid'], '--remote-control',
                    '--permission-mode', 'bypassPermissions'], env=env)
    SCREENS.append(name)
    for _ in range(50):
        pids = [p for p, k in eh.copies(s['cse'], s['cid']).items() if k == 'kit']
        if pids and os.path.exists(os.path.join(CLAUDE, 'sessions', '%d.json' % pids[0])):
            return pids[0]
        time.sleep(0.1)
    raise SystemExit('the stand-in claude did not start in its screen')


def bare(*args):
    """A stand-in claude with no terminal: the server's copy, the desktop app's, or a terminal's as ps shows it."""
    p = subprocess.Popen([FAKE] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS.append(p)
    time.sleep(0.3)
    return p.pid


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def keys(s):
    """Each read the stand-in got: (time, the bytes)."""
    try:
        out = []
        for l in open(KEYS + s['cid'][:8]).read().splitlines():
            t, _, hexed = l.split(' ', 2)
            out.append((float(t), bytes.fromhex(hexed)))
        return out
    except OSError:
        return []


def record(s):
    return [json.loads(l) for l in open(s['tp']) if l.strip()]


def state(*sessions, chat=None, working=(), more=None):
    now = time.time()
    st = {'sessions': {}}
    for s in sessions:
        x = {'transcript': s['tp'], 'title': s['title'], 'at': now - 120, 'asked_at': s['asked'], 'title_at': 1e12,
             'level': 'high', 'app': {'checked': now - 20, 'working': s['n'] in working}}
        if s['n'] in working:
            x['turn_at'] = now - 6 * 60
        st['sessions'][s['cse']] = x
    if chat is not None:
        st['checkins_chat'] = chat
    st.update(more or {})
    json.dump(st, open(os.path.join(KIT, 'state.json'), 'w'))


def due(*sessions):
    """Each session's check-in is due now, with a new step of its agent to tell."""
    now = time.time()
    C = c.read_json(c.FILE)
    for s in sessions:
        write(s['agent'], step('Check label %d' % int(now * 10), now - 30))
        os.utime(s['agent'], (now - 20, now - 20))
        r = C.setdefault('sessions', {}).setdefault(s['cse'], {})
        r.update(start=r.get('start') or now - 20 * 60, seen=now - 60, sent=now - 16 * 60)
        for k in ('idle', 'tried', 'empty'):
            r.pop(k, None)
    c.save(C)


def run():
    """One minute check now; the check-in lines it logged."""
    before = len(log_lines())
    c.check(now=time.time())
    return log_lines()[before:]


def log_lines(tag='checkin '):
    try:
        return [l[20:] for l in open(LOG).read().splitlines() if l[20:].startswith(tag)]
    except OSError:
        return []


def chat_words(line):
    """The chat part of a check-in's log line."""
    head = line.split(' | ')[0]
    return next((x for x in head.split('; ') if 'the chat' in x), '')


def chat_rec(s):
    return (c.read_json(c.FILE).get('sessions') or {}).get(s['cse'], {}).get('chat') or {}


MARK = '[Sttark Claude Kit] Check-in:'
NOTE = 'The label agent finished the barcode check and opened pull request 318. Next it adds the print test.'
try:
    # --- the Kit's own copy: the check-in goes in, as typed, and nothing ends ---------------------------------------
    A = session(1, 'Bottle labels')
    pid = kit_copy(A)
    screen_id = eh.screen_ids('kit-' + A['cid'][:8])
    state(A)
    due(A)
    got = run()
    check('the Kit\'s own copy, its turn idle and its agent at work: the check-in goes in the chat',
          len(got) == 1 and got[0].startswith('checkin %s "Bottle labels" shown in the Kit; in the chat | Barcode check, working' % A['cse']), got)
    users = [x for x in record(A) if x.get('type') == 'user' and MARK in str(x['message']['content'])]
    check('the session got the prompt word for word: the mark, then the note', len(users) == 1
          and users[0]['message']['content'] == MARK + ' ' + NOTE, users)
    k = keys(A)
    check('the keys it got: the text in one paste, then Enter alone, a second or more later, and no other key',
          len(k) == 2 and k[0][1] == (MARK + ' ' + NOTE).encode() and k[1][1] == b'\r' and k[1][0] - k[0][0] >= 0.9, k)
    check('no control key at all: no Escape, no Ctrl-C, no Ctrl-D',
          not any(b in data for _, data in k for b in (b'\x1b', b'\x03', b'\x04', b'\x1a')))
    check('the hard rule: the same copy still runs in the same screen, and its agent still works',
          alive(pid) and eh.screen_ids('kit-' + A['cid'][:8]) == screen_id
          and [p for p, kind in eh.copies(A['cse'], A['cid']).items() if kind == 'kit'] == [pid]
          and not json.load(open(A['agent'][:-len('.jsonl')] + '.meta.json')).get('finished'))
    rec = chat_rec(A)
    check('the last one is kept: when, into which copy, and that it went in', rec.get('pid') == pid and rec.get('ok') is True
          and time.time() - rec.get('at', 0) < 60, rec)
    check('the Kit app keeps its line as before', (c.read_json(c.FILE)['sessions'][A['cse']].get('note') or '') == NOTE)
    check('the text file it typed from is gone', os.path.isdir(os.path.join(KIT, 'checkin-chat'))
          and not os.listdir(os.path.join(KIT, 'checkin-chat')))

    # --- the next one, after the session answered: it goes in too ------------------------------------------------------
    time.sleep(1.5)
    due(A)
    got = run()
    check('15 minutes later, the last one answered: the next goes in', len(got) == 1 and chat_words(got[0]) == 'in the chat', got)

    # --- no answer yet: the next waits; a prompt of the person's own clears that ----------------------------------------
    time.sleep(1.5)   # the stand-in answers the one before a second after its Enter
    open(os.path.join(FLAGS, 'silent'), 'w').close()
    due(A)
    got = run()
    check('a third goes in, and the session does not answer it', len(got) == 1 and chat_words(got[0]) == 'in the chat', got)
    n_keys = len(keys(A))
    time.sleep(1.5)
    due(A)
    got = run()
    check('the last one has no answer yet: the next is not typed in, and the log says why',
          len(got) == 1 and chat_words(got[0]) == 'not in the chat: the last check-in in the chat has no answer yet'
          and len(keys(A)) == n_keys and got[0].startswith('checkin %s "Bottle labels" shown in the Kit;' % A['cse']), got)
    now = time.time()   # the person wrote 16 minutes ago, after the check-in with no answer (20 minutes ago)
    C = c.read_json(c.FILE)
    C['sessions'][A['cse']]['chat']['at'] = now - 20 * 60
    c.save(C)
    A['asked'] = now - 16 * 60
    state(A)
    due(A)
    got = run()
    check('a prompt of the person\'s own after it clears that: the next goes in', len(got) == 1 and chat_words(got[0]) == 'in the chat', got)
    os.remove(os.path.join(FLAGS, 'silent'))
    A['asked'] = time.time() - 3600
    time.sleep(1.5)

    # --- the turn runs, the session waits on the person, the copy started moments ago, vim mode: none -----------------
    state(A, working=(1,))
    due(A)
    n_keys = len(keys(A))
    got = run()
    check('the turn runs (the minute check): not in the chat, a prompt would only wait',
          len(got) == 1 and chat_words(got[0]) == 'not in the chat: its turn runs, and a prompt would only wait for it', got)
    state(A)
    rec_path = os.path.join(CLAUDE, 'sessions', '%d.json' % pid)
    saved = open(rec_path).read()
    json.dump(dict(json.loads(saved), status='busy'), open(rec_path, 'w'))
    due(A)
    got = run()
    check('the turn runs (Claude Code\'s own record says busy): not in the chat',
          len(got) == 1 and chat_words(got[0]) == 'not in the chat: its turn runs, and a prompt would only wait for it', got)
    json.dump(dict(json.loads(saved), waitingFor='permission'), open(rec_path, 'w'))
    due(A)
    got = run()
    check('it waits on the person: not in the chat', len(got) == 1 and chat_words(got[0]) == 'not in the chat: it waits on you', got)
    open(rec_path, 'w').write(saved)
    state(A, more={'keep': {'alone': {A['cse']: {'transcript': A['tp'], 'title': A['title'], 'at': time.time() - 30}}}})
    due(A)
    got = run()
    check('the Kit started its copy moments ago: not in the chat',
          len(got) == 1 and chat_words(got[0]) == 'not in the chat: the Kit started its copy moments ago', got)
    state(A)
    json.dump({'editorMode': 'vim'}, open(CLAUDE_JSON, 'w'))
    due(A)
    got = run()
    check('Claude Code in vim mode: not in the chat', len(got) == 1
          and chat_words(got[0]) == 'not in the chat: Claude Code is in vim mode, where typed text can act as keys', got)
    json.dump({'editorMode': 'normal'}, open(CLAUDE_JSON, 'w'))
    open(os.path.join(KIT, 'working-rules.off'), 'w').close()
    due(A)
    got = run()
    os.remove(os.path.join(KIT, 'working-rules.off'))
    check('the Sttark working rules off: not in the chat, as they tell the session how to answer', len(got) == 1
          and chat_words(got[0]) == 'not in the chat: the Sttark working rules are off, and they tell the session how to answer one', got)
    check('none of these typed a key', len(keys(A)) == n_keys)

    # --- only a note Haiku wrote; the switch off ------------------------------------------------------------------------
    open(os.path.join(T, 'fail'), 'w').close()
    due(A)
    got = run()
    os.remove(os.path.join(T, 'fail'))
    check('a failed summary (the count of steps) does not go in the chat',
          len(got) == 1 and chat_words(got[0]) == 'not in the chat: Haiku gave no summary to send' and 'no summary (exit 1' in got[0], got)
    now = time.time()
    C = c.read_json(c.FILE)
    C['sessions'][A['cse']].update(sent=now - 16 * 60, empty=False)
    c.save(C)
    os.utime(A['agent'], (now - 20, now - 20))
    got = run()
    check('no new steps (no model call) does not go in the chat',
          len(got) == 1 and chat_words(got[0]) == 'not in the chat: it has no new steps to tell', got)
    state(A, chat=False)
    due(A)
    got = run()
    check('Check-ins in the session off: the check-in stays in the Kit, and the line has no chat words',
          len(got) == 1 and 'the chat' not in got[0] and got[0].startswith('checkin %s "Bottle labels" shown in the Kit | ' % A['cse']), got)
    check('still no key typed', len(keys(A)) == n_keys)

    # --- a copy that takes no Enter: the Kit says so once, and types no more into it ------------------------------------
    B = session(2, 'Die cutter')
    pid_b = kit_copy(B)
    open(os.path.join(FLAGS, 'deaf'), 'w').close()
    state(B)
    due(B)
    got = run()
    check('a copy that takes no Enter: not in the chat, and why, as a failure',
          len(got) == 1 and chat_words(got[0]) == 'not in the chat: the Kit could not type it in: it did not start after the Enter key', got)
    check('it got the text and one Enter, nothing more', [d for _, d in keys(B)][-1:] == [b'\r'] and len(keys(B)) == 2, keys(B))
    rec = chat_rec(B)
    check('kept: the copy and that it did not go in', rec.get('pid') == pid_b and rec.get('ok') is False, rec)
    due(B)
    got = run()
    check('the next one is not typed into that copy', len(got) == 1 and len(keys(B)) == 2
          and chat_words(got[0]) == 'not in the chat: the last check-in did not go in, so the Kit types no more into this copy', got)
    check('the hard rule: that copy still runs too', alive(pid_b) and eh.screen_ids('kit-' + B['cid'][:8]))
    os.remove(os.path.join(FLAGS, 'deaf'))

    # --- where else a session runs: none of them gets one, and the log says why ----------------------------------------
    S1, S2, S3, S4, S5, S6 = (session(n, t) for n, t in ((3, 'Press 4 jobs'), (4, 'Ink order'), (5, 'Slitter blade'),
                                                          (6, 'Core supplier quote'), (7, 'Waste report'), (8, 'Dock door repair')))
    bare('--print', '--sdk-url', 'https://api.anthropic.com/v1/code/sessions/' + S1['cse'], '--session-id', S1['cse'])
    app_pid = bare('--input-format', 'stream-json', '--output-format', 'stream-json')
    json.dump({'pid': app_pid, 'sessionId': S2['cid'], 'status': 'idle', 'entrypoint': 'claude-desktop'},
              open(os.path.join(CLAUDE, 'sessions', '%d.json' % app_pid), 'w'))
    bare('--resume', S3['cid'])
    term_pid = bare('--continue')
    json.dump({'pid': term_pid, 'sessionId': S4['cid'], 'status': 'idle', 'entrypoint': 'cli'},
              open(os.path.join(CLAUDE, 'sessions', '%d.json' % term_pid), 'w'))
    kit_copy(S5)
    env2 = dict(os.environ, FAKE_CLAUDE_DIR=CLAUDE, FAKE_CID=S5['cid'], FAKE_TRANSCRIPT=S5['tp'], FAKE_KEYS=KEYS + 'second', FAKE_FLAGS=FLAGS)
    subprocess.run(['/usr/bin/screen', '-dmS', 'kit-' + S5['cid'][:8], FAKE, '--resume', S5['cid']], env=env2)
    time.sleep(0.5)
    state(S1, S2, S3, S4, S5, S6)
    due(S1, S2, S3, S4, S5, S6)
    got = {l.split()[1]: chat_words(l) for l in run()}
    want = {S1['cse']: "not in the chat: it runs in this Mac's server, which takes no typed prompt",
            S2['cse']: 'not in the chat: it runs in the Claude desktop app or another program, which takes no typed prompt from the Kit',
            S3['cse']: 'not in the chat: it runs in a terminal, which the Kit does not type into',
            S4['cse']: 'not in the chat: it runs in a terminal, which the Kit does not type into',
            S5['cse']: 'not in the chat: it runs in more than one copy',
            S6['cse']: 'not in the chat: the Kit sees no copy of it on this Mac'}
    for s, what in ((S1, "the server's copy"), (S2, "the desktop app's copy"), (S3, 'claude --resume in a terminal'),
                    (S4, "a terminal (Claude Code's record says cli)"), (S5, "two copies of the Kit's"), (S6, 'no copy at all')):
        check('%s: no check-in in the chat, and why' % what, got.get(s['cse']) == want[s['cse']], got.get(s['cse']))
    check('none of them got a key', not keys(S5) and not os.path.exists(KEYS + 'second'))
    kit_copy(S6)
    bare('--print', '--sdk-url', 'https://api.anthropic.com/v1/code/sessions/' + S6['cse'], '--session-id', S6['cse'])
    state(S6)
    due(S6)
    got = run()
    check('the server runs a session the Kit\'s copy runs too (a handover): none, and no key',
          len(got) == 1 and chat_words(got[0]) == want[S1['cse']] and not keys(S6), got)

    # --- a test run types nothing; --list says where one would go -------------------------------------------------------
    D = session(9, 'Laminator')
    kit_copy(D)
    state(D)
    due(D)
    r = subprocess.run([sys.executable, os.path.join(HOOKS, 'checkin.py'), '--check'], capture_output=True, text=True,
                       env=dict(os.environ, STTARK_CHECKIN_DRY='1'), timeout=120)
    check('a test run (STTARK_CHECKIN_DRY): "would go in the chat", and no key typed: %r' % r.stdout[-200:],
          'would go in the chat' in r.stdout and not keys(D)
          and any(l.startswith('checkin %s "Laminator" written (dry); would go in the chat |' % D['cse']) for l in log_lines()))
    r = subprocess.run([sys.executable, os.path.join(HOOKS, 'checkin.py'), '--list'], capture_output=True, text=True, timeout=60)
    check('--list says a check-in now would go in the chat of the Kit\'s copy, and types nothing: %r' % r.stdout[-300:],
          'Check-ins in the session are on.' in r.stdout and 'a check-in now would go in its chat too' in r.stdout and not keys(D))

    # --- the text typed in --------------------------------------------------------------------------------------------
    t = c.chat_text('It sent the proof to @sam and\x1b[2J the press team.\nNext it checks C:\\jobs\\')
    check('the text: one line, no control character, no "@" that starts a word, no backslash at the end: %r' % t,
          t == MARK + ' It sent the proof to sam and [2J the press team. Next it checks C:\\jobs')
    check('an address keeps its "@"', c.chat_text('It wrote to name@sttark.com.') == MARK + ' It wrote to name@sttark.com.')
    long_ = c.chat_text('word ' * 400)
    check('at most 790 characters, under the 800 at which Claude Code shows a paste as a placeholder',
          len(long_) == 790 and long_.endswith('…'), len(long_))

    lines, _, _, _ = c.digest([{'type': 'user', 'message': {'content': MARK + ' ' + NOTE}},
                               {'type': 'user', 'message': {'content': [{'type': 'text', 'text': MARK + ' ' + NOTE}]}},
                               {'type': 'user', 'message': {'content': 'Add the print test to the label page'}}])
    check('the next summary leaves a check-in typed into the chat out: it is not news', lines == [
        '- A message to it: Add the print test to the label page'], lines)

    # --- the hooks around it ---------------------------------------------------------------------------------------------
    calls = []
    e2 = load('effort-hook')
    e2.judge = lambda ask, system=None: calls.append(ask) or ('low', 'low - a status line')
    e2.send = lambda sid, level: calls.append(level) or (200, 'ok', 'rid')
    e2.live = lambda sid: {}   # the session as the server sees it: nothing is asked of Anthropic's server
    state(A)
    asked = json.load(open(os.path.join(KIT, 'state.json')))['sessions'][A['cse']]['asked_at']
    e2.on_prompt({'prompt': MARK + ' ' + NOTE, 'transcript_path': A['tp']}, A['cse'])
    x = json.load(open(os.path.join(KIT, 'state.json')))['sessions'][A['cse']]
    check('the effort hook: a check-in gets no model call and keeps its level, and is not the person\'s prompt',
          not calls and x.get('asked_at') == asked and time.time() - x.get('turn_at', 0) < 30
          and any(l.startswith('keep   %s high - a check-in from the Kit' % A['cse']) for l in log_lines('keep ')), calls)
    e2.on_prompt({'prompt': 'Add the print test to the label page', 'transcript_path': A['tp']}, A['cse'])
    check('a prompt of the person\'s own is still checked', len(calls) >= 1)
    wr = load('working-rules-hook')
    check('the working rules: a check-in gets one or two short lines, with no tools, no claude-notify, no question and no new work',
          '"[Sttark Claude Kit] Check-in:"' in wr.RULES and 'one or two short lines' in wr.RULES
          and 'Use no tools, send no claude-notify, ask nothing, and start no new work.' in wr.RULES)
    check('the working rules\' checks count a check-in as a notification, not the person\'s prompt',
          not wr.is_person({'type': 'user', 'message': {'content': MARK + ' ' + NOTE}})
          and wr.is_prompt({'type': 'user', 'message': {'content': MARK + ' ' + NOTE}}))

    check('the hard rule, at the end: every copy the test typed into still runs', alive(pid) and alive(pid_b))
finally:
    for name in SCREENS:
        for sid in eh.screen_ids(name):
            subprocess.run(['/usr/bin/screen', '-S', sid, '-X', 'quit'], capture_output=True)
    for p in PROCS:
        p.kill()
        p.wait()
    shutil.rmtree(T, ignore_errors=True)

print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
