# Sttark Claude Kit: notes for agents

Read README.md before you change anything. It says what each part does, and how it is built, tested and released.

- Test on copies (`STTARK_KIT_DIR`, `STTARK_KIT_LOG` and the other test variables in the README), never against live sessions or the live server. Never bring an app to the front or send keystrokes.

## What's new notes

Every pull request that changes what a person sees, or how they work with Claude sessions, adds a What's new note in the same pull request. The Kit shows each note once to each person, after the update that brings it. Bug fixes and internal changes get no note.

- **Needs a note:** a new menu item, window or notice; a new or changed Sttark working rule; a new command or phrase that a person or a session uses; a change in what sessions do for the person.
- **No note:** a fix that makes something work as the README already says, tests, tools, workflows, refactors, log lines, wording.
- **The files:** `whats-new/<slug>.md` and its picture `whats-new/<slug>.gif` (or `.png` or `.svg`). The slug is how the Kit remembers who saw a note, so never rename a note that has shipped. The format is at the top of `tools/whats-new.py`; the notes already there are examples.
- **The words:** all in ASD-STE100 Simplified Technical English. A title in sentence case; an `**Icon:**` line with an SF Symbol name; a `**Kind:**` line, `New` (a thing people did not have) or `Better` (a thing they had works better); one sentence of at most 20 words that says what changes for the person, which the What's new sheet shows too; then 2 or 3 points (`- ...`), one sentence of at most 20 words each. One point says how to start, in the exact words of the menu and the commands (check them in the code). No people's names, no dates, no lists of people, no version numbers: the page shows the day and version from git.
- **Replaces:** when a change makes an older note wrong (a button it names is gone, a step it gives no longer works), add a line `**Replaces:** <old-slug>` (more than one: separate them with commas) after the `**Kind:**` line. The app never shows a replaced note again. Do not edit or delete a shipped note to fix it.
- **How long a note shows:** the page shows a note for 7 days after its update arrives on a Mac, and an unseen note until the person sees it. So a note is about the change, not a manual.
- **The picture:** only the part that matters, never a whole window made smaller: at most 880 by 560 pixels, drawn at 2x, so the page shows it at its own size and its words stay readable. One simple diagram, a crop of the window, or a short GIF for anything that moves, and the same picture for dark mode as `<slug>-dark.gif` (or `.png`, `.svg`) beside it. `tools/whats-new-pictures.swift` draws the GIFs in the brand's colors, light and dark; `tools/screenshot.swift` makes the window crops; add one the same way. A GIF moves at 25 frames a second, holds each state long enough to read its words, holds its last state at least 2 seconds, and shows what really occurs (a limit that resets drops to 0 at once). Check it with `tools/whats-new-motion.swift`, which plays the real page and the bigger picture in light and dark and writes a sheet of what shows every 0.25 seconds.
- **Before the pull request:** `python3 tools/whats-new.py check` (the facts; the same check fails a pull request), `python3 tools/whats-new.py ste whats-new/<slug>.md` (the Kit's STE check, with Haiku), and draw the popup with `tools/screenshot.swift` (`STTARK_SHOT_DARK=<folder>` for dark mode too) and look at `docs/whats-new.png` and `docs/window-news.png` in light and dark.
- **On the pull request:** `.github/workflows/whats-new.yml` asks, with a comment and a neutral check, when a change looks like something people notice and adds no note. Answer with a note, or with a line `What's new: none, <why>` in the description.

<!-- sttark-app-guide -->
## The Sttark Brand and App Guidelines

The server in `phone/` (Kit on your phone, kit.sttark.com) is a Sttark web
app; its own notes are in `phone/README.md`. Before any work on its pages,
read all five Apps chapters of the Sttark Brand and App Guidelines in full: [building-web-apps](https://docs.sttark.com/company/sttark-brand-and-app-guidelines/guide/building-web-apps), [look](https://docs.sttark.com/company/sttark-brand-and-app-guidelines/guide/look), [pages-and-behavior](https://docs.sttark.com/company/sttark-brand-and-app-guidelines/guide/pages-and-behavior), [sign-in-and-access](https://docs.sttark.com/company/sttark-brand-and-app-guidelines/guide/sign-in-and-access), [checks](https://docs.sttark.com/company/sttark-brand-and-app-guidelines/guide/checks)
(with the Sttark Workrouter connector, `docs_read` on
`/company/sttark-brand-and-app-guidelines/guide/<chapter>`). Start from what
each page is for, as its "How to decide" says. Read `DESIGN-DECISIONS.md`
with the guide, and never re-raise a decision listed there.

Before opening a pull request, run `npm run check:pages:changed` in `phone`: it
starts the app on made-up data, checks the pages the change reaches at
phone and desktop width, light and dark, as each kind of person, and stops
it. Fix what fails, and answer its Questions in the pull request. The check
lives in Sttark/sttark-docs `page-check/`; change it there, never here.
