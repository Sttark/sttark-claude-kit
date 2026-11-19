"""One session's detail for the glasses: its last reply as plain text, and the prompt that waits for the person.

All from the session's events, as the Claude API keeps them (GET /v1/code/sessions/{id}/events, newest first, and
the live stream). A prompt is a `control_request` from the session (`source: worker`) with subtype `can_use_tool`:
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


def parts(md):
    """Markdown as parts, for a lens that draws a table as a picture: [{'text': ...}, {'table': {'heads', 'rows'}}].
    The text between tables is plain() text. A table keeps its cells, as words (no marks, a status emoji as its
    word), every row as long as the header. A header with no rows stays text, as plain() writes it."""
    if not md:
        return []
    lines = md.replace('\r\n', '\n').split('\n')
    out, buf, in_code, i = [], [], False, 0

    def flush():
        t = plain('\n'.join(buf))
        if t:
            out.append({'text': t})
        buf.clear()

    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            in_code = not in_code
        elif not in_code and _table_start(lines, i):
            j, rows = i + 2, []
            while j < len(lines) and lines[j].strip() and '|' in lines[j] and not _FENCE.match(lines[j]):
                rows.append([_status_text(_cell_text(c)) for c in _cells(lines[j])])
                j += 1
            if rows:
                flush()
                heads = [_status_text(_cell_text(c)) for c in _cells(line)]
                n = max([len(heads)] + [len(r) for r in rows])
                out.append({'table': {'heads': heads + [''] * (n - len(heads)),
                                      'rows': [r + [''] * (n - len(r)) for r in rows]}})
                i = j
                continue
        buf.append(line)
        i += 1
    flush()
    return out


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


def _last_text(events):
    """The markdown of the newest assistant message that has text (events newest first)."""
    for ev in events:
        p = payload(ev)
        if p.get('type') == 'assistant':
            t = message_text(p).strip()
            if t:
                return t
    return ''


def last_reply(events):
    """The text of the newest assistant message that has text (events newest first), as plain text."""
    return plain(_last_text(events))


def last_reply_parts(events):
    """The same reply as parts(): its tables kept as cells, for the lens to draw as pictures."""
    return parts(_last_text(events))


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
