#!/usr/bin/python3
"""Tests of the browser guard (Resources/hooks/browser-guard.py), all on copies: a temp state folder and log,
and a temp HOME for install-hooks.py. It feeds the hook the JSON Claude Code sends (a main session and a
subagent), and checks each step it must stop and each one it must let through, with the switch off, and after
the person asks for Claude in Chrome by name. It also checks the agent's id that the hook puts in front of an
agent's commands (so claude-window gives each agent its own tab): in which sessions, and never for the session
itself; and the step when an agent stops, with a stand-in for claude-window. Nothing real is read or written, and
no model is called.
Prints each case; exits 1 if any fails.
Run: /usr/bin/python3 tools/browser-guard-test.py"""
import json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.normpath(os.path.join(HERE, '../Resources/hooks/browser-guard.py'))
INSTALL = os.path.normpath(os.path.join(HERE, '../Resources/hooks/install-hooks.py'))
T = tempfile.mkdtemp(prefix='browser-guard-test-')
HOME = os.path.join(T, 'home')
KIT = os.path.join(T, 'kit')
LOG = os.path.join(T, 'log')
for k in [k for k in os.environ if k.startswith('CLAUDE')]:
    del os.environ[k]
os.environ.update(HOME=HOME, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG)
os.makedirs(HOME)
os.makedirs(KIT)
STATE = os.path.join(KIT, 'state.json')
SID = '5d1e0c7a-1111-2222-3333-444455556666'
OTHER = '9f00aa11-1111-2222-3333-444455556666'
failed = []


def check(name, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + name + ('' if ok else f'  -- {detail}'))
    if not ok:
        failed.append(name)


def state(**kv):
    json.dump(kv, open(STATE, 'w'))


def run(data):
    t = time.time()
    p = subprocess.run(['/usr/bin/python3', HOOK], input=json.dumps(data), capture_output=True, text=True, timeout=20)
    return p.stdout.strip(), p.returncode, time.time() - t


def tool(name, inp, sid=SID, agent=None):
    d = {'hook_event_name': 'PreToolUse', 'session_id': sid, 'tool_name': name, 'tool_input': inp,
         'tool_use_id': 'toolu_x', 'cwd': '/tmp', 'transcript_path': '/tmp/none.jsonl'}
    if agent:
        d['agent_id'] = agent
    return d


def decision(out):
    if not out:
        return 'allow'
    try:
        return json.loads(out)['hookSpecificOutput']['permissionDecision']
    except (ValueError, KeyError):
        return 'bad output: ' + out[:80]


def expect(label, data, want):
    out, rc, secs = run(data)
    got = decision(out)
    check(f'{want:5} {label}', got == want and rc == 0, f'got {got} rc {rc}')
    return out


BLOCK = [
    ('open -a "Google Chrome" https://x.com', 'open -a "Google Chrome" https://example.com'),
    ('open -a Chrome', 'open -a Chrome'),
    ("open -a 'Google Chrome'", "open -a 'Google Chrome'"),
    ('open -na Google\\ Chrome', 'open -na Google\\ Chrome --args --new-window'),
    ('open -a /Applications/Google Chrome.app', 'open -a "/Applications/Google Chrome.app" ~/x.html'),
    ('open -b com.google.Chrome', 'open -b com.google.Chrome'),
    ('open https URL', 'open https://docs.sttark.com/x'),
    ('open http URL after cd &&', 'cd /tmp && open http://localhost:3000'),
    ('/usr/bin/open URL', '/usr/bin/open "https://example.com"'),
    ('sudo -u x open URL', 'sudo -u griffin open https://example.com'),
    ('open URL in $()', 'x=$(open https://example.com)'),
    ('bash -c open -a Chrome', "bash -c 'open -a \"Google Chrome\"'"),
    ('osascript tell application', 'osascript -e \'tell application "Google Chrome" to activate\''),
    ('osascript tell application id', 'osascript -e \'tell application id "com.google.Chrome" to get URL of tab 1 of window 1\''),
    ('osascript JXA Application()', 'osascript -l JavaScript -e \'Application("Google Chrome").windows[0].tabs[0].url()\''),
    ('osascript heredoc', 'osascript <<EOF\ntell application "Google Chrome"\n  make new window\nend tell\nEOF'),
    ('echo | osascript', 'echo \'tell application "Google Chrome" to activate\' | osascript'),
    ('Chrome binary', '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" https://example.com'),
    ('Chrome binary escaped', '/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --new-window'),
    ('second line of a script', 'sleep 1\nopen -a "Google Chrome"'),
]

ALLOW = [
    ('claude-window go', 'claude-window go https://docs.sttark.com'),
    ('claude-window text', 'claude-window text 4000'),
    ('open a file', 'open ~/Desktop/report.pdf'),
    ('open -a Preview', 'open -a Preview chart.png'),
    ('open -R', 'open -R ~/Downloads/x.zip'),
    ('ps | grep Chrome', 'ps aux | grep "Google Chrome"'),
    ('pkill Chrome test', 'pkill -f "Google Chrome for Testing"'),
    ('grep the osascript text', 'grep -rn \'tell application "Google Chrome"\' ~/notes'),
    ('heredoc into a file', "cat > /tmp/x.sh <<'EOF'\nopen -a \"Google Chrome\" https://example.com\nosascript -e 'tell application \"Google Chrome\" to activate'\nEOF\nchmod +x /tmp/x.sh"),
    ('echo text', 'echo "run open -a Chrome https://x.com to see it"'),
    ('git commit message', 'git commit -m "block open https://x and osascript to Chrome"'),
    ('playwright', 'npx playwright test --project=chromium'),
    ('puppeteer node', 'node scripts/shot.js --browser chrome'),
    ('chromium headless', 'chromium --headless --screenshot https://example.com'),
    ('Chrome binary headless', '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --dump-dom https://x.com'),
    ('Chrome binary own profile', '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir=/tmp/p https://x.com'),
    ('Chrome --version', '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --version'),
    ('osascript Messages', 'osascript -e \'tell application "Messages" to get name\''),
    ('python open()', 'python3 -c "print(open(\'/tmp/x\').read())"'),
    ('comment', 'ls  # then open https://example.com'),
    ('openssl', 'openssl rand -hex 8'),
]

MCP = ['mcp__claude-in-chrome__tabs_context_mcp', 'mcp__claude-in-chrome__navigate',
       'mcp__Control_Chrome__open_url', 'mcp__Control_Chrome__list_tabs']

# --- switch on, no opt-in ---
state(claude_window=True, sessions={})
for who, agent in (('main', None), ('agent', 'a91f3c02deadbeef')):
    for label, cmd in BLOCK:
        expect(f'{who}: {label}', tool('Bash', {'command': cmd}, agent=agent), 'deny')
    for name in MCP:
        expect(f'{who}: {name}', tool(name, {'createIfEmpty': True}, agent=agent), 'deny')
for label, cmd in ALLOW:
    expect(f'main: {label}', tool('Bash', {'command': cmd}), 'allow')
expect('main: built-in browser pane', tool('mcp__Claude_Browser__navigate', {'url': 'http://localhost:3000'}), 'allow')
expect('main: Read', tool('Read', {'file_path': '/tmp/x'}), 'allow')

out, _, _ = run(tool('mcp__claude-in-chrome__navigate', {'url': 'https://x.com'}))
reason = json.loads(out)['hookSpecificOutput']['permissionDecisionReason']
check('reason names claude-window and the browser pane', 'claude-window go' in reason and 'mcp__Claude_Browser__' in reason, reason)
logtext = open(LOG).read()
check('deny is logged with the browser tag and the agent', 'browser deny   5d1e0c7a/a91f3c02 mcp__claude-in-chrome__tabs_context_mcp' in logtext, logtext[-400:])

# --- the fast path: a Bash command with nothing to look at answers quickly ---
_, _, secs = run(tool('Bash', {'command': 'ls -la'}))
check(f'fast path ({secs * 1000:.0f} ms)', secs < 1.0)

# --- switch off: everything goes through ---
state(claude_window=False, sessions={})
for label, cmd in BLOCK[:3]:
    expect(f'switch off: {label}', tool('Bash', {'command': cmd}), 'allow')
expect('switch off: Claude in Chrome', tool(MCP[0], {}), 'allow')
os.remove(STATE)
expect('no state file: Claude in Chrome', tool(MCP[0], {}), 'allow')

# --- opt-in by the person ---
state(claude_window=True, sessions={}, chrome_ok={'old-session': {'at': time.time() - 30 * 86400}})


def prompt(text, sid=SID):
    return run({'hook_event_name': 'UserPromptSubmit', 'session_id': sid, 'prompt': text, 'cwd': '/tmp'})[0]


for text in ("don't use Claude in Chrome for this", 'never use control chrome', 'the window takes my screen',
             'claude sometimes takes my chrome', "don't use my own chrome",
             '<task-notification>agent used Claude in Chrome</task-notification>',
             '[Sttark Claude Kit] Check-in: The agent tried to use Claude in Chrome, and the Kit stopped it.'):
    out = prompt(text)
    check(f'no opt-in: {text[:45]!r}', out == '' and SID not in (json.load(open(STATE)).get('chrome_ok') or {}), out)
out = prompt('Please use Claude in Chrome to check the order page')
s = json.load(open(STATE))
check('opt-in: "use Claude in Chrome" marks the session', SID in s.get('chrome_ok', {}), s)
check('opt-in: tells Claude', 'additionalContext' in out, out)
check('opt-in: old entries dropped', 'old-session' not in s.get('chrome_ok', {}), s)
check('opt-in: other keys kept', s.get('claude_window') is True and 'sessions' in s, s)
check('opt-in is logged', 'browser allow  5d1e0c7a Claude in Chrome' in open(LOG).read())
expect('opted-in main: Claude in Chrome', tool(MCP[0], {'createIfEmpty': True}), 'allow')
expect('opted-in agent: Claude in Chrome', tool(MCP[1], {}, agent='a91f3c02deadbeef'), 'allow')
expect('opted-in main: open -a Chrome', tool('Bash', {'command': 'open -a "Google Chrome"'}), 'allow')
expect('other session still blocked', tool(MCP[0], {}, sid=OTHER), 'deny')
for text in ('open it in my Chrome tab', 'do it in my chrome', 'control chrome please',
             'Use my own Chrome for this', 'check it with my chrome'):
    prompt(text, sid=OTHER + text[:3])
    check(f'opt-in phrase: {text!r}', OTHER + text[:3] in json.load(open(STATE)).get('chrome_ok', {}))
state(claude_window=True, chrome_ok={SID: {'at': time.time() - 8 * 86400}})
expect('opt-in older than 7 days: blocked again', tool(MCP[0], {}), 'deny')
state(claude_window=False)
prompt('use Claude in Chrome', sid=OTHER)
check('switch off: no opt-in written', 'chrome_ok' not in json.load(open(STATE)))

# --- a tab for each agent: the agent's id goes in front of its commands, only where no prompt can come from it ---
state(claude_window=True, sessions={})
AG = 'a91f3c02deadbeef'


def rewrite(data, **env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    out = run(data)[0]
    for k, v in old.items():
        if v is None:
            del os.environ[k]
        else:
            os.environ[k] = v
    try:
        return json.loads(out)['hookSpecificOutput'].get('updatedInput', {}).get('command') if out else None
    except (ValueError, KeyError):
        return 'bad output: ' + out[:80]


def call(cmd='ls -la', mode='bypassPermissions', agent=AG, name='Bash'):
    return dict(tool(name, {'command': cmd, 'description': 'd'}, agent=agent), permission_mode=mode)


want = f'export CLAUDE_WINDOW_AGENT={AG}; ls -la'
check('agent, Bypass permissions: its id goes in front', rewrite(call()) == want, rewrite(call()))
out = json.loads(run(call())[0])['hookSpecificOutput']
check('agent: other input kept, no permission decision', out['updatedInput'].get('description') == 'd' and 'permissionDecision' not in out, out)
check('session itself: nothing added', rewrite(call(agent=None)) is None)
check('agent, a Monitor command: its id goes in front', rewrite(call(name='Monitor')) == want)
check('agent, a script it runs: its id goes in front', rewrite(call('python3 helper.py')) == f'export CLAUDE_WINDOW_AGENT={AG}; python3 helper.py')
check('agent, command that has the id already: left as it is', rewrite(call(want)) is None)
check('agent, an id that is not safe in a command: nothing added', rewrite(call(agent='a1;rm -rf x')) is None)
for mode in ('default', 'bubble', 'acceptEdits', 'auto', 'plan', 'dontAsk', ''):
    check(f'agent, mode {mode or "(none)"}, no Kit bypass hook: nothing added', rewrite(call(mode=mode)) is None)
os.makedirs(os.path.join(HOME, '.claude'), exist_ok=True)
json.dump({'hooks': {'PermissionRequest': [{'hooks': [{'type': 'command', 'command': '"/k/hooks/bypass-hook.sh"'}]}]}},
          open(os.path.join(HOME, '.claude/settings.json'), 'w'))
RCCHAIN, PLAIN = os.path.join(T, 'chain-rc'), os.path.join(T, 'chain-plain')
open(RCCHAIN, 'w').write('/bin/sh -c hook\n/x/claude --print --sdk-url https://x\n/x/claude rc --permission-mode bypassPermissions\n')
open(PLAIN, 'w').write('/bin/sh -c hook\n/x/claude\n-zsh\n')
for mode in ('default', 'bubble', 'acceptEdits'):
    check(f'agent, mode {mode}, on a server the bypass hook answers for: its id goes in front',
          rewrite(call(mode=mode), STTARK_GUARD_CHAIN=RCCHAIN) == want)
check('agent, auto mode on that server: nothing added', rewrite(call(mode='auto'), STTARK_GUARD_CHAIN=RCCHAIN) is None)
check('agent, Manual in a session the bypass hook does not answer for: nothing added',
      rewrite(call(mode='default'), STTARK_GUARD_CHAIN=PLAIN) is None)
os.remove(os.path.join(HOME, '.claude/settings.json'))
os.rmdir(os.path.join(HOME, '.claude'))
expect('agent: a step that opens Chrome is still stopped', call('open -a "Google Chrome"'), 'deny')
state(claude_window=False, sessions={})
check('switch off: nothing added', rewrite(call()) is None)
state(claude_window=True, sessions={})

# --- the agent stopped: its window goes back, through claude-window agent-done, only when it has a tab or a window ---
HOOKS2 = os.path.join(T, 'hooks2')
os.makedirs(HOOKS2)
shutil.copy(HOOK, HOOKS2)
CALLS = os.path.join(T, 'window-calls')
open(os.path.join(HOOKS2, 'claude-window.sh'), 'w').write('#!/bin/zsh\nprint -r -- "$*" >> "%s"\n' % CALLS)


def stop(agent):
    subprocess.run(['/usr/bin/python3', os.path.join(HOOKS2, 'browser-guard.py')], capture_output=True, text=True, timeout=20,
                   input=json.dumps({'hook_event_name': 'SubagentStop', 'session_id': SID, 'agent_id': agent}))
    return open(CALLS).read() if os.path.exists(CALLS) else ''


check('agent stopped, no tab: claude-window is not run', stop(AG) == '')
os.makedirs(os.path.join(KIT, 'claude-window-tabs'))
open(os.path.join(KIT, 'claude-window-tabs', f'{SID}.{AG}'), 'w').write('1 2 3\n')
check('agent stopped, with a tab: claude-window agent-done <its id>', stop(AG) == f'agent-done {AG}\n', stop(AG))
check('another agent stopped: claude-window is not run again', stop('abc') == f'agent-done {AG}\nagent-done {AG}\n')
os.makedirs(os.path.join(KIT, 'claude-window-wins'))
open(os.path.join(KIT, 'claude-window-wins', f'{SID}.w1nd0w'), 'w').write('3 2\n')
check('agent stopped, with a window and no tab: claude-window agent-done <its id>', stop('w1nd0w').endswith('agent-done w1nd0w\n'), stop('w1nd0w'))

# --- never crash a tool call ---
p = subprocess.run(['/usr/bin/python3', HOOK], input='not json', capture_output=True, text=True)
check('bad input: no output, exit 0', p.stdout == '' and p.returncode == 0, p.stdout + p.stderr)
open(STATE, 'w').write('{broken')
expect('broken state file: allow', tool(MCP[0], {}), 'allow')

# --- install-hooks.py on a temp HOME ---
os.makedirs(os.path.join(HOME, '.claude'))
json.dump({'model': 'x', 'hooks': {'PreToolUse': [{'matcher': 'Edit', 'hooks': [{'type': 'command', 'command': 'mine'}]}]}},
          open(os.path.join(HOME, '.claude/settings.json'), 'w'))
subprocess.run(['/usr/bin/python3', INSTALL], capture_output=True, text=True, check=True)
subprocess.run(['/usr/bin/python3', INSTALL], capture_output=True, text=True, check=True)   # twice: no copies
st = json.load(open(os.path.join(HOME, '.claude/settings.json')))
pre = [g for g in st['hooks']['PreToolUse'] if any('browser-guard.py' in h['command'] for h in g['hooks'])]
ups = [g for g in st['hooks']['UserPromptSubmit'] if any('browser-guard.py' in h['command'] for h in g['hooks'])]
check('install: one PreToolUse entry with the matcher',
      len(pre) == 1 and pre[0].get('matcher') == 'Bash|Monitor|mcp__claude-in-chrome__.*|mcp__Control_Chrome__.*', pre)
check('install: one UserPromptSubmit entry', len(ups) == 1 and 'matcher' not in ups[0], ups)
stops = [g for g in st['hooks'].get('SubagentStop', []) if any('browser-guard.py' in h['command'] for h in g['hooks'])]
check('install: one SubagentStop entry', len(stops) == 1 and 'matcher' not in stops[0], stops)
check('install: own hooks and settings kept', st.get('model') == 'x' and st['hooks']['PreToolUse'][0]['matcher'] == 'Edit')
status = json.loads(subprocess.run(['/usr/bin/python3', INSTALL, '--status'], capture_output=True, text=True).stdout)
check('install: --status says guard', status.get('guard') is True, status)
subprocess.run(['/usr/bin/python3', INSTALL, '--remove'], capture_output=True, text=True, check=True)
st = json.load(open(os.path.join(HOME, '.claude/settings.json')))
check('install: --remove takes it out', 'browser-guard.py' not in json.dumps(st), st)
check('install: --remove keeps own hooks', st['hooks']['PreToolUse'][0]['matcher'] == 'Edit', st)

shutil.rmtree(T)
print(f'\n{"FAILED: " + ", ".join(failed) if failed else "all passed"} ({len(failed)} failed)')
sys.exit(1 if failed else 0)
