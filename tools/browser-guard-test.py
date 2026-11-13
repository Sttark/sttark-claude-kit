#!/usr/bin/python3
"""Tests of the browser guard (Resources/hooks/browser-guard.py), all on copies: a temp state folder and log,
and a temp HOME for install-hooks.py. It feeds the hook the JSON Claude Code sends (a main session and a
subagent), and checks each step it must stop and each one it must let through, with the switch off, and after
the person asks for Claude in Chrome by name. Nothing real is read or written, and no model is called.
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
             '<task-notification>agent used Claude in Chrome</task-notification>'):
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
      len(pre) == 1 and pre[0].get('matcher') == 'Bash|mcp__claude-in-chrome__.*|mcp__Control_Chrome__.*', pre)
check('install: one UserPromptSubmit entry', len(ups) == 1 and 'matcher' not in ups[0], ups)
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
