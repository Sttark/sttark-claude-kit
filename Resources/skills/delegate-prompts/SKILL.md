---
name: delegate-prompts
description: >-
  Use when actually WRITING the prompt for a subagent dispatch — an implementation
  task, test authoring, a research question, a review lens, a validation pass, or a
  refactor. Contains the five-element uplift anatomy (context injection, acceptance
  criteria, output contract, worked example, self-verification checklist) and six
  copy-adaptable templates with <PLACEHOLDERS>: implement-to-tests, test-author,
  research-brief, adversarial-reviewer, validator, refactor. Triggers: "write the
  delegate prompt", "what do I tell the subagent", "prompt for the implementer/
  reviewer/validator", "uplift prompt template". Don't use for deciding WHETHER to
  delegate or which model runs it — use orchestrator-delegation. Don't use for
  picking the multi-agent shape (fan-out vs pipeline vs tournament) — use
  workflow-patterns. Don't use for the evidence standards themselves — use
  validation-and-evidence. Don't use for the tests-first doctrine — use tdd-protocol.
---

# Delegate prompts

A subagent starts with zero context: no conversation history, no memory, no idea what the user wants. The difference between a mid-tier agent performing at top-tier level and one flailing is almost entirely the prompt. This skill is the template library. orchestrator-delegation decides WHEN to delegate and on what model; this skill supplies WHAT to say.

Definition used throughout: the **orchestrator** is the main session dispatching the work; the **delegate** is the subagent receiving one of these prompts.

## The anatomy — five elements, every prompt, no exceptions

1. **CONTEXT INJECTION** — everything the delegate needs, stated explicitly in the prompt: absolute repo path, the exact files in play, project conventions that apply (test command, lint rules, migration quirks), relevant decisions already made, and what NOT to touch. If the orchestrator discovered something in this session (a root cause, a version quirk, a failing test name), it goes IN the prompt — the delegate cannot see the conversation.
2. **ACCEPTANCE CRITERIA** — explicit, testable, numbered. "1. The test command exits 0. 2. No file outside src/ modified. 3. Typecheck clean." Never "make it good" or "fix the bug properly".
3. **OUTPUT CONTRACT** — the exact format of the final message: fields, order, length caps. Tell the delegate: *your final message is data the orchestrator parses, not conversation*. No preamble, no "I hope this helps".
4. **WORKED EXAMPLE** — when the output format matters (structured findings, JSON-ish reports), show one filled-in example. Format compliance without an example is a coin flip.
5. **SELF-VERIFICATION CHECKLIST** — 3-5 checks the delegate runs BEFORE returning: did you actually run the command (not infer the result)? does every claim cite file:line or pasted output? does the output match the contract?

If a drafted prompt is missing any element, it is not ready to dispatch.

## Hard rules baked into the templates

- **Absolute paths everywhere**: a sandboxed execution environment can strip PATH for write/git commands. Templates tell delegates to use absolute paths for the repo and to run commands from an explicit directory, never rely on cwd or PATH lookups working.
- **No open-ended web search inside delegates**: a long research workflow once died on a web-search tool stalling inside a subagent. Research templates restrict delegates to repo files, local docs, and explicitly provided URLs via fetch; anything needing live web search stays in the orchestrator.
- **Worktree lockdown**: an implementation agent's `git checkout`/`reset` once reverted the orchestrator's own uncommitted state. Every code-touching template forbids `git checkout`, `git reset`, `git stash`, and branch switching outside the delegate's assigned worktree/branch.
- **Index before grep**: agents default to grep and whole-file reads, and every extra search round re-sends the agent's full context. When the repo has a code-index or code-graph search tool, every brief's CONTEXT INJECTION names it and says: run it before any grep, from the repo or worktree root; read only the lines it returns; grep only for an exact symbol you already know. Index folders are often gitignored, so a fresh worktree has none: tell the delegate where the main checkout's index is, or use a tool that falls back to it.
- **Model per dispatch**: set the model explicitly on every dispatch. A mid-tier model for research, review lenses and small fixes; the strongest model only for the main build and the final validation. An unset model inherits the orchestrator's, which is usually the most expensive one.
- **Split oversized tasks**: a delegated build once stalled repeatedly because the task was too large for one pass. If a template's placeholders won't fit one coherent task ("implement X **and** Y **and** migrate Z"), stop and split into multiple dispatches — no prompt fixes a task that doesn't fit in one pass.

## Template 1 — implement-to-tests

Use when failing tests already exist (written by you, a test-author delegate, or per tdd-protocol) and the delegate's only job is making them green.

```
You are implementing a scoped change in <ABS_REPO_PATH> on branch <BRANCH> (your assigned
worktree: <ABS_WORKTREE_PATH>). You have no other context — everything you need is below.

CONTEXT
- Repo conventions: <TEST_FRAMEWORK, LINT RULES, LAYERING RULES, RELEVANT PROJECT RULES>
- The failing tests are in <ABS_TEST_FILE_PATHS>. They encode the full intended behavior.
- Relevant discoveries: <ROOT CAUSE / QUIRKS THE ORCHESTRATOR ALREADY KNOWS>
- Do NOT touch: <PATHS OFF LIMITS — e.g. the test files themselves, migrations, other agents' files>

TASK
Make the failing tests pass by changing production code only. Run the suite with exactly:
  cd <ABS_REPO_PATH> && <EXACT_TEST_COMMAND>
Modifying, deleting, or skipping any test is FORBIDDEN. If a test looks wrong, stop and
report it as BLOCKED with your reasoning — do not "fix" the test.

HARD RULES
- Use absolute paths in all commands; do not rely on cwd or PATH.
- Never run git checkout / reset / stash / branch-switch outside <ABS_WORKTREE_PATH>.
- Commit only your own changes, on <BRANCH>, message: <COMMIT_MESSAGE_CONVENTION>.

ACCEPTANCE CRITERIA
1. <EXACT_TEST_COMMAND> exits 0 — full suite, not just the new tests.
2. <TYPECHECK/LINT COMMAND> clean.
3. No test file modified (verify with git diff --stat).
4. No files changed outside <ALLOWED_PATHS>.

OUTPUT CONTRACT — your final message is data, not conversation:
STATUS: DONE | BLOCKED
DIFF SUMMARY: <files changed, one line each: path — what and why>
TEST OUTPUT: <last ~10 lines of the real test run, pasted verbatim>
NOTES: <anything the orchestrator must know; omit if none>

Before returning, verify: (1) you ran the test command and pasted REAL output, not a
prediction; (2) git diff --stat shows no test files; (3) your message matches the contract.
```

## Template 2 — test-author

Use to turn a behavior spec into failing tests, before any implementation exists (the red step of tdd-protocol).

```
You are writing tests in <ABS_REPO_PATH> (branch <BRANCH>). No implementation exists yet —
or the current one is wrong. Your tests define the target behavior.

CONTEXT
- Test framework and location: <FRAMEWORK, WHERE TESTS LIVE, NAMING CONVENTION>
- Run tests with exactly: cd <ABS_REPO_PATH> && <EXACT_TEST_COMMAND>
- Existing test patterns to imitate: <ABS_PATH_TO_A_GOOD_EXISTING_TEST_FILE>
- Behavior spec (complete — do not invent behavior beyond it):
  <NUMBERED BEHAVIOR ASSERTIONS: inputs, outputs, edge cases, error cases>

TASK
Write one test per numbered assertion. Each new test must FAIL when run now, and fail for
the RIGHT reason — because the behavior is missing (e.g. function undefined, wrong value
returned), not because of an import error, typo, or broken setup. Run the suite and check
each failure message yourself.

HARD RULES
- Touch only test files and test fixtures. Zero production code changes.
- Never run git checkout / reset / stash outside your assigned branch.
- Use absolute paths in all commands.
- If an assertion is untestable as specced, mark it BLOCKED with why — don't guess intent.

ACCEPTANCE CRITERIA
1. Every numbered assertion has exactly one corresponding test.
2. Every new test fails, and the failure message reflects missing behavior (paste it).
3. Pre-existing tests still pass (you broke nothing).

OUTPUT CONTRACT — your final message is data, not conversation:
STATUS: DONE | BLOCKED
TESTS WRITTEN: <assertion # -> test name -> file:line>
FAILURE EVIDENCE: <per test: the pasted failure message proving it fails for the right reason>
PRE-EXISTING SUITE: <pass/fail line from the run>
```

## Template 3 — research-brief

Use for a scoped factual question answered from the repo and provided sources. Saying UNKNOWN is a valid, preferred outcome — a delegate that guesses poisons the orchestrator's decisions.

```
You are researching one question about <ABS_REPO_PATH or SYSTEM>. Answer from evidence
only. "UNKNOWN" is an acceptable and respected answer — a confident guess is not.

QUESTION
<ONE PRECISE QUESTION — if you have two questions, dispatch two agents>

WHERE TO LOOK FIRST
<ORDERED LIST: specific files/dirs, local docs like node_modules/<pkg>/docs, config files,
git log for <PATH>, and any exact URLs the orchestrator provides for fetching>

HARD RULES
- Do NOT use open-ended web search — it stalls in subagents. You may fetch only the exact
  URLs listed above. If the answer needs open-ended web research, return UNKNOWN and say
  so; the orchestrator will handle it.
- Every claim in your answer must carry a citation: file:line, command + pasted output,
  or one of the provided URLs. An uncited claim is worthless.
- Distinguish clearly: VERIFIED (you saw it) vs INFERRED (you deduced it) vs UNKNOWN.

OUTPUT CONTRACT — your final message is data, not conversation:
ANSWER: <direct answer, 1-3 sentences, or UNKNOWN>
CONFIDENCE: VERIFIED | INFERRED | UNKNOWN
EVIDENCE: <bulleted citations, each tied to part of the answer>
GAPS: <what you could not determine and what would resolve it>

Before returning: (1) is every sentence in ANSWER backed by an EVIDENCE bullet?
(2) did you resist filling gaps with training-data knowledge? (3) if you're below
~90% sure, did you downgrade to INFERRED or UNKNOWN?
```

## Template 4 — adversarial-reviewer

Use one dispatch PER LENS — correctness, security, migration, coverage — with fresh agents that did not write the code. Lens assignment and fan-out sizing live in workflow-patterns.

```
You are an adversarial reviewer. Your ONE lens: <LENS — e.g. correctness | security |
migration safety | test coverage>. Ignore everything outside your lens; other agents
cover other lenses. Your job is to BREAK this change, not to approve it. Finding
nothing after a real attempt is a valid result; rubber-stamping is a failure.

CONTEXT
- Repo: <ABS_REPO_PATH>, branch <BRANCH>. Review the diff vs <BASE_BRANCH>:
  cd <ABS_REPO_PATH> && git diff <BASE_BRANCH>...<BRANCH>
- The change claims to: <THE BUILDER'S CLAIM / TICKET SUMMARY>
- Known conventions your lens must enforce: <LENS-SPECIFIC RULES — e.g. "every read
  filters soft-deleted rows", authorization checks, ordering guarantees>

TASK
Read the full diff and the surrounding code it touches. For your lens, actively hunt:
<LENS-SPECIFIC ATTACK LIST — e.g. correctness: edge cases, off-by-one, error paths,
concurrency; security: injection, authz gaps, secrets in code; migration: reversibility,
data loss, ordering; coverage: untested branches, tests that can't fail>. You are
READ-ONLY plus running commands: never edit files, never git checkout/reset/stash.

OUTPUT CONTRACT — your final message is data, not conversation:
LENS: <lens>
VERDICT: PASS | FINDINGS
FINDINGS (most severe first, empty if PASS):
- [P1|P2|P3] <one-line defect> | <file:line> | <concrete failure scenario: input/state ->
  wrong outcome> | <evidence: code excerpt or command output>
Severity: use the canonical P1/P2/P3 rubric from validation-and-evidence verbatim (P1 = would
send someone down a wrong path / data loss / security; P2 = broken edge case or misleading
behavior; P3 = polish). If your local copy of that skill differs, the skill wins.

Example finding:
- [P1] totals ignore soft-deleted rows filter | src/routers/stats.ts:84 |
  a deleted record still counts toward the weekly total -> user sees inflated stats |
  query lacks the deleted-row filter present in every sibling router

Before returning: (1) is every finding anchored to file:line with a concrete failure
scenario, not a style opinion? (2) did you stay inside your lens? (3) if VERDICT is
PASS, did you actually attempt the attack list, and can you say what you tried?
```

## Template 5 — validator

Use as the independent check after a builder returns. The builder's claims are hypotheses; the validator's job is to test them. What counts as sufficient evidence is defined in validation-and-evidence.

```
You are an independent validator. A builder agent claims to have completed the work
below. Treat every claim as a HYPOTHESIS to test yourself — you trust nothing you
did not run or read with your own tools. You did not write this code and owe it nothing.

CONTEXT
- Repo: <ABS_REPO_PATH>, branch <BRANCH> (worktree <ABS_WORKTREE_PATH>).
- The builder's claims: <PASTE THE BUILDER'S RETURNED SUMMARY>
- How to run everything: cd <ABS_REPO_PATH> && <EXACT TEST / TYPECHECK / BUILD COMMANDS>

ACCEPTANCE CRITERIA TO VALIDATE (verbatim from the original dispatch):
<NUMBERED CRITERIA — same numbers as the builder received>

TASK
For each criterion: run the check yourself, read the relevant diff/files yourself, and
record PASS or FAIL with evidence. Re-run commands even if the builder pasted output —
pasted output proves it passed once, not that it passes now. You are read-only plus
running commands: never edit files, never git checkout/reset/stash outside
<ABS_WORKTREE_PATH>, and use absolute paths in every command.

OUTPUT CONTRACT — your final message is data, not conversation:
VERDICT: PASS | FAIL
PER-CRITERION:
1. PASS|FAIL — <evidence: command + last lines of real output, or file:line read>
2. ...
DISCREPANCIES: <anywhere the builder's claims and your observations diverge>
RISKS: <anything true-but-worrying the criteria didn't cover; omit if none>

Before returning: (1) did you re-run every runnable check rather than trust pasted
output? (2) does each criterion line carry its own evidence? (3) is VERDICT derivable
from the per-criterion lines alone?
```

## Template 6 — refactor

Use for behavior-preserving restructuring. The entire safety argument is: tests green before, tests green after, nothing else changed.

```
You are refactoring in <ABS_REPO_PATH> on branch <BRANCH> (worktree <ABS_WORKTREE_PATH>).
This is a BEHAVIOR-PRESERVING change: externally observable behavior must be identical
before and after. If the refactor requires a behavior change, STOP and return BLOCKED.

CONTEXT
- What to refactor and why: <TARGET FILES/MODULES + THE STRUCTURAL GOAL, e.g. "extract
  the shared pagination logic from these three routers into one helper">
- Conventions to preserve: <LAYERING RULES, NAMING, ERROR-WRAPPING PATTERNS>
- Test command: cd <ABS_REPO_PATH> && <EXACT_TEST_COMMAND>

TASK
1. FIRST run the full suite and record the result. If it is not green, return BLOCKED
   immediately — refactoring on a red suite proves nothing.
2. Refactor in small steps, re-running the suite as you go.
3. AFTER: full suite green again, same test count (no tests added, removed, or skipped).

HARD RULES — no scope creep:
- No new features, no bug fixes (report bugs you notice as NOTES; do not fix them),
  no dependency changes, no "while I'm here" cleanups outside <TARGET FILES/MODULES>.
- Never git checkout / reset / stash outside <ABS_WORKTREE_PATH>; absolute paths always.

ACCEPTANCE CRITERIA
1. Suite green BEFORE (pasted) and AFTER (pasted), identical test counts.
2. <TYPECHECK/LINT COMMAND> clean.
3. git diff touches only <TARGET FILES/MODULES>.
4. Public interfaces unchanged unless listed here: <ALLOWED_INTERFACE_CHANGES or "none">.

OUTPUT CONTRACT — your final message is data, not conversation:
STATUS: DONE | BLOCKED
BEFORE: <test summary line, pasted>   AFTER: <test summary line, pasted>
STRUCTURE: <2-5 lines: what moved where and why it's better>
NOTES: <bugs noticed but NOT fixed, follow-up suggestions; omit if none>
```

## Adapting a template

- Fill every `<PLACEHOLDER>`; an unfilled placeholder means the orchestrator hasn't done its context-gathering job yet.
- Keep the five elements intact when trimming. The first thing people cut — the self-verification checklist — is the cheapest quality gate in the whole system.
- One task per dispatch. If the TASK section grows an "and", split it.
- Repo-specific conventions (exact test commands, migration quirks) come from that repo's own documentation — inject them; the delegate will not go read them reliably on its own.

## Scope

This skill owns the delegate prompt TEXT: the anatomy and the six templates. It does not decide whether to delegate, which model to pin, or how to define agents in `~/.claude/agents/` (orchestrator-delegation); does not choose fan-out shape or size (workflow-patterns); does not define what evidence counts as done or run the review process (validation-and-evidence); does not set the tests-first doctrine the implement/test templates assume (tdd-protocol); does not cover unattended runs. Per-project rules always override template defaults — e.g. a project may forbid agents from touching worktrees, stashes, or branches at all, or carry its own standing out-of-scope list.

## Provenance and maintenance

The five-element anatomy restates the sibling skill orchestrator-delegation's uplift doctrine in template form. The embedded hard rules (absolute paths, no open-ended web search in delegates, worktree lockdown, split oversized tasks) come from real incidents where skipping them cost real time; the templates encode the fix, not the story.

Re-verify on drift:
- `ls ~/.claude/skills/ | grep -E 'orchestrator-delegation|workflow-patterns|validation-and-evidence|tdd-protocol'` — cross-referenced siblings still exist
- Spot-check one repo's exact test command against its own conventions before reusing an old filled-in template — test commands are heterogeneous per project and drift
