#!/usr/bin/python3
"""Two settings of the Claude desktop app that Sttark Claude Kit sets, in the app's own file
(~/Library/Application Support/Claude/claude_desktop_config.json, "preferences"):

  ccAutoArchiveOnPrClose: false            a session stays in the list when its pull request closes, so the list
                                           works as an inbox
  bypassPermissionsGateByAccount[<id>]     lets sessions on "This computer" use Bypass permissions; <id> is the
                                           Claude Code login's account (oauthAccount.accountUuid in ~/.claude.json)

    desktop-prefs.py apply [--bypass]      set each one that is missing; --bypass also the bypass gate
    desktop-prefs.py bypass-off            take out the bypass gate, only if the Kit set it and it still says true
    desktop-prefs.py status                print what is set

A key is set only when it is missing: a value that is there, from the person or the app, is never changed. The app
keeps the file in memory and writes it again when one of its own settings changes, so it can drop a key the Kit
wrote. The app runs "apply" every 10 minutes, so a key the app dropped comes back, while a value the person changed
in the app stays. The file is written to a temporary file and moved in place, so the app never reads half a file,
and a backup is kept. What the Kit set is in desktop-prefs.json in the Kit's folder. STTARK_DESKTOP_CONFIG and
STTARK_KIT_DIR point it at test copies.
"""
import json, os, shutil, sys, time

CONFIG = os.environ.get('STTARK_DESKTOP_CONFIG') or os.path.expanduser(
    '~/Library/Application Support/Claude/claude_desktop_config.json')
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
RECORD = os.path.join(KIT, 'desktop-prefs.json')


def account():
    try:
        with open(os.path.expanduser('~/.claude.json')) as f:
            return (json.load(f).get('oauthAccount') or {}).get('accountUuid') or ''
    except (OSError, ValueError):
        return ''


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, data, backup=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if backup and os.path.exists(path):
        shutil.copy2(path, path + '.bak-kit')
    tmp = path + '.kit-tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    os.replace(tmp, path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    try:
        c = load(CONFIG, None)
    except ValueError:
        print('unchanged: the file does not read as JSON now')   # the app may be writing it; try again later
        return
    if c is None:
        if cmd == 'status':
            print('{}')
        else:
            print('unchanged: no Claude desktop app settings file')
        return
    p = c.setdefault('preferences', {})
    rec = load(RECORD, {})
    acct = account()
    changed = []
    if cmd == 'status':
        print(json.dumps({'autoArchiveOnPrClose': p.get('ccAutoArchiveOnPrClose'),
                          'bypassGate': (p.get('bypassPermissionsGateByAccount') or {}).get(acct)}))
        return
    if cmd == 'apply':
        if 'ccAutoArchiveOnPrClose' not in p:
            p['ccAutoArchiveOnPrClose'] = False
            changed.append('ccAutoArchiveOnPrClose')
        if '--bypass' in sys.argv and acct:
            gate = p.setdefault('bypassPermissionsGateByAccount', {})
            if acct not in gate:
                gate[acct] = True
                changed.append('bypassPermissionsGateByAccount')
    elif cmd == 'bypass-off':
        gate = p.get('bypassPermissionsGateByAccount') or {}
        if rec.get('bypassPermissionsGateByAccount') == acct and gate.get(acct) is True:
            del gate[acct]
            changed.append('-bypassPermissionsGateByAccount')
    if not changed:
        print('unchanged')
        return
    save(CONFIG, c, backup=True)
    for k in changed:
        if k.startswith('-'):
            rec.pop(k[1:], None)
        else:
            rec[k] = acct if k == 'bypassPermissionsGateByAccount' else time.time()
    save(RECORD, rec)
    print(('removed ' if changed[0].startswith('-') else 'set ') + ', '.join(k.lstrip('-') for k in changed))


if __name__ == '__main__':
    main()
