#!/usr/bin/python3
"""Add the effort hook to Claude Code's settings (~/.claude/settings.json), or
take it out with --remove. Run by the Sttark Effort app on every launch, so a
hook that went missing comes back. Other settings and hooks are left as they
are, and a backup is saved before any change.
"""
import json, os, shutil, sys, time

SETTINGS = os.path.expanduser('~/.claude/settings.json')
HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'effort-hook.py')
COMMAND = f'"{HOOK}"'


def ours(cmd):
    return cmd.rstrip('"').endswith('effort-hook.py')


def main():
    remove = '--remove' in sys.argv
    try:
        with open(SETTINGS) as f:
            s = json.load(f)
    except FileNotFoundError:
        s = {}
    before = json.dumps(s, sort_keys=True)
    hooks = s.setdefault('hooks', {})
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
    if not hooks:
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
    print('removed' if remove else 'installed')


if __name__ == '__main__':
    main()
