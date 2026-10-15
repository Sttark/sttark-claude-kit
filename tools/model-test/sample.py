"""Step 1 of the model test: pick 100 past Claude Code turns from this Mac's session history (the last 10 days),
20 from each size band by tool calls (0, 1-5, 6-20, 21-60, 61+). Each keeps what the hook sees at prompt time
(the prompt and the conversation before it) and how the work actually went. Writes cases.json here.
Run from an empty folder: python3 /path/to/tools/model-test/sample.py"""
import importlib.util, os, json, glob, random, re, time
spec = importlib.util.spec_from_file_location('h', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Resources', 'hooks', 'effort-hook.py'))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
cut = time.time() - 10 * 86400
files = [f for f in glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')) if os.path.getmtime(f) > cut]
cases = []
for f in files:
    try: entries = [json.loads(l) for l in open(f)]
    except Exception: continue
    prompts = []
    for i, e in enumerate(entries):
        if e.get('type') == 'user' and not e.get('isMeta'):
            t = h.text_of((e.get('message') or {}).get('content')).strip()
            if t and not t.startswith('<') and len(t) > 1:
                prompts.append((i, t))
    for k, (i, t) in enumerate(prompts):
        end = prompts[k + 1][0] if k + 1 < len(prompts) else len(entries)
        turn = entries[i:end]
        calls = errors = 0; work = []; final = ''
        for e in turn[1:]:
            c = (e.get('message') or {}).get('content')
            if not isinstance(c, list): continue
            for b in c:
                if not isinstance(b, dict): continue
                if b.get('type') == 'tool_use':
                    calls += 1; work.append(f'{calls}. {b.get("name")} ' + json.dumps(b.get('input', {}), ensure_ascii=False)[:200])
                elif b.get('type') == 'tool_result' and b.get('is_error'):
                    errors += 1; work.append('   (that step failed)')
                elif b.get('type') == 'text' and e.get('type') == 'assistant':
                    final = b['text']; work.append('Agent: ' + re.sub(r'\s+', ' ', b['text'])[:300])
        if calls == 0 and not final: continue
        ts = [e.get('timestamp') for e in turn if e.get('timestamp')]
        mins = 0
        if len(ts) > 1:
            from datetime import datetime
            p = lambda s: datetime.fromisoformat(s.replace('Z', '+00:00'))
            mins = (p(ts[-1]) - p(ts[0])).total_seconds() / 60
        # prompt-time context, exactly what the hook sees: transcript up to (not including) this prompt
        tmp = '/tmp/_ctx.jsonl'
        with open(tmp, 'w') as o:
            for e in entries[:i]: o.write(json.dumps(e) + '\n')
        ctx = h.recent(tmp, t)
        wtext = '\n'.join(work)
        if len(wtext) > 7000: wtext = wtext[:2000] + '\n[...]\n' + wtext[-5000:]
        cases.append({'file': os.path.basename(f), 'prompt': t[:4000], 'context': ctx, 'calls': calls, 'errors': errors,
                      'minutes': round(mins, 1), 'work': wtext, 'final': final[:2500]})
random.seed(7)
buckets = [(0, 0), (1, 5), (6, 20), (21, 60), (61, 10**6)]
out = []
for lo, hi in buckets:
    b = [c for c in cases if lo <= c['calls'] <= hi]
    out += random.sample(b, min(20, len(b)))
for n, c in enumerate(out): c['id'] = n
json.dump(out, open('cases.json', 'w'))
print(len(files), 'transcripts,', len(cases), 'turns; sampled', len(out), [sum(lo <= c['calls'] <= hi for c in out) for lo, hi in buckets])
