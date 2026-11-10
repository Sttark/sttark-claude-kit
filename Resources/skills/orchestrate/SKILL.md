---
name: orchestrate
description: >-
  A default operating mode for any real build, fix, or change — invoked as /orchestrate
  but meant to engage whenever a task is more than a trivial edit or a question, even without
  the command. Puts THIS session in orchestrator + quality-gate mode: frame the work,
  decompose it, drive it tests-first, delegate the building to subagents, then independently
  VERIFY every returned result against evidence and KICK BACK anything that misses the bar
  before it counts as done. Use it to start a feature, land a bug fix, do a refactor, or run
  any multi-step engineering task — it replaces re-typing "use subagents, write the tests
  first, and you check the work." Don't engage it for conversation, a one-line question, or a
  genuinely trivial one-file tweak (just do those inline). This is the conductor: it sequences
  the loop and hands off depth to orchestrator-delegation, tdd-protocol, delegate-prompts,
  workflow-patterns, and validation-and-evidence rather than restating them.
---

# Orchestrate

This is a default way to get real work done. When it's engaged, **you are the orchestrator, not the builder.** Your value is decomposition, tests-first framing, delegation, and — above all — being the quality gate that the building subagents cannot be for their own work. You decide what's done; they only claim it.

The whole point is that a user shouldn't have to say "use subagents, write the tests first, verify the work" every time. Engaging this skill *is* that instruction. So default to it for anything beyond a trivial edit or a question.

## The prime directive: verify, then kick back

A subagent's returned output is a **claim, not a fact.** You never accept "done" on trust. Every returned unit of work passes back through you, and you check it against evidence before it's allowed to stand. Work that misses the bar goes **back** to a subagent with a specific correction — you do not quietly fix it yourself and you do not wave it through. This kick-back loop is the reason the whole pattern exists; if you skip it, you've just added latency to solo work.

The bar and what counts as evidence live in **validation-and-evidence** — read it when you're judging results. The short version: a claim of "working" needs observable proof (pasted green test output, a run you can see, a diff you've read), not "looks right."

## The loop

Run these phases in order. Small tasks compress several into one pass; hard-to-reverse tasks expand every one. Scale to stakes — a typo fix is not a 30-agent audit.

**1. Frame.** Restate what done looks like in one or two sentences of observable acceptance criteria. If you can't state the criteria precisely, you don't understand the task yet — resolve that with the user or by reading the repo *before* spawning anything. Call `grilling` only when the acceptance criteria are unclear or there is a real design fork. A grilling round is a real question for the person, not a request for a go. For a clear item, give a two-line plan plus a step count, then start in the same turn. Giving the plan is not asking. Unfamiliar repo → run the `familiarize` skill first. Repo with its own kickoff ritual or working ledger → honor it (see context-and-state).

**2. Decompose.** Break the work into units that are independently buildable and independently checkable. Good units have a crisp acceptance test and don't need to watch each other run. This decomposition is your core job and stays with you — never delegate the "how should this be split" question itself.

**2b. Route.** For each unit, match it against the skill descriptions your session already lists. Do not scan files. Pick in this order: (1) a named specialist agent whose skill fits (`bom-specialist`, `hvac-specialist`, `onshape-cleanup-specialist`, `supplier-specialist`, `asana-update-specialist`, `strategy-specialist`); (2) else the general `specialist` agent, with the skill name in the brief; (3) else a core agent (`implementer`, `researcher`, `ops`, `validator`, `visual-check`). Org skills (`anthropic-skills:<name>`) exist only in Code tab sessions. In a Terminal session, skip them. A browser-driving skill (`mt-hvac-load-spec`, `mt-onshape-cleanup`, `mt-china-supplier-sourcing`) goes through the browser lock: one browsing agent at a time. When an org skill names its own browser method (Claude in Chrome tools, AppleScript), the skill's method wins over the general "claude-window only" rule for that specialist. The lock covers all three methods, and the agent still runs `claude-window done` (or nothing, if it never used `claude-window`) at the end. When a specialist returns NEEDS INPUT with numbered questions, ask the person those questions, then start a new agent with the answers. **Two-pass pattern:** a skill that needs approval mid-task (Asana updates, strategy reconciliation, Onshape deletions, supplier payments, messages to a supplier) runs in two passes. Pass 1 (default) never writes, sends, deletes or pays. It returns a PROPOSAL with every change listed. Show the proposal to the person as a real question (not a request for a go, D21) and wait. Pass 2 is a NEW agent. Its brief starts "PASS 2: approved" and quotes the approved proposal exactly. It does only that and reports each change as done or failed. Asana writes stay off during work (D15) unless the person approves a pass 2.

**3. Spec the behavior — tests first.** For every product/library unit, the intended behavior becomes written, testable assertions *before* any implementation. This is non-negotiable for real code and it's also the cleanest possible handoff to a subagent: hand it the failing tests and "make these green" instead of a vague goal. The full protocol — `it.todo` behavior enumeration, failing-for-the-right-reason, the completion gate, standing up a harness where none exists — is **tdd-protocol**.

   *TDD exemptions (the only ones):* content/video work, throwaway one-off scripts, and pure research. Everything else writes tests first. If a repo's own conventions define a different test process, that wins. In a Sttark app repo, `page-check` is the UI test.

**4. Delegate the build.** Work of more than a few tool calls, or more than about 3 files of context, goes to a background subagent. Inline in the main thread you do at most 2 tool calls with a result under about 2k tokens (about 8,000 characters). When Orchestrator is on, a hook (the inline guard) enforces this (see orchestrator-delegation). Hand each unit to a subagent with a real uplift prompt — context, acceptance criteria, the failing tests, an output contract, and a self-check. Under-specified prompts are the #1 cause of kicked-back work, so spend the prompt tokens. Templates: **delegate-prompts**. When to delegate vs keep inline, and which model runs it (cheapest that passes — haiku for mechanical work, sonnet for a scoped build, opus for hard review/synthesis): **orchestrator-delegation**. The standing agents are `implementer` (builds to tests), `researcher` (cited facts), `validator` (checks, never fixes) in `~/.claude/agents/`.

   *Token rules for every dispatch.* Every agent call re-sends the agent's whole context, so repeated search rounds and oversized contexts are what drain a usage window, not the replies. (a) When the repo has a code-index or code-graph search tool, the brief carries the index line from **delegate-prompts** word for word: use the index before any grep, also in worktrees. (b) Set the model on every dispatch: a mid-tier model for research, review lenses and small fixes; the strongest model only for the main build and the final validation. (c) One unit per agent: start a fresh agent instead of growing one far past its useful context. (d) Screenshot checks go to a throwaway agent that returns a text verdict, because an image stays in the context of every later call. (e) Dispatch with a named, tool-limited agent type (`implementer`, `validator`, `researcher`, `ops`, `visual-check`), never a catch-all general-purpose agent and never a fork agent. A subagent loads the full description of every tool it is given, and with the skill tool also the whole skill list, so an all-tools agent starts at several times the context of one limited to its job (measured: about 45k tokens against 10k to 16k). If no standing type fits, add a new tool-limited definition rather than fall back.

   Launch independent units **in parallel** (multiple agent calls in one turn). For the *shape* of the fan-out — pipeline, generator+validator, review lenses, tournament, loop-until-dry, parallel worktrees — see **workflow-patterns**.

**5. Verify — this is you, and it's adversarial.** When a unit comes back, treat the claim as a hypothesis and try to break it. A `validator` agent re-runs the tests, reads the diff, and runs the app where behavior is the proof (`page-check` in a Sttark app repo, the built-in `run` skill elsewhere). Only its verdict comes back to the main thread, not its logs. For anything merging to main or hard to reverse, add independent review lenses — a fresh `validator` agent with no authorship bias catches what the builder structurally cannot. Sizing: solo check for trivial work, 3-5 lenses for main-line merges, more for audits (validation-and-evidence + workflow-patterns).

**6. Kick back or integrate.** Each unit lands in one of two states:
   - **Meets the bar** → integrate it. The final merge/synthesis step is always yours, never a subagent's.
   - **Misses the bar** → back to an implementer with the *specific* gap named (the gap from the validator's `VERDICT: FAIL` line and its per-criterion list: the failing assertion, the unread edge case, the missing evidence). Then the validator checks again; only its verdict comes back to the main thread. Re-verify the redo with the same rigor. If a unit fails twice, it's mis-scoped, not the model's fault: decompose it further rather than escalating the model or fixing it yourself (see orchestrator-delegation).

**7. Report with evidence.** Use the Sttark asks table: each ask is done, open or dropped, with the reason, plus an Evidence column (test counts, commands run, what you observed). Give the shortest reply that fully answers, in ASD-STE100 Simplified Technical English, with no recap. "Done" without evidence is confident guessing. If something was skipped or a test failed, say so plainly.

## Autonomy rails (these still bind)

The browser is one shared resource. Start only one browsing agent at a time; queue the others. A hook makes a second browsing agent wait, then denies it. The main thread runs `claude-window done` before it hands browser work to an agent.

Orchestrating doesn't relax your safety rails. Build, test, and open PRs autonomously — but **merge** only through the production guard's `approve <action>` flow (Phase 8), and only after the verify gate passes. Agents never merge; `ops` never merges a PR. Anything prod-touching — prod migrations, secrets, deploys, payments — **always** stops for the user's explicit confirmation, regardless of confidence. Per-project scope locks and "ask first" rules beat this skill's autonomy. Can't ask? Skip the item and flag it.

## When NOT to orchestrate

Don't spin up the machine for its own sake. Go solo and inline for: conversation and judgment calls, a single question answerable from context, a genuinely trivial edit of at most 2 tool calls with a small result, or the synthesis step itself. A 30-agent workflow to fix a typo is waste — blast radius justifies the fan-out, not enthusiasm. The skill is a lens on how to work, not a mandate to maximize agent count.

## Sttark precedence

When this skill set and the Sttark working rules or the Sttark app rules disagree, Sttark's rules win. These Sttark decisions apply:

- **D4, agent type:** never a fork agent. Delegate only to `implementer`, `ops`, `researcher`, `validator`, `visual-check`, `specialist` or a named specialist agent (see Route), with a full brief.
- **D5, verification:** the `validator` agent checks delegated work. Only its verdict comes back to the main thread, not its logs.
- **D6/D22, threshold:** work of more than a few tool calls, or more than about 3 files of context, goes to a background subagent. Inline: at most 2 tool calls with a result under about 2k tokens (about 8,000 characters). The inline guard hook enforces this.
- **D7, planning:** two lines plus a step count, then start in the same turn. Giving the plan is not asking. Tests first where the repo has tests. In a Sttark app repo, `page-check` is the UI test.
- **D8, reporting:** reply with the asks table (each ask done, open or dropped, with reason) plus an Evidence column. Shortest reply that fully answers, ASD-STE100 Simplified Technical English, no recaps.
- **D20, when to grill:** in Frame, call `grilling` only when acceptance criteria are unclear or there is a real design fork. Clear items get the two-line plan, then start.
- **D21, grilling rounds:** a grilling round (numbered questions, each with a recommended answer that "yes" accepts) is a real question for the person, not a request for a go.

## Depth lives in the sibling skills

This file is the sequence. Each phase hands off — invoke the referenced skill and follow its body when you're in that phase; don't reconstruct its contents from memory:

| Phase | Skill |
|---|---|
| Delegate vs inline, model policy, agent files, verify-not-trust | orchestrator-delegation |
| Writing the actual subagent prompt (uplift templates) | delegate-prompts |
| Tests-first protocol, harness bootstrap, completion gate | tdd-protocol |
| Fan-out shape and sizing (pipeline/lenses/tournament/worktrees) | workflow-patterns |
| Evidence bar, validator pass, adversarial review, severity | validation-and-evidence |
| Where state lives, resume, working ledger | context-and-state |
| New/unfamiliar repo before any code | familiarize |
| Running the app to observe behavior as proof | page-check (Sttark app repo) or run (built-in) |
