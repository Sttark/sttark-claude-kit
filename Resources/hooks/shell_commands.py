"""Shared by the Orchestrator hooks inline-guard.py and browser-lock.py (no hook entry of its own).
The app copies it next to them. Plain functions, Python 3.9, no third-party imports.

commands(cmd): the commands in a Bash command line, split quote-aware.
strip_prefix(part): one command without the words in front that only wrap it. The prefixes are
VAR=x, timeout <n> and gtimeout <n> (with options like -k 5), time, env (with options), nohup, exec,
sudo (with options like -E) and command.
"""
import os, re, shlex

PREFIX_RE = re.compile(r'^(?:(?:\w+=\S*|sudo(?:\s+-\S+)*|time|env(?:\s+-\S+)*|nohup|exec|command|g?timeout\s+(?:-\S+\s+(?:(?=\d\S*\s+\d)\S+\s+)?)*\d\S*)\s+)*')

SHELLS = {'bash', 'sh', 'zsh'}
NOTED = []   # one parse line per hook run
NESTED_RE = re.compile(r'\$\(([^()]*)\)|`([^`]*)`')


def commands(cmd, note=None, depth=0):
    """The commands in a Bash command line, as strings. Splits at ; & | and new lines, and at ( ) and backticks
    (which open a nested command), but not inside quotes ('...', "...", $'...'). A nested command in double
    quotes ($(...) or backticks) and the text after `bash -c`, `sh -c` or `zsh -c` are split too.
    `note` is called once per run with a text when a quote is left open (the command is then not split)."""
    if not isinstance(cmd, str) or depth > 4:
        return []
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
    for seg in out:
        for m in NESTED_RE.finditer(seg):
            more += commands(m.group(1) or m.group(2), note, depth + 1)
        try:
            words = shlex.split(strip_prefix(seg))
        except ValueError:
            continue
        if words and os.path.basename(words[0]) in SHELLS:
            for k, w in enumerate(words[1:-1], 1):
                if re.match(r'^-\w*c$', w):
                    more += commands(words[k + 1], note, depth + 1)
                    break
    return out + more


def strip_prefix(part):
    """The command with its wrapping prefixes (see PREFIX_RE) taken off."""
    return PREFIX_RE.sub('', part.strip().lstrip('('))
