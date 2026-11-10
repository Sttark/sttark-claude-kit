#!/usr/bin/python3
"""Claude Code hook (SubagentStop): blocks an implementer that changed UI files and reports no page-check
output. Installed by the Sttark Claude Kit app only while the Orchestrator switch is on ("orchestrator": true
in the app's state.json), and it does nothing when the switch is off.

It acts only when the subagent is an `implementer` and the repo is a Sttark app repo (app_kind in
app-rules-hook.py). It reads the subagent's transcript for the files it changed (Edit, Write, MultiEdit and
NotebookEdit calls). If a UI file changed and the report has no page-check output, it blocks once and says
what to run. When stop_hook_active is true it always allows, so it never blocks twice.

The report is last_assistant_message, the last assistant text in the transcript, and the message of a
SubagentHandback call (Claude Code 2.1.271 and later deliver the report through that tool).

A git diff is not used as a second source: it would also list changes that were there before the subagent
started, and block for them. Any error is logged and the subagent is allowed to finish. No model calls.
Logged to ~/Library/Logs/sttark-claude-kit.log, with lines starting `uicheck`.
STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and a test log.
"""
import importlib.util, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')

# ---- The rules. Change them here. ----
AGENT = 'implementer'
EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
UI_EXT = ('.tsx', '.jsx', '.vue', '.svelte', '.astro', '.html', '.css', '.scss', '.sass', '.less')   # always UI
CODE_EXT = ('.ts', '.js')                             # UI only inside one of CODE_DIRS
CODE_DIRS = ('component', 'components', 'ui')
ASSET_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.avif', '.ico', '.woff', '.woff2', '.ttf', '.otf',
             '.eot', '.mp4', '.webm')
ASSET_DIR = 'public'                                  # image, font and video files under it are UI
NOT_UI_EXT = ('.md', '.py')
NOT_UI_NAME = re.compile(r'\.(test|spec)\.[a-z]+$|(^|/)(__tests__|tests?|e2e|api|server|db|models)/|'
                         r'(^|/)route\.(ts|js)$', re.I)
# A page check ran when the report shows a result line of page-check/check-pages.mjs ("Every page passes (N page
# views)", "N problems (... ) on M page views", "No page changed; nothing to check.") near the script's name.
# Generic words such as ok, pass, fail or error do not count.
CHECK_NAME = re.compile(r'page[- ]check|check-pages', re.I)
CHECK_RESULT = re.compile(r'Every page passes|\d+ problems? \(|nothing to check|page views', re.I)
NEAR = 4                                              # lines around the script name that may hold the result
SET_UP = ('scripts/page-check.mjs', '*/scripts/page-check.mjs', 'page-check/check-pages.mjs')


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'uicheck ' + line + '\n')
    except OSError:
        pass


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def is_ui(path):
    p = path.replace('\\', '/')
    low = p.lower()
    if low.endswith(NOT_UI_EXT) or NOT_UI_NAME.search(low):
        return False
    if low.endswith(UI_EXT):
        return True
    parts = low.split('/')[:-1]
    if ASSET_DIR in parts and low.endswith(ASSET_EXT):
        return True
    return low.endswith(CODE_EXT) and any(d in parts for d in CODE_DIRS)


def read_transcript(path):
    """(changed file paths in order, report texts) from a subagent transcript (JSON lines). An edit counts only
    when its tool result was not an error (denied, or old_string not found)."""
    edits, failed_ids, texts, last_text = [], set(), [], ''
    for line in open(path):
        try:
            msg = json.loads(line).get('message') or {}
        except ValueError:
            continue
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if msg.get('role') == 'user':
                if b.get('type') == 'tool_result' and b.get('is_error'):
                    failed_ids.add(b.get('tool_use_id'))
            elif msg.get('role') != 'assistant':
                continue
            elif b.get('type') == 'tool_use':
                inp = b.get('input') or {}
                if b.get('name') in EDIT_TOOLS:
                    f = inp.get('file_path') or inp.get('notebook_path')
                    if f:
                        edits.append((b.get('id'), f))
                elif b.get('name') == 'SubagentHandback' and inp.get('message'):
                    texts.append(str(inp['message']))
            elif b.get('type') == 'text' and b.get('text'):
                last_text = b['text']
    files = []
    for i, f in edits:
        if (i is None or i not in failed_ids) and f not in files:
            files.append(f)
    if last_text:
        texts.append(last_text)
    return files, texts


def has_check_output(texts):
    for t in texts:
        lines = t.splitlines()
        for i, ln in enumerate(lines):
            if CHECK_NAME.search(ln) and CHECK_RESULT.search('\n'.join(lines[max(0, i - NEAR):i + NEAR + 1])):
                return True
        for k, blk in enumerate(t.split('```')):
            if k % 2 and CHECK_NAME.search(blk) and CHECK_RESULT.search(blk):
                return True
    return False


def script_in(cwd):
    try:
        r = subprocess.run(['git', '-C', cwd, 'ls-files', '--cached', '--others', '--exclude-standard', '--', *SET_UP],
                           capture_output=True, text=True, timeout=3)
        found = r.stdout.split()
    except Exception:
        found = []
    return found[0] if found else 'scripts/page-check.mjs'


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return log('error bad input, allowed')
    if not isinstance(data, dict):
        return log('error bad input, allowed')
    try:
        if data.get('agent_type') != AGENT:
            return
        if not load('working-rules-hook').orchestrator_on():
            return
        cwd = data.get('cwd') or os.getcwd()
        kind = load('app-rules-hook').app_kind(cwd)
        if not kind or kind[0] != 'app':
            return
        if data.get('stop_hook_active'):
            return log('allow, already blocked once')
        files, texts = [], []
        tp = data.get('agent_transcript_path')
        if tp:
            files, texts = read_transcript(os.path.expanduser(tp))
        last = data.get('last_assistant_message')
        if isinstance(last, str) and last:
            texts.append(last)
        ui = [f for f in files if is_ui(os.path.relpath(f, cwd) if os.path.isabs(f) else f)]
        if not ui:
            return
        if has_check_output(texts):
            return log('allow, page-check output found (%d UI files)' % len(ui))
        names = [os.path.basename(f) for f in ui[:5]]
        reason = ('You changed UI files (%s%s) and your report has no page-check output. Run page-check (%s) '
                  'and paste its output, then finish.' % (', '.join(names), ', ...' if len(ui) > 5 else '',
                                                           script_in(cwd)))
        print(json.dumps({'decision': 'block', 'reason': reason}))
        log('block, %d UI files: %s' % (len(ui), ', '.join(names)))
    except Exception as e:
        log('error %s: %s, allowed' % (type(e).__name__, str(e)[:160]))


if __name__ == '__main__':
    main()
