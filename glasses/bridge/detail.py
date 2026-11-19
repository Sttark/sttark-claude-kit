"""One session's detail for the glasses: its last reply as plain text, and the prompt that waits for the person.

All from the session's events, as the Claude API keeps them (GET /v1/code/sessions/{id}/events, newest first, and
the live stream). The last reply is all the text of the newest turn that has text: a turn starts with a message
the person typed (or the Kit typed for them) and ends with its `result`; its agents' messages (with a
`parent_tool_use_id`) are not part of it. A prompt is a `control_request` from the session (`source: worker`) with
subtype `can_use_tool`:
AskUserQuestion (a question with options), ExitPlanMode (a plan to approve) or any other tool (a permission). It is
settled by a `control_response` or a `control_cancel_request` that names its request id, or by the end of its turn.
"""
import re

# -- markdown to plain text ---------------------------------------------------------------------------------------

_FENCE = re.compile(r'^\s*(```|~~~)')
_HEAD = re.compile(r'^\s{0,3}#{1,6}\s+')
_QUOTE = re.compile(r'^\s{0,3}>\s?')
_RULE = re.compile(r'^\s{0,3}([-*_])(\s*\1){2,}\s*$')
_BULLET = re.compile(r'^(\s*)[*+-]\s+')
_TABLE_SEP = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$')
_TABLE_DELIM = re.compile(r'^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$')
_IMAGE = re.compile(r'!\[([^\]]*)\]\([^)]*\)')
_LINK = re.compile(r'\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
_AUTOLINK = re.compile(r'<(https?://[^>\s]+)>')
_CODE = re.compile(r'`([^`]+)`')
_BOLD = re.compile(r'(\*\*|__)(?=\S)(.+?)(?<=\S)\1')
_ITALIC_STAR = re.compile(r'(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])')
_ITALIC_UND = re.compile(r'(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])')
_STRIKE = re.compile(r'~~(?=\S)(.+?)(?<=\S)~~')
_TAG = re.compile(r'</?[A-Za-z][A-Za-z0-9-]*(\s[^<>]*)?/?>')


def _inline(s):
    s = _IMAGE.sub(lambda m: m.group(1), s)
    s = _LINK.sub(lambda m: m.group(1) if m.group(1) != m.group(2) else m.group(2), s)
    s = _AUTOLINK.sub(lambda m: m.group(1), s)
    # code spans first, kept as they are (their stars and underscores are not emphasis)
    parts = _CODE.split(s)
    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append(p)
            continue
        p = _BOLD.sub(lambda m: m.group(2), p)
        p = _ITALIC_STAR.sub(lambda m: m.group(1), p)
        p = _ITALIC_UND.sub(lambda m: m.group(1), p)
        p = _STRIKE.sub(lambda m: m.group(1), p)
        p = _TAG.sub('', p)
        out.append(p)
    return ''.join(out)


# -- tables as cards ------------------------------------------------------------------------------------------------
# The lens font is proportional, so a table's columns never line up there. Each row becomes a card: the row's name on
# one line, then one line per other cell, indented two spaces, as "Header: cell". A status column goes into the label
# of the one other column ("  Needs you: Tell me a day"), and a status emoji becomes words, since the font has none.

_STATUS_WORDS = (('✅', 'Done'), ('🔄', 'In progress'), ('🔴', 'Needs you'), ('⚪', 'Dropped'))
_NOTHING = {'', 'nothing', 'none', '-', '--', '—', '–', 'n/a'}
_NUMBER = re.compile(r'^\d{1,3}[.)]?$')
_BR = re.compile(r'<br\s*/?>', re.I)
_INDENT = '  '


def _cells(line):
    """A table row's cells, without the outer pipes; an escaped pipe stays in its cell."""
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|') and not s.endswith('\\|'):
        s = s[:-1]
    return [c.replace('\\|', '|').strip() for c in re.split(r'(?<!\\)\|', s)]


def _cell_text(c):
    return _inline(_BR.sub(' ', c)).strip()


def _nothing(c):
    return c.strip().rstrip('.').lower() in _NOTHING


def _status(c):
    """(word, the rest) when a cell starts with a status emoji, else (None, the cell)."""
    s = c.strip()
    for mark, word in _STATUS_WORDS:
        if s.startswith(mark):
            return word, s[len(mark):].lstrip('️').strip()
    return None, s


def _status_text(c):
    """A status emoji as its word: "✅" is "Done", "🔄 Waiting on the supplier" is "In progress, Waiting on ..."."""
    word, rest = _status(c)
    if not word:
        return rest
    if not rest or rest.lower().startswith(word.lower()):
        return rest or word
    return f'{word}, {rest}'


def _table_start(lines, i):
    """True when line i is a table's header: pipes, and a separator row under it with as many cells."""
    if i + 1 >= len(lines) or '|' not in lines[i] or not _TABLE_DELIM.match(lines[i + 1]):
        return False
    return len(_cells(lines[i])) == len(_cells(lines[i + 1]))


def _cards(heads, rows):
    """A table as text cards, one per row, a blank line between them."""
    n = max([len(heads)] + [len(r) for r in rows])
    heads = heads + [''] * (n - len(heads))
    rows = [r + [''] * (n - len(r)) for r in rows]
    col = lambda j: [r[j] for r in rows if not _nothing(r[j])]  # noqa: E731
    # The status column: so named, or every cell in it a status emoji with a word or two.
    status = next((j for j in range(n) if heads[j].lower() in ('status', 'state')), None)
    if status is None:
        status = next((j for j in range(n) if col(j) and all(_status(c)[0] and len(_status(c)[1]) <= 24
                                                             for c in col(j))), None)
    rest = [j for j in range(n) if j != status]
    if not rest:
        return '\n\n'.join(_status_text(r[status]) for r in rows if not _nothing(r[status]))
    name = rest[0]
    # A first column of row numbers goes in front of the name: "2. Press 3 heads".
    number = None
    if len(rest) > 1 and heads[name] in ('', '#', 'No', 'No.') and col(name) and all(_NUMBER.match(c) for c in col(name)):
        number, name = name, rest[1]
    others = [j for j in rest if j not in (name, number)]
    merge = status is not None and len(others) == 1
    cards = []
    for r in rows:
        title = '' if _nothing(r[name]) else _status_text(r[name])
        if number is not None and r[number]:
            title = f'{r[number].rstrip(".)")}. {title}'.strip()
        word = '' if status is None or _nothing(r[status]) else _status_text(r[status])
        lines = []
        if word and not merge:
            lines.append(f'{heads[status]}: {word}' if heads[status] else word)
        for j in others:
            if _nothing(r[j]):
                continue
            label = (word or heads[j]) if merge else heads[j]
            lines.append(f'{label}: {_status_text(r[j])}' if label else _status_text(r[j]))
        if merge and word and not any(not _nothing(r[j]) for j in others):
            lines.append(word)
        if not title and lines:
            title = lines.pop(0)
        if title:
            cards.append('\n'.join([title] + [_INDENT + l for l in lines]))
    return '\n\n'.join(cards)


def plain(md):
    """Markdown as plain text: no marks, links as their words, code blocks kept as plain lines, tables as cards."""
    if not md:
        return ''
    lines, out, in_code = md.replace('\r\n', '\n').split('\n'), [], False
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if _FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            out.append(line.rstrip())
            continue
        if _table_start(lines, i - 1):
            heads = [_cell_text(c) for c in _cells(line)]
            rows, i = [], i + 1
            while i < len(lines) and lines[i].strip() and '|' in lines[i] and not _FENCE.match(lines[i]):
                rows.append([_cell_text(c) for c in _cells(lines[i])])
                i += 1
            out += ['', _cards(heads, rows) if rows else ', '.join(h for h in heads if h), '']
            continue
        if _RULE.match(line):
            out.append('')
            continue
        if _TABLE_SEP.match(line) and '-' in line:
            continue
        line = _HEAD.sub('', line)
        while _QUOTE.match(line):
            line = _QUOTE.sub('', line, count=1)
        line = _BULLET.sub(lambda m: m.group(1) + '- ', line)
        # A status emoji at the start of a line or a list item: its word (the font has no emoji).
        line = re.sub(r'^(\s*(?:- |\d+[.)] )?)(.*)$', lambda m: m.group(1) + _status_text(m.group(2))
                      if _status(m.group(2))[0] else m.group(0), line)
        out.append(_inline(line).rstrip())
    text = '\n'.join(out)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# -- events ---------------------------------------------------------------------------------------------------------

def payload(ev):
    return ev.get('payload') or {}


def seq(ev):
    try:
        return int(ev.get('sequence_num') or 0)
    except (TypeError, ValueError):
        return 0


def message_text(p):
    m = p.get('message') or {}
    c = m.get('content')
    if isinstance(c, str):
        return c
    out = []
    for b in c or []:
        if isinstance(b, dict) and b.get('type') == 'text' and b.get('text'):
            out.append(b['text'])
    return '\n\n'.join(out)


def main_thread(p):
    """The session's own message, not one of its agents' (they carry the agent's Task call as parent_tool_use_id)."""
    return not p.get('parent_tool_use_id') and not p.get('isSidechain')


def prompt(p):
    """A user message that starts a turn: one the person typed (in a Claude app, or on the Mac, as the Kit types it
    when a wait ends). Not a tool's result, an agent's message, a background task's notice, or text Claude Code adds
    itself (isSynthetic, isMeta)."""
    if p.get('type') != 'user' or not main_thread(p) or p.get('isSynthetic') or p.get('isMeta'):
        return False
    if (p.get('origin') or {}).get('kind') == 'task-notification':
        return False
    c = (p.get('message') or {}).get('content')
    if isinstance(c, str):
        return bool(c.strip())
    blocks = [b for b in c or [] if isinstance(b, dict)]
    return any(b.get('type') in ('text', 'image') for b in blocks) and not any(b.get('type') == 'tool_result'
                                                                               for b in blocks)


def turn_edge(p):
    """The end of a turn (its result) or the start of one (a prompt)."""
    return (p.get('type') == 'result' and main_thread(p)) or prompt(p)


def _reply(events):
    """The texts of the newest assistant turn that has text (events newest first), oldest first, and the index of
    the edge before that turn (None when the events stop before it). A turn's text is often in several messages,
    with tool steps between them, and the turn after it may have no text yet (it runs, or it only used tools)."""
    texts = []
    for i, ev in enumerate(events):
        p = payload(ev)
        if p.get('type') == 'assistant' and main_thread(p):
            t = message_text(p).strip()
            if t:
                texts.append(t)
        elif texts and turn_edge(p):
            return texts[::-1], i
    return texts[::-1], None


def reply_whole(events):
    """True when `events` (newest first) hold the newest assistant turn with text from its start."""
    return _reply(events)[1] is not None


def reply_start(events):
    """How many of `events` (newest first) the reply needs: down to the edge before its turn, with it."""
    edge = _reply(events)[1]
    return len(events) if edge is None else edge + 1


def slim(ev):
    """An event with only what the reply needs: its number, kind, flags and text (no tool inputs or results)."""
    p = payload(ev)
    q = {k: p[k] for k in ('type', 'subtype', 'parent_tool_use_id', 'isSidechain', 'isSynthetic', 'isMeta', 'origin')
         if k in p}
    m = p.get('message')
    if isinstance(m, dict):
        c = m.get('content')
        if isinstance(c, list):
            c = [b if b.get('type') == 'text' else {'type': b.get('type')} for b in c if isinstance(b, dict)]
        q['message'] = {'content': c}
    return {'sequence_num': ev.get('sequence_num'), 'payload': q}


def last_reply(events):
    """The newest assistant turn that has text (events newest first), as plain text: all of the turn's text, from
    each of its messages, not an agent's."""
    return '\n\n'.join(t for t in (plain(x) for x in _reply(events)[0]) if t)


def last_reply_md(events):
    """The same turn's text as its Markdown, for the glance card (glance.py), which reads its status table."""
    return '\n\n'.join(_reply(events)[0])


def find_pending(events):
    """The prompt that waits now, or None: the newest worker can_use_tool request with no answer, no withdrawal
    and no end of its turn after it (events newest first)."""
    settled = set()
    for ev in events:
        p = payload(ev)
        t = p.get('type')
        if t == 'control_response':
            rid = (p.get('response') or {}).get('request_id')
            if rid:
                settled.add(rid)
        elif t == 'control_cancel_request':
            if p.get('request_id'):
                settled.add(p['request_id'])
        elif t == 'result':
            return None  # the turn ended after any older prompt
        elif t == 'control_request' and ev.get('source') == 'worker':
            req = p.get('request') or {}
            if req.get('subtype') == 'can_use_tool' and p.get('request_id') and p['request_id'] not in settled:
                return {'request_id': p['request_id'], 'tool_name': req.get('tool_name') or '',
                        'display_name': req.get('display_name') or req.get('tool_name') or '',
                        'description': req.get('description') or '', 'tool_use_id': req.get('tool_use_id'),
                        'input': req.get('input') if isinstance(req.get('input'), dict) else {},
                        'seq': seq(ev)}
    return None


def _questions(req):
    qs = (req.get('input') or {}).get('questions') or []
    return [q for q in qs if isinstance(q, dict)]


def view(req, partial=None):
    """The contract's pending object for a prompt: {kind, text, options: [{id, label}]}. A question prompt with
    several questions shows the first one not answered yet (`partial`: {question index: label})."""
    partial = partial or {}
    tool = req.get('tool_name')
    if tool == 'AskUserQuestion':
        qs = _questions(req)
        for i, q in enumerate(qs):
            if i in partial:
                continue
            text = (q.get('question') or q.get('header') or '').strip()
            if len(qs) > 1:
                text = f'({i + 1}/{len(qs)}) ' + text
            opts = [{'id': f'q{i}.o{j}', 'label': (o.get('label') if isinstance(o, dict) else str(o)) or f'Option {j + 1}'}
                    for j, o in enumerate(q.get('options') or [])]
            return {'kind': 'question', 'text': text, 'options': opts, 'request_id': req['request_id']}
        return {'kind': 'question', 'text': 'Answered', 'options': [], 'request_id': req['request_id']}
    if tool == 'ExitPlanMode':
        plan = plain((req.get('input') or {}).get('plan') or '')
        return {'kind': 'plan', 'text': plan or 'Claude has a plan for your approval.',
                'options': [{'id': 'approve', 'label': 'Approve plan'}, {'id': 'keep', 'label': 'Keep planning'}],
                'request_id': req['request_id']}
    inp = req.get('input') or {}
    what = req.get('description') or inp.get('description') or inp.get('command') or inp.get('file_path') or \
        inp.get('url') or ''
    text = f"Allow {req.get('display_name') or tool}?" + (f' {str(what)[:400]}' if what else '')
    return {'kind': 'permission', 'text': text,
            'options': [{'id': 'allow', 'label': 'Allow'}, {'id': 'deny', 'label': 'Deny'}],
            'request_id': req['request_id']}


class BadOption(ValueError):
    pass


def decide(req, option_id, partial=None):
    """The answer to send for `option_id`. Returns (done, partial, behavior, updated_input, message): `done` False
    means more questions wait (nothing is sent yet; `partial` holds the answers so far)."""
    partial = dict(partial or {})
    tool = req.get('tool_name')
    inp = dict(req.get('input') or {})
    if tool == 'AskUserQuestion':
        m = re.fullmatch(r'q(\d+)\.o(\d+)', option_id or '')
        qs = _questions(req)
        if not m or int(m.group(1)) >= len(qs):
            raise BadOption('That option is not one of the question\'s options.')
        qi, oi = int(m.group(1)), int(m.group(2))
        opts = qs[qi].get('options') or []
        if oi >= len(opts):
            raise BadOption('That option is not one of the question\'s options.')
        o = opts[oi]
        partial[qi] = (o.get('label') if isinstance(o, dict) else str(o)) or ''
        if any(i not in partial for i in range(len(qs))):
            return False, partial, None, None, None
        answers = {}
        for i, q in enumerate(qs):
            key = q.get('question') or q.get('header') or ''
            answers[key] = [partial[i]] if q.get('multiSelect') else partial[i]
        return True, partial, 'allow', dict(inp, answers=answers), None
    if tool == 'ExitPlanMode':
        if option_id == 'approve':
            return True, partial, 'allow', inp, None
        if option_id == 'keep':
            return True, partial, 'deny', None, 'The person chose to keep planning. Do not start yet.'
        raise BadOption('Use approve or keep.')
    if option_id == 'allow':
        return True, partial, 'allow', inp, None
    if option_id == 'deny':
        return True, partial, 'deny', None, 'The person said no to this, from their glasses.'
    raise BadOption('Use allow or deny.')


# -- turns: the session's history, one prompt and its reply at a time ------------------------------------------------
# For scrolling back on the lens. The same turns as last_reply's: one prompt and all the text Claude wrote after it,
# until the next prompt or the end of its run (`result`), the session's own messages only (main_thread). The prompt
# is a message the person typed (prompt), a message the Kit typed for them (its text starts with "[Sttark Claude
# Kit]"), or a background task's notice: Claude answers one with a turn of its own (a user message from Claude Code
# 2.1.320 on, a `system` event `task_notification` before). "[Request interrupted by user]" ends a turn, as for
# last_reply, but starts none.

KIT_PREFIX = '[Sttark Claude Kit]'
_INTERRUPTED = re.compile(r'^\[Request interrupted by user[^\]]*\]$')
_TASK_SUMMARY = re.compile(r'<summary>(.*?)</summary>', re.S)
_SENTENCE = re.compile(r'^(.{12,}?[.!?])(\s|$)', re.S)


def _first_sentence(s, limit=120):
    s = ' '.join(s.split())
    m = _SENTENCE.match(s)
    s = m.group(1) if m else s
    return s if len(s) <= limit else s[:limit - 3].rsplit(' ', 1)[0] + '...'


def turn_start(p):
    """(who, text) when event payload `p` starts a turn, else None. `who` is "you" (the person's prompt, as plain
    text), "kit" (a message the Kit typed: its first sentence) or "task" (a background task's notice: its summary)."""
    if p.get('type') != 'user' or not main_thread(p) or p.get('isSynthetic') or p.get('isMeta'):
        return None
    c = (p.get('message') or {}).get('content')
    blocks = [{'type': 'text', 'text': c}] if isinstance(c, str) else [b for b in c or [] if isinstance(b, dict)]
    text = '\n\n'.join(b.get('text') or '' for b in blocks if b.get('type') == 'text').strip()
    images = sum(1 for b in blocks if b.get('type') == 'image')
    if (p.get('origin') or {}).get('kind') == 'task-notification':
        m = _TASK_SUMMARY.search(text)
        return 'task', _first_sentence(m.group(1) if m else 'A background task ended.')
    if not prompt(p) or _INTERRUPTED.match(text):
        return None
    if text.startswith(KIT_PREFIX):
        return 'kit', _first_sentence(text[len(KIT_PREFIX):].strip()) or 'A message from the Kit.'
    words = plain(text)
    if images:
        words = (words + ' ' if words else '') + ('[image]' if images == 1 else f'[{images} images]')
    return 'you', words


def _when(ev, p):
    return p.get('timestamp') or ev.get('created_at') or None


def _task_label(p, names):
    """A background task's notice (a system event) in a few words: 'Agent "<its description>" finished'."""
    name = names.get(p.get('task_id'))
    if name:
        return f'Agent "{_first_sentence(name, 80)}" finished'
    return _first_sentence(p.get('summary') or 'A background task ended.')


def turns(events):
    """The session's turns from its events, oldest first (each event once): [{index, at, from, user_text,
    reply_text}], newest last. `at` is when the prompt came (ISO 8601). Text Claude writes after a turn ended with no
    new prompt starts a turn of its own: from "task" when a background task's notice came before it, else from
    "claude", with no user_text.

    A prompt sent while Claude works stops that run: its `result` comes after the prompt, before Claude has done
    anything for it. So only a result after some of the turn's own work ends the turn."""
    out, cur, ran, open_ = [], None, False, False
    names, inner, note = {}, set(), None  # task id -> description; the tasks of agents; the last notice
    for ev in events:
        p = payload(ev)
        start = turn_start(p)
        if start:
            cur = {'at': _when(ev, p), 'from': start[0], 'user_text': start[1], 'texts': []}
            out.append(cur)
            ran, open_, note = False, True, None
        elif p.get('type') == 'system' and p.get('subtype') == 'task_started':
            names[p.get('task_id')] = p.get('description') or ''
            if p.get('owned_by_subagent'):
                inner.add(p.get('task_id'))
        elif p.get('type') == 'system' and p.get('subtype') == 'task_notification':
            if p.get('task_id') not in inner:
                note = (_when(ev, p), _task_label(p, names))
        elif turn_edge(p):  # its result, or "[Request interrupted by user]"
            if ran:
                open_ = False
        elif p.get('type') == 'assistant' and main_thread(p):
            ran = True
            t = message_text(p).strip()
            if not t:
                continue
            if cur is None or not open_:
                at, label = note or (_when(ev, p), '')
                cur = {'at': at, 'from': 'task' if note else 'claude', 'user_text': label, 'texts': []}
                out.append(cur)
                open_, note = True, None
            cur['texts'].append(t)
    return [{'index': i, 'at': t['at'], 'from': t['from'], 'user_text': t['user_text'],
             'reply_text': '\n\n'.join(x for x in (plain(s) for s in t['texts']) if x)} for i, t in enumerate(out)]


def latest_turn(ts):
    """The index of the turn the session screen shows now: the newest one with reply text (a turn that runs, or
    that only used tools, has none yet). -1 when no turn has any."""
    for t in reversed(ts):
        if t['reply_text']:
            return t['index']
    return -1


def slim_event(ev):
    """slim, and what the turns need besides: when, and the background tasks' names and notices."""
    p, out = payload(ev), slim(ev)
    q = out['payload']
    q.update({k: p[k] for k in ('timestamp', 'task_id', 'description', 'owned_by_subagent') if k in p})
    if p.get('subtype') == 'task_notification':
        q['summary'] = str(p.get('summary') or '')[:300]
    out['created_at'] = ev.get('created_at')
    return out
