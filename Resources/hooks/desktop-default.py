#!/usr/bin/python3
"""New Code sessions in the Claude desktop app start on this Mac's Remote Control server.

A new Code session in the Claude desktop app starts where the person started the last one. The app keeps that in
its Local Storage (the claude.ai page's "persisted.ccd-session-presets.<account>" entry): "startedPlaces", the
places sessions were started in, and "startedFrom", which of them to use first. The app has no setting for it.
This script puts the Kit's server (Remote Control > its folder) first in that list, the way the app records a
session the person started there, so the next new session starts on the server with nothing to choose.

    desktop-default.py apply --folder <server folder> --ldb <kit-ldb>   put the server first, when it isn't
    desktop-default.py status --folder <server folder> --ldb <kit-ldb>  print what the list starts with

The server's environment is the account's Remote Control environment for that folder (GET /v1/environments).
Local Storage is a LevelDB folder that the app locks while it runs, so this writes only while the Claude app is
closed (kit-ldb exits 3 on the lock, and the app is checked first): the app runs "apply" when the Claude app quits,
on launch and every 10 minutes. It writes nothing when the server is already first, and keeps one copy of the folder
from before its last write (desktop-default-backup in the Kit's folder).

Prints one line: "set: ...", "unchanged: ..." or "waiting: ...". STTARK_DESKTOP_LS (the Local Storage folder),
STTARK_KIT_DIR and STTARK_DESKTOP_ENV (an environment id, in place of the API) point it at test copies.
"""
import binascii, importlib.util, json, os, shutil, subprocess, sys, time, uuid

HERE = os.path.dirname(os.path.realpath(__file__))
LS = os.environ.get('STTARK_DESKTOP_LS') or os.path.expanduser('~/Library/Application Support/Claude/Local Storage/leveldb')
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
BACKUP = os.path.join(KIT, 'desktop-default-backup')
RECORD = os.path.join(KIT, 'desktop-default.json')
PREFIX = b'_https://claude.ai\x00\x01persisted.ccd-session-presets.'
CLAUDE_APP = '/Applications/Claude.app/Contents/MacOS/Claude'
MAX_PLACES, MAX_FROM = 5, 8   # the app keeps at most this many (startedPlaces, startedFrom)


def args():
    a, out = sys.argv[2:], {}
    while a:
        k = a.pop(0)
        if k.startswith('--') and a:
            out[k[2:]] = a.pop(0)
    return out


def claude_running():
    if os.environ.get('STTARK_DESKTOP_LS'):
        return False   # a test copy: the app doesn't hold it
    r = subprocess.run(['/usr/bin/pgrep', '-f', CLAUDE_APP], capture_output=True)
    return r.returncode == 0


def ldb(tool, *a):
    r = subprocess.run([tool, *a], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def environment(folder):
    """The id and name of the account's Remote Control environment for this folder, or (None, why)."""
    if os.environ.get('STTARK_DESKTOP_ENV'):
        return os.environ['STTARK_DESKTOP_ENV'], os.path.basename(folder)
    spec = importlib.util.spec_from_file_location('effort', os.path.join(HERE, 'effort-hook.py'))
    effort = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(effort)
    try:
        envs = effort.api('GET', 'https://api.anthropic.com/v1/environments', beta='environments-2025-11-01').get('data') or []
    except Exception as e:
        return None, f'could not read the environments ({e})'
    want = os.path.realpath(folder)
    mine = [e for e in envs if (e.get('config') or {}).get('type') == 'bridge' and not e.get('archived_at')
            and e.get('state', 'active') == 'active'
            and os.path.realpath((e.get('config') or {}).get('directory') or '/nonexistent') == want]
    if not mine:
        return None, 'the server has no environment yet'
    e = max(mine, key=lambda e: e.get('updated_at') or '')
    return e['id'], os.path.basename(want)


def decode(v):
    """Chromium's Local Storage value: 1 byte for the encoding (1 Latin-1, 0 UTF-16), then the text."""
    return v[1:].decode('latin-1') if v[:1] == b'\x01' else v[1:].decode('utf-16-le')


def encode(s):
    try:
        return b'\x01' + s.encode('latin-1')
    except UnicodeEncodeError:
        return b'\x00' + s.encode('utf-16-le')


def account_key(tool):
    """The machine entry's key: persisted.ccd-session-presets.<account>, with no org after the account."""
    rc, out, err = ldb(tool, 'keys', LS, PREFIX.hex())
    if rc == 3:
        return None, 'waiting: the Claude app has its Local Storage open'
    if rc != 0:
        return None, f'unchanged: could not read the Local Storage ({err or rc})'
    keys = [binascii.unhexlify(k) for k in out.split() if k]
    machine = [k for k in keys if b'.' not in k[len(PREFIX):]]
    if not machine:
        return None, 'unchanged: the Claude app has not opened Code on this Mac yet'
    if len(machine) > 1:
        try:
            with open(os.path.expanduser('~/.claude.json')) as f:
                acct = ((json.load(f).get('oauthAccount') or {}).get('accountUuid') or '').encode()
        except (OSError, ValueError):
            acct = b''
        machine = [k for k in machine if k.endswith(acct)] if acct else []
        if len(machine) != 1:
            return None, 'unchanged: more than one account in the Claude app, and none matches Claude Code'
    return machine[0], None


def first_place(state):
    places = {p.get('id'): p for p in state.get('startedPlaces') or [] if isinstance(p, dict)}
    for i in state.get('startedFrom') or []:
        if i in places:
            return places[i].get('target') or {}
        if i == 'quick-start:local':
            return {'kind': 'local'}
    return {}


def updated(state, env):
    """The state with the server first, or None when it is first already."""
    t = first_place(state)
    if t.get('kind') == 'bridge' and t.get('environmentId') == env:
        return None
    now = int(time.time() * 1000)
    places = [p for p in state.get('startedPlaces') or [] if isinstance(p, dict)]
    old = next((p for p in places if (p.get('target') or {}).get('kind') == 'bridge'
                and p['target'].get('environmentId') == env), None)
    orgs = {p.get('org') for p in places if p.get('org')}
    place = dict(old) if old else {'id': str(uuid.uuid4()), 'target': {'kind': 'bridge', 'environmentId': env}}
    if not old and len(orgs) == 1:
        place['org'] = orgs.pop()   # the app records the org for a Remote Control place; with none, any org reads it
    place.update(at=now, pickedAt=now, starts=int(place.get('starts') or 0) + (0 if old else 1))
    state = dict(state)
    state['startedPlaces'] = ([place] + [p for p in places if p.get('id') != place['id']])[:MAX_PLACES]
    state['startedFrom'] = ([place['id']] + [i for i in state.get('startedFrom') or [] if i != place['id']])[:MAX_FROM]
    return state


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    a = args()
    folder, tool = a.get('folder'), a.get('ldb')
    if not folder or not tool or not os.path.exists(tool):
        print('unchanged: needs --folder and --ldb')
        return
    if not os.path.isdir(LS):
        print('unchanged: no Claude desktop app Local Storage on this Mac')
        return
    if claude_running():
        print('waiting: the Claude app is open')
        return
    key, why = account_key(tool)
    if key is None:
        print(why)
        return
    rc, out, err = ldb(tool, 'get', LS, key.hex())
    if rc == 3:
        print('waiting: the Claude app has its Local Storage open')
        return
    try:
        whole = json.loads(decode(binascii.unhexlify(out))) if rc == 0 else {'state': {}, 'version': 4}
    except ValueError:
        print('unchanged: the stored list does not read as JSON')
        return
    state = whole.get('state') if isinstance(whole.get('state'), dict) else {}
    if cmd == 'status':
        print(json.dumps({'first': first_place(state)}))
        return
    env, name = environment(folder)
    if env is None:
        print('waiting: ' + name)
        return
    new = updated(state, env)
    if new is None:
        print(f'unchanged: new sessions start on Remote Control > {name} already')
        return
    shutil.rmtree(BACKUP, ignore_errors=True)
    shutil.copytree(LS, BACKUP, ignore=shutil.ignore_patterns('LOCK'))
    whole = dict(whole, state=new)
    rc, _, err = ldb(tool, 'put', LS, key.hex(), encode(json.dumps(whole, separators=(',', ':'))).hex())
    if rc == 3:
        print('waiting: the Claude app has its Local Storage open')
        return
    if rc != 0:
        print(f'unchanged: the write failed ({err or rc})')
        return
    try:
        with open(RECORD, 'w') as f:
            json.dump({'environment': env, 'name': name, 'at': int(time.time())}, f)
    except OSError:
        pass
    print(f'set: new Code sessions in the Claude app start on Remote Control > {name}')


if __name__ == '__main__':
    main()
