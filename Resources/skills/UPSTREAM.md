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
- Phase 4, Resources/agents/validator.md: Sttark repo checklist (re-run tests and `page-check`, "Before you ship" list, "Every change has a name on it", `DESIGN-DECISIONS.md`); checklists per kind (D26); fixed last-line `VERDICT: PASS | <item> | <evidence>` or `VERDICT: FAIL | <item> | <gap>`.
- Phase 4, Resources/skills/validation-and-evidence/SKILL.md: verdict line format, kick back to an implementer with the gap, short mirror of the Sttark checklist, `app-review.yml` stays the final gate on a Sttark app PR.
- Phase 4, Resources/skills/orchestrate/SKILL.md: step 6 kicks a FAIL back to an implementer with the gap from the verdict line and per-criterion list, then the validator re-checks.
- Phase 4, Resources/skills/delegate-prompts/SKILL.md: validator template (Template 5) adds kind and item, and ends with the fixed `VERDICT:` last line.
- Phase 4, Resources/agents/validator.md: checklist now lists the "Before you ship" items (Checks chapter) and the "Every change has a name on it" rule (Sign in and access chapter), from app rules revision 63; the validator still reads the live chapters file.
- Phase 4 fixes: delegate-prompts Template 4 (adversarial reviewer) last line is now `REVIEW: CLEAN | FINDINGS`, so only the validator's last line starts with `VERDICT:`; validator.md writes PARTIAL as `VERDICT: FAIL | <item> | partial: <gap>`; validation-and-evidence: an implementer fixes a FAIL; orchestrate step 6: em-dash removed.
- Phase 5, orchestrate and orchestrator-delegation: the browser is one shared resource; one browsing agent at a time, queue the others; the `browser-lock.py` hook makes a second one wait, then denies it. delegate-prompts: browsing briefs say to run `claude-window done` when finished.
- Phase 6, Resources/skills/orchestrate/SKILL.md: new Route step (2b) between Decompose and Delegate: named specialist agent, else the general `specialist` agent with the skill name in the brief, else a core agent (D14, D28); org skills only in Code tab sessions; two-pass pattern; browser skills go through the browser lock. Mirrored in orchestrator-delegation (short paragraph), delegate-prompts ("Skill to use" field) and workflow-patterns ("Two-pass approval" entry).
- Phase 6, Resources/agents/: new `specialist` and six named specialists (one org skill each, `skills:` preload plus the `Skill` tool, BLOCKED when the skill is missing): `bom-specialist`, `hvac-specialist`, `onshape-cleanup-specialist`, `supplier-specialist`, `asana-update-specialist`, `strategy-specialist`.
- Phase 6, I24: ui-check-guard.py block reason adds "If you have no Bash tool, say in your report that you could not run page-check."
- Phase 6, specialist tools: `bom-specialist` keeps a narrow `tools:` list (its skill runs a python3 script). The other five omit `tools:` (inherit the session's tools, including MCP: Workrouter, Chrome, Gmail) and use `disallowedTools:` for core tools their skill does not use. MCP tool names carry a per-user connector id, so they cannot be listed.
- Phase 6 fixes: `specialist` omits `tools:` (inherits MCP and write tools) and uses `disallowedTools: Agent, Task`. browser-lock.py: a Bash `osascript` whose script names Chrome (also in a heredoc) counts as a browser call (tests added). Decision: an org skill's own browser method (Chrome tools, AppleScript) wins over the general claude-window-only rule for that specialist; the lock covers all three methods; effort-hook.py unchanged. supplier-specialist: AppleScript text; pass 1 may write the skill's local files (deal ledger, morning handoff). bom-specialist may write `bom-check-report.md`. hvac-specialist returns NEEDS INPUT for intake questions; orchestrate Route handles it.
- Phase 7, Resources/skills/orchestrate/SKILL.md and context-and-state/SKILL.md: day log and state checkpoint rules (D17, D18): only the orchestrator writes the day log, at verdict, decision, drop and rotation; state file at each checkpoint; rotate at a clean stop then /clear; NEXT.md stays the repo's own notes. Every agent file gains one line: never write the day log or the orchestrator state file.
