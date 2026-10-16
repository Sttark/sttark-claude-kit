#!/usr/bin/python3
"""Add the effort hook to Claude Code's settings (~/.claude/settings.json), or
take it out with --remove. Run by the Sttark Effort app on every launch, so a
hook that went missing comes back.

--names on|off adds or removes the session naming hook ("Name sessions
automatically"), --profile on|off the profile instructions hook (the "Sync Claude
profile instructions" switch), and --bypass on|off the bypass hook (the "Bypass permissions for
server sessions" switch) and leaves the effort hook alone. --status prints which are
on. Other settings and hooks are left as they are, and a backup is saved
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
                          'names': has(s, 'UserPromptSubmit', is_names)}))
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
    if remove:
        set_bypass(hooks, False)
        set_profile(hooks, False)
        set_names(hooks, False)
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
