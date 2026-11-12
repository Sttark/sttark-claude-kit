#!/usr/bin/python3
"""Real Claude Code test of a session set to "never use credits; hold at 80%", on copies: a test state folder
and log, a stand-in usage file, and only this repo's limit hooks (the plain entry and the --hold entry, as
install-hooks.py adds them), in a clean environment. "Use credits at the usage limit" is on for every session
in the test state, to show the held session holds anyway.

  main   the session works through four Bash steps; usage goes from 50% to 85% partway, so the next step is
         stopped, Claude says the hold line and runs the wait, and the --hold hook waits with no model calls;
         usage then drops to 10% and the session finishes
  agent  the session starts a background agent that is in the middle of its steps when usage reaches 85%;
         the agent holds in its own wait and finishes after the drop

For each, it counts the assistant messages written while the hold ran (there must be none), and prints the
hold and resume times, the wait's output and the limit log lines.
Run: /usr/bin/python3 tools/limit-mode-claude-test.py [main|agent|both]   (MODEL=sonnet by default; HOLD=60 s)"""
import datetime, glob, json, os, shutil, subprocess, sys, tempfile, time, uuid

HOOK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../Resources/hooks/limit-hook.py'))
MODEL = os.environ.get('MODEL', 'sonnet')
HOLD = int(os.environ.get('HOLD', '60'))   # seconds the stand-in stays at 85% after the hold starts
PROMPTS = {
    'main': 'Run these four Bash commands, one per tool call, in this order, and nothing else: `echo step1`, '
            '`python3 -c "import time; time.sleep(25)"`, `echo step2`, `echo step3`. Then reply with the single word DONE.',
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
    json.dump({'extra_usage': {'is_enabled': True},
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
    set_usage(use, 50)
    cmd = f'/usr/bin/python3 "{HOOK}"'   # the installed copy is executable; this one may not be
    json.dump({'hooks': {
        'PreToolUse': [{'hooks': [{'type': 'command', 'command': cmd, 'timeout': 60}]},
                       {'hooks': [{'type': 'command', 'command': cmd + ' --hold', 'timeout': 691200}]}],
        'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': cmd, 'timeout': 60}]}]},
        'permissions': {'allow': ['Bash']}}, open(os.path.join(w, '.claude/settings.json'), 'w'))
    env = {k: os.environ[k] for k in ('HOME', 'USER', 'PATH', 'TMPDIR', 'LANG') if k in os.environ}
    env.update(STTARK_KIT_DIR=kit, STTARK_KIT_LOG=log, STTARK_LIMIT_TEST=use,
               STTARK_LIMIT_EVENTS=os.path.join(T, 'events.json'))
    out = open(os.path.join(T, 'out.jsonl'), 'w')
    t0 = time.time()
    p = subprocess.Popen(['claude', '-p', PROMPTS[case], '--session-id', sid, '--setting-sources', 'project',
                          '--permission-mode', 'bypassPermissions', '--output-format', 'stream-json', '--verbose',
                          '--model', MODEL], cwd=w, env=env, stdout=out, stderr=subprocess.STDOUT)
    time.sleep(18 if case == 'main' else 22)   # in the middle of the 25-second wait step
    set_usage(use, 85)
    t85 = time.time()
    print(f'usage at 85% after {t85 - t0:.0f} s')
    rows, t_hold = {}, None
    while time.time() - t85 < 240 and p.poll() is None:
        pauses = json.load(open(os.path.join(kit, 'state.json'))).get('limit_pauses') or {}
        for k, v in pauses.items():
            if v.get('what') == 'hold' and k not in rows:
                rows[k] = dict(v, alive=subprocess.run(['kill', '-0', str(v['pid'])]).returncode == 0)
                print(f'hold started after {v["since"] - t0:.0f} s: row {k[:8]}{"/" + v["agent"][:8] if v.get("agent") else ""}'
                      f' mode {v["mode"]} at {v["at"]}% percent {v["percent"]} pid {v["pid"]} alive {rows[k]["alive"]}')
                t_hold = t_hold or v['since']
        if t_hold and time.time() - t_hold >= HOLD:
            break
        time.sleep(1)
    check(f'{case}: a hold started in the --hold hook', bool(rows), 'no hold row')
    set_usage(use, 10)
    t_release = time.time()
    print(f'usage at 10% after {t_release - t0:.0f} s' + (f' (held {t_release - t_hold:.0f} s)' if t_hold else ''))
    try:
        p.wait(timeout=300)
    except subprocess.TimeoutExpired:
        p.kill()
        check(f'{case}: the session finished', False, 'timed out')
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
        who = 'main' if tp == main_tp else 'agent ' + os.path.basename(tp)[6:14]
        key = sid if tp == main_tp else sid + '/' + os.path.basename(tp)[6:-6]
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
        if key in rows:
            since = rows[key]['since']
            during = [e.get('timestamp') for e in es if e.get('type') == 'assistant' and since + 1 < ts(e['timestamp']) < t_release]
            check(f'{case}/{who}: no model calls while the hook held ({t_release - since:.0f} s)', not during, during)
            if tp == main_tp:   # the session says the line and waits in the open
                check(f'{case}/{who}: said the hold line', any('holds at 80% usage' in t for t in says), says)
                check(f'{case}/{who}: the wait printed GO ON', bool(results), results)
            else:   # an agent is held before its next step, which runs after the hold
                after = [e.get('timestamp') for e in es if e.get('type') == 'user' and ts(e['timestamp']) > t_release
                         and 'tool_result' in json.dumps(e['message'].get('content'))]
                check(f'{case}/{who}: its held step ran after the hold ended, with no wait command', bool(after) and not waits,
                      (after, waits))
    check(f'{case}: the session finished its task', 'DONE' in final, final[:200])
    if case == 'agent':
        check('agent: the held one was the background agent', any('/' in k for k in rows), list(rows))
    lines = [ln.rstrip() for ln in open(log)] if os.path.exists(log) else []
    print('-- log:\n   ' + '\n   '.join(lines))
    check(f'{case}: log has hold, wait and resume lines',
          all(any(f'limit  {w_} ' in ln for ln in lines) for w_ in ('hold  ', 'wait  ', 'resume')), lines)
    check(f'{case}: no usage.json cache in the test folder', not os.path.exists(os.path.join(kit, 'usage.json')))
    shutil.rmtree(T)


for c in (['main', 'agent'] if (sys.argv[1:] or ['both'])[0] == 'both' else sys.argv[1:]):
    run(c)
print(f'\n{len(failed)} failed' if failed else '\nall passed')
sys.exit(1 if failed else 0)
