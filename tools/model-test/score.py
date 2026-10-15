"""Step 3: score each model against the answer key and draw the chart. Reads results.json, prints a table,
writes chart.html and chart.png (the PNG needs Google Chrome)."""
import json, os, statistics, subprocess, time
L = ['low', 'medium', 'high', 'xhigh', 'max']
r = json.load(open('results.json'))
models = sorted({k for v in r.values() for k in v} - {'key'})
NAMES = lambda m: m.replace('claude-', '').replace('-', ' ', 1).replace('-', '.').title()
rows = ''
for m in models:
    b = dict.fromkeys(['l2', 'l1', 'ok', 'h1', 'h2'], 0); n = 0; secs = []
    for v in r.values():
        if m not in v or not v['key'][0]: continue
        secs.append(v[m][2]); p = v[m][0]
        if not p: continue
        n += 1; d = L.index(p) - L.index(v['key'][0])
        b['l2' if d <= -2 else 'l1' if d == -1 else 'ok' if d == 0 else 'h1' if d == 1 else 'h2'] += 1
    pct = {k: b[k] / n for k in b}
    print(f'{NAMES(m):12} right {pct["ok"]:4.0%}  within one {1 - pct["l2"] - pct["h2"]:4.0%}  too low {pct["l1"] + pct["l2"]:4.0%} '
          f'(2+ {pct["l2"]:3.0%})  too high {pct["h1"] + pct["h2"]:4.0%}  typical {statistics.median(secs):.1f} s')
    seg = ''.join(f'<div class="s {k}" style="width:{pct[k] * 100:.1f}%">{round(pct[k] * 100) if pct[k] >= 0.06 else ""}</div>' for k in b)
    rows += f'<div class="row"><div class="name">{NAMES(m)}</div><div class="bar">{seg}</div><div class="t">{statistics.median(secs):.1f} s</div></div>'
html = f'''<html><head><style>
body{{margin:0;padding:24px;background:#fff;font:15px "Helvetica Neue";color:#000;width:760px}}
h1{{font-size:19px;font-weight:600;margin:0 0 4px}} p{{color:#5b6570;margin:0 0 16px;font-size:14px}}
.row{{display:flex;align-items:center;gap:12px;margin:8px 0}} .name{{width:90px;font-weight:600}} .t{{width:60px;color:#5b6570;text-align:right}}
.bar{{flex:1;display:flex;height:30px;border-radius:6px;overflow:hidden}}
.s{{display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600}}
.l2{{background:#df3d33;color:#fff}} .l1{{background:#fdecea;color:#b42318}} .ok{{background:#e6f4ea;color:#007a2a}} .h1{{background:#e8f1f8;color:#035f93}} .h2{{background:#0473b1;color:#fff}}
.legend{{display:flex;gap:16px;margin-top:14px;font-size:13px;color:#5b6570}} .legend span::before{{content:"";display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px;background:var(--c)}}
.hd{{display:flex;gap:12px;font-size:13px;color:#5b6570}} .hd .sp{{flex:1}}
</style></head><body>
<h1>Which model picks effort best</h1><p>{len(r)} past prompts. Answer key: Opus at max, judging each with hindsight of how the work went. % of prompts.</p>
<div class="hd"><div style="width:90px"></div><div class="sp"></div><div style="width:60px;text-align:right">Typical time</div></div>
{rows}
<div class="legend"><span style="--c:#df3d33">2+ levels too low</span><span style="--c:#fdecea">1 too low</span><span style="--c:#e6f4ea">Right</span><span style="--c:#e8f1f8">1 too high</span><span style="--c:#0473b1">2+ too high</span></div>
</body></html>'''
open('chart.html', 'w').write(html)
chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
if os.path.exists(chrome):
    here = os.path.abspath('.')
    c = subprocess.Popen([chrome, '--headless=new', '--user-data-dir=' + os.path.join(here, '.chrome'), '--hide-scrollbars',
                          '--window-size=808,%d' % (180 + 46 * len(models)), '--screenshot=' + os.path.join(here, 'chart.png'),
                          'file://' + os.path.join(here, 'chart.html')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5); c.kill()
    print('wrote chart.png')
