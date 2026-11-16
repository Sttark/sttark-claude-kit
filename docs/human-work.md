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
| Software | 12 |
| Design | 5 |
| Browser and admin | 2.5 |
| Small or mixed | 2 |

They are set in one place, `WORK` in `Resources/hooks/usage-scan.py`; the window and the phone take them, and the
words of the ⓘ note, from the scan's output.

**Where they come from.** A one-time study (November 2026) had reviewers read a week of one Mac's records, the 24
sessions that held 92% of that week's active hours, and estimate how long a person would take for each. Their
estimate divided by the session's active hours fell into groups by kind of work: six software sessions from 4.5 to 14.7,
half of them at 12.5 or more; two house design sessions, 4.2 and 7.2; two browser and admin sessions (orders,
freight, email), 2.0 and 3.1; and 14 short sessions, together 1.8. The factors were chosen from those groups.

The study measured active hours with a simpler rule: the gaps of 5 minutes or less between any two lines of a record.
The rule above leaves out more waits (notes between turns made many idle gaps look active). For the same week it finds
112 active hours where the simple rule found 148, mostly less in the sessions' own records, which wait on the person
and on agents; agents' records change little. So the estimate is lower than the study's factors and the simple rule
would give together. The factors can be checked again with a new study, and changed in `WORK`.

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
