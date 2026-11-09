---
name: orchestrator-delegation
description: >-
  Use when deciding whether to do work inline or hand it to subagents, when picking which
  model (haiku/sonnet/opus) runs a delegated task, when writing or wiring subagent
  definitions in ~/.claude/agents/ or .claude/agents/, or when a delegate's output comes
  back and needs checking. Covers the delegate-vs-inline rule, the model cost policy,
  the subagent file format and its caveats, the five mandatory elements of every delegate
  prompt (the uplift doctrine), and verify-not-trust. Triggers: "should I delegate this",
  "spin up subagents", "which model should the agent use", "write an agent definition".
  Don't use for choosing a multi-agent workflow SHAPE (fan-out vs pipeline vs tournament —
  use workflow-patterns), for the full delegate prompt templates (use delegate-prompts), or
  for unattended/recurring runs (use the built-in loop/schedule mechanisms).
---

# Orchestrator delegation

The main session is the orchestrator: it decomposes work, launches subagents, and judges their output. Subagents are cheap, disposable executors that know NOTHING about this conversation. This skill is the doctrine for when to delegate, on what model, through what mechanism, and how to check the result.

## Delegate vs inline

**Do it inline (no subagent)** when the task is:
- A trivial edit, rename, or config tweak you can make in one or two tool calls
- Conversation, judgment calls, or anything requiring context only available in this session
- A single-file read or a question answerable from files already in context
- The final synthesis/merge step itself — the orchestrator always owns that

**Delegate to a subagent** when the task:
- Needs more than ~3 files of context-gathering before any edit (exploration burns orchestrator context; a researcher agent returns a distilled summary instead)
- Is parallelizable — independent tickets, independent review lenses, independent research questions
- Is adversarial review — a fresh agent with no authorship bias catches what the author-session cannot (see validation-and-evidence)
- Is a long build/test cycle whose intermediate output you don't need to watch (use `background: true` or a backgrounded shell run)

Scale to stakes: solo for trivial work, 3-6 agents for routine builds, 3-5 review lenses added per item merging to main, 15-30+ reserved for audits and hard-to-reverse work. Sizing guidance and pattern selection live in workflow-patterns.

## Model policy — cheapest model that passes

| Model | Use for | Why |
|---|---|---|
| `haiku` | Mechanical work: classification, extraction, formatting, bulk file triage, log scanning | Same-quality output at a fraction of the cost — routing this class of work through the smallest capable model instead of a top-tier one routinely runs 100-500x cheaper per message for identical output |
| `sonnet` | Scoped execution: implement a ticket, write tests, fix a named bug, research one question | Reliable executor WHEN given uplift scaffolding (below); fails when handed vague goals |
| `opus` (usually the main session) | Decomposition, hard adversarial review, synthesis of agent outputs, merge decisions | Judgment work — reserve the top-tier model for review and synthesis, not for building |

Never assign the top-tier model to work a mid-tier model can pass, and never assign a mid-tier model to work the smallest model can pass. If a delegate fails twice on the same task, the task is mis-scoped — decompose it further rather than escalating the model. (Learned the hard way: a delegated build once stalled repeatedly because the underlying task was too large for one pass — no model upgrade fixes a task that doesn't fit in one pass.)

## The subagent mechanism

Custom subagent definitions are markdown files with YAML frontmatter:

- **User-level** (all projects): `~/.claude/agents/<name>.md` — this operating layer ships five: `implementer`, `validator`, `researcher`, `ops`, `visual-check`. Each lists only the tools it needs in `tools:`. Leave that line out and the agent gets every tool, whose descriptions (plus the skill list) load into every call it makes, so an all-tools agent starts at several times the context of a tool-limited one
- **Project-level**: `.claude/agents/<name>.md` (discovered by walking up from cwd)
- **Per-session**: `claude --agents '<json>'` (inline agent definitions)

Required frontmatter fields: `name`, `description`. Key optional fields:

```yaml
---
name: implementer
description: Builds one scoped ticket with tests. Use for any delegated implementation task.
model: sonnet            # sonnet | opus | haiku | inherit (default) | full model ID
tools: Read, Edit, Write, Bash, Grep, Glob
permissionMode: default
maxTurns: 60
skills:                  # preloaded in full — the agent doesn't have to discover them
  - tdd-protocol
background: true         # always run as a background task
isolation: worktree      # run in an isolated git worktree
---
The markdown body is the agent's system prompt.
```

Model resolution order: `CLAUDE_CODE_SUBAGENT_MODEL` env var > per-invocation model parameter > frontmatter `model` > main session's model.

**Caveats worth re-checking as the tool evolves:** Whether subagents inherit extended thinking and whether they run in the background by default has changed between Claude Code versions. Check `claude --help` and the release notes for your version before relying on either.

## The uplift doctrine — five mandatory elements of every delegate prompt

A subagent starts with zero context: no conversation history, no knowledge of what the user wants, no memory of past decisions. Every delegate prompt MUST contain all five:

1. **Full context injection** — everything the agent needs, stated explicitly: file paths, project conventions, relevant decisions, what NOT to touch. Assume it knows nothing, because it doesn't.
2. **Explicit acceptance criteria** — the testable conditions under which the task is done ("all tests green", "typecheck clean", "returns exactly N findings"), not "make it good".
3. **Required output schema** — the exact shape of what comes back (fields, format, length caps), so the orchestrator can consume it without re-reading everything.
4. **Worked example** — when the output format matters, show one filled-in example. Format compliance without an example is a coin flip.
5. **Self-verification checklist** — a short list the agent must run BEFORE returning ("did you run the tests? did you re-read your diff? does every claim cite a file:line?").

Worked templates for every task type live in delegate-prompts — that skill owns the full anatomy; this checklist is the minimum bar.

## Verify, don't trust

Delegate output is never accepted on the builder's word. The orchestrator (or a dedicated validator agent) independently checks every returned claim:

- "Tests pass" → the orchestrator or validator re-runs the test command
- "File updated" → read the file
- "Researched X, answer is Y" → spot-check at least one cited source
- Builds destined for the main branch get an adversarial review pass by a fresh agent that did not write the code

Evidence standards, the validator pass, and done-criteria live in **validation-and-evidence** — this skill only establishes the rule: a builder's self-report is a claim, not a fact.

## Operational scar tissue

One-line rules — the canonical incident catalog with full details is workflow-patterns → "Paid-for lessons":

- **Commit the working tree before launching agents** — uncommitted orchestrator state is not safe from a subagent's `git checkout`/`reset`.
- **Merges are done serially by the orchestrator, never by agents.**
- **No open-ended web search inside subagents** — a research workflow once died on a web-search tool stalling inside a subagent; keep web-heavy research in the main session.
- **Give agents explicit absolute paths** — a sandboxed execution environment can strip PATH for write/git commands.
- **Record what you launched (branches, worktree paths) in your working ledger** — background task handles can be lost across a context compaction; see context-and-state.
- **Pre-assign shared serial resources (migrations, ports, slugs) before fan-out.**

## Scope

This skill decides WHETHER and TO WHOM to delegate, and what any delegate prompt must contain. It does not: pick the multi-agent workflow shape or size (workflow-patterns), provide the full prompt templates (delegate-prompts), define evidence/review standards (validation-and-evidence), run unattended/recurring loops (the built-in loop/schedule mechanisms), or manage the per-repo ledger and resume protocol (context-and-state). Per-project rules always win: a project may forbid agents from touching worktrees, stashes, or branches at all, or carry its own standing out-of-scope list; prod-touching steps always gate on the user.

## Provenance and maintenance

Re-verify on drift:
- `ls ~/.claude/skills/ | grep -E 'orchestrator-delegation|workflow-patterns|validation-and-evidence|tdd-protocol'` — cross-referenced siblings still exist
- Check the CLI's current version and changelog — if subagent behavior around extended thinking or background-by-default has changed, update the caveats above before relying on either
- `ls ~/.claude/agents/` — confirm the starter agents exist
- Check the CLI's own help output for its subagent-definition flag — confirm the mechanism described above is still current
