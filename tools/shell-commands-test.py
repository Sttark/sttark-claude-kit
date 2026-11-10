"""Test the shared command splitter (Resources/hooks/shell_commands.py). No files are touched.
Run: /usr/bin/python3 tools/shell-commands-test.py"""
import importlib.util, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('shell_commands', os.path.join(REPO, 'Resources', 'hooks', 'shell_commands.py'))
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


check('split at ; && | and new line', sc.commands('a; b && c | d\ne') == ['a', 'b', 'c', 'd', 'e'])
check('quotes are not split', sc.commands('git commit -m "a; b | c"') == ['git commit -m "a; b | c"'])
check('$ quote is not split', sc.commands("echo $'a;b'") == ["echo $'a;b'"])
check('redirect & is not a split', sc.commands('a 2>&1 | b') == ['a 2>&1', 'b'])
check('parens nest', 'make' in sc.commands('(make)'))
check('$( ) nests', 'make' in sc.commands('echo $(make)'))
check('backticks nest', 'make' in sc.commands('echo `make`'))
check('bash -c nests', 'make build' in sc.commands('bash -c "make build"'))
check('prefix then bash -c nests', 'make' in sc.commands("timeout 5 sudo -E bash -c 'make'"))
check('timeout then bash -c nests', 'make' in sc.commands('timeout 5 bash -c "make"'))
check('gtimeout then sh -c nests', 'claude-window go x' in sc.commands('gtimeout 5 sh -c "claude-window go x"'))
check('non-string gives []', sc.commands(None) == [])
notes = []
check('unbalanced quote: no split', sc.commands('echo "open; make', notes.append) == ['echo "open; make'])
check('unbalanced quote: noted once', len(notes) == 1 and notes[0].startswith('parse'))
for cmd, want in [('timeout 600 npm test', 'npm test'), ('gtimeout -k 5 60 swift build', 'swift build'),
                  ('command make build', 'make build'), ('FOO=1 npm test', 'npm test'),
                  ('sudo -E make install', 'make install'), ('env -i PATH=/bin npm ci', 'npm ci'),
                  ('time nohup exec ls', 'ls'), ('make', 'make'),
                  ('echo timeout make build', 'echo timeout make build'), ('timeout npm test', 'timeout npm test')]:
    check(f'prefix: {cmd}', sc.strip_prefix(cmd) == want)

def cmds(c):
    return [sc.strip_prefix(x) for x in sc.commands(c)]


check('keyword if/then', 'git push' in cmds('if true; then git push; fi') and 'git push' in cmds('if git push; then echo; fi'))
check('keywords else, elif, while, until, do', all('X' in cmds(c) for c in ('if a; then b; else X; fi', 'if a; then b; elif c; then d; else X; fi',
      'while X; do b; done', 'until X; do b; done', 'for i in 1; do X; done')))
check('keywords { } and !', 'X' in cmds('{ X; }') and 'X' in cmds('! X') and 'X' in cmds('{ X ; }'))
check('nice and builtin', 'X' in cmds('nice -n 5 X') and 'X' in cmds('nice X') and 'X' in cmds('builtin X') and 'X' in cmds('nice -10 X'))
check('a word that only starts like a keyword is not stripped', cmds('iffy x') == ['iffy x'] and cmds('done_it') == ['done_it'])
check('eval with double quotes', 'make build' in cmds('eval "make build"'))
check('eval with single quotes', 'make build' in cmds("eval 'make build'"))
check('eval with words', 'make build' in cmds('eval make build'))
check('heredoc fed to bash is commands', 'make' in cmds('bash <<EOF\nmake\nEOF'))
check('heredoc fed to sh, quoted marker', 'make' in cmds("sh <<'EOF'\nmake\nEOF"))
check('heredoc piped to a shell', 'make' in cmds("cat <<EOF | bash\nmake\nEOF"))
check('heredoc piped to sudo bash', 'make' in cmds("cat <<EOF | sudo bash\nmake\nEOF"))
check('heredoc fed to another command is data', 'make' not in cmds("git commit -F - <<'EOF'\nmake\nEOF"))
check('heredoc <<- with tabs', 'make' not in cmds("cat <<-EOF\n\tmake\n\tEOF") and 'make' in cmds("bash <<-EOF\n\tmake\n\tEOF"))
check('commands on the line that opens a heredoc are checked', 'git push x' in cmds("git commit -F - <<'EOF' && git push x\nmsg\nEOF"))
check('commands after the heredoc end are checked', 'git push x' in cmds("cat <<EOF\nmsg\nEOF\ngit push x"))
check('heredoc with no end line: nothing hidden', 'make' in cmds('cat <<EOF\nmake'))
check('<< inside quotes is not a heredoc', 'git push x' in cmds('echo "<<EOF"\ngit push x\nEOF'))
check('here-string is not a heredoc', 'git push x' in cmds('cat <<< hi\ngit push x'))
check('heredoc inside $( ) in quotes is data', 'git push x' not in cmds('git commit -m "$(cat <<\'EOF\'\nmsg\ngit push x\nEOF\n)"'))
check('two heredocs on one line: both bodies are data', cmds("cat <<A <<B\none\nA\ntwo\nB\nmake") == ['cat <<A <<B', 'make'])
check('here-string to bash', 'git push x' in cmds("bash <<< 'git push x'") and 'git push x' in cmds('sh <<< "git push x"'))
check('here-string to another command is data', 'git push x' not in cmds("cat <<< 'git push x'"))
check('sudo -u user and command -p', cmds('sudo -u me make') == ['make'] and cmds('sudo -E -u me make') == ['make'] and cmds('command -p make') == ['make'])
for c in ("bash <<<'git push x'", 'bash <<<"git push x"', "bash<<<'git push x'", 'sh<<<"git push x"', "bash <<< 'git push x'", "bash<< 'EOF'\ngit push x\nEOF", "bash<<EOF\ngit push x\nEOF", "cat<<EOF|bash\ngit push x\nEOF"):
    check('shell input without spaces: ' + c.replace('\n', ' / '), 'git push x' in cmds(c))
for c in ("grep y<<<'git push x'", "cat<<<'git push x'", "cat<<EOF\ngit push x\nEOF", "git commit -F -<<EOF\ngit push x\nEOF"):
    check('no-space form to a non-shell is data: ' + c.replace('\n', ' / '), 'git push x' not in cmds(c))
print(f'\n{len(passed)} passed, {len(failed)} failed')
sys.exit(1 if failed else 0)
