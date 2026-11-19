"""Read to me: a session's short summary as words to speak, and as sound made on this Mac with macOS `say`.

The glasses have no speaker. The app plays the sound on the phone (its speaker, or the earbuds connected to it), so
the Mac makes an AAC file (audio/mp4) that every phone web view plays. `say` uses the Mac's own voice (System
Settings > Accessibility > Spoken Content, System voice). Nothing goes to any other server.

The words, in order: the session's name; its `glance` (a short summary) when the session has one, else its status
line and the first two sentences of its last reply; then the question it asks now, with the answers.
glasses/app/src/speech-text.ts says the same words for the phone's own voice, when the Mac cannot make the sound.
"""
import collections
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata

SAY = '/usr/bin/say'
MAX_CHARS = 900  # about a minute of speech
SENTENCES = 2
CACHE_SIZE = 24
TIMEOUT_S = 60

STATUS_WORDS = {'needs_you': 'Needs you', 'working': 'Working', 'waiting': 'Waiting', 'idle': 'Idle'}

_cache = collections.OrderedDict()
_lock = threading.Lock()


class SpeechUnavailable(Exception):
    pass


def status():
    """None when `say` can make sound, else why not."""
    return None if os.access(SAY, os.X_OK) else 'macOS say is not on this Mac'


# -- the words

def speakable(s):
    """Text as a voice should read it: no links, no Markdown or table marks, no emoji."""
    s = str(s or '')
    s = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', s)  # Markdown links: their words
    s = re.sub(r'https?://\S+', 'a link', s)
    s = re.sub(r'`+', '', s)
    s = re.sub(r'(\*\*|__)(.+?)\1', r'\2', s)
    s = re.sub(r'^\s*(#{1,6}|>|[-*+]|\d+[.)])\s+', '', s, flags=re.M)  # headings, quotes, list marks
    s = s.replace('|', ', ').replace('->', ' to ').replace('→', ' to ').replace('=>', ' to ')
    s = ''.join(c for c in s if unicodedata.category(c) not in ('So', 'Cs', 'Co') and c not in '️‍')
    s = s.replace('…', '...').replace('—', ', ').replace('–', '-')
    return s


def _sentence(s):
    s = re.sub(r'\s+', ' ', s).strip(' ,;:')
    if s and s[-1] not in '.!?':
        s += '.'
    return s


def first_sentences(text, n=SENTENCES):
    """The first `n` sentences. A line that ends without a stop (a heading, a list item, a table card's line) is a
    sentence of its own."""
    lines = [ln.strip() for ln in speakable(text).split('\n')]
    flat = ' '.join(_sentence(ln) for ln in lines if re.search(r'\w', ln))
    parts = re.split(r'(?<=[.!?])\s+(?=["\'(\[]?[A-Z0-9])', flat)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > 300:  # one very long sentence: cut it at a word
            p = p[:300].rsplit(' ', 1)[0].rstrip(' ,;:') + '.'
        out.append(p)
        if len(out) == n:
            break
    return out


def _clean(s):
    return re.sub(r'\s+', ' ', speakable(s)).strip()


def spoken_text(d):
    """The words to read for a session (a list row or the detail)."""
    parts = [_sentence(_clean(d.get('title')) or 'This session')]
    pending = d.get('pending') or None
    glance = _clean(d.get('glance'))
    if glance:
        parts.append(_sentence(glance))
    else:
        words = STATUS_WORDS.get(d.get('status'), 'Idle')
        # The status line's words. While a question waits, they repeat the question, which comes last.
        why = '' if pending else _clean(d.get('why') or d.get('status_line'))
        parts.append(_sentence(f'{words}: {why}' if why else words))
        parts.extend(first_sentences(d.get('last_reply') or ''))
    if pending:
        kind = pending.get('kind')
        text = _clean(pending.get('text'))
        if kind == 'plan':
            parts.append('It has a plan for you to approve.')
        elif kind == 'permission':
            parts.append(_sentence(f'It asks for your OK: {text}' if text else 'It asks for your OK.'))
        else:
            parts.append(_sentence(f'It asks: {text}' if text else 'It asks you a question.'))
            labels = [_clean(o.get('label')) for o in pending.get('options') or [] if _clean(o.get('label'))]
            if labels:
                parts.append('The answers: ' + ' '.join(_sentence(f'{i + 1}, {lb}') for i, lb in enumerate(labels[:6])))
    text = ' '.join(p for p in parts if p)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(' ', 1)[0].rstrip(' ,;:') + '.'
    return text


# -- the sound

def render(text):
    """AAC audio (audio/mp4) of `text` in the Mac's own voice. Returns (bytes, cached)."""
    key = hashlib.sha1(text.encode('utf-8')).hexdigest()
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key], True
    why = status()
    if why:
        raise SpeechUnavailable(why)
    tmp = tempfile.mkdtemp(prefix='g2-speech-')
    out = os.path.join(tmp, 'speech.m4a')
    try:
        # The words go in on stdin, so no word can read as an option.
        r = subprocess.run([SAY, '-o', out, '--file-format=m4af', '--data-format=aac', '-f', '-'],
                           input=text.encode('utf-8'), capture_output=True, timeout=TIMEOUT_S)
        if r.returncode != 0 or not os.path.exists(out):
            raise SpeechUnavailable((r.stderr or b'').decode('utf-8', 'replace').strip()[:200] or f'say failed ({r.returncode})')
        with open(out, 'rb') as f:
            data = f.read()
    except subprocess.TimeoutExpired:
        raise SpeechUnavailable(f'say took over {TIMEOUT_S} s')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with _lock:
        _cache[key] = data
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return data, False

