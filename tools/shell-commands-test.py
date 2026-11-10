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
print(f'\n{len(passed)} passed, {len(failed)} failed')
sys.exit(1 if failed else 0)
