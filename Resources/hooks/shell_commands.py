"""Shared by the Orchestrator hooks inline-guard.py and browser-lock.py (no hook entry of its own).
The app copies it next to them. Plain functions, Python 3.9, no third-party imports.

commands(cmd): the commands in a Bash command line, split quote-aware.
strip_prefix(part): one command without the words in front that only wrap it. The prefixes are
VAR=x, timeout <n> and gtimeout <n> (with options like -k 5), time, env (with options), nohup, exec,
sudo (with options like -E or -u user), command (with -p) and builtin, nice (with -n N), and the shell keywords if, then, else, elif, do,
while, until, { } and ! at the start of a command.
Nested commands: $( ), backticks, `bash -c "..."`, `eval <command>`, `bash <<< 'cmd'`, and the body of a heredoc fed to a shell
(`bash <<EOF`, `cat <<EOF | sh`). The body of a heredoc fed to any other command is data, not commands.
"""
import os, re, shlex

PREFIX_RE = re.compile(r'^(?:(?:\w+=\S*|sudo(?:\s+-[ugCDhpRrT]\s+\S+|\s+-\S+)*|time|env(?:\s+-\S+)*|nohup|exec|command(?:\s+-p)?|builtin|if|then|else|elif|do|while|until|\{|\}|!|nice(?:\s+-n\s*\d+|\s+-\d+)*|g?timeout\s+(?:-\S+\s+(?:(?=\d\S*\s+\d)\S+\s+)?)*\d\S*)\s+)*')

SHELLS = {'bash', 'sh', 'zsh'}
NOTED = []   # one parse line per hook run
HEREDOC_RE = re.compile(r'''<<(-?)\s*(?:'([^']*)'|"([^"]*)"|\\?(\w+))''')
NESTED_RE = re.compile(r'\$\(([^()]*)\)|`([^`]*)`')


def spaced(s):
    """The text with spaces around `<<<`, `<<` and `<<-` outside quotes, so `bash<<<"x"` splits into words."""
    out, quote, i = [], None, 0
    while i < len(s):
        c = s[i]
        if quote:
            out.append(c)
            if c == '\\' and quote == '"' and i + 1 < len(s):
                out.append(s[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c == '\\' and i + 1 < len(s):
            out.append(c + s[i + 1])
            i += 1
        elif c in '\'"':
            quote = c
            out.append(c)
        elif s.startswith('<<<', i):
            out.append(' <<< ')
            i += 2
        elif s.startswith('<<', i):
            out.append(' << ')
            i += 1
        else:
            out.append(c)
        i += 1
    return ''.join(out)


def heredocs(cmd):
    """(the command without heredoc bodies, [(the line that opens it, its body)]). A `<<` inside quotes, a `<<<`, and
    a heredoc with no end line are left alone."""
    lines, out, found, i = cmd.split('\n'), [], [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        delims, quote, k = [], None, 0
        while k < len(line):
            c = line[k]
            if quote:
                if c == '\\' and quote == '"':
                    k += 1
                elif c == quote:
                    quote = None
            elif c == '\\':
                k += 1
            elif c in '\'"':
                quote = c
            elif line.startswith('<<', k) and line[k + 2:k + 3] != '<' and line[k - 1:k] != '<':
                m = HEREDOC_RE.match(line, k)
                if m:
                    delims.append(m.group(2) if m.group(2) is not None else m.group(3) if m.group(3) is not None else m.group(4))
                    k = m.end() - 1
            k += 1
        for d in delims:
            end = next((j for j in range(i, len(lines)) if lines[j].strip() == d), None)
            if end is None:
                continue
            found.append((line, '\n'.join(lines[i:end])))
            i = end + 1
    return '\n'.join(out), found


def commands(cmd, note=None, depth=0):
    """The commands in a Bash command line, as strings. Splits at ; & | and new lines, and at ( ) and backticks
    (which open a nested command), but not inside quotes ('...', "...", $'...'). A nested command in double
    quotes ($(...) or backticks) and the text after `bash -c`, `sh -c` or `zsh -c` are split too.
    `note` is called once per run with a text when a quote is left open (the command is then not split)."""
    if not isinstance(cmd, str) or depth > 4:
        return []
    cmd, bodies = heredocs(cmd) if '<<' in cmd else (cmd, [])
    out, buf, quote, i, n = [], [], None, 0, len(cmd)

    def end():
        seg = ''.join(buf).strip()
        buf.clear()
        if seg:
            out.append(seg)
    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == '\\' and quote != "'" and i + 1 < n:
                buf.append(cmd[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c == '\\' and i + 1 < n:
            buf.append(c + cmd[i + 1])
            i += 1
        elif c == "'" or c == '"':
            quote = c
            buf.append(c)
        elif c == '$' and cmd[i + 1:i + 2] == "'":
            quote = "'"
            buf.append("$'")
            i += 1
        elif c in ';|\n(`)' or (c == '&' and cmd[i - 1:i] not in ('>', '<') and cmd[i + 1:i + 2] != '>'):
            end()
        else:
            buf.append(c)
        i += 1
    end()
    if quote and depth == 0 and not NOTED:   # an open quote: the command is not split, and the call is let through
        NOTED.append(1)
        if note:
            note(f'parse  unbalanced quote: {cmd[:60]!r}')
    more = []
    for head, body in bodies:   # fed to a shell (not `sh -c`): the body is commands; any other command: data
        for part in commands(head, None, depth + 1):
            try:
                w = shlex.split(spaced(strip_prefix(part)))
            except ValueError:
                continue
            if w and os.path.basename(w[0]) in SHELLS and not any(re.match(r'^-\w*c$', x) for x in w[1:]):
                more += commands(body, note, depth + 1)
                break
    for seg in out:
        for m in NESTED_RE.finditer(seg):
            more += commands(m.group(1) or m.group(2), note, depth + 1)
        try:
            words = shlex.split(spaced(strip_prefix(seg)))
        except ValueError:
            continue
        if words and os.path.basename(words[0]) == 'eval' and len(words) > 1:
            more += commands(' '.join(words[1:]), note, depth + 1)
        if words and os.path.basename(words[0]) in SHELLS and '<<<' in words[1:-1]:   # bash <<< 'cmd'
            more += commands(words[words.index('<<<') + 1], note, depth + 1)
        if words and os.path.basename(words[0]) in SHELLS:
            for k, w in enumerate(words[1:-1], 1):
                if re.match(r'^-\w*c$', w):
                    more += commands(words[k + 1], note, depth + 1)
                    break
    return out + more


def strip_prefix(part):
    """The command with its wrapping prefixes (see PREFIX_RE) taken off."""
    return PREFIX_RE.sub('', part.strip().lstrip('('))
