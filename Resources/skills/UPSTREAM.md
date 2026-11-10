# Upstream sources

Files below were copied byte for byte from these repos (shallow clones, 2026-11-09).

## cgraves09/claude-orchestrate-skill

- Repo: https://github.com/cgraves09/claude-orchestrate-skill
- Commit: 5be7eee324fed0ae0d3108b63b3e9d3781ea84fc
- License: Unlicense (public domain dedication)

Files copied (destination ← source):

- Resources/skills/context-and-state/SKILL.md ← skills/context-and-state/SKILL.md
- Resources/skills/delegate-prompts/SKILL.md ← skills/delegate-prompts/SKILL.md
- Resources/skills/familiarize/SKILL.md ← skills/familiarize/SKILL.md
- Resources/skills/orchestrate/SKILL.md ← skills/orchestrate/SKILL.md
- Resources/skills/orchestrator-delegation/SKILL.md ← skills/orchestrator-delegation/SKILL.md
- Resources/skills/tdd-protocol/SKILL.md ← skills/tdd-protocol/SKILL.md
- Resources/skills/validation-and-evidence/SKILL.md ← skills/validation-and-evidence/SKILL.md
- Resources/skills/workflow-patterns/SKILL.md ← skills/workflow-patterns/SKILL.md
- Resources/agents/implementer.md ← agents/implementer.md
- Resources/agents/ops.md ← agents/ops.md
- Resources/agents/researcher.md ← agents/researcher.md
- Resources/agents/validator.md ← agents/validator.md
- Resources/agents/visual-check.md ← agents/visual-check.md

Not copied: LICENSE, README.md, install.sh, scripts/check.sh.

## mattpocock/skills

- Repo: https://github.com/mattpocock/skills
- Commit: 4ae2317ddb22b046e26455e4f9c9b3aaaf62212d
- License: MIT (Copyright (c) 2026 Matt Pocock)

Files copied (destination ← source):

- Resources/skills/grilling/SKILL.md ← skills/productivity/grilling/SKILL.md
- Resources/skills/grilling/agents/openai.yaml ← skills/productivity/grilling/agents/openai.yaml
- Resources/skills/grilling/LICENSE ← LICENSE

## Sttark changes

The files below differ from the upstream copies. The decision IDs come from the Orchestrator plan.

- Resources/skills/orchestrate/SKILL.md: Frame calls `grilling` only for unclear criteria or a real design fork, else a two-line plan and start (D7, D20, D21); `page-check` is the UI test in Sttark app repos; inline limit and inline guard hook (D6/D22); never a fork agent (D4); `validator` verifies and only its verdict comes back (D5); final report uses the asks table with an Evidence column (D8); new "Sttark precedence" section.
- Resources/skills/orchestrator-delegation/SKILL.md: inline limit of 2 tool calls and about 2k tokens, inline guard hook, background subagents (D6/D22); explicit "never a fork agent" line (D4); `validator` checks claims and only its verdict comes back (D5).
- Resources/skills/grilling/SKILL.md: fact lookups inline within the D22 limit, else the `researcher` agent; a round is a real question, not a request for a go (D21).
- Resources/skills/tdd-protocol/SKILL.md: `page-check` is the UI test in Sttark app repos (D7); the `validator` sees the gate output, the main thread gets only its verdict (D5).
- Resources/skills/validation-and-evidence/SKILL.md: only the validator verdict comes back (D5); evidence goes in the asks table Evidence column (D8).
- Resources/skills/familiarize/SKILL.md: reading goes to `researcher` agents and map writing to `implementer`, not Explore or fork agents (D4, D6); user brief uses the Sttark reply format (D8).
- Resources/skills/context-and-state/SKILL.md: resume lookups go to a `researcher`, test runs to a `validator` (D6/D22, D5).
- Resources/skills/workflow-patterns/SKILL.md: inline threshold in the selection matrix and fan-out sizing matches D6/D22.
- Resources/skills/delegate-prompts/SKILL.md: new "Sttark context block" (worker rules in short form, plus the app-repo lines) for briefs, as a fallback when the SubagentStart hook does not run.
- Resources/agents/*.md (all five): one line: in a Sttark repo with no Sttark context in the context or the brief, return BLOCKED.
- Resources/agents/validator.md: report is the only output that reaches the main thread; short excerpts, no whole logs (D5).
