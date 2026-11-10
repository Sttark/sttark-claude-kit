#!/usr/bin/python3
"""Claude Code hook: the production guard. Installed by the Sttark Claude Kit app only while the Orchestrator
switch is on ("orchestrator": true in the app's state.json), and it does nothing when the switch is off.
It applies to the main thread and to every subagent. It makes no model calls.

PreToolUse denies these actions (never "ask": the kit's Bypass hook approves ask prompts), each with a name:
  push-main  `git push` that targets main or master (a refspec such as main, HEAD:main, +main, refs/heads/main,
             :main; a push with no refspec while the current branch is main or master; --all; --mirror)
  merge      `gh pr merge`, a `gh api` call that PUTs a pull's merge endpoint (or runs mergePullRequest), and an
             MCP tool whose name ends in merge_pull_request, mergePullRequest, pull_request_merge or enable_auto_merge
  deploy     DEPLOY below (gh workflow run, a gh api workflow dispatches call, vercel --prod, fly deploy, npm publish, terraform apply, ...)
  migrate    MIGRATE below (prisma migrate deploy, rails db:migrate, alembic upgrade, ...)
A command with --dry-run is let through. Commands are split with shell_commands.py (quote-aware, same prefixes),
so a commit message that names `git push origin main` is not a push. The body of a heredoc is data, except when a
shell reads it (`bash <<EOF`); the commands on the line that opens it are checked. `eval` and shell keywords (if, then, do)
are looked through.

UserPromptSubmit: a prompt that is exactly `approve <action>` (push-main, merge, deploy, migrate, pass2) records
the approval for the session. It covers one denied action within 10 minutes (APPROVAL_SECONDS); using it removes
it. Subagents share the session id, so the person's approval in the main thread covers an agent's action.

Pass 1 of the two-pass specialists (TWO_PASS agent types) may not write: an MCP tool is denied until `approve pass2` unless its
name has a READS word and no STRONG word (fail closed). The first allowed-by-approval write of an agent after that takes the approval and
records pass2_agent; that agent may write until it stops (SubagentStop frees it).

A denial also saves `prod_wait` on the session in state.json; effort-hook.py --track shows it under "Waiting on
you" as "Approval needed: <action>" while the session is not being watched. Approving clears it.
Everything is kept per session in state.json under "approvals" and "pass2_agent", under the shared lock.
Any error is logged (lines start `prod`) and the call is let through. STTARK_KIT_DIR and STTARK_KIT_LOG point it
at a test folder; STTARK_PROD_NOW sets the clock (tests use it).
"""
import fcntl, json, os, re, shlex, subprocess, sys, time
from contextlib import contextmanager

DIR = os.environ.get('STTARK_KIT_DIR') or os.path.expanduser('~/Library/Application Support/SttarkClaudeKit')
STATE = os.path.join(DIR, 'state.json')
LOG = os.environ.get('STTARK_KIT_LOG') or os.path.expanduser('~/Library/Logs/sttark-claude-kit.log')

APPROVAL_SECONDS = 600
KEEP = 86400
ACTIONS = ['push-main', 'merge', 'deploy', 'migrate', 'pass2']
PROTECTED = ('main', 'master')

# Deploys: (program, words that must come first among the positional words, flags of which one must be present).
# Add a line here. A program that wraps another (npx, bundle exec, pnpm dlx) is looked through.
DEPLOY = [
    ('gh', ('workflow', 'run'), ()), ('gh', ('workflow', 'dispatch'), ()),
    ('vercel', (), ('--prod', '--production')),
    ('netlify', ('deploy',), ('--prod', '-p')),
    ('fly', ('deploy',), ()), ('flyctl', ('deploy',), ()),
    ('firebase', ('deploy',), ()),
    ('railway', ('up',), ()),
    ('heroku', ('deploy',), ()), ('heroku', ('container:release',), ()),
    ('heroku', ('pipelines:promote',), ()), ('heroku', ('releases:rollback',), ()),
    ('npm', ('publish',), ()), ('pnpm', ('publish',), ()), ('yarn', ('publish',), ()), ('bun', ('publish',), ()),
    ('terraform', ('apply',), ()), ('tofu', ('apply',), ()),
    ('kubectl', ('apply',), ()), ('kubectl', ('rollout',), ()),
]
# Script deploys: (programs, name starts, needs `run`; None: `run` or not). `npm run deploy:prod`, `make release`, `just deploy`.
SCRIPTS = [(('npm',), ('deploy', 'release', 'publish'), True),
           (('pnpm', 'yarn', 'bun'), ('deploy', 'release', 'publish'), None),
           (('make',), ('deploy', 'release', 'publish'), False),
           (('just', 'task'), ('deploy', 'release'), False)]
DEPLOY_ANY = ('gcloud', 'aws')   # any positional word `deploy` (gcloud run deploy, aws cloudformation deploy)

MIGRATE = [
    ('prisma', ('migrate', 'deploy')), ('prisma', ('db', 'push')),
    ('rails', ('db:migrate',)), ('rake', ('db:migrate',)),
    ('knex', ('migrate:latest',)), ('sequelize', ('db:migrate',)), ('sequelize-cli', ('db:migrate',)),
    ('alembic', ('upgrade',)), ('drizzle-kit', ('push',)),
    ('supabase', ('db', 'push')), ('flyway', ('migrate',)),
]

# Pass 1 of these agent types never writes, and the guard fails closed. An MCP tool is allowed in pass 1 only when
# the words of the last part of its name (split at `_`, `-` and capitals, lowercase) have a READS word and no STRONG
# word, or its name is in READ_OK. Everything else is denied until `approve pass2`: asana_get_task passes,
# asana_duplicate_task, comment and get_project_set (`set` is a write word) do not. A name that is unknown is
# a write. READ_OK is compared after the name is made lowercase with `_` between words (RunQuery, run-query).
TWO_PASS = {'asana-update-specialist', 'strategy-specialist', 'onshape-cleanup-specialist', 'supplier-specialist'}
STRONG = {'create', 'update', 'delete', 'remove', 'send', 'post', 'reply', 'forward', 'upload', 'trash', 'untrash',
          'edit', 'write', 'set', 'add', 'insert', 'replace', 'archive', 'assign', 'unassign', 'rename', 'patch',
          'import', 'complete', 'batch', 'execute', 'submit', 'cancel', 'void', 'refund', 'charge', 'pay', 'merge',
          'publish', 'deploy', 'apply', 'approve', 'reject', 'close', 'reopen', 'move', 'log', 'take', 'return',
          'save', 'restore', 'purge', 'wipe', 'reset', 'sync', 'trigger', 'start', 'stop', 'notify', 'grant',
          'revoke', 'transfer', 'toggle', 'enable', 'disable', 'increment', 'decrement', 'adjust', 'restock',
          'append', 'upsert', 'copy', 'duplicate', 'modify', 'clear', 'fork', 'mark', 'label', 'unlabel', 'attach',
          'detach', 'lock', 'unlock', 'subscribe', 'unsubscribe', 'invite', 'share', 'accept', 'decline',
          'resolve', 'schedule', 'book', 'reserve', 'propose', 'run', 'ship', 'checkin', 'checkout'}
# Words that are often nouns (get_order_status, get_pull_request). They never deny a name that has a READS word; a
# name with no READS word is denied anyway. Listed so the choice is visible.
AMBIGUOUS = {'order', 'pull', 'push', 'comment', 'link', 'unlink', 'pin', 'unpin', 'star', 'follow', 'unfollow',
             'release', 'commit'}
READS = {'get', 'list', 'search', 'read', 'query', 'fetch', 'find', 'show', 'view', 'status', 'whoami', 'schema',
         'report', 'history', 'preview', 'estimate', 'count', 'check', 'describe', 'lookup', 'ask', 'browse', 'info',
         'diff', 'quote', 'download', 'validate', 'calculate', 'summarize', 'compare', 'analyze'}
# Read-only tools whose names have no read word, by the servers' own descriptions (lookups, reports, previews).
READ_OK = {'run_query', 'org_structure', 'business_days', 'meetings_today', 'circle_meetings_checklist',
           'order_reprint_quote', 'order_design_files', 'die_template',
           'order_due_date_preview', 'order_roll_estimate'}   # these two have the write word `order`
WORD_RE = re.compile(r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+')

# git options that take a value in the next word, before the subcommand and after `push`
GIT_VALUE = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path'}
PUSH_VALUE = {'-o', '--push-option', '--receive-pack', '--exec', '--repo'}
WRAPPERS = {'npx', 'bunx', 'pnpx'}


def now():
    try:
        return float(os.environ.get('STTARK_PROD_NOW') or time.time())
    except ValueError:
        return time.time()


def log(line):
    try:
        with open(LOG, 'a') as f:
            f.write(time.strftime('%F %T ') + 'prod ' + line + '\n')
    except OSError:
        pass

try:   # the shared command splitter, next to this file; if it cannot be loaded, the hook logs and allows
    import importlib.util
    _spec = importlib.util.spec_from_file_location('shell_commands', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shell_commands.py'))
    SC = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(SC)
    SC_ERR = None
except Exception as _e:
    SC, SC_ERR = None, _e


@contextmanager
def state():
    """The app's shared state file, under the same lock the app and the other hooks use."""
    os.makedirs(DIR, exist_ok=True)
    with open(STATE + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            s = json.load(open(STATE))
        except (OSError, ValueError):
            s = {}
        if not isinstance(s, dict):
            s = {}
        yield s
        tmp = STATE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, STATE)


def switch_on():
    try:
        return json.load(open(STATE)).get('orchestrator') is True
    except (OSError, ValueError, AttributeError):
        return False


# ---- finding the actions in a Bash command ----

def words_of(part):
    try:
        return shlex.split(SC.strip_prefix(part))
    except ValueError:
        return SC.strip_prefix(part).split()


def unwrap(words):
    """The words of the command a wrapper runs: npx x, bunx x, bundle exec x, pnpm dlx|exec x, yarn dlx|exec x."""
    for _ in range(3):
        if not words:
            break
        w0 = os.path.basename(words[0])
        rest = words[1:]
        if w0 in WRAPPERS or (w0 in ('pnpm', 'yarn') and rest[:1] in (['dlx'], ['exec'])) or (w0 == 'bundle' and rest[:1] == ['exec']):
            if w0 not in WRAPPERS:
                rest = rest[1:]
            while rest and rest[0].startswith('-'):
                rest = rest[1:]
            words = rest
            continue
        break
    return words


def positionals(words):
    return [w for w in words[1:] if not w.startswith('-')]


def has_flag(words, flags):
    return any(w == f or w.startswith(f + '=') for w in words for f in flags)


def sub_ok(pos, sub):
    return pos == sub or (':' in sub and pos.startswith(sub + ':'))


def starts_with_subs(pos, subs):
    head = pos[:len(subs) + 2]
    return all(any(sub_ok(p, s) for p in head) for s in subs)


def current_branch(cwd):
    try:
        r = subprocess.run(['git', '-C', cwd or os.getcwd(), 'symbolic-ref', '--short', '-q', 'HEAD'],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def git_split(words):
    """(folder given with -C or None, subcommand, the words after it) for a git command line."""
    i, cwd = 1, None
    while i < len(words):
        w = words[i]
        if w in GIT_VALUE and i + 1 < len(words):
            if w == '-C':
                cwd = words[i + 1] if cwd is None else os.path.join(cwd, words[i + 1])
            i += 2
        elif w.startswith('-'):
            i += 1
        else:
            return cwd, w, words[i + 1:]
    return cwd, '', []


def push_actions(args, cwd):
    """The actions of one `git push`: {'push-main'} and/or {'deploy'}."""
    if has_flag(args, ('--dry-run', '-n')):
        return set()
    if has_flag(args, ('--all', '--mirror')):
        return {'push-main'}
    pos, i, repo = [], 0, None
    while i < len(args):
        w = args[i]
        if w in PUSH_VALUE and i + 1 < len(args):
            if w == '--repo':
                repo = args[i + 1]
            i += 2
        elif w.startswith('--repo='):
            repo = w[7:]
            i += 1
        elif w.startswith('-') and w != '-':
            i += 1
        else:
            pos.append(w)
            i += 1
    if repo is None and pos:
        repo, pos = pos[0], pos[1:]
    if repo and repo.lower() == 'heroku':
        return {'deploy'}
    if not pos:
        return {'push-main'} if current_branch(cwd) in PROTECTED else set()
    for ref in pos:
        ref = ref.lstrip('+')
        dst = ref.split(':', 1)[1] if ':' in ref else ref
        if ':' in ref and not dst:
            dst = ref.split(':', 1)[0]   # `main:` has no target of its own
        dst = dst[len('refs/heads/'):] if dst.startswith('refs/heads/') else dst
        if dst == 'HEAD' or (':' not in ref and ref == 'HEAD'):
            dst = current_branch(cwd)
        if dst in PROTECTED:
            return {'push-main'}
    return set()


def gh_actions(words):
    pos = []
    i = 1
    while i < len(words):
        w = words[i]
        if w in ('-R', '--repo') and i + 1 < len(words):
            i += 2
            continue
        if not w.startswith('-'):
            pos.append(w)
        i += 1
    if pos[:2] == ['pr', 'merge']:
        return {'merge'}
    if pos[:2] in (['workflow', 'run'], ['workflow', 'dispatch']):
        return {'deploy'}
    if pos[:1] == ['api']:
        text = ' '.join(words)
        if 'mergePullRequest' in text:
            return {'merge'}
        if re.search(r'actions/workflows/[^/\s]+/dispatches\b', text):
            return {'deploy'}
        put = bool(re.search(r'(?:^|\s)(?:-X\s*|--method[= ]\s*)put\b', text, re.I))
        if put and re.search(r'pulls/[^/\s]+/merge\b', text):
            return {'merge'}
    return set()


def part_actions(part, cwd):
    words = unwrap(words_of(part))
    if not words:
        return set()
    prog = os.path.basename(words[0])
    if prog == 'git':
        gcwd, sub, args = git_split(words)
        if sub == 'push':
            return push_actions(args, os.path.join(cwd, gcwd) if gcwd else cwd)
        return set()
    if has_flag(words, ('--dry-run',)):
        return set()
    if prog == 'gh':
        return gh_actions(words)
    pos = positionals(words)
    out = set()
    for p, subs, flags in DEPLOY:
        if prog == p and starts_with_subs(pos, subs) and (not flags or has_flag(words, flags)):
            out.add('deploy')
    if prog in DEPLOY_ANY and 'deploy' in pos:
        out.add('deploy')
    for progs, starts, needs_run in SCRIPTS:
        if prog in progs:
            if needs_run is None:
                names = pos[1:] if pos[:1] == ['run'] else pos[:1]
            else:
                names = pos[1:] if needs_run and pos[:1] == ['run'] else ([] if needs_run else pos)
            if any(n.lower().startswith(starts) for n in names):
                out.add('deploy')
    for p, subs in MIGRATE:
        if prog == p and starts_with_subs(pos, subs):
            out.add('migrate')
    return out


def command_actions(cmd, cwd):
    """The set of actions a Bash command line takes."""
    if not isinstance(cmd, str):
        return set()
    out, here = set(), cwd or os.getcwd()
    for part in SC.commands(cmd, log):
        words = words_of(part)
        if words and words[0] == 'cd' and len(words) > 1:
            here = os.path.join(here, os.path.expanduser(words[1]))
            continue
        out |= part_actions(part, here)
    return out


def tool_actions(data):
    tool = data.get('tool_name') or ''
    if tool == 'Bash':
        return command_actions((data.get('tool_input') or {}).get('command'), data.get('cwd'))
    if tool.startswith('mcp__') and ''.join(name_words(tool)).endswith(('mergepullrequest', 'pullrequestmerge', 'enableautomerge')):
        return {'merge'}
    return set()


def name_words(tool):
    return [w.lower() for w in WORD_RE.findall(tool.split('__')[-1])]


def is_write(tool):
    """True for an MCP tool that pass 1 may not use (see READS and STRONG)."""
    if not tool.startswith('mcp__'):
        return False
    words = name_words(tool)
    if '_'.join(words) in READ_OK:
        return False
    # check+in and check+out (check_in, CheckIn) are writes; `checkout` alone is too (get_checkout_status is denied)
    pair = any(a == 'check' and b in ('in', 'out') for a, b in zip(words, words[1:]))
    return pair or not (any(w in READS for w in words) and not any(w in STRONG for w in words))


# ---- approvals ----

def fresh(approvals, sid):
    """The session's approvals that are still valid: {action: time}."""
    t = now()
    return {a: at for a, at in (approvals.get(sid) or {}).items()
            if isinstance(at, (int, float)) and 0 <= t - at <= APPROVAL_SECONDS}


def prune(s):
    t = now()
    ap = s.get('approvals') or {}
    for sid in list(ap):
        ap[sid] = {a: at for a, at in (ap[sid] or {}).items() if isinstance(at, (int, float)) and t - at <= APPROVAL_SECONDS}
        if not ap[sid]:
            del ap[sid]
    s['approvals'] = ap
    p2 = s.get('pass2_agent') or {}
    for sid in list(p2):
        if not isinstance(p2[sid], dict) or t - p2[sid].get('at', 0) > KEEP:
            del p2[sid]
    s['pass2_agent'] = p2


def wait_for(s, sid, action):
    x = (s.get('sessions') or {}).get(sid)
    if isinstance(x, dict):
        x['prod_wait'] = {'action': action, 'at': now()}


def deny(data, action, why):
    sid = data.get('session_id', '')
    if action == 'pass2':
        reason = ('Pass 1 never writes. Return the PROPOSAL; after the person types `approve pass2`, '
                  'a new pass 2 agent does the approved changes.')
    else:
        reason = (f"Production guard: {action} needs the person's approval. Ask them to type `approve {action}` "
                  'in this session, then try again within 10 minutes.')
    with state() as s:
        wait_for(s, sid, action)
    who = data.get('agent_type') or ('agent' if data.get('agent_id') else 'main')
    log(f'deny   {sid[:8]} {who} {action}: {why[:80]}')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                             'permissionDecisionReason': reason}}))


def on_tool(data):
    sid, tool = data.get('session_id', ''), data.get('tool_name') or ''
    agent, atype = data.get('agent_id'), data.get('agent_type') or ''
    why = (data.get('tool_input') or {}).get('command') if tool == 'Bash' else tool
    why = why if isinstance(why, str) else tool
    actions = tool_actions(data)
    if actions:
        with state() as s:
            prune(s)
            have = fresh(s.get('approvals') or {}, sid)
            missing = [a for a in ACTIONS if a in actions and a not in have]
            if not missing:
                for a in actions:
                    del s['approvals'][sid][a]
                if not s['approvals'].get(sid):
                    s['approvals'].pop(sid, None)
                log(f'use    {sid[:8]} {"+".join(sorted(actions))} (one approval used)')
                return
        return deny(data, missing[0], why)
    if atype in TWO_PASS and agent and is_write(tool):
        with state() as s:
            prune(s)
            cur = (s.get('pass2_agent') or {}).get(sid)
            if cur and cur.get('agent_id') == agent:
                return
            if 'pass2' in fresh(s.get('approvals') or {}, sid):
                del s['approvals'][sid]['pass2']
                if not s['approvals'].get(sid):
                    s['approvals'].pop(sid, None)
                s['pass2_agent'][sid] = {'agent_id': agent, 'agent_type': atype, 'at': now()}
                log(f'use    {sid[:8]} pass2 for {atype} {agent[:8]}')
                return
        return deny(data, 'pass2', why)


def on_prompt(data):
    text = data.get('prompt')
    if not isinstance(text, str):
        return
    words = text.strip().lower().split()
    if len(words) != 2 or words[0] != 'approve':
        return
    sid, action = data.get('session_id', ''), words[1]
    if action not in ACTIONS:
        note = 'No approval recorded: "%s" is not an action. The valid ones are %s.' % (action, ', '.join(ACTIONS))
        log(f'note   {sid[:8]} unknown approve word {action[:20]!r}')
    else:
        with state() as s:
            prune(s)
            s.setdefault('approvals', {}).setdefault(sid, {})[action] = now()
            x = (s.get('sessions') or {}).get(sid)
            if isinstance(x, dict) and (x.get('prod_wait') or {}).get('action') == action:
                del x['prod_wait']
        note = f'Approved {action} for one use in the next 10 minutes.'
        log(f'approve {sid[:8]} {action}')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': note}}))


def on_stop(data):
    sid, agent = data.get('session_id', ''), data.get('agent_id')
    with state() as s:
        cur = (s.get('pass2_agent') or {}).get(sid)
        if isinstance(cur, dict) and cur.get('agent_id') == agent:
            del s['pass2_agent'][sid]
            log(f'free   {sid[:8]} pass2 {data.get("agent_type") or ""} {str(agent)[:8]} agent stopped')


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return log('error  input is not JSON, let through')
    if not isinstance(data, dict):
        return log('error  input is not an object, let through')
    if not switch_on():
        return
    if SC is None:
        return log(f'error  shell_commands.py not loaded: {SC_ERR}')
    try:
        event = data.get('hook_event_name')
        if event == 'PreToolUse':
            on_tool(data)
        elif event == 'UserPromptSubmit':
            on_prompt(data)
        elif event == 'SubagentStop' and data.get('agent_id'):
            on_stop(data)
    except Exception as e:   # never stop a session because of this hook
        log(f'error  {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
