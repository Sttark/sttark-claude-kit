"""Step 2: an answer key from Opus at max effort, which reads each whole turn in hindsight and names the level the
work truly needed; then each candidate model judges the same prompts the way the hook does, with only what it
sees at prompt time. Edit the model list below for new models. Reads cases.json, writes results.json.
Uses your Claude Code login; 100 Opus calls plus 100 per model."""
import importlib.util, os, json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
spec = importlib.util.spec_from_file_location('h', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Resources', 'hooks', 'effort-hook.py'))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
cases = json.load(open('cases.json'))
KEY = """You grade effort levels for a Claude Code agent, in hindsight. You see a user's request, the conversation \
before it, and the full record of how the agent's work on it actually went. Decide the effort level that work truly \
needed to be done right the first time, no more. Higher effort means more thinking and care, at more time and cost.

low: quick answers, lookups, confirmations, small talk, trivial edits.
medium: routine work with a clear path.
high: multi-step work needing judgment: code across a few files, debugging with a findable cause, careful writing.
xhigh: hard or open-ended work: unknown causes, building something end to end, many systems, costly mistakes.
max: the hardest work, where a wrong answer is costly and hard to undo, or the problem resisted earlier attempts.

Judge by what the work really demanded, not by how long the agent took (it may have been slow or wasteful). \
Answer on one line: the level, then " - " and a reason of under 15 words."""
def run(model, effort, system, ask, timeout):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'
    t = time.time()
    try:
        r = subprocess.run([h.CLAUDE, '-p', '--model', model, '--effort', effort, '--no-session-persistence', '--strict-mcp-config',
                            '--tools', '', '--settings', '{"disableAllHooks":true}', '--system-prompt', system, ask],
                           capture_output=True, text=True, timeout=timeout, env=env, cwd='/tmp')
        a = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ''
    except Exception as e:
        a = 'ERR ' + repr(e)
    m = re.match(r'\W*(low|medium|high|xhigh|max)\b', a, re.I)
    return (m.group(1).lower() if m else None), a, round(time.time() - t, 1)
def key(c):
    ask = (f'Conversation before the request:\n{c["context"] or "(none)"}\n\nRequest:\n{c["prompt"]}\n\n'
           f'How the work went ({c["calls"]} tool calls, {c["errors"]} failed, {c["minutes"]} minutes):\n{c["work"]}\n\n'
           f'Agent\'s final reply:\n{c["final"]}\n\nEffort level the work needed?')
    return run('claude-opus-5-5', 'max', KEY, ask, 600)
def judge(c, model):
    ask = (f'Recent conversation:\n{c["context"] or "(none)"}\n\nCurrent effort: unknown\n\n'
           f'Latest user message:\n{c["prompt"]}\n\nEffort level?')
    return run(model, 'low', h.RULES, ask, 60)
out = {}
with ThreadPoolExecutor(10) as ex:
    futs = {('key', c['id']): ex.submit(key, c) for c in cases}
    for m in ['claude-haiku-5-5', 'claude-haiku-4-5', 'claude-sonnet-5-5', 'claude-sonnet-5']:
        for c in cases: futs[(m, c['id'])] = ex.submit(judge, c, m)
    for k, f in futs.items():
        out.setdefault(str(k[1]), {})[k[0]] = f.result()
        json.dump(out, open('results.json', 'w'))
print('done', len(out))
