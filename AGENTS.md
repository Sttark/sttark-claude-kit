# Sttark Claude Kit: notes for agents

Read README.md before you change anything. It says what each part does, and how it is built, tested and released.

- Test on copies (`STTARK_KIT_DIR`, `STTARK_KIT_LOG` and the other test variables in the README), never against live sessions or the live server. Never bring an app to the front or send keystrokes.

## What's new notes

Every pull request that changes what a person sees, or how they work with Claude sessions, adds a What's new note in the same pull request. The Kit shows each note once to each person, after the update that brings it. Bug fixes and internal changes get no note.

- **Needs a note:** a new menu item, window or notice; a new or changed Sttark working rule; a new command or phrase that a person or a session uses; a change in what sessions do for the person.
- **No note:** a fix that makes something work as the README already says, tests, tools, workflows, refactors, log lines, wording.
- **The files:** `whats-new/<slug>.md` and its picture `whats-new/<slug>.gif` (or `.png` or `.svg`). The slug is how the Kit remembers who saw a note, so never rename a note that has shipped. The format is at the top of `tools/whats-new.py`; the notes already there are examples.
- **The words:** a title in sentence case; an `**Icon:**` line with an SF Symbol name and an `**In short:**` line of at most 15 words, which the What's new sheet shows; 2 to 4 short sentences in ASD-STE100 Simplified Technical English that say what is new; a `**What you do:**` line with what the person does differently, in the exact words of the menu and the commands (check them in the code); no people's names, no dates, no lists of people, no version numbers.
- **The picture:** one simple diagram, or a short GIF for anything that moves, and the same picture for dark mode as `<slug>-dark.gif` (or `.png`, `.svg`) beside it. `tools/whats-new-pictures.swift` draws the GIFs in the brand's colors, light and dark; add one the same way.
- **Before the pull request:** `python3 tools/whats-new.py check` (the facts; the same check fails a pull request), `python3 tools/whats-new.py ste whats-new/<slug>.md` (the Kit's STE check, with Haiku), and draw the popup with `tools/screenshot.swift` (`STTARK_SHOT_DARK=<folder>` for dark mode too) and look at `docs/whats-new.png` in light and dark.
- **On the pull request:** `.github/workflows/whats-new.yml` asks, with a comment and a neutral check, when a change looks like something people notice and adds no note. Answer with a note, or with a line `What's new: none, <why>` in the description.
