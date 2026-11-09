---
name: tdd-protocol
description: >-
  Tests-first protocol for all product and library code — extract the intended behavior into
  written testable assertions BEFORE implementing, write the failing tests, confirm they fail
  for the right reason, implement to green, and gate "done" on pasted passing output. Covers
  the it.todo behavior-surface enumeration pattern, a per-ecosystem test-command index, and
  standing up a test harness in a repo that has none. Trigger on "TDD", "test-first", "write
  the tests first", "add a test harness", "set up testing". Exempt work:
  content/video editing, throwaway scripts, pure research. Don't use for run-the-app
  behavioral proof of a finished change — use the verify built-in; for evidence standards,
  done-criteria, and the validator pass, use validation-and-evidence.
---

# TDD Protocol

Tests-first is the default lifecycle for product and library code — a standing decision, not a suggestion. The pattern is proven, not aspirational: a real test suite grew from mostly `it.todo` placeholders to over a thousand passing tests within weeks under exactly this protocol.

## When to use

- **Default for all product/library code** — new features, bug fixes, behavior-changing refactors — in any repo.
- Applies even when the repo has **no test harness yet**: standing one up is part of the job, not a reason to skip (see "Standing up a harness" below).
- **Exempt:** content/video work, throwaway one-off scripts, and pure research tasks.
- **Local conventions win.** If the repo defines its own test process, follow that. The table below is an index, not a substitute for reading the repo's own docs.

## The protocol

1. **Spec the behavior first — in writing.** Before touching implementation, extract the exact intended behavior into concrete, testable assertions and write them down: as `it.todo` entries in the test file (preferred for JS/TS), as a checklist in your issue tracker, or as Gherkin scenarios where the repo uses BDD. If you cannot state the assertion precisely, you do not understand the ticket yet — go back to the spec/issue, not to code.
2. **Write the failing tests.** Convert the assertions into real tests against the intended public surface (the API you wish existed, not implementation internals).
3. **Run them and confirm they fail FOR THE RIGHT REASON.** A test failing with "module not found", a typo, or a harness misconfiguration proves nothing. The failure message must show the behavioral gap you are about to close (wrong value, missing endpoint, unhandled case). Fix import/setup errors until the failure is the real one, and only then move on.
4. **Implement to green.** The smallest change that makes the failing tests pass without breaking the rest of the suite. Run the full suite, not just the new file.
5. **Run the completion gate and paste the output** (next section). Only then is the work done.

**Bug fixes are TDD too:** reproduce the bug as a failing test first, then fix. A fix without a regression test can silently un-fix later.

**When delegating implementation to a subagent,** steps 1-3 are the handoff artifact: give the agent the written assertions and the failing tests, require it to return pasted green output. See orchestrator-delegation and delegate-prompts.

## The completion gate

Nothing is "done" without pasted passing output in the conversation, PR, or ticket. Claimed-green is not green — an orchestrator must see the output, not a summary of it. One real project's done-criteria are the reference shape:

- `tsc` clean
- `build:types` clean
- test runner green — the **full suite**, not just the new tests
- a schema/migration drift check (e.g. `drizzle-kit check`) — no drift

The exact commands differ per repo; the principle transfers: **typecheck + full test suite + any drift/lint check the repo defines, output pasted, before the ticket moves to Done/In Review.**

Learned the hard way on one project: a migration journal's `when` values were hand-sequenced (previous + 100000000, not wall clock, because later entries were future-dated). A wall-clock value silently skipped the migration on already-migrated databases **and the tests did not catch it**. That is why the gate includes the no-drift check — green tests alone miss this whole class of failure.

## The it.todo pattern (enumerate the surface first)

From a real test-harness build-out: before implementing a feature area, enumerate its **entire behavior surface** as `it.todo("...")` entries — every input class, error path, permission boundary, and edge you can name. Then:

- The todo list IS the written behavior spec from protocol step 1 — reviewable before any implementation exists.
- Convert todos to real tests as you implement each behavior. `it.todo` shows up in the runner output, so unconverted todos are visible, not forgotten.
- **A ticket does not close with its todos unconverted.** Todos are a planning device inside a ticket, not a way to ship untested behavior.

This is what took one real suite from mostly todo to over a thousand passing tests within weeks: the surface was named up front, then burned down ticket by ticket. In non-JS ecosystems, use the local equivalent: `#[ignore]` tests in Rust, `t.Skip` in Go, `@pytest.mark.skip` in Python, or unimplemented Gherkin scenarios in godog.

## Per-repo test commands

Build and keep your own index — the shape below is proven to be worth maintaining, but the specific commands are always repo-specific. **This kind of table drifts — reverify against the repo's own docs before relying on it**, especially in repos you haven't touched recently.

| Ecosystem | Typical commands | Notes |
|---|---|---|
| Go, Gherkin/BDD | `go test ./...`, `godog features/`, or a `make test-*` target | Two-tier setups (mock spec + real-dependency e2e) are common; check for a testing process doc first |
| Node/TS | `npm test` (Vitest/Jest) | In-process test databases (e.g. PGlite) avoid needing Docker; a full gate often adds `tsc` + a types build + a schema-drift check |
| Multi-layer web app | unit runner + `pytest` + an e2e runner (e.g. Playwright) | Three layers are common: unit, integration, browser — read the repo's own testing doc for the exact commands |
| Rust | `cargo fmt`, `cargo clippy` (zero warnings), `cargo test`, plus any `--features integration` variant | Check for nested module-level docs with their own conventions |
| Any ecosystem with a wrapper script | run the wrapper, never the raw test binary directly | Wrappers often enforce coverage thresholds or other repo-specific gates; a maintainer repo's own rules override this skill |
| Any ecosystem with mandatory changesets | `cargo test` / `npm test` / etc. + a changeset or changelog entry per PR | Patch-coverage enforcement is common here |

## Standing up a harness in a bare repo

No harness is not an exemption. When the repo has product/library code and no tests:

1. **Pick the ecosystem-native runner.** Vitest for TS/Node, pytest for Python, `cargo test` for Rust, `go test` for Go. Do not import a foreign stack the repo's ecosystem doesn't expect.
2. **Write one smoke test proving the harness itself runs** — the cheapest real assertion against actual code (import the main module and call one pure function). Run it; paste the passing output. This isolates harness problems from behavior problems before they can blur together in step 3 of the protocol.
3. **Wire the standard invocation** (`npm test` script, Makefile target) so the command is discoverable by the next session.
4. **Record the command** in the repo's CLAUDE.md (augment only — never overwrite existing human-written lines) and in NEXT.md if the repo keeps one.
5. Then run the full protocol from step 1 for the actual feature.

## Scope

This skill covers the write-tests-first loop and the passing-output gate for code. It does **not** cover:

- **Run-the-app behavioral proof** (launch it, click through it, screenshot it) — that is the `verify` built-in skill.
- **Evidence standards, done-criteria policy, and the independent validator pass** (a second agent adversarially checking claimed-done work) — that is **validation-and-evidence**. This skill produces the evidence; that one judges it.
- **How to split test-writing across subagents or size a workflow** — **orchestrator-delegation** and **workflow-patterns**.
- **Where the results get recorded** (issue-tracker status, ledger notes, build log) — keep the repo's own docs and issue tracker current as you go.

## Provenance and maintenance

- This protocol is written from real Phase-1 build-out experience: per-repo commands verified against each repo's own docs, done-criteria taken from a real review cycle, and the it.todo growth curve (mostly-todo to over a thousand passing) taken from a real project's history. Treat the specific counts above as illustrative, not a target to hit exactly.
- **What drifts:** the per-repo command table (reverify by reading the target repo's own CLAUDE.md/AGENTS.md, or its package manifest's script list); suite counts and growth curves (reverify by running the suite yourself).
- If a repo has been dormant for a long stretch, don't assume its recorded commands still work — its build may have rotted; verify before relying on them.
