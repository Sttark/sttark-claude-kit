// Tests the Events page's reading of the log and the trim of the logs, on a temporary folder, never the real logs.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/events-test tools/events-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/events-test
import Foundation

@main struct EventsTest {
    static var failed = 0
    static func check(_ ok: Bool, _ what: String) { print((ok ? "ok    " : "FAIL  ") + what); if !ok { failed += 1 } }

    static func main() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("events-test-\(getpid())")
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        func at(_ m: Double) -> String { f.string(from: Date().addingTimeInterval(-m * 60)) }

        // Names come from the Kit's state file.
        var names = Events.Names()
        names.byCse["cse_01AAAtest1"] = "Press color"; names.cseByName["Press color"] = "cse_01AAAtest1"
        names.bySid["f46255ef-0000"] = "Press color"; names.cseBySid["f46255ef-0000"] = "cse_01AAAtest1"

        var lines = [
            at(30) + " change cse_01AAAtest1 low->high (2.0s) high - Needs judgment. | Fix the color page",
            at(20) + " limit  hold   f46255ef/a10a43cb at 90%: the weekly limit is at 93%, until Sat 2:00 AM (Bash)",
            at(20) + " limit  wait   f46255ef/a10a43cb at 90%: the weekly limit is at 93%, until Sat 2:00 AM, with no model calls until it ends",
            at(10) + " ste    f46255ef ok (3.1s)",
            at(8) + " agent  cse_01AAAtest1 Explore ->low (1.9s) low - Simple file search. | Find the color files",
            at(7) + " agent  cse_01AAAtest1 fork high->xhigh (2.2s) xhigh - Builds a feature end to end. | Build the page",
            at(6) + " agent  cse_01AAAtest1 general-purpose kept high - set in the call | Check the build",
            at(6) + " agent  cse_01AAAtest1 general-purpose replaced xhigh (set in the call) with low (1.9s) low - Simple file search. | List the job fields",
            at(6) + " agent  cse_01AAAtest1 reviewer replaced high (set by its definition) with high (2.0s) high - Needs judgment. | Review the diff",
            at(6) + " agent  cse_01AAAtest1 general-purpose replaced higher (set in the call) with medium (2.0s) medium - A short edit. | Fix one label",
            at(6) + " agent  cse_01AAAtest1 Explore left at high - Auto effort is off | Find the old jobs",
            at(6) + " agent  cse_01AAAtest1 general-purpose left at xhigh (set in the call) - the session is on Manual | Check the press log",
            at(6) + " agent  cse_01AAAtest1 fork left at high - the session is on Manual | Build the filters",
            at(6) + " agent  f46255ef Explore left at ? - Auto effort is off | Find the new jobs",
            at(6) + " agent  cse_01AAAtest1 fork at high (1.9s) medium - A short edit. | Small edit",
            at(6) + " agent  cse_01AAAtest1 fork stopped - start a briefed agent instead | Build the job card",
            at(6) + " agent  f46255ef fork stopped - start a briefed agent instead | Build the die list",
            at(5) + " migrate 3796db69 \"Bin label sizes\" moved to Remote Control as cse_01BBBtest2; closed it in Terminal (window)",
        ]
        for m in stride(from: 50.0, through: 1, by: -7) { lines.append(at(m) + " limit  usage read failed: HTTP Error 429: Too Many Requests; next read in 2 min, using the last read") }
        for m in [2880.0, 2875, 2870] { lines.append(at(m) + " limit  usage read failed: HTTP Error 429: Too Many Requests; next read in 2 min, using the last read") }
        lines.sort()
        let log = dir.appendingPathComponent("kit.log")
        try! (lines.joined(separator: "\n") + "\n").write(to: log, atomically: true, encoding: .utf8)
        let ev = Events.read(kitLog: log, bypassLog: dir.appendingPathComponent("none.log"), names: names)

        let change = ev.first { $0.kind == .effort && $0.text.hasPrefix("Effort raised from Low") }
        check(change?.name == "Press color" && change?.text == "Effort raised from Low to High", "an effort change reads in plain words under the session's name")
        check(change?.detail.contains("Why: Needs judgment.") == true, "the reason is in the row's detail")
        let holds = ev.filter { $0.kind == .limit }
        check(holds.count == 1 && holds[0].text == "Held: the weekly limit is at 93%. Goes on Sat 2:00 AM", "a hold and its wait are one row")
        let usage = ev.filter { $0.kind == .problem }
        check(usage.count == 2 && usage[0].count == 8 && usage[0].level == .warn && usage[1].count == 3,
              "a problem that occurs again is one row a day, with that day's count")
        check(ev.first { $0.kind == .check }?.routine == true, "a reply check that passed is routine")
        check(ev.first?.last ?? .distantPast >= ev.last?.last ?? .distantFuture, "newest first")
        check(!ev.contains { $0.text.contains("cse_") || $0.text.contains("f46255ef") }, "no ids in the sentences")
        let agent = ev.first { $0.text == "Agent \u{201C}Find the color files\u{201D} set to Low effort" }
        check(agent?.name == "Press color" && agent?.detail.contains("Why: Simple file search.") == true,
              "a subagent's pick reads in plain words under its session's name")
        check(ev.contains { $0.text == "Effort raised from High to Extra so fork \u{201C}Build the page\u{201D} starts at Extra" },
              "a raise for a fork says why")
        check(ev.contains { $0.text == "Agent \u{201C}Check the build\u{201D} keeps High effort" && $0.routine }, "an effort set in the call is kept, as a routine row")
        let aRaise = ev.first { $0.text.hasSuffix("so fork \u{201C}Build the page\u{201D} starts at Extra") }
        check(aRaise?.detail.first == "A fork runs at the session's level, also when that level changes. So the Kit does not set the session back.",
              "an older line: a raise for a fork says that a fork follows the session's level")
        let aReplaced = ev.first { $0.text == "Agent \u{201C}List the job fields\u{201D} set to Low effort" }
        check(aReplaced?.name == "Press color" && aReplaced?.routine == false
              && aReplaced?.detail == ["Why: Simple file search.", "It replaces Extra, the level of the call.",
                                      "Agent type: general-purpose. It keeps this level until it finishes."],
              "a level that the Kit replaced in the call reads in plain words")
        let aSame = ev.first { $0.text == "Agent \u{201C}Review the diff\u{201D} set to High effort" }
        check(aSame?.detail.contains("The level of its definition was High too.") == true,
              "the same level as the definition's")
        let aStep = ev.first { $0.text == "Agent \u{201C}Fix one label\u{201D} set to Medium effort" }
        check(aStep?.detail.contains("It replaces one step over the session's level, the level of the call.") == true,
              "a call that asked for one step higher")
        let aOff = ev.first { $0.text == "Agent \u{201C}Find the old jobs\u{201D} left at High effort" }
        check(aOff?.routine == true && aOff?.name == "Press color"
              && aOff?.detail == ["The Kit did not set it: Auto effort is off.", "It runs at the session's level, also when that level changes."],
              "Auto effort off: an agent left at the session's level, as a routine row")
        let aManual = ev.first { $0.text == "Agent \u{201C}Check the press log\u{201D} left at Extra effort" }
        check(aManual?.detail == ["The Kit did not set it: the session is on Manual.", "The call sets this level."],
              "Manual: an agent left at the level of its call")
        let aForkLeft = ev.first { $0.text == "Fork \u{201C}Build the filters\u{201D} left at High effort" }
        check(aForkLeft?.detail.last == "A fork runs at the session's level, also when that level changes.", "Manual: a fork left at the session's level")
        check(ev.contains { $0.text == "Agent \u{201C}Find the new jobs\u{201D} left at the session's level" },
              "a level the hook did not know reads as the session's level, never a question mark")
        let aForkAt = ev.first { $0.text == "Fork \u{201C}Small edit\u{201D} starts at High effort, the session's level" }
        check(aForkAt?.routine == true && aForkAt?.detail == ["It needs Medium: A short edit.", "A fork runs at the session's level, also when that level changes."],
              "a fork that needs less starts at the session's level")
        let aStopped = ev.first { $0.text == "Fork \u{201C}Build the job card\u{201D} stopped" }
        check(aStopped?.name == "Press color" && aStopped?.routine == false && aStopped?.kind == .effort
              && aStopped?.detail == ["A fork runs at the session's level, so it cannot get a level for its own work.",
                                      "Claude starts a new agent with a full brief in its place, and the Kit sets the level of that agent."],
              "a fork the Kit stopped reads in plain words under its session's name: \(String(describing: aStopped?.text)) \(String(describing: aStopped?.detail))")
        check(ev.contains { $0.text == "Fork \u{201C}Build the die list\u{201D} stopped" },
              "a stopped fork in a session that is not on Remote Control (a short id) reads the same")
        let moved = ev.first { $0.text == "Moved to Remote Control from this Mac only" }
        check(moved?.name == "Bin label sizes" && moved?.detail.contains { $0.contains("open in Terminal") } == true,
              "a move to Remote Control reads in plain words under the session's name")

        // The Remote Control server: what its health check does, in plain words, with the problems as problems
        let server = [
            at(9) + " server ended 25 old copies of the server that earlier starts left running",
            at(8) + " server answered same-dir: the spawn mode, so every session starts in ~/src",
            at(7) + " server not connected: it waits on a question the Kit can't answer: Region [1/2]:",
            at(6) + " server stopped, and macOS started it again",
            at(5) + " server not connected: it stopped 3 times soon after it started; it showed: Error: x. The Kit starts it again in 1 min.",
            at(4) + " server start command updated: it gives --spawn same-dir when Claude Code has it, from the next start",
            at(3) + " keep   the server is not connected: 4 session(s) on it wait until it connects, and none starts on its own",
        ]
        let slog = dir.appendingPathComponent("server.log")
        try! (server.joined(separator: "\n") + "\n").write(to: slog, atomically: true, encoding: .utf8)
        let sev = Events.read(kitLog: slog, bypassLog: dir.appendingPathComponent("none.log"), names: names)
        check(sev.contains { $0.kind == .problem && $0.level == .warn && $0.text == "Ended 25 old copies of the Remote Control server" },
              "old copies of the server that were ended are a problem row, with how many")
        check(sev.contains { $0.text == "The server asked which spawn mode to use, so the Kit chose same-dir" && $0.level == .info },
              "the spawn mode answer reads in plain words")
        check(sev.filter { $0.kind == .problem && $0.text.hasPrefix("Remote Control server not connected: ") }.count == 2,
              "a question the Kit can't answer, and a server that stops again and again, are problem rows")
        check(sev.contains { $0.kind == .restart && $0.level == .warn && $0.text == "Remote Control server stopped, and macOS started it again" },
              "a server that stopped and came back is a warning")
        check(sev.contains { $0.routine && $0.text == "Remote Control server: start command updated" }, "the updated start command is a routine row")
        check(sev.contains { $0.kind == .restart && $0.level == .warn && $0.text == "Sessions on the server wait until it connects" },
              "sessions that wait for the server read in plain words")

        // Only the person archives: the Kit's own lines say it stopped sessions without archiving them, and why it ran one on its own
        let noArchive = [
            at(5) + " halt   the Mac shuts down: ended 3 Claude Code process(es) of 3 chat(s) the Kit runs, so none is archived",
            at(4) + " reattach cse_01AAAtest2 \"Bird deterrent\" the server won't start it (2 wakes did not start it), so it runs on its own on the same link, from 113",
            at(3) + " reattach cse_01AAAtest3 \"Facility map\" the server won't start it (it was archived, then unarchived), so it runs on its own on the same link, from 9",
            at(2) + " keep   cse_01AAAtest4 \"Rivian claims\" archived or deleted in the Claude app while it was stopped; left it so",
            at(1) + " move   cse_01AAAtest5 \"JetFly\" the server won't start it (2 wakes did not start it), so it runs on its own as cse_01AAAtest6; 0 Routine(s) moved, old entry renamed \"(old link)\" and left in the list",
        ]
        let klog = dir.appendingPathComponent("kept.log")
        try! (noArchive.joined(separator: "\n") + "\n").write(to: klog, atomically: true, encoding: .utf8)
        let kev = Events.read(kitLog: klog, bypassLog: dir.appendingPathComponent("none.log"), names: names)
        check(kev.contains { $0.routine && $0.text == "The Mac shuts down, so the Kit stopped its sessions without archiving them" },
              "the halt before a shutdown is a routine row that says nothing was archived")
        check(kev.first { $0.name == "Bird deterrent" }?.text == "The server did not start it, so the Kit started it on the same link",
              "a session the server did not start after wakes is not called unarchived")
        check(kev.first { $0.name == "Facility map" }?.text == "Unarchived, so the Kit started it on the same link",
              "an unarchived session still reads as unarchived")
        check(kev.first { $0.name == "Rivian claims" }?.text == "Archived in the Claude app while it was stopped, so the Kit left it archived",
              "a session archived while stopped is left archived")
        check(kev.first { $0.name == "JetFly" }?.text == "Moved to a new link; the old entry stays in your list",
              "a move leaves the old entry in the list")

        // A session started on its own: its folder trusted in Claude Code first, and a start that waits at the trust question
        let trust = [
            at(4) + " trust  /Users/x/src/airpark home trusted in Claude Code, so a chat that ran there starts without its safety question",
            at(3) + " trust  /Users/x/src/other could not be marked trusted in Claude Code: PermissionError(13, 'Permission denied')",
            at(2) + " keep   cse_01AAAtest1 \"Press color\" won't start, and starting it on a new link didn't work either - it waits in kit-6850f368 at Claude Code's question whether to trust /Users/x/src/airpark home",
        ]
        let tlog = dir.appendingPathComponent("trust.log")
        try! (trust.joined(separator: "\n") + "\n").write(to: tlog, atomically: true, encoding: .utf8)
        let tev = Events.read(kitLog: tlog, bypassLog: dir.appendingPathComponent("none.log"), names: names)
        check(tev.contains { $0.kind == .restart && $0.routine && $0.text == "Trusted a session's folder in Claude Code"
                             && $0.detail.first == "Folder: /Users/x/src/airpark home" }, "a folder trusted for a session is a routine row, with the folder")
        check(tev.contains { $0.level == .warn && $0.text == "Could not trust a session's folder in Claude Code"
                             && $0.detail.first == "Folder: /Users/x/src/other" }, "a folder that could not be trusted is a warning")
        let stuck = tev.first { $0.name == "Press color" }
        check(stuck?.text == "Won't start, and starting it on a new link didn't work either"
              && stuck?.detail.contains("Why: it waits in kit-6850f368 at Claude Code's question whether to trust /Users/x/src/airpark home") == true,
              "a start that waits at the trust question says why")

        // Trim: 30 days, lines with no date go with the dated line before them, a writer that holds the file open
        // in append mode (as launchd does) goes on at the new end, and a second trim finds nothing to cut.
        var s = ""
        for day in stride(from: 40, through: 0, by: -1) {
            for i in 0..<3 { s += f.string(from: Date().addingTimeInterval(-Double(day) * 86400 + Double(i))) + " app    day \(day) #\(i)\n" + (i == 1 ? "  no date\n" : "") }
        }
        let t = dir.appendingPathComponent("t.log")
        try! s.write(to: t, atomically: true, encoding: .utf8)
        let fd = open(t.path, O_WRONLY | O_APPEND)
        let r = KitLogs.trim(t)
        _ = "late line\n".withCString { write(fd, $0, strlen($0)) }
        close(fd)
        let out = try! String(contentsOf: t, encoding: .utf8).split(separator: "\n")
        check(r != nil && out.first?.contains("day 30 #0") == true, "lines older than 30 days are cut")
        check(out.last == "late line", "a line written after the trim lands at the end")
        check(KitLogs.trim(t) == nil, "a second trim cuts nothing")
        let big = String(repeating: f.string(from: Date()) + " app    " + String(repeating: "x", count: 90) + "\n", count: 2000)
        try! big.write(to: t, atomically: true, encoding: .utf8)
        _ = KitLogs.trim(t, bytes: 50_000)
        let kept = try! Data(contentsOf: t)
        check(kept.count <= 50_000 && kept.first == UInt8(ascii: "2"), "the size cap keeps whole lines, the newest")

        // A menu click on a session shows as that session opened in the Claude app, with no raw link or id.
        let m = Events.kitLine(f.string(from: Date()) + " app    menu   open claude://code/cse_01AAAtest1", names)
        check(m?.name == "Press color" && m?.text == "Opened in the Claude app", "a menu open names the session, no link")
        let w = Events.kitLine(f.string(from: Date()) + " wait   7f15a1 cse_01AAAtest1 \"Press color\" set: a reply on email thread 1a1d6158534acc04, by Wed 5:00 PM", names)
        check(w.map { !$0.text.contains("1a1d6158") && !$0.text.contains("cse_") } == true, "no email thread id in a wait row")
        // Unarchive on the Archived page (claude-wait --unarchive): the session, in plain words, and who asked
        let b = Events.kitLine(f.string(from: Date()) + " wait   cse_01AAAtest1 \"Press color\" brought back from the archive (window)", names)
        check(b?.name == "Press color" && b?.text == "Unarchived, on the same link" && b?.kind == .restart
              && b?.detail.first?.contains("the Kit window") == true, "a session brought back from the archive")
        let n = Events.kitLine(f.string(from: Date()) + " wait   cse_01AAAtest1 \"Press color\" not brought back from the archive (phone): its conversation is not on this Mac", names)
        check(n?.text == "Not unarchived: its conversation is not on this Mac" && n?.level == .warn
              && n?.detail.first?.contains("the phone") == true, "one that could not come back says why")
        // The reply watch (watch.py): a session brought back for new messages, a read, a failed read, and the working
        // rules' reply wait check.
        let wb = Events.kitLine(f.string(from: Date()) + " watch  cse_01AAAtes \"Press color\" brought back for 1 new message: Sam <help@utility.example> \"[Ticket 1] Contact Us\"", names)
        check(wb?.name == "Press color" && wb?.session == "cse_01AAAtest1" && wb?.kind == .restart && wb?.text == "Brought back: new messages came in from someone it contacted"
              && wb?.detail.first?.contains("help@utility.example") == true, "a session the reply watch brought back, with what came")
        // An archived session with no open wait: not watched (routine), or messages that came for it, not told.
        let wa = Events.kitLine(f.string(from: Date()) + " watch  cse_01AAAtes \"Press color\" not watched: archived with no wait", names)
        check(wa?.name == "Press color" && wa?.session == "cse_01AAAtest1" && wa?.kind == .wait && wa?.routine == true
              && wa?.text == "Not watched: it is archived and waits on no one",
              "an archived session with no wait: one routine row, in plain words")
        let wt = Events.kitLine(f.string(from: Date()) + " watch  cse_01AAAtes \"Press color\" not told of 1 new message: archived with no wait: Sam <help@utility.example> \"Re: color\"", names)
        check(wt?.name == "Press color" && wt?.kind == .wait && wt?.routine == false
              && wt?.text == "Not brought back: it is archived and waits on no one"
              && wt?.detail.first == "Messages: Sam <help@utility.example> \"Re: color\"",
              "messages for an archived session with no wait: not brought back, with what came")
        let wr = Events.kitLine(f.string(from: Date()) + " watch  person@sample.example read (Haiku through Workrouter): 4 new messages, 0 for a session", names)
        check(wr?.kind == .check && wr?.routine == true && wr?.text == "Reply watch read person@sample.example: 4 new messages, 0 for a session",
              "a read of the reply watch is a routine check")
        let wf = Events.kitLine(f.string(from: Date()) + " watch  person@sample.example read failed: Haiku did not call gmail_search", names)
        check(wf?.kind == .problem && wf?.text == "The reply watch could not read person@sample.example"
              && wf?.detail.first == "Haiku did not call gmail_search", "a failed read is a problem, with why")
        let wn = Events.kitLine(f.string(from: Date()) + " watch  f46255ef contacted utility.example (a web form) with no reply wait: noted for the next prompt", names)
        check(wn?.name == "Press color" && wn?.kind == .check && wn?.text == "Contacted someone and set no wait for the answer",
              "the reply wait check names the session")
        // The check of a broad match: a skip shows, with who, the first words and why; a yes is routine; a failed
        // check is a problem.
        let ws = Events.kitLine(f.string(from: Date()) + " watch  skip cse_01AAAtes \"Press color\" Jo Sample in Chat: not about this session's work: Lunch is here in the break room | Lunch, not the press color", names)
        check(ws?.name == "Press color" && ws?.session == "cse_01AAAtest1" && ws?.kind == .wait && ws?.routine == false
              && ws?.text == "Not brought back: a new message was about other work"
              && ws?.detail.prefix(3) == ["From: Jo Sample in Chat.", "Message: \u{201C}Lunch is here in the break room\u{201D}", "Why: Lunch, not the press color"],
              "a message the check found to be about other work: one row, with who, the first words and why")
        let wy = Events.kitLine(f.string(from: Date()) + " watch  checked cse_01AAAtes \"Press color\" Sam <help@utility.example>: about this session's work: Re: color | It answers the question", names)
        check(wy?.name == "Press color" && wy?.kind == .check && wy?.routine == true && wy?.text == "A new message is about its work",
              "a message the check found to be about its work is a routine check")
        let wx = Events.kitLine(f.string(from: Date()) + " watch  cse_01AAAtes \"Press color\" could not check a message (RuntimeError: exit 1: ); it comes back for it all the same: Sam: Re: color", names)
        check(wx?.kind == .problem && wx?.level == .warn && wx?.text == "The reply watch could not check a message, so it brought the session back",
              "a check that failed is a problem, and says the session came back")
        // The person's own reply where a session watches or waits: what they wrote and where, then each thing the Kit
        // did; a bring-back with a note is a restart row; the note at the next prompt; their own Chat post about other work.
        let own = Events.kitLine(f.string(from: Date()) + " watch  replied cse_01AAAtes \"Press color\" in the email thread \"Ink quote\", 2:30 PM: Tuesday works, thanks. Book the ocean express. | its message in the Kit \"Ink quote is in\" now shows You replied 2:30 PM; its wait 0d39c2 shows You replied 2:30 PM and still waits for the other person; brought back with a note: a message kept in the Kit depends on it", names)
        check(own?.name == "Press color" && own?.session == "cse_01AAAtest1" && own?.kind == .restart && own?.routine == false
              && own?.text == "Brought back with a note: you replied in the email thread \u{201C}Ink quote\u{201D}"
              && own?.detail == ["At 2:30 PM you wrote: \u{201C}Tuesday works, thanks. Book the ocean express.\u{201D}",
                                 "Its message in the Kit, \u{201C}Ink quote is in\u{201D}, now shows \u{201C}You replied 2:30 PM\u{201D}: it is handled.",
                                 "Its email reply wait shows \u{201C}You replied 2:30 PM\u{201D} and still waits for the other person: your own reply does not end it.",
                                 "The Kit brought it back with a note, since a message kept in the Kit depends on it.",
                                 "No alert, and no message to anyone."],
              "the person's own reply that a kept message depends on: a bring-back row, what they wrote and what the Kit did")
        let ownNote = Events.kitLine(f.string(from: Date()) + " watch  replied cse_01AAAtes \"Press color\" on its Asana task 1200000000000001, Wed 9:05 AM: Done | it ships | noted for its next prompt", names)
        check(ownNote?.kind == .wait && ownNote?.text == "You replied on its Asana task" && ownNote?.routine == false
              && ownNote?.detail == ["At Wed 9:05 AM you wrote: \u{201C}Done | it ships\u{201D}", "Asana task: https://app.asana.com/0/0/1200000000000001",
                                     "The session gets a note about it with its next prompt.", "No alert, and no message to anyone."]
              && !(ownNote?.text.contains("1200000000000001") ?? true),
              "on an Asana task: no id in the sentence, the task's link in the detail; a | in the person's words stays theirs")
        let ownLate = Events.kitLine(f.string(from: Date()) + " watch  replied cse_01AAAtes \"Press color\" in a Chat space it posted in, Nov 18 4:10 PM: ok | not told: it read the reply at 4:12 PM", names)
        check(ownLate?.text == "You replied in a Chat space it posted in" && ownLate?.routine == true
              && ownLate?.detail == ["At Nov 18 4:10 PM you wrote: \u{201C}ok\u{201D}", "Not told: it read the reply at 4:12 PM."],
              "a reply the session read itself: routine, and it says why it was not told, with when")
        let ownSent = Events.kitLine(f.string(from: Date()) + " watch  replied cse_01AAAtes \"Press color\" in the email thread \"Ink quote\", 2:30 PM: Tuesday works | not told: it sent this mail itself with claude-window at 2:30 PM", names)
        check(ownSent?.routine == true && ownSent?.detail.last == "Not told: it sent this mail itself with claude-window at 2:30 PM.",
              "a mail the session sent itself: routine, and it says so")
        let ownOld = Events.kitLine(f.string(from: Date()) + " watch  replied cse_01AAAtes \"Press color\" in a Chat space it posted in, Nov 18 4:10 PM: ok | not told: it had a turn since your reply", names)
        check(ownOld?.detail.last == "Not told: it had a turn since your reply.", "an older log line still reads")
        let ownTold = Events.kitLine(f.string(from: Date()) + " watch  replied cse_01AAAtes \"Press color\" in the email thread \"Ink quote\", 2:30 PM: Tuesday works | noted for its next prompt: its records do not show your reply", names)
        check(ownTold?.routine == false && ownTold?.detail == ["At 2:30 PM you wrote: \u{201C}Tuesday works\u{201D}",
                                                               "The session gets a note about it with its next prompt.", "No alert, and no message to anyone."],
              "a reply the session's records do not show: a note with its next prompt")
        let told = Events.kitLine(f.string(from: Date()) + " watch  told cse_01AAAtest1 \"Press color\" of your reply in the thread of its Chat post, with its next prompt", names)
        check(told?.name == "Press color" && told?.kind == .wait && told?.routine == true && told?.text == "Told of your reply, with its next prompt"
              && told?.detail == ["Where: in the thread of its Chat post.", "No alert, and no message to anyone."],
              "the note given with the session's next prompt")
        let toldKit = Events.kitLine(f.string(from: Date()) + " watch  told cse_01AAAtest1 \"Press color\" of your reply in the email thread \"Ink quote\", in the Kit's message", names)
        check(toldKit?.text == "Told of your reply, in the Kit's message" && toldKit?.detail.first == "Where: in the email thread \u{201C}Ink quote\u{201D}.",
              "the note given in the Kit's own message")
        let ownSkip = Events.kitLine(f.string(from: Date()) + " watch  skip cse_01AAAtes \"Press color\" you in Chat: not about this session's work: Lunch is here | Lunch, not the press color", names)
        check(ownSkip?.name == "Press color" && ownSkip?.kind == .wait && ownSkip?.text == "Your Chat post was about other work, so the session was not told"
              && ownSkip?.detail.prefix(2) == ["You wrote: \u{201C}Lunch is here\u{201D}", "Why: Lunch, not the press color"],
              "the person's own Chat post that the check found to be about other work")
        let ownYes = Events.kitLine(f.string(from: Date()) + " watch  checked cse_01AAAtes \"Press color\" you in Chat: about this session's work: The die is fine | It answers the session's post", names)
        check(ownYes?.kind == .check && ownYes?.routine == true && ownYes?.text == "Your Chat post is about its work",
              "the person's own Chat post that is about its work is a routine check")
        // The progress check-ins (checkin.py): one row a check-in under its session, with the note in the detail; a
        // summary that failed, a test run, a hold and the end of the work.
        let ck = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" shown in the Kit | Build the color page, working 45 min | It finished the page and opened pull request 12. Next it checks the links.", names)
        check(ck?.name == "Press color" && ck?.session == "cse_01AAAtest1" && ck?.kind == .wait && ck?.level == .info && ck?.routine == false
              && ck?.text == "Progress check-in: Build the color page, working 45 min"
              && ck?.detail == ["\u{201C}It finished the page and opened pull request 12. Next it checks the links.\u{201D}"],
              "a check-in kept in the Kit: its subject, the note in the detail")
        let cks = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" shown in the Kit; no summary (exit 1: overloaded) | Working 20 min | It made 12 steps since the last note.", names)
        check(cks?.level == .info && cks?.text == "Progress check-in: Working 20 min"
              && cks?.detail.contains { $0.hasPrefix("Haiku gave no summary (exit 1: overloaded)") } == true, "a summary that failed shows in the row")
        let ckd = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" written (dry) | Working 20 min | It made 3 steps.", names)
        let cke = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" work ended after 1 hr 31 min; 6 check-ins", names)
        check(ckd?.routine == true && ckd?.text == "Progress check-in written, not kept (test run): Working 20 min"
              && cke?.routine == true && cke?.text == "Long work ended after 1 hr 31 min; 6 check-ins", "a test run and the end of the work are routine rows")
        // lines from before check-ins stayed in the Kit app (they went the Reach me by ways) still read
        let cs = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" sent by Email, Google Chat | Build the color page, working 45 min | It finished the page and opened pull request 12. Next it checks the links.", names)
        check(cs?.name == "Press color" && cs?.session == "cse_01AAAtest1" && cs?.kind == .wait && cs?.level == .info && cs?.routine == false
              && cs?.text == "Progress check-in sent by Email, Google Chat: Build the color page, working 45 min"
              && cs?.detail == ["\u{201C}It finished the page and opened pull request 12. Next it checks the links.\u{201D}"],
              "a check-in that went: its ways and subject, the note in the detail")
        let cw = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" sent by Email; not by Google Chat (the webhook did not take it: HTTP Error 404); no summary (exit 1: overloaded) | Working 20 min | It made 12 steps in the last 15 min.", names)
        check(cw?.level == .warn && cw?.text == "Progress check-in sent by Email: Working 20 min"
              && cw?.detail.contains("Not sent by Google Chat (the webhook did not take it: HTTP Error 404).") == true
              && cw?.detail.contains { $0.hasPrefix("Haiku gave no summary (exit 1: overloaded)") } == true,
              "a way that failed and a summary that failed show in the row")
        let cn = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" not sent: no way is checked under Reach me by", names)
        check(cn?.level == .warn && cn?.text == "Progress check-in not sent: no way is checked under Reach me by", "no way to send is a warning, with why")
        let cf = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" not sent (Email: gh could not start the mail: HTTP 401) | Working 20 min | It made 3 steps.", names)
        check(cf?.level == .warn && cf?.text == "Progress check-in not sent: Working 20 min"
              && cf?.detail.first == "Email: gh could not start the mail: HTTP 401", "a check-in that went no way says why first")
        let ch = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" skipped: it holds at the usage limit", names)
        let cd = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" would send (dry) | Working 20 min | It made 3 steps.", names)
        let ce = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" work ended after 1 hr 31 min; 6 check-ins sent", names)
        check(ch?.routine == true && ch?.text == "Progress check-in skipped: it holds at the usage limit"
              && cd?.routine == true && cd?.text == "Progress check-in written, not sent (test run): Working 20 min"
              && ce?.routine == true && ce?.text == "Long work ended after 1 hr 31 min; 6 check-ins sent",
              "a hold, a test run and the end of the work are routine rows")
        let cu = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" skipped: Haiku gave no usable note (it is empty, then it repeats its rules: 'Sentence limit: 50 words. Subject first. Active voice.')", names)
        check(cu?.name == "Press color" && cu?.routine == true
              && cu?.text == "Progress check-in skipped: Haiku gave no usable note (it is empty, then it repeats its rules: 'Sentence limit: 50 words. Subject first. Active voice.')",
              "a check-in skipped as Haiku gave no usable note is a routine row, with why")
        let cx = Events.kitLine(f.string(from: Date()) + " checkin error: KeyError: 'sessions'", names)
        check(cx?.kind == .problem && cx?.text == "A progress check-in failed", "an error is a problem")
        // Check-ins in the session (checkin.py in_chat()): each one in the chat, or not and why, in the same row
        let cc = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" shown in the Kit; in the chat | Build the color page, working 45 min | It finished the page and opened pull request 12. Next it checks the links.", names)
        check(cc?.name == "Press color" && cc?.session == "cse_01AAAtest1" && cc?.level == .info && cc?.routine == false
              && cc?.text == "Progress check-in, also in the chat: Build the color page, working 45 min"
              && cc?.detail == ["\u{201C}It finished the page and opened pull request 12. Next it checks the links.\u{201D}",
                                "The Kit typed it into the session as a prompt, and the session answers it in its chat."],
              "a check-in in the chat: the row says so, and the detail how")
        let cnc = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" shown in the Kit; not in the chat: it runs in this Mac's server, which takes no typed prompt | Build the color page, working 45 min | It finished the page.", names)
        check(cnc?.level == .info && cnc?.text == "Progress check-in: Build the color page, working 45 min"
              && cnc?.detail.last == "Not in the chat: it runs in this Mac's server, which takes no typed prompt.",
              "a check-in not in the chat: why, in the detail, with no warning")
        let cna = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" shown in the Kit; no summary (exit 1: overloaded); not in the chat: Haiku gave no summary to send | Working 20 min | It made 12 steps since the last note.", names)
        check(cna?.level == .info && cna?.detail.contains { $0.hasPrefix("Haiku gave no summary (exit 1: overloaded)") } == true
              && cna?.detail.last == "Not in the chat: Haiku gave no summary to send.", "a failed summary does not go in the chat, and says so")
        let cfc = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" shown in the Kit; not in the chat: the Kit could not type it in: it did not start after the Enter key | Working 20 min | It finished the page.", names)
        check(cfc?.level == .warn && cfc?.text == "Progress check-in: Working 20 min"
              && cfc?.detail.last == "Not in the chat: the Kit could not type it in: it did not start after the Enter key.",
              "a check-in the Kit could not type in is a warning, with why")
        let cdc = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" written (dry); would go in the chat | Working 20 min | It finished the page.", names)
        check(cdc?.routine == true && cdc?.text == "Progress check-in written, not kept (test run): Working 20 min"
              && cdc?.detail.last == "Test run: it would go in the session's chat, and nothing was typed.", "a test run types nothing, and says so")
        // the check-in timer in the session (checkin-timer.py): asked, set, each check-in, a reminder, deleted
        let ta = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" timer asked | agent \"Build the color page\" started, every 15 min (6,21,36,51 * * * *)", names)
        check(ta?.name == "Press color" && ta?.session == "cse_01AAAtest1" && ta?.routine == true && ta?.text == "Check-in timer asked for"
              && ta?.detail == ["Work runs in the background (agent \"Build the color page\" started, every 15 min (6,21,36,51 * * * *)), so the Kit asked the session to set its check-in timer."],
              "the ask for a timer is a routine row, with the work that started it")
        let ts = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" timer set 3f9a2c1d | every 15 min (6,21,36,51 * * * *)", names)
        check(ts?.routine == true && ts?.text == "Check-in timer set" && ts?.detail == ["The session set its check-in timer, job 3f9a2c1d: every 15 min (6,21,36,51 * * * *)."],
              "a timer set is a routine row, with its job")
        let tc = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" timer check-in 3f9a2c1d | 2 agents, 1 background command", names)
        check(tc?.routine == false && tc?.level == .info && tc?.text == "Check-in in the session's chat"
              && tc?.detail == ["What runs: 2 agents, 1 background command. The Kit gave the session this list for its answer of one or two lines."],
              "a check-in in the chat is a row of its own, with what runs")
        let tn = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" timer check-in 3f9a2c1d | no work runs: asked to delete it", names)
        check(tn?.text == "Check-in in the session's chat"
              && tn?.detail == ["The Kit saw no agent or background command at work, so it told the session to delete the timer."],
              "a check-in with no work: the Kit told the session to delete the timer")
        let tr = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" timer reminder 3f9a2c1d | no work runs: asked to delete it", names)
        let te = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" timer ended 3f9a2c1d", names)
        check(tr?.routine == true && tr?.text == "Check-in timer: the Kit told the session to delete it"
              && te?.routine == true && te?.text == "Check-in timer deleted" && te?.detail == ["The session deleted its check-in timer, job 3f9a2c1d."],
              "a reminder and a deleted timer are routine rows")
        let tx = Events.kitLine(f.string(from: Date()) + " checkin timer error: KeyError: 'job'", names)
        check(tx?.kind == .problem && tx?.level == .warn && tx?.text == "The check-in timer hook failed" && tx?.detail == ["KeyError: 'job'"],
              "an error of the timer hook is a problem")
        let ckeep = Events.kitLine(f.string(from: Date()) + " keep   cse_01AAAtest1 high - a check-in from the Kit, which needs no new level | [Sttark Claude Kit] Check-in: It finished the page and opened pull request 12.", names)
        check(ckeep?.kind == .effort && ckeep?.routine == true && ckeep?.text == "Effort stays at High"
              && ckeep?.detail.first == "Why: a check-in from the Kit, which needs no new level",
              "the effort hook's line for a check-in in the chat is a routine row")

        // One session for the same work (same-work.py): the question under the new session, the prompt under the open
        // session it went to, the checks that find nothing as routine rows, and what failed as problems
        var sn = names
        sn.byCse["cse_01NEWtest3"] = "Color page"; sn.cseByName["Color page"] = "cse_01NEWtest3"
        func same(_ s: String) -> KitEvent? { Events.kitLine(f.string(from: Date()) + " same   " + s, sn) }
        let sa = same("cse_01NEWtest3 asks: same work as cse_01AAAtest1 \"Press color\", started 2 hours ago (1.8s) - the same press color page | Add a gray balance chart to the color page")
        check(sa?.kind == .same && sa?.session == "cse_01NEWtest3" && sa?.name == "Color page" && sa?.routine == false
              && sa?.text == "Same work as \u{201C}Press color\u{201D}: Claude asks where the prompt goes"
              && sa?.detail.contains("\u{201C}Press color\u{201D} started 2 hours ago. The question offers Send to and Keep here.") == true
              && sa?.detail.contains("Why: the same press color page.") == true
              && sa?.detail.contains("Prompt: \u{201C}Add a gray balance chart to the color page\u{201D}") == true,
              "the question: under the new session, the open session named, with its age, why and the prompt")
        let sg = same("cse_01AAAtest1 \"Press color\" got the first prompt of cse_01NEWtest3: the person chose Send to")
        check(sg?.kind == .same && sg?.session == "cse_01AAAtest1" && sg?.name == "Press color" && sg?.level == .info
              && sg?.text == "Got a new session's first prompt (Send to)"
              && sg?.detail.contains("From the new session \u{201C}Color page\u{201D}.") == true,
              "Send to: a row under the open session that got the prompt, with the new session named")
        let sq = same("cse_01AAAtest1 \"Press color\" gets the first prompt of cse_01NEWtest3 when its turn ends: the person chose Send to")
        let sw = same("cse_01AAAtest1 \"Press color\" got the first prompt of cse_01NEWtest3, which waited 12 minutes")
        check(sq?.text == "A new session's first prompt waits for the turn to end" && sq?.level == .info
              && sw?.text == "Got a new session's first prompt after its turn ended" && sw?.detail.first == "It waited 12 minutes.",
              "a session in a turn: the prompt waits, then goes, each a row")
        let sk = same("cse_01NEWtest3 keeps its first prompt here: the person chose Keep here, not \"Press color\"")
        check(sk?.session == "cse_01NEWtest3" && sk?.text == "The prompt stays here: Keep here, not \u{201C}Press color\u{201D}", "Keep here is a row")
        let sn1 = same("cse_01NEWtest3 no match among 3 open session(s) (1.6s) - a new topic | Order more ink")
        let sn2 = same("cse_01NEWtest3 no match: no other session is open on this Mac | Order more ink")
        let sn3 = same("cse_01NEWtest3 not checked: its first prompt is one word, too little to compare | hello")
        check(sn1?.routine == true && sn1?.text == "Same work check: no open session does this work"
              && sn1?.detail.contains("Compared with 3 open sessions.") == true && sn1?.detail.contains("Why: a new topic.") == true
              && sn2?.routine == true && sn2?.detail.first == "No other session is open on this Mac."
              && sn3?.routine == true && sn3?.text == "Same work check skipped", "a check that finds nothing is a routine row")
        let sf = same("cse_01NEWtest3 check failed: RuntimeError: exit 1: overloaded | Order more ink")
        let sl = same("cse_01AAAtest1 \"Press color\" could not start for the first prompt of cse_01NEWtest3: its copy in the server did not stop; the Kit tries again each minute")
        let sd = same("cse_01AAAtest1 \"Press color\" never got the first prompt of cse_01NEWtest3: it is in a turn; dropped after 7 days")
        let se = same("error: JSONDecodeError: Expecting value")
        check(sf?.kind == .problem && sf?.level == .warn && sl?.kind == .same && sl?.level == .warn
              && sl?.detail.first == "its copy in the server did not stop; the Kit tries again each minute"
              && sd?.kind == .problem && sd?.text == "A new session's first prompt never went" && se?.kind == .problem,
              "a check that failed, a start that failed and a prompt dropped are warnings")
        check(![sa, sg, sq, sw, sk, sn1, sf, sl, sd].contains { ($0?.text ?? "cse_").contains("cse_") }, "no ids in the sentences")

        // Reach me by's alerts off: what was kept in the Kit, the reminder and the Kit's own notice that did not show.
        // Each is a plain row, not a warning: alerts off is a choice. With alerts on and no way checked, a warning.
        let nk = Events.kitLine(f.string(from: Date()) + " notify Press color kept a1b2c3d4e5f6: alerts are off | PR #12 merged", names)
        check(nk?.name == "Press color" && nk?.session == "cse_01AAAtest1" && nk?.kind == .wait && nk?.level == .info
              && nk?.text == "Message kept in the Kit, not sent: PR #12 merged"
              && nk?.detail.first == "Not sent: alerts are off. It is on the session's panel on the Sessions page.",
              "a message kept in the Kit: its session, its subject, and why it was not sent")
        let nw = Events.kitLine(f.string(from: Date()) + " notify Press color kept a1b2c3d4e5f7: no way is checked under Reach me by | PR #12 merged", names)
        check(nw?.level == .warn && nw?.text == "Message kept in the Kit, not sent: PR #12 merged", "kept with no way checked is a warning")
        let rk = Events.kitLine(f.string(from: Date()) + " app    waiting notice skipped: Press color: alerts are off", names)
        check(rk?.name == "Press color" && rk?.session == "cse_01AAAtest1" && rk?.text == "No reminder: alerts are off" && rk?.level == .info,
              "a Needs you reminder that alerts off kept back")
        let ak = Events.kitLine(f.string(from: Date()) + " app    notice not shown, alerts are off: Sttark Claude Kit 1.300 didn't install | Click to try again.", names)
        check(ak?.kind == .app && ak?.level == .info && ak?.text == "Notice not shown, alerts are off: Sttark Claude Kit 1.300 didn't install"
              && ak?.detail == ["Click to try again."], "the Kit's own notice that alerts off kept back")
        let wk = Events.kitLine(f.string(from: Date()) + " wait   07f324 cse_01AAAtes \"Press color\" sent no message after coming back; the Kit kept one in the Kit app (alerts are off)", names)
        check(wk?.text == "It sent no message after coming back; the Kit kept one here", "the Kit's own message after a wait, kept")

        // Work the Kit waits for, or ends, when it would end a session's copy (effort-hook.py running_work(), wait.py)
        let now = f.string(from: Date())
        let kd = Events.kitLine(now + " work   defer cse_01AAAtest1 \"Press color\" bring-back waits: 1 agent (a1b2c3d4e5f6a7b8c \"Build the color page\"), 1 background command (b0c7bgbd8 \"Run the tests\"); it tries again each minute, at most 2 hours", names)
        check(kd?.name == "Press color" && kd?.session == "cse_01AAAtest1" && kd?.kind == .restart && kd?.level == .info
              && kd?.text == "Comes back when its work ends"
              && kd?.detail.first == "Still at work: 1 agent (\u{201C}Build the color page\u{201D}), 1 background command (\u{201C}Run the tests\u{201D}).",
              "a bring-back that waits for the session's work: its session, and what still runs, with no ids")
        let kk = Events.kitLine(now + " work   kill cse_01AAAtest1 \"Press color\" handover: 1 agent (a1b2c3d4e5f6a7b8c \"Build the color page\"), 1 Monitor (b9x15v33r \"CI checks on the pull request\"); the session is told at its next prompt", names)
        check(kk?.name == "Press color" && kk?.kind == .restart && kk?.level == .warn && kk?.text == "Work stopped: the server took it over"
              && kk?.detail.first == "Stopped: 1 agent (\u{201C}Build the color page\u{201D}), 1 Monitor (\u{201C}CI checks on the pull request\u{201D})."
              && kk?.detail.last?.contains("at its next prompt") == true,
              "work the Kit ended at a handover is a warning, with what stopped and when the session hears of it")
        let kh = Events.kitLine(now + " work   kill cse_01AAAtest1 \"Press color\" halt: 2 agents (a1 \"x\"); the session is told at its next prompt", names)
        let kb = Events.kitLine(now + " work   kill cse_01AAAtest1 \"Press color\" bring-back: 1 agent (a1b2c3d4e5f6a7b8c \"Build the color page\"); the session is told in the Kit's message", names)
        let ka = Events.kitLine(now + " work   kill cse_01AAAtest1 \"Press color\" archived: 1 agent (a1b2c3d4e5f6a7b8c \"Build the color page\"); the session is told at its next prompt", names)
        check(kh?.text == "Work stopped: the Mac shut down" && kb?.text == "Work stopped: brought back after 2 hours"
              && kb?.detail.last?.contains("The Kit's message") == true && ka?.text == "Work stopped: archived",
              "each reason the Kit ends work reads in plain words")
        let kt = Events.kitLine(now + " work   told cse_01AAAtest1 \"Press color\" what stopped at 10:41 AM (handover: 2 item(s)), with its next prompt", names)
        check(kt?.name == "Press color" && kt?.text == "Told the session what work stopped" && kt?.level == .info, "the session told is a row of its own")
        let kn = Events.kitLine(now + " work   done cse_01AAAtest1 \"Press color\" bring-back waited 12 min; its work ended", names)
        check(kn?.routine == true, "the end of a wait for the work is a routine row")
        check(![kd, kk, kh, kb, ka, kt, kn].contains { ($0?.text ?? "").contains("cse_") || ($0?.detail ?? []).joined().contains("a1b2c3d4e5f6a7b8c") },
              "no session, agent or command id in the rows")

        // A handover that waits for the Kit's copy, and a prompt the Kit typed in (effort-hook.py keep(), wait.py redeliver())
        let hw = Events.kitLine(now + " handover cse_01AAAtest1 \"Press color\" waits: the server runs it now, but the Kit's copy still works (its turn runs; it has not answered the prompt the Kit typed in at 1:16 PM; 1 agent (a1b2c3d4e5f6a7b8c \"Build the color page\")); the Kit waits while the server's copy may still fail, 30 seconds at most", names)
        check(hw?.name == "Press color" && hw?.kind == .restart && hw?.level == .info
              && hw?.text == "The server runs it again, but the Kit's copy still works, so the Kit waits to close it"
              && hw?.detail.first == "Still at work: its turn runs; it has not answered the prompt the Kit typed in at 1:16 PM; 1 agent (\u{201C}Build the color page\u{201D}).",
              "a handover that waits: what still works in the Kit's copy, with no ids")
        let hd = Events.kitLine(now + " handover cse_01AAAtest1 \"Press color\" the server runs it now; quit its own copy (kit-a0b1c2d3) after it waited 31 seconds", names)
        check(hd?.text == "The server runs it again, so the Kit closed its own copy" && hd?.detail == ["It waited 31 seconds first, as the server's copy can fail as it starts."],
              "a handover after the wait says how long it waited")
        let hs = Events.kitLine(now + " standdown cse_01AAAtest1 \"Press color\" its own copy was taken over elsewhere (code 4090); quit its own copy (kit-a0b1c2d3)", names)
        check(hs?.text == "Taken over in another place, so the Kit closed its own copy" && hs?.level == .warn, "a stand-down closes the Kit's copy at once")
        let pl = Events.kitLine(now + " prompt lost   cse_01AAAtest1 \"Press color\" the copy that received the prompt the Kit typed in at 1:16 PM (same work) ended before it answered: this Mac's server took control of the session; the Kit types it in again | Why does the order page show no totals?", names)
        check(pl?.name == "Press color" && pl?.kind == .same && pl?.level == .warn && pl?.text == "The copy that received a prompt ended before it answered"
              && pl?.detail == ["Why: this Mac's server took control of the session.", "The Kit typed it in at 1:16 PM, for a prompt you sent here from another session (Send to).",
                                "The Kit types it in again in the copy that runs the session next.", "Prompt: \u{201C}Why does the order page show no totals?\u{201D}"],
              "a lost prompt: why, when, where it came from, that it goes again, and its words")
        let pa = Events.kitLine(now + " prompt again  cse_01AAAtest1 \"Press color\" typed in again the prompt from 1:16 PM (same work), try 2 of 3 | Why does the order page show no totals?", names)
        check(pa?.text == "Typed a prompt in again" && pa?.detail.first == "It first went in at 1:16 PM, for a prompt you sent here from another session (Send to), and had no answer. This was try 2 of 3.",
              "a prompt typed in again")
        let pi = Events.kitLine(now + " prompt in     cse_01AAAtest1 \"Press color\" answered the prompt the Kit typed in at 1:19 PM (same work), try 2 of 3", names)
        let p1 = Events.kitLine(now + " prompt in     cse_01AAAtest1 \"Press color\" answered the prompt the Kit typed in at 1:16 PM (a wait)", names)
        check(pi?.text == "Answered the prompt the Kit typed in again" && pi?.routine == false && p1?.routine == true && p1?.kind == .wait
              && p1?.text == "Answered the prompt the Kit typed in", "an answered prompt: a routine row, unless it went again")
        let pw = Events.kitLine(now + " prompt waits  cse_01AAAtest1 \"Press color\" the prompt the Kit typed in at 1:16 PM (new messages) goes again when its turn ends", names)
        check(pw?.text == "A prompt waits to go in again" && pw?.detail == ["It goes when the session's turn ends."] && pw?.kind == .wait, "a prompt that waits for the turn")
        let pf = Events.kitLine(now + " prompt failed cse_01AAAtest1 \"Press color\" the prompt the Kit typed in at 1:16 PM (same work) did not go in: the session did not answer it after 3 tries (this Mac's server took control of the session); the Kit sent you a message with its text | Why does the order page show no totals?", names)
        check(pf?.kind == .problem && pf?.level == .error && pf?.text == "A prompt did not go in"
              && pf?.detail.first == "Why: the session did not answer it after 3 tries (this Mac's server took control of the session)."
              && pf?.detail.contains("The Kit sent you a message with its text. Send it again in the session if you still need it.") == true,
              "a prompt that did not go in is a problem, with why and what the Kit sent")
        let eh = Events.kitLine(now + " keep   cse_01AAAtest1 xhigh (2.0s) max - not set now: the Kit's copy has not answered the prompt the Kit typed in. A change now makes this Mac's server take control of the session | <task-notification>", names)
        check(eh?.text == "Effort stays at Extra" && eh?.detail == ["It needs Max, but the Kit did not set it now. The Kit's copy has not answered the prompt the Kit typed in. A change now makes this Mac's server take control of the session."],
              "an effort change not sent while the Kit's copy answers a prompt it typed in")
        check(![hw, hd, hs, pl, pa, pi, pw, pf].contains { ($0?.text ?? "").contains("cse_") || ($0?.detail ?? []).joined().contains("cse_") },
              "no session id in the new rows")

        print(failed == 0 ? "all passed" : "\(failed) failed")
        exit(failed == 0 ? 0 : 1)
    }
}
