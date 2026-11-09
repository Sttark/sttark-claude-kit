---
name: context-and-state
description: >-
  Use when starting or resuming work in a repo, deciding where a piece of state
  should live, or checkpointing before a long build, session end, or context compaction.
  Covers the repo-ledger model (a per-repo NEXT.md plus whatever tracker and notes your
  team uses), the standard NEXT.md format, the fresh-session resume protocol (CLAUDE.md
  -> NEXT.md -> open ticket -> deeper notes -> verify against git/tests), and checkpoint
  discipline. Trigger on "where were we", "pick up where we left off", "resume this
  project", "what's next here", "update NEXT.md", "save our state before I go",
  "checkpoint". Don't use for doc writing style or entry format for a gotchas log — keep
  the repo's own docs and ledger current using its existing conventions. Don't use for
  issue-tracker mechanics — use whatever tracker skill or workflow your team already has.
  Don't use for onboarding a brand-new unfamiliar repo — the familiarize skill owns that;
  this skill is for repos with existing state to pick back up.
---

# Context and state — where state lives, and how to resume

Many projects run in parallel across sessions that end, compact, or crash mid-flight. This skill defines the single source of truth for each kind of state and the exact order to rebuild context in a fresh session. The core rule: **one home per fact — cross-reference, don't duplicate.**

## When to use

- A session starts (or resumes) in a repo that has prior work in flight.
- You're about to record something and need to know WHERE it goes.
- You're about to launch a long build, end a session, or expect compaction — checkpoint first.
- Someone asks "where were we?", "what's next?", or "what's blocked?".

## The stores — division of labor

| Store | Holds | Granularity | Read when | Written when |
|---|---|---|---|---|
| **NEXT.md** (per repo, in the repo root) | What's on deck, in-flight state, blockers, exact next command | Working memory — messy, current, disposable once done | Session start, always | Before long builds, before session end, before expected compaction |
| **Your notes/knowledge base** (whatever you use to keep durable facts findable — a personal notes app, a wiki, a shared doc store) | Short durable facts: decisions, outcomes, discovered gotchas, preferences | One-liner, first-person: "I'm working with Claude Code on <PROJECT>: <summary>" | Session start for meaningful work; before asking a question that may already be answered | After significant work — model judgment, not automatic |
| **Deeper narrative docs** (a wiki page, a status doc, whatever your team keeps long-form notes in) | Full narrative docs; one living status/handoff doc per project | Pages — setup guides, deep handoff narrative, decision records | When NEXT.md isn't enough and you need the deeper story | After meaningful work; re-use the SAME living doc, don't spawn near-duplicates |
| **Your issue tracker** (whichever one the project uses) | Tickets, specs, decisions — **source of truth when the project uses one** | Issues + living documents | Resume step 3 (the in-progress ticket) | Status moves + comments as work lands |

Content rules for each store (what belongs, what never goes in) are owned by your project's own documentation conventions — this table is only read-when/write-when.

Boundary rules that keep the stores clean:

- **Your notes/knowledge base is NOT for** file paths, code snippets, or ephemeral task details — that's NEXT.md territory. It's what should still be true and findable in three months.
- **NEXT.md is NOT for** durable decisions — record the decision in your tracker (if the project uses one) or your notes, and let NEXT.md just point at it.
- **Not every project has an issue tracker.** Some repos and most content projects have no tracker home; their state lives entirely in NEXT.md plus whatever notes system you keep.
- Where a repo has a **LEARNED.md** (or similarly named gotchas log), surprises and hard-won lessons go there, not into NEXT.md. Entry format is your project's own documentation convention.
- Mechanics for actually reading/writing your notes system or tracker (auth, endpoints, payload shapes) belong in a tool-specific playbook, not this skill — this skill only says when to read/write, not how.

## Standard NEXT.md format

Canonical target shape — four sections:

```markdown
# NEXT

## Now
The single active task, with the exact next command to run.

## Next
On deck, in priority order.

## Blocked
What's blocked, on whom/what, and what unblocks it (e.g. "⛔ Needs a decision: prod creds").

## State
Branch, test status (e.g. "1098 passing"), open PR numbers, background task handles,
migration head, anything a fresh session needs to trust-but-verify.
```

**Augment, never clobber.** Existing NEXT.md files are often free-form and healthy — some use an Active/Open-questions/Done shape, some a dated narrative with explicit "needs a human" markers, some a Status/Immediate-next-steps/Open-decisions shape. When updating one of these, work within its existing structure and make sure the four kinds of information (now / next / blocked / state) are present and current somewhere in it. Only use the standard skeleton verbatim when creating a NEXT.md where none exists. Never delete someone's hand-written items — mark them done or move them, don't drop them.

Good habits worth keeping wherever you see them: date-stamp status blocks, use a clear marker (like `⛔`) for gates that need a human decision, record exact refs (`main @ <short-sha>`, migration ranges), name PR numbers and test counts.

## Resume protocol — fresh session in a repo with prior work

Run in this order; each step is skipped only if the source doesn't exist:

1. **Repo CLAUDE.md** — conventions, hard rules, and any session ritual it mandates (some repos mandate "read this file + NEXT.md"; some redirect to AGENTS.md — follow the indirection). Per-repo rituals override this generic protocol where they conflict.
2. **NEXT.md** — the ledger. This tells you what "Now" is. Read a LEARNED.md too if the repo has one.
3. **The in-progress ticket** (only if the project uses an issue tracker) — via whatever tool or MCP server connects to it. Respect any ownership boundaries the project defines (e.g. one area is owned by someone else — never touch it).
4. **Deeper narrative doc** (only if more context is needed) — search your notes system for a handoff or status doc for this project and read the latest one.
5. **Verify state matches reality before continuing.** NEXT.md can be stale — don't trust it blind:
   - `git status` + `git log --oneline -5` — is the branch/ref what the ledger claims? Uncommitted changes?
   - `gh pr list` — do the claimed open PRs still exist in the claimed state?
   - Run the repo's own test command (it's per-repo — take it from the repo CLAUDE.md, never assume) — does the claimed green status hold?
   - If reality diverges from the ledger, fix the ledger FIRST, then proceed.

Then state your understanding of "where we are + what's next" in one short block before doing anything, so a wrong resume can be corrected cheaply.

## When the sources disagree

NEXT.md, an issue tracker, and git can disagree — this is a common state after interrupted sessions (seen in the wild: a repo had several started tickets, a stale NEXT.md, and unlabeled items simultaneously). The tie-break: git evidence wins. Commits, branch names, and merged PRs are facts; NEXT.md and a tracker are claims about facts. Protocol: (1) establish reality from git (`git log --oneline -15`, `git branch --show-current`, `gh pr list --state merged --limit 5`); (2) reconcile — update NEXT.md to match reality and note the reconciliation; flag tracker states that need moving (move them if the work is unambiguous, otherwise list them for a human to decide); (3) only then continue the task. Never build on top of an unreconciled disagreement.

## Checkpoint discipline — when to write NEXT.md

Update NEXT.md (and, for milestone-sized state, a deeper handoff doc) at these moments:

1. **Before launching any long build or agent fan-out.** Also commit the working tree first — learned the hard way once: an implementation agent's `git checkout`/reset reverted an uncommitted NEXT.md and the state was lost.
2. **Before ending a session** — the next session's step 2 is only as good as what you wrote.
3. **Before expected compaction.** Learned the hard way once: a background workflow task handle existed only in conversation context, compaction dropped it, and the state had to be reconstructed from worktree branches. Anything only-in-context (task handles, background session IDs, in-flight PR intent) dies at compaction — write it to `## State` the moment it exists.
4. **When a blocker appears or clears** — `## Blocked` must name what and on whom, so an unattended loop or a fresh session knows whether to proceed or escalate.

A checkpoint is 2 minutes of writing that saves a 30-minute archaeology dig. When work completes, a good convention is: update the tracker status + append a build log entry + update NEXT.md, in that order.

## Repos without a NEXT.md

If a repo has real multi-session work but no NEXT.md, create one with the standard skeleton and mention it. Don't create one for throwaway scripts or single-session tasks. For a repo you've never seen at all, run familiarize first — it owns onboarding and CLAUDE.md creation; this skill takes over once there's state worth resuming.

## Scope

This skill owns WHERE STATE LIVES and the RESUME ORDER — nothing else:

- Curl/API mechanics for your own notes system or wiki belong in a tool-specific playbook, not here.
- Writing style and house patterns for NEXT.md/LEARNED.md content, CLAUDE.md editing policy, and decision records belong to your project's own documentation conventions.
- The runbook for your issue tracker (states, labels, issue templates, ownership boundaries) belongs to a tracker-specific skill or your team's own process docs.
- Checkpointing and stop conditions inside unattended loops are a separate concern from this skill — keep them documented wherever your loop tooling lives.
- **familiarize** (a companion skill) owns first contact with an unfamiliar repo.
