#!/usr/bin/python3
"""Send an effort change to a Claude Code Remote Control session, the same
message the Claude app's effort picker sends. Signs in with the Claude Code
login saved in this Mac's Keychain.

usage: set-session-effort.py <cse_... session id> <low|medium|high|xhigh|max>
"""
import json, os, subprocess, sys, urllib.request, uuid

API = 'https://api.anthropic.com/v1/code/sessions/'


def token():
    raw = subprocess.run(['security', 'find-generic-password', '-s',
                          'Claude Code-credentials', '-w'],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(raw)['claudeAiOauth']['accessToken']


def org():
    with open(os.path.expanduser('~/.claude.json')) as f:
        return json.load(f)['oauthAccount']['organizationUuid']


def headers():
    return {'Authorization': f'Bearer {token()}',
            'Content-Type': 'application/json',
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'ccr-byoc-2025-07-29',
            'x-organization-uuid': org()}


def send(session, level):
    body = {'session_id': session, 'events': [{'payload': {
        'type': 'control_request', 'request_id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()),
        'request': {'subtype': 'apply_flag_settings',
                    'settings': {'effortLevel': level}}}}]}
    r = urllib.request.Request(API + session + '/events', data=json.dumps(body).encode(),
                               method='POST', headers=headers())
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, resp.read().decode()[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def session(session):
    """The session as the server sees it: title, status, link."""
    r = urllib.request.Request(API + session, headers=headers())
    with urllib.request.urlopen(r, timeout=15) as resp:
        d = json.load(resp)
    return d.get('response_shape', d)


def rename(session, title):
    """Set the session's name in the Claude app. Takes the cse_ or session_ id."""
    sid = 'session_' + session.split('_', 1)[1]
    r = urllib.request.Request('https://api.anthropic.com/v1/sessions/' + sid,
                               data=json.dumps({'title': title}).encode(),
                               method='PATCH', headers=headers())
    with urllib.request.urlopen(r, timeout=15) as resp:
        return resp.status


if __name__ == '__main__':
    status, text = send(sys.argv[1], sys.argv[2])
    print(status, text)
    sys.exit(0 if 200 <= status < 300 else 1)
