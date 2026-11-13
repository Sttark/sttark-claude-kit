#!/usr/bin/python3
"""What's new notes: the short notes the app shows once, after an update, for a change people notice.

Each note is whats-new/<slug>.md with its picture whats-new/<slug>.gif (or .png or .svg) beside it, and the same
picture for dark mode as whats-new/<slug>-dark.gif; the app shows the one for the system's look:

    # Title in sentence case

    **Icon:** an SF Symbol's name (macwindow, pause.circle, tray)

    **Kind:** New (a thing people did not have) or Better (a thing they had works better)

    One sentence of at most 20 words: what changes for the person. The sheet and the page both show it.

    - Two or three points, one sentence each, at most 20 words.
    - One point says how to start, with the exact words of the menu and the commands.

    ![What the picture shows, for screen readers](slug.gif)

All words in ASD-STE100 Simplified Technical English. The picture shows only the part that matters, drawn at 2x:
at most 880 by 560 pixels, so the app shows it at its own size (440 by 280 points) and never makes it smaller.

The slug is how the app remembers who saw the note, so a note's file is never renamed once it ships.

    whats-new.py check [file ...]        the facts every note must meet (all notes when none named); exit 1 on a miss
    whats-new.py build <folder>          the notes for the app: <folder>/index.json, newest first, and the pictures
    whats-new.py needs <base> <head>     why a change looks like something people notice, one reason a line
    whats-new.py ask                     on a pull request: asks for a note when one looks needed (never fails)
    whats-new.py ste <file>              the Kit's own STE check of the note's words, with Haiku (needs Claude Code)

build.sh runs build; .github/workflows/whats-new.yml runs check and ask. A note's version is the build number of
the commit that added it (the app's version is 1.<commits on main>), so nobody writes a version by hand.
Runs on macOS's own Python 3.9.
"""
import json, os, re, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES = os.path.join(ROOT, 'whats-new')
PICTURES = ('.gif', '.png', '.svg')
MAX_PICTURE = 3 * 1024 * 1024
MARK = '<!-- sttark-whats-new -->'
CHECK_NAME = "What's new note"

SLUG = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
PICTURE = re.compile(r'^!\[([^\]]*)\]\(([^)\s]+)\)$')
ICON = '**Icon:**'
KIND = '**Kind:**'
KINDS = ('New', 'Better')
MAX_PX = (880, 560)
SYMBOL = re.compile(r'^[a-z0-9]+(\.[a-z0-9]+)*$')
MONTHS = r'(January|February|March|April|May|June|July|August|September|October|November|December|' \
         r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)'
DATES = [
    (re.compile(r'\b' + MONTHS + r'\.? +\d{1,2}\b'), 'a date'),
    (re.compile(r'\b\d{1,2}/\d{1,2}(/\d{2,4})?\b'), 'a date'),
    (re.compile(r'\b(19|20)\d{2}\b'), 'a year'),
    (re.compile(r'\b(yesterday|today|tomorrow|last week|next week)\b', re.I), 'a day'),
    (re.compile(r'\bv?1\.\d{2,}\b'), 'a version number'),
]


def words_only(s):
    """The text a reader sees: code spans count as one word, bold marks dropped."""
    s = re.sub(r'`[^`]*`', 'CODE', s)
    return s.replace('**', '')


def sentences(s):
    s = words_only(s)
    parts = re.split(r'(?<=[.!?])["”)]?\s+(?=[A-Z"“(])', s.strip())
    return [p for p in parts if p.strip()]


def parse(path):
    """The note's parts, or raises ValueError with what is wrong."""
    slug = os.path.splitext(os.path.basename(path))[0]
    with open(path, encoding='utf-8') as f:
        text = f.read()
    paras = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    if not paras or not paras[0].startswith('# ') or '\n' in paras[0]:
        raise ValueError('the first line must be "# Title", alone in its paragraph')
    note = {'id': slug, 'title': paras[0][2:].strip(), 'lead': '', 'points': [], 'picture': '', 'alt': '', 'icon': '', 'kind': ''}
    for p in paras[1:]:
        m = PICTURE.match(p)
        if m:
            if note['picture']:
                raise ValueError('one picture only')
            note['alt'], note['picture'] = m.group(1).strip(), m.group(2)
        elif p.startswith(ICON):
            note['icon'] = p[len(ICON):].strip()
        elif p.startswith(KIND):
            note['kind'] = p[len(KIND):].strip()
        elif p.startswith('- '):
            if note['points']:
                raise ValueError('one list of points only')
            items = re.split(r'\n- ', p[2:])
            note['points'] = [' '.join(i.split()) for i in items]
        elif p.startswith(('#', '-', '*', '>', '|', '```')) and not p.startswith('**'):
            raise ValueError('no headings, quotes, tables or code blocks: %r' % p[:40])
        elif note['lead']:
            raise ValueError('one sentence before the points only; put the rest in the points')
        else:
            note['lead'] = ' '.join(p.split())
    return note


def pixels(path):
    """A PNG's or GIF's width and height in pixels, or None."""
    with open(path, 'rb') as f:
        h = f.read(26)
    if h[:8] == b'\x89PNG\r\n\x1a\n':
        return int.from_bytes(h[16:20], 'big'), int.from_bytes(h[20:24], 'big')
    if h[:4] == b'GIF8':
        return int.from_bytes(h[6:8], 'little'), int.from_bytes(h[8:10], 'little')
    return None


def dark_picture(name):
    """The picture for dark mode, beside the light one: hold-before-limit.gif and hold-before-limit-dark.gif."""
    base, ext = os.path.splitext(name)
    return base + '-dark' + ext


def problems(path):
    """Every fact the note breaks. Judgment (are the words clear, is it STE) is for people and the ste command."""
    out = []
    slug = os.path.splitext(os.path.basename(path))[0]
    if not SLUG.match(slug):
        out.append('the file name must be lowercase words joined by hyphens: whats-new/<slug>.md')
    try:
        n = parse(path)
    except ValueError as e:
        return out + [str(e)]
    if not n['title']:
        out.append('no title')
    elif len(n['title']) > 60:
        out.append('the title has %d characters; 60 at most' % len(n['title']))
    elif n['title'][0].islower() or n['title'].endswith('.'):
        out.append('the title starts with a capital letter and has no full stop')
    if not n['lead']:
        out.append('no sentence that says what changes for the person')
    elif len(sentences(n['lead'])) > 1 or len(words_only(n['lead']).split()) > 20:
        out.append('the sentence before the points is one sentence of at most 20 words')
    if not 2 <= len(n['points']) <= 3:
        out.append('%d points; 2 or 3, each a line "- ..."' % len(n['points']))
    for x in n['points']:
        if len(sentences(x)) > 1 or len(words_only(x).split()) > 20:
            out.append('a point is one sentence of at most 20 words: "%s..."' % ' '.join(x.split()[:5]))
    if not SYMBOL.match(n['icon']):
        out.append('no "%s" line with an SF Symbol name, such as macwindow' % ICON)
    if n['kind'] not in KINDS:
        out.append('no "%s" line: New or Better' % KIND)
    body = ' '.join([n['lead']] + n['points'])
    if not n['picture']:
        out.append('no picture: one line "![what it shows](%s.gif)"' % slug)
    else:
        pic = os.path.join(os.path.dirname(path), n['picture'])
        if '/' in n['picture'] or os.path.splitext(n['picture'])[1].lower() not in PICTURES:
            out.append('the picture is a .gif, .png or .svg file next to the note')
        elif not os.path.isfile(pic):
            out.append('the picture %s is not in whats-new/' % n['picture'])
        elif os.path.getsize(pic) > MAX_PICTURE:
            out.append('the picture is %.1f MB; 3 MB at most' % (os.path.getsize(pic) / 1048576))
        else:
            px = pixels(pic)
            if px and (px[0] > MAX_PX[0] or px[1] > MAX_PX[1]):
                out.append('the picture is %d by %d pixels; %d by %d at most: show only the part that matters'
                           % (px + MAX_PX))
        if not n['alt']:
            out.append('the picture needs words that say what it shows: ![...]')
        dark = os.path.join(os.path.dirname(path), dark_picture(n['picture']))
        if not os.path.isfile(dark):
            out.append('no %s: the picture for dark mode, beside the light one (tools/whats-new-pictures.swift draws both)'
                       % dark_picture(n['picture']))
        elif os.path.getsize(dark) > MAX_PICTURE:
            out.append('the dark picture is %.1f MB; 3 MB at most' % (os.path.getsize(dark) / 1048576))
    words = ' '.join([n['title'], body, n['alt']])
    plain = re.sub(r'`[^`]*`', '', words)
    for rx, what in DATES:
        m = rx.search(plain)
        if m:
            out.append('%s ("%s"): a note says what is, with no dates or versions' % (what, m.group(0)))
    if '—' in plain or '--' in plain:
        out.append('no em-dashes or double hyphens')
    if re.search(r'[\w.+-]+@[\w-]+\.\w+', plain) or re.search(r'(^|\s)@\w', plain):
        out.append('no email addresses or @names')
    return out


def note_files():
    if not os.path.isdir(NOTES):
        return []
    return sorted(os.path.join(NOTES, f) for f in os.listdir(NOTES) if f.endswith('.md') and f != 'README.md')


def check(files):
    files = files or note_files()
    bad = 0
    for f in files:
        p = problems(f)
        rel = os.path.relpath(f, ROOT)
        if p:
            bad += 1
            for x in p:
                print('%s: %s' % (rel, x))
                if os.environ.get('GITHUB_ACTIONS'):
                    print('::error file=%s::%s' % (rel, x))
        else:
            print('%s: ok' % rel)
    if not files:
        print('no notes')
    return 1 if bad else 0


def git(*args):
    return subprocess.run(['git'] + list(args), cwd=ROOT, capture_output=True, text=True).stdout


def build_number(path):
    """The build that first shipped the note: the commit count at the commit that added it. A note not yet
    committed belongs to the build being made."""
    rel = os.path.relpath(path, ROOT)
    added = git('log', '--diff-filter=A', '--format=%H', '--', rel).split()
    if added:
        n = git('rev-list', '--count', added[-1]).strip()
        if n.isdigit():
            return int(n)
    return int(os.environ.get('BUILD') or git('rev-list', '--count', 'HEAD').strip() or 0) or 0


def shipped(path):
    """(build, date) of the commit on main that first shipped the note: the note's own commit when it is on main,
    or the merge that brought it. Not committed yet: the build being made, today."""
    import datetime
    rel = os.path.relpath(path, ROOT)
    added = git('log', '--diff-filter=A', '--format=%H', '--', rel).split()
    if added:
        c = added[-1]
        main = git('rev-list', '--first-parent', 'HEAD').split()
        if c not in main:
            later = set(git('rev-list', '--ancestry-path', '%s..HEAD' % c).split())
            c = next((m for m in reversed(main) if m in later), c)
        n = git('rev-list', '--count', c).strip()
        d = git('log', '-1', '--format=%cs', c).strip()
        if n.isdigit():
            return int(n), d
    return build_number(path), datetime.date.today().isoformat()


def build(out):
    """The app's copy: index.json (newest first) and the pictures. A note that breaks a fact stops the build."""
    files = note_files()
    if check(files):
        sys.exit('whats-new: fix the notes above first')
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    notes = []
    for f in files:
        n = parse(f)
        n['build'], n['date'] = shipped(f)
        shutil.copy(os.path.join(NOTES, n['picture']), os.path.join(out, n['picture']))
        dark = dark_picture(n['picture'])
        if os.path.isfile(os.path.join(NOTES, dark)):
            shutil.copy(os.path.join(NOTES, dark), os.path.join(out, dark))
            n['picture_dark'] = dark
        notes.append(n)
    notes.sort(key=lambda n: (-n['build'], n['id']))
    with open(os.path.join(out, 'index.json'), 'w') as f:
        json.dump(notes, f, indent=1, ensure_ascii=False)
    print('whats-new: %d notes' % len(notes))


# --- does a change need a note ---

MENU_CALL = re.compile(r'\b(?:action|caption|row|header)\(\s*"((?:[^"\\]|\\.)*)"')
WINDOW_TEXT = re.compile(r'\b(?:messageText|informativeText|title)\s*=\s*"((?:[^"\\]|\\.)*)"')


def diff_lines(base, head, path):
    """(added lines with their new line numbers, removed lines) of one file between base and head."""
    added, removed, line = [], [], 0
    for l in git('diff', '-U0', '%s...%s' % (base, head), '--', path).splitlines():
        m = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', l)
        if m:
            line = int(m.group(1))
        elif l.startswith('+') and not l.startswith('+++'):
            added.append((line, l[1:]))
            line += 1
        elif l.startswith('-') and not l.startswith('---'):
            removed.append(l[1:])
    return added, removed


LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def plain_string(s):
    return re.sub(r'\\\([^)]*\)+', '#', s).strip()


def strings(lines, rx):
    out = []
    for l in lines:
        out += [m.group(1) for m in rx.finditer(l)]
    return out


def needs(base, head):
    """(has a note, reasons the change looks like something people notice). Facts about the diff only; whether
    a person really notices it is the author's call, so this only ever asks."""
    reasons = []
    status = [l.split('\t') for l in git('diff', '--name-status', '%s...%s' % (base, head)).splitlines() if '\t' in l]
    has_note = any(p[-1].startswith('whats-new/') and p[-1].endswith('.md') and p[0][0] in 'AMR' for p in status)
    for p in status:
        kind, path = p[0][0], p[-1]
        if kind == 'D':
            continue
        if path.startswith('Sources/') and path.endswith('.swift'):
            if kind == 'A':
                reasons.append('a new part of the app: `%s`' % path)
                continue
            added, _ = diff_lines(base, head, path)
            # a string that was in the file before only moved; \(...) parts may change
            before = set(plain_string(x) for x in LITERAL.findall(git('show', '%s:%s' % (base, path))))
            new = [s for s in strings([l for _, l in added], MENU_CALL) + strings([l for _, l in added], WINDOW_TEXT)
                   if plain_string(s) not in before and len(plain_string(s)) > 2]
            if new:
                reasons.append('new words in the menu or a window (`%s`): %s'
                               % (path, ', '.join('"%s"' % s for s in new[:3]) + (' and more' if len(new) > 3 else '')))
        elif path == 'Resources/hooks/working-rules-hook.py':
            added, removed = diff_lines(base, head, path)
            src = git('show', '%s:%s' % (head, path)).splitlines()
            start = next((i + 1 for i, l in enumerate(src) if l.startswith('RULES = ')), 0)
            end = next((i + 1 for i, l in enumerate(src) if i + 1 > start and l.rstrip().endswith('"""')), 0)
            if start and any(start <= n <= end for n, _ in added):
                reasons.append('the Sttark working rules change: sessions work differently')
        elif path.startswith('Resources/hooks/') and path.endswith(('.py', '.sh')) and kind == 'A':
            reasons.append('a new hook or command: `%s`' % path)
        elif path == 'Resources/hooks/install-hooks.py':
            added, removed = diff_lines(base, head, path)
            cmds = sorted(set(re.findall(r'\.local/bin/(claude-[\w-]+)', ' '.join(l for _, l in added)))
                          - set(re.findall(r'\.local/bin/(claude-[\w-]+)', ' '.join(removed))))
            if cmds:
                reasons.append('a new command: %s' % ', '.join('`%s`' % c for c in cmds))
        elif path == 'Info.plist':
            added, _ = diff_lines(base, head, path)
            if any('UsageDescription' in l for _, l in added):
                reasons.append('a new macOS permission prompt (`Info.plist`)')
        elif path == 'README.md':
            added, _ = diff_lines(base, head, path)
            heads = [l[3:].strip() for _, l in added if l.startswith('## ')]
            rows = [l for _, l in added if re.match(r'^\| [^|]+ \| \[[^\]]+\]\(#', l)]
            if heads:
                reasons.append('the README gains a section: %s' % ', '.join('"%s"' % h for h in heads))
            elif rows:
                reasons.append('the README gains a row in its list of what the Kit does')
    return has_note, reasons


NONE = re.compile(r"^\s*What's new:\s*none\b", re.I | re.M)


def gh(*args, **kw):
    return subprocess.run(['gh'] + list(args), capture_output=True, text=True, **kw)


def ask():
    """On a pull request: when the change looks like something people notice and adds no note, one comment that
    asks for one, and a neutral check. Otherwise the comment goes and the check passes. Never fails the run."""
    base, head = os.environ['BASE'], os.environ['HEAD']
    repo, pr = os.environ['REPO'], os.environ['PR']
    has_note, reasons = needs(base, head)
    declined = NONE.search(os.environ.get('BODY') or '')
    asking = bool(reasons) and not has_note and not declined
    for r in reasons:
        print('looks user-facing: ' + r)
    print('note added' if has_note else 'declined in the description' if declined else 'asking' if asking else 'no note needed')

    if asking:
        title = 'A note may be needed'
        summary = ('This change looks like something people see, or do differently:\n\n'
                   + '\n'.join('- ' + r for r in reasons)
                   + '\n\nIf people notice it, add a note in `whats-new/` (see AGENTS.md, "What\'s new notes"). '
                   'If it is a bug fix or an internal change, add a line to the description: '
                   '`What\'s new: none, <why>`. This check does not fail.')
    else:
        title = ('Note added' if has_note else 'Not needed: ' + declined.group(0).strip() if declined
                 else 'Not needed')
        summary = title + '.'
    # a neutral check asks; it never blocks a merge
    r = gh('api', '-X', 'POST', 'repos/%s/check-runs' % repo, '-f', 'name=' + CHECK_NAME, '-f', 'head_sha=' + head,
           '-f', 'status=completed', '-f', 'conclusion=' + ('neutral' if asking else 'success'),
           '-f', 'output[title]=' + title, '-f', 'output[summary]=' + summary)
    if r.returncode:
        print('::warning::could not post the check: ' + (r.stderr or r.stdout).strip()[:200])
    # one comment, kept up to date; it goes when the question is answered
    r = gh('api', 'repos/%s/issues/%s/comments' % (repo, pr), '--paginate',
           '--jq', '.[] | select(.body | contains("%s")) | .id' % MARK)
    ids = r.stdout.split()
    if asking:
        body = MARK + "\n**What's new note?** " + summary
        if ids:
            r = gh('api', '-X', 'PATCH', 'repos/%s/issues/comments/%s' % (repo, ids[0]), '-f', 'body=' + body)
        else:
            r = gh('api', '-X', 'POST', 'repos/%s/issues/%s/comments' % (repo, pr), '-f', 'body=' + body)
        if r.returncode:
            print('::warning::could not comment: ' + (r.stderr or r.stdout).strip()[:200])
        print('::warning::' + summary.split('\n')[0] + ' ' + '; '.join(reasons))
    else:
        for i in ids:
            gh('api', '-X', 'DELETE', 'repos/%s/issues/comments/%s' % (repo, i))
    return 0


def ste(path):
    """The Kit's own Simplified Technical English check (Resources/hooks/working-rules-hook.py) on the note's
    words, with Haiku. Judgment, so it is run by hand before a pull request, not in CI."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('rules', os.path.join(ROOT, 'Resources/hooks/working-rules-hook.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    n = parse(path)
    text = '\n\n'.join([n['title'], n['lead']] + n['points'])
    answer = m.ask(text)
    print(answer)
    return 0 if answer.strip().upper().rstrip('.') == 'OK' else 1


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'check':
        return check([os.path.abspath(a) for a in argv[2:]])
    if cmd == 'build' and len(argv) == 3:
        return build(os.path.abspath(argv[2]))
    if cmd == 'needs' and len(argv) == 4:
        has_note, reasons = needs(argv[2], argv[3])
        print('note added' if has_note else 'no note')
        for r in reasons:
            print(r)
        return 0
    if cmd == 'ask':
        return ask()
    if cmd == 'ste' and len(argv) == 3:
        return ste(os.path.abspath(argv[2]))
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
