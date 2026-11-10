#!/usr/bin/python3
"""Add the effort hook to Claude Code's settings (~/.claude/settings.json), or
take it out with --remove. Run by the Sttark Claude Kit app on every launch, so a
hook that went missing comes back.

--names on|off adds or removes the session naming hook ("Name sessions
automatically"), --profile on|off the profile instructions hook (the "Sync Claude
profile instructions" switch), and --bypass on|off the bypass hook (the "Bypass permissions for
server sessions" switch) and leaves the effort hook alone. The app rules hook
(app-rules-hook.py, no switch) goes in with the effort hook, and so do the working rules
hooks (working-rules-hook.py, the "Sttark working rules" switch, on by default) unless
--working off was run, which leaves a marker in the app's folder; --working on removes it.
The usage limit hook (limit-hook.py) also goes in with the effort hook; the menu's "Use credits at
the usage limit" switch is a setting it reads, not a hook change.
--orchestrator on|off sets the "Orchestrator" switch (off by default, kept as "orchestrator" in the
app's state.json) and copies the orchestrator skills and agents into ~/.claude/skills and ~/.claude/agents,
or takes them out. Every run without a switch brings the copies in line with the switch; --remove takes
them out. Only copies this script made are replaced or removed (listed in orchestrator-installed.json);
a skill or agent of the same name that someone put there by hand is left alone.
The inline guard hooks (inline-guard.py: PreToolUse, PostToolUse and UserPromptSubmit) go in only while the
Orchestrator switch is on, and come out when it is off and with --remove. So does the subagent rules hook
(subagent-rules-hook.py: SubagentStart), which gives subagents the worker rules.
--status prints which are on. Other settings and hooks are left as they are, and a backup is saved
before any change.
"""
import fcntl, json, os, shutil, sys, time

SETTINGS = os.path.expanduser('~/.claude/settings.json')
HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'effort-hook.py')
COMMAND = f'"{HOOK}"'
BYPASS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bypass-hook.sh')


def is_bypass(cmd):
    c = cmd.rstrip('"')
    return c.endswith('bypass-hook.sh')  # this app's copy, or one set up by hand as rc-bypass-hook.sh


NAMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'name-hook.py')


def is_names(cmd):
    return cmd.rstrip('"').endswith('name-hook.py')


PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'profile-hook.sh')


def is_profile(cmd):
    c = cmd.rstrip('"')
    return c.endswith('profile-hook.sh') or c.endswith('profile-instructions-hook.sh')  # this app's, or one set up by hand


RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app-rules-hook.py')
RULES_PARTS = 8  # app-rules-hook.py's PARTS: one UserPromptSubmit entry per part


def is_rules(cmd):
    return 'app-rules-hook.py' in cmd


def set_rules(hooks, on):
    for event in ('UserPromptSubmit', 'SessionStart'):
        groups = hooks.get(event, [])
        for g in groups:
            g['hooks'] = [h for h in g.get('hooks', []) if not is_rules(h.get('command', ''))]
        groups = [g for g in groups if g.get('hooks')]
        if on and event == 'UserPromptSubmit':
            groups.append({'hooks': [{'type': 'command', 'command': f'"{RULES}" {i}', 'timeout': 10}
                                     for i in range(1, RULES_PARTS + 1)]})
        if on and event == 'SessionStart':
            groups.append({'matcher': 'compact',
                           'hooks': [{'type': 'command', 'command': f'"{RULES}" --compacted', 'timeout': 10}]})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)


WORKING = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'working-rules-hook.py')
WORKING_OFF = os.path.expanduser('~/Library/Application Support/SttarkClaudeKit/working-rules.off')


def is_working(cmd):
    return 'working-rules-hook.py' in cmd


def set_working(hooks, on):
    """The rules in front of every prompt, right after the person's own instructions when the profile hook
    is on, and the STE check when a reply ends."""
    for event in ('UserPromptSubmit', 'Stop'):
        groups = hooks.get(event, [])
        for g in groups:
            g['hooks'] = [h for h in g.get('hooks', []) if not is_working(h.get('command', ''))]
        groups = [g for g in groups if g.get('hooks')]
        if on and event == 'UserPromptSubmit':
            after = [i for i, g in enumerate(groups) if any(is_profile(h.get('command', '')) for h in g['hooks'])]
            groups.insert(after[0] + 1 if after else 0,
                          {'hooks': [{'type': 'command', 'command': f'"{WORKING}"', 'timeout': 10}]})
        if on and event == 'Stop':
            groups.append({'hooks': [{'type': 'command', 'command': f'"{WORKING}" --check', 'timeout': 60,
                                      'async': True}]})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)


LIMIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'limit-hook.py')
LIMIT_WAIT = 60  # the hooks only check and answer; the wait runs as a visible command (claude-limit-wait)


def is_limit(cmd):
    return 'limit-hook.py' in cmd


def set_limit(hooks, on):
    """Before every tool call, and on every message: wait at the usage limit instead of spending credits."""
    for event in ('PreToolUse', 'UserPromptSubmit'):
        groups = hooks.get(event, [])
        for g in groups:
            g['hooks'] = [h for h in g.get('hooks', []) if not is_limit(h.get('command', ''))]
        groups = [g for g in groups if g.get('hooks')]
        if on:
            groups.append({'hooks': [{'type': 'command', 'command': f'"{LIMIT}"',
                                      'timeout': LIMIT_WAIT}]})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)


KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the app's folder: hooks/ sits in it
KIT_STATE = os.path.join(KIT, 'state.json')
ORCH_SRC = {'skills': os.path.join(KIT, 'skills'), 'agents': os.path.join(KIT, 'agents')}
ORCH_DEST = {k: os.path.expanduser(f'~/.claude/{k}') for k in ORCH_SRC}
ORCH_MANIFEST = os.path.join(KIT, 'orchestrator-installed.json')


def orchestrator_on():
    try:
        return json.load(open(KIT_STATE)).get('orchestrator') is True
    except (OSError, ValueError):
        return False


def set_orchestrator_state(on):
    """The switch, in state.json, under the lock the app and the hooks share."""
    os.makedirs(KIT, exist_ok=True)
    with open(KIT_STATE + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            s = json.load(open(KIT_STATE))
        except (OSError, ValueError):
            s = {}
        s['orchestrator'] = on
        tmp = KIT_STATE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, KIT_STATE)


def sync_orchestrator(on):
    """Copies each skill folder and agent file in, or takes out the ones this script put in.
    Returns a short word for the log, or None when nothing changed."""
    try:
        made = json.load(open(ORCH_MANIFEST))
    except (OSError, ValueError):
        made = []
    want, skipped = [], []
    if on:
        for kind, src in ORCH_SRC.items():
            for name in sorted(os.listdir(src)) if os.path.isdir(src) else []:
                if name.startswith('.') or (kind == 'skills' and not os.path.isdir(os.path.join(src, name))):
                    continue
                if kind == 'agents' and not name.endswith('.md'):
                    continue
                dest = os.path.join(ORCH_DEST[kind], name)
                if os.path.lexists(dest) and dest not in made:
                    skipped.append(dest)
                    continue
                want.append((os.path.join(src, name), dest))
    changed = False
    for dest in made:
        if dest not in [d for _, d in want] and os.path.lexists(dest):
            shutil.rmtree(dest) if os.path.isdir(dest) and not os.path.islink(dest) else os.remove(dest)
            changed = True
    for src, dest in want:
        if os.path.isdir(src):
            if os.path.isdir(dest) and same_tree(src, dest):
                continue
            if os.path.lexists(dest):
                shutil.rmtree(dest)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copytree(src, dest)
        else:
            if os.path.isfile(dest) and open(src, 'rb').read() == open(dest, 'rb').read():
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
        changed = True
    now = [d for _, d in want]
    if now != made:
        if now:
            with open(ORCH_MANIFEST, 'w') as f:
                json.dump(now, f, indent=1)
        elif os.path.exists(ORCH_MANIFEST):
            os.remove(ORCH_MANIFEST)
    word = None
    if changed:
        word = f'orchestrator {"on" if on else "off"}: {len(now)} skills and agents in ~/.claude'
    if skipped:
        word = (word or 'orchestrator') + '; left alone, not ours: ' + ', '.join(skipped)
    return word


GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'inline-guard.py')


def is_guard(cmd):
    return 'inline-guard.py' in cmd


def set_guard(hooks, on):
    """The inline guard: with the Orchestrator switch on, the main agent gives worker jobs to subagents."""
    for event in ('PreToolUse', 'PostToolUse', 'UserPromptSubmit'):
        groups = hooks.get(event, [])
        for g in groups:
            g['hooks'] = [h for h in g.get('hooks', []) if not is_guard(h.get('command', ''))]
        groups = [g for g in groups if g.get('hooks')]
        if on:
            groups.append({'hooks': [{'type': 'command', 'command': f'"{GUARD}"', 'timeout': 10}]})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)


SUBRULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'subagent-rules-hook.py')


def is_subrules(cmd):
    return 'subagent-rules-hook.py' in cmd


def set_subrules(hooks, on):
    """The worker rules for subagents, added at SubagentStart, with the Orchestrator switch on."""
    groups = hooks.get('SubagentStart', [])
    for g in groups:
        g['hooks'] = [h for h in g.get('hooks', []) if not is_subrules(h.get('command', ''))]
    groups = [g for g in groups if g.get('hooks')]
    if on:
        groups.append({'hooks': [{'type': 'command', 'command': f'"{SUBRULES}"', 'timeout': 10}]})
    if groups:
        hooks['SubagentStart'] = groups
    else:
        hooks.pop('SubagentStart', None)


def same_tree(a, b):
    def files(root):
        out = {}
        for d, _, fs in os.walk(root):
            for f in fs:
                p = os.path.join(d, f)
                out[os.path.relpath(p, root)] = open(p, 'rb').read()
        return out
    return files(a) == files(b)


def ours(cmd):
    return cmd.rstrip('"').endswith('effort-hook.py')


def load():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def has(s, event, test):
    return any(test(h.get('command', '')) for g in s.get('hooks', {}).get(event, []) for h in g.get('hooks', []))


def set_bypass(hooks, on):
    groups = hooks.get('PermissionRequest', [])
    for g in groups:
        g['hooks'] = [h for h in g.get('hooks', []) if not is_bypass(h.get('command', ''))]
    groups = [g for g in groups if g.get('hooks')]
    if on:
        groups.append({'hooks': [{'type': 'command', 'command': f'"{BYPASS}"', 'timeout': 10}]})
    if groups:
        hooks['PermissionRequest'] = groups
    else:
        hooks.pop('PermissionRequest', None)


def set_profile(hooks, on):
    groups = hooks.get('UserPromptSubmit', [])
    for g in groups:
        g['hooks'] = [h for h in g.get('hooks', []) if not is_profile(h.get('command', ''))]
    groups = [g for g in groups if g.get('hooks')]
    if on:
        groups.insert(0, {'hooks': [{'type': 'command', 'command': f'"{PROFILE}"', 'timeout': 10}]})
    if groups:
        hooks['UserPromptSubmit'] = groups
    else:
        hooks.pop('UserPromptSubmit', None)


def set_names(hooks, on):
    groups = hooks.get('UserPromptSubmit', [])
    for g in groups:
        g['hooks'] = [h for h in g.get('hooks', []) if not is_names(h.get('command', ''))]
    groups = [g for g in groups if g.get('hooks')]
    if on:
        groups.append({'hooks': [{'type': 'command', 'command': f'"{NAMES}"', 'timeout': 40}]})
    if groups:
        hooks['UserPromptSubmit'] = groups
    else:
        hooks.pop('UserPromptSubmit', None)


def main():
    s = load()
    if '--status' in sys.argv:
        print(json.dumps({'effort': has(s, 'UserPromptSubmit', ours),
                          'bypass': has(s, 'PermissionRequest', is_bypass),
                          'profile': has(s, 'UserPromptSubmit', is_profile),
                          'names': has(s, 'UserPromptSubmit', is_names),
                          'rules': has(s, 'UserPromptSubmit', is_rules),
                          'working': has(s, 'UserPromptSubmit', is_working) and has(s, 'Stop', is_working),
                          'limit': has(s, 'PreToolUse', is_limit),
                          'orchestrator': orchestrator_on(),
                          'guard': has(s, 'PreToolUse', is_guard),
                          'subrules': has(s, 'SubagentStart', is_subrules)}))
        return
    if '--orchestrator' in sys.argv:
        on = sys.argv[sys.argv.index('--orchestrator') + 1] == 'on'
        set_orchestrator_state(on)
        word = sync_orchestrator(on)
        before = json.dumps(s, sort_keys=True)
        set_guard(s.setdefault('hooks', {}), on)
        set_subrules(s['hooks'], on)
        if save(s, before, None):
            word = (word + '; ' if word else '') + 'guard ' + ('on' if on else 'off')
        print(word or 'unchanged')
        return
    remove = '--remove' in sys.argv
    before = json.dumps(s, sort_keys=True)
    hooks = s.setdefault('hooks', {})
    if '--bypass' in sys.argv:
        set_bypass(hooks, sys.argv[sys.argv.index('--bypass') + 1] == 'on')
        return save(s, before, 'bypass ' + sys.argv[sys.argv.index('--bypass') + 1])
    if '--names' in sys.argv:
        set_names(hooks, sys.argv[sys.argv.index('--names') + 1] == 'on')
        return save(s, before, 'names ' + sys.argv[sys.argv.index('--names') + 1])
    if '--profile' in sys.argv:
        set_profile(hooks, sys.argv[sys.argv.index('--profile') + 1] == 'on')
        return save(s, before, 'profile ' + sys.argv[sys.argv.index('--profile') + 1])
    if '--working' in sys.argv:
        on = sys.argv[sys.argv.index('--working') + 1] == 'on'
        if on:
            try:
                os.remove(WORKING_OFF)
            except OSError:
                pass
        else:
            os.makedirs(os.path.dirname(WORKING_OFF), exist_ok=True)
            open(WORKING_OFF, 'w').close()
        set_working(hooks, on)
        return save(s, before, 'working ' + ('on' if on else 'off'))
    if remove:
        set_bypass(hooks, False)
        set_profile(hooks, False)
        set_names(hooks, False)
    word = sync_orchestrator(orchestrator_on() and not remove)
    if word:
        print(word)
    set_rules(hooks, not remove)
    set_limit(hooks, not remove)
    set_guard(hooks, orchestrator_on() and not remove)
    set_subrules(hooks, orchestrator_on() and not remove)
    set_working(hooks, not remove and not os.path.exists(WORKING_OFF))
    for event in ('UserPromptSubmit', 'PostToolUse'):
        groups = hooks.get(event, [])
        for g in groups:  # drop every copy, old paths included
            g['hooks'] = [h for h in g.get('hooks', []) if not ours(h.get('command', ''))]
        groups = [g for g in groups if g.get('hooks')]
        if not remove:
            h = {'type': 'command', 'command': COMMAND}
            h.update({'timeout': 40} if event == 'UserPromptSubmit' else {'async': True})
            groups.append({'hooks': [h]})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    save(s, before, 'removed' if remove else 'installed')


def save(s, before, what):
    """Writes the settings when they changed and prints what (or 'unchanged'); prints nothing when what
    is None. True when it wrote."""
    if not s.get('hooks'):
        s.pop('hooks', None)
    if json.dumps(s, sort_keys=True) == before:
        if what is not None:
            print('unchanged')
        return False
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    if os.path.exists(SETTINGS):
        shutil.copy2(SETTINGS, SETTINGS + time.strftime('.bak-effort-%Y%m%d-%H%M%S'))
    tmp = SETTINGS + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(s, f, indent=2)
        f.write('\n')
    os.replace(tmp, SETTINGS)
    if what is not None:
        print(what)
    return True


if __name__ == '__main__':
    main()
