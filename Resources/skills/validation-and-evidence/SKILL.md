---
name: validation-and-evidence
description: >-
  Use when deciding whether work is actually DONE — before claiming "it works", "fixed",
  "tests pass", or "ready to merge", when ending any non-trivial build, or when a high-stakes
  change (merge to main, prod-adjacent, hard to reverse) needs adversarial review. Owns the
  evidence standard (what counts as proof), the standing independent validator pass, the
  adversarial-review patterns (parallel lenses, hard opus gate, consensus review), P1/P2/P3
  severity discipline, and per-repo done-criteria. Trigger on "validate this", "is this
  actually done", "prove it works", "review before merge", "run the validator". Don't use for
  actually running the app to observe behavior — that's the built-in verify skill (use it as
  one evidence source). Don't use for plain diff review — that's the built-in code-review
  skill. Don't use for writing the tests themselves (tdd-protocol) or filing the bugs found
  (your issue tracker).
---

# Validation and evidence

This skill sets the STANDARD for what counts as proof and the PROCESS for checking finished
work. It exists because "looks right" has repeatedly not been right. Confident guessing is not
welcome here: if you don't have evidence, say so plainly and go get it — never assert.

## The evidence bar

A claim of "working" requires observable proof. Acceptable evidence, roughly strongest first:

| Evidence | Example |
|---|---|
| Test output | full suite run, exit code 0, pass/fail counts pasted |
| Command output | typecheck clean, `curl` response body, migration `status` output |
| Queried data | row actually in the DB, API returns the new field |
| Screenshot / rendered output | UI state, rendered video frame |
| Reproduced-then-gone | bug repro steps fail before the fix, succeed after |

Not evidence: "the code looks correct", "this should work", "I implemented it as specified",
a passing suite that never exercised the changed path, or a linter pass.

Rules:

- **Measurable beats eyeballed, always.** A pasted number, exit code, or diff of actual vs
  expected outranks a visual impression. If you eyeballed it, say "eyeballed, unverified".
- **One mechanism must explain ALL observations — including the negatives.** If your theory
  of the bug (or of why the fix works) doesn't account for every symptom, the case where it
  DIDN'T fail, and why the fix changes the behavior, you don't have the mechanism yet. Keep
  digging before claiming done.
- **Evidence is quoted, not summarized.** Paste the relevant lines of output into the report.
  "Tests pass" without the count and command is an assertion, not evidence.
- **Run the app when the claim is behavioral.** Use the built-in `verify` skill to launch the
  app and observe the behavior — that observation is one evidence source under this standard.

## The standing validator pass

Every non-trivial build ends with an INDEPENDENT validator agent — never the builder checking
its own homework. The builder has motivated reasoning about its own diff; a fresh agent with
only the acceptance criteria does not. Scale per workflow-patterns: one sonnet-class validator
for routine builds; the adversarial patterns below for high-stakes work.

Validator prompt skeleton (compact — the full uplifted template lives in delegate-prompts):

```
You are an independent validator. You did NOT write this change; trust nothing you
haven't run yourself.

INPUTS
- Acceptance criteria: <numbered list, verbatim from the ticket/spec>
- The change: <branch/diff location, files touched>
- How to run: <exact build/test/run commands for THIS repo>

TASK
1. For EACH criterion: mark PASS or FAIL, with pasted evidence (command + output,
   query result, or observed behavior). No evidence = FAIL.
2. Actively try to break it: edge inputs, the empty case, the error path.
3. Report anything broken NEARBY that the diff plausibly caused, even if outside
   the criteria.

OUTPUT: per-criterion PASS/FAIL table with evidence, then a list of nearby breakage
with severity (P1/P2/P3), then a one-line verdict: SHIP / FIX FIRST.
```

A FAIL or P1 from the validator blocks the done claim. The builder (or a repair agent) fixes,
then the validator re-runs — the same validator context re-checks; don't grade your own retry.

## Adversarial review for high-stakes changes

For merges to main, prod-adjacent work, and anything hard to reverse, one validator is not
enough. Three patterns worth having ready (pattern mechanics live in workflow-patterns;
prompts in delegate-prompts):

- **Four parallel lenses** (proven on a real ticket-automation workflow): spawn 4 reviewers in
  parallel, each with ONE mandate — correctness, security, migration safety, test coverage.
  A single generalist reviewer skims; a single-mandate reviewer digs. Synthesize findings,
  self-repair bounded, re-review.
- **Hard opus review gate** (proven on a 4-ticket parallel worktree build): before any
  PR/merge, an opus-class adversarial review plus a full test loop must pass. The gate is
  hard — no green, no merge. Merges stay serial in the orchestrating session.
- **Consensus review** (proven on a large real codebase): for the highest stakes, a large
  fan-out of independent reviewers over the same code — a 29-agent consensus review once
  found several HIGH-severity issues a single pass had missed. Findings that multiple
  independent agents converge on are near-certain; singletons get verified before filing.

Learned the hard way across many bug hunts: reviews that report "concerns" without severity
produce noise no one can act on. Every finding gets a severity:

| Level | Meaning | Test |
|---|---|---|
| P1 | Wrong results, data loss, security hole | Would this send a user confidently down a wrong path? |
| P2 | Broken edge case, misleading behavior | Wrong under conditions that will realistically occur |
| P3 | Hygiene, robustness, minor gap | Worth fixing, harms no one today |

The "wrong path" framing is the P1 discriminator: silent wrongness outranks loud breakage,
because loud breakage gets noticed and silent wrongness gets trusted.

## Done-criteria per repo

"Green" is repo-specific — the per-ecosystem test-command index lives in tdd-protocol; use its
commands as the mechanical half of done. One real project's standing definition of green lives
in tdd-protocol's completion gate (typecheck + types build + full test suite + schema-drift
check) — cite it, don't restate it.

If a repo has no written definition of done, write one into that repo's NEXT.md the first
time you validate there (a short "Definition of green" block: the exact commands and what
clean output looks like), so the next session — human or agent — validates against the same
bar. NEXT.md conventions live in context-and-state.

## What to do with findings

- Bugs found during validation that won't be fixed in this change get filed in your issue
  tracker, with a clear defect-statement title, a severity line, file:line, and repro steps.
  A finding that lives only in a chat transcript is lost.
- Fixed-in-this-change findings get a line in the PR/report with their evidence of the fix.
- Validation outcomes worth remembering (a class of bug, a gap in a repo's harness) go into
  your notes or your team's knowledge base so the lesson survives past this session.

## Scope

This skill owns the STANDARD for proof and the validator/adversarial PROCESS. It does not:
run the app itself (built-in `verify` does that — its output feeds this standard), perform
inline diff review (built-in `code-review`), write tests or define the TDD loop
(tdd-protocol), choose fan-out sizes and workflow shapes (workflow-patterns), hold the full
validator prompt templates (delegate-prompts), or manage your issue tracker.

## Provenance and maintenance

This standard comes from real validation and bug-hunt cycles, not theory: parallel-lens
reviews, hard merge gates, and large consensus reviews have each caught real issues that
single-pass review missed. Treat the exact counts above as illustrative, not guaranteed
results.

Re-verify drift periodically:
- Confirm the sibling skills referenced here (tdd-protocol, delegate-prompts,
  workflow-patterns) still exist in your skill set.
- Confirm your project's own definition of green (test/typecheck/lint commands) is still
  current by reading its CLAUDE.md or equivalent.
