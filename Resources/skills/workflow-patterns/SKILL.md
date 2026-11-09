---
name: workflow-patterns
description: >-
  Pattern catalog for multi-agent work: pick the right shape (fan-out, pipeline,
  generator+validator, adversarial review lenses, consensus/quorum, tournament,
  loop-until-dry, parallel worktree builds), size it to the stakes, and avoid the
  failure modes that already cost real time. Use when orchestrating more than one
  subagent — "fan this out", "run the 4-lens review", "tournament bug hunt",
  "build these tickets in parallel", "run rounds until dry", "which pattern should
  I use here". Don't use for the mechanics of a single delegation (prompt format,
  model pinning, verify-not-trust — use orchestrator-delegation) or the prompt
  templates themselves (use delegate-prompts). Don't use for unattended/recurring
  operation — the built-in loop/schedule skills own that.
  Don't use for research fan-outs on web topics — the deep-research skill owns those.
---

# Workflow patterns

How to shape multi-agent work. Each pattern says when it wins, how big to make it, and how it fails. Sizing follows a scale-to-stakes principle: solo for trivial work, 3–6 agents for routine builds, 3-5 review lenses added per item merging to main, 15–30+ reserved for audits and hard-to-reverse work (per-workflow total, e.g. roughly 7 agents per ticket across a multi-ticket batch). Model policy: haiku for mechanical steps, sonnet for execution, opus-class for hard review/synthesis — details in orchestrator-delegation.

**Harness note.** One proven reference implementation uses a Workflow-tool harness (`agent()`, `parallel()`, `phase()`, JSON schemas per agent) living under a repo's `.claude/workflows/` directory. That harness may NOT exist in every session. The patterns transfer unchanged to plain subagent fan-out (multiple Task/agent calls in one message = parallel; sequenced calls = pipeline). Never assume the Workflow tool is available — check, and fall back to plain subagents.

## Pattern catalog

### Fan-out (independent shards)
Split work into shards with no dependencies between them; launch all at once; collect results. Wins when shards are truly independent (per-file review, per-module survey, per-ticket triage). Size: 3–6 for routine, up to ~15 for audits; below 3 the coordination overhead beats doing it inline. Failure mode: hidden shared state — two shards editing the same file, or both claiming the same resource (see the migration-numbering collision in "Paid-for lessons" below). If shards write, pre-partition what each may touch.

### Pipeline (per-item stages, no barrier)
Each item flows through its own stage sequence (implement → verify → review → merge) independently — item 2 starts while item 1 is still in review. No global barrier waiting for all items to finish a stage. Wins for a batch of similar items (tickets) where per-item latency matters. Size: stages × items; keep in-flight items ≤ 3–4 unless isolation is airtight. Failure mode: cross-item ordering dependencies (stacked migrations, shared schema) — one reference workflow deliberately ran tickets SERIALLY so migrations stacked cleanly off freshly-merged main. If items share ordered state, serialize the items and pipeline only within each.

### Generator + validator
One agent produces, a separate agent (fresh context, ideally stronger model) checks against the acceptance criteria, and the generator repairs. One reference workflow's verify phase is this: an independent agent runs the typechecker plus the full test suite authoritatively — the implementer's own "tests green" claim is never trusted. Wins any time output quality matters more than latency. Size: +1 agent per generation step; bound repair rounds (2 is a reasonable cap). Failure mode: validator drift — a vague validator prompt rubber-stamps. Give the validator explicit pass/fail criteria and a structured output shape (see validation-and-evidence).

### Adversarial review lenses (the proven 4-lens)
Parallel reviewers, each restricted to ONE lens, each instructed to be hard and adversarial, each returning structured blockers with file:line + required fix. The proven set (one real run built and merged 4 tickets using 29 agents in under an hour): **correctness / security / migration-safety / test-coverage**, all opus-class, run in parallel after tests are green, synthesized by union — ANY blocker from ANY lens fails the round and feeds a bounded repair loop. Wins before any merge to main. Size: 3–5 lenses; more than 5 lenses mostly duplicates findings. Swap lenses to fit the work (e.g. drop migration-safety for a docs change, add privacy/perf where relevant). Failure mode: soft reviewers — without "raise a BLOCKER with exact file:line, what's wrong, why, and the precise fix," reviewers return nits and everything passes.

### Consensus / quorum voting
N independent agents answer the same question from fresh contexts; findings that K-of-N agree on are trusted, singletons get a second look. Wins for judgment calls with no oracle (is this design safe? which root cause?) and for high-stakes audits — a large adversarial consensus review on a real codebase once surfaced several HIGH-severity issues that single-pass review had missed. Size: 3–5 voters for a decision; 10–30 for a paid audit of hard-to-reverse work. Failure mode: shared blind spots — same prompt, same misses. Vary the framing/lens per voter, not just the temperature.

### Tournament (N independent attempts, judged)
N agents each attempt the whole task independently; a judge (opus-class, fresh context) picks the winner or merges the best parts. Wins when the solution space is wide (naming, architecture sketch, tricky bug where hypotheses differ) and a judge can compare cheaply. Size: 3–5 attempts; the judge is the expensive part, so don't tournament what a single sonnet-class agent does reliably. Failure mode: judge without criteria — give the judge an explicit rubric and make it justify the pick against each loser.

### Loop-until-dry (K dry rounds = done)
Repeat a whole round (e.g. a full bug-hunt fan-out) until a round produces zero new findings — or run a fixed round count and observe diminishing returns. Termination is defined by dryness, not by one pass "feeling" complete. Proven: a 3-round tournament bug hunt against a live stack found that later rounds still surfaced real P1 issues round 1 had missed — the whole argument for rounds. Wins for exhaustive hunts: bugs, security, dead code, doc drift. Size: rounds of 3–6 agents each; K=1–2 dry rounds to stop; hard-cap total rounds (~4–5) so it can't run away. Failure mode: agents re-reporting known findings makes rounds look wet forever — feed each round the deduped list of prior findings and count only NEW ones.

### Parallel worktree builds
Each agent builds its item in an isolated `git worktree` on its own branch; the orchestrator integrates serially afterward. Proven: four tickets built in parallel worktrees, each gated by a hard opus-class adversarial review plus a full test loop before PR. Wins when items are code-independent and wall-clock time matters. Size: 3–5 worktrees; beyond that integration review becomes the bottleneck. Failure modes: (a) shared sequential resources — migration numbers, journal files — collide (see the migration-numbering collision in "Paid-for lessons" below); (b) integration conflicts pile up — rebase each branch onto main serially, re-running tests after each. **Per-project rules can forbid this pattern entirely — check first (see below).**

## Selection matrix

| Task shape | Pattern | Typical size |
|---|---|---|
| Trivial edit, one file, low stakes | none — do it inline, solo | 0 extra agents |
| Survey/read many independent areas | fan-out | 3–6 sonnet/haiku |
| Batch of similar independent items | pipeline (serialize if state is ordered) | 3–4 in flight |
| One deliverable, quality-gated | generator + validator | 2–3 |
| Routine feature build to a PR | generator + validator + tests-first (tdd-protocol) | 3–6 |
| Anything merging to main | add adversarial 4-lens review | +4 opus-class lenses/item |
| Judgment call, no oracle | consensus/quorum | 3–5 voters |
| High-stakes / hard-to-reverse audit | consensus at scale + loop-until-dry | 15–30+ |
| Wide solution space, comparable outputs | tournament | 3–5 attempts + 1 judge |
| Exhaustive hunt (bugs/security/drift) | loop-until-dry over fan-out rounds | 3–6/round, K=1–2 dry |
| Multiple code items, wall-clock bound | parallel worktrees (if repo allows) | 3–5 worktrees |

## Paid-for lessons (hard rules) (canonical catalog — orchestrator-delegation and delegate-prompts reference this section; edit lessons HERE)

Each of these cost real time. Treat them as non-negotiable:

1. **Pre-assign shared sequential resources before parallel builds.** Two worktree agents once both generated the same migration number because one ignored its reservation. Assign migration numbers / journal slots / port numbers in the launch prompt, and have the integration step verify the assignment held.
2. **PR + merge stays OUT of workflows — the orchestrator does it serially.** Merges hit permission prompts, need conflict resolution (append-only journal files both sides touched), and must be recorded. Agents build and commit on branches; the orchestrating session opens PRs and merges one at a time.
3. **Never delete-branch-on-merge unless the merge already succeeded.** Passed on a failed merge once, it closed the PR and deleted the branch anyway. Confirm mergeable, merge, and only then delete the branch. If not mergeable: stop, delete nothing.
4. **Commit the working tree before launching any agents.** A subagent's `git checkout`/`git reset` once destroyed uncommitted ledger changes. The orchestrator's first act before a fan-out is a WIP-safe commit (or verifying `git status --porcelain` is clean).
5. **Give agents absolute paths — the background sandbox strips PATH and resets cwd.** `cd` does not persist between calls; use `git -C <repo> ...` and full paths to binaries/repos in every agent prompt. (`~`-relative is fine in skills; expand to absolute in the actual prompts.)
6. **Web research runs in the main session, or with a timeout fallback.** Web search once stalled inside subagents and burned hours before the workflow was declared dead. If a subagent must search the web, give it an explicit time budget and a "proceed without" fallback; prefer doing the search yourself and passing results in.
7. **Split oversized single-pass tasks before delegating.** One workflow stalled because a single task was too large for one pass — it had to be split into smaller tickets. If a ticket needs more than one coherent test-first slice, split it into separate tickets first (in your issue tracker), then run the pattern per slice.

## Per-project rules constrain pattern choice

A project's own CLAUDE.md rules always beat this catalog. A repo might forbid creating or applying a git stash, managing git worktrees, or switching branches unless asked — so parallel worktree builds would be off the table there; use fan-out over read-only shards plus serial in-place builds instead. Another repo might have an out-of-scope lock (no tooling installs, no deploys). Check the repo's CLAUDE.md for this class of rule before picking a pattern, every time.

## Scope

This skill picks and sizes the SHAPE of multi-agent work. It does not cover: how to write the individual delegation (model choice, subagent file format, verify-not-trust — orchestrator-delegation), the prompt templates (delegate-prompts), evidence/done-criteria standards inside a validator (validation-and-evidence), unattended or recurring operation (the built-in loop/schedule skills), tests-first mechanics (tdd-protocol), or issue-tracker hygiene (keep your tracker current).

## Provenance and maintenance

This catalog comes from patterns proven across real multi-agent workflows, not theory: parallel-lens reviews, hard merge gates, worktree builds, and large consensus reviews have each caught real issues or saved real time. Treat the exact counts and outcomes above as illustrative, not guaranteed results.

Re-verify drift periodically:
- Confirm whether your harness still exposes a Workflow-tool style API (`agent()/parallel()`) before assuming it does; check the session's available tools first.
- Confirm any repo-level constraints on git worktrees, stashing, or branch switching are still current by reading that repo's own CLAUDE.md.
