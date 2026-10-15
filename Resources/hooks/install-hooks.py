#!/usr/bin/python3
"""Add the effort hook to Claude Code's settings (~/.claude/settings.json), or
take it out with --remove. Run by the Sttark Effort app on every launch, so a
hook that went missing comes back.

--bypass on|off adds or removes the bypass hook (the "Skip approvals in phone
sessions" switch) and leaves the effort hook alone. --status prints which are
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


def main():
    s = load()
    if '--status' in sys.argv:
        print(json.dumps({'effort': has(s, 'UserPromptSubmit', ours),
                          'bypass': has(s, 'PermissionRequest', is_bypass)}))
        return
    remove = '--remove' in sys.argv
    before = json.dumps(s, sort_keys=True)
    hooks = s.setdefault('hooks', {})
    if '--bypass' in sys.argv:
        set_bypass(hooks, sys.argv[sys.argv.index('--bypass') + 1] == 'on')
        return save(s, before, 'bypass ' + sys.argv[sys.argv.index('--bypass') + 1])
    if remove:
        set_bypass(hooks, False)
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
