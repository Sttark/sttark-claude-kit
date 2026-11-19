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


def plain(md):
    """Markdown as plain text: no marks, links as their words, code blocks kept as plain lines."""
    if not md:
        return ''
    lines, out, in_code = md.replace('\r\n', '\n').split('\n'), [], False
    for line in lines:
        if _FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            out.append(line.rstrip())
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
        if line.strip().startswith('|') and line.strip().endswith('|') and line.count('|') >= 2:
            cells = [c.strip() for c in line.strip()[1:-1].split('|')]
            line = ' | '.join(cells)
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


def last_reply(events):
    """The text of the newest assistant message that has text (events newest first), as plain text."""
    for ev in events:
        p = payload(ev)
        if p.get('type') == 'assistant':
            t = message_text(p).strip()
            if t:
                return plain(t)
    return ''


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
