"""The glance card: what the glasses show first for a session, so it reads in a second, on the move, by someone who
is not a strong reader. A status word, at most 3 short lines with the key fact or number first, and what the person
must do ("you"). When the newest reply ends with a status table (Ask | Status | Need from you, a status mark in each
row), the card is that table: one short line per ask, the asks that need the person first.

Haiku writes the short words, through Claude Code (`claude -p`, as the Kit's own checks call it: hooks off, no
tools, no saved conversation), once per reply: the result is kept by the reply's hash, here and on disk. Until it
comes, and when the call fails or the account is at its usage limit, the card holds the reply's first sentence (or
the table's own cells). Nothing in a card is from anywhere but the reply: a line with a number the reply does not
have is dropped.
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import threading
import time

import detail

HOME = os.path.expanduser('~')
STABLE = os.path.join(HOME, '.local/share/claude/stable/claude')  # the Kit's fixed copy, when its server is on
CLAUDE = STABLE if os.access(STABLE, os.X_OK) else os.path.join(HOME, '.local/bin/claude')
MODEL = 'haiku'
TIMEOUT = 45
MAX_REPLY = 6000  # characters of a reply sent to the model; longer ones keep their start and end
LINE_MAX = 52     # characters of a card line (the app wraps it on the lens)
YOU_MAX = 40
OPTION_MAX = 18
WORKERS = 2
REFETCH_S = 15    # a session's events are read again at most this often for its card
RETRY_S = 600     # a card that holds only the first sentence asks Haiku again after this long
KEEP = 400        # cards kept on disk

STATUS_WORD = {'needs_you': 'NEEDS YOU', 'working': 'WORKING', 'waiting': 'WAITING', 'idle': 'DONE'}
WORDS = ('NEEDS YOU', 'WORKING', 'WAITING', 'DONE')
NOTHING = 'nothing now'

# -- the status table -------------------------------------------------------------------------------------------------

_MARKS = (
    ('needs', ('🔴', '❗', '‼', '⚠', '🟥', '🛑', '🚨')),
    ('working', ('🔄', '⏳', '⌛', '🟡', '🟠', '🕒', '🔁', '⏸', '🟨')),
    ('done', ('✅', '✔', '☑', '🟢', '🟩')),
    ('dropped', ('⚪', '❌', '✖', '➖', '⛔', '🚫')),
)
_STATE_WORDS = (
    ('needs', ('needs you', 'need you', 'your turn', 'blocked on you', 'needs your')),
    ('working', ('in progress', 'waiting', 'working', 'running', 'pending', 'on hold', 'blocked')),
    ('done', ('done', 'sent', 'finished', 'complete', 'fixed', 'merged')),
    ('dropped', ('dropped', 'cancelled', 'canceled', 'skipped', 'not needed')),
)
ORDER = {'needs': 0, 'working': 1, 'other': 2, 'done': 3, 'dropped': 4}
_NEED_HEAD = re.compile(r'need|you|action|next|to do|todo|your', re.I)


def _mark(cell):
    """(state, the cell without its mark) when the cell starts with a status mark, else (None, cell)."""
    s = cell.strip()
    for state, marks in _MARKS:
        for m in marks:
            if s.startswith(m):
                return state, s[len(m):].lstrip('️').strip(' ,:-')
    return None, s


def _state_of(cell):
    state, rest = _mark(cell)
    if state:
        return state, rest
    low = cell.strip().lower()
    for st, words in _STATE_WORDS:
        if any(low.startswith(w) for w in words):
            return st, cell.strip()
    return None, cell.strip()


def _tables(md):
    """Every Markdown table in `md`: (headers, rows), cells as plain text."""
    lines = (md or '').replace('\r\n', '\n').split('\n')
    out, i, in_code = [], 0, False
    while i < len(lines):
        if detail._FENCE.match(lines[i]):
            in_code = not in_code
        elif not in_code and detail._table_start(lines, i):
            heads = [detail._cell_text(c) for c in detail._cells(lines[i])]
            rows, i = [], i + 2
            while i < len(lines) and lines[i].strip() and '|' in lines[i] and not detail._FENCE.match(lines[i]):
                rows.append([detail._cell_text(c) for c in detail._cells(lines[i])])
                i += 1
            if rows:
                out.append((heads, rows))
            continue
        i += 1
    return out


def status_table(md):
    """The reply's last status table as rows {ask, state, status, need, notes}, or None. A status table has a
    column named Status (or State), or a column whose cells start with status marks (✅ 🔄 🔴 ⚪ and the like)."""
    for heads, rows in reversed(_tables(md)):
        n = max([len(heads)] + [len(r) for r in rows])
        heads = heads + [''] * (n - len(heads))
        rows = [r + [''] * (n - len(r)) for r in rows]
        filled = lambda j: [r[j] for r in rows if not detail._nothing(r[j])]  # noqa: E731
        status = next((j for j in range(n) if heads[j].strip().lower() in ('status', 'state')), None)
        if status is None:
            status = next((j for j in range(n) if filled(j) and
                           sum(1 for c in filled(j) if _mark(c)[0]) * 2 > len(filled(j))), None)
        if status is None:
            continue
        rest = [j for j in range(n) if j != status]
        if not rest:
            continue
        name = rest[0]
        if len(rest) > 1 and heads[name] in ('', '#', 'No', 'No.') and filled(name) and \
                all(detail._NUMBER.match(c) for c in filled(name)):
            name = rest[1]
        others = [j for j in rest if j != name and not (heads[j] in ('', '#', 'No', 'No.') and j < name)]
        need = next((j for j in others if _NEED_HEAD.search(heads[j] or '')), None)
        out = []
        for r in rows:
            ask = _mark(r[name])[1]
            if not ask:
                continue
            state, said = _state_of(r[status])
            need_text = '' if need is None or detail._nothing(r[need]) else _mark(r[need])[1]
            if state is None and need_text:
                state = 'needs'
            notes = '; '.join(f'{heads[j]}: {r[j]}' if heads[j] else r[j] for j in others
                              if j != need and not detail._nothing(r[j]))
            out.append({'ask': ask, 'state': state or 'other', 'status': said, 'need': need_text, 'notes': notes})
        if out:
            return out
    return None


# -- words that fit -------------------------------------------------------------------------------------------------

def _clip(s, n):
    """At most n characters, cut at a word."""
    s = re.sub(r'\s+', ' ', (s or '').replace('**', '').replace('`', '')).strip().strip('"')
    if len(s) <= n:
        return s
    cut = s[:n - 2].rsplit(' ', 1)[0] if ' ' in s[:n - 2] else s[:n - 2]
    return cut.rstrip(' ,;:.-+') + '...'


def _words(s, n):
    return ' '.join((s or '').split()[:n]).rstrip(' ,;:.-')


_NUM = re.compile(r'\d[\d,.:/]*\d|\d')


def _digits(s):
    return {m.replace(',', '') for m in _NUM.findall(s or '')}


def numbers_ok(line, source):
    """Every number in `line` is in `source` (commas aside): Haiku may shorten, never change or add a number."""
    src = (source or '').replace(',', '')
    return all(d in src for d in _digits(line))


def first_sentence(text):
    t = re.sub(r'\s+', ' ', text or '').strip()
    m = re.search(r'(?<=[.!?])\s|\s-\s', t)
    return t[:m.start()].strip() if m else t


# -- the card -----------------------------------------------------------------------------------------------------------

def _options(pending, short=None):
    opts = (pending or {}).get('options') or []
    use_short = isinstance(short, list) and len(short) == len(opts) and all(isinstance(x, str) and x.strip()
                                                                          for x in short)
    return [{'id': o['id'], 'label': _clip(short[i], OPTION_MAX) if use_short else _clip(o.get('label') or '', 60)}
            for i, o in enumerate(opts)]


def _subject(ask):
    """A row's subject without its tail: "Laminate quote from New Star Labels" is "Laminate quote"."""
    m = re.search(r'\s(?:from|for|to|with|on|at|in|of|about)\s|\s\(|[,;:]', ask)
    head = ask[:m.start()] if m and len(ask[:m.start()].split()) >= 2 else ask
    return _words(head, 4)


def table_line(row, ask=None, what=None):
    """One status-table row as a card line: "! Job 4490 proof: pick a day" for an ask that needs the person."""
    ask = _clip(ask or _subject(row['ask']), 26)
    if not what:
        if row['state'] == 'needs':
            what = _clip(row['need'] or row['status'] or 'needs you', 30)
        elif row['state'] in ('done', 'dropped'):
            what = row['state']
        else:
            what = _clip(row['status'] or row['need'] or row['notes'] or 'in progress', 30)
    line = _clip(f'{ask}: {what}', LINE_MAX)
    return ('! ' if row['state'] == 'needs' else '') + line


def from_table(rows, pending, short=None):
    """A card from a status table: one line per row, the rows that need the person first. `short`: Haiku's
    [{ask, what}], one per row, in order."""
    use = isinstance(short, list) and len(short) == len(rows)
    items = []
    for i, r in enumerate(rows):
        ask = what = None
        if use and isinstance(short[i], dict):
            src = ' '.join([r['ask'], r['status'], r['need'], r['notes']])
            ask, what = str(short[i].get('ask') or ''), str(short[i].get('what') or '')
            if not ask or not what or not numbers_ok(ask + ' ' + what, src):
                ask = what = None
        items.append((ORDER.get(r['state'], 2), i, table_line(r, ask, what), r['state']))
    items.sort()
    needs = sum(1 for it in items if it[3] == 'needs')
    word = 'NEEDS YOU' if needs else 'WAITING' if any(it[3] == 'working' for it in items) else 'DONE'
    return {'from': 'table', 'word': word, 'lines': [it[2] for it in items], 'states': [it[3] for it in items],
            'you': None if needs else NOTHING, 'options': _options(pending)}


def from_summary(reply, pending, out):
    """A card from Haiku's summary `out` ({status_word, lines, you, options}), checked against the reply."""
    source = (reply or '') + '\n' + ((pending or {}).get('text') or '') + '\n' + \
        ' '.join(o.get('label', '') for o in (pending or {}).get('options') or [])
    lines = [_clip(str(l), LINE_MAX) for l in (out.get('lines') or []) if isinstance(l, str) and l.strip()]
    lines = [l for l in lines if numbers_ok(l, source)][:3]
    you = _clip(str(out.get('you') or ''), YOU_MAX)
    if you.lower().startswith('you:'):
        you = you[4:].strip()
    if not you or not numbers_ok(you, source):
        you = NOTHING if not pending else 'answer below'
    if not lines:
        return None
    word = str(out.get('status_word') or '').strip().upper()
    return {'from': 'summary', 'word': word if word in WORDS else 'DONE', 'lines': lines,
            'you': you, 'options': _options(pending, out.get('options'))}


def short_card(reply, pending, rows=None):
    """The card with no model: the table's own cells, or the reply's first sentence."""
    if rows:
        return dict(from_table(rows, pending), source='short')
    text = first_sentence(detail.plain(reply))
    if pending and pending.get('kind') != 'plan' and pending.get('text'):
        text = first_sentence(detail.plain(pending['text']))
    lines = [_clip(text, 90)] if text else []
    you = ('pick below' if pending.get('options') else 'answer below') if pending else NOTHING
    return {'from': 'summary', 'source': 'short', 'word': 'NEEDS YOU' if pending else 'DONE', 'lines': lines,
            'you': you, 'options': _options(pending)}


def serve(card, status):
    """The card as the API gives it, for the session's state now. The live state sets the status word, except
    for a finished turn (idle), where the reply itself says whether it needs the person."""
    if not card:
        return None
    word = STATUS_WORD.get(status) if status != 'idle' else card.get('word')
    if word == 'WORKING' and status == 'idle':
        word = 'DONE'
    lines = list(card.get('lines') or [])
    states = card.get('states')
    you = card.get('you')
    if card.get('from') == 'table':
        needs = [l[2:] if l.startswith('! ') else l for l, s in zip(lines, states or []) if s == 'needs']
        phrase = (needs[0] if len(needs) == 1 else f'{len(needs)} asks need you') if needs else \
            (lines[0] if lines else '')
    else:
        phrase = you if you and you != NOTHING else (lines[0] if lines else '')
    out = {'status_word': word or 'DONE', 'lines': lines, 'you': you, 'options': card.get('options') or [],
           'phrase': _clip(phrase, LINE_MAX), 'from': card.get('from'), 'source': card.get('source', 'model')}
    if states:
        out['states'] = list(states)
    return out


# -- Haiku ------------------------------------------------------------------------------------------------------------

RULES = """\
Rules:
- Use ASD-STE100 Simplified Technical English words: short, common words, present tense, active voice. \
Use "+" for "and", and "w/" for "with", when that saves space.
- Keep every number, price, date, time, part number and name exactly as the reply writes it. You can shorten \
units: wk, hr, min, pcs, m, in.
- Use only facts that the text gives. Do not add a name, a number, a reason or a step that the text does not \
have. Do not guess.
- No Markdown, no emoji, no quote marks around a line."""

SUMMARY = """\
You write a glance card for smart glasses. The reader is not a strong reader. He reads the card in one second, \
while he walks. The card comes before the long reply.

You get a work session's last reply, and the question that it asks now, if there is one. Return only one JSON \
object, with no other text:
{"status_word": "...", "lines": ["...", "..."], "you": "...", "options": ["...", "..."]}

status_word: "NEEDS YOU" when the reply asks the reader to do or decide something. "WAITING" when the work waits \
on a different person, a supplier or a set time. "WORKING" when the reply says that the work continues now. Else \
"DONE".
lines: 1 to 3 lines, the most important first. Each line has 3 to 6 words and at most 30 characters. Put the key \
fact or number first, after a short label: "Harbor Film: $4,820 for 10", "Lead: 3 wk after deposit", "Card: +3%". \
One fact on each line. An error or a failure is a key fact: give it the first line ("Error: job 4471 locked"). \
What the reader must do goes in "you", not in lines.
you: what the reader must do now, in 2 to 5 words, with no "You:" in front: "sign + pay 50%", "pick a day", \
"check the error". When the reader must do nothing, "nothing now".
options: only when a question waits: for each of its options, in the same order, the same answer in 1 to 3 words: \
"Tue", "2nd purge", "Allow". Else [].

""" + RULES

TABLE = """\
You shorten the rows of a status table for smart glasses. The reader is not a strong reader. He reads each row \
in one second, while he walks.

You get the rows as JSON. Each row has "ask" (what the row is about), "state" (needs: the reader must act; \
working: it goes on or waits on someone else; done; dropped; other), "status", "need" (what the reader must do) \
and "notes". Return only one JSON object, with no other text:
{"rows": [{"ask": "...", "what": "..."}], "options": ["..."]}

Give one item for each row, in the same order, and no other items.
ask: what the row is about, in 2 to 4 of the row's own main words, at most 22 characters: "Belt order", \
"Proof w/ customer", "Add feeder to LX-210". Two rows never get the same ask. \
Keep a job number or a part number when the row has one: "Job 4490 proof", "LX-210 feeder".
what: 2 to 5 words and at most 24 characters. For a row whose state is needs: what the reader must do ("pick a day", "sign + pay 50%"). \
For the other rows: the short status, with who or when if the row gives it ("wait Acme, Mon 5 PM", \
"check Mon 11/30", "done").
options: only when a question waits: for each of its options, in the same order, the same answer in 1 to 3 \
words. Else [].

""" + RULES


def ask_haiku(system, text):
    """Haiku's answer, through Claude Code as the Kit's checks call it: hooks off and this process's session
    variables dropped, so the call starts no other check and no session."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT'))}
    env['EFFORT_JUDGE'] = '1'  # the Kit's mark for its own side calls
    r = subprocess.run(
        [CLAUDE, '-p', '--model', MODEL, '--effort', 'low', '--no-session-persistence', '--strict-mcp-config',
         '--tools', '', '--settings', '{"disableAllHooks":true}', '--system-prompt', system, text],
        capture_output=True, text=True, timeout=TIMEOUT, env=env, cwd='/tmp')
    if r.returncode:
        raise RuntimeError('exit %d %s' % (r.returncode, (r.stderr or r.stdout).strip()[:160]))
    return r.stdout


def parse_json(text):
    """The first JSON object in the model's answer (it can come in a code block)."""
    s = text or ''
    start = s.find('{')
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                esc = (c == '\\') and not esc
                if c == '"' and not esc:
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(s[start:i + 1])
                        if isinstance(v, dict):
                            return v
                    except ValueError:
                        break
                    break
        start = s.find('{', start + 1)
    raise ValueError('no JSON object in the answer')


def _question(pending):
    if not pending:
        return ''
    opts = ' | '.join(f'{i + 1}. {o.get("label", "")}' for i, o in enumerate(pending.get('options') or []))
    text = detail.plain(pending.get('text') or '')
    return f'{pending.get("kind", "question")}: {text[:1500]}' + (f'\nOptions: {opts}' if opts else '')


def make(title, reply, pending, ask=ask_haiku):
    """The card for one reply (Markdown) and the prompt that waits, if any. Raises when the model fails."""
    rows = status_table(reply)
    q = _question(pending)
    if rows:
        text = json.dumps(rows, ensure_ascii=False) + (f'\n\nQuestion now: {q}' if q else '')
        out = parse_json(ask(TABLE, text))
        short = out.get('rows')
        card = from_table(rows, pending, short if isinstance(short, list) else None)
        card['options'] = _options(pending, out.get('options'))
        return card
    r = reply or ''
    if len(r) > MAX_REPLY:
        r = r[:MAX_REPLY // 2] + '\n[...]\n' + r[-MAX_REPLY // 2:]
    text = f'Session: {title}\n' + (f'Question now: {q}\n' if q else '') + f'\nLast reply:\n{r}'
    card = from_summary(reply, pending, parse_json(ask(SUMMARY, text)))
    if card is None:
        raise ValueError('no line passed the checks')
    return card


def key_of(reply, pending):
    p = pending or {}
    raw = json.dumps([reply or '', p.get('kind'), p.get('text'), [o.get('label') for o in p.get('options') or []]],
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


# -- the cards of every session ---------------------------------------------------------------------------------------

def kit_held(kit_folder):
    """True when the Kit says its side calls to Claude wait now (the account at its usage limit, and no one chose
    usage credits): the Kit's own limit-hook.py, as its other checks ask it. False when the Kit is not there."""
    path = os.path.join(kit_folder, 'hooks', 'limit-hook.py')
    if not os.path.exists(path):
        return False
    try:
        spec = importlib.util.spec_from_file_location('kit_limit', path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return bool(m.held(None, None))
    except Exception:
        return False


class Cards:
    """Each session's card, made in the background, never in the way of the list: `card(cse)` gives what is
    there now (or None), and `ready(cse)` is called when a new one is made. Sessions get their card in the order:
    the one the glasses show, needs you, working, waiting, idle."""

    def __init__(self, folder, fetch, ready, ask=ask_haiku, held=lambda: False, only='', log=print, workers=WORKERS):
        self.path = os.path.join(folder, 'glances.json') if folder else None
        self.fetch = fetch  # cse -> (title, reply Markdown, pending view or None)
        self.ready = ready
        self.ask = ask
        self.held = held
        self.only = (only or '').strip().lower()
        self.log = log
        self.lock = threading.Lock()
        self.wake = threading.Condition(self.lock)
        self.cache = {}  # reply key -> card
        self.seen = {}  # cse -> {'marker', 'key', 'at'}
        self.want = {}  # cse -> (rank, marker, input or None)
        self.busy = set()
        self.fetched = {}  # cse -> time of its last read
        self.stop = threading.Event()
        self._load()
        for i in range(workers):
            threading.Thread(target=self._run, name=f'glance-{i}', daemon=True).start()

    # -- disk
    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path) as f:
                d = json.load(f)
            self.cache = d.get('cards') or {}
            self.seen = d.get('seen') or {}
        except (OSError, ValueError):
            pass

    def _save(self):
        if not self.path:
            return
        with self.lock:
            cards = sorted(self.cache.items(), key=lambda kv: kv[1].get('at', 0))[-KEEP:]
            self.cache = dict(cards)
            keys = set(self.cache)
            seen = {c: s for c, s in self.seen.items() if s.get('key') in keys}
            data = json.dumps({'cards': self.cache, 'seen': seen}, ensure_ascii=False)
        tmp = self.path + '.tmp'
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(data)
            os.replace(tmp, self.path)
        except OSError as e:
            self.log(f'glance could not save the cards: {e}')

    # -- what the hub asks
    def wanted(self, title):
        return not self.only or (title or '').strip().lower().startswith(self.only)

    def card(self, cse):
        with self.lock:
            s = self.seen.get(cse)
            return (self.cache.get(s['key']) or s.get('short')) if s else None

    def note(self, cse, title, marker, rank):
        """A session in the list, as it is now (`marker` changes when anything in it changes). Its card is made
        again when the marker moved, or when it holds only the first sentence and RETRY_S has gone by."""
        if not self.wanted(title):
            return
        with self.lock:
            s = self.seen.get(cse)
            stale = s is None or s.get('marker') != marker or \
                (s.get('key') not in self.cache and time.time() - s.get('at', 0) > RETRY_S)
            if not stale or cse in self.busy:
                return
            old = self.want.get(cse)
            if old and old[0] <= rank and old[1] == marker:
                return
            # A reply handed in for the same state stays; for a newer one, the worker reads it again.
            self.want[cse] = (rank, marker, old[2] if old and old[1] == marker else None)
            self.wake.notify()

    def for_reply(self, cse, title, reply, pending, marker, rank=0):
        """The card for this exact reply: made already, or the short card now and Haiku's soon."""
        if not (reply or pending):
            return None  # nothing to show yet: the app shows the status
        key = key_of(reply, pending)
        with self.lock:
            if key in self.cache:
                self.seen[cse] = {'marker': marker, 'key': key, 'at': time.time()}
                return self.cache[key]
            s = self.seen.get(cse)
            if s and s.get('key') == key and s.get('short'):
                short = s['short']
            else:
                short = short_card(reply, pending, status_table(reply))
            if self.wanted(title) and cse not in self.busy and \
                    not (s and s.get('key') == key and time.time() - s.get('at', 0) < RETRY_S):
                self.want[cse] = (rank, marker, (title, reply, pending))
                self.wake.notify()
            return short

    # -- the workers
    def _next(self):
        with self.lock:
            while not self.stop.is_set():
                now = time.time()
                ready = [(v[0], c) for c, v in self.want.items()
                         if v[2] is not None or now - self.fetched.get(c, 0) >= REFETCH_S]
                if ready:
                    _, cse = min(ready)
                    item = self.want.pop(cse)
                    self.busy.add(cse)
                    return cse, item
                self.wake.wait(timeout=2 if self.want else None)
        return None, None

    def _run(self):
        while not self.stop.is_set():
            cse, item = self._next()
            if cse is None:
                return
            try:
                self._make(cse, item)
            except Exception as e:
                self.log(f'glance {cse}: {type(e).__name__}: {str(e)[:160]}')
            finally:
                with self.lock:
                    self.busy.discard(cse)

    def _make(self, cse, item):
        _, marker, given = item
        if given is None:
            self.fetched[cse] = time.time()
            given = self.fetch(cse)
            if given is None:
                return
        title, reply, pending = given
        key = key_of(reply, pending)
        with self.lock:
            if key in self.cache:
                self.seen[cse] = {'marker': marker, 'key': key, 'at': time.time()}
                hit = True
            else:
                hit = False
        if hit:
            self.ready(cse)
            return
        if not (reply or pending):
            with self.lock:
                self.seen[cse] = {'marker': marker, 'key': key, 'at': time.time()}
            return
        card, why = None, ''
        if self.held():
            why = 'the account is at its usage limit'
        else:
            try:
                t0 = time.time()
                card = make(title, reply, pending, self.ask)
                card['at'] = time.time()
                self.log(f'glance {cse}: made in {time.time() - t0:.1f} s ({card["from"]})')
            except Exception as e:
                why = f'{type(e).__name__}: {str(e)[:120]}'
        with self.lock:
            if card:
                self.cache[key] = card
                self.seen[cse] = {'marker': marker, 'key': key, 'at': time.time()}
            else:
                self.seen[cse] = {'marker': marker, 'key': key, 'at': time.time(),
                                  'short': short_card(reply, pending, status_table(reply))}
        if card:
            self._save()
        else:
            self.log(f'glance {cse}: the first sentence for now ({why})')
        self.ready(cse)


if __name__ == '__main__':
    # A card for text in a file, to try the words: glance.py <reply.md> [title]
    import sys
    reply = open(sys.argv[1]).read()
    print(json.dumps(serve(make(sys.argv[2] if len(sys.argv) > 2 else 'Session', reply, None), 'idle'), indent=1,
                     ensure_ascii=False))
