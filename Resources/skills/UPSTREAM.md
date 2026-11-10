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
- I5: `verify` replaced by `page-check` (Sttark app repo) or the built-in `run` skill elsewhere (orchestrate, tdd-protocol, validation-and-evidence, validator.md); deep-research replaced by the `researcher` agent; `code-review` kept and marked as a Claude Code built-in.
- I6: `ops` never merges a PR; merges go only through the production guard's `approve <action>` flow (Phase 8). Aligned in ops.md and orchestrate.
- I7: `researcher` gets `WebSearch` (with a time budget and UNKNOWN fallback); orchestrator-delegation, workflow-patterns, familiarize and delegate-prompts send web research to the `researcher` agent.
- I8: validator model is Opus for code and UI checks, Sonnet for draft, Asana proposal, BOM check and research checks; set in validation-and-evidence and validator.md.
- I12: delegate-prompts adds the Sttark context block to briefs whenever the target repo is not the session's repo.
- I13: all five agent files: the Sttark repo test is a remote under github.com/Sttark, or a repo the Sttark context marks as an app repo.
- I14: delegate-prompts heading renamed "Sttark context" to match the name the agent files look for.
- I18: deleted grilling/agents/openai.yaml; grilling/LICENSE kept.
- P2: delegate-prompts block: repo rule is now read the docs first and do not pull, switch branches or reset unless the brief says so.
- P2: orchestrator-delegation, workflow-patterns, validation-and-evidence: merges stay serial and happen only after the person types `approve <action>` (Phase 8).
- I5: orchestrate step 5 now names `page-check` / the built-in `run` skill instead of `verify`.
