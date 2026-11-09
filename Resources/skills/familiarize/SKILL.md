---
name: familiarize
description: Run this FIRST on an unfamiliar repository, before writing any code. Systematically explores the repo — reads every README/spec/markdown file, maps the architecture, languages and framework versions, checks for existing CLAUDE.md/AGENTS.md, works out how to run and test it, pulls current external docs for the detected stack, and generates a docs/repo-map/ (architecture map, command reference, file index) plus creates or augments the root CLAUDE.md. Use when handed a new codebase, starting a technical interview, or returning to a repo after time away.
---

# Familiarize

Take a repository from "never seen this" to "I understand the stack, the
structure, how to run it, and where everything lives" — and leave behind
durable maps so every later session starts oriented.

Run this **before writing any code**.

## When to use

- The first thing after cloning or opening an unfamiliar repo.
- The opening minutes of a technical interview when handed a repo.
- Returning to a codebase you haven't touched in a while.

## Procedure

Work the phases in order. On a large repo, parallelize Phases 2–3 with several
Explore agents (one per area) instead of searching serially.

### Phase 1 — Human-written context

Read what people deliberately wrote down, in this order:

1. **Root `README.md`** — purpose, setup, and especially any **task list or
   requirements**. If this is an interview/exercise repo, extract the explicit
   deliverables into a checklist.
2. **Every other markdown file** — `docs/**`, `ARCHITECTURE.md`,
   `CONTRIBUTING.md`, ADRs, per-app/per-lib `*.md`.
3. **Existing AI context** — `CLAUDE.md`, `AGENTS.md`, `.cursorrules`,
   `.github/copilot-instructions.md`. If a `CLAUDE.md` exists, treat it as
   ground truth — you will *augment* it, never overwrite it.
4. **`package.json`** (root + nested) — name, `scripts`, dependencies,
   `engines`.
5. **Config & ops** — `.env.example`, `.nvmrc`, CI workflows, Dockerfiles.
6. **Git context** — current branch, `git log` (recent ~15 commits),
   uncommitted changes. Tells you what's in flight.

### Phase 2 — Architecture & stack

Open real files; never infer architecture from folder names alone. Determine:

- Languages and frameworks, **with versions** (package.json + lockfile).
- Package manager (whichever lockfile exists).
- Monorepo? If **Nx**: read `nx.json`, run `nx show projects` and `nx graph`;
  list apps vs libs and their tags. Adapt for Turborepo / pnpm workspaces /
  Lerna / single-package.
- Build, test, and lint tooling.
- The data layer — ORM, schema files, migrations, database engine.
- Each app's entry point (`main.ts`, etc.).
- Patterns and conventions actually in use — confirm by reading 5–10
  representative files.

### Phase 3 — Code map

- Inventory every project/module/package and its responsibility.
- The API surface — routes, endpoints, controllers.
- The shared contracts — shared types / models / DTO libraries.
- The dependency graph — what depends on what.
- Where the stubs, `TODO`s, and unimplemented areas are — i.e. what you'd be
  expected to build.

### Phase 4 — How to run it + baseline

- Required runtime/Node version.
- The bootstrap sequence: install → env → database (migrate/seed) → serve.
- Dev server ports; how to run the test suite.
- **Establish a baseline:** does it build, do existing tests pass *right now*,
  before you change anything. Note it — you need a known-good starting point.

### Phase 5 — Current external docs

- For each major framework + version, pull the **current** official docs via
  WebFetch/WebSearch — training data drifts, and version-specific APIs matter.
  Note anything that changed from older versions.
- Cross-reference any installed skills that match the stack (a framework skill,
  an ORM skill, a monorepo skill) and note they apply.

### Phase 6 — Generate the maps

Create a **`docs/repo-map/`** folder:

- **`architecture.md`** — stack + versions, project/module map, dependency
  graph, data layer, conventions in use.
- **`commands.md`** — the CLI mapping: *every* runnable command (npm scripts,
  Nx targets) with a one-line description and when to use it, grouped by
  build / test / serve / db / lint.
- **`index.md`** — the file/directory index: where things live, plus a
  "where do I add X?" guide for common tasks.
- **`references.md`** — links to the current external docs from Phase 5, with
  the key version-specific notes worth remembering.
- **`glossary.md`** — domain terms from the code/README, defined. (Skip if
  trivial.)

Then **create or augment the root `CLAUDE.md`**:

- If missing — create it: project purpose, stack + versions, structure, how to
  run, conventions, key file locations, known gotchas, and a pointer to
  `docs/repo-map/`.
- If it exists — add a "Repo map" section pointing to `docs/repo-map/`, fill
  gaps, and **keep every human-written line**.

### Phase 7 — Brief the user

Give a tight spoken summary — assume they want to act on it immediately:

- What the project is; the stack + versions.
- The structure, in 2–3 sentences.
- How to run it — the exact commands.
- For an interview/exercise repo: the **task checklist** extracted from the
  README, plus a few **clarifying questions** worth asking before coding.
- Anything surprising, risky, broken, or notably missing.

## Principles

- **Read, don't assume.** Open real files; folder names lie.
- **Versions matter.** Pin framework versions and pull current docs — your
  training data is stale relative to the repo.
- **Don't pollute.** Generated maps go under `docs/repo-map/`. Never overwrite
  human-written docs or a meaningful existing `CLAUDE.md` — augment only.
- **Be fast.** Parallelize with Explore agents on anything large.
- **Leave it better.** After `familiarize`, the next session — yours or a
  teammate's — starts already oriented.
- **Read-only until asked.** Familiarize explores and writes maps; it does not
  refactor, install, or change app code. If `node_modules` is missing, some
  analysis (e.g. `nx graph`) needs an install first — note it rather than
  installing unprompted.

## Interview note

In a timed interview, run `familiarize` in the first few minutes while you talk
through the README out loud. The task checklist it extracts becomes your plan;
the clarifying questions become your spec conversation with the interviewers.
Mention to the interviewers what you're doing — it shows method and is itself a
signal of how you work with AI.
