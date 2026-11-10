#!/usr/bin/python3
"""Claude Code hook: Sttark rules for subagents. Installed by the Sttark Claude Kit app only while the
Orchestrator switch is on ("orchestrator": true in the app's state.json), and it does nothing when the
switch is off.

Subagents do not get the UserPromptSubmit working rules. On SubagentStart this hook adds the worker rules
to the subagent's context: the rules about how to do the work. The rules about how to talk to the person
(STE replies, the asks table, the two-line plan, answer first, shortest reply, end of turn, the manager
rule) are left out, because a subagent's report goes to the main agent, not to the person.

The rules come from RULES in working-rules-hook.py, picked by their opening words (WORKER below), so a
change to the rules text does not break this hook. A rule that is not found is logged and skipped. The
hook never fails a subagent: any error is logged and nothing is added.

In a Sttark app repo (the same test app-rules-hook.py uses) it also adds a pointer to the saved app
chapters (app-rules/chapters.json in the kit folder) and the page-check line. The chapters are not copied.

It makes no model calls. Logged to ~/Library/Logs/sttark-claude-kit.log, with lines starting `subrules`.
STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and a test log.
"""
import importlib.util, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')

LEAD = 'Sttark worker rules (from Sttark Claude Kit), for this subagent:'
MARKER = 'Sttark context: present.'

# The worker rules: the opening words of each rule in RULES, and (when the wording must change for a
# subagent) the text to use in its place.
WORKER = [
    ("- Don't know it?", None),
    ('- Repo work:', None),
    ('- When the person gives an example', None),
    ('- UI and layout:', None),
    ('- Asana tasks:', None),
    ('- No em-dashes', '- No em-dashes or double hyphens in text a person reads (reports, comments, commit '
                       'messages, docs). Code, CLI flags and file syntax are exempt.'),
]

APP = ('Sttark app repo: the app rules (the Apps chapters of the Sttark Brand and App Guidelines) are saved in '
       '%s. Read the chapters that apply to your task before you change UI or pages. If the file is missing, '
       'read them with the Sttark Workrouter docs_read tool. Run page-check before you report UI work, and '
       'include its output.')


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'subrules ' + line + '\n')
    except OSError:
        pass


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def worker_rules(rules_text):
    """The worker rules found in the rules text, as lines. Logs each one that is missing."""
    import re
    rules = re.split(r'\n(?=- )', rules_text)
    out = []
    for start, text in WORKER:
        found = next((r for r in rules if r.startswith(start)), None)
        if found is None:
            log('missing rule, skipped: %s' % start)
            continue
        out.append(text or found)
    return out


def in_app_repo(cwd):
    """True in a Sttark app repo: the test app-rules-hook.py uses."""
    try:
        kind = load('app-rules-hook').app_kind(cwd)
    except Exception as e:
        log('app repo test failed: %s: %s' % (type(e).__name__, str(e)[:120]))
        return False
    return bool(kind) and kind[0] == 'app'


def build(cwd, rules_text):
    parts = [LEAD, '\n'.join(worker_rules(rules_text)), MARKER]
    app = in_app_repo(cwd)
    if app:
        parts.append(APP % os.path.join(KIT, 'app-rules', 'chapters.json'))
    return '\n\n'.join(parts), app


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    agent = data.get('agent_type') or '?'
    try:
        work = load('working-rules-hook')
        if not work.orchestrator_on():
            return
        text, app = build(data.get('cwd') or os.getcwd(), work.RULES)
    except Exception as e:
        return log('%s error %s: %s' % (agent, type(e).__name__, str(e)[:160]))
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SubagentStart', 'additionalContext': text}}))
    log('%s added worker rules%s' % (agent, ' and app pointer' if app else ''))


if __name__ == '__main__':
    main()
