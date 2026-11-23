#!/usr/bin/python3
"""Tests the effort pick for subagents in Resources/hooks/effort-hook.py (on_agent), the session's list of its agents
(the `agents` entries that on_agent, SubagentStart, the Agent tool's answer and SubagentStop write), and the hook
entries install-hooks.py adds for them, on copies: a temp state folder, log and HOME. The model check, the send to the
server and the read of the server are stand-ins, so no model is called and no session is changed. Prints each case;
exits 1 if any fails.
Run: /usr/bin/python3 tools/agent-effort-test.py"""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.normpath(os.path.join(HERE, '../Resources/hooks/effort-hook.py'))
INSTALL = os.path.normpath(os.path.join(HERE, '../Resources/hooks/install-hooks.py'))
T = tempfile.mkdtemp(prefix='agent-effort-test-')
HOME, KIT, LOG = (os.path.join(T, x) for x in ('home', 'kit', 'log'))
for k in [k for k in os.environ if k.startswith('CLAUDE')]:
    del os.environ[k]
os.environ.update(HOME=HOME, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG, STTARK_EFFORT_DRY='1')
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
hand = {'v': ''}
typed = {'v': None}
eh.judge = lambda ask, system=eh.RULES: answer['v']
eh.send = lambda sid, level: (sent.append((sid, level)) or (200, 'ok', 'rid-1'))
eh.by_hand = lambda sid, why, d=None: hand['v']
eh.typed_waits = lambda sid: typed['v']
eh.time.sleep = lambda s: None
SID = 'cse_01TESTsession'
SESSION_TP = os.path.join(T, 'projects', 'f46255ef-0000.jsonl')  # the session's transcript; its agents' are beside it
SUBAGENTS = os.path.join(T, 'projects', 'f46255ef-0000', 'subagents')
os.makedirs(SUBAGENTS)
calls = {'n': 0}


def state(**kv):
    with open(eh.STATE, 'w') as f:
        json.dump(dict({'sessions': {SID: {'level': 'medium'}}}, **kv), f)


def agent(typ='Explore', effort=None, level='medium', cwd=T, desc='Find the color files', tool=None):
    calls['n'] += 1
    ti = {'description': desc, 'prompt': 'Find where the color pages live and list the files.', 'subagent_type': typ}
    if effort:
        ti['effort'] = effort
    return {'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'tool_input': ti, 'effort': {'level': level},
            'session_id': 'f46255ef-0000', 'cwd': cwd, 'transcript_path': SESSION_TP,
            'tool_use_id': tool or f'toolu_test{calls["n"]:03d}'}


def picked(out):
    return ((out or {}).get('hookSpecificOutput') or {}).get('updatedInput') or {}


def last_log():
    try:
        return open(LOG).read().strip().splitlines()[-1]
    except (OSError, IndexError):
        return ''


def rows():
    return json.load(open(eh.STATE))['sessions'][SID].get('agents') or []


def last_row():
    return (rows() or [{}])[-1]


# Every agent but a fork gets the Kit's level in its own call
state()
out = eh.on_agent(agent(), SID)
ti = picked(out)
check('an agent gets the picked level in its own call', ti.get('effort') == 'low' and ti.get('prompt', '').startswith('Find'), out)
check('the rest of the call stays as it was', ti.get('subagent_type') == 'Explore' and ti.get('description') == 'Find the color files', ti)
check('its log line names the session, type and level', 'agent  cse_01TESTsession Explore ->low' in last_log(), last_log())

out = eh.on_agent(agent(effort='xhigh'), SID)
check('an effort set in the call is replaced by the Kit\'s level', picked(out).get('effort') == 'low', out)
check('the log says which level it replaced, and where it came from',
      'agent  cse_01TESTsession Explore replaced xhigh (set in the call) with low (' in last_log()
      and last_log().endswith('low - Simple file search. | Find the color files'), last_log())
check('its entry says the Kit set it', last_row().get('level') == 'low' and last_row().get('set_by') == 'kit'
      and last_row().get('reason') == 'Simple file search.', last_row())

os.makedirs(os.path.join(T, '.claude/agents'))
open(os.path.join(T, '.claude/agents/reviewer.md'), 'w').write('---\nname: reviewer\neffort: high\n---\nReview it.\n')
out = eh.on_agent(agent(typ='reviewer'), SID)
check("an effort an agent's definition sets is replaced too", picked(out).get('effort') == 'low', out)
check('the log says it came from the definition', 'reviewer replaced high (set by its definition) with low' in last_log(), last_log())
out = eh.on_agent(agent(typ='reviewer', effort='max'), SID)
check('a call and a definition that both set one: the call\'s is the one replaced (Claude Code uses it)',
      picked(out).get('effort') == 'low' and 'replaced max (set in the call) with low' in last_log(), last_log())

answer['v'] = ('high', 'high - Needs judgment.')
out = eh.on_agent(agent(effort='high'), SID)
check('the same level as the call\'s still goes in the call', picked(out).get('effort') == 'high'
      and 'replaced high (set in the call) with high' in last_log(), (out, last_log()))

# Auto effort off and Manual: left alone, and the log says so
state(paused=True)
n = len(rows())
check('Auto effort off: the agent is left alone', eh.on_agent(agent(), SID) is None)
check('Auto effort off: the log says so', last_log().endswith('agent  cse_01TESTsession Explore left at medium - Auto effort is off | Find the color files'), last_log())
check('Auto effort off: its entry is at the session\'s level, not set by the Kit',
      len(rows()) == n + 1 and last_row().get('level') == 'medium' and last_row().get('set_by') == 'session'
      and last_row().get('reason') == 'Auto effort is off.', last_row())
state(sessions={SID: {'level': 'high', 'manual': True}})
check('a session on Manual: its agents are left alone', eh.on_agent(agent(level='high'), SID) is None)
check('Manual: the log says so', 'Explore left at high - the session is on Manual |' in last_log(), last_log())
out = eh.on_agent(agent(level='high', effort='xhigh'), SID)
check('Manual with a level in the call: the call keeps it, and the log and the entry say so',
      out is None and 'Explore left at xhigh (set in the call) - the session is on Manual' in last_log()
      and last_row().get('level') == 'xhigh' and last_row().get('set_by') == 'session', (out, last_log(), last_row()))
sent.clear()
check('Manual: a fork is left alone too, and nothing is sent', eh.on_agent(agent(typ='fork', level='high'), SID) is None
      and not sent and 'fork left at high - the session is on Manual' in last_log(), (sent, last_log()))

state()
answer['v'] = (None, eh.AT_LIMIT)
check('at the usage limit: no pick, nothing changed', eh.on_agent(agent(), SID) is None)
check('at the usage limit: its entry is at the session\'s level', last_row().get('set_by') == 'session'
      and last_row().get('level') == 'medium' and 'usage limit' in last_row().get('reason', ''), last_row())


def broken(ask, system=eh.RULES):
    raise RuntimeError('no answer')


eh.judge = broken
check('a check that fails never blocks the agent', eh.on_agent(agent(effort='high'), SID) is None)
check('a check that fails: the entry has the call\'s level, not set by the Kit',
      last_row().get('level') == 'high' and last_row().get('set_by') == 'session', last_row())
eh.judge = lambda ask, system=eh.RULES: answer['v']

# Forks: no level of their own, so the session is raised for one that needs more, and stays there
answer['v'] = ('xhigh', 'xhigh - Builds a feature end to end.')
state(sessions={SID: {'level': 'low'}})
sent.clear()
out = eh.on_agent(agent(typ='fork', level='low', desc='Build the page'), SID)
st = json.load(open(eh.STATE))['sessions'][SID]
check('a fork that needs more raises the session first', out is None and sent == [(SID, 'xhigh')], (out, sent))
check('a fork never gets an effort in its call (Claude Code ignores it there)', out is None)
check('the raise is remembered as the Kit\'s own', st.get('sent') == 'xhigh' and st.get('level') == 'xhigh', st)
check('the raise is logged with the fork', 'agent  cse_01TESTsession fork low->xhigh' in last_log(), last_log())
check('the fork\'s entry is at the raised level, set by the Kit', last_row().get('type') == 'fork'
      and last_row().get('level') == 'xhigh' and last_row().get('set_by') == 'kit', last_row())
check('the session is not set back (a fork runs at the session\'s level while it works)', sent == [(SID, 'xhigh')], sent)

out = eh.on_agent(agent(typ='fork', level='xhigh', desc='Build the second page'), SID)
check('two forks back to back: the second finds the session raised and sends nothing',
      out is None and sent == [(SID, 'xhigh')] and 'fork at xhigh' in last_log(), (sent, last_log()))
check('the second fork\'s entry: the Kit\'s pick is the session\'s level', last_row().get('level') == 'xhigh'
      and last_row().get('set_by') == 'kit', last_row())

answer['v'] = ('medium', 'medium - A short edit.')
sent.clear()
out = eh.on_agent(agent(typ='fork', level='high', desc='Small edit'), SID)
check('a fork that needs less starts at the session level; nothing is sent', out is None and not sent and 'fork at high' in last_log(),
      (sent, last_log()))
check('its entry is at the session\'s level, with what it needs', last_row().get('level') == 'high'
      and last_row().get('set_by') == 'session' and 'It needs medium' in last_row().get('reason', ''), last_row())

answer['v'] = ('xhigh', 'xhigh - Builds a feature end to end.')
typed['v'] = {'level': 'medium'}
out = eh.on_agent(agent(typ='fork', level='medium', desc='Build it'), SID)
check('a fork while a prompt the Kit typed in has no answer: not raised, and logged',
      out is None and not sent and 'not raised now:' in last_log() and last_row().get('set_by') == 'session', (sent, last_log()))
typed['v'] = None
hand['v'] = 'high'
out = eh.on_agent(agent(typ='fork', level='medium', desc='Build it'), SID)
check('a fork when the person just set the level by hand: nothing sent, its entry at that level',
      out is None and not sent and last_row().get('level') == 'high' and last_row().get('set_by') == 'session', (sent, last_row()))
hand['v'] = ''

answer['v'] = ('high', 'high - Needs judgment.')
n = len(rows())
out = eh.on_agent(agent(), None)
check('a session that is not on Remote Control still gets its agents picked', picked(out).get('effort') == 'high', out)
check('but it has no list of agents (no record in the state file)', len(rows()) == n, rows()[n:])
sent.clear()
check('and a fork there is not raised (no way to reach the session)', eh.on_agent(agent(typ='fork', level='low'), None) is None and not sent)

# The session's list of its agents
state()
eh.on_agent(agent(desc='A long description of an agent that goes on and on past the eighty characters the list keeps'), SID)
e = last_row()
check('an entry has every field, with the call\'s tool_use_id and no id or end yet',
      set(e) == {'tool_use_id', 'agent_id', 'type', 'desc', 'level', 'set_by', 'reason', 'started_at', 'done_at'}
      and e['tool_use_id'].startswith('toolu_test') and e['agent_id'] is None and e['done_at'] is None
      and isinstance(e['started_at'], float) and e['type'] == 'Explore' and e['level'] in eh.LEVELS, e)
check('an entry\'s description is at most 80 characters', len(e['desc']) == 80, e['desc'])


def subagent(event, aid, typ, stop_tp=None):
    d = {'hook_event_name': event, 'session_id': 'f46255ef-0000', 'transcript_path': SESSION_TP, 'cwd': T,
         'agent_id': aid, 'agent_type': typ}
    if event == 'SubagentStop':
        d['agent_transcript_path'] = stop_tp or os.path.join(SUBAGENTS, f'agent-{aid}.jsonl')
    return d


def meta(aid, tool):
    with open(os.path.join(SUBAGENTS, f'agent-{aid}.meta.json'), 'w') as f:
        json.dump({'agentType': 'Explore', 'description': 'x', 'toolUseId': tool}, f)


def by_tool(tool):
    return next((a for a in rows() if a.get('tool_use_id') == tool), {})


state()
answer['v'] = ('low', 'low - Simple file search.')
eh.on_agent(agent(tool='toolu_A'), SID)
eh.on_agent(agent(typ='fork', level='medium', tool='toolu_F'), SID)
eh.on_agent(agent(tool='toolu_B'), SID)
eh.on_subagent(subagent('SubagentStart', 'aaaa0000000000001', 'Explore'), SID, 'SubagentStart')
eh.on_subagent(subagent('SubagentStart', 'aaaa0000000000002', 'fork'), SID, 'SubagentStart')
check('SubagentStart: the oldest entry of the same type with no id gets the agent\'s id',
      by_tool('toolu_A').get('agent_id') == 'aaaa0000000000001' and by_tool('toolu_B').get('agent_id') is None, rows())
check('SubagentStart: a fork goes to the fork\'s entry', by_tool('toolu_F').get('agent_id') == 'aaaa0000000000002', rows())
eh.on_subagent(subagent('SubagentStart', 'aaaa0000000000003', 'explore'), SID, 'SubagentStart')
check('SubagentStart: the type matches with case ignored', by_tool('toolu_B').get('agent_id') == 'aaaa0000000000003', rows())
before = rows()
eh.on_subagent(subagent('SubagentStart', 'aaaa0000000000004', 'Plan'), SID, 'SubagentStart')
check('SubagentStart for an agent with no entry changes nothing', rows() == before, rows())

state()
eh.on_agent(agent(tool='toolu_C'), SID)
eh.on_agent(agent(tool='toolu_D'), SID)
meta('bbbb0000000000002', 'toolu_D')
eh.on_subagent(subagent('SubagentStart', 'bbbb0000000000002', 'Explore'), SID, 'SubagentStart')
check('SubagentStart: Claude Code\'s record of the agent, when it is there, names the exact entry',
      by_tool('toolu_D').get('agent_id') == 'bbbb0000000000002' and by_tool('toolu_C').get('agent_id') is None, rows())

state()
eh.on_agent(agent(tool='toolu_E'), SID)
eh.on_agent(agent(tool='toolu_G'), SID)
# the agent of toolu_G starts first, so by type and order it lands on toolu_E's entry
eh.on_subagent(subagent('SubagentStart', 'cccc0000000000002', 'Explore'), SID, 'SubagentStart')
check('(two agents of one type start out of order: the first match is wrong)', by_tool('toolu_E').get('agent_id') == 'cccc0000000000002', rows())
eh.on_agent_answer({'hook_event_name': 'PostToolUse', 'tool_name': 'Agent', 'tool_use_id': 'toolu_G',
                    'tool_response': {'isAsync': True, 'status': 'async_launched', 'agentId': 'cccc0000000000002'}}, SID)
check('the Agent tool\'s answer moves the id to the entry of its own call',
      by_tool('toolu_G').get('agent_id') == 'cccc0000000000002' and by_tool('toolu_E').get('agent_id') is None, rows())
eh.on_subagent(subagent('SubagentStart', 'cccc0000000000001', 'Explore'), SID, 'SubagentStart')
check('then the other agent\'s start finds its own entry', by_tool('toolu_E').get('agent_id') == 'cccc0000000000001', rows())

eh.on_subagent(subagent('SubagentStop', 'cccc0000000000002', 'Explore'), SID, 'SubagentStop')
check('SubagentStop: the entry with the agent\'s id gets the time it ended',
      isinstance(by_tool('toolu_G').get('done_at'), float) and by_tool('toolu_E').get('done_at') is None, rows())
done = by_tool('toolu_G')['done_at']
eh.on_subagent(subagent('SubagentStop', 'cccc0000000000002', 'Explore'), SID, 'SubagentStop')
check('a second SubagentStop keeps the first end', by_tool('toolu_G').get('done_at') == done, rows())

state()
eh.on_agent(agent(tool='toolu_H'), SID)
eh.on_agent(agent(tool='toolu_I'), SID)
meta('dddd0000000000002', 'toolu_I')
eh.on_subagent(subagent('SubagentStop', 'dddd0000000000002', 'Explore'), SID, 'SubagentStop')
check('SubagentStop with no start seen: Claude Code\'s record names the entry, which gets the id and the end',
      by_tool('toolu_I').get('agent_id') == 'dddd0000000000002' and by_tool('toolu_I').get('done_at')
      and by_tool('toolu_H').get('done_at') is None, rows())

now = time.time()
old_done = {'tool_use_id': 'toolu_old', 'agent_id': 'a1', 'type': 'Explore', 'desc': 'old', 'level': 'low',
            'set_by': 'kit', 'reason': '', 'started_at': now - 9 * 86400, 'done_at': now - 8 * 86400}
old_open = dict(old_done, tool_use_id='toolu_stale', agent_id='a2', done_at=None)
recent_done = dict(old_done, tool_use_id='toolu_recent', agent_id='a3', started_at=now - 6 * 86400, done_at=now - 6 * 86400)
many = [dict(old_done, tool_use_id=f'toolu_n{i:03d}', agent_id=f'n{i}', started_at=now - 3600 + i, done_at=None) for i in range(60)]
state(sessions={SID: {'level': 'medium', 'agents': [old_done, old_open, recent_done]}})
eh.on_agent(agent(tool='toolu_new'), SID)
kept = [a['tool_use_id'] for a in rows()]
check('an agent that ended more than 7 days ago leaves the list', 'toolu_old' not in kept, kept)
check('an agent that started more than 7 days ago with no end leaves it too', 'toolu_stale' not in kept, kept)
check('an agent that ended 6 days ago stays, and the new one is last', kept == ['toolu_recent', 'toolu_new'], kept)
state(sessions={SID: {'level': 'medium', 'agents': many}})
eh.on_agent(agent(tool='toolu_last'), SID)
kept = [a['tool_use_id'] for a in rows()]
check('the list keeps the last 50 entries', len(kept) == 50 and kept[-1] == 'toolu_last' and kept[0] == 'toolu_n011', (len(kept), kept[:2]))
state(sessions={SID: {'level': 'medium'}, 'cse_01TESTidle': {'level': 'high', 'agents': [old_done]},
                'cse_01TESTbusy': {'level': 'high', 'agents': [old_done, recent_done]}})
eh.on_agent(agent(tool='toolu_other'), SID)
others = json.load(open(eh.STATE))['sessions']
check('a new entry in one session also takes old entries out of the other sessions\' lists',
      'agents' not in others['cse_01TESTidle']
      and [a['tool_use_id'] for a in others['cse_01TESTbusy']['agents']] == ['toolu_recent'], others)

# The hook itself: SubagentStart and SubagentStop through main(), on the test folder
state()
eh.on_agent(agent(tool='toolu_main'), SID)
env = dict(os.environ, CLAUDE_CODE_BRIDGE_SESSION_ID=SID)
hook = lambda d: subprocess.run([sys.executable, HOOK], input=json.dumps(d), capture_output=True, text=True, env=env)
r1 = hook(subagent('SubagentStart', 'eeee0000000000001', 'Explore'))
check('the hook takes SubagentStart: the entry gets the agent\'s id, and nothing is printed',
      by_tool('toolu_main').get('agent_id') == 'eeee0000000000001' and r1.returncode == 0 and not r1.stdout.strip(), (r1, rows()))
r2 = hook(subagent('SubagentStop', 'eeee0000000000001', 'Explore'))
check('the hook takes SubagentStop: the entry gets its end', by_tool('toolu_main').get('done_at') and r2.returncode == 0, (r2, rows()))
n = len(open(LOG).read().splitlines())
r3 = subprocess.run([sys.executable, HOOK], input=json.dumps(subagent('SubagentStart', 'eeee0000000000002', 'Explore')),
                    capture_output=True, text=True, env=dict(os.environ))
check('SubagentStart in a session that is not on Remote Control: nothing written, nothing logged',
      r3.returncode == 0 and len(open(LOG).read().splitlines()) == n, r3)

# The hook entries: PreToolUse for Agent|Task, waited on; SubagentStart and SubagentStop in the background
settings = os.path.join(HOME, '.claude/settings.json')
json.dump({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'other'}]}],
                     'SubagentStop': [{'hooks': [{'type': 'command', 'command': 'other-stop'}]}]}}, open(settings, 'w'))
run = lambda *a: subprocess.run([sys.executable, INSTALL, *a], capture_output=True, text=True, env=os.environ).stdout.strip()
run()
s = json.load(open(settings))
mine = lambda s, ev: [g for g in s['hooks'].get(ev, []) if any(h['command'].endswith('effort-hook.py"') for h in g['hooks'])]
pre = mine(s, 'PreToolUse')
check('install adds one PreToolUse entry for Agent|Task', len(pre) == 1 and pre[0].get('matcher') == 'Agent|Task', pre)
check('the entry is waited on, with a time limit', pre and pre[0]['hooks'][0].get('timeout') == 40 and not pre[0]['hooks'][0].get('async'), pre)
check("another hook's PreToolUse entry stays", any(g.get('matcher') == 'Bash' for g in s['hooks']['PreToolUse']))
for ev in ('SubagentStart', 'SubagentStop'):
    g = mine(s, ev)
    check(f'install adds one {ev} entry, in the background, for every agent type',
          len(g) == 1 and g[0]['hooks'][0].get('async') is True and 'matcher' not in g[0], g)
check("another hook's SubagentStop entry stays", any(h['command'] == 'other-stop' for g in s['hooks']['SubagentStop'] for h in g['hooks']))
run()
s2 = json.load(open(settings))
check('a second install adds no copy', all(len(mine(s2, ev)) == 1 for ev in ('PreToolUse', 'SubagentStart', 'SubagentStop')),
      {ev: mine(s2, ev) for ev in ('PreToolUse', 'SubagentStart', 'SubagentStop')})
status = json.loads(run('--status'))
check('--status shows them', status.get('agent_effort') is True and status.get('agent_list') is True, status)
run('--remove')
s3 = json.load(open(settings))
check('--remove takes them out', not any('effort-hook.py' in h['command'] for ev in ('PreToolUse', 'SubagentStart', 'SubagentStop')
                                         for g in s3.get('hooks', {}).get(ev, []) for h in g['hooks']), s3.get('hooks'))
check("--remove leaves another hook's SubagentStop entry", any(h['command'] == 'other-stop'
                                                               for g in s3.get('hooks', {}).get('SubagentStop', []) for h in g['hooks']), s3.get('hooks'))

shutil.rmtree(T)
print('all passed' if not failed else f'{len(failed)} failed')
sys.exit(1 if failed else 0)
