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
--status prints which are on. Other settings and hooks are left as they are, and a backup is saved
before any change.
"""
import json, os, shutil, sys, time

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
                          'limit': has(s, 'PreToolUse', is_limit)}))
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
    set_rules(hooks, not remove)
    set_limit(hooks, not remove)
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
    if not s.get('hooks'):
        s.pop('hooks', None)
    if json.dumps(s, sort_keys=True) == before:
        print('unchanged')
        return
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    if os.path.exists(SETTINGS):
        shutil.copy2(SETTINGS, SETTINGS + time.strftime('.bak-effort-%Y%m%d-%H%M%S'))
    tmp = SETTINGS + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(s, f, indent=2)
        f.write('\n')
    os.replace(tmp, SETTINGS)
    print(what)


if __name__ == '__main__':
    main()
