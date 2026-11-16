#!/usr/bin/python3
"""Usage by session: how much of the person's Claude Code use each session took, from the records on this Mac.

Reads each session's record, ~/.claude/projects/<folder>/<id>.jsonl, and its agents' records,
<id>/subagents/agent-*.jsonl, and writes usage/by-session.json in the Kit's folder for the window's Usage page and
the phone's Usage tab. A page open is fast because the reading is incremental: usage/scan-cache.json keeps, for each
record file, its size, time and how far it was read, and what it held, so a later scan reads only the lines added
since (a file that got shorter or was replaced is read again from the start).

Each reply counts once (Claude Code writes a reply once for each of its parts, and a resumed or forked session's
record copies earlier replies: the copy in the session's own record wins, then the older file). Its tokens (input,
output, 5-minute and 1-hour cache writes, cache reads, web searches) count at its model's API price (PRICES), because
the usage limit also counts a larger model as more use; a share is a session's part of the person's use in a period,
never a percent of the limit, which Anthropic gives only as a total.

Who a record belongs to:
  - a session with a Remote Control link (the record's newest bridge-session line, or the Kit's own record of it);
    its agents' records, and the records of runs started in its scratchpad folder, count as its agents;
  - a session with no link, by its own id ("On this Mac only");
  - the Kit's own runs (its wait checks and rules refresh), and runs in temporary folders, one row each.
Names come from the Claude app's list, the Kit's state and its archived list, then the record's own title lines;
never from a prompt or a reply. Nothing is sent anywhere: the Kit sends the phone only names, ids and numbers.

  usage-scan.py              scan, write by-session.json, print one line of what it did
  usage-scan.py --if-older N scan only when by-session.json is more than N seconds old
  usage-scan.py --prices     list each model in the kept data, its tokens and whether PRICES has it; exit 1 when
                             one with tokens has no price (tools/usage-scan-test.py runs it)
STTARK_KIT_DIR, STTARK_KIT_LOG and STTARK_CLAUDE_DIR point it at test folders and a test log.
"""
import calendar, fcntl, json, os, re, sys, time

KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')
CLAUDE_DIR = os.environ.get('STTARK_CLAUDE_DIR') or os.path.expanduser('~/.claude')
PROJECTS = os.path.join(CLAUDE_DIR, 'projects')
DIR = os.path.join(KIT, 'usage')   # a folder of its own: the app's watch on the Kit's folder does not see these writes
OUT = os.path.join(DIR, 'by-session.json')
CACHE = os.path.join(DIR, 'scan-cache.json')
LOCK = os.path.join(DIR, 'scan.lock')
KEEP_DAYS = 45          # replies older than this are not kept; Custom periods start at the oldest day kept
VERSION = 1             # of the cache: a new one reads every file again

# API prices, dollars per million tokens: input, output, 5-minute cache write, 1-hour cache write, cache read.
# The one table of prices. A model in the records with no row here counts at its family's newest price and is
# listed under "unpriced" in by-session.json; tools/usage-scan-test.py fails while one is in recent data.
PRICES = {
    'claude-fable-5-2':  (8.00, 40.00, 10.00, 16.00, 0.20),
    'claude-mythos-5-2': (8.00, 40.00, 10.00, 16.00, 0.20),
    'claude-fable-5-1':  (10.00, 50.00, 12.50, 20.00, 0.25),
    'claude-mythos-5-1': (10.00, 50.00, 12.50, 20.00, 0.25),
    'claude-fable-5':    (10.00, 50.00, 12.50, 20.00, 1.00),
    'claude-mythos-5':   (10.00, 50.00, 12.50, 20.00, 1.00),
    'claude-opus-5-5':   (4.00, 20.00, 5.00, 8.00, 0.20),
    'claude-opus-5':     (5.00, 25.00, 6.25, 10.00, 0.50),
    'claude-opus-4-8':   (5.00, 25.00, 6.25, 10.00, 0.50),
    'claude-opus-4-7':   (5.00, 25.00, 6.25, 10.00, 0.50),
    'claude-opus-4-6':   (5.00, 25.00, 6.25, 10.00, 0.50),
    'claude-sonnet-5-5': (2.00, 10.00, 2.50, 4.00, 0.10),
    'claude-sonnet-5':   (2.00, 10.00, 2.50, 4.00, 0.20),
    'claude-sonnet-4-6': (3.00, 15.00, 3.75, 6.00, 0.30),
    'claude-haiku-5-5':  (0.10, 0.50, 0.125, 0.20, 0.01),
    'claude-haiku-4-5':  (1.00, 5.00, 1.25, 2.00, 0.10),
}
# A prompt over this many tokens costs more on these models.
LONG = {'claude-haiku-5-5': (100000, (0.50, 2.50, 0.625, 1.00, 0.05))}
FAST = 2.0              # fast mode costs twice the standard price
WEB_SEARCH = 0.01       # dollars for each web search
FAMILY = [('fable', 'claude-fable-5-2'), ('mythos', 'claude-mythos-5-2'), ('opus', 'claude-opus-5-5'),
          ('sonnet', 'claude-sonnet-5-5'), ('haiku', 'claude-haiku-5-5')]

UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
SCRATCH = re.compile('-(' + UUID + ')-scratchpad(?:-|$)')   # a folder in a session's own scratchpad
TEMP = re.compile(r'^-(private-|var-folders-|tmp-|tmp$)')       # /private/tmp, /private/var/folders, /tmp
KIT_FOLDER = '-Library-Application-Support-SttarkClaudeKit'      # the Kit's own runs (wait checks, the rules refresh)
DATED = re.compile(r'-\d{8}$')
RUNS = 5                # more unnamed sessions with no link than this in one folder make one row


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'usage  ' + line + '\n')
    except OSError:
        pass


def model_id(m):
    """claude-opus-5-5 from claude-opus-5-5[1m], us.anthropic.claude-opus-5-5, claude-haiku-4-5-20251001."""
    m = (m or '').strip().lower()
    m = m.split('[', 1)[0]
    if '.claude-' in m:
        m = 'claude-' + m.split('.claude-', 1)[1]
    m = re.sub(r'-v\d+(:\d+)?$', '', m)
    return DATED.sub('', m)


def price_of(model):
    """(prices, priced): the model's row, else its family's newest row."""
    if model in PRICES:
        return PRICES[model], True
    for word, stand_in in FAMILY:
        if word in model:
            return PRICES[stand_in], False
    return PRICES['claude-opus-5-5'], False


def model_name(model):
    """Opus 5.5 from claude-opus-5-5."""
    m = re.match(r'claude-([a-z]+)-(\d+(?:-\d+)*)$', model)
    if not m:
        return model or 'Unknown model'
    return m.group(1).capitalize() + ' ' + m.group(2).replace('-', '.')


def value(row):
    """Dollars at API prices for one reply: row = [ts, model, in, out, c5m, c1h, cr, searches, fast, side]."""
    p, _ = price_of(row[1])
    long = LONG.get(row[1])
    if long and row[2] + row[4] + row[5] + row[6] > long[0]:
        p = long[1]
    usd = (row[2] * p[0] + row[3] * p[1] + row[4] * p[2] + row[5] * p[3] + row[6] * p[4]) / 1e6
    return usd * (FAST if row[8] else 1) + row[7] * WEB_SEARCH


def iso(ts):
    """Unix time of '2026-11-16T14:43:10.123Z'; None when it is not one."""
    try:
        return calendar.timegm((int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), int(ts[11:13]), int(ts[14:16]), int(ts[17:19]), 0, 0, 0))
    except (TypeError, ValueError, IndexError):
        return None


def num(x):
    return x if isinstance(x, int) and x > 0 else 0


# ---------- reading one record ----------

def read_lines(path, entry, start):
    """Reads `path` from byte `start` to its last whole line into `entry`; returns the bytes read. A line still being
    written waits for the next scan. Reads 4 MB at a time, so a large record never fills the memory."""
    used, carry = 0, b''
    with open(path, 'rb') as f:
        f.seek(start)
        while True:
            block = f.read(4 << 20)
            if not block:
                break
            block = carry + block
            end = block.rfind(b'\n') + 1
            if end <= 0:
                carry = block
                continue
            for line in block[:end].split(b'\n'):
                if line:
                    read_line(line, entry)
            used += end
            carry = block[end:]
    return used


def read_line(line, entry):
    """One line of a record: a reply's usage, the session's link, or a title."""
    if b'"usage"' in line and b'"assistant"' in line:
        try:
            d = json.loads(line)
        except ValueError:
            return
        if d.get('type') != 'assistant':
            return
        m = d.get('message') or {}
        u = m.get('usage')
        mid = m.get('id')
        ts = iso(d.get('timestamp'))
        if not isinstance(u, dict) or not mid or ts is None or ts < time.time() - KEEP_DAYS * 86400:
            return
        model = model_id(m.get('model'))
        if not model or model.startswith('<'):
            return   # Claude Code's own notes, such as <synthetic>, use no tokens
        cc = u.get('cache_creation') if isinstance(u.get('cache_creation'), dict) else {}
        c1h, c5m = num(cc.get('ephemeral_1h_input_tokens')), num(cc.get('ephemeral_5m_input_tokens'))
        written = num(u.get('cache_creation_input_tokens'))
        if c1h + c5m < written:   # no split given: the rest counts as 5-minute writes
            c5m += written - c1h - c5m
        tools = u.get('server_tool_use') if isinstance(u.get('server_tool_use'), dict) else {}
        row = [ts, model, num(u.get('input_tokens')), num(u.get('output_tokens')), c5m, c1h,
               num(u.get('cache_read_input_tokens')), num(tools.get('web_search_requests')),
               1 if u.get('speed') == 'fast' else 0, 1 if d.get('isSidechain') else 0]
        old = entry['m'].get(mid)
        if old is None or row[3] >= old[3]:   # each part repeats the reply's usage; the last has its whole output
            entry['m'][mid] = row
        if not entry['agent'] and isinstance(d.get('cwd'), str) and d['cwd']:
            entry['folder'] = os.path.basename(d['cwd'].rstrip('/'))[:80]   # its own name only: never the path
    elif len(line) < 8192 and (b'"bridge-session"' in line or b'"custom-title"' in line or b'"ai-title"' in line
                               or b'"agent-name"' in line):
        try:
            d = json.loads(line)
        except ValueError:
            return
        t = d.get('type')
        if t == 'bridge-session' and isinstance(d.get('bridgeSessionId'), str):
            entry['cse'] = d['bridgeSessionId']
        elif t == 'custom-title' and isinstance(d.get('customTitle'), str) and d['customTitle'].strip():
            entry['title'] = d['customTitle'].strip()[:200]
        elif t == 'ai-title' and isinstance(d.get('aiTitle'), str) and d['aiTitle'].strip():
            entry['ai'] = d['aiTitle'].strip()[:200]
        elif t == 'agent-name' and isinstance(d.get('agentName'), str) and d['agentName'].strip():
            entry['aname'] = d['agentName'].strip()[:200]


def head_of(path):
    try:
        with open(path, 'rb') as f:
            return f.read(64).hex()
    except OSError:
        return ''


def record_files():
    """(path, project folder, session id, agent name or None) for each record changed in the kept days."""
    out = []
    cut = time.time() - KEEP_DAYS * 86400
    try:
        projects = os.listdir(PROJECTS)
    except OSError:
        return out
    for proj in projects:
        pdir = os.path.join(PROJECTS, proj)
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for n in names:
            p = os.path.join(pdir, n)
            if n.endswith('.jsonl'):
                out.append((p, proj, n[:-6], None))
            elif re.match(UUID + '$', n):
                sub = os.path.join(p, 'subagents')
                try:
                    agents = os.listdir(sub)
                except OSError:
                    continue
                for a in agents:
                    if a.endswith('.jsonl'):
                        out.append((os.path.join(sub, a), proj, n, a[:-6]))
    kept = []
    for x in out:
        try:
            st = os.stat(x[0])
        except OSError:
            continue
        if st.st_mtime >= cut:
            kept.append(x + (st,))
    return kept


def scan(cache):
    """Brings the cache up to date with the records on disk; returns (files, files read, bytes read)."""
    files = cache.setdefault('files', {})
    seen, read, nbytes = set(), 0, 0
    for path, proj, sid, agent, st in record_files():
        seen.add(path)
        e = files.get(path)
        if e and e['size'] == st.st_size and e['mtime'] == st.st_mtime and e['ino'] == st.st_ino:
            continue
        start = 0
        if e and e['ino'] == st.st_ino and st.st_size >= e['off'] and e['off'] > 0 and e['head'] == head_of(path):
            start = e['off']   # the same file, longer: read only what was added
        else:
            e = {'proj': proj, 'sid': sid, 'agent': agent, 'birth': getattr(st, 'st_birthtime', st.st_mtime),
                 'head': '', 'off': 0, 'm': {}}
            files[path] = e
        try:
            got = read_lines(path, e, start)
        except OSError:
            continue
        e.update(size=st.st_size, mtime=st.st_mtime, ino=st.st_ino, off=start + got)
        if not e['head']:
            e['head'] = head_of(path)
        read += 1
        nbytes += got
    for gone in set(files) - seen:
        files.pop(gone)
    return len(seen), read, nbytes


# ---------- whose use it is ----------

def kit_names():
    """(names by link, link by session id, links in the Claude app's list) from the Kit's state and archived list.
    The Claude app's own title wins: it is the name the person sees."""
    def load(name):
        try:
            with open(os.path.join(KIT, name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    s, arch = load('state.json'), load('archived.json')
    names, link_of = {}, {}
    stem = lambda p: os.path.splitext(os.path.basename(p))[0] if isinstance(p, str) and p else None

    def note(cse, title, transcript):
        if not isinstance(cse, str) or not cse:
            return
        if isinstance(title, str) and title.strip():
            names[cse] = title.strip()
        sid = stem(transcript)
        if sid:
            link_of.setdefault(sid, cse)

    for x in arch.get('items') or []:
        note(x.get('cse'), x.get('title'), x.get('transcript'))
    for w in (s.get('waits') or {}).values() if isinstance(s.get('waits'), dict) else []:
        note(w.get('cse'), w.get('title'), w.get('transcript'))
    for cse, x in ((s.get('keep') or {}).get('alone') or {}).items():
        note(cse, x.get('title'), x.get('transcript'))
    for cse, x in (s.get('sessions') or {}).items():
        note(cse, x.get('title'), x.get('transcript'))
    for x in (s.get('app_list') or {}).get('sessions') or []:
        note(x.get('id'), x.get('title'), None)
    return names, link_of


def group(e, link_of, main_of, runs):
    """(key, kind, part) of one record: part is 'own' or 'agents'. kind is session (it has a Remote Control link),
    local (no link), runs (many unnamed sessions of one folder with no link, one row), kit or temp."""
    proj, sid = e['proj'], e['sid']
    part = 'agents' if e['agent'] else 'own'
    main = main_of.get(sid) if e['agent'] else e
    cse = (main or {}).get('cse') or link_of.get(sid)
    if cse:
        return 'cse:' + cse, 'session', part
    m = SCRATCH.search(proj)
    if m and m.group(1) != sid:
        # a run started in another session's scratchpad folder: one of that session's agents
        parent = m.group(1)
        pcse = (main_of.get(parent) or {}).get('cse') or link_of.get(parent)
        return ('cse:' + pcse, 'session', 'agents') if pcse else ('sid:' + parent, 'local', 'agents')
    if KIT_FOLDER in proj:
        return 'kit', 'kit', part
    if TEMP.match(proj):
        return 'temp', 'temp', part
    if sid in runs:
        return 'runs:' + runs[sid], 'runs', part
    return 'sid:' + sid, 'local', part


def titled(e):
    return e.get('title') or e.get('ai') or e.get('aname')


def build(cache):
    """by-session.json from the cache."""
    files = cache['files']
    names, link_of = kit_names()
    main_of = {e['sid']: e for e in files.values() if not e['agent']}
    # each reply once: the copy in a session's own record, then the oldest file
    owner = {}
    for path, e in files.items():
        rank = (1 if e['agent'] else 0, e['birth'], path)
        for mid in e['m']:
            o = owner.get(mid)
            if o is None or rank < o[0]:
                owner[mid] = (rank, path)
    # sessions with no link and no name, many in one folder (another app's runs, say): one row for the folder
    unnamed = {}
    for e in files.values():
        if not e['agent'] and not e.get('cse') and not link_of.get(e['sid']) and not titled(e) and e['m'] \
                and not SCRATCH.search(e['proj']) and KIT_FOLDER not in e['proj'] and not TEMP.match(e['proj']):
            unnamed.setdefault(e.get('folder') or e['proj'].rsplit('-', 1)[-1] or 'a folder', []).append(e['sid'])
    runs = {sid: folder for folder, sids in unnamed.items() if len(sids) > RUNS for sid in sids}
    keys, sessions = {}, []
    days, models = {}, {}
    rows, agents, unpriced, last, titles = {}, {}, {}, {}, {}
    cut = time.time() - KEEP_DAYS * 86400
    for path, e in files.items():
        key, kind, part = group(e, link_of, main_of, runs)
        if not e['agent'] and titled(e) and (key not in titles or e['mtime'] > titles[key][0]):
            titles[key] = (e['mtime'], titled(e))
        s, first = None, None
        for mid, r in e['m'].items():
            if owner[mid][1] != path or r[0] < cut:
                continue
            if s is None:
                if key not in keys:
                    keys[key] = len(sessions)
                    sessions.append({'key': key, 'kind': kind})
                s = keys[key]
            d = days.setdefault(time.strftime('%Y-%m-%d', time.localtime(r[0])), len(days))
            m = models.setdefault(r[1], len(models))
            if not price_of(r[1])[1]:
                unpriced[r[1]] = unpriced.get(r[1], 0) + sum(r[2:7])
            usd, tok = value(r), sum(r[2:7])
            a = rows.setdefault((s, d, m), [0.0, 0.0, 0, 0])
            if part == 'agents' or r[9]:
                a[1] += usd
                a[3] += tok
            else:
                a[0] += usd
                a[2] += tok
            last[s] = max(last.get(s, 0), r[0])
            first = r[0] if first is None else min(first, r[0])
        if first is not None and part == 'agents':
            d = days[time.strftime('%Y-%m-%d', time.localtime(first))]
            agents[(s, d)] = agents.get((s, d), 0) + 1
    # the days, from the oldest one with use to today, in this Mac's time zone
    today = time.strftime('%Y-%m-%d')
    span = []
    if days:
        t = calendar.timegm(time.strptime(min(days), '%Y-%m-%d'))
        while len(span) <= KEEP_DAYS + 2:
            day = time.strftime('%Y-%m-%d', time.gmtime(t))
            span.append(day)
            if day >= today:
                break
            t += 86400
    at = {day: i for i, day in enumerate(span)}
    remap = {old: at.get(day, -1) for day, old in days.items()}
    for x in sessions:
        k = x['key']
        x['last'] = round(last.get(keys[k], 0))
        x['cse'] = k[4:] if k.startswith('cse:') else None
        own = (titles.get(k) or (0, ''))[1]
        if x['cse']:
            x['title'] = names.get(x['cse']) or own or 'Session ' + x['cse'][-6:]
        elif k.startswith('sid:'):
            x['title'] = own or 'Unnamed session'
        elif k.startswith('runs:'):
            x['title'] = 'Runs with no name in ' + k[5:]
        elif k == 'kit':
            x['title'] = 'Sttark Claude Kit checks'
        else:
            x['title'] = 'Runs in temporary folders'
    return {
        'v': 1,
        'at': time.time(),
        'keep_days': KEEP_DAYS,
        'days': span,
        'models': [{'id': m, 'name': model_name(m), 'priced': price_of(m)[1]} for m in sorted(models, key=models.get)],
        'sessions': sessions,
        # [session, day, model, own dollars, agents' dollars, own tokens, agents' tokens]
        'rows': [[s, remap[d], m, round(v[0], 6), round(v[1], 6), v[2], v[3]] for (s, d, m), v in sorted(rows.items()) if remap[d] >= 0],
        # [session, day, agents started that day]
        'agents': [[s, remap[d], n] for (s, d), n in sorted(agents.items()) if remap[d] >= 0],
        'unpriced': unpriced,
    }


def write_json(path, data, compact=False):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, separators=(',', ':') if compact else None)
    os.replace(tmp, path)


def load_cache():
    try:
        with open(CACHE) as f:
            c = json.load(f)
        if c.get('v') == VERSION and c.get('keep') == KEEP_DAYS:
            return c
    except (OSError, ValueError):
        pass
    return {'v': VERSION, 'keep': KEEP_DAYS, 'files': {}}


def run():
    t0 = time.time()
    os.makedirs(DIR, exist_ok=True)
    with open(LOCK, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)   # one scan at a time; a second caller then finds a fresh result
        cache = load_cache()
        first = not cache['files']
        n, read, nbytes = scan(cache)
        out = build(cache)
        out['scan'] = {'files': n, 'read': read, 'bytes': nbytes, 'seconds': round(time.time() - t0, 2)}
        told = cache.setdefault('told', {})
        for m in sorted(out['unpriced']):
            if told.get(m) != time.strftime('%F'):   # once a day for each model
                log("no price for %s in usage-scan.py's PRICES: it counts at its family's price" % m)
                told[m] = time.strftime('%F')
                read += 1
        if read or not os.path.exists(CACHE):
            write_json(CACHE, cache, compact=True)
        write_json(OUT, out, compact=True)
    if first:
        log('first scan: %d records, %.0f MB, %.1f s' % (n, nbytes / 1e6, time.time() - t0))
    print('%d records, %d read (%d bytes), %d sessions, %.2f s' % (n, out['scan']['read'], nbytes, len(out['sessions']), time.time() - t0))
    return out


def prices():
    """Each model in the kept data, its tokens, and whether PRICES has it. Exit 1 when one with tokens has none."""
    out = run()
    tok = {}
    for r in out['rows']:
        m = out['models'][r[2]]
        tok[m['id']] = tok.get(m['id'], 0) + r[5] + r[6]
    missing = [m['id'] for m in out['models'] if not m['priced'] and tok.get(m['id'], 0) > 0]
    for m in out['models']:
        print('%-28s %16d tokens  %s' % (m['id'], tok.get(m['id'], 0), 'priced' if m['priced'] else 'NO PRICE'))
    if missing:
        print('no price for: ' + ', '.join(missing))
        sys.exit(1)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['--prices']:
        prices()
    elif a[:1] == ['--if-older']:
        try:
            with open(OUT) as f:
                at = json.load(f).get('at', 0)
        except (OSError, ValueError):
            at = 0
        if time.time() - at > float(a[1] if len(a) > 1 else 60):
            run()
    else:
        run()
