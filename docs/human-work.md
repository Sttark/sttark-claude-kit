# Human work estimate

The Usage page in the Kit's window and the Usage tab of Kit on your phone show, for each period and each session, what
the same work would take people: "≈ 1 person for 4.7 months" and "≈ 20 people full time over these 7 days". It is an
estimate, always shown with "≈". This page says how it is made and where its numbers come from.

**Human hours = active hours × the factor for the kind of work.**

The scan of the sessions' records (`Resources/hooks/usage-scan.py`) finds both, a reply at a time, and writes them to
`usage/by-session.json` in the Kit's folder; the window (`Sources/SessionUsage.swift`) and the phone add up a period.

## Active hours: Claude at work, waits left out

The records are Claude Code's transcripts in `~/.claude/projects`: a session's own record, and one record for each of
its agents (`<session>/subagents/agent-*.jsonl`). Each record is read on its own.

- **Model time:** from what the model answers (a prompt, a tool's result, or the last hook note before its request) to
  each part of its reply.
- **Tool time:** from a tool call to its result.
- **Once:** the parts of one reply that overlap, such as tools that run at the same time, count once.
- **At most 5 minutes a step,** unless the record says the model thought, or wrote a tool's input, for longer
  (`thinkingDurationMs`, `toolInputStreamMs`). Tools that are always quick (Read, Edit, Write, Glob, Grep and the like)
  count 1 minute at most: more is a hold or a permission prompt.
- **Agents add up.** An agent's record counts its own time, also while its session's record counts time. Three agents
  at work for an hour count as three hours, as three people would.
- **A reply counts once,** in the record that holds the original: a fork agent's or a resumed session's copy of an
  earlier reply counts nothing.

Never active:

| Wait | How it shows in the records |
|---|---|
| The person reads, decides or is away | The time from a finished turn to the next prompt. A new turn's model time starts at the last hook note before its request. |
| Notes between turns | Hook notes, system lines, queued prompts, pull-request links, Remote Control status: they never make the time before them active. |
| The usage limit, with a reply | `claude-limit-wait` runs, and the replies that only start the next wait. |
| The usage limit, with no reply | The Kit holds a tool call: from the Kit log's `limit hold` line to its `resume` line, for that session or agent (`abcdef12` or `abcdef12/a1b2c3d4`). The Kit holds a prompt: its hooks' notes come when the hold ends, so the model time starts then. |
| API retries and errors | An `api_error` line's `retryInMs`; a reply that is an error note (model `<synthetic>`, `isApiErrorMessage`). |
| Someone else | `claude-wait`, and the time until the Kit brings the session back; the prompt that brings it back starts only the next reply. |
| Waits inside a turn | A shell command that sleeps 20 seconds or more, polls (`until` or `while` with `sleep`), or watches (`gh pr checks --watch`, `gh run watch`, `tail -f`); a shorter sleep is taken off its command's time. The tools that wait: Monitor, ScheduleWakeup, TaskOutput, Workflow, the timers, and Agent and SendMessage (the session waits on its agents, whose own records count their work). |
| The person, inside a turn | AskUserQuestion, a plan waiting for approval, and a permission prompt (a tool result whose permission decision came from the person). |

## The kind of work

- **Units.** Each agent's record is one unit; a session's own record is cut into turns, from one prompt of the person to
  the next.
- **Signs, from the tool calls.** Software: tests, builds, pull requests and CI (`gh pr`, `gh run`, `npm test`,
  `npm run build`, `vitest`, `pytest`, `swift build`, `./build.sh`, `make`); weaker: a code file edited, a commit.
  Design: CAD files and tools (`.scad`, `.stl`, `.step`, `.dxf`, Onshape, OpenSCAD, CadQuery, ezdxf, Blender), drawing
  and render scripts; weaker: an image read. Browser and admin: `claude-window`, browser tools, email drafts, Asana and
  other office tools.
- **A unit's kind.** Tests, builds or pull requests make it software, also with browser checks or drawings in it. Else
  the browser and office tools make it browser and admin; else CAD, drawing scripts and images make it design; else
  several code edits make it software. Else the signs do not say.
- **A unit the signs leave open** takes its session's main kind: the kind of at least half its active time. A session
  with no main kind is small or mixed when it has under an hour of active time. A longer one gets one call to Haiku
  with a short account of its tool calls: its name, how often it used each tool, the kinds of files it changed and
  the first word of its commands, never a prompt, a reply, a path or a file's content. The answer is kept until the
  session gains another hour of work; no answer, or a usage limit at 100%, leaves it small or mixed.

## The factors

| Kind | Factor (human hours for each active hour) |
|---|---|
| Software | 15 |
| Design | 5 |
| Browser and admin | 5.5 |
| Small or mixed | 2.5 |

They are set in one place, `WORK` in `Resources/hooks/usage-scan.py`; the window and the phone take them, and the
words of the ⓘ note, from the scan's output.

### Where they come from

A one-time study (November 2026) had reviewers read a week of one Mac's records, the 24 sessions that held 92% of that
week's active hours, and estimate from what each session made how long a person would take for it. Those human hours
are the fixed part. The study measured active hours with a simpler rule (the gaps of 5 minutes or less between any two
lines of a record), which counts many idle stretches that the rule above leaves out, so the factors are set again from
the same sessions, measured by the rule above:

**factor of a kind = the study's human hours for that kind's sessions ÷ the active hours of the same sessions (rule
above), rounded to 0.5.**

The active hours are each session's own record, its agents and the runs in its scratchpad, from the start of the
study's week to the moment the study ran, so both sides cover the same work. A session counts whole under its kind;
the one session the study split by kind (a house design session) counts each part with the active hours the rule above
gave that kind in it, and its document and research parts go with design, the session's main kind.

| Kind | Sessions | Study's human hours | Active hours | Factor |
|---|---|---|---|---|
| Software | a facility map app (260), three Kit sessions (205, 92, 88), a fourth (21), a browser tool (14), and the design session's software part (12) | 692 | 45.96 | 15.06, so 15 |
| Design | a house design session (50), and the other's design, document and research parts (115 + 15 + 12) | 192 | 38.52 | 4.98, so 5 |
| Browser and admin | freight and email (13), online orders (8), and the design session's admin part (28) | 49 | 8.97 | 5.46, so 5.5 |
| Small or mixed | 14 short sessions | 23.5 | 9.23 | 2.55, so 2.5 |

With the simple rule's active hours, the factors were 12, 5, 2.5 and 2. Browser and admin moves the most: its sessions wait
the most (on the person, on pages, on agents), so the rule above finds the fewest active hours in them, and the design
session's admin part is 28 human hours in 4.4 active hours. Without that part, the browser and admin factor would be 4.5.
The factors can be checked again with a new study, and changed in `WORK`.

## In words

- **One person:** 8 hours a day, 40 a week, 4.33 weeks a month, 52 weeks a year. The unit is the one that reads best:
  minutes under an hour, then hours under a day, days under 2 weeks, weeks under 3 months, months under 2 years, then
  years.
- **People full time:** human hours ÷ (8 hours × the weekdays in the period, at least 1). Under 1: "less than 1 person
  full time".
- **Numbers:** one decimal under 10, and none when it is whole; whole numbers from 10.

## Tests

`tools/usage-scan-test.py` (made-up records with each kind of wait, the kinds of work, and the Haiku call with a
stand-in), `tools/usage-words-test.swift` (the words and a period's sums), `phone/test/human.test.ts` (the phone's words,
with the same examples), and `tools/phone-test.swift` (what goes to the phone).
