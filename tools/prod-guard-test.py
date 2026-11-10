"""Test the production guard (Resources/hooks/prod-guard.py), its Waiting on you feed (effort-hook.py --track
reads prod_wait) and its install (install-hooks.py), on copies only: a temp kit folder, a temp log, temp git
repos and a temp HOME. No model calls.
Run: /usr/bin/python3 tools/prod-guard-test.py"""
import json, os, re, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, 'Resources', 'hooks')
HOOK = os.path.join(HOOKS, 'prod-guard.py')
passed, failed = [], []


def check(name, ok):
    (passed if ok else failed).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name)


tmp = tempfile.mkdtemp(prefix='prod-guard-test-')
KIT = os.path.join(tmp, 'kit')
LOG = os.path.join(tmp, 'kit.log')
os.makedirs(KIT)
STATE = os.path.join(KIT, 'state.json')
ENV = dict(os.environ, STTARK_KIT_DIR=KIT, STTARK_KIT_LOG=LOG)
ENV.pop('STTARK_PROD_NOW', None)


def switch(on, extra=None):
    d = {'orchestrator': on, 'sessions': {'s1': {'at': 1}}}
    d.update(extra or {})
    json.dump(d, open(STATE, 'w'))


def st():
    return json.load(open(STATE))


def git_repo(name, branch):
    p = os.path.join(tmp, name)
    os.makedirs(p)
    subprocess.run(['git', '-C', p, 'init', '-q'], check=True, capture_output=True)
    subprocess.run(['git', '-C', p, 'symbolic-ref', 'HEAD', 'refs/heads/' + branch], check=True, capture_output=True)
    return p


ON_MAIN, ON_FEAT = git_repo('onmain', 'main'), git_repo('onfeat', 'feature-x')
ON_MASTER = git_repo('onmaster', 'master')


def run(data, env=None, raw=None):
    r = subprocess.run([sys.executable, HOOK], input=raw if raw is not None else json.dumps(data),
                       capture_output=True, text=True, env=env or ENV)
    return (json.loads(r.stdout) if r.stdout.strip() else None), r.returncode


def pre(cmd=None, tool='Bash', agent=None, atype='implementer', sid='s1', cwd=ON_FEAT):
    d = dict(hook_event_name='PreToolUse', session_id=sid, tool_name=tool, cwd=cwd,
             tool_input={'command': cmd} if cmd is not None else {})
    if agent:
        d.update(agent_id=agent, agent_type=atype)
    return d


def prompt(text, sid='s1'):
    return dict(hook_event_name='UserPromptSubmit', session_id=sid, prompt=text)


def denied(out):
    return bool(out) and out['hookSpecificOutput']['permissionDecision'] == 'deny'


def reason(out):
    return out['hookSpecificOutput']['permissionDecisionReason']


def lines():
    return [l[20:] for l in open(LOG).read().splitlines()] if os.path.exists(LOG) else []


def blocked(cmd, action, cwd=ON_FEAT):
    out, rc = run(pre(cmd, cwd=cwd))
    return denied(out) and rc == 0 and ('Production guard: %s needs' % action) in reason(out)


def allowed(cmd, cwd=ON_FEAT):
    out, rc = run(pre(cmd, cwd=cwd))
    return out is None and rc == 0


U = 'mcp__0b9c1f2e-3d4a-4b5c-8d6e-7f8091a2b3c4__'
switch(True)
# ---- push-main ----
for c in ('git push origin main', 'git push origin master', 'git push origin HEAD:main', 'git push origin +main',
          'git push origin refs/heads/main', 'git push origin :main', 'git push --delete origin main',
          'git push -u origin feat:refs/heads/main', 'git push --all', 'git push --mirror origin',
          'git push --force-with-lease origin main', 'git -C /tmp push origin main', 'git -c x=y push origin main',
          'cd /tmp && git push origin main', 'FOO=1 git push origin main', 'timeout 60 git push origin main',
          'echo hi; git push origin main', 'bash -c "git push origin main"', 'git push origin feat:main',
          'git push origin HEAD:refs/heads/master'):
    check('push-main denies: ' + c, blocked(c, 'push-main'))
check('push-main denies: no refspec on main', blocked('git push', 'push-main', cwd=ON_MAIN))
check('push-main denies: no refspec, remote only, on master', blocked('git push -u origin', 'push-main', cwd=ON_MASTER))
check('push-main denies: HEAD while on main', blocked('git push origin HEAD', 'push-main', cwd=ON_MAIN))
check('push-main denies: git -C <main repo> push with no refspec', blocked('git -C %s push' % ON_MAIN, 'push-main', cwd=ON_FEAT))
check('push-main denies: cd <main repo> && git push', blocked('cd %s && git push' % ON_MAIN, 'push-main', cwd=ON_FEAT))
for c in ('git push origin feature-x', 'git push -u origin feature-x', 'git push origin HEAD:feature-x',
          'git push origin main:feature-x', 'git push', 'git push origin', 'git push origin HEAD',
          'git push --tags', 'git push origin mainline', 'git push --dry-run origin main', 'git push -n origin main',
          'git status', 'git pull origin main', 'git fetch origin main', 'git checkout main'):
    check('push allowed on a feature branch: ' + c, allowed(c, cwd=ON_FEAT))
check('quoted text is not a push: commit message', allowed('git commit -m "then git push origin main"'))
check('quoted text is not a push: echo', allowed('echo "git push origin main"') and allowed("echo 'git push origin main'"))
check('quoted text is not a push: heredoc commit message',
      allowed("git commit -m \"$(cat <<'EOF'\nFix it\n\ngit push origin main\nEOF\n)\""))
check('quoted text is not a merge or deploy', allowed('git commit -m "gh pr merge 5; npm publish; terraform apply"'))
check('not a command: grep for text', allowed('grep -rn "git push origin main" docs'))
check('not a git push: --dry-run to main is allowed', allowed('git push --dry-run', cwd=ON_MAIN))

# ---- merge ----
for c in ('gh pr merge 12', 'gh pr merge --squash --auto 12', 'gh pr merge -R Sttark/x 12', 'gh -R Sttark/x pr merge 12',
          'gh api -X PUT repos/Sttark/x/pulls/12/merge', 'gh api --method PUT /repos/o/r/pulls/3/merge -f merge_method=squash',
          'gh api -XPUT repos/{owner}/{repo}/pulls/3/merge', 'gh api graphql -f query=\'mutation { mergePullRequest(input:{}) { x } }\'',
          'command gh pr merge 1'):
    check('merge denies: ' + c, blocked(c, 'merge'))
for c in ('gh pr view 12', 'gh pr create --title x', 'gh pr checks 12', 'gh api repos/o/r/pulls/12',
          'gh api -X GET repos/o/r/pulls/12/merge', 'gh pr merge --dry-run 12'):
    check('merge allowed: ' + c, allowed(c))
for tool in ('mcp__github__merge_pull_request', 'mcp__plugin_x_github__merge_pull_request', 'mcp__github__mergePullRequest',
             U + 'github_mergePullRequest', U + 'merge-pull-request'):
    out, _ = run(pre(tool=tool))
    check('merge denies MCP tool ' + tool, denied(out) and 'merge needs' in reason(out))
out, _ = run(pre(tool='mcp__github__get_pull_request'))
check('MCP read tool allowed', out is None)

# ---- deploy ----
for c in ('gh workflow run release.yml', 'gh workflow dispatch release', 'gh api -X POST repos/o/r/actions/workflows/r.yml/dispatches',
          'vercel --prod', 'vercel deploy --prod', 'npx vercel --prod --yes', 'netlify deploy --prod', 'fly deploy',
          'flyctl deploy --remote-only', 'firebase deploy --only hosting', 'railway up', 'heroku container:release web',
          'heroku pipelines:promote -a x', 'git push heroku feature-x', 'git push heroku main', 'npm publish',
          'pnpm publish --access public', 'terraform apply -auto-approve', 'terraform -chdir=infra apply',
          'kubectl apply -f x.yaml', 'kubectl -n prod rollout restart deploy/x', 'gcloud run deploy svc --image i',
          'gcloud app deploy', 'aws cloudformation deploy --stack-name s', 'aws deploy create-deployment'):
    check('deploy denies: ' + c, blocked(c, 'deploy') if not c.startswith('gh api') else
          (denied(run(pre(c))[0])))
for c in ('vercel', 'vercel dev', 'vercel deploy', 'netlify deploy', 'netlify status', 'fly status', 'firebase login',
          'railway status', 'heroku logs -t', 'npm publish --dry-run', 'npm test', 'npm view x', 'terraform plan',
          'kubectl get pods', 'gcloud config list', 'aws s3 ls', 'gh workflow list', 'gh workflow view x',
          'gh run list'):
    check('deploy allowed: ' + c, allowed(c))

# ---- migrate ----
for c in ('prisma migrate deploy', 'npx prisma migrate deploy', 'prisma db push', 'rails db:migrate',
          'bundle exec rails db:migrate RAILS_ENV=production', 'rake db:migrate', 'knex migrate:latest',
          'npx knex migrate:latest --env production', 'sequelize db:migrate', 'alembic upgrade head',
          'drizzle-kit push', 'pnpm dlx drizzle-kit push', 'supabase db push', 'flyway migrate'):
    check('migrate denies: ' + c, blocked(c, 'migrate'))
for c in ('prisma migrate dev', 'prisma generate', 'rails db:rollback', 'alembic current', 'alembic revision -m x',
          'supabase db diff', 'supabase start', 'flyway info', 'prisma migrate deploy --dry-run'):
    check('migrate allowed: ' + c, allowed(c))

# ---- keywords, eval, heredocs, script deploys ----
for c, a in (('if git push origin main; then echo ok; fi', 'push-main'), ('for i in 1; do git push origin main; done', 'push-main'),
             ('while true; do npm publish; done', 'deploy'), ('{ gh pr merge 3; }', 'merge'), ('! git push origin main', 'push-main'),
             ('nice -n 5 npm publish', 'deploy'), ('builtin command npm publish', 'deploy'),
             ('eval "git push origin main"', 'push-main'), ("eval 'gh pr merge 3'", 'merge'), ('eval npm publish', 'deploy'),
             ('bash <<EOF\ngit push origin main\nEOF', 'push-main'), ("sh <<'EOF'\nnpm publish\nEOF", 'deploy'),
             ("cat <<EOF | bash\nprisma migrate deploy\nEOF", 'migrate'),
             ("git commit -F - <<'EOF' && git push origin main\nmsg\nEOF", 'push-main'),
             ("git commit -F - <<'EOF'\nmsg\nEOF\ngit push origin main", 'push-main'),
             ('npm run deploy', 'deploy'), ('pnpm run deploy:prod', 'deploy'), ('yarn run release', 'deploy'),
             ('bun run publish-all', 'deploy'), ('npm run --silent deploy', 'deploy'), ('make deploy', 'deploy'),
             ('make release', 'deploy'), ('make publish-docs', 'deploy'), ('just deploy', 'deploy'),
             ('just release patch', 'deploy'), ('task deploy', 'deploy'), ('task release', 'deploy')):
    check('denies: ' + c.replace('\n', ' / '), blocked(c, a))
for c in ("git commit -F - <<'EOF'\nmsg\ngit push origin main\nnpm publish\nEOF", "cat <<EOF\ngit push origin main\nEOF",
          'npm run build', 'npm run test', 'npm run dev', 'make build', 'make test', 'just test', 'task build',
          'npm test', 'echo make deploy', 'if true; then echo hi; fi', 'eval "echo hi"', 'bash <<EOF\necho hi\nEOF'):
    check('allowed: ' + c.replace('\n', ' / '), allowed(c))

for c, a in (("bash <<< 'git push origin main'", 'push-main'), ('bash <<<"git push origin main"', 'push-main'),
             ("bash<<<'git push origin main'", 'push-main'), ('sh<<<"gh pr merge 1"', 'merge'),
             ('bash<<EOF\nnpm publish\nEOF', 'deploy'), ('bash <<EOF\nnpm publish\nEOF', 'deploy'),
             ('bash << EOF\nnpm publish\nEOF', 'deploy'), ("cat<<EOF|bash\nnpm publish\nEOF", 'deploy'), ('sh <<< "npm publish"', 'deploy'),
             ('sudo -u deploy npm publish', 'deploy'), ('sudo -E -u root git push origin main', 'push-main'),
             ('command -p npm publish', 'deploy'), ('yarn deploy', 'deploy'), ('pnpm release', 'deploy'),
             ('bun publish-all', 'deploy'), ('yarn run deploy:prod', 'deploy'), ('pnpm deploy --prod', 'deploy'),
             ('npm publish', 'deploy')):
    check('denies: ' + c, blocked(c, a))
for c in ("grep x<<<'git push origin main'", "cat<<<'npm publish'", "cat<<EOF\nnpm publish\nEOF", "bash <<<'echo hi'", "bash <<< 'echo hi'", 'yarn build', 'yarn install', 'pnpm test', 'bun run dev', 'sudo -u me ls', 'command -p ls'):
    check('allowed: ' + c, allowed(c))
for tool in ('mcp__github__pull_request_merge', U + 'github_enable_auto_merge', 'mcp__github__enableAutoMerge'):
    out, _ = run(pre(tool=tool))
    check('merge denies MCP tool ' + tool, denied(out) and 'merge needs' in reason(out))

# ---- reason, log, agent ----
out, _ = run(pre('git push origin main'))
check('deny reason is the exact text',
      reason(out) == "Production guard: push-main needs the person's approval. Ask them to type `approve push-main` in this session, then try again within 10 minutes.")
check('deny is never "ask"', out['hookSpecificOutput']['permissionDecision'] == 'deny')
check('deny is logged with a prod line', any(l.startswith('prod deny') and 'push-main' in l for l in lines()))
out, _ = run(pre('npm publish', agent='a1', atype='ops'))
check('a subagent is denied too', denied(out) and 'deploy needs' in reason(out))
out, _ = run(pre('gh pr merge 3 && npm publish'))
check('two actions: the first missing one is named', denied(out) and 'merge needs' in reason(out))

# ---- approval flow ----
def approve(action, sid='s1', env=None):
    return run(prompt('approve ' + action, sid), env=env)[0]


out = approve('push-main')
check('approve: context line', out['hookSpecificOutput']['hookEventName'] == 'UserPromptSubmit'
      and out['hookSpecificOutput']['additionalContext'] == 'Approved push-main for one use in the next 10 minutes.')
check('approve: recorded per session and action', 'push-main' in st()['approvals']['s1'])
check('approve: exact match only (case-insensitive, trimmed)', run(prompt('  Approve   PUSH-MAIN \n'))[0] is not None
      and run(prompt('please approve push-main'))[0] is None and run(prompt('approve push-main now'))[0] is None
      and run(prompt('hello'))[0] is None)
check('use 1: allowed', allowed('git push origin main'))
check('use 1 removed the approval', 's1' not in st().get('approvals', {}) or 'push-main' not in st()['approvals'].get('s1', {}))
check('use 2: denied', blocked('git push origin main', 'push-main'))
approve('merge')
check('an approval covers only its own action', blocked('npm publish', 'deploy') and allowed('gh pr merge 5'))
approve('deploy', sid='other')
check('an approval of another session does not count', blocked('npm publish', 'deploy'))
approve('deploy')
out, _ = run(pre('gh pr merge 5; terraform apply'))
check('two actions need two approvals', denied(out) and 'merge needs' in reason(out))
approve('merge')
check('both approved: one use takes both', allowed('gh pr merge 5; terraform apply') and blocked('terraform apply', 'deploy'))
approve('migrate')
out, _ = run(pre('prisma migrate deploy', agent='a9', atype='implementer'))
check('approval in the main thread covers a subagent', out is None)
approve('push-main')
check('dry run does not use an approval', allowed('git push --dry-run origin main') and allowed('git push origin main'))
# expiry
T0 = 1_800_000_000
E0 = dict(ENV, STTARK_PROD_NOW=str(T0))
approve('push-main', env=E0)
check('expiry: 9 min later still valid',
      run(pre('git push origin main'), env=dict(ENV, STTARK_PROD_NOW=str(T0 + 540)))[0] is None)
approve('push-main', env=E0)
out, _ = run(pre('git push origin main'), env=dict(ENV, STTARK_PROD_NOW=str(T0 + 601)))
check('expiry: 10 min and 1 s later denied', denied(out) and 'push-main needs' in reason(out))
out = run(prompt('approve deploy'), env=dict(ENV, STTARK_PROD_NOW=str(T0 + 700)))[0]
check('expiry: stale approvals are dropped on the next write', 'push-main' not in st()['approvals'].get('s1', {}))
# unknown word
out = run(prompt('approve everything'))[0]
ctx = out['hookSpecificOutput']['additionalContext']
check('unknown approve word: note lists the valid ones, nothing recorded',
      all(a in ctx for a in ('push-main', 'merge', 'deploy', 'migrate', 'pass2')) and 'everything' in ctx
      and 'everything' not in json.dumps(st().get('approvals')))

# ---- I27: pass 1 never writes ----
TWO = ('asana-update-specialist', 'strategy-specialist', 'onshape-cleanup-specialist', 'supplier-specialist')
WR = ['mcp__asana__create_task', 'mcp__asana__update_task', 'mcp__x__delete_thing', 'mcp__x__add_comment',
      'mcp__x__send_email', 'mcp__x__reply_to', 'mcp__x__forward_message', 'mcp__x__post_message',
      'mcp__x__upload_file', 'mcp__x__label_message', 'mcp__x__mark_read', 'mcp__x__apply_change',
      'mcp__x__set_field', 'mcp__x__edit_doc', 'mcp__x__write_note', 'mcp__x__propose_x', 'mcp__x__take_x',
      'mcp__x__return_x', 'mcp__x__save_x', 'mcp__x__log_time', 'mcp__x__move_task', 'mcp__x__trash_x',
      'mcp__x__untrash_x', 'mcp__x__unlabel_x', 'mcp__x__merge_x', 'mcp__x__createTask']
WR += [U + n for n in ('asana_create_task', 'asana_update_task', 'asana_add_comment', 'asana_log_time', 'asana_move_task',
                       'asana_delete_comment', 'docs_edit', 'docs_create', 'docs_propose', 'docs_upload_photo',
                       'gmail_create_draft', 'calendar_create_event', 'inventory_take', 'discount_code_create',
                       'asana_duplicate_task', 'gmail_modify', 'sheets_append_rows', 'drive_copy_file', 'upsert_record',
                       'deploy_edge_function', 'reset_branch', 'order_cancel', 'invoice_void', 'inventory_adjust',
                       'inventory_restock', 'toggle_flag', 'enable_feature', 'clear_cells', 'comment', 'fork',
                       'get_project_set', 'RunSql', 'cancel_order', 'create_order', 'update_order_status', 'delete_comment',
                       'add_comment', 'post_comment', 'asana_submit_status', 'submit_report', 'schedule_meeting', 'sync_records', 'engineering_material', 'inventory_return', 'inventory_save', 'inventory_photo', 'address_book', 'tasks_remove_item', 'doc_insert_text', 'doc_replace_text', 'tasks_archive', 'tasks_assign',
                       'files_rename', 'files_patch', 'data_import', 'task_complete', 'rows_batch_update',
                       'sql_execute', 'job_run', 'site_publish', 'doc_share', 'team_invite', 'order_approve',
                       'order_reject', 'ticket_close', 'ticket_reopen', 'check_in', 'check_out', 'checkin', 'checkout', 'CheckIn', 'CheckOut', 'get_check_in', 'lookup_order_and_ship', 'ship_order', 'get_checkout_status', 'asana_updateTask', 'docs-edit')]
switch(True)
for t in WR:
    out, _ = run(pre(tool=t, agent='p1', atype='asana-update-specialist'))
    if not (denied(out) and reason(out) == "Pass 1 never writes. Return the PROPOSAL; after the person types `approve pass2`, a new pass 2 agent does the approved changes."):
        check('pass 1 denies write tool ' + t, False)
check('pass 1 denies every listed write tool (%d)' % len(WR), not any(f.startswith('pass 1 denies') for f in failed))
for a in TWO:
    out, _ = run(pre(tool='mcp__x__create_task', agent='p1', atype=a))
    check('pass 1 denies for ' + a, denied(out))
for t in (U + 'asana_get_task', U + 'asana_search_tasks', U + 'docs_read', U + 'drive_search', U + 'get_database_schema',
          U + 'run_query', U + 'gmail_get_thread', U + 'asana_list_projects', U + 'x_show_history', U + 'x_preview_estimate',
          U + 'x_whoami', *[U + n for n in ('get_order_status', 'order_status', 'order_lookup', 'order_history', 'order_get',
          'order_list', 'show_order', 'fetch_order', 'preview_order', 'get_pull_request', 'quote_price', 'download_file',
          'validate_order', 'calculate_total', 'summarize_thread', 'compare_files', 'analyze_data', 'list_comments',
          'get_release_notes', 'check_inventory', 'check_status', 'check_stock')], *[U + n for n in ('org_structure', 'business_days', 'meetings_today', 'circle_meetings_checklist',
          'order_reprint_quote', 'order_design_files', 'die_template', 'asana_whoami', 'asana_get_task_stories',
          'asana_list_sections', 'asana_get_time_entries', 'drive_list_folder', 'gchat_search_messages',
          'gchat_list_spaces', 'gmail_read_message', 'gmail_search', 'read_document', 'meetings_search',
          'meetings_get_transcript', 'inventory_ask', 'inventory_get', 'inventory_history', 'inventory_report',
          'inventory_search', 'order_due_date_preview', 'order_roll_estimate', 'session_replay_lookup',
          'docs_search', 'docs_list_drafts', 'docs_get_draft')], U + 'RunQuery', U + 'run-query', U + 'x_count_rows', U + 'x_check_access', U + 'x_describe_table',
          U + 'x_lookup_user', U + 'x_ask', U + 'x_browse_files', U + 'x_info', U + 'x_diff_files', U + 'x_report_status', U + 'x_view_page', U + 'x_fetch_page', U + 'x_find_user',
          'mcp__asana__get_task', 'mcp__asana__search_tasks', 'mcp__x__list_things',
          'mcp__x__settings_get', 'mcp__x__fetch_page', 'Read', 'Write'):
    out, _ = run(pre(tool=t, agent='p1', atype='asana-update-specialist'))
    check('pass 1 allows ' + t, out is None)
out, _ = run(pre(tool='mcp__x__create_task', agent='p1', atype='implementer'))
check('other agent types are not held to pass 1', out is None)
out, _ = run(pre(tool='mcp__x__create_task'))
check('the main thread is not held to pass 1', out is None)
approve('pass2')
out, _ = run(pre(tool='mcp__x__create_task', agent='p2', atype='supplier-specialist'))
check('pass2 approved: the first write is allowed and takes the approval',
      out is None and st()['pass2_agent']['s1']['agent_id'] == 'p2' and 'pass2' not in st().get('approvals', {}).get('s1', {}))
out, _ = run(pre(tool='mcp__x__update_task', agent='p2', atype='supplier-specialist'))
check('pass2: later writes of the same agent are allowed', out is None)
out, _ = run(pre(tool='mcp__x__update_task', agent='p3', atype='supplier-specialist'))
check('pass2: another agent is still denied', denied(out))
run(dict(hook_event_name='SubagentStop', session_id='s1', agent_id='p3', agent_type='supplier-specialist'))
check('SubagentStop of another agent keeps the hold', 'pass2_agent' in st() and 's1' in st()['pass2_agent'])
run(dict(hook_event_name='SubagentStop', session_id='s1', agent_id='p2', agent_type='supplier-specialist'))
check('SubagentStop frees pass2_agent', 's1' not in st()['pass2_agent'])
out, _ = run(pre(tool='mcp__x__update_task', agent='p2', atype='supplier-specialist'))
check('after SubagentStop the agent writes are denied again', denied(out))

# ---- switch off, bad input ----
switch(False)
check('switch off: every action allowed',
      all(allowed(c, cwd=ON_MAIN) for c in ('git push origin main', 'gh pr merge 1', 'npm publish', 'prisma migrate deploy'))
      and run(pre(tool='mcp__github__merge_pull_request'))[0] is None
      and run(pre(tool='mcp__x__create_task', agent='p1', atype='strategy-specialist'))[0] is None)
check('switch off: approve records nothing', run(prompt('approve merge'))[0] is None and 'approvals' not in st())
os.remove(STATE)
check('no state file: allowed', allowed('git push origin main', cwd=ON_MAIN))
switch(True)
n = len([l for l in lines() if l.startswith('prod error')])
out, rc = run(None, raw='not json{')
check('bad input: allowed, exit 0, logged', out is None and rc == 0 and len([l for l in lines() if l.startswith('prod error')]) == n + 1)
out, rc = run(None, raw='[1,2]')
check('input that is a list: allowed, exit 0, logged', out is None and rc == 0 and len([l for l in lines() if l.startswith('prod error')]) == n + 2)
out, rc = run(dict(hook_event_name='PreToolUse', session_id='s1', tool_name='Bash', tool_input=None))
check('Bash with no tool_input: allowed', out is None and rc == 0)
out, rc = run(dict(hook_event_name='PreToolUse', session_id='s1', tool_name='Bash', tool_input={'command': 5}))
check('command that is not text: allowed', out is None and rc == 0)
out, rc = run(dict(hook_event_name='PreToolUse', tool_name='Bash', tool_input={'command': 'npm publish'}))
check('no session id: still denied', denied(out) and rc == 0)
out, rc = run(pre('git push origin main', cwd=os.path.join(tmp, 'no-such-folder')))
check('cwd that is gone: still denied for an explicit main', denied(out))
out, rc = run(pre('git push', cwd=os.path.join(tmp, 'no-such-folder')))
check('cwd that is gone: no refspec push is let through', out is None and rc == 0)

# ---- Waiting on you ----
switch(True)
run(pre('git push origin main'))
w = st()['sessions']['s1'].get('prod_wait')
check('deny writes prod_wait with the action', w and w['action'] == 'push-main')
run(pre('npm publish'))
check('the latest denial replaces it', st()['sessions']['s1']['prod_wait']['action'] == 'deploy')
run(prompt('approve migrate'))
check('approving another action keeps it', 'prod_wait' in st()['sessions']['s1'])
run(prompt('approve deploy'))
check('approving the denied action clears it', 'prod_wait' not in st()['sessions']['s1'])
run(pre('git push origin main', sid='unknown-session'))
check('a session the app does not know gets no entry', 'unknown-session' not in st()['sessions'])
# effort-hook --track (its paths pointed at the temp kit): the entry makes an unseen session need the person
switch(True)
run(pre('terraform apply'))
drv = """
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('effort_hook', os.path.join(%r, 'effort-hook.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.STATE, m.LOG = %r, %r
class S:
    def session(self, sid):
        return {'title': 'T', 'session_url': 'u', 'status_bucket': 'idle', 'unread': True,
                'last_event_at': '2026-11-10T10:00:00.000Z'}
m.sse = lambda: S()
m.on_screen = lambda: {}
m.by_hand = lambda *a, **k: None
m.asks_you = lambda t: (False, '')
m.track()
""" % (HOOKS, STATE, LOG)
d = st()
d['sessions']['s1']['at'] = 4102444800   # far future: counts as recent
json.dump(d, open(STATE, 'w'))
r = subprocess.run([sys.executable, '-c', drv], capture_output=True, text=True, env=ENV)
app = st()['sessions']['s1'].get('app', {})
check('track: an unseen session needs you, with "Approval needed: deploy"',
      r.returncode == 0 and app.get('needs') is True and app.get('why') == 'Approval needed: deploy')
check('track keeps prod_wait', 'prod_wait' in st()['sessions']['s1'])
run(prompt('approve deploy'))
r = subprocess.run([sys.executable, '-c', drv], capture_output=True, text=True, env=ENV)
app = st()['sessions']['s1'].get('app', {})
check('track after approval: the reply needs nothing', r.returncode == 0 and app.get('needs') is False)

# ---- install-hooks.py ----
home = os.path.join(tmp, 'home')
ikit = os.path.join(tmp, 'ikit')
os.makedirs(os.path.join(home, '.claude'))
shutil.copytree(HOOKS, os.path.join(ikit, 'hooks'))
SET = os.path.join(home, '.claude', 'settings.json')
json.dump({'hooks': {ev: [{'hooks': [{'type': 'command', 'command': 'other-%s.sh' % ev}]}]
                     for ev in ('PreToolUse', 'UserPromptSubmit', 'SubagentStop')}}, open(SET, 'w'))
IENV = dict(os.environ, HOME=home)
IENV.pop('STTARK_KIT_DIR', None)


def install(*args):
    return subprocess.run([sys.executable, os.path.join(ikit, 'hooks', 'install-hooks.py')] + list(args),
                          capture_output=True, text=True, env=IENV).stdout.strip()


def groups(event):
    return [g for g in json.load(open(SET)).get('hooks', {}).get(event, [])
            if any('prod-guard.py' in h['command'] for h in g['hooks'])]


def allg():
    return [groups(e) for e in ('PreToolUse', 'UserPromptSubmit', 'SubagentStop')]


install()
check('install, switch off: no prod entries; --status prod false', allg() == [[], [], []] and json.loads(install('--status'))['prod'] is False)
out = install('--orchestrator', 'on')
check('--orchestrator on: output ends with "prod on"', out.endswith('rotation on, prod on'))
pg, ug, sg = allg()
check('PreToolUse: one entry, matcher covers Bash and mcp__.*, quoted command',
      len(pg) == 1 and pg[0]['matcher'] == '^(Bash|mcp__.*)$' and pg[0]['hooks'][0]['command'].endswith('prod-guard.py"'))
check('matcher matches Bash and MCP tools only',
      all(re.search(pg[0]['matcher'], n) for n in ('Bash', 'mcp__github__merge_pull_request'))
      and not any(re.search(pg[0]['matcher'], n) for n in ('Read', 'BashOutput', 'Edit')))
check('UserPromptSubmit and SubagentStop: one entry each, no matcher',
      len(ug) == 1 and 'matcher' not in ug[0] and len(sg) == 1 and 'matcher' not in sg[0])
check('--status prod true', json.loads(install('--status'))['prod'] is True)
install()
check('launch run keeps one copy of each', [len(x) for x in allg()] == [1, 1, 1])
check('launch run with nothing new: unchanged', install() == 'unchanged')
out = install('--orchestrator', 'off')
check('--orchestrator off: removed, output ends with "prod off"', allg() == [[], [], []] and out.endswith('rotation off, prod off'))
check('other hooks left alone',
      all(any(h.get('command') == 'other-%s.sh' % e for g in json.load(open(SET))['hooks'][e] for h in g['hooks'])
          for e in ('PreToolUse', 'UserPromptSubmit', 'SubagentStop')))
json.dump({'orchestrator': True}, open(os.path.join(ikit, 'state.json'), 'w'))
install()
check('launch run brings entries in line with the switch (on)', [len(x) for x in allg()] == [1, 1, 1])
install('--remove')
check('--remove removes them', allg() == [[], [], []])

shutil.rmtree(tmp, ignore_errors=True)
print('\n%d passed, %d failed' % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
