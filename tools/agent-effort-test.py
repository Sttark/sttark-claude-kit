#!/usr/bin/python3
"""Tests the effort pick for subagents in Resources/hooks/effort-hook.py (on_agent) and its PreToolUse entry in
install-hooks.py, on copies: a temp state folder, log and HOME. The model check, the send to the server and the
read of the server are stand-ins, so no model is called and no session is changed. Prints each case; exits 1 if
any fails.
Run: /usr/bin/python3 tools/agent-effort-test.py"""
import importlib.util, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.normpath(os.path.join(HERE, '../Resources/hooks/effort-hook.py'))
INSTALL = os.path.normpath(os.path.join(HERE, '../Resources/hooks/install-hooks.py'))
T = tempfile.mkdtemp(prefix='agent-effort-test-')
HOME, KIT, LOG = (os.path.join(T, x) for x in ('home', 'kit', 'log'))
for k in [k for k in os.environ if k.startswith('CLAUDE')]:
    del os.environ[k]
os.environ.update(HOME=HOME, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG)
os.makedirs(KIT)
os.makedirs(os.path.join(HOME, '.claude'))
spec = importlib.util.spec_from_file_location('eh', HOOK)
eh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eh)

failed = []


def check(name, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + name + ('' if ok else f'  -- {detail}'))
    if not ok:
        failed.append(name)


answer = {'v': ('low', 'low - Simple file search.')}
sent = []
eh.judge = lambda ask, system=eh.RULES: answer['v']
eh.send = lambda sid, level: (sent.append((sid, level)) or (200, 'ok', 'rid-1'))
eh.by_hand = lambda sid, why, d=None: ''
eh.time.sleep = lambda s: None
SID = 'cse_01TESTsession'


def state(**kv):
    with open(eh.STATE, 'w') as f:
        json.dump(dict({'sessions': {SID: {'level': 'medium'}}}, **kv), f)


def agent(typ='Explore', effort=None, level='medium', cwd=T, desc='Find the color files'):
    ti = {'description': desc, 'prompt': 'Find where the color pages live and list the files.', 'subagent_type': typ}
    if effort:
        ti['effort'] = effort
    return {'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'tool_input': ti, 'effort': {'level': level},
            'session_id': 'f46255ef-0000', 'cwd': cwd}


def last_log():
    try:
        return open(LOG).read().strip().splitlines()[-1]
    except (OSError, IndexError):
        return ''


state()
out = eh.on_agent(agent(), SID)
ti = ((out or {}).get('hookSpecificOutput') or {}).get('updatedInput') or {}
check('an agent gets the picked level in its own call', ti.get('effort') == 'low' and ti.get('prompt', '').startswith('Find'), out)
check('the rest of the call stays as it was', ti.get('subagent_type') == 'Explore' and ti.get('description') == 'Find the color files', ti)
check('its log line names the session, type and level', 'agent  cse_01TESTsession Explore ->low' in last_log(), last_log())

out = eh.on_agent(agent(effort='xhigh'), SID)
check('an effort set in the call is kept', out is None and 'kept xhigh - set in the call' in last_log(), (out, last_log()))

os.makedirs(os.path.join(T, '.claude/agents'))
open(os.path.join(T, '.claude/agents/reviewer.md'), 'w').write('---\nname: reviewer\neffort: high\n---\nReview it.\n')
out = eh.on_agent(agent(typ='reviewer'), SID)
check("an effort an agent's definition sets is kept", out is None and 'kept high - set by its definition' in last_log(), (out, last_log()))

state(paused=True)
check('Auto effort off: the agent is left alone', eh.on_agent(agent(), SID) is None)
state(sessions={SID: {'level': 'high', 'manual': True}})
check('a session on Manual: its agents are left alone', eh.on_agent(agent(), SID) is None)

state()
answer['v'] = (None, eh.AT_LIMIT)
check('at the usage limit: no pick, nothing changed', eh.on_agent(agent(), SID) is None)

answer['v'] = ('xhigh', 'xhigh - Builds a feature end to end.')
sent.clear()
out = eh.on_agent(agent(typ='fork', level='low', desc='Build the page'), SID)
st = json.load(open(eh.STATE))['sessions'][SID]
check('a fork that needs more raises the session first', out is None and sent == [(SID, 'xhigh')], (out, sent))
check('the raise is remembered as the Kit\'s own', st.get('sent') == 'xhigh' and st.get('level') == 'xhigh', st)
check('the raise is logged with the fork', 'agent  cse_01TESTsession fork low->xhigh' in last_log(), last_log())

answer['v'] = ('medium', 'medium - A short edit.')
sent.clear()
out = eh.on_agent(agent(typ='fork', level='high', desc='Small edit'), SID)
check('a fork that needs less starts at the session level; nothing is sent', out is None and not sent and 'fork at high' in last_log(),
      (sent, last_log()))
check('a fork never gets an effort in its call (Claude Code ignores it there)', out is None)

answer['v'] = ('high', 'high - Needs judgment.')
out = eh.on_agent(agent(), None)
check('a session that is not on Remote Control still gets its agents picked', ((out or {}).get('hookSpecificOutput') or {}).get('updatedInput', {}).get('effort') == 'high', out)
sent.clear()
check('but a fork there is not raised (no way to reach the session)', eh.on_agent(agent(typ='fork', level='low'), None) is None and not sent)

# The hook entry: PreToolUse for Agent|Task, waited on (not async), and status/remove see it.
settings = os.path.join(HOME, '.claude/settings.json')
json.dump({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'other'}]}]}}, open(settings, 'w'))
run = lambda *a: subprocess.run([sys.executable, INSTALL, *a], capture_output=True, text=True, env=os.environ).stdout.strip()
run()
s = json.load(open(settings))
pre = [g for g in s['hooks']['PreToolUse'] if any(h['command'].endswith('effort-hook.py"') for h in g['hooks'])]
check('install adds one PreToolUse entry for Agent|Task', len(pre) == 1 and pre[0].get('matcher') == 'Agent|Task', pre)
check('the entry is waited on, with a time limit', pre and pre[0]['hooks'][0].get('timeout') == 40 and not pre[0]['hooks'][0].get('async'), pre)
check("another hook's PreToolUse entry stays", any(g.get('matcher') == 'Bash' for g in s['hooks']['PreToolUse']))
run()
s2 = json.load(open(settings))
check('a second install adds no copy', len([g for g in s2['hooks']['PreToolUse'] if any('effort-hook.py' in h['command'] for h in g['hooks'])]) == 1)
check('--status shows it', json.loads(run('--status')).get('agent_effort') is True)
run('--remove')
s3 = json.load(open(settings))
check('--remove takes it out', not any('effort-hook.py' in h['command'] for g in s3.get('hooks', {}).get('PreToolUse', []) for h in g['hooks']))

shutil.rmtree(T)
print('all passed' if not failed else f'{len(failed)} failed')
sys.exit(1 if failed else 0)
