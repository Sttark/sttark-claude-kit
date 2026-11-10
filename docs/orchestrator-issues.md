# Orchestrator plan: issues log

Issues, conflicts and gaps found while the orchestrator plan was built, with the recommended fix and the
point where each one must come up. Status: open, decided or fixed. Last update: 2026-11-10, after the shared splitter fix.

**Rule:** at the start of each phase, and before the merge to `main`, read this file and raise every open item
whose "Raise at" matches. Give the recommended fix and ask for a decision only where one is needed. Update the
status here when it is decided or fixed.

## Open

| # | Found in | Issue | Recommended fix | Raise at |
|---|---|---|---|---|
| I3 | Phase 0 | This Mac has no "Sttark Effort Signing" certificate, so the branch build is signed ad hoc. macOS asks again for the Chrome approver's Accessibility permission after each install. | No change on the branch. Releases from `main` are signed by CI. | Merge to `main` |
| I4 | Phase 0 | The updater is off on the branch (`Updater.enabled = false` in `Sources/Update.swift`), and the menu says so. `tools/update-test.sh` cannot pass with it off. | Set `Updater.enabled = true` and remove the menu line in the merge PR. Run `tools/update-test.sh`. | Merge to `main` |
| I20 | This log | `CLAUDE.md` on this branch holds the rule to raise these items. It must not reach `main` as it is. | Remove the orchestrator lines from `CLAUDE.md` in the merge PR, or keep only lines that are true on `main`. | Merge to `main` (D38) |
| I22 | Fixes | The validator's P3 finding is fixed, but the guard still lets one call of cost 2 through as the first call (for example `head -1 a b c d`). This is by design (2 lookups per item). | No change. | Before the org rollout (with D33) |
| I23 | Phase 4 | The UI guard's page-check output check also accepts the markers "page views" and "nothing to check" near the script name, so a sentence such as "I did not run page-check; no page views to look at." passes. | Accept "page views" and "nothing to check" only inside a code block or on a line that starts like page-check's own output; add tests. | Phase 7 start (with the hook work there) |
| I24 | Phase 4 | The UI guard asks the implementer to run page-check. That works only when the agent has Bash; the kit's `implementer` has it, but a project agent without Bash cannot answer the block. | No change for the kit agents. Say in the block reason that an agent without Bash must report that it could not run page-check. | Phase 6 start (specialist agents) |
| I25 | Phase 5 | The browser lock and the inline guard treat a heredoc body line that starts with `claude-window` (or a long-run command) as a command. The agent only waits or is told to delegate; nothing gets through. | Skip heredoc bodies in the splitter if it becomes a nuisance. | Before the org rollout |

## Decided or fixed

| # | Found in | Issue | Result |
|---|---|---|---|
| D-a | Phase 0 | The headless CLI was not signed in, so the hook checks could not run. | Fixed: Cole signed in. `tools/hook-event-test.sh` passes 5 of 5. |
| D-b | Phase 1 | With Orchestrator on before Phase 2, the kit rules and the skill rules disagreed. | Fixed in Phase 2: the working rules hook swaps the conflicting rules. |
| D-c | Phase 2 | The test "read any 3 files" passed with one Bash call, so it did not test the guard. | Decided: the guard counts calls by design. The test now forces one Read call per file. See I9 for the file count. |
| D-d | Phase 2 | The lookup limit of 2 per item. | Decided by Cole: keep it as it is. See I10. |
| D-e | Phase 4 | The app rules cache (`app-rules/chapters.json`) was empty on Cole's Mac. | Not a fault: it fills on the first prompt in a Sttark app repo. Filled with the hook's own gh check (revision 63). |
| D-f | Phase 5 | The inline guard accepted fewer command prefixes than the browser lock, so `timeout 600 npm test` in the main thread was not seen as a long run. | Fixed: one shared module `shell_commands.py` holds the splitter and the prefix list for both hooks. Validator: PASS. |
| I1 | Phase 0 | The org skills (`mt-*`, `bom-folder-check`, `onshape-asana-update`) come from the Claude app as a per-session plugin named `anthropic-skills:<name>`. They are not in `~/.claude/skills`, so a `claude` session started in Terminal does not see them. | Fixed: README note added. Routing itself is Phase 6 (D28). |
| I2 | Phase 2 | The kit hooks need Claude Code at `~/.local/bin/claude`. Without it, the STE check, Auto effort and the app rules refresh fail with `FileNotFoundError` and nobody is told. Fixed on Cole's Mac by installing Claude Code in Terminal. Other people who use only the Claude app have the same problem. The same code is on `main`. | PR https://github.com/Sttark/sttark-claude-kit/pull/75 open: menu Install item and one log line. App CLI fallback rejected because that copy is not signed in for headless use (D37). PR head 3cf5308, validator PASS; waiting for review and merge. |
| I5 | Phase 1 | The upstream skills refer to skills the kit does not ship: `verify` (`orchestrate`), deep-research (`researcher.md`). `code-review` is a Claude Code built-in. | Fixed: verify, deep-research and code-review mapped in the skill text. |
| I6 | Phase 1 | The `ops` agent may merge a PR "when the human has authorized that step". This conflicts with the production guard. | Fixed: merge removed from `ops.md`; merges only after `approve <action>`. |
| I7 | Phase 2 | `orchestrator-delegation` and `workflow-patterns` say web research stays in the main session. This conflicts with D6/D22 and the inline guard. The `researcher` agent has WebFetch but not WebSearch. | Fixed: WebSearch added to `researcher.md`; web research goes to the researcher. |
| I8 | Phase 2 | `validation-and-evidence` says the validator is a Sonnet-class agent, but `validator.md` sets Opus. This changes cost. | Fixed: validator uses Opus for code and UI, Sonnet otherwise; both files agree. |
| I9 | Phase 2 | The inline guard counts tool calls, not files. One Bash command can read many files (for example `head -1` on 3 files) and pass. The D6 rule "more than about 3 files of context" is not enforced. | Fixed: the guard counts files; it denies when the count plus the call's cost is over 2. |
| I10 | Phase 2 | The lookup limit is 2 per item. Cole decided to keep it. Routine chores in the main thread (build, install, commit) must go to an agent, which adds time. | Decided: keep 2 (D34). |
| I11 | Phase 2 | The guard hooks have no matcher, so a Python process starts on every tool call in every session while Orchestrator is on. | Fixed: matchers added so the guard runs only for the tools it acts on. |
| I12 | Phase 3 | Claude Code gives the `SubagentStart` hook the main session's folder as `cwd`. A subagent that works in another repo or worktree gets the Sttark context of the main session's repo. | Fixed: briefs name the target repo and add the Sttark context block. |
| I13 | Phase 3 | The hook's app repo test also counts a new repo with no remote. The agents' BLOCKED line counts a repo as Sttark only when its remote is under `github.com/Sttark`. | Fixed: BLOCKED line aligned with the hook's app repo test. |
| I14 | Phase 3 | The fallback block heading in `delegate-prompts` is "STTARK CONTEXT", but the agent files look for a "Sttark context" section. | Fixed: one name, "Sttark context". |
| I15 | Phase 3 | `subagent-rules-hook.py` exits 1 when the input is valid JSON but not an object. It does not block the subagent. | Fixed: the hook exits 0 on non-object input; test added. |
| I16 | Phase 3 | `install-hooks.py --orchestrator on` prints only "guard on" and does not mention the subagent rules. | Fixed: `--orchestrator` prints guard and subrules state. |
| I17 | Phase 3 | Subagents get the rule "pull latest from remote before you work". An agent in a worktree or in the middle of a task could pull and change its branch. | Fixed: subagents get no pull, switch or reset unless the brief says so. |
| I18 | Phase 1 | `grilling/agents/openai.yaml` was copied with the grilling skill. Claude Code does not use it. | Fixed: `openai.yaml` removed. |
| I19 | Phase 1 | When someone has their own skill with the same name as an orchestrator skill, the log says "left alone, not ours" on every launch. | Fixed: skip note logged only when the list changes. |
| I21 | I2 PR | `effort-hook.py` (about line 588) relaunches a session in `screen` with the CLI path and no check that the file exists. | Fixed in PR #75 (commits 05b309f and 3cf5308): `start_alone` skips the relaunch when Claude Code is missing; name-hook logs one line, not one per prompt. Validator: PASS. |
