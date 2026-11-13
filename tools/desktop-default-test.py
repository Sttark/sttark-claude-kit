#!/usr/bin/python3
"""Tests desktop-default.py's decision (updated, first_place) on made-up stored lists, with no Local Storage.
Run from the repo root: /usr/bin/python3 tools/desktop-default-test.py"""
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('dd', os.path.join('Resources', 'hooks', 'desktop-default.py'))
dd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dd)
fails = 0


def check(name, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + name)
    fails += 0 if ok else 1


E1, E2 = 'env_server', 'env_other'
bridge = lambda i, e, org=None: dict(id=i, target={'kind': 'bridge', 'environmentId': e}, at=1, pickedAt=1, starts=2, **({'org': org} if org else {}))
local = dict(id='L', target={'kind': 'local', 'cwd': '/x'}, at=1, starts=1)

s = {'startedFrom': ['A'], 'startedPlaces': [bridge('A', E1)]}
check('server first already: no write', dd.updated(s, E1) is None)

s = {'startedFrom': ['L', 'A', 'quick-start:local'], 'startedPlaces': [local, bridge('A', E1, 'org1')]}
n = dd.updated(s, E1)
check('This computer first: the server goes first', n['startedFrom'][:2] == ['A', 'L'] and dd.first_place(n)['environmentId'] == E1)
check('the same place is reused, not doubled', [p['id'] for p in n['startedPlaces']].count('A') == 1 and n['startedPlaces'][0]['org'] == 'org1')
check('quick start stays in the list', 'quick-start:local' in n['startedFrom'])

s = {'startedFrom': ['quick-start:local'], 'startedPlaces': [bridge('B', E2, 'org9')]}
n = dd.updated(s, E1)
p = n['startedPlaces'][0]
check('no place for the server: a new one, first', p['target'] == {'kind': 'bridge', 'environmentId': E1} and n['startedFrom'][0] == p['id'])
check('a new place takes the one org the list has', p.get('org') == 'org9')
check('the other place stays', any(q['id'] == 'B' for q in n['startedPlaces']))

n = dd.updated({}, E1)
check('an empty list gets the server', dd.first_place(n).get('environmentId') == E1)

s = {'startedFrom': [str(i) for i in range(8)], 'startedPlaces': [bridge(str(i), 'env_%d' % i) for i in range(5)]}
n = dd.updated(s, E1)
check('the app\'s limits hold (5 places, 8 starts)', len(n['startedPlaces']) == 5 and len(n['startedFrom']) == 8)

check('Latin-1 text keeps the 1 byte form', dd.encode('{"a":1}')[:1] == b'\x01' and dd.decode(dd.encode('{"a":1}')) == '{"a":1}')
check('other text keeps the UTF-16 form', dd.encode('{"a":"✓"}')[:1] == b'\x00' and dd.decode(dd.encode('{"a":"✓"}')) == '{"a":"✓"}')
print('all passed' if not fails else f'{fails} failed')
sys.exit(1 if fails else 0)
