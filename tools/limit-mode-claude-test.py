#!/usr/bin/python3
"""Real Claude Code test of a session set to "never use credits; hold at 80%". The Kit side runs on copies: a
test state folder and log, a stand-in usage file, and only this repo's limit hooks (the plain entries and the
--hold entries, as install-hooks.py adds them), in a clean environment. Claude Code itself runs as you, with
your login and your home folder: each case is a short `claude -p` run that spends a little real usage, and the
transcript folder each run leaves in ~/.claude/projects is removed afterwards (only those of this test's own
temp folders). "Use credits at the usage limit" is on for every session in the test state, to show the held
session holds anyway.

  main      the session works through four Bash steps; usage goes from 50% to 85% partway, so the next step is
            stopped, Claude says the hold line and runs the wait, and the --hold hook waits with no model calls;
            usage then drops to 10% and the session finishes
  agent     the session starts a background agent that is in the middle of its steps when usage reaches 85%;
            the agent is held before its next step, with no model calls, and finishes after the drop
  billable  usage is at 100% with credits on from the start, so a reply would use credits: the first message is
            held in the hook with no reply at all; at 50% it goes through and the steps run; usage goes back to
            100% partway, so the next step is held in the hook, again with no reply; at 10% the session finishes

For each hold it counts the assistant messages written while the hook held (there must be none), and prints
the hold and release times, what Claude said, the wait's output and the limit log lines.
Run: /usr/bin/python3 tools/limit-mode-claude-test.py [main|agent|billable|both|all]
     (both = main and agent; MODEL=sonnet by default; HOLD=60 s)"""
import datetime, glob, json, os, shutil, subprocess, sys, tempfile, time, uuid

HOOK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../Resources/hooks/limit-hook.py'))
MODEL = os.environ.get('MODEL', 'sonnet')
HOLD = int(os.environ.get('HOLD', '60'))   # seconds the stand-in stays over 80% after a hold starts
STEPS = ('Run these four Bash commands, one per tool call, in this order, and nothing else: `echo step1`, '
         '`python3 -c "import time; time.sleep(25)"`, `echo step2`, `echo step3`. Then reply with the single word DONE.')
PROMPTS = {
    'main': STEPS,
    'billable': STEPS,
    'agent': 'Start one background agent: use the Agent tool with run_in_background true, subagent_type '
             'general-purpose, description "steps", and this prompt: "Run these Bash commands, one per tool call, '
             'in this order: echo a1, then python3 -c \'import time; time.sleep(25)\', then echo a2, then echo a3. Then reply with the word FINISHED." '
             'After you start it, do nothing else until its completion notification arrives. Then reply with the '
             'single word DONE.',
}
failed = []


def check(name, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + name + ('' if ok else f'  -- {detail}'))
    if not ok:
        failed.append(name)


def iso(secs):
    return (datetime.datetime.now().astimezone() + datetime.timedelta(seconds=secs)).isoformat()


def ts(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def set_usage(path, five):
    tmp = path + '.tmp'
    json.dump({'extra_usage': {'is_enabled': True, 'spend_limit_reached': False},
               'limits': [{'kind': 'session', 'percent': five, 'resets_at': iso(7200), 'scope': None},
                          {'kind': 'weekly_all', 'percent': 40, 'resets_at': iso(3 * 86400), 'scope': None}]},
              open(tmp, 'w'))
    os.replace(tmp, path)


def entries(path):
    out = []
    try:
        for ln in open(path):
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def pauses(kit):
    try:
        return json.load(open(os.path.join(kit, 'state.json'))).get('limit_pauses') or {}
    except (OSError, ValueError):
        return {}


def watch(kit, rows, t0, until):
    """Note every new holding row until `until` returns True or 240 s pass; the first new row's start time."""
    first = None
    end = time.time() + 240
    while time.time() < end:
        for k, v in pauses(kit).items():
            if v.get('what') == 'hold' and k not in rows:
                rows[k] = dict(v)
                first = first or v['since']
                print(f'hold started after {v["since"] - t0:.0f} s: {k.split("/", 1)[-1][:24]}'
                      f'{" agent " + v["agent"][:8] if v.get("agent") else ""} mode {v["mode"]} at {v["at"]}%'
                      f' percent {v["percent"]} pid {v["pid"]}')
        if until(first):
            return first
        time.sleep(1)
    return first


def started(sid, text):
    """True once the session has asked for a tool call with this text in it."""
    for tp in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{sid}.jsonl')):
        for e in entries(tp):
            if e.get('type') == 'assistant' and text in json.dumps(e['message'].get('content')):
                return True
    return False


def clean_projects(sid):
    """Remove the transcript folder this run left, only when it is one of this test's temp folders."""
    for tp in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{sid}.jsonl')):
        d = os.path.dirname(tp)
        if 'limit-mode-' in os.path.basename(d) and os.path.dirname(d) == os.path.expanduser('~/.claude/projects'):
            shutil.rmtree(d, ignore_errors=True)
            print(f'removed {d.replace(os.path.expanduser("~"), "~")}')


def run(case):
    print(f'\n== {case} ({MODEL})')
    T = tempfile.mkdtemp(prefix=f'limit-mode-{case}-')
    kit, log, use, w = (os.path.join(T, x) for x in ('kit', 'log', 'usage.json', 'w'))
    os.makedirs(os.path.join(w, '.claude'))
    os.makedirs(kit)
    json.dump({'data': []}, open(os.path.join(T, 'events.json'), 'w'))
    sid = str(uuid.uuid4())
    json.dump({'limit_credits_all': True,
               'limit_modes': {sid: {'mode': 'hold', 'at': 80, 'sid': sid, 'by': 'command', 'set_at': time.time()}}},
              open(os.path.join(kit, 'state.json'), 'w'))
    set_usage(use, 100 if case == 'billable' else 50)
    cmd = f'/usr/bin/python3 "{HOOK}"'   # the installed copy is executable; this one may not be
    plain = {'type': 'command', 'command': cmd, 'timeout': 60}
    hold = {'type': 'command', 'command': cmd + ' --hold', 'timeout': 691200}
    json.dump({'hooks': {'PreToolUse': [{'hooks': [plain]}, {'hooks': [hold]}],
                         'UserPromptSubmit': [{'hooks': [plain]}, {'hooks': [hold]}]},
               'permissions': {'allow': ['Bash']}}, open(os.path.join(w, '.claude/settings.json'), 'w'))
    env = {k: os.environ[k] for k in ('HOME', 'USER', 'PATH', 'TMPDIR', 'LANG') if k in os.environ}
    env.update(STTARK_KIT_DIR=kit, STTARK_KIT_LOG=log, STTARK_LIMIT_TEST=use,
               STTARK_LIMIT_EVENTS=os.path.join(T, 'events.json'))
    out = open(os.path.join(T, 'out.jsonl'), 'w')
    t0 = time.time()
    p = subprocess.Popen(['claude', '-p', PROMPTS[case], '--session-id', sid, '--setting-sources', 'project',
                          '--permission-mode', 'bypassPermissions', '--output-format', 'stream-json', '--verbose',
                          '--model', MODEL], cwd=w, env=env, stdout=out, stderr=subprocess.STDOUT)
    rows, holds = {}, []   # holds: (start, release)
    try:
        if case == 'billable':
            start = watch(kit, rows, t0, lambda f: f and time.time() - f >= HOLD)
            check('billable: the first message was held in the hook', any(k.split('/', 1)[-1].startswith('prompt-') for k in rows),
                  list(rows))
            set_usage(use, 50)
            holds.append((start or t0, time.time()))
            print(f'usage at 50% after {time.time() - t0:.0f} s')
            seen = set(rows)
            # the steps run; during the 25-second step, back to 100%
            end = time.time() + 120
            while time.time() < end and not started(sid, 'time.sleep(25)'):
                time.sleep(1)
            time.sleep(6)
            set_usage(use, 100)
            print(f'usage at 100% after {time.time() - t0:.0f} s')
            start = watch(kit, rows, t0, lambda f: any(k not in seen for k in rows) and time.time() - max(
                v['since'] for k, v in rows.items() if k not in seen) >= HOLD)
            check('billable: a step was held in the hook', any(k not in seen and not k.split('/', 1)[-1].startswith('prompt-')
                                                               for k in rows), list(rows))
            start = max([v['since'] for k, v in rows.items() if k not in seen] or [time.time()])
            set_usage(use, 10)
            holds.append((start, time.time()))
            print(f'usage at 10% after {time.time() - t0:.0f} s')
        else:
            time.sleep(18 if case == 'main' else 22)   # in the middle of the 25-second wait step
            set_usage(use, 85)
            print(f'usage at 85% after {time.time() - t0:.0f} s')
            start = watch(kit, rows, t0, lambda f: f and time.time() - f >= HOLD)
            check(f'{case}: a hold started in the --hold hook', bool(rows), 'no hold row')
            set_usage(use, 10)
            holds.append((start or time.time(), time.time()))
            print(f'usage at 10% after {time.time() - t0:.0f} s' + (f' (held {time.time() - start:.0f} s)' if start else ''))
        try:
            p.wait(timeout=300)
        except subprocess.TimeoutExpired:
            p.kill()
            check(f'{case}: the session finished', False, 'timed out')
    finally:
        if p.poll() is None:
            p.kill()
        out.close()
    proj = glob.glob(os.path.expanduser(f'~/.claude/projects/*/{sid}.jsonl'))
    main_tp = proj[0] if proj else ''
    agents = glob.glob(os.path.join(main_tp[:-6], 'subagents', 'agent-*.jsonl')) if main_tp else []
    final = ''
    for e in entries(os.path.join(T, 'out.jsonl')):
        if e.get('type') == 'result':
            final = e.get('result') or ''
    for tp in [main_tp] + agents:
        es = entries(tp)
        agent = '' if tp == main_tp else os.path.basename(tp)[6:-6]
        who = 'main' if not agent else 'agent ' + agent[:8]
        says, waits = [], []
        for e in es:
            if e.get('type') != 'assistant':
                continue
            for b in e['message'].get('content') or []:
                if b.get('type') == 'text' and b.get('text', '').strip():
                    says.append(b['text'].strip()[:140])
                if b.get('type') == 'tool_use' and 'wait' in json.dumps(b.get('input')):
                    waits.append(b['input'].get('command', ''))
        results = [c.get('content') for e in es if e.get('type') == 'user' and isinstance(e['message'].get('content'), list)
                   for c in e['message']['content'] if c.get('type') == 'tool_result'
                   and 'GO ON' in json.dumps(c.get('content'))]
        print(f'-- {who}: said {says}')
        print(f'   wait commands: {waits}')
        print(f'   wait output: {[json.dumps(r)[:120] for r in results]}')
        mine = [v for v in rows.values() if (v.get('agent') or '') == agent]
        if not mine:
            continue
        for start, release in holds:
            during = [e.get('timestamp') for e in es if e.get('type') == 'assistant' and start + 1 < ts(e['timestamp']) < release]
            check(f'{case}/{who}: no model calls while the hook held ({release - start:.0f} s)', not during, during)
        if case == 'main':   # the session says the line and waits in the open
            check(f'{case}/{who}: said the hold line', any('holds at 80% usage' in t for t in says), says)
            check(f'{case}/{who}: the wait printed GO ON', bool(results), results)
        elif case == 'billable':   # a reply would have used credits: nothing said, no wait command
            check(f'{case}/{who}: no hold line and no wait command (no reply at all)',
                  not any('holds at' in t for t in says) and not waits, (says, waits))
        else:   # an agent is held before its next step, which runs after the hold
            release = holds[-1][1]
            after = [e.get('timestamp') for e in es if e.get('type') == 'user' and ts(e['timestamp']) > release
                     and 'tool_result' in json.dumps(e['message'].get('content'))]
            check(f'{case}/{who}: its held step ran after the hold ended, with no wait command', bool(after) and not waits,
                  (after, waits))
    check(f'{case}: the session finished its task', 'DONE' in final, final[:200])
    if case == 'agent':
        check('agent: the held one was the background agent', any(v.get('agent') for v in rows.values()), list(rows))
    lines = [ln.rstrip() for ln in open(log)] if os.path.exists(log) else []
    print('-- log:\n   ' + '\n   '.join(lines))
    check(f'{case}: log has hold, wait and resume lines',
          all(any(f'limit  {w_} ' in ln for ln in lines) for w_ in ('hold  ', 'wait  ', 'resume')), lines)
    if case == 'billable':
        check('billable: the log says no reply', any('no reply: one now would use credits' in ln for ln in lines), lines)
    check(f'{case}: no errors in the log', not any(' error ' in ln for ln in lines), lines)
    check(f'{case}: no usage.json cache in the test folder', not os.path.exists(os.path.join(kit, 'usage.json')))
    shutil.rmtree(T)
    clean_projects(sid)


arg = (sys.argv[1:] or ['both'])[0]
for c in {'both': ['main', 'agent'], 'all': ['main', 'agent', 'billable']}.get(arg, sys.argv[1:]):
    run(c)
print(f'\n{len(failed)} failed' if failed else '\nall passed')
sys.exit(1 if failed else 0)
