"""Test install-hooks.py on copies only: a temp HOME with its own ~/.claude/settings.json, and a temp kit folder
(the parent of a copy of Resources/hooks). No model calls, no Chrome.

The Orchestrator's browser lock (browser-lock.py) is gone: the browser guard gives each agent its own Claude
window. A settings.json that still has a lock entry, at any path, loses it on a plain install, with
--orchestrator on and off, and with --remove. The browser guard (browser-guard.py) stays installed, and other
hooks are left alone.
Run: /usr/bin/python3 tools/install-hooks-test.py"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, 'Resources', 'hooks')
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


tmp = tempfile.mkdtemp(prefix='install-hooks-test-')
home = os.path.join(tmp, 'home')
ikit = os.path.join(tmp, 'ikit')
os.makedirs(os.path.join(home, '.claude'))
shutil.copytree(HOOKS, os.path.join(ikit, 'hooks'), ignore=shutil.ignore_patterns('__pycache__'))
SET = os.path.join(home, '.claude', 'settings.json')
IENV = dict(os.environ, HOME=home)
for k in ('STTARK_KIT_DIR', 'STTARK_KIT_LOG'):
    IENV.pop(k, None)

LIVE = '"/Users/someone/Library/Application Support/SttarkClaudeKit/hooks/browser-lock.py"'
OTHER_PATH = '/opt/old-kit/hooks/browser-lock.py'


def old_lock(settings):
    """Puts the old lock entries in, as the orchestrator build wrote them, plus one at another path that shares a
    group with someone's own hook."""
    hooks = settings.setdefault('hooks', {})
    hooks.setdefault('PreToolUse', []).append(
        {'matcher': '^(Bash|Agent|Task|mcp__claude-in-chrome__.*)$',
         'hooks': [{'type': 'command', 'command': LIVE, 'timeout': 60}]})
    hooks.setdefault('SubagentStop', []).append({'hooks': [{'type': 'command', 'command': LIVE, 'timeout': 10}]})
    hooks['SubagentStop'].append({'hooks': [{'type': 'command', 'command': 'own-stop.sh'},
                                            {'type': 'command', 'command': OTHER_PATH, 'timeout': 10}]})
    return settings


def seed():
    try:
        s = json.load(open(SET))
    except (OSError, ValueError):
        s = {}
    json.dump(old_lock(s), open(SET, 'w'), indent=2)


def install(*args):
    return subprocess.run([sys.executable, os.path.join(ikit, 'hooks', 'install-hooks.py')] + list(args),
                          capture_output=True, text=True, env=IENV).stdout.strip()


def text():
    return open(SET).read()


def lock_gone():
    return 'browser-lock.py' not in text()


def guard_in():
    s = json.load(open(SET))
    return any('browser-guard.py' in h.get('command', '')
               for g in s.get('hooks', {}).get('PreToolUse', []) for h in g.get('hooks', []))


def own_kept():
    s = json.load(open(SET))
    return (any(h.get('command') == 'own-hook.sh' for g in s['hooks'].get('PreToolUse', []) for h in g['hooks'])
            and any(h.get('command') == 'own-stop.sh' for g in s['hooks'].get('SubagentStop', []) for h in g['hooks']))


check('the lock hook file is gone from Resources/hooks', not os.path.exists(os.path.join(HOOKS, 'browser-lock.py')))

# a plain install (the app's launch run), switch off
json.dump({'model': 'x', 'hooks': {'PreToolUse': [{'matcher': 'Edit', 'hooks': [{'type': 'command',
                                                                                 'command': 'own-hook.sh'}]}]}},
          open(SET, 'w'))
seed()
check('seeded: settings have the old lock entries', text().count('browser-lock.py') == 3)
install()
check('plain install, switch off: old lock entries removed (any path)', lock_gone())
check('plain install, switch off: browser guard installed', guard_in())
check('plain install, switch off: own hooks and settings kept',
      own_kept() and json.load(open(SET)).get('model') == 'x')
check('plain install: no empty hook groups left',
      all(g.get('hooks') for gs in json.load(open(SET))['hooks'].values() for g in gs))

# --orchestrator on
seed()
out = install('--orchestrator', 'on')
check('--orchestrator on: old lock entries removed (any path)', lock_gone())
check('--orchestrator on: browser guard still installed', guard_in())
check('--orchestrator on: own hooks kept', own_kept())
check('--orchestrator on: output has no browser word',
      'browser' not in out and out.endswith('inline on, subrules on, uicheck on, daylog on, rotation on, prod on'))
status = json.loads(install('--status'))
check('--status: no browser key', 'browser' not in status)
check('--status: browser guard on', status.get('guard') is True)

# a plain install with the switch on (the launch run brings the hooks in line with it)
seed()
install()
check('plain install, switch on: old lock entries removed', lock_gone())
check('plain install, switch on: browser guard installed', guard_in())
check('plain install, switch on: launch run again is unchanged', install() == 'unchanged')

# --orchestrator off
seed()
out = install('--orchestrator', 'off')
check('--orchestrator off: old lock entries removed', lock_gone())
check('--orchestrator off: output has no browser word', 'browser' not in out)
check('--orchestrator off: browser guard still installed', guard_in())

# --remove
seed()
install('--remove')
check('--remove: old lock entries removed', lock_gone())
check('--remove: own hooks kept', own_kept())

shutil.rmtree(tmp, ignore_errors=True)
print(f'\n{len(passed)} passed, {len(failed)} failed')
sys.exit(1 if failed else 0)
